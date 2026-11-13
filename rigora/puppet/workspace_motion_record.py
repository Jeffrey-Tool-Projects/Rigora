"""User motion recording lifecycle and document insertion."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QInputDialog,
)
from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.takes import (
    CONFLICT_DISCARD,
    CONFLICT_RENAME,
    CONFLICT_REPLACE,
    name_conflict,
    store_take,
)

class PuppetMotionRecordMixin:
    def _toggle_motion_record(self, enabled: bool) -> None:
        if enabled:
            if not self._start_motion_recording():
                self._reset_toggle(self._motion_record_toggle)
        else:
            self._motion_recorder.stop()

    def _start_motion_recording(self) -> bool:
        if self._canvas.document() is None:
            return False
        lang = language_wrapper.language_word_dict
        name, ok = QInputDialog.getText(
            self,
            lang.get("puppet_record_motion_title", "Record motion"),
            lang.get("puppet_record_motion_prompt", "Motion name:"),
            text="user_motion",
        )
        if not ok or not name.strip():
            return False
        self._commit_edit()
        self._motion_record_revision = self.session.revision
        return self._motion_recorder.start(name.strip(), inputs=self._active_inputs())

    def _active_inputs(self) -> list[str]:
        """Live inputs switched on while a take is recorded, for its take record."""
        toggles = {"mouse": "_drag_toggle", "blink": "_blink_toggle",
                   "microphone": "_lipsync_toggle", "webcam": "_webcam_toggle",
                   "idle": "_idle_toggle"}
        return [name for name, attr in toggles.items()
                if getattr(self, attr, None) is not None and getattr(self, attr).isChecked()]

    def _choose_take_conflict(self, name: str) -> str:
        """Ask how to store a take whose name already exists."""
        from PySide6.QtWidgets import QMessageBox
        lang = language_wrapper.language_word_dict
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(lang.get("puppet_take_conflict_title", "Motion name in use"))
        box.setText(lang.get("puppet_take_conflict_body",
                             "A motion named '{name}' already exists.").format(name=name))
        replace = box.addButton(lang.get("puppet_take_replace", "Replace it"),
                                QMessageBox.ButtonRole.DestructiveRole)
        keep = box.addButton(lang.get("puppet_take_keep_both", "Keep both"),
                             QMessageBox.ButtonRole.AcceptRole)
        box.addButton(lang.get("puppet_take_discard", "Discard new take"),
                      QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        box.exec()
        clicked = box.clickedButton()
        box.deleteLater()
        if clicked is replace:
            return CONFLICT_REPLACE
        if clicked is keep:
            return CONFLICT_RENAME
        return CONFLICT_DISCARD

    def store_motion_take(self, motion, conflict: str | None = None) -> str | None:
        """Store a take as one undoable edit; ``conflict`` skips the question."""
        document = self.session.document
        if document is None:
            return None
        if conflict is None:
            conflict = (self._choose_take_conflict(motion.name)
                        if name_conflict(document, motion.name) else CONFLICT_RENAME)
        if conflict == CONFLICT_DISCARD and name_conflict(document, motion.name):
            self._announce("puppet_take_discarded", "Take discarded; nothing changed.")
            return None
        with self.session.transaction("Record motion"):
            stored = store_take(self.session.document, motion, conflict)
        self._canvas.load_document(self.session.document)
        self._update_session_actions()
        return stored

    def _on_motion_recorded(self, motion) -> None:
        if motion is None:
            return
        revision = getattr(self, "_motion_record_revision", None)
        if revision is not None and not self.session.accepts(revision):
            self._announce(
                "puppet_stale_motion", "Recording belongs to an older document revision. "
                "Record again after finishing edits.",
            )
            return
        if self.store_motion_take(motion) is not None:
            self._announce(
                "puppet_motion_recorded",
                "Recorded motion '{name}' ({duration:.1f}s, {tracks} tracks)",
                name=motion.name,
                duration=motion.duration,
                tracks=len(motion.tracks),
            )
