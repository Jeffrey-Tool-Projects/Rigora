"""R3.1: key selection, move, scale, copy / paste, snapping, tangents, filtering."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

from rigora.puppet.document import Motion, MotionSegment, MotionTrack
from rigora.puppet.motion_keys import (
    copy_keys,
    filter_tracks,
    keys,
    keys_in_range,
    move_keys,
    paste_keys,
    scale_keys,
    set_tangents,
    snap_time,
)
from rigora.puppet.motion_sampler import sample_track
from rigora.puppet.motion_timeline import MotionTimelineDialog


def track() -> MotionTrack:
    points = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0), (3.0, 1.0)]
    segments = [MotionSegment("linear", points[i], points[i + 1]) for i in range(3)]
    segments[1] = MotionSegment("cubic-bezier", points[1], points[2], (1.3, 1.0), (1.7, 0.0))
    return MotionTrack("ParamA", segments)


def chained(t: MotionTrack) -> bool:
    return all(a.p1 == b.p0 for a, b in zip(t.segments, t.segments[1:], strict=False))


def test_keys_and_range_selection():
    t = track()
    assert keys(t) == [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0), (3.0, 1.0)]
    assert keys_in_range(t, 2.5, 0.5) == [1, 2]
    assert keys_in_range(t, 0, 3, low=0.5) == [1, 3]
    assert snap_time(0.51, 0.1) == 0.5 and snap_time(0.51, None) == 0.51


def test_move_keeps_order_chain_and_carries_bezier_handles():
    t = track()
    assert move_keys(t, [1, 2], 0.25, 0.5, duration=3.0, value_range=(-1.0, 1.0)) == [1, 2]
    assert keys(t)[1] == (1.25, 1.0) and keys(t)[2] == (2.25, 0.5)
    bezier = t.segments[1]
    assert bezier.c0 == pytest.approx((1.55, 1.0)) and bezier.c1 == pytest.approx((1.95, 0.5))
    assert chained(t)
    move_keys(t, [1], 5.0, 0.0, duration=3.0)                   # clamped before key 2
    assert keys(t)[1][0] < keys(t)[2][0]
    move_keys(t, [3], 0.4, 0.0, duration=3.0, snap=0.25)
    assert keys(t)[3][0] == 3.0                                   # duration wins
    assert move_keys(t, [], 1, 1) == []


def test_scale_stretches_a_range_and_shifts_later_keys():
    t = track()
    assert scale_keys(t, [0, 1, 2], 0.5) == [0, 1, 2]
    assert [k[0] for k in keys(t)] == [0.0, 0.5, 1.0, 2.0]
    assert chained(t)
    with pytest.raises(ValueError, match="contiguous"):
        scale_keys(track(), [0, 2], 2.0)
    with pytest.raises(ValueError, match="duration"):
        scale_keys(track(), [1, 2], 3.0, duration=3.0)


def test_copy_paste_replaces_the_span_and_keeps_shapes():
    source = track()
    clip = copy_keys(source, [1, 2])
    target = MotionTrack("ParamA", [MotionSegment("linear", (0.0, 0.0), (3.0, 0.0))])
    pasted = paste_keys(target, clip, 1.0, duration=3.0)
    assert pasted == [1, 2]
    assert keys(target) == [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0), (3.0, 0.0)]
    assert target.segments[1].type == "cubic-bezier"
    assert sample_track(target, 1.5) == pytest.approx(sample_track(source, 1.5))
    assert chained(target)
    with pytest.raises(ValueError, match="duration"):
        paste_keys(target, clip, 2.5, duration=3.0)
    with pytest.raises(ValueError):
        copy_keys(source, [])


def test_tangent_modes_shape_neighbouring_segments():
    t = track()
    assert set_tangents(t, [1], "stepped") == [0, 1]
    assert [s.type for s in t.segments] == ["stepped", "stepped", "linear"]
    set_tangents(t, [1], "flat")
    assert t.segments[0].c1[1] == 1.0 and t.segments[1].c0[1] == 1.0
    rising = MotionTrack("ParamB", [MotionSegment("linear", (0.0, 0.0), (1.0, 1.0)),
                                    MotionSegment("linear", (1.0, 1.0), (2.0, 3.0))])
    set_tangents(rising, [1], "smooth")             # slope at key 1 = (3 - 0) / 2
    assert rising.segments[0].c1 == pytest.approx((2 / 3, 1.0 - 1.5 / 3))
    assert rising.segments[1].c0 == pytest.approx((4 / 3, 1.0 + 1.5 / 3))
    assert chained(t) and chained(rising)
    with pytest.raises(ValueError):
        set_tangents(t, [1], "wobbly")


def test_filter_tracks():
    motion = Motion("m", 3.0, tracks=[MotionTrack("ParamAngleX", []),
                                      MotionTrack("ParamEyeLOpen", [])])
    assert [t.param_id for t in filter_tracks(motion, "eye")] == ["ParamEyeLOpen"]


def test_dialog_operations_emit_one_edit_each(qapp):
    motion = Motion("m", 3.0, tracks=[track(), MotionTrack("ParamEyeLOpen", [
        MotionSegment("linear", (0.0, 0.0), (3.0, 1.0))])])
    parent = QWidget()
    dialog = MotionTimelineDialog(motion, parent, ranges={"ParamA": (-1.0, 1.0)})
    edits = []
    dialog.widget().track_modified.connect(lambda: edits.append(True))
    dialog.set_track_filter("eye")
    assert dialog.track_ids() == ["ParamEyeLOpen"]
    dialog.set_track_filter("")
    assert dialog.select_track("ParamA")
    view = dialog.widget()
    view.select_keys([1, 2])
    assert view.selected_keys() == [1, 2]
    assert dialog.move_selected(0.1, 0.0) and len(edits) == 1
    assert dialog.copy_selected()
    assert dialog.paste_at(0.0) and len(edits) == 2
    assert dialog.tangent_selected("linear") and len(edits) == 3
    assert len(keys(view.track())) >= 3
    view.select_keys([0, 2])
    assert not dialog.scale_selected(2.0)
    assert "contiguous" in dialog._key_status.text()   # noqa: SLF001
    assert len(edits) == 3
    view.select_keys([])
    assert not dialog.move_selected(0.1, 0.0)
    assert "nothing changed" in dialog._key_status.text() and len(edits) == 3   # noqa: SLF001
    dialog.set_snap(0.5)
    view.update_endpoint(0, view._scene_point(0.9, 0.0))   # noqa: SLF001
    assert keys(motion.tracks[0])[1][0] == 1.0
    parent.deleteLater()
