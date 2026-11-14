"""PSD multi-layer → ``PuppetDocument`` import.

Live2D's authoring workflow is "draw the character in Photoshop with
each part on its own layer, drop into Cubism Editor, every layer
becomes an ArtMesh." This module is the puppet plugin's equivalent:
each visible layer in the PSD turns into one cropped :class:`Drawable`
positioned at its alpha bounding box.

Importing is two steps. :func:`plan_psd_import` decodes the file once and
builds a :class:`PsdImportPreview` — layer names, sizes, order, opacity,
blend, masks, groups and every difference the puppet cannot reproduce.
:meth:`PsdImportPlan.build` then creates the document from the same decoded
pixels, so a preview and the import it approves cannot disagree.

Keeps the texture map tight by cropping each layer to its alpha bbox — a 4k
canvas with eight tiny eye-shaped layers becomes eight tiny PNGs.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np

from rigora.psd.model import PsdDocument, PsdLayer
from rigora.psd.reader import load_psd
from rigora.puppet.auto_rig import auto_rig
from rigora.puppet.document import Drawable, Part, PuppetDocument
from rigora.puppet.psd_import_report import (
    SEVERITY_INFO,
    STATUS_CLIP_BASE_MISSING,
    STATUS_EMPTY,
    STATUS_HIDDEN,
    STATUS_IMPORT,
    GroupPreview,
    ImportDifference,
    LayerPreview,
    PsdImportPreview,
    layer_differences,
    puppet_blend,
    skipped_layer_difference,
)
from rigora.puppet.standard_params import standard_parameters

_TEXTURE_PREFIX: str = "textures/"

__all__ = [
    "PsdImportPlan", "PsdImportPreview", "alpha_bbox", "crop_to_png_bytes",
    "plan_psd_import", "preview_psd", "puppet_from_psd",
]


def plan_psd_import(path: str | Path) -> PsdImportPlan:
    """Decode ``path`` and describe the import without building a document.

    Raises :class:`FileNotFoundError` when the file is missing and
    :class:`ValueError` for an unreadable PSD or one with no usable layer.
    """
    psd_doc = load_psd(path)
    if not psd_doc.layers():
        raise ValueError(f"PSD {path} has no layers")
    return PsdImportPlan(str(path), psd_doc)


def preview_psd(path: str | Path) -> PsdImportPreview:
    """The :class:`PsdImportPreview` for ``path``; see :func:`plan_psd_import`."""
    return plan_psd_import(path).preview


def puppet_from_psd(
    path: str | Path,
    *,
    seed_standard_parameters: bool = True,
    enable_auto_rig: bool = True,
) -> PuppetDocument:
    """Load ``path`` as a PSD and build a multi-drawable
    :class:`PuppetDocument`.

    Hidden layers and layers whose alpha is fully zero are skipped.
    Layer order in the PSD becomes ``draw_order`` on the drawables —
    the bottom of the layer stack is drawn first (behind), the top
    drawn last (in front), matching Live2D's convention.

    Raises :class:`FileNotFoundError` when the file is missing,
    :class:`ValueError` when the PSD has no usable layer.
    """
    return plan_psd_import(path).build(
        seed_standard_parameters=seed_standard_parameters,
        enable_auto_rig=enable_auto_rig,
    )


class PsdImportPlan:
    """A decoded PSD plus the preview of what importing it will create."""

    def __init__(self, source: str, psd_doc: PsdDocument) -> None:
        self.source = source
        self.psd = psd_doc
        width, height = psd_doc.size
        self.canvas_size = (width, height)
        self._layers = psd_doc.layers()
        self._bboxes = [alpha_bbox(layer.image) for layer in self._layers]
        self.preview = self._build_preview()

    # ---- preview ---------------------------------------------------------

    def _build_preview(self) -> PsdImportPreview:
        statuses = self._statuses()
        drawable_ids = self._drawable_ids(statuses)
        differences: list[ImportDifference] = []
        previews: list[LayerPreview] = []
        base_ids = self._clip_bases(statuses, drawable_ids)
        for index, layer in enumerate(self._layers):
            status = statuses[index]
            drawable_id = drawable_ids.get(index)
            preview = self._layer_preview(index, layer, status, drawable_id, base_ids.get(index))
            previews.append(preview)
            if status != STATUS_IMPORT:
                skipped = skipped_layer_difference(layer, status)
                if skipped is not None:
                    differences.append(skipped)
                continue
            differences.extend(layer_differences(
                layer, canvas_size=self.canvas_size, drawable_id=drawable_id))
            if preview.clip_mask is not None:
                differences.append(ImportDifference(
                    "clipping_approximated", layer.name,
                    f"clipped to the mesh of '{preview.clip_mask}' (its alpha bounding box), "
                    "not to its exact pixels"))
        for record in self.psd.empty_records:
            skipped = skipped_layer_difference(
                record, STATUS_EMPTY if record.visible else STATUS_HIDDEN)
            if skipped is not None:
                differences.append(skipped)
        groups = self._group_previews(previews)
        differences.extend(self._group_differences(groups))
        if not any(p.status == STATUS_IMPORT for p in previews):
            raise ValueError(f"PSD {self.source} had no visible non-empty layers")
        return PsdImportPreview(
            source=self.source, canvas_size=self.canvas_size, layers=tuple(previews),
            groups=tuple(groups), differences=tuple(differences),
        )

    def _statuses(self) -> list[str]:
        statuses: list[str] = []
        for index, layer in enumerate(self._layers):
            if not layer.visible:
                statuses.append(STATUS_HIDDEN)
            elif self._bboxes[index] is None:
                statuses.append(STATUS_EMPTY)
            else:
                statuses.append(STATUS_IMPORT)
        # A clipped layer follows its base: Photoshop hides it with the base.
        for index, layer in enumerate(self._layers):
            base = self._clip_base_index(index)
            if layer.clipping and statuses[index] == STATUS_IMPORT and (
                base is None or statuses[base] != STATUS_IMPORT
            ):
                statuses[index] = STATUS_CLIP_BASE_MISSING
        return statuses

    def _clip_base_index(self, index: int) -> int | None:
        """Nearest non-clipping layer below ``index`` in the same group."""
        layer = self._layers[index]
        for lower in range(index - 1, -1, -1):
            candidate = self._layers[lower]
            if candidate.group_path != layer.group_path:
                return None
            if not candidate.clipping:
                return lower
        return None

    def _drawable_ids(self, statuses: list[str]) -> dict[int, str]:
        used: set[str] = set()
        return {
            index: _unique(_sanitize_id(layer.name), used)
            for index, layer in enumerate(self._layers)
            if statuses[index] == STATUS_IMPORT
        }

    def _clip_bases(self, statuses: list[str], ids: dict[int, str]) -> dict[int, str]:
        bases: dict[int, str] = {}
        for index, layer in enumerate(self._layers):
            if not layer.clipping or statuses[index] != STATUS_IMPORT:
                continue
            base = self._clip_base_index(index)
            if base is not None and base in ids:
                bases[index] = ids[base]
        return bases

    def _layer_preview(
        self, index: int, layer: PsdLayer, status: str, drawable_id: str | None,
        clip_mask: str | None,
    ) -> LayerPreview:
        imported = status == STATUS_IMPORT
        return LayerPreview(
            index=index, name=layer.name, group_path=layer.group_path, status=status,
            drawable_id=drawable_id,
            texture=f"{_TEXTURE_PREFIX}{drawable_id}.png" if drawable_id else None,
            bounds=self._bboxes[index], opacity=layer.opacity,
            source_blend_mode=_source_blend_label(layer),
            blend_mode=puppet_blend(layer) if imported else None,
            clipping=layer.clipping, clip_mask=clip_mask, has_mask=layer.has_mask,
            visible=layer.visible,
        )

    def _group_previews(self, layers: list[LayerPreview]) -> list[GroupPreview]:
        with_content: set[str] = set()
        for layer in layers:
            if layer.status == STATUS_IMPORT:
                with_content.update(layer.group_path)
        used: set[str] = set()
        previews = []
        for key, group in self.psd.groups.items():
            label = group.source_name or key
            part_id = _unique(_sanitize_id(label), used) if key in with_content else None
            previews.append(GroupPreview(
                key=key, part_id=part_id, parent=group.parent, visible=group.visible,
                opacity=group.opacity, blend_mode=group.blend_mode,
            ))
        return previews

    def _group_differences(self, groups: list[GroupPreview]) -> list[ImportDifference]:
        found: list[ImportDifference] = []
        for preview in groups:
            group = self.psd.groups[preview.key]
            if group.source_name is not None:
                found.append(ImportDifference(
                    "duplicate_group_name", group.source_name,
                    f"another group has the same name; this one is listed as '{preview.key}'",
                    SEVERITY_INFO))
            if preview.part_id is None:
                continue
            if group.blend_mode not in ("pass_through", "normal"):
                found.append(ImportDifference(
                    "group_blend_ignored", preview.key,
                    f"group blend '{group.blend_mode}' is not applied; members keep their own"))
            if not group.visible:
                found.append(ImportDifference(
                    "group_hidden", preview.key,
                    f"hidden group becomes hidden part '{preview.part_id}'", SEVERITY_INFO))
        return found

    # ---- build -----------------------------------------------------------

    def layer_image(self, index: int) -> np.ndarray:
        """Full-canvas RGBA pixels of layer ``index`` (bottom of stack is 0)."""
        return self._layers[index].image

    def build(
        self, *, seed_standard_parameters: bool = True, enable_auto_rig: bool = True,
    ) -> PuppetDocument:
        """Create the document the preview describes."""
        doc = PuppetDocument(size=self.canvas_size)
        for preview in self.preview.imported_layers:
            layer = self._layers[preview.index]
            doc.drawables.append(_drawable_from_preview(preview, layer))
            doc.textures[preview.texture] = crop_to_png_bytes(layer.image, preview.bounds)
        doc.parts = _build_parts(self.preview)
        if seed_standard_parameters:
            doc.parameters = standard_parameters()
        if enable_auto_rig:
            auto_rig(doc)
        return doc


def _source_blend_label(layer: PsdLayer) -> str:
    """Readable PSD blend name; the raw key when the reader has no name for it."""
    if layer.blend_mode == "normal" and layer.source_blend_key != "norm":
        return layer.source_blend_key.strip()
    return layer.blend_mode


def _drawable_from_preview(preview: LayerPreview, layer: PsdLayer) -> Drawable:
    x0, y0, x1, y1 = preview.bounds
    return Drawable(
        id=preview.drawable_id,
        texture=preview.texture,
        vertices=[
            (float(x0), float(y0)),
            (float(x1), float(y0)),
            (float(x1), float(y1)),
            (float(x0), float(y1)),
        ],
        indices=[0, 1, 2, 0, 2, 3],
        uvs=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        draw_order=preview.index,
        blend_mode=preview.blend_mode,
        clip_mask=preview.clip_mask,
        opacity=float(layer.opacity),
    )


def _build_parts(preview: PsdImportPreview) -> list[Part]:
    """Each PSD group holding an imported layer becomes a Part. Nested groups
    become child parts; a group's visibility and opacity cascade through the
    part tree the way they do in the PSD."""
    part_ids = {group.key: group.part_id for group in preview.groups if group.part_id}
    parts: dict[str, Part] = {}
    for group in preview.groups:
        if group.part_id:
            parts[group.key] = Part(
                id=group.part_id, visible=group.visible, opacity=group.opacity)
    for layer in preview.imported_layers:
        if layer.group_path and layer.group_path[-1] in parts:
            parts[layer.group_path[-1]].drawables.append(layer.drawable_id)
    for group in preview.groups:
        if group.key in parts and group.parent in parts:
            parts[group.parent].children.append(part_ids[group.key])
    return list(parts.values())


# ---------------------------------------------------------------------------
# Pixel helpers
# ---------------------------------------------------------------------------


def alpha_bbox(image: np.ndarray) -> tuple[int, int, int, int] | None:
    """Return ``(x0, y0, x1, y1)`` of the smallest box covering all
    pixels where ``alpha > 0``, or ``None`` for fully transparent
    images. ``x1`` / ``y1`` are exclusive so the slice
    ``image[y0:y1, x0:x1]`` returns exactly the cropped region."""
    if image.ndim != 3 or image.shape[2] != 4:
        return None
    alpha = image[..., 3]
    rows = np.any(alpha > 0, axis=1)
    cols = np.any(alpha > 0, axis=0)
    if not rows.any() or not cols.any():
        return None
    y0 = int(np.argmax(rows))
    y1 = int(len(rows) - np.argmax(rows[::-1]))
    x0 = int(np.argmax(cols))
    x1 = int(len(cols) - np.argmax(cols[::-1]))
    return x0, y0, x1, y1


def crop_to_png_bytes(image: np.ndarray, bbox: tuple[int, int, int, int]) -> bytes:
    """PNG bytes of ``image[y0:y1, x0:x1]``."""
    from PIL import Image
    x0, y0, x1, y1 = bbox
    crop = np.ascontiguousarray(image[y0:y1, x0:x1])
    buf = io.BytesIO()
    Image.fromarray(crop, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


def _sanitize_id(name: str) -> str:
    """Map a PSD layer name to a safe drawable id. Strips characters
    that would confuse the manifest / texture-path layer (slashes,
    quotes, etc.) and falls back to ``layer`` when everything was
    stripped. PSDs let users name layers ``私の/絵🎨`` — we keep the
    intent without crashing the schema."""
    safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", name).strip("_")
    return safe or "layer"


def _unique(candidate: str, used: set[str]) -> str:
    """Suffix ``candidate`` with ``_2``, ``_3`` … until it's not in
    ``used``, then record the result."""
    if candidate not in used:
        used.add(candidate)
        return candidate
    i = 2
    while True:
        alt = f"{candidate}_{i}"
        if alt not in used:
            used.add(alt)
            return alt
        i += 1
