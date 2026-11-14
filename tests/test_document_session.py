"""Authored history, rollback, save failures and stale work contracts."""
from copy import deepcopy

import pytest

from rigora.puppet.document import Parameter, PuppetDocument
from rigora.puppet.document_io import load_puppet
from rigora.puppet.document_session import DocumentSession
from rigora.puppet.recovery import RecoveryStore


def session_with_document(**limits):
    session = DocumentSession(**limits)
    session.bind(PuppetDocument(parameters=[Parameter("x", -1, 1, 0)]), saved=True)
    return session


def test_history_save_point_and_branch(tmp_path):
    session = session_with_document()
    with session.transaction("Rename") as doc:
        doc.parameters[0].id = "angle"
    assert session.dirty
    session.save(tmp_path / "saved.puppet")
    assert not session.dirty
    assert session.undo() and session.dirty
    assert session.document.parameters[0].id == "x"
    assert session.redo() and not session.dirty
    assert load_puppet(session.path) == session.document
    session.undo()
    with session.transaction("Another edit") as doc:
        doc.parameters[0].id = "y"
    assert not session.can_redo


def test_composite_transaction_and_failure_restore():
    session = session_with_document()
    original = deepcopy(session.document)
    with session.transaction("Composite") as doc:
        doc.parameters[0].id = "a"
        with session.transaction("Child"):
            doc.display_names["a"] = "Angle"
    assert session.undo()
    assert session.document == original
    assert not session.can_undo
    with pytest.raises(ValueError, match="failed"), session.transaction("Invalid") as doc:
        doc.parameters.clear()
        raise ValueError("failed")
    assert session.document == original
    assert not session.dirty


def test_gesture_checkpoint_and_budget():
    session = session_with_document(max_history_steps=2)
    for value in (0.1, 0.2, 0.3):
        session.document.parameters[0].default = value
    session.checkpoint("Drag")
    assert session.undo()
    assert session.document.parameters[0].default == 0
    for value in (0.4, 0.5, 0.6):
        with session.transaction("Step") as doc:
            doc.parameters[0].default = value
    assert session.undo() and session.undo() and not session.undo()
    small = session_with_document(max_history_bytes=1)
    with small.transaction("Too large") as doc:
        doc.parameters.clear()
    assert small.dirty and not small.can_undo and small.history_bytes == 0


def test_failed_save_keeps_file_and_dirty(tmp_path, monkeypatch):
    session = session_with_document()
    path = tmp_path / "model.puppet"
    session.save(path)
    before = path.read_bytes()
    with session.transaction("Edit") as doc:
        doc.parameters[0].id = "changed"
    def fail(_doc, temporary):
        temporary.write_bytes(b"partial")
        raise OSError("disk failed")
    monkeypatch.setattr("rigora.puppet.document_io._write_puppet", fail)
    with pytest.raises(OSError, match="disk failed"):
        session.save()
    assert path.read_bytes() == before
    assert session.dirty and session.path == path


def test_stale_revision_after_edit_undo_or_replacement():
    session = session_with_document()
    token = session.revision
    assert session.accepts(token)
    session.document.parameters[0].id = "edited"
    assert not session.accepts(token)
    session.checkpoint("Edit")
    session.undo()
    assert not session.accepts(token)
    token = session.revision
    session.bind(deepcopy(session.document), saved=True)
    assert not session.accepts(token)


def test_runtime_morph_cache_does_not_dirty_or_break_history():
    import numpy as np
    from rigora.puppet.document import Drawable
    session = session_with_document()
    drawable = Drawable("face", "face.png", [(0, 0)], [], [(0, 0)],
                        vertex_morphs=[{"parameter": "x", "delta_at_max": [(1, 1)]}])
    session.document.drawables.append(drawable)
    session.bind(session.document, saved=True)
    drawable.vertex_morphs[0]["_np_delta_at_max"] = np.array([[1, 1]])
    drawable._np_rest_vertices = np.array([[0, 0]])
    assert not session.dirty
    assert not session.checkpoint("Playback")
    with session.transaction("Mesh") as doc:
        doc.drawables[0].vertices[0] = (5, 6)
    assert session.undo() and not session.dirty
    assert not hasattr(session.document.drawables[0], "_np_rest_vertices")


def test_recovery_isolation_corruption_and_original_path(tmp_path):
    session = session_with_document()
    session.save(tmp_path / "original.puppet")
    with session.transaction("Edit") as doc:
        doc.parameters[0].id = "recovered"
    root = tmp_path / "recovery"
    first = RecoveryStore(root)
    second = RecoveryStore(root)
    try:
        archive = first.write(session)
        assert second.candidates() == ([], [])
        first.close()
        candidates, errors = second.candidates()
        assert not errors and len(candidates) == 1
        assert candidates[0].source == session.path
        assert second.load(candidates[0]) == session.document
        assert load_puppet(session.path).parameters[0].id == "x"
        archive.write_bytes(b"broken")
        candidates, errors = second.candidates()
        assert not candidates and len(errors) == 1
    finally:
        first.close()
        second.close()


def test_recovery_write_failure_keeps_previous_archive(tmp_path, monkeypatch):
    session = session_with_document()
    session.document.parameters[0].id = "first"
    store = RecoveryStore(tmp_path / "recovery")
    try:
        archive = store.write(session)
        before = archive.read_bytes()
        session.document.parameters[0].id = "second"
        def fail(target, writer):
            raise PermissionError("denied")
        monkeypatch.setattr("rigora.puppet.recovery.replace_atomically", fail)
        with pytest.raises(PermissionError):
            store.write(session)
        assert archive.read_bytes() == before
        assert session.dirty
    finally:
        store.close()


@pytest.mark.parametrize("collection", ["parameters", "drawables", "deformers", "expressions",
                                        "pose_groups", "physics_rigs", "motions"])
def test_each_authored_collection_can_be_undone_and_saved(collection, tmp_path):
    from rigora.puppet.document import (
        Deformer, Drawable, Expression, ExpressionParam, Motion, PhysicsParticle, PhysicsRig,
        PoseGroup,
    )
    document = PuppetDocument(
        parameters=[Parameter("x", -1, 1, 0)],
        drawables=[Drawable("d", "textures/d.png", [(0, 0)], [], [(0, 0)],
                            bone_weights={"bone": [1.0]})],
        deformers=[Deformer("bone", "bone_rotation", parent=None,
                           drawables=["d"], form={"angle": 0})],
        expressions=[Expression("smile", [ExpressionParam("x", 1)])],
        pose_groups=[PoseGroup("pose", ["d"])],
        physics_rigs=[PhysicsRig("hair", "x", "x", [PhysicsParticle()])],
        motions=[Motion("idle", 1.0)],
    )
    session = DocumentSession()
    session.bind(document, saved=True)
    original = deepcopy(document)
    with session.transaction(f"Clear {collection}"):
        getattr(document, collection).clear()
    assert session.dirty and session.undo()
    assert session.document == original
    assert session.redo() and not getattr(document, collection)
    assert session.undo()
    session.save(tmp_path / "roundtrip.puppet")
    assert load_puppet(session.path) == session.document


def test_recovery_after_process_exit(tmp_path):
    import subprocess
    import sys
    root = tmp_path / "recovery"
    script = (
        "from pathlib import Path; import os, sys; "
        "from rigora.puppet.document_session import DocumentSession; "
        "from rigora.puppet.document import PuppetDocument; "
        "from rigora.puppet.recovery import RecoveryStore; "
        "session = DocumentSession(); session.bind(PuppetDocument(size=(123, 456))); "
        "store = RecoveryStore(Path(sys.argv[1])); store.write(session); os._exit(0)"
    )
    subprocess.run([sys.executable, "-c", script, str(root)], check=True, timeout=20)
    store = RecoveryStore(root)
    try:
        candidates, errors = store.candidates()
        assert not errors and len(candidates) == 1
        assert store.load(candidates[0]).size == (123, 456)
    finally:
        store.close()
