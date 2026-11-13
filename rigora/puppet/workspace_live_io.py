"""Device settings, recovery, input ownership and output status (R4.1–R4.5)."""
from __future__ import annotations

import logging

from PySide6.QtCore import QTimer

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.device_supervisor import ACT_START, ACT_STOP, ACT_SWITCH, DeviceSupervisor
from rigora.puppet.input_calibration import (
    Calibrator,
    active_profile,
    apply_neutral,
    capture_neutral,
    delete_profile,
    parameter_ranges,
    save_profile,
)

logger = logging.getLogger(__name__)

SUPERVISE_INTERVAL_MS = 1000


def camera_devices() -> list[str]:
    """Names of the cameras the system lists. Enumeration does not open them."""
    try:
        from PySide6.QtMultimedia import QMediaDevices
    except ImportError:
        return []
    return [device.description() for device in QMediaDevices.videoInputs()]


def microphone_devices() -> list[str]:
    try:
        import sounddevice as sd
    except ImportError:
        return []
    try:
        devices = sd.query_devices()
    except Exception:   # noqa: BLE001 - PortAudio errors vary by host
        return []
    names = []
    for device in devices:
        if device.get("max_input_channels", 0) > 0 and device["name"] not in names:
            names.append(device["name"])
    return names


class PuppetLiveIOMixin:
    """Wires calibration, the device supervisors and the status dialogs."""

    def _init_live_io(self) -> None:
        from rigora.system.settings import user_setting_dict
        self._input_store = user_setting_dict
        self._input_profile = active_profile(user_setting_dict)
        self._webcam_supervisor = DeviceSupervisor()
        self._mic_supervisor = DeviceSupervisor()
        self._webcam.set_device(self._input_profile.camera_index)
        self._input_engine._mic_device = self._input_profile.mic_device   # noqa: SLF001
        self._apply_calibrators()
        self._canvas.document_loaded.connect(self._apply_calibrators)
        self._input_engine.state_changed.connect(self._on_mic_state_changed)
        for output, toggle in ((self._virtual_camera, "_virtual_camera_toggle"),
                               (self._ndi_output, "_ndi_toggle")):
            output.state_changed.connect(
                lambda o=output, t=toggle: self._sync_output_toggle(o, t))
        self._device_timer = QTimer(self)
        self._device_timer.setInterval(SUPERVISE_INTERVAL_MS)
        self._device_timer.timeout.connect(self._supervise_devices)
        self._device_timer.start()

    def _sync_output_toggle(self, output, toggle_name: str) -> None:
        """An output that stopped itself (its receiver kept failing) unticks its
        toggle and says why."""
        toggle = getattr(self, toggle_name, None)
        if toggle is None or toggle.isChecked() == output.is_enabled():
            return
        toggle.blockSignals(True)
        toggle.setChecked(output.is_enabled())
        toggle.blockSignals(False)
        error = output.stats().get("last_error")
        if not output.is_enabled() and error:
            self._announce("puppet_output_failed", "Output stopped: {error}", error=error)

    def _apply_calibrators(self) -> None:
        ranges = parameter_ranges(self._canvas.document())
        self._webcam.set_calibrator(Calibrator(self._input_profile, ranges))
        self._input_engine.set_calibrator(Calibrator(self._input_profile, ranges))

    # ---- recovery (R4.3) -----------------------------------------------------

    def _supervise_devices(self) -> None:
        status = self._webcam.status()
        supervisor = self._webcam_supervisor
        supervisor.observe(status.phase.value, status.detail)
        action = supervisor.next_action(status.phase.value, self._webcam.can_configure())
        if action == ACT_STOP:
            self._webcam.set_enabled(False)
        elif action == ACT_SWITCH:
            self._webcam.set_device(supervisor.take_pending_device())
            self._webcam.set_enabled(True)
        elif action == ACT_START:
            self._webcam.set_enabled(True)
        phase, detail = self._input_engine.mic_status()
        self._mic_supervisor.observe(phase, detail)
        mic_action = self._mic_supervisor.next_action(phase, True)
        if mic_action in (ACT_START, ACT_SWITCH):
            self._mic_supervisor.take_pending_device()
            self._restart_mic()

    def _restart_mic(self) -> None:
        engine = self._input_engine
        if not engine.lipsync_enabled():
            engine._lipsync_enabled = True   # noqa: SLF001 - a retry keeps the user's choice
        if not engine.restart_mic():
            engine._lipsync_enabled = False   # noqa: SLF001
        self._lipsync_toggle.blockSignals(True)
        self._lipsync_toggle.setChecked(engine.lipsync_enabled())
        self._lipsync_toggle.blockSignals(False)

    def _on_mic_state_changed(self) -> None:
        phase, _ = self._input_engine.mic_status()
        if phase == "device_lost":
            self._announce("puppet_mic_lost",
                           "Microphone disconnected. Rigora will retry automatically.")

    def switch_camera(self, index: int) -> None:
        """Change camera; a running capture stops, releases, then restarts."""
        if self._webcam.can_configure():
            self._webcam.set_device(index)
        else:
            self._webcam_supervisor.switch_device(index)

    def retry_devices(self) -> None:
        for supervisor, active in ((self._webcam_supervisor, self._webcam_toggle.isChecked()),
                                   (self._mic_supervisor, self._lipsync_toggle.isChecked())):
            if active or supervisor.wanted:
                supervisor.retry_now()

    def device_report(self) -> dict:
        webcam = self._webcam.status()
        mic_phase, mic_detail = self._input_engine.mic_status()
        return {
            "camera": {"phase": webcam.phase.value, "device": webcam.device,
                       "detail": webcam.detail,
                       "recovery": vars(self._webcam_supervisor.snapshot())},
            "microphone": {"phase": mic_phase, "device": self._input_engine.mic_device(),
                           "detail": mic_detail,
                           "recovery": vars(self._mic_supervisor.snapshot())},
        }

    # ---- calibration (R4.1) -------------------------------------------------

    def apply_input_profile(self, profile, deleted=()) -> None:
        for name in deleted:
            delete_profile(self._input_store, name)
        save_profile(self._input_store, profile)
        self._input_profile = profile
        self._apply_calibrators()
        self.switch_camera(profile.camera_index)
        if profile.mic_device != self._input_engine.mic_device():
            self._input_engine.set_mic_device(profile.mic_device)

    def capture_neutral_pose(self, seconds: float = 2.0, done=None) -> bool:
        """Record the performer at rest for ``seconds`` and store each tracked
        value as that channel's neutral. Needs webcam tracking running."""
        if not self._webcam.status().active:
            return False
        self._webcam.start_neutral_capture()

        def finish() -> None:
            neutral = capture_neutral(self._webcam.finish_neutral_capture())
            if neutral:
                apply_neutral(self._input_profile, neutral)
                save_profile(self._input_store, self._input_profile)
                self._apply_calibrators()
            if done is not None:
                done(neutral)

        QTimer.singleShot(int(seconds * 1000), finish)
        return True

    def input_settings_via_dialog(self) -> None:
        from rigora.puppet.input_calibration import load_profiles
        from rigora.puppet.input_settings_dialog import InputSettingsDialog
        dialog = InputSettingsDialog(load_profiles(self._input_store), self._input_profile.name,
                                     camera_devices(), microphone_devices(), self,
                                     capture=self.capture_neutral_pose)
        if dialog.exec():
            self.apply_input_profile(dialog.profile(), dialog.deleted())

    # ---- ownership (R4.2) and outputs (R4.4 / R4.5) ----------------------------

    def show_input_sources(self) -> None:
        from rigora.puppet.input_sources_dialog import InputSourcesDialog
        if getattr(self, "_input_sources_dialog", None) is None:
            self._input_sources_dialog = InputSourcesDialog(self._canvas, self)
        self._input_sources_dialog.show()

    def output_report(self) -> list[dict]:
        rows = [self._virtual_camera.stats(), self._ndi_output.stats()]
        vts = self._vts_server
        rows.append({"kind": "vts_api", "source_name": f"127.0.0.1:{vts.port()}",
                     "connected": vts.is_enabled(), "receivers": vts.session_count(),
                     "tokens": len(vts.tokens.active())})
        return rows

    def show_output_status(self) -> None:
        from rigora.puppet.output_status_dialog import OutputStatusDialog
        if getattr(self, "_output_status_dialog", None) is None:
            self._output_status_dialog = OutputStatusDialog(
                self.output_report, self.device_report, self.revoke_vts_tokens,
                self.retry_devices, self)
        self._output_status_dialog.show()

    def revoke_vts_tokens(self) -> int:
        count = self._vts_server.revoke_tokens()
        self._announce("puppet_vts_tokens_revoked",
                       "Revoked {count} plug-in token(s); plug-ins must authenticate again.",
                       count=count)
        return count

    def _shutdown_live_io(self) -> None:
        timer = getattr(self, "_device_timer", None)
        if timer is not None:
            timer.stop()
        for name in ("_input_sources_dialog", "_output_status_dialog"):
            dialog = getattr(self, name, None)
            if dialog is not None:
                dialog.close()


def tr(key: str, fallback: str) -> str:
    return language_wrapper.language_word_dict.get(key, fallback)
