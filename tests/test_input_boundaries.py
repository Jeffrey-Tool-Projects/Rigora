"""R7.6: hostile archives, oversized images, corrupt PSDs, bad numbers, cycles, caches."""
from __future__ import annotations

import io
import json
import struct
import zipfile
import zlib

import numpy as np
import pytest
from PIL import Image

from rigora.psd import layers as psd_layers
from rigora.psd.reader import load_psd
from rigora.puppet import webcam_tracker
from rigora.puppet.asset_update import decode_texture
from rigora.puppet.auto_mesh import puppet_from_png
from rigora.puppet.document import Deformer, Drawable, Part, PuppetDocument
from rigora.puppet.document_io import PuppetFormatError, from_zip_bytes, to_zip_bytes
from rigora.puppet.runtime import compose_all_drawables
from rigora.puppet.runtime_parts import resolve_part_state
from tests.psd_fixtures import FixtureLayer, save_psd_stack


def _archive(manifest_text: str, extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("puppet.json", manifest_text)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def _manifest(**overrides) -> dict:
    doc = PuppetDocument(size=(16, 16), drawables=[Drawable(
        "a", "textures/a.png", [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0)], [0, 1, 2],
        [(0, 0), (1, 0), (1, 1)])])
    data = json.loads(zipfile.ZipFile(io.BytesIO(to_zip_bytes(doc))).read("puppet.json"))
    data.update(overrides)
    return data


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_non_finite_numbers_are_refused(token):
    text = json.dumps(_manifest()).replace("4.0", token, 1)
    with pytest.raises(PuppetFormatError, match="non-finite|out of range"):
        from_zip_bytes(_archive(text))


@pytest.mark.parametrize("size", [[0, 10], [10, -1], [100_000, 10], ["x", 1]])
def test_canvas_size_is_bounded(size):
    with pytest.raises(PuppetFormatError):
        from_zip_bytes(_archive(json.dumps(_manifest(size=size))))


def test_path_like_member_names_stay_inside_the_texture_map(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    archive = _archive(json.dumps(_manifest()),
                       {"textures/../../evil.png": b"x", "../outside.txt": b"y"})
    doc = from_zip_bytes(archive)
    assert "textures/../../evil.png" in doc.textures       # a key, never a file path
    assert list(tmp_path.iterdir()) == []                  # nothing written anywhere


def test_declared_size_over_the_limit_is_refused_before_reading():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("puppet.json", json.dumps(_manifest()))
        zf.writestr("textures/zeros.png", b"\0" * (8 * 1024 * 1024))
    with pytest.raises(PuppetFormatError, match="limit"):
        from io import BytesIO

        from rigora.puppet.archive_container import _load_from_zip
        with zipfile.ZipFile(BytesIO(buf.getvalue())) as zf:
            _load_from_zip(zf, max_uncompressed=1024 * 1024)


def _png_claiming(width: int, height: int) -> bytes:
    """A tiny PNG whose header claims ``width`` × ``height`` pixels."""
    buf = io.BytesIO()
    Image.new("RGBA", (1, 1)).save(buf, format="PNG")
    data = bytearray(buf.getvalue())
    ihdr = 8 + 8                                             # signature + length/type
    data[ihdr:ihdr + 8] = struct.pack(">II", width, height)
    crc = zlib.crc32(bytes(data[12:ihdr + 13])) & 0xFFFFFFFF
    data[ihdr + 13:ihdr + 17] = struct.pack(">I", crc)
    return bytes(data)


def test_oversized_images_fail_as_readable_errors(tmp_path):
    bomb = _png_claiming(60_000, 60_000)
    with pytest.raises(ValueError, match="cannot read the image"):
        puppet_from_png(bomb)
    assert decode_texture(bomb) is None
    path = tmp_path / "bomb.png"
    path.write_bytes(bomb)
    from rigora.puppet.asset_update import _load_image
    with pytest.raises(ValueError, match="not a readable image"):
        _load_image(path)


def test_truncated_psds_only_raise_value_errors(tmp_path):
    image = np.zeros((12, 16, 4), dtype=np.uint8)
    image[2:8, 3:9] = (200, 10, 10, 255)
    whole = tmp_path / "whole.psd"
    save_psd_stack(whole, (16, 12), [FixtureLayer("a", image), FixtureLayer("b", image)],
                   rle=True)
    data = whole.read_bytes()
    cut = tmp_path / "cut.psd"
    for size in range(0, len(data), max(1, len(data) // 97)):
        cut.write_bytes(data[:size])
        try:
            load_psd(cut)
        except ValueError:
            continue


def test_psd_that_would_exhaust_memory_is_refused(tmp_path, monkeypatch):
    image = np.zeros((40, 40, 4), dtype=np.uint8)
    image[1:3, 1:3] = 255
    path = tmp_path / "wide.psd"
    save_psd_stack(path, (40, 40), [FixtureLayer(f"l{i}", image) for i in range(4)])
    monkeypatch.setattr(psd_layers, "MAX_DECODED_BYTES", 4 * 40 * 40 * 4 - 1)
    with pytest.raises(ValueError, match="merge layers"):
        load_psd(path)


def test_reference_cycles_do_not_hang():
    doc = PuppetDocument(
        drawables=[Drawable("d", "t", [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)], [0, 1, 2],
                            [(0, 0)] * 3)],
        deformers=[Deformer("x", "rotation", "y", ["d"], {"anchor": [0, 0], "angle": 0.2}),
                   Deformer("y", "rotation", "x", ["d"], {"anchor": [0, 0], "angle": 0.2})],
        parts=[Part("p", ["d"], ["q"]), Part("q", [], ["p"])],
    )
    assert compose_all_drawables(doc, {})["d"].shape == (3, 2)
    assert resolve_part_state(doc)["d"] == (True, 1.0)


def test_model_cache_failures_are_readable_and_leave_no_partial(tmp_path, monkeypatch):
    blocker = tmp_path / "data"
    blocker.write_text("not a folder", encoding="utf-8")
    monkeypatch.setattr("rigora.system.app_paths.app_dir", lambda: blocker)
    with pytest.raises(webcam_tracker._WebcamSetupError, match="model folder"):   # noqa: SLF001
        webcam_tracker._face_landmarker_model_path()   # noqa: SLF001

    folder = tmp_path / "ok"
    monkeypatch.setattr("rigora.system.app_paths.app_dir", lambda: folder)
    payload = b"model bytes"
    monkeypatch.setattr(webcam_tracker, "_FACE_LANDMARKER_SHA256",
                        webcam_tracker._sha256_of(payload))   # noqa: SLF001

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(webcam_tracker, "_https_urlopen", lambda url: Response(payload))

    def refuse(*_args, **_kwargs):
        raise PermissionError("read-only")

    import os
    monkeypatch.setattr(os, "replace", refuse)   # the tracker imports os inside the function
    with pytest.raises(webcam_tracker._WebcamSetupError, match="failed to save"):   # noqa: SLF001
        webcam_tracker._face_landmarker_model_path()   # noqa: SLF001
    assert not (folder / "models" / "face_landmarker.task.part").exists()
