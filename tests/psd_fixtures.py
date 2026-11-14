"""Small independent PSD encoder for exercising the public import path."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class FixtureLayer:
    name: str
    image: np.ndarray
    visible: bool = True
    opacity: float = 1.0
    group: str | None = None
    top: int = 0
    left: int = 0
    blend_key: bytes = b"norm"
    clipping: bool = False
    mask: bool = False
    extra: tuple[tuple[bytes, bytes], ...] = ()


@dataclass
class GroupEnd:
    """Section divider that opens a group when reading bottom to top."""


@dataclass
class GroupHeader:
    name: str
    visible: bool = True
    opacity: float = 1.0
    blend_key: bytes = b"pass"


class FixtureDocument:
    def __init__(self) -> None:
        self.stack: list[FixtureLayer] = []

    def load_image(self, image: np.ndarray) -> None:
        self.stack = [FixtureLayer("Background", image.copy())]

    def layers(self) -> list[FixtureLayer]:
        return self.stack

    def add_layer(self, *, name: str) -> FixtureLayer:
        layer = FixtureLayer(name, np.zeros_like(self.stack[0].image))
        self.stack.append(layer)
        return layer


def _additional(key: bytes, payload: bytes) -> bytes:
    return b"8BIM" + key + struct.pack(">I", len(payload)) + payload + b"\0" * (len(payload) % 2)


def _row_literal(row: np.ndarray) -> bytes:
    raw = row.tobytes()
    return b"".join(bytes([len(raw[i:i + 128]) - 1]) + raw[i:i + 128]
                    for i in range(0, len(raw), 128))


def _channel(image: np.ndarray, channel: int, *, rle: bool) -> bytes:
    plane = image[..., channel]
    if not rle:
        return b"\0\0" + plane.tobytes()
    rows = [_row_literal(row) for row in plane]
    return b"\0\1" + struct.pack(f">{len(rows)}H", *(len(row) for row in rows)) + b"".join(rows)


def _record(layer: FixtureLayer, *, rle: bool, section: int | None = None) -> tuple[bytes, bytes]:
    height, width = layer.image.shape[:2]
    channels = [] if section is not None else [_channel(layer.image, i, rle=rle) for i in range(4)]
    ids = [0, 1, 2, -1]
    if layer.mask and section is None:
        # A 1x1 user-mask plane whose rectangle differs from the layer bounds.
        channels.append(b"\0\0\xff")
        ids.append(-2)
    record = struct.pack(">4iH", layer.top, layer.left, layer.top + height,
                         layer.left + width, len(channels))
    for channel, data in zip(ids, channels, strict=False):
        record += struct.pack(">hI", channel, len(data))
    record += b"8BIM" + layer.blend_key + bytes([
        round(layer.opacity * 255), int(layer.clipping), 8 if layer.visible else 10, 0])
    legacy = layer.name.encode("latin-1", errors="replace")[:255]
    name = bytes([len(legacy)]) + legacy
    name += b"\0" * (-len(name) % 4)
    unicode_name = layer.name.encode("utf-16-be")
    mask_data = struct.pack(">4i", 0, 0, 1, 1) + b"\0" * 4 if layer.mask else b""
    extra = (struct.pack(">I", len(mask_data)) + mask_data + b"\0" * 4 + name
             + _additional(b"luni", struct.pack(">I", len(unicode_name) // 2) + unicode_name))
    if section is not None:
        extra += _additional(b"lsct", struct.pack(">I", section))
    for key, payload in layer.extra:
        extra += _additional(key, payload)
    return record + struct.pack(">I", len(extra)) + extra, b"".join(channels)


def _layer_section(layers: list[FixtureLayer], *, rle: bool) -> bytes:
    records, pixels = [], []
    previous_group = None
    empty = np.zeros((0, 0, 4), dtype=np.uint8)
    for layer in [*layers, None]:
        group = layer.group if layer is not None else None
        if group != previous_group:
            if previous_group is not None:
                record, _ = _record(FixtureLayer(previous_group, empty), rle=False, section=1)
                records.append(record)
            if group is not None:
                record, _ = _record(FixtureLayer("</Layer group>", empty), rle=False, section=3)
                records.append(record)
            previous_group = group
        if layer is not None:
            record, data = _record(layer, rle=rle)
            records.append(record)
            pixels.append(data)
    info = struct.pack(">h", len(records)) + b"".join(records) + b"".join(pixels)
    info += b"\0" * (len(info) % 2)
    block = struct.pack(">I", len(info)) + info + b"\0" * 4
    return struct.pack(">I", len(block)) + block


def composite_psd(image: np.ndarray, *, rle: bool = False) -> bytes:
    height, width, channels = image.shape
    header = struct.pack(">4sH6xHIIHH", b"8BPS", 1, channels, height, width, 8, 3)
    if not rle:
        data = b"\0\0" + b"".join(image[..., i].tobytes() for i in range(channels))
    else:
        rows = [_row_literal(row) for i in range(channels) for row in image[..., i]]
        data = b"\0\1" + struct.pack(f">{len(rows)}H", *(len(row) for row in rows)) + b"".join(rows)
    return header + b"\0" * 12 + data


def save_psd(document: FixtureDocument, path: str | Path, *, rle: bool = False) -> None:
    height, width = document.stack[0].image.shape[:2]
    header = struct.pack(">4sH6xHIIHH", b"8BPS", 1, 4, height, width, 8, 3)
    Path(path).write_bytes(header + b"\0" * 8 + _layer_section(document.stack, rle=rle))


def save_psd_stack(path: str | Path, size: tuple[int, int],
                   stack: list[FixtureLayer | GroupEnd | GroupHeader], *, rle: bool = False) -> None:
    """Write an explicit bottom-to-top record stack, e.g. for nested groups."""
    width, height = size
    empty = np.zeros((0, 0, 4), dtype=np.uint8)
    records, pixels = [], []
    for item in stack:
        if isinstance(item, GroupEnd):
            record, _ = _record(FixtureLayer("</Layer group>", empty), rle=False, section=3)
        elif isinstance(item, GroupHeader):
            header_layer = FixtureLayer(item.name, empty, visible=item.visible,
                                        opacity=item.opacity, blend_key=item.blend_key)
            record, _ = _record(header_layer, rle=False, section=1)
        else:
            record, data = _record(item, rle=rle)
            pixels.append(data)
        records.append(record)
    info = struct.pack(">h", len(records)) + b"".join(records) + b"".join(pixels)
    info += b"\0" * (len(info) % 2)
    block = struct.pack(">I", len(info)) + info + b"\0" * 4
    header = struct.pack(">4sH6xHIIHH", b"8BPS", 1, 4, height, width, 8, 3)
    Path(path).write_bytes(header + b"\0" * 8 + struct.pack(">I", len(block)) + block)
