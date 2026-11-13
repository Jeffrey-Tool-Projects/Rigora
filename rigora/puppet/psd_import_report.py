"""What a PSD import will produce, and what it cannot carry over.

Qt-free records shared by the import preview dialog, the asset-update
planner and machine callers. ``differences`` names every PSD feature the
puppet cannot reproduce exactly, so a successful import never hides a loss.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from rigora.psd.model import PsdEmptyRecord, PsdLayer
from rigora.puppet.import_report import (
    SEVERITY_INFO,
    SEVERITY_WARNING,
    ImportDifference,
)

STATUS_IMPORT = "import"
STATUS_HIDDEN = "hidden"
STATUS_EMPTY = "empty"
STATUS_CLIP_BASE_MISSING = "clip_base_missing"

# PSD blend keys with an exact puppet equivalent.
PUPPET_BLEND_FOR_KEY: dict[str, str] = {
    "norm": "normal",
    "mul ": "multiply",
    "lddg": "additive",
}


def puppet_blend(layer: PsdLayer) -> str:
    """Puppet blend mode for ``layer``; normal when there is no equivalent."""
    return PUPPET_BLEND_FOR_KEY.get(layer.source_blend_key, "normal")

_EFFECT_KEYS = frozenset({"lfx2", "lrFX", "lmfx"})
_SMART_OBJECT_KEYS = frozenset({"SoLd", "PlLd", "plLd", "SoLE"})
_TEXT_KEYS = frozenset({"TySh", "tySh"})
_FILL_KEYS = frozenset({"SoCo", "GdFl", "PtFl"})
_ADJUSTMENT_KEYS = frozenset({
    "levl", "curv", "brit", "blnc", "hue2", "hue ", "selc", "mixr", "grdm",
    "phfl", "expA", "vibA", "thrs", "post", "nvrt", "CgEd", "blwh", "clrL",
})


@dataclass(frozen=True)
class LayerPreview:
    """One PSD layer record and the drawable it becomes, if any."""

    index: int
    name: str
    group_path: tuple[str, ...]
    status: str
    drawable_id: str | None
    texture: str | None
    bounds: tuple[int, int, int, int] | None
    """Alpha bounding box ``(x0, y0, x1, y1)`` in canvas pixels, exclusive end."""
    opacity: float
    source_blend_mode: str
    blend_mode: str | None
    clipping: bool
    clip_mask: str | None
    has_mask: bool
    visible: bool

    @property
    def size(self) -> tuple[int, int] | None:
        if self.bounds is None:
            return None
        x0, y0, x1, y1 = self.bounds
        return x1 - x0, y1 - y0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["size"] = list(self.size) if self.size else None
        return data


@dataclass(frozen=True)
class GroupPreview:
    """One PSD layer group and the part it becomes, if any."""

    key: str
    part_id: str | None
    parent: str | None
    visible: bool
    opacity: float
    blend_mode: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PsdImportPreview:
    """Everything a PSD import would create, before touching any document."""

    source: str
    canvas_size: tuple[int, int]
    layers: tuple[LayerPreview, ...]
    groups: tuple[GroupPreview, ...]
    differences: tuple[ImportDifference, ...]

    @property
    def imported_layers(self) -> tuple[LayerPreview, ...]:
        return tuple(layer for layer in self.layers if layer.status == STATUS_IMPORT)

    @property
    def warnings(self) -> tuple[ImportDifference, ...]:
        return tuple(d for d in self.differences if d.severity == SEVERITY_WARNING)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "canvas_size": list(self.canvas_size),
            "drawable_count": len(self.imported_layers),
            "layers": [layer.to_dict() for layer in self.layers],
            "groups": [group.to_dict() for group in self.groups],
            "differences": [diff.to_dict() for diff in self.differences],
        }


def layer_differences(
    layer: PsdLayer, *, canvas_size: tuple[int, int], drawable_id: str | None,
) -> list[ImportDifference]:
    """Differences caused by one imported layer record's own attributes."""
    name = layer.name
    found: list[ImportDifference] = []
    if layer.source_blend_key not in PUPPET_BLEND_FOR_KEY:
        found.append(ImportDifference(
            "blend_mode_approximated", name,
            f"PSD blend '{layer.source_blend_key.strip()}' has no puppet equivalent; "
            "drawn with normal blending"))
    if layer.has_mask:
        found.append(ImportDifference(
            "layer_mask_ignored", name,
            "layer mask is not applied; pixels it hides in the PSD will show"))
    if layer.fill_opacity < 1.0:
        found.append(ImportDifference(
            "fill_opacity_ignored", name,
            f"fill opacity {layer.fill_opacity:.0%} is not applied; only layer opacity is"))
    found.extend(_info_key_differences(layer))
    found.extend(_geometry_differences(layer, canvas_size, drawable_id))
    return found


def _info_key_differences(layer: PsdLayer) -> list[ImportDifference]:
    keys = set(layer.info_keys)
    name = layer.name
    found: list[ImportDifference] = []
    if keys & _EFFECT_KEYS:
        found.append(ImportDifference(
            "layer_effects_ignored", name,
            "layer effects (shadow, stroke, glow…) are not rendered"))
    if keys & _SMART_OBJECT_KEYS:
        found.append(ImportDifference(
            "smart_object_rasterized", name,
            "smart object imported from its stored raster; source link is not kept",
            SEVERITY_INFO))
    if keys & _TEXT_KEYS:
        found.append(ImportDifference(
            "text_rasterized", name, "text layer imported as pixels; text is not editable",
            SEVERITY_INFO))
    if keys & _FILL_KEYS:
        found.append(ImportDifference(
            "fill_layer_rasterized", name,
            "fill layer imported from its stored raster; the fill setting is not kept",
            SEVERITY_INFO))
    return found


def _geometry_differences(
    layer: PsdLayer, canvas_size: tuple[int, int], drawable_id: str | None,
) -> list[ImportDifference]:
    found: list[ImportDifference] = []
    top, left, bottom, right = layer.bounds
    width, height = canvas_size
    if top < 0 or left < 0 or bottom > height or right > width:
        found.append(ImportDifference(
            "canvas_overhang_clipped", layer.name,
            "pixels outside the canvas are cropped", SEVERITY_INFO))
    if drawable_id is not None and drawable_id != layer.name:
        found.append(ImportDifference(
            "drawable_id_changed", layer.name,
            f"stored as drawable '{drawable_id}' (ids allow A-Z, a-z, 0-9, '_' and '-', "
            "and must be unique)", SEVERITY_INFO))
    return found


def skipped_layer_difference(
    layer: PsdLayer | PsdEmptyRecord, status: str,
) -> ImportDifference | None:
    """Difference for a layer record that will not become a drawable."""
    keys = set(layer.info_keys)
    if keys & _ADJUSTMENT_KEYS:
        return ImportDifference(
            "adjustment_layer_ignored", layer.name,
            "adjustment layer is not applied to the layers below it")
    if status == STATUS_HIDDEN:
        return ImportDifference(
            "hidden_layer_skipped", layer.name, "hidden layer is not imported", SEVERITY_INFO)
    if status == STATUS_EMPTY:
        return ImportDifference(
            "empty_layer_skipped", layer.name, "layer has no visible pixels", SEVERITY_INFO)
    if status == STATUS_CLIP_BASE_MISSING:
        return ImportDifference(
            "clipping_base_missing", layer.name,
            "clipped to a hidden or empty base layer, so it is not imported", SEVERITY_INFO)
    return None
