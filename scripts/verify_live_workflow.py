"""R4 acceptance in the real hidden editor, invoked by verify_gui.py.

Nothing here opens the user's camera, microphone or a visible window. Capture
devices are replaced by scripted stand-ins at the driver boundary (``cv2``,
``mediapipe``, ``sounddevice``, ``pyvirtualcam``), while everything above that
boundary is the real editor: the tracker thread and its recovery, calibration,
arbitration on the real canvas, the hidden-canvas GL render feeding the
virtual-camera queue, and a real loopback WebSocket for the VTS API. Real
virtual-camera and NDI receivers are R4.6 and are not covered here.
"""
from __future__ import annotations

import json
import math
import socket
import sys
import time
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


def _module(name, **attributes):
    """A stand-in driver module that import machinery (find_spec) accepts."""
    import importlib.machinery
    from types import ModuleType
    module = ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, None)
    module.__dict__.update(attributes)
    return module


@contextmanager
def _stub_modules(**modules):
    """Swap only the named driver modules. ``patch.dict(sys.modules)`` would
    also drop every module first imported inside the block (PySide6 ones
    included), and a second import of a Qt module crashes."""
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _require(value, message):
    if not value:
        raise RuntimeError(message)


class _Loop:
    """Pump Qt events while measuring the longest gap between timer ticks."""

    def __init__(self, app):
        from PySide6.QtCore import QTimer
        self.app = app
        self.longest = 0.0
        self._last = time.perf_counter()
        self._timer = QTimer()
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        now = time.perf_counter()
        self.longest = max(self.longest, now - self._last)
        self._last = now

    def run_until(self, condition, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return True
            time.sleep(0.005)
        return condition()

    def run_for(self, seconds: float) -> None:
        self.run_until(lambda: False, seconds)

    def stop(self):
        self._timer.stop()


class _Camera:
    """A capture device that plays ``frames`` frames and then disappears."""

    opened: list = []

    def __init__(self, index, frames):
        self.index, self.frames = index, frames
        _Camera.opened.append(index)
        self.released = False

    def isOpened(self):   # noqa: N802 - cv2 API
        return True

    def read(self):
        if self.frames <= 0:
            return False, None
        self.frames -= 1
        time.sleep(1 / 60)
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self):
        self.released = True


def _check_webcam(editor, loop, report):
    from rigora.puppet import webcam_tracker as wt
    from rigora.puppet.input_calibration import Calibrator, ChannelCalibration, \
        parameter_ranges
    from rigora.puppet.webcam_status import WebcamPhase

    canvas, tracker = editor.canvas(), editor._webcam   # noqa: SLF001
    plan = {"frames": 40, "face": True}
    cameras: list[_Camera] = []

    def capture(index):
        camera = _Camera(index, plan["frames"])
        cameras.append(camera)
        return camera

    fake_cv2 = SimpleNamespace(VideoCapture=capture, cvtColor=lambda f, _c: f, COLOR_BGR2RGB=4)
    face = np.zeros((478, 3))
    with ExitStack() as stack:
        stack.enter_context(_stub_modules(cv2=fake_cv2,
                                          mediapipe=_module("mediapipe")))
        stack.enter_context(patch.object(wt, "_build_face_landmarker",
                                         lambda: SimpleNamespace(close=lambda: None)))
        stack.enter_context(patch.object(
            wt, "_detect_face", lambda *_a: face if plan["face"] else None))
        stack.enter_context(patch.object(wt, "landmarks_to_params",
                                         lambda _l: {"ParamAngleX": 14.0}))
        profile = editor._input_profile   # noqa: SLF001
        angle = canvas.document().parameter("ParamAngleX")
        sensitivity = 0.5 * (angle.max - angle.default) / 10.0     # lands halfway to max
        profile.channels["ParamAngleX"] = ChannelCalibration(neutral=4.0,
                                                             sensitivity=sensitivity,
                                                             smoothing=0.0)
        profile.lost_after, profile.return_seconds = 0.2, 0.3
        tracker.set_calibrator(Calibrator(profile, parameter_ranges(canvas.document())))
        editor._webcam_supervisor.request(True)   # noqa: SLF001
        _require(tracker.set_enabled(True), "tracker did not start")
        expected = angle.default + (14.0 - 4.0) * sensitivity
        _require(loop.run_until(lambda: abs(canvas.parameter_values()["ParamAngleX"]
                                            - expected) < 1e-6, 5),
                 "calibrated webcam value never reached the canvas: "
                 f"{canvas.parameter_values().get('ParamAngleX')} vs {expected}, owners "
                 f"{canvas.input_arbiter().owners()}, status {tracker.status()}, "
                 f"rejected {canvas.input_arbiter().rejected}")
        report["calibrated_value"] = expected
        owners = canvas.input_arbiter().owners()
        _require(owners.get("ParamAngleX") == "webcam", f"unexpected owner {owners}")
        canvas.submit_input("motion", {"ParamAngleX": angle.min})
        loop.run_for(0.1)
        _require(canvas.parameter_values()["ParamAngleX"] == angle.min
                 and canvas.input_arbiter().owners().get("ParamAngleX") == "motion",
                 "motion did not take over from the webcam")
        report["motion_overrides_webcam"] = True

        # Unplug: the device stops delivering frames mid-session.
        plan["frames"] = 60
        _require(loop.run_until(lambda: tracker.status().phase == WebcamPhase.DEVICE_LOST, 8),
                 "lost device was not reported")
        report["device_lost_detected"] = True
        _require(cameras[0].released, "lost device was not released")
        _require(loop.run_until(lambda: len(cameras) >= 2
                                and tracker.status().phase == WebcamPhase.RUNNING, 6),
                 "supervisor did not reconnect the device")
        report["reconnected_after_seconds"] = editor._webcam_supervisor.delays[0]   # noqa: SLF001

        # Face lost: values ease back to the neutral pose (parameter default).
        plan["face"] = False
        default = canvas.document().parameter("ParamAngleX").default
        _require(loop.run_until(lambda: abs(canvas.parameter_values()["ParamAngleX"]
                                            - default) < 1e-6, 3),
                 "lost tracking did not return to neutral")
        report["lost_face_returns_to_neutral"] = True
        plan["face"] = True

        # Switch device while capturing: stop, release, start on the new index.
        plan["frames"] = 10_000
        loop.run_until(lambda: tracker.status().phase == WebcamPhase.RUNNING, 3)
        before = len(cameras)
        editor.switch_camera(3)
        _require(loop.run_until(lambda: len(cameras) > before and cameras[-1].index == 3
                                and tracker.status().phase == WebcamPhase.RUNNING, 8),
                 "device switch did not restart on the new camera")
        _require(cameras[before - 1].released, "previous camera was not released on switch")
        report["device_switch"] = {"to": 3, "previous_released": True}

        # Sleep/wake: a jump of the wall clock against the monotonic clock.
        supervisor = editor._webcam_supervisor   # noqa: SLF001
        supervisor._offset -= 3600   # noqa: SLF001 - as if the machine slept an hour
        before = len(cameras)
        _require(loop.run_until(lambda: len(cameras) > before
                                and tracker.status().phase == WebcamPhase.RUNNING, 8),
                 "wake from sleep did not restart capture")
        report["restart_after_wake"] = True

        editor._webcam_supervisor.request(False)   # noqa: SLF001
        tracker.set_enabled(False)
        _require(tracker.wait_released(3.0), "tracker thread did not exit")
        loop.run_until(lambda: tracker.can_configure(), 2)
        _require(all(c.released for c in cameras), "a capture was left open")
        report["threads_released"] = True
        report["captures_opened"] = len(cameras)
    canvas.release_input("motion")


def _check_mic(editor, loop, report):
    from rigora.puppet.input_drivers import DEFAULT_MOUTH_PARAM
    streams = []

    class Stream:
        def __init__(self, **kwargs):
            self.kwargs, self.closed = kwargs, False
            streams.append(self)

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            self.closed = True

    engine = editor._input_engine   # noqa: SLF001
    with _stub_modules(sounddevice=_module("sounddevice", InputStream=Stream)):
        editor._input_profile.mic_gate = 0.0   # noqa: SLF001
        editor._apply_calibrators()   # noqa: SLF001
        editor._lipsync_toggle.setChecked(True)   # noqa: SLF001
        _require(engine.lipsync_enabled() and streams, "lip-sync did not start")
        tone = (0.5 * np.sin(np.linspace(0, 300, 1024))).astype(np.float32).reshape(-1, 1)
        for _ in range(5):
            streams[-1].kwargs["callback"](tone, 1024, None, None)
            loop.run_for(0.02)
        mouth = editor.canvas().parameter_values().get(DEFAULT_MOUTH_PARAM, 0.0)
        _require(mouth > 0.05, f"mic audio did not open the mouth ({mouth})")
        report["mic_mouth_open"] = round(mouth, 3)
        streams[-1].kwargs["finished_callback"]()
        _require(loop.run_until(lambda: engine.mic_status()[0] == "device_lost", 2),
                 "lost microphone was not reported")
        _require(streams[0].closed, "lost microphone stream was not closed")
        _require(loop.run_until(lambda: engine.mic_status()[0] == "running"
                                and len(streams) >= 2, 4),
                 "microphone was not reconnected")
        report["mic_reconnected"] = True
        editor._lipsync_toggle.setChecked(False)   # noqa: SLF001
        _require(all(s.closed for s in streams), "a microphone stream was left open")
        report["mic_released"] = True


def _check_virtual_camera(editor, loop, report):
    frames = []
    state = {"delay": 0.12, "fail": False}

    class Camera:
        def __init__(self, width, height, fps, fmt):
            self.width, self.height, self.fps = width, height, fps
            self.device = "Verification Camera"

        def send(self, frame):
            if state["fail"]:
                raise OSError("receiver went away")
            time.sleep(state["delay"])                 # a receiver slower than 30 fps
            frames.append(frame)

        def close(self):
            pass

    output = editor._virtual_camera   # noqa: SLF001
    fake = _module("pyvirtualcam", Camera=Camera, PixelFormat=SimpleNamespace(RGB="RGB"))
    with _stub_modules(pyvirtualcam=fake):
        loop.longest = 0.0
        _require(output.set_enabled(True), "virtual camera did not start")
        loop.run_for(1.5)
        stats = output.stats()
        _require(stats["sent"] >= 5 and stats["dropped"] > 0,
                 f"expected dropped frames with a slow receiver: {stats}")
        _require(loop.longest < 0.25, f"GUI stalled {loop.longest:.3f}s behind a slow receiver")
        frame = frames[-1]
        magenta = (frame[..., 0] == 255) & (frame[..., 1] == 0) & (frame[..., 2] == 255)
        _require(0.05 < magenta.mean() < 0.98, "streamed frame does not show the puppet")
        report["virtual_camera"] = {
            "source_name": stats["source_name"], "size": [stats["width"], stats["height"]],
            "sent": stats["sent"], "dropped": stats["dropped"],
            "measured_fps": stats["measured_fps"], "gui_longest_gap_ms":
                round(loop.longest * 1000, 1), "alpha": stats["alpha"],
            "puppet_pixels": round(1 - float(magenta.mean()), 3)}
        state["fail"] = True
        _require(loop.run_until(lambda: not output.is_enabled(), 3),
                 "a failing receiver did not stop the output")
        _require(output.stats()["last_error"] == "receiver went away", "error not reported")
        report["virtual_camera"]["failure_reported"] = True


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _check_vts(editor, loop, report):
    from PySide6.QtCore import QUrl
    from PySide6.QtNetwork import QNetworkRequest
    from PySide6.QtWebSockets import QWebSocket

    from rigora.puppet import vts_session as vs
    from rigora.puppet.vts_api import VTubeStudioServer
    canvas = editor.canvas()
    port = _free_port()
    server = VTubeStudioServer(canvas, port=port)
    _require(server.set_enabled(True), "VTS server did not listen")
    _require(server._server.serverAddress().toString() == "127.0.0.1",   # noqa: SLF001
             "VTS server is not bound to localhost")

    def client(origin=None):
        sock, inbox = QWebSocket(), []
        sock.textMessageReceived.connect(lambda text: inbox.append(json.loads(text)))
        request = QNetworkRequest(QUrl(f"ws://127.0.0.1:{port}"))
        if origin:
            request.setRawHeader(b"Origin", origin.encode())
        sock.open(request)
        return sock, inbox

    def ask(sock, inbox, message_type, data=None):
        count = len(inbox)
        sock.sendTextMessage(json.dumps({"apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
                                         "requestID": "v", "messageType": message_type,
                                         "data": data or {}}))
        _require(loop.run_until(lambda: len(inbox) > count, 3), f"no reply to {message_type}")
        return inbox[-1]

    def login(name):
        sock, inbox = client()
        _require(loop.run_until(lambda: sock.state().name == "ConnectedState", 3),
                 "native client could not connect")
        token = ask(sock, inbox, "AuthenticationTokenRequest", {
            "pluginName": name, "pluginDeveloper": "Verify"})["data"]["authenticationToken"]
        auth = ask(sock, inbox, "AuthenticationRequest", {
            "authenticationToken": token, "pluginName": name, "pluginDeveloper": "Verify"})
        _require(auth["data"]["authenticated"], "authentication failed")
        return sock, inbox

    param = canvas.document().parameter("ParamAngleY")
    first, first_inbox = login("Verify one")
    reply = ask(first, first_inbox, "InjectParameterDataRequest", {
        "parameterValues": [{"id": param.id, "value": param.max * 0.5}]})
    _require(reply["messageType"] == "InjectParameterDataResponse"
             and math.isclose(canvas.parameter_values()[param.id], param.max * 0.5),
             "injection did not reach the canvas")
    second, second_inbox = login("Verify two")
    taken = ask(second, second_inbox, "InjectParameterDataRequest", {
        "parameterValues": [{"id": param.id, "value": 0}]})
    _require(taken["data"].get("errorID") == vs.ERR_INJECT_PARAM_TAKEN,
             "second plug-in was not refused a held parameter")
    for _ in range(int(vs.INJECT_BURST) + 40):
        first.sendTextMessage(json.dumps({"messageType": "InjectParameterDataRequest",
                                          "data": {"parameterValues": [
                                              {"id": param.id, "value": 0.1}]}}))
    loop.run_until(lambda: len(first_inbox) > int(vs.INJECT_BURST) + 30, 5)
    limited = sum(1 for m in first_inbox if m["data"].get("errorID") == vs.ERR_RATE_LIMITED)
    _require(limited > 0, "flooding was not rate limited")
    _require(loop.longest < 0.5, "VTS flood stalled the GUI")
    revoked = server.revoke_tokens()
    after = ask(first, first_inbox, "InjectParameterDataRequest", {
        "parameterValues": [{"id": param.id, "value": 0}]})
    _require(after["data"].get("errorID") == vs.ERR_REQUIRES_AUTHENTICATION,
             "revoked token still worked")
    web, _ = client("https://example.invalid")
    loop.run_for(0.5)
    _require(web.state().name != "ConnectedState" and server.session_count() == 2,
             "a web origin got a session")
    for sock in (first, second, web):
        sock.close()
    loop.run_for(0.2)
    server.set_enabled(False)
    report["vts_api"] = {"port_bound": "127.0.0.1", "inject": True, "param_taken_refused": True,
                         "rate_limited_replies": limited, "tokens_revoked": revoked,
                         "web_origin_refused": True,
                         "owner_after_disconnect": canvas.input_arbiter().owners().get(param.id)}


def check_live_workflow(window, root) -> dict:   # noqa: ARG001 - same hook signature
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    editor = window.editor
    loop = _Loop(app)
    report: dict = {}
    # Earlier checks may leave a motion preview playing; it would own parameters.
    editor._motion_dock.player().stop()   # noqa: SLF001
    loop.run_for(0.3)
    editor.canvas().input_arbiter().clear()
    try:
        _check_webcam(editor, loop, report)
        _check_mic(editor, loop, report)
        _check_virtual_camera(editor, loop, report)
        _check_vts(editor, loop, report)
        from rigora.puppet.input_sources_dialog import InputSourcesDialog
        from rigora.puppet.output_status_dialog import output_row
        sources = InputSourcesDialog(editor.canvas())          # built, never shown
        report["owner_rows"] = len(sources.rows())
        sources.deleteLater()
        report["status_rows"] = [output_row(r)[:2] for r in editor.output_report()]
        report["gui_longest_gap_ms"] = round(loop.longest * 1000, 1)
    finally:
        loop.stop()
    return report
