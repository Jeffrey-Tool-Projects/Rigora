"""R2.1: PSD import preview lists layers, groups and every unsupported feature."""
from __future__ import annotations

import json
import struct

import numpy as np
import pytest

from rigora.psd.reader import load_psd
from rigora.puppet.psd_import import plan_psd_import, preview_psd, puppet_from_psd
from rigora.puppet.runtime_parts import resolve_part_state
from tests.psd_fixtures import FixtureLayer, GroupEnd, GroupHeader, save_psd_stack

SIZE = (16, 12)


def _square(x0: int, y0: int, x1: int, y1: int, rgb=(200, 80, 40)) -> np.ndarray:
    image = np.zeros((SIZE[1], SIZE[0], 4), dtype=np.uint8)
    image[y0:y1, x0:x1, :3] = rgb
    image[y0:y1, x0:x1, 3] = 255
    return image


def _layer(name: str, box=(2, 2, 6, 6), **kwargs) -> FixtureLayer:
    return FixtureLayer(name, _square(*box), **kwargs)


def _codes(preview, subject=None) -> set[str]:
    return {d.code for d in preview.differences if subject is None or d.subject == subject}


@pytest.mark.parametrize("rle", [False, True])
def test_nested_groups_become_a_part_tree_with_group_visibility(tmp_path, rle):
    path = tmp_path / "nested.psd"
    save_psd_stack(path, SIZE, [
        _layer("body", (1, 1, 15, 11)),
        GroupEnd(),
        _layer("neck", (6, 6, 9, 9)),
        GroupEnd(),
        _layer("eye", (3, 3, 5, 5)),
        GroupHeader("face", opacity=0.5),
        _layer("hair", (2, 0, 14, 4)),
        GroupHeader("head", visible=False),
    ], rle=rle)

    decoded = load_psd(path)
    assert decoded.groups["face"].parent == "head"
    assert [layer.group_path for layer in decoded.layers()] == [
        (), ("head",), ("head", "face"), ("head",)]

    doc = puppet_from_psd(path, enable_auto_rig=False)
    parts = {part.id: part for part in doc.parts}
    assert parts["head"].drawables == ["neck", "hair"]
    assert parts["head"].children == ["face"]
    assert parts["face"].drawables == ["eye"]
    assert parts["head"].visible is False
    assert parts["face"].opacity == pytest.approx(0.5, abs=1 / 255)
    state = resolve_part_state(doc)
    assert state["body"] == (True, 1.0)
    assert state["eye"][0] is False

    preview = preview_psd(path)
    assert "group_hidden" in _codes(preview, "head")


def test_unsupported_features_are_listed_not_hidden(tmp_path):
    path = tmp_path / "features.psd"
    save_psd_stack(path, SIZE, [
        _layer("base", (2, 2, 10, 10)),
        _layer("shade", (0, 0, 12, 12), clipping=True, blend_key=b"mul "),
        _layer("glow", (4, 4, 8, 8), blend_key=b"lddg"),
        _layer("tone", (4, 4, 8, 8), blend_key=b"scrn"),
        _layer("odd", (4, 4, 8, 8), blend_key=b"hue "),
        _layer("masked", (1, 1, 3, 3), mask=True),
        _layer("styled", (1, 1, 3, 3), extra=((b"lfx2", b"\0" * 4), (b"iOpa", b"\x80"))),
        FixtureLayer("levels", np.zeros((0, 0, 4), dtype=np.uint8), extra=((b"levl", b"\0\0"),)),
        _layer("ghost", (5, 5, 6, 6), visible=False),
        _layer("ghost_detail", (5, 5, 6, 6), clipping=True),
        _layer("顏色", (9, 9, 11, 11)),
    ])

    preview = preview_psd(path)
    by_name = {layer.name: layer for layer in preview.layers}
    assert by_name["shade"].clip_mask == "base"
    assert by_name["shade"].blend_mode == "multiply"
    assert by_name["glow"].blend_mode == "additive"
    assert by_name["tone"].blend_mode == "normal"
    assert by_name["odd"].source_blend_mode == "hue"
    assert by_name["masked"].has_mask is True
    assert by_name["ghost"].status == "hidden"
    assert by_name["ghost_detail"].status == "clip_base_missing"
    assert "levels" not in by_name
    assert by_name["顏色"].drawable_id == "layer"
    assert by_name["base"].bounds == (2, 2, 10, 10)
    assert by_name["base"].size == (8, 8)

    assert "clipping_approximated" in _codes(preview, "shade")
    assert "blend_mode_approximated" in _codes(preview, "tone")
    assert "blend_mode_approximated" in _codes(preview, "odd")
    assert "blend_mode_approximated" not in _codes(preview, "glow")
    assert "layer_mask_ignored" in _codes(preview, "masked")
    assert {"layer_effects_ignored", "fill_opacity_ignored"} <= _codes(preview, "styled")
    assert "adjustment_layer_ignored" in _codes(preview, "levels")
    assert "hidden_layer_skipped" in _codes(preview, "ghost")
    assert "clipping_base_missing" in _codes(preview, "ghost_detail")
    assert "drawable_id_changed" in _codes(preview, "顏色")
    assert {d.code for d in preview.warnings} >= {"layer_mask_ignored", "blend_mode_approximated"}

    doc = puppet_from_psd(path, enable_auto_rig=False)
    drawables = {d.id: d for d in doc.drawables}
    assert drawables["shade"].clip_mask == "base"
    assert drawables["shade"].blend_mode == "multiply"
    assert drawables["glow"].blend_mode == "additive"
    assert "ghost_detail" not in drawables
    json.dumps(preview.to_dict(), ensure_ascii=False)


@pytest.mark.parametrize("rle", [False, True])
def test_mask_plane_with_its_own_rectangle_does_not_corrupt_pixels(tmp_path, rle):
    path = tmp_path / "mask.psd"
    layer = _layer("masked", (3, 2, 9, 7), mask=True)
    save_psd_stack(path, SIZE, [layer], rle=rle)
    decoded = load_psd(path).layers()[0]
    assert decoded.has_mask is True
    np.testing.assert_array_equal(decoded.image, layer.image)


def test_duplicate_group_names_keep_separate_parts(tmp_path):
    path = tmp_path / "dupes.psd"
    save_psd_stack(path, SIZE, [
        GroupEnd(), _layer("a", (1, 1, 3, 3)), GroupHeader("頭"),
        GroupEnd(), _layer("b", (5, 5, 7, 7)), GroupHeader("頭"),
    ])
    preview = preview_psd(path)
    assert [group.key for group in preview.groups] == ["頭", "頭 (2)"]
    assert [group.part_id for group in preview.groups] == ["layer", "layer_2"]
    assert "duplicate_group_name" in _codes(preview)
    doc = puppet_from_psd(path, enable_auto_rig=False)
    assert {part.id: part.drawables for part in doc.parts} == {"layer": ["a"], "layer_2": ["b"]}


def test_build_matches_preview_and_reads_the_file_once(tmp_path):
    path = tmp_path / "rig.psd"
    save_psd_stack(path, SIZE, [_layer("body", (1, 1, 15, 11)), _layer("eye", (3, 3, 5, 5))])
    plan = plan_psd_import(path)
    path.unlink()
    doc = plan.build(enable_auto_rig=False)
    for layer, drawable in zip(plan.preview.imported_layers, doc.drawables, strict=True):
        assert drawable.id == layer.drawable_id
        assert drawable.texture == layer.texture
        xs = [v[0] for v in drawable.vertices]
        ys = [v[1] for v in drawable.vertices]
        assert (min(xs), min(ys), max(xs), max(ys)) == layer.bounds


def test_no_importable_layer_raises(tmp_path):
    path = tmp_path / "empty.psd"
    save_psd_stack(path, SIZE, [_layer("ghost", visible=False)])
    with pytest.raises(ValueError, match="no visible non-empty layers"):
        preview_psd(path)


def test_fill_opacity_block_is_read(tmp_path):
    path = tmp_path / "fill.psd"
    save_psd_stack(path, SIZE, [_layer("a", extra=((b"iOpa", struct.pack(">B", 64)),))])
    assert load_psd(path).layers()[0].fill_opacity == pytest.approx(64 / 255)
