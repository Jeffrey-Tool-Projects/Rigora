"""PSD reader — layer records, additional info and group assembly.

Parses the layer + mask section: each layer record with its ``luni`` /
``lsct`` additional-info blocks, then walks the records bottom-to-top,
reading their channel data and rebuilding layer groups from the
section-divider records.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from rigora.psd.model import LAYER_BLEND_MODES, PsdEmptyRecord
from rigora.psd.model import PsdLayer as Layer, PsdGroup as LayerGroup
from rigora.psd.format import (
    _LAYER_FLAG_HIDDEN,
    _PSD_TO_BLEND_MODE,
    _SECTION_CLOSED_GROUP,
    _SECTION_END,
    _SECTION_OPEN_GROUP,
    _read_pascal_padded,
)
from rigora.psd.pixels import _read_layer_channel_data


def _parse_layer_and_mask_section(
    cursor, h: int, w: int,
) -> tuple[list[Layer], dict[str, LayerGroup], list[PsdEmptyRecord]]:
    section_length = cursor.read_u32()
    if section_length == 0:
        return [], {}, []
    section_end = cursor.pos + section_length
    layer_info_length = cursor.read_u32()
    if layer_info_length == 0:
        cursor.seek(section_end)
        return [], {}, []
    layer_info_end = cursor.pos + layer_info_length

    layer_count_signed = cursor.read_i16()
    # Negative layer count means the first alpha channel of the merged
    # image holds transparency information for the base layer — for our
    # subset we just take the absolute count.
    layer_count = abs(layer_count_signed)

    records: list[dict] = []
    for _ in range(layer_count):
        records.append(_parse_layer_record(cursor))
    _check_decoded_size(records, h, w)

    # Walk records bottom-to-top, reading channel data, and assemble
    # groups via lsct section dividers. PSD encodes a group as:
    #   ┌── section divider end (lsct=3)
    #   │   member layers (regular records)
    #   └── group header (lsct=1 or 2, name = group name)
    layers: list[Layer] = []
    groups: dict[str, LayerGroup] = {}
    state = _GroupAssemblyState()
    for record in records:
        _consume_record(cursor, record, h, w, layers, groups, state)

    cursor.seek(layer_info_end)
    cursor.seek(section_end)
    return layers, groups, state.empty_records


MAX_DECODED_BYTES = 4 * 1024 ** 3
"""Every pixel layer decodes to a full-canvas RGBA buffer; refuse files whose
layers would need more than this instead of exhausting memory part-way."""


def _check_decoded_size(records: list[dict], h: int, w: int) -> None:
    pixel_layers = sum(1 for r in records if r["bounds"][2] > r["bounds"][0]
                       and r["bounds"][3] > r["bounds"][1] and r.get("section_type") in (None, 0))
    needed = pixel_layers * h * w * 4
    if needed > MAX_DECODED_BYTES:
        raise ValueError(
            f"PSD needs {needed / 1024 ** 3:.1f} GiB to decode {pixel_layers} layers at "
            f"{w}x{h}; the limit is {MAX_DECODED_BYTES / 1024 ** 3:.0f} GiB — reduce the "
            "canvas size or merge layers")


@dataclass
class _GroupFrame:
    """Layers and child groups collected for a group whose header is pending."""

    layers: list[Layer] = field(default_factory=list)
    child_groups: list[str] = field(default_factory=list)


@dataclass
class _GroupAssemblyState:
    """Mutable bookkeeping while walking PSD layer records bottom→top.

    A section end divider opens a frame; the matching group header closes
    it. Frames nest, so layers below and above an inner group still belong
    to the enclosing group, and inner groups record their parent.
    """

    frames: list[_GroupFrame] = field(default_factory=list)
    empty_records: list[PsdEmptyRecord] = field(default_factory=list)


def _consume_record(
    cursor, record, h: int, w: int,
    layers: list[Layer],
    groups: dict[str, LayerGroup],
    state: _GroupAssemblyState,
) -> None:
    """Dispatch one PSD layer record to the section-divider /
    group-header / regular-layer handler. Pulled out of
    ``_parse_layer_and_mask_section`` so that function stays under the
    cognitive-complexity budget."""
    section_type = record.get("section_type")
    if section_type == _SECTION_END:
        _read_layer_channel_data(cursor, record, h, w)
        state.frames.append(_GroupFrame())
        return
    if section_type in (_SECTION_OPEN_GROUP, _SECTION_CLOSED_GROUP):
        _consume_group_header(cursor, record, h, w, groups, state)
        return
    layer = _read_layer_channel_data(cursor, record, h, w)
    if layer is None:
        layer = PsdEmptyRecord(
            name=record["name"],
            visible=not bool(record["flags"] & _LAYER_FLAG_HIDDEN),
            info_keys=tuple(record.get("info_keys", ())),
        )
        state.empty_records.append(layer)
    if state.frames:
        state.frames[-1].layers.append(layer)
    if isinstance(layer, Layer):
        layers.append(layer)


def _unique_group_key(name: str, groups: dict[str, LayerGroup]) -> str:
    if name not in groups:
        return name
    index = 2
    while f"{name} ({index})" in groups:
        index += 1
    return f"{name} ({index})"


def _consume_group_header(
    cursor, record, h: int, w: int,
    groups: dict[str, LayerGroup],
    state: _GroupAssemblyState,
) -> None:
    """Materialise the LayerGroup for a section divider record and
    bind the layers and groups collected since its end divider."""
    _read_layer_channel_data(cursor, record, h, w)
    frame = state.frames.pop() if state.frames else _GroupFrame()
    source_name = record["name"]
    key = _unique_group_key(source_name, groups)
    blend_key = record["blend_key"]
    blend_mode = _PSD_TO_BLEND_MODE.get(blend_key, "normal")
    grp_blend = blend_mode if blend_mode in LAYER_BLEND_MODES else "normal"
    # Skip a corrupt group (bad name / opacity) rather than fail
    # the whole load.
    with contextlib.suppress(ValueError):
        groups[key] = LayerGroup(
            name=key,
            visible=not bool(record["flags"] & _LAYER_FLAG_HIDDEN),
            opacity=record["opacity"] / 255.0,
            blend_mode=grp_blend if grp_blend != "normal" else "pass_through",
            expanded=record["section_type"] == _SECTION_OPEN_GROUP,
            source_name=source_name if key != source_name else None,
            source_blend_key=blend_key.decode("latin-1"),
        )
    for member in frame.layers:
        if member.group is None:
            member.group = key
        member.group_path = (key, *member.group_path)
    for child in frame.child_groups:
        if child in groups:
            groups[child].parent = key
    if state.frames:
        state.frames[-1].layers.extend(frame.layers)
        state.frames[-1].child_groups.append(key)


def _parse_layer_record(cursor) -> dict:
    top = cursor.read_i32()
    left = cursor.read_i32()
    bottom = cursor.read_i32()
    right = cursor.read_i32()
    n_channels = cursor.read_u16()
    channels: list[tuple[int, int]] = []
    for _ in range(n_channels):
        ch_id = cursor.read_i16()
        ch_size = cursor.read_u32()
        channels.append((ch_id, ch_size))
    blend_sig = cursor.read(4)
    if blend_sig != b"8BIM":
        raise ValueError(f"layer record signature mismatch: {blend_sig!r}")
    blend_key = bytes(cursor.read(4))
    opacity = cursor.read_u8()
    clipping = cursor.read_u8()
    flags = cursor.read_u8()
    cursor.read_u8()   # filler
    extra_length = cursor.read_u32()
    extra_start = cursor.pos
    mask_data_length = cursor.read_u32()
    cursor.skip(mask_data_length)
    blending_ranges_length = cursor.read_u32()
    cursor.skip(blending_ranges_length)
    legacy_name = _read_pascal_padded(cursor, pad_to=4)
    additional = _parse_additional_info(
        cursor, end=extra_start + extra_length,
    )
    cursor.seek(extra_start + extra_length)
    return {
        "bounds": (top, left, bottom, right),
        "channels": channels,
        "blend_key": blend_key,
        "opacity": opacity,
        "flags": flags,
        # Prefer the Unicode name when present; legacy name is a
        # latin-1 fallback that loses high codepoints.
        "name": additional.get("luni", legacy_name),
        "section_type": additional.get("lsct"),
        "clipping": clipping,
        # Channel -2 / -3 are the user and vector-derived mask planes.
        "has_mask": mask_data_length > 0
        or any(ch_id in (-2, -3) for ch_id, _ in channels)
        or bool({"vmsk", "vsms"} & set(additional.get("keys", ()))),
        "fill_opacity": additional.get("iOpa", 255),
        "info_keys": additional.get("keys", ()),
    }


def _parse_additional_info(cursor, *, end: int) -> dict:
    """Walk the additional-info blocks at the tail of a layer record's
    extra-data section. Recognised keys: ``luni`` (Unicode name),
    ``lsct`` (section divider type), ``iOpa`` (fill opacity). Every key
    seen is listed under ``keys`` so callers can report what they skip."""
    out: dict = {"keys": []}
    while cursor.pos + 12 <= end:
        sig = cursor.read(4)
        if sig not in (b"8BIM", b"8B64"):
            # Some encoders pad with zeros — back up so the outer
            # ``cursor.seek(end)`` skips cleanly.
            cursor.seek(cursor.pos - 4)
            break
        key = cursor.read(4)
        length = cursor.read_u32()
        out["keys"].append(key.decode("latin-1"))
        block_start = cursor.pos
        _read_additional_info_block(cursor, key, length, out)
        cursor.seek(block_start + length)
        # Many additional-info payloads are padded to a 2-byte
        # boundary; account for it.
        if (cursor.pos - block_start) % 2:
            cursor.skip(1)
    return out


def _read_additional_info_block(cursor, key: bytes, length: int, out: dict) -> None:
    """Decode the payload of a single additional-info block in place."""
    if key == b"luni" and length >= 4:
        char_count = cursor.read_u32()
        chars_bytes = cursor.read(char_count * 2)
        out["luni"] = chars_bytes.decode("utf-16-be", errors="replace")
    elif key == b"lsct" and length >= 4:
        out["lsct"] = cursor.read_u32()
    elif key == b"iOpa" and length >= 1:
        out["iOpa"] = cursor.read_u8()
