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

    def __post_init__(self) -> None:
        if self.image.ndim != 3 or self.image.shape[2] != 4 or self.image.dtype != np.uint8:
            raise ValueError("PSD layer image must be HxWx4 uint8 RGBA")
        if self.blend_mode not in LAYER_BLEND_MODES:
            raise ValueError(f"unsupported PSD blend mode {self.blend_mode!r}")
        self.opacity = max(0.0, min(1.0, float(self.opacity)))


@dataclass
class PsdGroup:
    name: str
    visible: bool = True
    opacity: float = 1.0
    blend_mode: str = "pass_through"
    expanded: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("PSD group name must be non-empty")
        if self.blend_mode not in ("pass_through", *LAYER_BLEND_MODES):
            raise ValueError(f"unsupported PSD group blend mode {self.blend_mode!r}")
        self.opacity = max(0.0, min(1.0, float(self.opacity)))


@dataclass
class PsdDocument:
    size: tuple[int, int]
    layer_stack: list[PsdLayer]
    groups: dict[str, PsdGroup] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        width, height = self.size
        return height, width

    def layers(self) -> list[PsdLayer]:
        return self.layer_stack
