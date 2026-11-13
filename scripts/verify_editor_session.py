"""Real hidden editor acceptance, invoked by verify_gui.py's native GL worker."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


def check_editor_session(window, root: Path) -> dict:
    from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
    from rigora.puppet.document_io import load_puppet
    from rigora.puppet.document_session import DocumentSession, authored_copy
    from rigora.puppet.recovery import RecoveryStore

    def require(value, message):
        if not value:
            raise RuntimeError(message)

    editor = window.editor
    canvas = editor.canvas()
    session = editor.session
    saved = root / "editor-session.puppet"
    require(editor.save_puppet(saved), "Initial editor save failed")
    original = authored_copy(canvas.document())
    canvas.set_parameter_value("ParamAngleX", 15)
    require(not session.dirty, "Live parameter or runtime caches dirtied document")
    editor._add_parameter()
    require(session.dirty and session.can_undo, "Authoring was not recorded")
    editor.undo()
    require(not session.dirty, "Undo did not return to saved version")
    editor.redo()
    require(session.dirty, "Redo did not restore edit")
    editor.undo()

    canvas.set_mesh_edit_enabled(True)
    drawable = canvas.document().drawables[-1]
    x, y = drawable.vertices[0]
    require(canvas.begin_mesh_edit_at(x, y), "No vertex available for mesh edit")
    target, index = canvas._mesh_edit_target
    before = canvas.document().drawable(target).vertices[index]
    canvas.update_mesh_edit_drag(x + 2, y + 1)
    canvas.update_mesh_edit_drag(x + 4, y + 3)
    canvas.end_mesh_edit_drag()
    require(session.dirty, "Mesh drag was not recorded")
    editor.undo()
    require(canvas.document().drawable(target).vertices[index] == before,
            "Mesh undo did not restore vertex")
    require(not session.can_undo, "A single drag created multiple history entries")
    canvas.set_mesh_edit_enabled(False)

    with session.transaction("All authored collections") as document:
        document.parameters[0].default = document.parameters[0].max
        document.deformers[0].form["angle"] = 5.0
        document.drawables[0].opacity = 0.6
        document.drawables[0].bone_weights = {document.deformers[0].id: [1.0] * len(
            document.drawables[0].vertices)}
        document.expressions.clear()
        document.pose_groups.clear()
        document.physics_rigs.clear()
        document.motions[0].duration += 1.0
    changed = authored_copy(document)
    editor.undo()
    require(authored_copy(canvas.document()) == original, "Composite undo lost authored state")
    editor.redo()
    require(authored_copy(canvas.document()) == changed, "Composite redo lost authored state")
    editor._autosave()
    observer = RecoveryStore(root / "recovery")
    try:
        require(observer.candidates() == ([], []), "Live session recovery was offered")
        require(any(editor._recovery.directory.glob("*.puppet")), "No recovery copy was saved")
    finally:
        observer.close()

    before_bytes = saved.read_bytes()
    with patch("rigora.puppet.workspace_files.save_puppet",
               side_effect=PermissionError("read only")):
        require(not editor.save_puppet(saved), "Read-only save incorrectly succeeded")
    require(session.dirty and saved.read_bytes() == before_bytes, "Failed save changed save point")
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
        require(not editor.open_puppet(saved), "Cancelled open replaced document")
        require(not window.close(), "Cancelled close destroyed editor")
    require(authored_copy(canvas.document()) == changed, "Cancel lost edits")
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save), \
            patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
        session.path = None
        require(not editor.open_puppet(saved), "Cancelled Save As discarded edits")
    require(editor.save_puppet(saved), "Edited document save failed")
    require(editor.open_puppet(saved), "Edited document reopen failed")
    require(authored_copy(load_puppet(saved)) == authored_copy(canvas.document()),
            "Saved/reopened authored state differs")
    token = session.revision
    editor._add_parameter()
    require(not session.accepts(token), "Stale revision was accepted")
    editor.undo()
    require(not session.accepts(token), "Undo revived stale revision")
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
        editor._add_parameter()
        require(editor.open_puppet(saved), "Explicit discard did not open document")
    require(not session.dirty, "Reopened document marked dirty")
    orphan = DocumentSession()
    orphan.bind(authored_copy(session.document))
    orphan.document.parameters[0].default = orphan.document.parameters[0].min
    abandoned = RecoveryStore(root / "recovery")
    try:
        archive = abandoned.write(orphan)
    finally:
        abandoned.close()
    original_bytes = saved.read_bytes()
    with patch.object(QInputDialog, "getItem", side_effect=lambda *args: (args[3][0], True)):
        editor._recover_document()
    require(session.dirty and session.path is None, "Recovery did not create an unsaved document")
    require(authored_copy(session.document) == authored_copy(orphan.document),
            "Recovery choice loaded the wrong document")
    recovered_path = root / "recovered-save.puppet"
    with patch.object(QFileDialog, "getSaveFileName", return_value=(str(recovered_path), "")):
        require(editor.save_current_document(), "Recovered document could not be saved")
    require(saved.read_bytes() == original_bytes and archive.exists(),
            "Recovery changed the original file or destroyed its recovery source")
    return {"history": True, "mesh_gesture": True, "composite": True,
            "save_failure": True, "cancel_open_close": True, "cancel_save_as": True,
            "roundtrip": True, "stale_revision": True, "recovery_choice": True}
