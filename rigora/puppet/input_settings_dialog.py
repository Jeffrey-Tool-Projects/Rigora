"""Input devices, calibration and profiles (R4.1)."""
from __future__ import annotations

import copy

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.input_calibration import DEFAULT_PROFILE, InputProfile

_FIELDS = (
    ("sensitivity", "puppet_input_sensitivity", "Sensitivity", 0.0, 10.0, 0.1),
    ("dead_zone", "puppet_input_dead_zone", "Dead zone", 0.0, 100.0, 0.01),
    ("smoothing", "puppet_input_smoothing", "Smoothing", 0.0, 0.95, 0.05),
    ("lost_after", "puppet_input_lost_after", "Return to neutral after (s)", 0.0, 30.0, 0.1),
    ("return_seconds", "puppet_input_return_seconds", "Return duration (s)", 0.0, 10.0, 0.1),
    ("mic_gain", "puppet_input_mic_gain", "Microphone gain", 0.0, 20.0, 0.1),
    ("mic_gate", "puppet_input_mic_gate", "Microphone noise gate", 0.0, 1.0, 0.01),
    ("mic_smoothing", "puppet_input_mic_smoothing", "Lip-sync smoothing", 0.0, 0.95, 0.05),
)


def _tr(key: str, fallback: str) -> str:
    return language_wrapper.language_word_dict.get(key, fallback)


class InputSettingsDialog(QDialog):
    def __init__(self, profiles: dict[str, InputProfile], active: str, cameras: list[str],
                 microphones: list[str], parent=None, capture=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_tr("puppet_input_settings_title", "Input Devices and Calibration"))
        self._profiles = {name: copy.deepcopy(p) for name, p in profiles.items()}
        self._deleted: list[str] = []
        self._capture = capture
        self._profile_box = QComboBox()
        self._profile_box.addItems(list(self._profiles))
        new_button = QPushButton(_tr("puppet_input_profile_new", "New…"))
        new_button.clicked.connect(self._new_profile)
        self._delete_button = QPushButton(_tr("puppet_input_profile_delete", "Delete"))
        self._delete_button.clicked.connect(self._delete_profile)
        top = QHBoxLayout()
        top.addWidget(QLabel(_tr("puppet_input_profile", "Profile")))
        top.addWidget(self._profile_box, 1)
        top.addWidget(new_button)
        top.addWidget(self._delete_button)
        form = QFormLayout()
        self._camera_box = QComboBox()
        self._camera_box.addItems(cameras or [_tr("puppet_input_no_camera", "(no camera found)")])
        self._mic_box = QComboBox()
        self._mic_box.addItem(_tr("puppet_input_default_mic", "System default"), "")
        for name in microphones:
            self._mic_box.addItem(name, name)
        form.addRow(_tr("puppet_input_camera", "Camera"), self._camera_box)
        form.addRow(_tr("puppet_input_microphone", "Microphone"), self._mic_box)
        self._spins: dict[str, QDoubleSpinBox] = {}
        for attr, key, fallback, low, high, step in _FIELDS:
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setDecimals(2)
            self._spins[attr] = spin
            form.addRow(_tr(key, fallback), spin)
        self._neutral_label = QLabel()
        neutral_button = QPushButton(_tr("puppet_input_capture_neutral",
                                         "Capture neutral pose (2 s)"))
        neutral_button.setEnabled(capture is not None)
        neutral_button.clicked.connect(self._capture_neutral)
        neutral_row = QWidget()
        row = QHBoxLayout(neutral_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(neutral_button)
        row.addWidget(self._neutral_label, 1)
        form.addRow(neutral_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._current = None
        self._profile_box.currentTextChanged.connect(self._show_profile)
        self._profile_box.setCurrentText(active if active in self._profiles else DEFAULT_PROFILE)
        self._show_profile(self._profile_box.currentText())

    def _store_current(self) -> None:
        profile = self._profiles.get(self._current or "")
        if profile is None:
            return
        for attr, spin in self._spins.items():
            setattr(profile, attr, float(spin.value()))
        profile.camera_index = max(0, self._camera_box.currentIndex())
        profile.camera_name = self._camera_box.currentText()
        profile.mic_device = self._mic_box.currentData() or ""

    def _show_profile(self, name: str) -> None:
        self._store_current()
        profile = self._profiles.get(name)
        if profile is None:
            return
        self._current = name
        for attr, spin in self._spins.items():
            spin.setValue(float(getattr(profile, attr)))
        if 0 <= profile.camera_index < self._camera_box.count():
            self._camera_box.setCurrentIndex(profile.camera_index)
        index = self._mic_box.findData(profile.mic_device)
        self._mic_box.setCurrentIndex(max(0, index))
        self._delete_button.setEnabled(name != DEFAULT_PROFILE)
        self._neutral_label.setText(_tr("puppet_input_neutral_count",
                                        "{count} calibrated channel(s)").format(
            count=len(profile.channels)))

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, _tr("puppet_input_profile_new", "New…"),
                                        _tr("puppet_input_profile", "Profile"))
        name = name.strip()[:80]
        if not ok or not name or name in self._profiles:
            return
        self._store_current()
        base = copy.deepcopy(self._profiles[self._current]) if self._current else InputProfile()
        base.name = name
        self._profiles[name] = base
        self._profile_box.addItem(name)
        self._profile_box.setCurrentText(name)

    def _delete_profile(self) -> None:
        name = self._profile_box.currentText()
        if name == DEFAULT_PROFILE:
            return
        self._profiles.pop(name, None)
        self._deleted.append(name)
        self._current = None
        self._profile_box.removeItem(self._profile_box.currentIndex())

    def _capture_neutral(self) -> None:
        self._store_current()
        started = self._capture(done=self._neutral_done)
        self._neutral_label.setText(
            _tr("puppet_input_neutral_recording", "Hold still…") if started else
            _tr("puppet_input_neutral_needs_webcam", "Turn on webcam tracking first."))

    def _neutral_done(self, neutral: dict) -> None:
        profile = self._profiles.get(self._current or "")
        if profile is not None:
            from rigora.puppet.input_calibration import apply_neutral
            apply_neutral(profile, neutral)
        self._neutral_label.setText(_tr("puppet_input_neutral_count",
                                        "{count} calibrated channel(s)").format(
            count=len(neutral)))

    def profile(self) -> InputProfile:
        self._store_current()
        return self._profiles[self._current or DEFAULT_PROFILE]

    def deleted(self) -> list[str]:
        return list(self._deleted)
