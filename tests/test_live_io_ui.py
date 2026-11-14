"""R4 dialogs and workspace wiring, driven with stand-ins (no devices opened)."""
from __future__ import annotations

from types import SimpleNamespace

from rigora.puppet.device_supervisor import DeviceSupervisor
from rigora.puppet.input_arbitration import InputArbiter
from rigora.puppet.input_calibration import ChannelCalibration, InputProfile
from rigora.puppet.webcam_status import WebcamPhase, WebcamStatus
from rigora.puppet.workspace_live_io import PuppetLiveIOMixin


def test_input_settings_dialog_edits_creates_and_deletes_profiles(qapp, monkeypatch):
    from rigora.puppet import input_settings_dialog as module
    profiles = {"Default": InputProfile(), "Desk": InputProfile(
        name="Desk", camera_index=1, mic_device="USB mic",
        channels={"A": ChannelCalibration(neutral=2.0)})}
    dialog = module.InputSettingsDialog(profiles, "Desk", ["Cam A", "Cam B"], ["USB mic"])
    assert dialog._camera_box.currentIndex() == 1                       # noqa: SLF001
    assert dialog._mic_box.currentData() == "USB mic"                   # noqa: SLF001
    dialog._spins["sensitivity"].setValue(2.5)                          # noqa: SLF001
    profile = dialog.profile()
    assert profile.name == "Desk" and profile.sensitivity == 2.5
    assert profiles["Desk"].sensitivity == 1.0                          # caller's copy untouched
    monkeypatch.setattr(module.QInputDialog, "getText", lambda *a, **k: ("Stream", True))
    dialog._new_profile()                                               # noqa: SLF001
    assert dialog.profile().name == "Stream" and dialog.profile().sensitivity == 2.5
    dialog._delete_profile()                                            # noqa: SLF001
    assert dialog.deleted() == ["Stream"]
    dialog._profile_box.setCurrentText("Default")                       # noqa: SLF001
    assert not dialog._delete_button.isEnabled()                        # noqa: SLF001
    dialog.deleteLater()


def test_neutral_capture_button_reports_when_webcam_is_off(qapp):
    from rigora.puppet.input_settings_dialog import InputSettingsDialog
    dialog = InputSettingsDialog({"Default": InputProfile()}, "Default", [], [],
                                 capture=lambda done: False)
    dialog._capture_neutral()                                           # noqa: SLF001
    assert "webcam" in dialog._neutral_label.text().lower()             # noqa: SLF001
    dialog._neutral_done({"A": 1.0, "B": 2.0})                          # noqa: SLF001
    assert dialog.profile().channels["B"].neutral == 2.0
    dialog.deleteLater()


def test_input_sources_dialog_lists_owners_and_overlays(qapp):
    from rigora.puppet.document import Parameter, PuppetDocument
    from rigora.puppet.input_sources_dialog import InputSourcesDialog, owner_label
    arbiter = InputArbiter()
    arbiter.submit("webcam", {"A": 0.1})
    arbiter.submit("external:Tracker", {"B": 0.1})
    canvas = SimpleNamespace(
        document=lambda: PuppetDocument(parameters=[Parameter("A", 0, 1, 0), Parameter("B", 0, 1, 0),
                                                    Parameter("C", 0, 1, 0)]),
        input_arbiter=lambda: arbiter, active_expressions=lambda: ["smile"])
    dialog = InputSourcesDialog(canvas)
    rows = dialog.rows()
    assert [r[1] for r in rows] == ["Webcam", "External plug-in (Tracker)", "—"]
    assert rows[0][3] == "smile" and rows[2][2] == ""
    dialog.refresh()
    assert dialog._table.rowCount() == 3                                # noqa: SLF001
    assert owner_label("custom") == "custom"
    dialog.deleteLater()


def test_output_status_rows_show_real_names_rates_drops_and_recovery(qapp):
    from rigora.puppet.output_status_dialog import OutputStatusDialog
    outputs = [{"kind": "virtual_camera", "source_name": "Unity Video Capture", "width": 640,
                "height": 360, "target_fps": 30, "measured_fps": 29.5, "dropped": 3,
                "connected": True, "receivers": None, "last_error": ""},
               {"kind": "vts_api", "source_name": "127.0.0.1:8001", "connected": True,
                "receivers": 2}]
    devices = {"camera": {"phase": "device_lost", "device": 0, "detail": "",
                          "recovery": {"state": "waiting_retry", "next_retry_in": 2.0,
                                       "reason": "unplugged"}},
               "microphone": {"phase": "running", "device": "USB mic", "detail": "",
                              "recovery": {"state": "running"}}}
    calls = []
    dialog = OutputStatusDialog(lambda: outputs, lambda: devices,
                                lambda: calls.append("revoke"), lambda: calls.append("retry"))
    rows = dialog.rows()
    assert rows[0][1:5] == ["Unity Video Capture", "640×360", "29.5 / 30", "3"]
    assert rows[1][5].endswith("· 2")
    assert "retry in 2.0s" in rows[2][5] and rows[2][6] == "unplugged"
    dialog.refresh()
    dialog.deleteLater()


class _Tracker:
    def __init__(self):
        self.phase, self.device, self.calls = WebcamPhase.RUNNING, 0, []
        self.released = False

    def status(self):
        return WebcamStatus(self.phase, self.device)

    def can_configure(self):
        return self.released

    def set_enabled(self, on):
        self.calls.append(("enabled", on))

    def set_device(self, index):
        self.calls.append(("device", index))
        self.device = index


def test_workspace_supervision_switches_camera_after_release_and_reports():
    tracker = _Tracker()
    host = SimpleNamespace(
        _webcam=tracker, _webcam_supervisor=DeviceSupervisor(),
        _mic_supervisor=DeviceSupervisor(),
        _input_engine=SimpleNamespace(mic_status=lambda: ("stopped", ""),
                                      mic_device=lambda: ""))
    host._webcam_supervisor.request(True)
    PuppetLiveIOMixin.switch_camera(host, 1)                   # busy -> queued
    PuppetLiveIOMixin._supervise_devices(host)                 # noqa: SLF001
    assert tracker.calls == [("enabled", False)]
    tracker.phase, tracker.released = WebcamPhase.STOPPED, True
    PuppetLiveIOMixin._supervise_devices(host)                 # noqa: SLF001
    assert tracker.calls[-2:] == [("device", 1), ("enabled", True)]
    report = PuppetLiveIOMixin.device_report(host)
    assert report["camera"]["device"] == 1 and report["microphone"]["phase"] == "stopped"


def test_workspace_output_report_and_revoke():
    said = []
    vts = SimpleNamespace(port=lambda: 8001, is_enabled=lambda: True, session_count=lambda: 1,
                          tokens=SimpleNamespace(active=lambda: [1, 2]),
                          revoke_tokens=lambda: 2)
    host = SimpleNamespace(
        _virtual_camera=SimpleNamespace(stats=lambda: {"kind": "virtual_camera"}),
        _ndi_output=SimpleNamespace(stats=lambda: {"kind": "ndi"}), _vts_server=vts,
        _announce=lambda key, fallback, **fmt: said.append((key, fmt)))
    rows = PuppetLiveIOMixin.output_report(host)
    assert rows[2] == {"kind": "vts_api", "source_name": "127.0.0.1:8001", "connected": True,
                       "receivers": 1, "tokens": 2}
    assert PuppetLiveIOMixin.revoke_vts_tokens(host) == 2
    assert said == [("puppet_vts_tokens_revoked", {"count": 2})]


def test_device_lists_never_open_a_device(monkeypatch):
    import sys

    from rigora.puppet import workspace_live_io as module
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(query_devices=lambda: [
        {"name": "Mic A", "max_input_channels": 1}, {"name": "Speakers",
                                                     "max_input_channels": 0},
        {"name": "Mic A", "max_input_channels": 2}]))
    assert module.microphone_devices() == ["Mic A"]
    assert isinstance(module.camera_devices(), list)
