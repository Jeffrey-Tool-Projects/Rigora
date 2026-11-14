"""R2.7: reusable part templates with stated requirements and honest limits."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QWidget

from rigora.puppet.document import Drawable, Parameter, PuppetDocument
from rigora.puppet.document_io import from_zip_bytes, to_zip_bytes
from rigora.puppet.document_session import DocumentSession
from rigora.puppet.part_template_dialog import PartTemplateDialog
from rigora.puppet.part_templates import TEMPLATES, apply_template, check_template
from rigora.puppet.runtime import compose_all_drawables, resolve_drawable_opacity
from rigora.puppet.validator import validate
from rigora.puppet.workspace_rig_tools import PuppetRigToolsMixin


def quad(drawable_id, x0, y0, w=20, h=20):
    return Drawable(drawable_id, "textures/t.png",
                    [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)],
                    [0, 1, 2, 0, 2, 3], [(0, 0), (1, 0), (1, 1), (0, 1)])


def face() -> PuppetDocument:
    ids = {"face_base": (40, 20, 80, 90), "hair_main": (30, 10, 100, 40),
           "eyeL1": (55, 50), "eyeL2": (55, 50), "eyeR1": (85, 50), "eyeR2": (85, 50),
           "mouthA": (70, 80), "mouthB": (70, 80), "mouthV": (70, 80), "ribbon": (120, 20)}
    drawables = [quad(k, *v) for k, v in ids.items()]
    return PuppetDocument(size=(200, 200), drawables=drawables,
                          parameters=[Parameter("ParamAngleX", -30, 30, 0)],
                          textures={"textures/t.png": b"png"})


def test_every_template_states_requirements_and_parameters():
    for template in TEMPLATES.values():
        assert template.requirements and template.parameters and template.roles
        assert template.to_dict()["id"] == template.id


def test_checks_report_missing_roles_before_any_change():
    doc = face()
    problems, _ = check_template(doc, "eye_blink", {"left_open": ["eyeL1"]})
    assert problems == ["left eye needs both the open and the closed layer"]
    problems, _ = check_template(doc, "mouth_shapes", {"closed": ["ghost"]})
    assert "closed: no drawable ghost" in problems and any("open needs" in p for p in problems)
    problems, _ = check_template(doc, "eye_blink", {"left_open": ["eyeL1"],
                                                    "left_closed": ["eyeL1"]})
    assert any("used for both" in p for p in problems)
    assert check_template(doc, "nope", {})[0] == ["no template 'nope'"]
    with pytest.raises(ValueError):
        apply_template(doc, "sway", {})
    assert to_zip_bytes(doc) == to_zip_bytes(face())


def test_single_png_rig_gets_an_honest_warning():
    flat = PuppetDocument(drawables=[quad("character", 0, 0, 100, 100)])
    _problems, warnings = check_template(flat, "head_turn", {"head": ["character"]})
    assert any("cannot split a flat image" in w for w in warnings)
    assert any("no parallax" in w for w in warnings)


def test_eye_and_mouth_templates_cross_fade_layers():
    doc = face()
    apply_template(doc, "eye_blink", {"left_open": ["eyeL1"], "left_closed": ["eyeL2"]})
    apply_template(doc, "mouth_shapes", {"closed": ["mouthA"], "open": ["mouthB"],
                                         "a": ["mouthV"]})
    open_eye, closed_eye = doc.drawable("eyeL1"), doc.drawable("eyeL2")
    assert resolve_drawable_opacity(open_eye, {"ParamEyeLOpen": 0.0}) == 0.0
    assert resolve_drawable_opacity(closed_eye, {"ParamEyeLOpen": 0.0}) == 1.0
    assert resolve_drawable_opacity(doc.drawable("mouthB"), {"ParamMouthOpenY": 1.0}) == 1.0
    assert doc.parameter("ParamMouthForm") is not None
    assert not [i for i in validate(doc) if i.severity == "error"]


def test_head_turn_and_sway_move_geometry_and_round_trip():
    doc = face()
    added = apply_template(doc, "head_turn", {"head": ["face_base", "hair_main"],
                                              "features": ["eyeL1", "mouthA"]})
    assert added["deformers"] == ["head_tilt", "head_turn", "face_parallax"]
    apply_template(doc, "sway", {"parts": ["ribbon"]})
    rest = compose_all_drawables(doc, {"ParamAngleX": 0.0, "ParamAngleZ": 0.0})
    turned = compose_all_drawables(doc, {"ParamAngleX": 30.0, "ParamAngleZ": 0.0})
    head_shift = turned["face_base"][:, 0].mean() - rest["face_base"][:, 0].mean()
    eye_shift = turned["eyeL1"][:, 0].mean() - rest["eyeL1"][:, 0].mean()
    assert head_shift > 0 and eye_shift > head_shift          # features lead: parallax
    tilted = compose_all_drawables(doc, {"ParamAngleX": 0.0, "ParamAngleZ": 1.0})
    assert not np.allclose(tilted["eyeL1"], rest["eyeL1"])
    swayed = compose_all_drawables(doc, {"ParamSway": 1.0, "ParamAngleX": 0.0})
    assert not np.allclose(swayed["ribbon"], rest["ribbon"])
    assert doc.physics_rigs[-1].output_param == "ParamSway"
    assert not [i for i in validate(doc) if i.severity == "error"]
    reopened = from_zip_bytes(to_zip_bytes(doc))
    assert [d.id for d in reopened.deformers] == [d.id for d in doc.deformers]


class _Workspace(PuppetRigToolsMixin, QWidget):
    def __init__(self, document):
        super().__init__()
        self.session = DocumentSession()
        self.session.bind(document, path="t.puppet", saved=True)
        self._canvas = type("C", (), {"document": lambda s: self.session.document,
                                      "load_document": lambda s, d: None})()
        self._status_label = QLabel(self)

    def _begin_document_work(self):
        return self.session.revision

    def _update_session_actions(self):
        pass

    def _announce(self, key, fallback, **fmt):
        self._status_label.setText(fallback.format(**fmt))

    def _run_rig_dialog(self, dialog):
        dialog.select_template("eye_blink")
        dialog.set_role("left_open", ["eyeL1"])
        assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        dialog.set_role("left_closed", ["eyeL2"])
        assert dialog.refresh() == ([], [])
        return True


def test_dialog_flow_is_one_undo_step(qapp):
    ws = _Workspace(face())
    assert ws.part_templates_via_dialog() is True
    assert ws.session.document.drawable("eyeL1").opacity_keys
    assert "eye_blink applied" in ws._status_label.text()   # noqa: SLF001
    ws.session.undo()
    assert ws.session.document.drawable("eyeL1").opacity_keys is None
    parent = QWidget()
    dialog = PartTemplateDialog(parent, face())
    dialog.select_template("head_turn")
    dialog.set_role("head", ["face_base", "hair_main"])
    assert dialog.mapping() == {"head": ["face_base", "hair_main"]}
    assert "no parallax" in dialog.status.text()
    parent.deleteLater()
    ws.deleteLater()


def test_head_turn_reuses_an_existing_tilt_instead_of_stacking_one():
    doc = face()
    apply_template(doc, "head_turn", {"head": ["face_base", "hair_main"]})
    _problems, warnings = check_template(doc, "head_turn", {"head": ["face_base"],
                                                            "features": ["eyeL1"]})
    assert any("reuses the existing head tilt 'head_tilt'" in w for w in warnings)
    added = apply_template(doc, "head_turn", {"head": ["face_base"], "features": ["eyeL1"]})
    assert "head_tilt_2" not in [d.id for d in doc.deformers]
    assert added["deformers"][0] == "head_turn_2"
    assert "eyeL1" in doc.deformer("head_tilt").drawables
    partial = face()
    apply_template(partial, "head_turn", {"head": ["face_base"]})
    apply_template(partial, "head_turn", {"head": ["face_base", "hair_main"]})
    assert [d.id for d in partial.deformers if d.type == "rotation"] == ["head_tilt"]
    assert {"face_base", "hair_main"} <= set(partial.deformer("head_tilt").drawables)
