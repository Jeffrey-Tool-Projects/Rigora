"""R2.6: diagnose → preview → apply → undo, with every finding located."""
from __future__ import annotations

from copy import deepcopy

from PySide6.QtWidgets import QLabel, QWidget

from rigora.puppet.document import Deformer, Drawable, PuppetDocument
from rigora.puppet.document_io import to_zip_bytes
from rigora.puppet.document_session import DocumentSession
from rigora.puppet.rig_doctor import apply_fixes, diagnose, preview_fixes
from rigora.puppet.rig_doctor_dialog import RigDoctorDialog
from rigora.puppet.standard_params import standard_parameters
from rigora.puppet.workspace_rig_tools import PuppetRigToolsMixin


def quad(drawable_id, x=0.0, *, extra_duplicate=False):
    vertices = [(x, 0.0), (x + 10, 0.0), (x + 10, 10.0), (x, 10.0)]
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
    indices = [0, 1, 2, 0, 2, 3]
    if extra_duplicate:
        vertices.append((x, 0.0))
        uvs.append((0, 0))
        indices += [4, 1, 2, 0, 0, 1]          # one triangle on the duplicate, one zero-area
    return Drawable(drawable_id, "textures/t.png", vertices, indices, uvs)


def rig() -> PuppetDocument:
    arm = quad("arm_l", 10)
    arm.bone_weights = {"b": [2.0, 2.0, 2.0, 2.0]}
    return PuppetDocument(
        size=(100, 100),
        drawables=[quad("body", 40, extra_duplicate=True), arm, quad("eye_l_open"),
                   quad("eye_l_close"), quad("head", 45)],
        deformers=[Deformer("lonely", "rotation", "ghost", ["nope"], {"angle": 0})],
        parameters=standard_parameters(),
        textures={"textures/t.png": b"png"},
    )


def test_diagnosis_covers_every_source_and_locates_parts():
    findings = {f.id: f for f in diagnose(rig())}
    assert findings["mesh:body"].location == "drawable:body"
    assert "zero-area" in findings["mesh:body"].message
    assert "duplicate" in findings["mesh:body"].message
    assert findings["weights:arm_l"].fixable
    assert findings["symmetry:arm_l"].message.endswith("a mirrored copy can be added")
    assert {"auto_rig:eyes", "auto_rig:head_tilt"} <= set(findings)
    validation = [f for f in findings.values() if f.kind == "validation"]
    assert any(f.location.startswith("deformer:lonely") for f in validation)
    assert not any(f.fixable for f in validation)
    assert not any("bone_weights" in f.id for f in validation)


def test_preview_changes_nothing_and_matches_apply():
    doc = rig()
    before = to_zip_bytes(doc)
    ids = ["mesh:body", "weights:arm_l", "symmetry:arm_l", "auto_rig:head_tilt",
           "auto_rig:eyes", "validation:0:x", "unknown"]
    preview = preview_fixes(doc, ids)
    assert to_zip_bytes(doc) == before
    assert preview.applied == ids[:5]
    assert "vertices 5→4" in preview.changed_drawables["body"]
    assert preview.changed_drawables["arm_l"] == "weights normalised"
    assert preview.added["drawables"] == ["arm_r"]
    assert preview.added["deformers"] == ["head_tilt"]
    applied = apply_fixes(doc, ids)
    assert applied.to_dict() == preview.to_dict()
    assert {f.id for f in diagnose(doc)} & set(ids) == set()


def test_auto_rig_is_not_offered_twice():
    doc = rig()
    apply_fixes(doc, ["auto_rig:head_tilt"])
    deformers = len(doc.deformers)
    assert "auto_rig:head_tilt" not in {f.id for f in diagnose(doc)}
    apply_fixes(doc, ["auto_rig:head_tilt"])
    assert len(doc.deformers) == deformers


class FakeCanvas:
    def __init__(self, session):
        self.session = session
        self.selection = None
        self.deformer = None

    def document(self):
        return self.session.document

    def load_document(self, _doc):
        pass

    def set_vertex_selection(self, drawable_id, indices):
        self.selection = (drawable_id, set(indices))

    def set_selected_deformer(self, deformer_id):
        self.deformer = deformer_id


class _Workspace(PuppetRigToolsMixin, QWidget):
    def __init__(self, document):
        super().__init__()
        self.session = DocumentSession()
        self.session.bind(document, path="d.puppet", saved=True)
        self._canvas = FakeCanvas(self.session)
        self._bone_tree_dock = type("Dock", (), {"select_deformer": lambda s, i: None})()
        self._status_label = QLabel(self)
        self.configure = None

    def _begin_document_work(self):
        return self.session.revision

    def _update_session_actions(self):
        pass

    def _announce(self, key, fallback, **fmt):
        self._status_label.setText(fallback.format(**fmt))

    def _run_rig_dialog(self, dialog):
        if self.configure:
            self.configure(dialog)
        return True


def test_dialog_preview_locate_and_single_undo(qapp):
    doc = rig()
    original = deepcopy(doc)
    ws = _Workspace(doc)

    def configure(dialog):
        dialog.set_checked("symmetry:arm_l", True)
        dialog.show_preview()
        assert "arm_r" in dialog.preview_label.text()
        dialog.table.setCurrentCell(0, 3)
        dialog._locate_selected()   # noqa: SLF001

    ws.configure = configure
    assert ws.run_rig_doctor_via_dialog() is True
    assert ws._canvas.selection[0] == "body"   # noqa: SLF001
    assert ws.session.document.drawable("arm_r") is not None
    assert len(ws.session.document.drawable("body").vertices) == 4
    assert "Applied 3 fixes" in ws._status_label.text()   # noqa: SLF001
    ws.session.undo()
    assert to_zip_bytes(ws.session.document) == to_zip_bytes(original)
    assert ws.locate_rig_part("deformer:lonely") is True
    assert ws._canvas.deformer == "lonely"   # noqa: SLF001
    assert ws.locate_rig_part("parameter:ParamAngleX") is False
    ws.deleteLater()


def test_dialog_lists_findings_with_default_ticks(qapp):
    parent = QWidget()
    findings = diagnose(rig())
    dialog = RigDoctorDialog(parent, rig(), findings, lambda _location: None)
    assert dialog.table.rowCount() == len(findings)
    assert sorted(dialog.selected_fixes()) == ["mesh:body", "weights:arm_l"]
    parent.deleteLater()
