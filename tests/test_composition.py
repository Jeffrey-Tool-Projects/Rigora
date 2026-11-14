"""R3.2: multi-track clip semantics, storage and downgrade behaviour."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from rigora.puppet.composition import (
    bake_composition,
    clip_envelope,
    clip_time,
    composition_to_json,
    parse_composition,
    sample_composition,
    validate_composition,
)
from rigora.puppet.document import (
    Clip,
    Composition,
    CompositionLayer,
    Motion,
    MotionSegment,
    MotionTrack,
    Parameter,
    PuppetDocument,
)
from rigora.puppet.document_io import PuppetFormatError, from_zip_bytes, to_zip_bytes
from rigora.puppet.format_schema import SCHEMAS
from rigora.puppet.motion_sampler import sample_motion


def ramp(name: str, param: str, start: float, end: float, duration: float = 1.0) -> Motion:
    return Motion(name, duration, tracks=[MotionTrack(param, [
        MotionSegment("linear", (0.0, start), (duration, end))])])


def doc(*layers: CompositionLayer, duration: float = 4.0) -> PuppetDocument:
    return PuppetDocument(
        parameters=[Parameter("A", -10, 10, 0), Parameter("B", 0, 1, 0.5)],
        motions=[ramp("up", "A", 0, 10), ramp("down", "A", 10, 0), ramp("hold5", "A", 5, 5),
                 ramp("b", "B", 0, 1)],
        compositions=[Composition("show", duration, list(layers))],
    )


def sample(d, t):
    return sample_composition(d, d.compositions[0], t)


def test_single_clip_matches_its_motion_and_is_inactive_outside():
    d = doc(CompositionLayer("base", [Clip("up", start=1.0)]))
    assert sample(d, 1.5)["A"] == pytest.approx(sample_motion(d.motions[0], 0.5)["A"])
    assert sample(d, 0.5) == {}
    assert sample(d, 2.5) == {}


def test_loop_offset_and_hold():
    d = doc()
    motion = d.motions[0]
    assert clip_time(Clip("up", start=1, offset=0.25), motion, 1.5) == 0.75
    assert clip_time(Clip("up", start=0, loop=True, length=3), motion, 2.5) == pytest.approx(0.5)
    assert clip_time(Clip("up", start=0, length=3), motion, 2.5) == 1.0


def test_fades_weights_and_mutes_shape_the_envelope():
    motion = doc().motions[0]
    clip = Clip("up", start=0, length=2, fade_in=0.5, fade_out=1.0, weight=0.8)
    assert clip_envelope(clip, motion, 0.25) == pytest.approx(0.4)
    assert clip_envelope(clip, motion, 1.5) == pytest.approx(0.4)
    assert clip_envelope(Clip("up", muted=True), motion, 0.5) == 0.0


def test_half_weight_clip_moves_halfway_from_the_default():
    d = doc(CompositionLayer("base", [Clip("hold5", weight=0.5)]))
    assert sample(d, 0.5)["A"] == pytest.approx(2.5)


def test_later_clip_crossfades_over_earlier_within_a_layer():
    d = doc(CompositionLayer("base", [Clip("hold5", length=4),
                                      Clip("down", start=1, fade_in=1.0)]))
    assert sample(d, 0.5)["A"] == pytest.approx(5.0)
    halfway = sample(d, 1.5)["A"]                  # down at 5, fade 0.5 over hold 5
    assert halfway == pytest.approx(5.0)
    assert sample(d, 1.75)["A"] == pytest.approx(0.75 * 2.5 + 0.25 * 5.0)


def test_layer_priority_override_and_additive():
    over = CompositionLayer("top", [Clip("hold5")], weight=0.5)
    base = CompositionLayer("base", [Clip("down")])
    d = doc(base, over)
    assert sample(d, 0.0)["A"] == pytest.approx(10 + (5 - 10) * 0.5)
    additive = CompositionLayer("add", [Clip("hold5")], blend="additive")
    d = doc(base, additive)
    assert sample(d, 0.0)["A"] == pytest.approx(10.0)          # 10 + 5 clamped to the range
    assert sample(d, 0.9)["A"] == pytest.approx(min(10.0, 1.0 + 5.0))
    d = doc(base, CompositionLayer("muted", [Clip("hold5")], muted=True))
    assert sample(d, 0.0)["A"] == pytest.approx(10.0)


def test_layers_on_different_parameters_combine():
    d = doc(CompositionLayer("a", [Clip("up")]), CompositionLayer("b", [Clip("b")]))
    assert set(sample(d, 0.5)) == {"A", "B"}


def test_bake_matches_live_sampling_and_plays_like_a_motion():
    d = doc(CompositionLayer("base", [Clip("up", loop=True, length=4)]), duration=2.0)
    baked = bake_composition(d, d.compositions[0], fps=20)
    assert baked.duration == 2.0 and baked.name == "show (baked)"
    for t in (0.0, 0.33, 1.25, 1.95):
        assert sample_motion(baked, t)["A"] == pytest.approx(sample(d, t)["A"], abs=0.6)
    with pytest.raises(ValueError):
        bake_composition(d, d.compositions[0], fps=0)


def test_validation_reports_every_problem():
    d = doc(CompositionLayer("x", [Clip("ghost", start=-1, length=0)], blend="mix"),
            CompositionLayer("x"), duration=0)
    problems = validate_composition(d, d.compositions[0])
    assert len(problems) == 6


def test_round_trip_schema_and_downgrade(tmp_path):
    layer = CompositionLayer("base", [Clip("up", start=0.5, fade_in=0.2, loop=True)],
                             blend="additive", weight=0.7)
    d = doc(layer)
    reopened = from_zip_bytes(to_zip_bytes(d))
    assert reopened.compositions == d.compositions
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(to_zip_bytes(d))).read("puppet.json"))
    from rigora.puppet.format_schema import validate
    assert validate(manifest, SCHEMAS["puppet"]) == []
    assert "length" not in manifest["compositions"][0]["layers"][0]["clips"][0]
    plain = doc()
    plain.compositions = []
    plain_manifest = json.loads(zipfile.ZipFile(io.BytesIO(to_zip_bytes(plain))).read("puppet.json"))
    assert "compositions" not in plain_manifest             # files without them are unchanged
    with pytest.raises(PuppetFormatError):
        parse_composition({"name": "x", "duration": "long"})
    with pytest.raises(PuppetFormatError):
        parse_composition({"name": "x", "layers": [{"id": "l", "blend": "mix"}]})
    assert parse_composition(composition_to_json(d.compositions[0])) == d.compositions[0]


def test_dialog_bake_button_saves_and_names_the_composition(qapp):
    from rigora.puppet.composition_dialog import CompositionDialog
    document = doc(CompositionLayer("base", [Clip("up")]))
    dialog = CompositionDialog(None, document)
    dialog.list.setCurrentRow(0)
    dialog._bake()                                              # noqa: SLF001
    assert dialog.bake_requested == document.compositions[0].name
    assert dialog.result_code() == dialog.DialogCode.Accepted
    dialog.deleteLater()


def test_workspace_bakes_after_applying_the_dialog(monkeypatch):
    from types import SimpleNamespace

    from rigora.puppet import composition_dialog
    from rigora.puppet.workspace_animation import PuppetAnimationMixin
    calls = []

    class Dialog:
        def __init__(self, _parent, _document):
            self.bake_requested, self.preview_requested = "show", None

        def result(self):
            return ["compositions"]

        def deleteLater(self):   # noqa: N802 - Qt API
            pass

    monkeypatch.setattr(composition_dialog, "CompositionDialog", Dialog)
    host = SimpleNamespace(
        _canvas=SimpleNamespace(document=lambda: object()),
        preview_composition=None, _run_animation_dialog=lambda _d: True,
        apply_compositions=lambda result: calls.append(("apply", result)) or True,
        bake_composition_to_motion=lambda name: calls.append(("bake", name)))
    assert PuppetAnimationMixin.edit_compositions_via_dialog(host)
    assert calls == [("apply", ["compositions"]), ("bake", "show")]
