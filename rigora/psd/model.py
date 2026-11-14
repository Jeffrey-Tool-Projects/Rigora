"""Decoded PSD layer records, without raster-editor state or operations."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from rigora.psd.format import _BLEND_MODE_TO_PSD

LAYER_BLEND_MODES = tuple(_BLEND_MODE_TO_PSD)


@dataclass
class PsdLayer:
    name: str
    image: np.ndarray
    opacity: float = 1.0
    blend_mode: str = "normal"
    visible: bool = True
    lock_alpha: bool = False
    group: str | None = None
    """Key of the innermost enclosing group; ``None`` for top-level layers."""
    group_path: tuple[str, ...] = ()
    """Enclosing group keys from outermost to innermost."""
    source_blend_key: str = "norm"
    """Blend key as stored; kept when ``blend_mode`` falls back to normal."""
    clipping: bool = False
    """Clipped to the layer below it (a Photoshop clipping mask)."""
    has_mask: bool = False
    """A raster or vector layer mask was present; ``image`` does not apply it."""
    fill_opacity: float = 1.0
    """Photoshop fill opacity (``iOpa``); ``image`` does not apply it."""
    info_keys: tuple[str, ...] = ()
    """Additional-information block keys on the record, in file order."""
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    """Stored ``(top, left, bottom, right)``; may overhang the canvas."""

    def __post_init__(self) -> None:
        if self.image.ndim != 3 or self.image.shape[2] != 4 or self.image.dtype != np.uint8:
            raise ValueError("PSD layer image must be HxWx4 uint8 RGBA")
        if self.blend_mode not in LAYER_BLEND_MODES:
            raise ValueError(f"unsupported PSD blend mode {self.blend_mode!r}")
        self.opacity = max(0.0, min(1.0, float(self.opacity)))
        self.fill_opacity = max(0.0, min(1.0, float(self.fill_opacity)))


@dataclass
class PsdGroup:
    name: str
    visible: bool = True
    opacity: float = 1.0
    blend_mode: str = "pass_through"
    expanded: bool = True
    parent: str | None = None
    """Key of the enclosing group, or ``None`` at the top level."""
    source_name: str | None = None
    """Original name when a repeated group name received a unique key."""
    source_blend_key: str = "pass"
    """Blend key as stored; kept when ``blend_mode`` falls back."""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("PSD group name must be non-empty")
        if self.blend_mode not in ("pass_through", *LAYER_BLEND_MODES):
            raise ValueError(f"unsupported PSD group blend mode {self.blend_mode!r}")
        self.opacity = max(0.0, min(1.0, float(self.opacity)))


@dataclass
class PsdEmptyRecord:
    """A layer record without pixel bounds, such as an adjustment layer."""

    name: str
    visible: bool = True
    info_keys: tuple[str, ...] = ()
    group: str | None = None
    group_path: tuple[str, ...] = ()


@dataclass
class PsdDocument:
    size: tuple[int, int]
    layer_stack: list[PsdLayer]
    groups: dict[str, PsdGroup] = field(default_factory=dict)
    empty_records: list[PsdEmptyRecord] = field(default_factory=list)
    """Records the reader could not turn into layers; kept so imports can report them."""

    @property
    def shape(self) -> tuple[int, int]:
        width, height = self.size
        return height, width

    def layers(self) -> list[PsdLayer]:
        return self.layer_stack
