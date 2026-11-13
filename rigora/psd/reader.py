"""Decode 8-bit RGB PSD files into layers for Puppet conversion.

Supports raw and PackBits channels, Unicode names, flattened layer groups and
composite-only documents. No Paint document, compositing engine or Qt is loaded.
"""
from __future__ import annotations

from pathlib import Path

from rigora.psd.format import (
    PSD_COLOR_MODE_RGB,
    PSD_DEPTH_8BIT,
    PSD_SIGNATURE,
    PSD_VERSION,
    _Cursor,
)
from rigora.psd.layers import _parse_layer_and_mask_section
from rigora.psd.model import PsdDocument, PsdLayer
from rigora.psd.pixels import _parse_image_data_section


def load_psd(path: str | Path) -> PsdDocument:
    cursor = _Cursor(Path(path).read_bytes())
    height, width, channels = _parse_header(cursor)
    for _ in range(2):
        cursor.read(cursor.read_u32())
    layers, groups, empty_records = _parse_layer_and_mask_section(cursor, height, width)
    if not layers:
        composite = _parse_image_data_section(cursor, height, width, channels=channels)
        layers = [PsdLayer(name="Background", image=composite)]
    return PsdDocument(size=(width, height), layer_stack=layers, groups=groups,
                       empty_records=empty_records)


def _parse_header(cursor: _Cursor) -> tuple[int, int, int]:
    signature = cursor.read(4)
    if signature != PSD_SIGNATURE:
        raise ValueError(f"not a PSD file: signature {signature!r}")
    version = cursor.read_u16()
    if version != PSD_VERSION:
        raise ValueError(f"unsupported PSD version {version}")
    cursor.read(6)
    channels = cursor.read_u16()
    if not 3 <= channels <= 56:
        raise ValueError(f"PSD RGB channel count {channels} out of range")
    height, width = cursor.read_u32(), cursor.read_u32()
    if not 1 <= height <= 30_000 or not 1 <= width <= 30_000:
        raise ValueError(f"PSD canvas size {width}x{height} out of range")
    depth = cursor.read_u16()
    if depth != PSD_DEPTH_8BIT:
        raise ValueError(f"unsupported PSD depth {depth}; expected 8")
    mode = cursor.read_u16()
    if mode != PSD_COLOR_MODE_RGB:
        raise ValueError(f"unsupported PSD color mode {mode}; expected RGB")
    return height, width, channels
