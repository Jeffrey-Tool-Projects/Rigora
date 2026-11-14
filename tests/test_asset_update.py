"""R2.2: art updates keep rig data, preview size changes and resolve conflicts."""
from __future__ import annotations

import io
import json

import numpy as np
import pytest
from PIL import Image

from rigora.puppet.asset_update import (
    apply_asset_update,
    decode_texture,
    find_missing_textures,
    locate_textures,
    plan_asset_update,
    preview_relink,
    relink_texture,
    texture_rect,
)
from rigora.puppet.document import Drawable, Motion, MotionSegment, MotionTrack, PuppetDocument
from rigora.puppet.document_io import from_zip_bytes, to_zip_bytes
from rigora.puppet.document_session import DocumentSession
from rigora.puppet.psd_import import plan_psd_import
from tests.psd_fixtures import FixtureLayer, GroupEnd, GroupHeader, save_psd_stack

SIZE = (20, 16)


def _art(box, rgb) -> np.ndarray:
    image = np.zeros((SIZE[1], SIZE[0], 4), dtype=np.uint8)
    x0, y0, x1, y1 = box
    image[y0:y1, x0:x1, :3] = rgb
    image[y0:y1, x0:x1, 3] = 255
    return image


def _v1(path):
    save_psd_stack(path, SIZE, [
        _layer("body", (2, 2, 12, 14), (200, 150, 120)),
        GroupEnd(),
        _layer("arm", (12, 4, 16, 10), (180, 120, 90)),
        GroupHeader("limbs"),
        _layer("hat", (3, 0, 10, 3), (40, 40, 160)),
        _layer("old", (17, 1, 19, 3), (0, 0, 0)),
    ])


def _v2(path):
    save_psd_stack(path, SIZE, [
        _layer("body", (1, 2, 12, 15), (210, 160, 130)),     # grew past its mesh
        GroupEnd(),
        _layer("arm", (12, 4, 16, 10), (90, 60, 45)),        # recoloured in place
        _layer("eye", (5, 5, 7, 7), (10, 10, 10)),           # new, inside the group
        GroupHeader("limbs"),
        _layer("cap", (3, 0, 10, 3), (40, 40, 200)),         # renamed hat
    ])


def _layer(name, box, rgb) -> FixtureLayer:
    return FixtureLayer(name, _art(box, rgb))


def _rigged(tmp_path) -> PuppetDocument:
    path = tmp_path / "v1.psd"
    _v1(path)
    doc = plan_psd_import(path).build(enable_auto_rig=False)
    arm = doc.drawable("arm")
    arm.bone_weights = {"shoulder": [1.0, 0.5, 0.5, 1.0]}
    arm.vertex_morphs = [{"parameter": "ParamArm", "delta_at_min": [(0, 0)] * 4,
                          "delta_at_max": [(1, 0)] * 4}]
    doc.motions.append(Motion("wave", 1.0, tracks=[MotionTrack("ParamArm", [
        MotionSegment("linear", (0.0, 0.0), (1.0, 1.0))])]))
    return doc


def _plan(tmp_path, doc, **kwargs):
    path = tmp_path / "v2.psd"
    _v2(path)
    return plan_asset_update(doc, plan_psd_import(path), **kwargs)


def test_plan_reports_kinds_conflicts_and_safe_defaults(tmp_path):
    doc = _rigged(tmp_path)
    update = _plan(tmp_path, doc)
    by_key = {c.key: c for c in update.changes}
    assert by_key["arm"].kind == "changed"
    assert by_key["arm"].default_action == "update"
    assert by_key["body"].conflicts == ("art_outside_mesh",)
    assert by_key["body"].texture_rect == (2.0, 2.0, 12.0, 14.0)
    assert by_key["body"].new_bounds == (1, 2, 12, 15)
    assert by_key["+eye"].kind == "new"
    assert by_key["old"].kind == "not_in_source"
    assert by_key["old"].actions == ("keep", "hide")
    assert "possible_rename" in by_key["hat"].conflicts
    assert "possible_rename" in by_key["+cap"].conflicts
    assert by_key["+cap"].default_action == "skip"
    json.dumps(update.to_dict())


def test_default_apply_replaces_pixels_and_keeps_rig_data(tmp_path):
    doc = _rigged(tmp_path)
    arm_before = (list(doc.drawable("arm").vertices), dict(doc.drawable("arm").bone_weights))
    result = apply_asset_update(doc, _plan(tmp_path, doc))
    assert sorted(result.updated) == ["arm", "body"]
    assert result.added == ["eye"]
    arm = doc.drawable("arm")
    assert (arm.vertices, arm.bone_weights) == arm_before
    assert arm.vertex_morphs[0]["parameter"] == "ParamArm"
    assert tuple(decode_texture(doc.textures[arm.texture])[0, 0]) == (90, 60, 45, 255)
    body = doc.drawable("body")
    assert decode_texture(doc.textures[body.texture]).shape == (12, 10, 4)
    eye = doc.drawable("eye")
    orders = {d.id: d.draw_order for d in doc.drawables}
    assert orders["arm"] < orders["eye"] < orders["hat"]
    assert len(set(orders.values())) == len(orders)
    assert "eye" in next(p for p in doc.parts if p.id == "limbs").drawables
    assert eye.texture in doc.textures
    assert doc.drawable("old").visible is True
    reopened = from_zip_bytes(to_zip_bytes(doc))
    assert reopened.drawable("arm").bone_weights == arm.bone_weights
    assert reopened.motions[0].name == "wave"


def test_rebuild_and_mapping_and_hide(tmp_path):
    doc = _rigged(tmp_path)
    update = _plan(tmp_path, doc, mapping={"hat": "cap"})
    assert update.change("hat").source_id == "cap"
    assert "+cap" not in {c.key for c in update.changes}
    result = apply_asset_update(doc, update, {"body": "rebuild", "arm": "rebuild", "old": "hide"})
    assert result.dropped == {"body": [], "arm": ["bone_weights", "vertex_morphs"]}
    assert doc.drawable("arm").bone_weights is None
    xs = [v[0] for v in doc.drawable("body").vertices]
    assert (min(xs), max(xs)) == (1.0, 12.0)
    assert tuple(decode_texture(doc.textures[doc.drawable("hat").texture])[0, 0]) == (
        40, 40, 200, 255)
    assert doc.drawable("old").visible is False


def test_invalid_requests_change_nothing(tmp_path):
    doc = _rigged(tmp_path)
    snapshot = to_zip_bytes(doc)
    update = _plan(tmp_path, doc)
    with pytest.raises(ValueError, match="not possible"):
        apply_asset_update(doc, update, {"old": "update"})
    with pytest.raises(ValueError, match="no planned change"):
        apply_asset_update(doc, update, {"ghost": "skip"})
    with pytest.raises(ValueError, match="unknown source"):
        _plan(tmp_path, doc, mapping={"hat": "nope"})
    doc.drawable("arm").vertices.append((0.0, 0.0))
    with pytest.raises(ValueError, match="plan the update again"):
        apply_asset_update(doc, update)
    doc.drawable("arm").vertices.pop()
    assert to_zip_bytes(doc) == snapshot


def test_canvas_size_mismatch_blocks(tmp_path):
    doc = _rigged(tmp_path)
    doc.size = (40, 32)
    update = _plan(tmp_path, doc)
    assert update.blocking and "resize" in update.blocking[0]
    with pytest.raises(ValueError, match="resize"):
        apply_asset_update(doc, update)


def test_unaligned_and_shared_textures_offer_rebuild_only(tmp_path):
    doc = _rigged(tmp_path)
    doc.drawable("arm").uvs = [(1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]   # rotated
    doc.drawable("hat").texture = doc.drawable("body").texture
    update = _plan(tmp_path, doc, mapping={"hat": "cap"})
    assert update.change("arm").conflicts == ("unaligned_uvs",)
    assert update.change("arm").actions == ("rebuild", "skip")
    assert "shared_texture" in update.change("body").conflicts
    assert update.change("body").default_action == "skip"
    apply_asset_update(doc, update, {"hat": "rebuild"})
    assert doc.drawable("hat").texture != doc.drawable("body").texture


def test_fractional_rect_keeps_texel_positions():
    from rigora.puppet import asset_update as module
    drawable = Drawable("d", "textures/d.png", [(2.5, 1.25), (6.5, 1.25), (6.5, 5.25)],
                        [0, 1, 2], [(0, 0), (1, 0), (1, 1)])
    doc = PuppetDocument(size=SIZE, drawables=[drawable])
    rect = texture_rect(drawable)
    assert rect == (2.5, 1.25, 6.5, 5.25)
    change = module.AssetChange("d", "d", "d", "changed", rect, (0, 0, 20, 16), (),
                                ("update",), "update")
    layer = type("Layer", (), {"index": 0, "drawable_id": "d"})
    image = _art((0, 0, 20, 16), (1, 2, 3))
    plan = type("Plan", (), {"layer_image": staticmethod(lambda _index: image),
                             "preview": type("Preview", (), {"imported_layers": (layer,)})})
    before = [c for u, v in drawable.uvs for c in (rect[0] + u * 4, rect[1] + v * 4)]
    module._update_in_place(doc, change, plan)   # noqa: SLF001
    # The whole-pixel crop spans (2, 1)-(7, 6); each UV still lands on the same canvas spot.
    after = [c for u, v in drawable.uvs for c in (2 + u * 5, 1 + v * 5)]
    assert after == pytest.approx(before)
    assert decode_texture(doc.textures["textures/d.png"]).shape == (5, 5, 4)


def test_missing_textures_are_found_located_and_relinked(tmp_path):
    doc = _rigged(tmp_path)
    del doc.textures[doc.drawable("arm").texture]
    doc.textures[doc.drawable("hat").texture] = b"not a png"
    missing = {m.texture: m for m in find_missing_textures(doc)}
    assert missing["textures/arm.png"].reason == "missing"
    assert missing["textures/arm.png"].expected_size == (4, 6)
    assert missing["textures/hat.png"].reason == "unreadable"

    library = tmp_path / "library" / "nested"
    library.mkdir(parents=True)
    Image.fromarray(np.full((12, 8, 4), 200, dtype=np.uint8)).save(library / "ARM.png")
    Image.fromarray(np.full((3, 7, 4), 50, dtype=np.uint8)).save(library / "hat.webp")
    found = locate_textures(missing.values(), [tmp_path / "library", tmp_path / "absent"])
    assert found["textures/arm.png"] == [library / "ARM.png"]
    assert found["textures/hat.png"] == [library / "hat.webp"]

    preview = preview_relink(doc, "textures/arm.png", library / "ARM.png")
    assert preview.image_size == (8, 12)
    assert preview.notes == ("size_differs",)
    relink_texture(doc, "textures/arm.png", library / "ARM.png")
    relink_texture(doc, "textures/hat.png", library / "hat.webp")
    assert find_missing_textures(doc) == []
    stored = Image.open(io.BytesIO(doc.textures["textures/hat.png"]))
    assert stored.format == "PNG"
    with pytest.raises(ValueError, match="not a readable image"):
        preview_relink(doc, "textures/arm.png", tmp_path / "v1.psd")


def test_update_inside_a_transaction_undoes_completely(tmp_path):
    doc = _rigged(tmp_path)
    session = DocumentSession()
    session.bind(doc)
    original = to_zip_bytes(doc)
    update = _plan(tmp_path, doc)
    with session.transaction("Update art"):
        apply_asset_update(session.document, update)
    assert session.dirty
    session.undo()
    assert to_zip_bytes(session.document) == original
    session.redo()
    assert session.document.drawable("eye") is not None
