"""R2.4: safe reparent, ordering, search, hide/lock, cycle checks and parameter tools."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QWidget

from rigora.puppet.bone_tree_dock import BoneTreeDock
from rigora.puppet.document import (
    BlendKey,
    Deformer,
    Expression,
    ExpressionParam,
    Parameter,
    ParameterBlend,
    ParameterKey,
    PuppetDocument,
)
from rigora.puppet.document_session import DocumentSession
from rigora.puppet.parameter_dock import ParameterDock
from rigora.puppet.rig_hierarchy import (
    ancestors,
    find_cycles,
    grouped_parameters,
    key_summary,
    missing_parents,
    move_deformer,
    parameter_group,
    reparent_deformer,
    search_deformers,
    set_parameter_range,
)
from rigora.puppet.runtime_deformer_order import topologically_sorted_deformers
from rigora.puppet.workspace_rig_tools import PuppetRigToolsMixin


def _rot(i, parent=None, drawables=()):
    return Deformer(i, "rotation", parent, list(drawables), {"anchor": [0, 0], "angle": 0})


def rig() -> PuppetDocument:
    return PuppetDocument(
        deformers=[_rot("root"), _rot("head", "root", ["face"]), _rot("hair", "head", ["bangs"]),
                   _rot("arm_l", "root"), _rot("arm_r", "root")],
        parameters=[
            Parameter("ParamAngleX", -30, 30, 0, [ParameterKey(-30, {"head": {"angle": -1}}),
                                                  ParameterKey(30, {"head": {"angle": 1}})]),
            Parameter("ParamEyeLOpen", 0, 1, 1), Parameter("ParamMouthOpenY", 0, 1, 0),
            Parameter("ParamHairFront", -1, 1, 0), Parameter("ParamBreath", 0, 1, 0),
            Parameter("Custom", 0, 1, 0),
        ],
        display_names={"Custom": "Glow"},
    )


def test_reparent_refuses_cycles_and_unknown_ids_without_changes():
    doc = rig()
    assert ancestors(doc, "hair") == ["head", "root"]
    with pytest.raises(ValueError, match="descendant"):
        reparent_deformer(doc, "root", "hair")
    with pytest.raises(ValueError, match="no deformer"):
        reparent_deformer(doc, "head", "ghost")
    assert doc.deformer("root").parent is None
    assert reparent_deformer(doc, "hair", "root") is True
    assert reparent_deformer(doc, "hair", "root") is False


def test_cycle_and_missing_parent_detection():
    doc = rig()
    doc.deformer("root").parent = "hair"
    doc.deformers.append(_rot("orphan", "gone"))
    assert find_cycles(doc) == [["root", "hair", "head"]]
    assert missing_parents(doc) == ["orphan"]
    assert len(topologically_sorted_deformers(doc.deformers)) == 6


def test_move_changes_sibling_application_order():
    doc = rig()
    assert move_deformer(doc, "arm_r", -1) is True
    order = [d.id for d in topologically_sorted_deformers(doc.deformers)
             if d.parent == "root"]
    assert order == ["head", "arm_r", "arm_l"]
    assert move_deformer(doc, "head", -5) is False
    assert move_deformer(doc, "arm_l", 3) is False


def test_search_matches_ids_types_and_drawables():
    doc = rig()
    assert search_deformers(doc, "BANGS") == ["hair"]
    assert search_deformers(doc, "arm") == ["arm_l", "arm_r"]
    assert len(search_deformers(doc, "")) == 5


def test_parameter_groups_filters_and_keys():
    doc = rig()
    assert parameter_group("ParamEyeLOpen") == "Eyes"
    assert parameter_group("ParamBreath") == "Body"
    assert grouped_parameters(doc) == {
        "Head": ["ParamAngleX"], "Eyes": ["ParamEyeLOpen"], "Mouth": ["ParamMouthOpenY"],
        "Body": ["ParamBreath"], "Hair": ["ParamHairFront"], "Other": ["Custom"]}
    assert grouped_parameters(doc, "glow") == {"Other": ["Custom"]}
    keys = key_summary(doc, "ParamAngleX")
    assert [(k.value, k.deformers, k.fields) for k in keys] == [
        (-30, ("head",), ("angle",)), (30, ("head",), ("angle",))]


def test_range_edit_refuses_to_strand_keys_blends_or_expressions():
    doc = rig()
    with pytest.raises(ValueError, match="-30, 30"):
        set_parameter_range(doc, "ParamAngleX", -10, 10, 0)
    doc.parameter_blends = [ParameterBlend("b", ["ParamMouthOpenY", "ParamAngleX"],
                                           [BlendKey([2.0, 0.0])])]
    with pytest.raises(ValueError, match="2"):
        set_parameter_range(doc, "ParamMouthOpenY", 0, 1, 0)
    doc.parameter_blends = []
    doc.expressions = [Expression("e", [ExpressionParam("ParamEyeLOpen", 2, "overwrite")])]
    with pytest.raises(ValueError):
        set_parameter_range(doc, "ParamEyeLOpen", 0, 1, 1)
    with pytest.raises(ValueError, match="below"):
        set_parameter_range(doc, "Custom", 1, 1, 1)
    with pytest.raises(ValueError, match="within"):
        set_parameter_range(doc, "Custom", 0, 1, 5)
    assert set_parameter_range(doc, "ParamAngleX", -45, 45, 5).default == 5


class FakeCanvas(QObject):
    document_loaded = Signal()
    parameters_changed = Signal()

    def __init__(self, document):
        super().__init__()
        self._document = document
        self.values = {}

    def document(self):
        return self._document

    def load_document(self, document):
        self._document = document
        self.document_loaded.emit()

    def parameter_values(self):
        return dict(self.values)

    def set_parameter_value(self, pid, value):
        self.values[pid] = value

    def reset_parameters(self):
        self.values = {}
        self.parameters_changed.emit()


def test_bone_dock_search_hide_lock_and_order(qapp):
    canvas = FakeCanvas(rig())
    dock = BoneTreeDock(canvas)
    changes = []
    dock.hierarchy_changed.connect(lambda: changes.append(True))
    dock.set_search_text("bangs")
    assert dock.visible_ids() == ["root", "head", "hair"]
    dock.set_search_text("")
    dock.set_hidden("arm_r", True)
    assert "arm_r" not in dock.visible_ids()
    dock.set_show_hidden(True)
    assert "arm_r" in dock.visible_ids()
    dock.set_locked("arm_l", True)
    assert dock.reparent("arm_l", "head") is False
    assert dock.move("arm_l", -1) is False
    assert dock.reparent("root", "hair") is False
    assert dock.move("arm_r", -1) is True and changes == [True]
    dock.select_deformer("hair")
    assert dock.selected_id() == "hair"
    canvas.document().deformer("root").parent = "hair"
    dock.rebuild()
    assert "Parent cycle" in dock.problems_text()
    assert len(dock.visible_ids()) == 5      # cycle members still listed, no hang
    dock.deleteLater()


class _Workspace(PuppetRigToolsMixin, QWidget):
    def __init__(self, document):
        super().__init__()
        self.session = DocumentSession()
        self.session.bind(document, path="r.puppet", saved=True)
        self._canvas = FakeCanvas(document)
        self._status_label = QLabel(self)
        self.answer = True

    def _begin_document_work(self):
        return self.session.revision

    def _update_session_actions(self):
        pass

    def _announce(self, key, fallback, **fmt):
        self._status_label.setText(fallback.format(**fmt))

    def set_key_at_current_slider(self, _pid):
        return True

    def _run_rig_dialog(self, dialog):
        from PySide6.QtWidgets import QDoubleSpinBox
        spins = dialog.findChildren(QDoubleSpinBox)
        spins[0].setValue(-60)
        spins[1].setValue(60)
        return self.answer


def test_parameter_dock_groups_filter_and_preview(qapp):
    canvas = FakeCanvas(rig())
    workspace = _Workspace(canvas.document())
    dock = ParameterDock(canvas, workspace=workspace)
    assert dock.group_names() == ["Head", "Eyes", "Mouth", "Body", "Hair", "Other"]
    dock.set_filter("mouth")
    assert dock.group_names() == ["Mouth"] and dock.slider_for("ParamAngleX") is None
    dock.preview_key("ParamAngleX", 30.0)
    assert canvas.values["ParamAngleX"] == 30.0
    dock.deleteLater()
    workspace.deleteLater()


def test_range_edit_is_one_undo_step_and_reports_failures(qapp):
    workspace = _Workspace(rig())
    assert workspace.edit_parameter_range_via_dialog("ParamAngleX") is True
    assert workspace.session.document.parameter("ParamAngleX").max == 60
    assert "-60..60" in workspace._status_label.text()   # noqa: SLF001
    workspace.session.undo()
    assert workspace.session.document.parameter("ParamAngleX").max == 30
    assert workspace.edit_parameter_range("ParamAngleX", -1, 1, 0) is False
    assert "failed" in workspace._status_label.text()   # noqa: SLF001
    assert not workspace.session.dirty
    workspace.answer = False
    assert workspace.edit_parameter_range_via_dialog("ParamAngleX") is False
    workspace.deleteLater()
