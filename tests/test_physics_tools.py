"""R2.5: physics chain editing, mapping, presets and limit assessment."""
from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QLabel, QTableWidgetItem, QWidget

from rigora.puppet.document import Parameter, PhysicsParticle, PhysicsRig, PuppetDocument
from rigora.puppet.document_io import from_zip_bytes, to_zip_bytes
from rigora.puppet.document_session import DocumentSession
from rigora.puppet.physics import PhysicsEngine
from rigora.puppet.physics_dialog import PhysicsDialog
from rigora.puppet.physics_tools import (
    BUILTIN_PRESETS,
    PresetStore,
    apply_preset,
    assess_limits,
    remove_rig,
    rig_to_preset,
    rig_warnings,
    upsert_rig,
    validate_rig,
)
from rigora.puppet.workspace_rig_tools import PuppetRigToolsMixin


def doc() -> PuppetDocument:
    return PuppetDocument(
        parameters=[Parameter("ParamAngleX", -30, 30, 0), Parameter("ParamHair", -1, 1, 0),
                    Parameter("ParamTail", 0, 1, 0)],
        physics_rigs=[PhysicsRig("hair", "ParamAngleX", "ParamHair",
                                 [PhysicsParticle() for _ in range(3)])])


def test_validation_lists_every_problem():
    d = doc()
    bad = PhysicsRig("x", "Missing", "Missing", [PhysicsParticle(mass=0, damping=1, spring=-1)])
    problems = validate_rig(d, bad)
    assert len(problems) == 6
    assert validate_rig(d, d.physics_rigs[0]) == []
    twin = PhysicsRig("twin", "ParamTail", "ParamHair", [PhysicsParticle()])
    d.physics_rigs.append(twin)
    assert rig_warnings(d, twin) == ["another chain also drives 'ParamHair'; the later one wins"]


def test_upsert_and_remove_keep_document_consistent():
    d = doc()
    with pytest.raises(ValueError, match="does not exist"):
        upsert_rig(d, "hair", input_param="Nope", output_param="ParamHair", chain=[])
    assert len(d.physics_rigs[0].chain) == 3                # unchanged after a failure
    upsert_rig(d, "tail", input_param="ParamAngleX", output_param="ParamTail",
               chain=BUILTIN_PRESETS["hair_long"]["chain"], gravity=(1.0, -5.0))
    assert [r.id for r in d.physics_rigs] == ["hair", "tail"]
    assert d.physics_rigs[1].gravity == (1.0, -5.0)
    upsert_rig(d, "hair", input_param="ParamAngleX", output_param="ParamHair",
               chain=[{"mass": 2, "damping": 0.5, "spring": 3}])
    assert d.physics_rigs[0].chain == [PhysicsParticle(2.0, 0.5, 3.0)]
    assert remove_rig(d, "tail") and not remove_rig(d, "tail")
    reopened = from_zip_bytes(to_zip_bytes(d))
    assert reopened.physics_rigs[0].chain == d.physics_rigs[0].chain


def test_presets_round_trip_and_reject_bad_files(tmp_path):
    store = PresetStore(tmp_path / "presets.json")
    assert store.names()[:3] == ["hair_short", "hair_long", "accessory"]
    d = doc()
    store.save("my_hair", rig_to_preset(d.physics_rigs[0]))
    assert "my_hair" in store.names()
    with pytest.raises(ValueError):
        store.save("hair_long", rig_to_preset(d.physics_rigs[0]))
    with pytest.raises(ValueError):
        store.save("x", {"chain": [{}], "gravity": [0, 0]})
    apply_preset(d, "hair", store.get("accessory"))
    assert len(d.physics_rigs[0].chain) == 2
    assert d.physics_rigs[0].output_param == "ParamHair"      # mapping kept
    data = json.loads((tmp_path / "presets.json").read_text(encoding="utf-8"))
    data["presets"]["broken"] = {"chain": "x"}
    (tmp_path / "presets.json").write_text(json.dumps(data), encoding="utf-8")
    assert "broken" not in store.names()
    (tmp_path / "presets.json").write_text("{bad json", encoding="utf-8")
    assert store.names() == list(BUILTIN_PRESETS)


def test_assessment_reports_needs_without_changing_behaviour():
    d = doc()
    reference = PhysicsEngine()
    reference.bind_document(d)
    before = [reference.step(1 / 60, {"ParamAngleX": 30.0})["ParamHair"] for _ in range(5)]
    calm_doc = doc()
    calm_doc.parameters[0] = Parameter("ParamAngleX", -1, 1, 0)
    calm = assess_limits(calm_doc, "hair")
    assert calm.needs == () and calm.settle_seconds is not None
    assert "output_clipped" in assess_limits(d, "hair").needs   # ±30 px saturates the tip
    loose = doc()
    loose.parameters[0] = Parameter("ParamAngleX", -3000, 3000, 0)
    loose.parameters[2] = Parameter("ParamTail", 0, 1, 0)
    upsert_rig(loose, "hair", input_param="ParamAngleX", output_param="ParamTail",
               chain=[{"mass": 1, "damping": 0.0, "spring": 0.5}] * 4)
    wild = assess_limits(loose, "hair")
    assert "output_clipped" in wild.needs
    assert "output_outside_parameter_range" in wild.needs
    assert wild.output_min < 0
    again = PhysicsEngine()
    again.bind_document(d)
    assert [again.step(1 / 60, {"ParamAngleX": 30.0})["ParamHair"] for _ in range(5)] == before
    with pytest.raises(ValueError):
        assess_limits(d, "nope")


def test_dialog_edits_a_working_copy(qapp, tmp_path):
    d = doc()
    parent = QWidget()
    dialog = PhysicsDialog(parent, d, PresetStore(tmp_path / "p.json"))
    dialog.table.setItem(0, 2, QTableWidgetItem("20"))
    assert dialog.store_current()
    assert d.physics_rigs[0].chain[0].spring == 12.0          # document untouched
    assert dialog.result_rigs()[0].chain[0].spring == 20.0
    dialog.table.setItem(0, 0, QTableWidgetItem("heavy"))
    assert dialog.store_current() is False
    assert "number" in dialog.message.text()
    dialog.table.setItem(0, 0, QTableWidgetItem("1"))
    dialog.particle_count.setValue(5)
    assert dialog.store_current() and len(dialog.result_rigs()[0].chain) == 5
    assert dialog.save_preset_as("five")
    assert "five" in dialog.presets.names()
    result = dialog.assess_current()
    assert result is not None and "clipped" in dialog.message.text()
    dialog._new_chain()   # noqa: SLF001
    assert [r.output_param for r in dialog.result_rigs()] == ["ParamHair", "ParamAngleX"]
    parent.deleteLater()


class _Workspace(PuppetRigToolsMixin, QWidget):
    def __init__(self, document):
        super().__init__()
        self.session = DocumentSession()
        self.session.bind(document, path="p.puppet", saved=True)
        self._canvas = type("C", (), {"document": lambda s: self.session.document,
                                      "load_document": lambda s, d: None})()
        self._status_label = QLabel(self)

    def _begin_document_work(self):
        return self.session.revision

    def _update_session_actions(self):
        pass

    def _announce(self, key, fallback, **fmt):
        self._status_label.setText(fallback.format(**fmt))


def test_apply_physics_is_validated_and_undoable(qapp):
    ws = _Workspace(doc())
    rigs = [PhysicsRig("hair", "ParamAngleX", "ParamHair", [PhysicsParticle(spring=30)])]
    assert ws.apply_physics_rigs(rigs) is True
    assert ws.session.document.physics_rigs[0].chain[0].spring == 30
    ws.session.undo()
    assert len(ws.session.document.physics_rigs[0].chain) == 3
    assert ws.apply_physics_rigs([PhysicsRig("bad", "Nope", "ParamHair", [])]) is False
    assert "bad: input parameter" in ws._status_label.text()   # noqa: SLF001
    assert not ws.session.dirty
    ws.deleteLater()
