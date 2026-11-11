"""PSD decoding contracts exercised through independently encoded files."""
from __future__ import annotations

import struct
import subprocess
import sys

import numpy as np
import pytest

from rigora.psd.reader import load_psd
from rigora.puppet.psd_import import puppet_from_psd
from tests.psd_fixtures import FixtureDocument, composite_psd, save_psd


@pytest.mark.parametrize("rle", [False, True])
def test_layers_keep_unicode_groups_opacity_and_visibility(tmp_path, rle):
    document = FixtureDocument()
    document.load_image(np.full((3, 4, 4), 255, dtype=np.uint8))
    document.stack[0].name = "髮絲😀"
    document.stack[0].group = "頭部"
    document.stack[0].opacity = 0.4
    hidden = document.add_layer(name="隱藏眼睛")
    hidden.image[:] = (13, 27, 49, 255)
    hidden.visible = False
    hidden.group = "頭部"
    path = tmp_path / "layers.psd"
    save_psd(document, path, rle=rle)

    decoded = load_psd(path)
    assert decoded.size == (4, 3)
    assert [layer.name for layer in decoded.layers()] == ["髮絲😀", "隱藏眼睛"]
    assert decoded.layers()[0].opacity == pytest.approx(0.4)
    assert decoded.layers()[1].visible is False
    assert [layer.group for layer in decoded.layers()] == ["頭部", "頭部"]
    np.testing.assert_array_equal(decoded.layers()[1].image, hidden.image)
    assert decoded.groups["頭部"].expanded is True
    puppet = puppet_from_psd(path, enable_auto_rig=False)
    assert len(puppet.drawables) == 1
    assert puppet.parts[0].drawables == [puppet.drawables[0].id]


@pytest.mark.parametrize("rle", [False, True])
@pytest.mark.parametrize("channels", [3, 4, 5])
def test_composite_only_uses_header_channel_count(tmp_path, rle, channels):
    pixels = np.empty((2, 3, channels), dtype=np.uint8)
    for channel in range(channels):
        pixels[..., channel] = channel * 40 + 12
    path = tmp_path / "composite.psd"
    path.write_bytes(composite_psd(pixels, rle=rle))
    decoded = load_psd(path)
    assert decoded.size == (3, 2)
    assert len(decoded.layers()) == 1
    result = decoded.layers()[0].image
    np.testing.assert_array_equal(result[..., :3], pixels[..., :3])
    expected_alpha = pixels[..., 3] if channels >= 4 else np.full((2, 3), 255)
    np.testing.assert_array_equal(result[..., 3], expected_alpha)


def test_explicit_transparent_composite_is_not_made_opaque(tmp_path):
    pixels = np.zeros((2, 3, 4), dtype=np.uint8)
    pixels[..., :3] = (12, 34, 56)
    path = tmp_path / "transparent.psd"
    path.write_bytes(composite_psd(pixels))
    np.testing.assert_array_equal(load_psd(path).layers()[0].image, pixels)
    with pytest.raises(ValueError, match="no visible non-empty layers"):
        puppet_from_psd(path)


def test_packbits_repeat_runs_and_noop_rows(tmp_path):
    header = composite_psd(np.zeros((1, 3, 3), dtype=np.uint8))[:38]
    rows = [b"\x80\xfe" + bytes([value]) for value in (12, 34, 56)]
    path = tmp_path / "repeat.psd"
    path.write_bytes(header + b"\0\1" + struct.pack(">3H", 3, 3, 3) + b"".join(rows))
    expected = np.full((1, 3, 4), (12, 34, 56, 255), dtype=np.uint8)
    np.testing.assert_array_equal(load_psd(path).layers()[0].image, expected)


def test_layer_pixels_are_clipped_to_canvas(tmp_path):
    document = FixtureDocument()
    document.load_image(np.full((3, 4, 4), 255, dtype=np.uint8))
    layer = document.add_layer(name="overhang")
    layer.image[:] = (12, 34, 56, 200)
    layer.top, layer.left = -1, -2
    path = tmp_path / "overhang.psd"
    save_psd(document, path)
    image = load_psd(path).layers()[1].image
    np.testing.assert_array_equal(image[:2, :2], layer.image[1:, 2:])
    assert not image[2:].any()
    assert not image[:, 2:].any()


@pytest.mark.parametrize(("offset", "replacement", "message"), [
    (0, b"BAD!", "signature"),
    (4, struct.pack(">H", 2), "version"),
    (12, struct.pack(">H", 2), "channel count"),
    (14, struct.pack(">I", 0), "canvas size"),
    (22, struct.pack(">H", 16), "depth"),
    (24, struct.pack(">H", 4), "color mode"),
    (38, struct.pack(">H", 3), "compression"),
])
def test_rejects_unsupported_header_and_compression(tmp_path, offset, replacement, message):
    raw = bytearray(composite_psd(np.zeros((2, 3, 4), dtype=np.uint8)))
    raw[offset:offset + len(replacement)] = replacement
    path = tmp_path / "invalid.psd"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match=message):
        load_psd(path)


@pytest.mark.parametrize("length", [0, 4, 10, 24, 27, 39, 41])
def test_rejects_truncated_data(tmp_path, length):
    raw = composite_psd(np.zeros((2, 3, 4), dtype=np.uint8))
    path = tmp_path / "truncated.psd"
    path.write_bytes(raw[:length])
    with pytest.raises(ValueError, match="truncated"):
        load_psd(path)


def test_import_and_conversion_do_not_load_host_or_gui(tmp_path):
    path = tmp_path / "standalone.psd"
    path.write_bytes(composite_psd(np.full((2, 3, 4), 255, dtype=np.uint8)))
    program = """
import importlib.abc
import sys
class RejectHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'Imervue', 'PySide6', 'OpenGL'}:
            raise AssertionError('unexpected import: ' + fullname)
sys.meta_path.insert(0, RejectHost())
from rigora.puppet.psd_import import puppet_from_psd
document = puppet_from_psd(sys.argv[1], enable_auto_rig=False)
assert document.size == (3, 2)
assert len(document.drawables) == 1
"""
    subprocess.run([sys.executable, "-c", program, str(path)], check=True, timeout=30)
