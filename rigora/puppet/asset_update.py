"""Update a rig's artwork from a re-exported PSD without losing the rig.

Drawables are matched to source layers by their stable id — the same
sanitised, de-duplicated layer name the PSD import assigned — or by an
explicit mapping for renamed layers. Each change is planned before the
document is touched:

``update``
    Keep the mesh, bone weights, morphs and every reference; replace only
    the pixels inside the texture's canvas rectangle. New art that reaches
    past that rectangle is reported, because the mesh cannot show it.
``rebuild``
    Replace the mesh with a quad around the new art, as a fresh import
    would. Bone weights and vertex morphs of that drawable are dropped and
    listed; deformer, part, mask and hit-area references keep working.
``add`` / ``skip`` / ``keep`` / ``hide``
    Add a new layer, leave a change out, or keep / hide a drawable that is
    no longer in the source.

The texture rectangle is recovered from the drawable's UVs and rest
vertices. A drawable whose UVs are not a scale-and-offset of its vertices
(a hand-edited or atlas mapping) cannot be updated in place and offers
``rebuild`` or ``skip`` instead. Missing or unreadable textures can be
located on disk and relinked separately.
"""
from __future__ import annotations

import io
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from rigora.puppet.document import Drawable, PuppetDocument
from rigora.puppet.psd_import import PsdImportPlan, crop_to_png_bytes
from rigora.puppet.psd_import_report import LayerPreview

ACTION_UPDATE = "update"
ACTION_REBUILD = "rebuild"
ACTION_ADD = "add"
ACTION_SKIP = "skip"
ACTION_KEEP = "keep"
ACTION_HIDE = "hide"

KIND_CHANGED = "changed"
KIND_UNCHANGED = "unchanged"
KIND_NEW = "new"
KIND_NOT_IN_SOURCE = "not_in_source"

_ALIGN_TOLERANCE_PX = 0.5
_RENAME_OVERLAP = 0.5

Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class AssetChange:
    """One drawable or source layer and what the update would do to it."""

    drawable_id: str | None
    source_id: str | None
    """Drawable id the source layer would receive on a fresh import."""
    layer_name: str | None
    kind: str
    texture_rect: Rect | None
    """Canvas rectangle the current texture covers, ``(x0, y0, x1, y1)``."""
    new_bounds: tuple[int, int, int, int] | None
    conflicts: tuple[str, ...]
    actions: tuple[str, ...]
    default_action: str

    @property
    def key(self) -> str:
        return self.drawable_id or f"+{self.source_id}"

    def to_dict(self) -> dict:
        return asdict(self) | {"key": self.key}


@dataclass
class AssetUpdatePlan:
    source: str
    canvas_size: tuple[int, int]
    changes: list[AssetChange]
    blocking: list[str] = field(default_factory=list)
    _plan: PsdImportPlan | None = field(default=None, repr=False)
    _geometry: dict[str, tuple[int, int]] = field(default_factory=dict, repr=False)

    def change(self, key: str) -> AssetChange:
        for change in self.changes:
            if change.key == key:
                return change
        raise KeyError(key)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "canvas_size": list(self.canvas_size),
            "blocking": list(self.blocking),
            "changes": [change.to_dict() for change in self.changes],
        }


@dataclass
class AssetUpdateResult:
    updated: list[str] = field(default_factory=list)
    rebuilt: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    dropped: dict[str, list[str]] = field(default_factory=dict)
    """Per rebuilt drawable, the rig data that could not be kept."""

    @property
    def changed(self) -> bool:
        return bool(self.updated or self.rebuilt or self.added or self.hidden)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Texture placement
# ---------------------------------------------------------------------------


def texture_rect(drawable: Drawable) -> Rect | None:
    """Canvas rectangle the texture is mapped onto, or ``None`` when the UVs
    are not an axis-aligned scale-and-offset of the rest vertices."""
    if len(drawable.vertices) < 2 or len(drawable.vertices) != len(drawable.uvs):
        return None
    xy = np.asarray(drawable.vertices, dtype=float)
    uv = np.asarray(drawable.uvs, dtype=float)
    rect = []
    for axis in (0, 1):
        coords, pos = uv[:, axis], xy[:, axis]
        if np.ptp(coords) < 1e-9:
            return None
        design = np.column_stack([coords, np.ones_like(coords)])
        (scale, offset), *_ = np.linalg.lstsq(design, pos, rcond=None)
        error = np.max(np.abs(design @ (scale, offset) - pos))
        if abs(scale) < 1e-9 or error > _ALIGN_TOLERANCE_PX:
            return None
        # Rounded so whole-pixel rectangles compare exactly after the fit.
        rect.append((round(float(offset), 6), round(float(offset + scale), 6)))
    (x0, x1), (y0, y1) = rect
    if x1 <= x0 or y1 <= y0:
        return None   # mirrored mapping; leave it to a rebuild
    return x0, y0, x1, y1


def _pixel_rect(rect: Rect) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    return (int(np.floor(x0 + 1e-6)), int(np.floor(y0 + 1e-6)),
            int(np.ceil(x1 - 1e-6)), int(np.ceil(y1 - 1e-6)))


def crop_canvas(image: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray:
    """``image[y0:y1, x0:x1]`` with transparent padding outside the canvas."""
    x0, y0, x1, y1 = rect
    out = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
    height, width = image.shape[:2]
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = image[sy0:sy1, sx0:sx1]
    return out


def decode_texture(data: bytes | None) -> np.ndarray | None:
    """RGBA pixels of a stored texture, or ``None`` when absent or unreadable."""
    if not data:
        return None
    from PIL import Image

    from rigora.system.image_errors import IMAGE_READ_ERRORS
    try:
        with Image.open(io.BytesIO(data)) as image:
            return np.asarray(image.convert("RGBA"))
    except IMAGE_READ_ERRORS:
        return None


def _png(pixels: np.ndarray) -> bytes:
    return crop_to_png_bytes(pixels, (0, 0, pixels.shape[1], pixels.shape[0]))


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_asset_update(
    document: PuppetDocument,
    plan: PsdImportPlan,
    *,
    mapping: dict[str, str] | None = None,
) -> AssetUpdatePlan:
    """Compare ``document`` with the PSD described by ``plan``.

    ``mapping`` pairs a document drawable id with a source id (the id a
    fresh import would give the layer) for layers that were renamed.
    """
    mapping = dict(mapping or {})
    result = AssetUpdatePlan(source=plan.source, canvas_size=plan.canvas_size, changes=[],
                             _plan=plan)
    if tuple(document.size) != tuple(plan.canvas_size):
        result.blocking.append(
            f"canvas is {plan.canvas_size[0]}×{plan.canvas_size[1]} in the PSD but "
            f"{document.size[0]}×{document.size[1]} in the puppet; resize one to match first")
    layers = {layer.drawable_id: layer for layer in plan.preview.imported_layers}
    unknown = [src for src in mapping.values() if src not in layers]
    if unknown:
        raise ValueError(f"mapping names unknown source layers: {', '.join(unknown)}")
    pairs = {d.id: layers.get(mapping.get(d.id, d.id)) for d in document.drawables}
    used_sources = {layer.drawable_id for layer in pairs.values() if layer is not None}
    shared = _shared_textures(document)
    for drawable in document.drawables:
        layer = pairs[drawable.id]
        result._geometry[drawable.id] = (len(drawable.vertices), len(drawable.indices))
        if layer is None:
            result.changes.append(_not_in_source(drawable))
        else:
            result.changes.append(_matched(document, drawable, layer, plan, shared))
    for layer in plan.preview.imported_layers:
        if layer.drawable_id not in used_sources:
            result.changes.append(_new_layer(document, layer))
    _flag_renames(result.changes)
    return result


def _shared_textures(document: PuppetDocument) -> set[str]:
    seen: dict[str, int] = {}
    for drawable in document.drawables:
        seen[drawable.texture] = seen.get(drawable.texture, 0) + 1
    return {texture for texture, count in seen.items() if count > 1}


def _matched(document, drawable, layer: LayerPreview, plan: PsdImportPlan,
             shared: set[str]) -> AssetChange:
    rect = texture_rect(drawable)
    conflicts: list[str] = []
    if rect is None:
        conflicts.append("unaligned_uvs")
    if drawable.texture in shared:
        conflicts.append("shared_texture")
    current = decode_texture(document.textures.get(drawable.texture))
    if current is None:
        conflicts.append("texture_missing")
    kind = KIND_CHANGED
    if rect is not None:
        pixel_rect = _pixel_rect(rect)
        x0, y0, x1, y1 = layer.bounds
        if x0 < pixel_rect[0] or y0 < pixel_rect[1] or x1 > pixel_rect[2] or y1 > pixel_rect[3]:
            conflicts.append("art_outside_mesh")
        fresh = crop_canvas(plan.layer_image(layer.index), pixel_rect)
        if current is not None and current.shape == fresh.shape and np.array_equal(current, fresh):
            kind = KIND_UNCHANGED
    in_place = rect is not None and "shared_texture" not in conflicts
    actions = ((ACTION_UPDATE,) if in_place else ()) + (ACTION_REBUILD, ACTION_SKIP)
    # Updating in place keeps the rig even when new art is cut off; a rebuild
    # is always the caller's explicit choice because it drops rig data.
    default = ACTION_UPDATE if in_place and kind == KIND_CHANGED else ACTION_SKIP
    return AssetChange(
        drawable_id=drawable.id, source_id=layer.drawable_id, layer_name=layer.name, kind=kind,
        texture_rect=rect, new_bounds=layer.bounds, conflicts=tuple(conflicts),
        actions=actions, default_action=default,
    )


def _not_in_source(drawable: Drawable) -> AssetChange:
    return AssetChange(
        drawable_id=drawable.id, source_id=None, layer_name=None, kind=KIND_NOT_IN_SOURCE,
        texture_rect=texture_rect(drawable), new_bounds=None, conflicts=(),
        actions=(ACTION_KEEP, ACTION_HIDE), default_action=ACTION_KEEP,
    )


def _new_layer(document: PuppetDocument, layer: LayerPreview) -> AssetChange:
    conflicts = ("id_taken",) if document.drawable(layer.drawable_id) else ()
    return AssetChange(
        drawable_id=None, source_id=layer.drawable_id, layer_name=layer.name, kind=KIND_NEW,
        texture_rect=None, new_bounds=layer.bounds, conflicts=conflicts,
        actions=(ACTION_ADD, ACTION_SKIP), default_action=ACTION_ADD,
    )


def _overlap(a: Rect, b: Rect) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _flag_renames(changes: list[AssetChange]) -> None:
    """Mark a vanished drawable and a new layer that occupy the same place:
    probably a renamed layer the caller should map instead."""
    gone = [c for c in changes if c.kind == KIND_NOT_IN_SOURCE and c.texture_rect]
    new = [c for c in changes if c.kind == KIND_NEW]
    for g in gone:
        for n in new:
            if _overlap(g.texture_rect, n.new_bounds) >= _RENAME_OVERLAP:
                for target in (g, n):
                    index = changes.index(target)
                    if "possible_rename" not in changes[index].conflicts:
                        changes[index] = _with_conflict(changes[index], "possible_rename")


def _with_conflict(change: AssetChange, code: str) -> AssetChange:
    data = asdict(change)
    data["conflicts"] = (*change.conflicts, code)
    if change.kind == KIND_NEW:
        # Adding a probable rename would duplicate the part; let the caller map it.
        data["default_action"] = ACTION_SKIP
    return AssetChange(**data)


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def apply_asset_update(
    document: PuppetDocument,
    update: AssetUpdatePlan,
    actions: dict[str, str] | None = None,
) -> AssetUpdateResult:
    """Apply ``update`` to ``document`` in place, using each change's default
    action unless ``actions`` (keyed by :attr:`AssetChange.key`) overrides it.

    Raises :class:`ValueError` before changing anything when the plan is
    blocked, an action is not offered for its change, or the document's
    drawables changed since the plan was made.
    """
    if update.blocking:
        raise ValueError("; ".join(update.blocking))
    chosen = _choose_actions(update, actions or {})
    _check_document_unchanged(document, update)
    plan = update._plan
    result = AssetUpdateResult()
    for change in update.changes:
        action = chosen[change.key]
        if action in (ACTION_SKIP, ACTION_KEEP):
            result.skipped.append(change.key)
        elif action == ACTION_HIDE:
            document.drawable(change.drawable_id).visible = False
            result.hidden.append(change.drawable_id)
        elif action == ACTION_UPDATE:
            _update_in_place(document, change, plan)
            result.updated.append(change.drawable_id)
        elif action == ACTION_REBUILD:
            result.dropped[change.drawable_id] = _rebuild(document, change, plan)
            result.rebuilt.append(change.drawable_id)
        else:
            result.added.append(_add(document, change, plan))
    return result


def _choose_actions(update: AssetUpdatePlan, actions: dict[str, str]) -> dict[str, str]:
    keys = {change.key for change in update.changes}
    unknown = set(actions) - keys
    if unknown:
        raise ValueError(f"no planned change for {', '.join(sorted(unknown))}")
    chosen = {}
    for change in update.changes:
        action = actions.get(change.key, change.default_action)
        if action not in change.actions:
            raise ValueError(f"{change.key}: '{action}' is not possible; "
                             f"choose one of {', '.join(change.actions)}")
        chosen[change.key] = action
    return chosen


def _check_document_unchanged(document: PuppetDocument, update: AssetUpdatePlan) -> None:
    current = {d.id: (len(d.vertices), len(d.indices)) for d in document.drawables}
    if current != update._geometry:
        raise ValueError("the puppet's drawables changed after the update was planned; "
                         "plan the update again")


def _update_in_place(document: PuppetDocument, change: AssetChange, plan: PsdImportPlan) -> None:
    drawable = document.drawable(change.drawable_id)
    layer = _source_layer(plan, change.source_id)
    old = change.texture_rect
    pixel_rect = _pixel_rect(old)
    document.textures[drawable.texture] = _png(
        crop_canvas(plan.layer_image(layer.index), pixel_rect))
    if pixel_rect != old:
        # Map the old UV rectangle onto the whole-pixel crop.
        px0, py0, px1, py1 = pixel_rect
        drawable.uvs = [
            ((old[0] + u * (old[2] - old[0]) - px0) / (px1 - px0),
             (old[1] + v * (old[3] - old[1]) - py0) / (py1 - py0))
            for u, v in drawable.uvs
        ]


def _quad(bounds: tuple[int, int, int, int]) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = (float(v) for v in bounds)
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _rebuild(document: PuppetDocument, change: AssetChange, plan: PsdImportPlan) -> list[str]:
    drawable = document.drawable(change.drawable_id)
    layer = _source_layer(plan, change.source_id)
    dropped = []
    if drawable.bone_weights:
        dropped.append("bone_weights")
    if drawable.vertex_morphs:
        dropped.append("vertex_morphs")
    texture = drawable.texture
    if "shared_texture" in change.conflicts or texture not in document.textures:
        texture = _free_texture_path(document, drawable.id)
    drawable.texture = texture
    drawable.vertices = _quad(layer.bounds)
    drawable.indices = [0, 1, 2, 0, 2, 3]
    drawable.uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    drawable.bone_weights = None
    drawable.vertex_morphs = None
    document.textures[texture] = crop_to_png_bytes(plan.layer_image(layer.index), layer.bounds)
    return dropped


def _add(document: PuppetDocument, change: AssetChange, plan: PsdImportPlan) -> str:
    layer = _source_layer(plan, change.source_id)
    used = {d.id for d in document.drawables}
    drawable_id = layer.drawable_id
    suffix = 2
    while drawable_id in used:
        drawable_id = f"{layer.drawable_id}_{suffix}"
        suffix += 1
    texture = _free_texture_path(document, drawable_id)
    order = _insert_order(document, plan, layer)
    document.drawables.append(Drawable(
        id=drawable_id, texture=texture, vertices=_quad(layer.bounds),
        indices=[0, 1, 2, 0, 2, 3], uvs=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        draw_order=order, blend_mode=layer.blend_mode, opacity=layer.opacity,
    ))
    document.textures[texture] = crop_to_png_bytes(plan.layer_image(layer.index), layer.bounds)
    part_ids = {g.key: g.part_id for g in plan.preview.groups}
    if layer.group_path:
        part = next((p for p in document.parts
                     if p.id == part_ids.get(layer.group_path[-1])), None)
        if part is not None:
            part.drawables.append(drawable_id)
    return drawable_id


def _insert_order(document: PuppetDocument, plan: PsdImportPlan, layer: LayerPreview) -> int:
    """Draw right above the nearest existing drawable below it in the PSD."""
    by_id = {d.id: d for d in document.drawables}
    below = [
        by_id[other.drawable_id].draw_order
        for other in plan.preview.imported_layers
        if other.index < layer.index and other.drawable_id in by_id
    ]
    order = below[-1] + 1 if below else min((d.draw_order for d in document.drawables), default=0)
    for drawable in document.drawables:
        if drawable.draw_order >= order:
            drawable.draw_order += 1
    return order


def _source_layer(plan: PsdImportPlan, source_id: str) -> LayerPreview:
    return next(layer for layer in plan.preview.imported_layers if layer.drawable_id == source_id)


def _free_texture_path(document: PuppetDocument, stem: str) -> str:
    candidate, suffix = f"textures/{stem}.png", 2
    taken = set(document.textures) | {d.texture for d in document.drawables}
    while candidate in taken:
        candidate = f"textures/{stem}_{suffix}.png"
        suffix += 1
    return candidate


# ---------------------------------------------------------------------------
# Missing textures and relinking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MissingTexture:
    texture: str
    drawables: tuple[str, ...]
    reason: str
    """``missing`` (not in the archive) or ``unreadable`` (not a decodable image)."""
    expected_size: tuple[int, int] | None

    def to_dict(self) -> dict:
        return asdict(self)


def find_missing_textures(document: PuppetDocument) -> list[MissingTexture]:
    """Textures referenced by drawables that are absent or cannot be decoded."""
    users: dict[str, list[Drawable]] = {}
    for drawable in document.drawables:
        users.setdefault(drawable.texture, []).append(drawable)
    found = []
    for texture, drawables in users.items():
        data = document.textures.get(texture)
        if data is None:
            reason = "missing"
        elif decode_texture(data) is None:
            reason = "unreadable"
        else:
            continue
        found.append(MissingTexture(
            texture=texture, drawables=tuple(d.id for d in drawables), reason=reason,
            expected_size=_expected_size(drawables)))
    return found


def _expected_size(drawables: list[Drawable]) -> tuple[int, int] | None:
    rect = texture_rect(drawables[0]) if len(drawables) == 1 else None
    if rect is None:
        return None
    x0, y0, x1, y1 = _pixel_rect(rect)
    return x1 - x0, y1 - y0


_IMAGE_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


def locate_textures(
    missing: Iterable[MissingTexture], search_dirs: Iterable[str | Path], *, limit: int = 5,
) -> dict[str, list[Path]]:
    """Candidate files for each missing texture: images under ``search_dirs``
    whose file name (or stem, for another image format) matches."""
    wanted = {m.texture: Path(m.texture).name.lower() for m in missing}
    stems = {texture: Path(name).stem for texture, name in wanted.items()}
    out: dict[str, list[Path]] = {texture: [] for texture in wanted}
    for directory in search_dirs:
        root = Path(directory)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in _IMAGE_SUFFIXES or not path.is_file():
                continue
            name = path.name.lower()
            for texture, target in wanted.items():
                matches = name == target or path.stem.lower() == stems[texture]
                if matches and len(out[texture]) < limit and path not in out[texture]:
                    out[texture].append(path)
    return out


@dataclass(frozen=True)
class RelinkPreview:
    texture: str
    drawables: tuple[str, ...]
    image_size: tuple[int, int]
    current_size: tuple[int, int] | None
    expected_size: tuple[int, int] | None
    notes: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _load_image(path: str | Path) -> np.ndarray:
    from PIL import Image

    from rigora.system.image_errors import IMAGE_READ_ERRORS
    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGBA"))
    except IMAGE_READ_ERRORS as exc:
        raise ValueError(f"{path} is not a readable image: {exc}") from exc


def preview_relink(document: PuppetDocument, texture: str, image_path: str | Path) -> RelinkPreview:
    """What relinking ``texture`` to ``image_path`` changes. The image is
    stretched over the existing UVs; size and aspect differences are noted."""
    drawables = [d for d in document.drawables if d.texture == texture]
    if not drawables:
        raise ValueError(f"no drawable uses texture {texture!r}")
    pixels = _load_image(image_path)
    size = (pixels.shape[1], pixels.shape[0])
    current = decode_texture(document.textures.get(texture))
    current_size = (current.shape[1], current.shape[0]) if current is not None else None
    expected = current_size or _expected_size(drawables)
    notes = []
    if expected and size != expected:
        notes.append("size_differs")
        if abs(size[0] / size[1] - expected[0] / expected[1]) > 0.01:
            notes.append("aspect_differs")
    if len(drawables) > 1:
        notes.append("shared_texture")
    return RelinkPreview(texture, tuple(d.id for d in drawables), size, current_size,
                         _expected_size(drawables), tuple(notes))


def relink_texture(document: PuppetDocument, texture: str, image_path: str | Path) -> RelinkPreview:
    """Store ``image_path`` as ``texture`` (re-encoded as PNG). UVs are kept."""
    preview = preview_relink(document, texture, image_path)
    document.textures[texture] = _png(_load_image(image_path))
    return preview
