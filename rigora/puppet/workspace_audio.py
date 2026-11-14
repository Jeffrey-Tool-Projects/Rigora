"""Audio-file lip-sync motion creation, sound relinking and feedback (R3.4)."""
from __future__ import annotations

import wave
from pathlib import Path

from rigora.gui.file_filters import translated_filter
from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.document import Parameter


class PuppetAudioMixin:
    def _lipsync_from_audio_file(self) -> None:  # pragma: no cover - Qt file dialog
        """Live > Lip-sync from Audio File…: pick a WAV and add a motion that mimes it."""
        from PySide6.QtWidgets import QFileDialog

        from rigora.puppet.standard_params import PARAM_MOUTH_OPEN_Y
        doc = self._canvas.document()
        if doc is None:
            self._announce("puppet_lipsync_audio_no_doc", "Load a puppet first.")
            return
        mouth = next((p for p in doc.parameters if p.id == PARAM_MOUTH_OPEN_Y), None)
        if mouth is None:
            self._announce(
                "puppet_lipsync_audio_no_mouth",
                "This rig has no {param} parameter to drive.", param=PARAM_MOUTH_OPEN_Y,
            )
            return
        lang = language_wrapper.language_word_dict
        path, _ = QFileDialog.getOpenFileName(
            self, lang.get("puppet_lipsync_audio", "Lip-sync from Audio File…"), "",
            translated_filter("file_filter_wav", "WAV audio", ("wav",)),
        )
        if path:
            options = self._ask_lipsync_options()
            if options is not None:
                self._add_lipsync_motion(Path(path), mouth, **options)

    def _ask_lipsync_options(self) -> dict | None:  # pragma: no cover - Qt dialog
        """Frame rate, how far the mouth leads the sound, and the silence gate."""
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QSpinBox,
        )
        lang = language_wrapper.language_word_dict
        dialog = QDialog(self)
        dialog.setWindowTitle(lang.get("puppet_lipsync_options", "Lip-sync options"))
        form = QFormLayout(dialog)
        fps, lead, gate = QSpinBox(), QSpinBox(), QDoubleSpinBox()
        fps.setRange(5, 120)
        fps.setValue(30)
        lead.setRange(0, 500)
        lead.setSuffix(" ms")
        lead.setValue(40)
        gate.setRange(0.0, 0.5)
        gate.setSingleStep(0.01)
        gate.setValue(0.04)
        form.addRow(lang.get("puppet_lipsync_fps", "Frames per second"), fps)
        form.addRow(lang.get("puppet_lipsync_lead", "Mouth leads sound by"), lead)
        form.addRow(lang.get("puppet_lipsync_gate", "Silence gate"), gate)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        values = {"fps": float(fps.value()), "lead": lead.value() / 1000.0,
                  "gate": gate.value()}
        dialog.deleteLater()
        return values if accepted else None

    def _add_lipsync_motion(self, path: Path, mouth: Parameter, *, fps: float = 30.0,
                            lead: float = 0.0, gate: float = 0.04,
                            conflict: str | None = None) -> str | None:
        """Add a motion opening *mouth* with *path*'s loudness, playing the file; report it."""
        from rigora.puppet.audio_lipsync import lipsync_motion
        wide = mouth.max if mouth.max > mouth.default else mouth.min
        try:
            motion = lipsync_motion(path, name=f"lipsync_{path.stem}", param_id=mouth.id,
                                    mouth_range=(mouth.default, wide), fps=fps, lead=lead,
                                    gate=gate)
        except (OSError, EOFError, ValueError, wave.Error) as exc:
            self._announce("puppet_lipsync_audio_failed", "Could not read {name}: {error}",
                           name=path.name, error=exc)
            return None
        if motion is None:
            self._announce("puppet_lipsync_audio_silent", "{name} is silent — no motion added.",
                           name=path.name)
            return None
        stored = self.store_motion_take(motion, conflict)
        if stored is None:
            return None
        self._motion_dock.select_motion(stored)
        self._announce(
            "puppet_lipsync_audio_done",
            "Added lip-sync motion '{name}' ({duration:.1f}s); it plays with its sound.",
            name=stored, duration=motion.duration,
        )
        return stored

    def _relink_sounds_via_dialog(self) -> None:  # pragma: no cover - Qt file dialog
        from PySide6.QtWidgets import QFileDialog
        from rigora.puppet.audio_lipsync import find_missing_sounds
        document = self._canvas.document()
        if document is None or not find_missing_sounds(document):
            self._announce("puppet_sounds_none_missing", "Every motion sound is present.")
            return
        folder = QFileDialog.getExistingDirectory(self, language_wrapper.language_word_dict.get(
            "puppet_relink_sounds", "Relink sounds…"))
        if folder:
            self.relink_sounds_from(folder)

    def relink_sounds_from(self, folder: str | Path) -> int:
        """Relink every missing motion sound found by file name under ``folder``,
        as one undoable edit; returns how many were relinked."""
        from rigora.puppet.audio_lipsync import find_missing_sounds, locate_sounds, relink_sound
        document = self.session.document
        if document is None:
            return 0
        missing = find_missing_sounds(document)
        found = locate_sounds(missing, [folder])
        relinked = 0
        if found:
            self._begin_document_work()
            with self.session.transaction("Relink sounds"):
                for motion_name, path in found.items():
                    try:
                        relink_sound(self.session.document, motion_name, path)
                        relinked += 1
                    except (OSError, EOFError, ValueError, wave.Error):
                        continue
            self._canvas.load_document(self.session.document)
            self._update_session_actions()
        self._announce("puppet_sounds_relinked", "Relinked {n} of {total} missing sounds.",
                       n=relinked, total=len(missing))
        return relinked
