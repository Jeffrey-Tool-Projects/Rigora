"""Editor binding for document history, unsaved changes and recovery."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QInputDialog, QMessageBox

from rigora.puppet.document_session import DocumentSession
from rigora.puppet.recovery import RecoveryStore
from rigora.system.app_paths import app_dir
from rigora.system.settings import user_setting_dict


class PuppetSessionMixin:
    def _init_session(self) -> None:
        self.session = DocumentSession()
        self._recovery = None
        self._canvas.document_loaded.connect(self._session_document_loaded)
        self._canvas.edit_finished.connect(self._commit_edit)
        self._canvas.deformer_selection_changed.connect(self._session_selection_changed)
        self._recovery_timer = QTimer(self)
        self.set_autosave_interval(user_setting_dict.get("puppet_autosave_seconds", 60))
        self._recovery_timer.timeout.connect(self._autosave)

    def set_autosave_interval(self, seconds: int) -> None:
        if not isinstance(seconds, int) or not 0 <= seconds <= 86400:
            seconds = 60
        user_setting_dict["puppet_autosave_seconds"] = seconds
        if seconds:
            self._recovery_timer.start(seconds * 1000)
        else:
            self._recovery_timer.stop()

    def _configure_autosave(self) -> None:
        seconds, accepted = QInputDialog.getInt(
            self, "Autosave", "Recovery interval in seconds (0 disables autosave):",
            self._recovery_timer.interval() // 1000 if self._recovery_timer.isActive() else 0,
            0, 86400,
        )
        if accepted:
            self.set_autosave_interval(seconds)

    def _session_selection_changed(self, selected: str) -> None:
        self.session.select(selected or None)

    def _session_document_loaded(self) -> None:
        document = self._canvas.document()
        if document is not self.session.document:
            self._cancel_document_work()
            self.session.bind(document, saved=True)
        elif self.session.checkpoint("Edit document"):
            self._stop_document_outputs()
        self._update_session_actions()

    def _commit_edit(self, label: str = "Edit document") -> None:
        if self.session.checkpoint(label):
            self._stop_document_outputs()
        self._update_session_actions()

    def _update_session_actions(self) -> None:
        self._undo_action.setEnabled(self.session.can_undo)
        self._redo_action.setEnabled(self.session.can_redo)
        self.setWindowModified(self.session.dirty)
        name = self.session.path.name if self.session.path else "Untitled"
        self.setWindowTitle(f"{name}[*] - Rigora")
        self._document_state_label.setText(name + (" *" if self.session.dirty else ""))

    def _restore_history(self, *, redo: bool = False) -> None:
        self._motion_recorder.stop()
        self._stop_document_outputs()
        self._canvas.end_mesh_edit_drag()
        changed = self.session.redo() if redo else self.session.undo()
        if changed:
            selected = self.session.selection
            self._canvas.load_document(self.session.document)
            self._canvas.set_selected_deformer(selected)
            self._bone_tree_dock.select_deformer(selected)
        self._update_session_actions()

    def undo(self) -> None:
        self._restore_history()

    def redo(self) -> None:
        self._restore_history(redo=True)

    def confirm_discard_changes(self) -> bool:
        self._motion_recorder.stop()
        self._canvas.end_mesh_edit_drag()
        self._commit_edit()
        if not self.session.dirty:
            return True
        choice = QMessageBox.question(
            self, "Unsaved changes", "Save changes before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            return self.save_current_document()
        self._discarded_revision = self.session.revision
        self._discard_recovery()
        return True

    def _replace_document(self, document, *, path=None, saved=False) -> bool:
        if not self.confirm_discard_changes():
            return False
        self._discard_recovery()
        self._cancel_document_work()
        self.session.bind(document, path=path, saved=saved)
        self._canvas.load_document(document)
        return True

    def _accept_document_result(self, revision) -> bool:
        if self.session.accepts(revision):
            return True
        self._status_label.setText(
            "The document changed while the operation was running. Retry on the current document."
        )
        return False

    def _begin_document_work(self):
        self._canvas.end_mesh_edit_drag()
        self._commit_edit()
        return self.session.revision

    def _discard_recovery(self) -> None:
        if self._recovery is not None:
            try:
                self._recovery.discard(self.session)
            except OSError as exc:
                self._status_label.setText(f"Could not remove recovery file: {exc}")

    def _recovery_store(self) -> RecoveryStore:
        if self._recovery is None:
            self._recovery = RecoveryStore(app_dir() / "recovery")
        return self._recovery

    def _autosave(self) -> None:
        if (not self.session.dirty or self._canvas._mesh_edit_target is not None
                or getattr(self, "_timeline_editing", False)):
            return
        try:
            self._recovery_store().write(self.session)
        except (OSError, ValueError) as exc:
            self._status_label.setText(f"Recovery save failed: {exc}. Save As to another location.")

    def _recover_document(self) -> None:
        try:
            store = self._recovery_store()
            candidates, errors = store.candidates()
            if not candidates:
                self._status_label.setText(
                    "No recoverable documents." + (" " + "; ".join(errors) if errors else "")
                )
                return
            labels = [f"{index + 1}. {item.source or 'Untitled'} ({item.archive.stem[:8]})"
                      for index, item in enumerate(candidates)]
            selected, accepted = QInputDialog.getItem(
                self, "Recover document", "Choose a recovery copy:", labels, 0, False,
            )
            if not accepted:
                return
            candidate = candidates[labels.index(selected)]
            document = store.load(candidate)
            # A recovered document uses Save As so the original is never overwritten implicitly.
            if self._replace_document(document):
                self._status_label.setText(
                    f"Recovered {candidate.source or 'Untitled'}. Use Save As."
                )
        except (OSError, ValueError) as exc:
            self._status_label.setText(
                f"Recovery failed: {exc}. Keep the recovery file for inspection."
            )

    def _cancel_document_work(self) -> None:
        self._motion_recorder.cancel()
        self._stop_document_outputs()

    def _stop_document_outputs(self) -> None:
        self._batch_exporter.stop()
        self._recorder.stop()

    def _close_session(self) -> None:
        self._recovery_timer.stop()
        self._canvas.end_mesh_edit_drag()
        if getattr(self, "_discarded_revision", None) != self.session.revision:
            self._autosave()
        if self._recovery is not None:
            self._recovery.close()
