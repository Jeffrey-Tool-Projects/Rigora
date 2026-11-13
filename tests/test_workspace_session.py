"""File and session behavior with real documents, without a native GL surface."""
from types import MethodType, SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

from rigora.puppet.document import Parameter, PuppetDocument
from rigora.puppet.document_io import save_puppet
from rigora.puppet.document_session import DocumentSession
from rigora.puppet.workspace import PuppetWorkspace


class Host(SimpleNamespace):
    def __getattr__(self, name):
        return MethodType(getattr(PuppetWorkspace, name), self)


@pytest.fixture
def editor(tmp_path):
    session = DocumentSession()
    doc = PuppetDocument(parameters=[Parameter("x", -1, 1, 0)])
    session.bind(doc, saved=True)
    messages = []
    host = Host(
        session=session, _recovery=None,
        _canvas=SimpleNamespace(document=lambda: session.document,
                                end_mesh_edit_drag=lambda: None, _mesh_edit_target=None),
        _motion_recorder=SimpleNamespace(stop=lambda: None, cancel=lambda: None),
        _batch_exporter=SimpleNamespace(stop=lambda: None),
        _recorder=SimpleNamespace(stop=lambda: None),
        _status_label=SimpleNamespace(setText=messages.append),
        _document_state_label=SimpleNamespace(setText=lambda value: None),
        _undo_action=SimpleNamespace(setEnabled=lambda value: None),
        _redo_action=SimpleNamespace(setEnabled=lambda value: None),
        setWindowModified=lambda value: None, setWindowTitle=lambda value: None,
    )
    host._canvas.load_document = lambda doc: host._session_document_loaded()
    host.messages = messages
    return host


def edit(host):
    with host.session.transaction("Rename") as doc:
        doc.parameters[0].id = "edited"


@pytest.mark.parametrize("choice,success", [
    (QMessageBox.StandardButton.Cancel, False),
    (QMessageBox.StandardButton.Discard, True),
    (QMessageBox.StandardButton.Save, True),
])
def test_open_unsaved_choices(editor, tmp_path, monkeypatch, choice, success):
    original = tmp_path / "original.puppet"
    editor.session.save(original)
    target = tmp_path / "new.puppet"
    save_puppet(PuppetDocument(size=(100, 100)), target)
    edit(editor)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: choice)
    assert editor.open_puppet(target) is success
    if success:
        assert editor.session.path == target
        assert not editor.session.dirty
    else:
        assert editor.session.path == original
        assert editor.session.document.parameters[0].id == "edited"
        assert editor.session.dirty


def test_unsaved_save_failure_prevents_replacement(editor, tmp_path, monkeypatch):
    target = tmp_path / "new.puppet"
    save_puppet(PuppetDocument(), target)
    editor.session.path = tmp_path / "protected.puppet"
    edit(editor)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Save)
    monkeypatch.setattr("rigora.puppet.workspace_files.save_puppet",
                        lambda *args: (_ for _ in ()).throw(PermissionError("denied")))
    assert not editor.open_puppet(target)
    assert editor.session.document.parameters[0].id == "edited"
    assert editor.session.dirty


def test_import_result_rejected_after_document_switch(editor, monkeypatch):
    def convert(*args, **kwargs):
        editor.session.bind(PuppetDocument(size=(200, 200)), saved=True)
        return PuppetDocument(size=(99, 99))
    monkeypatch.setattr("rigora.puppet.workspace_import.puppet_from_png", convert)
    assert not editor.import_png("source.png")
    assert editor.session.document.size == (200, 200)
    assert "Retry" in editor.messages[-1]


def test_partial_cubism_import_failure_preserves_document(editor, monkeypatch):
    from rigora.puppet.cubism_import import CubismFormatError
    def broken(document, path):
        document.parameters.clear()
        raise CubismFormatError("invalid asset")
    editor._dispatch_cubism_import = broken
    editor._show_cubism_error_dialog = lambda error: None
    assert not editor.import_cubism("asset.model3.json")
    assert editor.session.document.parameters[0].id == "x"
    assert not editor.session.dirty


def test_stale_recording_does_not_append_to_new_document(editor):
    from rigora.puppet.document import Motion
    editor._motion_record_revision = editor.session.revision
    editor.session.bind(PuppetDocument(), saved=True)
    editor._on_motion_recorded(Motion("old", 1))
    assert not editor.session.document.motions
    assert not editor.session.dirty


def test_document_edit_stops_exports_before_next_frame(editor):
    calls = []
    editor._batch_exporter.stop = lambda: calls.append("batch")
    editor._recorder.stop = lambda: calls.append("recording")
    editor.session.document.parameters[0].id = "changed"
    editor._commit_edit("Rename")
    assert calls == ["batch", "recording"]
    editor._commit_edit("No change")
    assert calls == ["batch", "recording"]


def test_timeline_drag_is_one_undo_step(editor, qapp):
    from PySide6.QtCore import QPointF
    from rigora.puppet.document import Motion, MotionSegment, MotionTrack
    from rigora.puppet.motion_timeline import MotionTimelineWidget
    track = MotionTrack("x", [MotionSegment("linear", (0.0, 0.0), (1.0, 1.0))])
    motion = Motion("edit", 1.0, tracks=[track])
    editor.session.document.motions.append(motion)
    editor.session.bind(editor.session.document, saved=True)
    player = SimpleNamespace(motion=lambda: motion, elapsed=lambda: 0.5, seek=lambda t: None)
    editor._motion_dock = SimpleNamespace(player=lambda: player)
    view = MotionTimelineWidget()
    view.set_track(motion, track)
    view.edit_started.connect(editor._begin_timeline_edit)
    view.track_modified.connect(editor._on_timeline_edit_committed)
    view.edit_finished.connect(editor._finish_timeline_edit)
    try:
        view.edit_started.emit()
        view.update_endpoint(0, QPointF(300, 120))
        view.update_endpoint(0, QPointF(400, 150))
        assert not editor.session.can_undo
        view.edit_finished.emit()
        assert editor.session.undo()
        assert editor.session.document.motions[0].tracks[0].segments[0].p1 == (1.0, 1.0)
        assert not editor.session.can_undo and not editor.session.dirty
    finally:
        view.deleteLater()
