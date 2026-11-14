"""R4.1–R4.5: calibration, arbitration, device recovery, output queues and VTS rules.

No camera, microphone or receiver is opened: capture, audio and sending are
fakes, which is what these Qt-free cores are designed to accept.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from rigora.puppet import vts_session as vs
from rigora.puppet.device_supervisor import ACT_NONE, ACT_START, ACT_STOP, ACT_SWITCH, \
    DeviceSupervisor
from rigora.puppet.input_arbitration import InputArbiter, release_source, submit_values
from rigora.puppet.input_calibration import (
    Calibrator,
    ChannelCalibration,
    InputProfile,
    active_profile,
    apply_neutral,
    capture_neutral,
    delete_profile,
    load_profiles,
    save_profile,
)
from rigora.puppet.output_pump import FramePump, OutputStats

# ---- arbitration (R4.2) -------------------------------------------------------


def test_higher_priority_takes_over_and_lower_waits_for_hold():
    arbiter = InputArbiter(hold=0.25)
    assert arbiter.submit("webcam", {"A": 0.5}, now=0.0) == {"A": 0.5}
    assert arbiter.submit("mouse", {"A": 0.9, "B": 0.1}, now=0.1) == {"B": 0.1}
    assert arbiter.rejected == {"mouse": 1}
    assert arbiter.submit("motion", {"A": -1}, now=0.15) == {"A": -1}
    assert arbiter.owners(0.2) == {"A": "motion", "B": "mouse"}
    assert arbiter.submit("webcam", {"A": 0.3}, now=0.3) == {}        # motion still holds
    assert arbiter.submit("webcam", {"A": 0.3}, now=0.5) == {"A": 0.3}   # hold expired
    assert arbiter.owners(10.0) == {}


def test_manual_holds_longer_and_release_frees_parameters():
    arbiter = InputArbiter()
    arbiter.submit("manual", {"A": 1}, now=0.0)
    assert arbiter.submit("external:VTS", {"A": 0}, now=0.5) == {}
    assert arbiter.submit("external:VTS", {"A": 0}, now=1.1) == {"A": 0.0}
    arbiter.submit("webcam", {"B": 1}, now=1.2)
    assert arbiter.release("webcam") == ["B"]
    assert arbiter.submit("mouse", {"B": 0}, now=1.21) == {"B": 0.0}


def test_two_plugins_cannot_share_a_parameter_and_bad_values_are_dropped():
    arbiter = InputArbiter()
    arbiter.submit("external:one", {"A": 1}, now=0.0)
    assert arbiter.blocked("external:two", ["A", "B"], now=0.1) == ["A"]
    assert arbiter.submit("mic", {"M": float("nan"), "N": "x", "O": 1}, now=0) == {"O": 1.0}
    rows = arbiter.owner_rows(["A", "Z"], ["smile"], now=0.1)
    assert rows[0][:2] == ("A", "external:one") and rows[1][1] == "" and rows[0][3] == ["smile"]


def test_canvas_routes_live_inputs_through_its_arbiter(qapp):
    from rigora.puppet.canvas import PuppetCanvas
    from rigora.puppet.document import Parameter, PuppetDocument
    canvas = PuppetCanvas()
    try:
        canvas.load_document(PuppetDocument(parameters=[Parameter("A", -1, 1, 0)]))
        assert canvas.submit_input("webcam", {"A": 0.5}) == {"A": 0.5}
        assert canvas.submit_input("idle", {"A": 0.1}) == {}
        assert canvas.parameter_values()["A"] == 0.5
        canvas.release_input("webcam")
        assert submit_values(canvas, "idle", {"A": 0.2}) == {"A": 0.2}
        canvas.load_document(PuppetDocument(parameters=[Parameter("A", -1, 1, 0)]))
        assert canvas.input_arbiter().owners() == {}
    finally:
        canvas.deleteLater()


def test_hosts_without_an_arbiter_get_plain_writes():
    writes = []
    plain = SimpleNamespace(set_parameter_values=writes.append,
                            force_parameter_values=lambda v: writes.append(("force", v)))
    submit_values(plain, "webcam", {"A": 1})
    submit_values(plain, "blink", {"E": 0}, force=True)
    release_source(plain, "webcam")
    single = SimpleNamespace(set_parameter_value=lambda p, v: writes.append((p, v)))
    submit_values(single, "manual", {"S": 2}, force=True)
    assert writes == [{"A": 1}, ("force", {"E": 0}), ("S", 2)]


# ---- calibration (R4.1) ---------------------------------------------------------

RANGES = {"AngleX": (-30.0, 30.0, 0.0), "EyeOpen": (0.0, 1.0, 1.0), "Mouth": (0.0, 1.0, 0.0)}


def test_neutral_sensitivity_dead_zone_and_clamp():
    profile = InputProfile(smoothing=0.0, channels={
        "AngleX": ChannelCalibration(neutral=5.0, sensitivity=2.0, dead_zone=1.0),
        "EyeOpen": ChannelCalibration(neutral=0.8, invert=False)})
    calibrator = Calibrator(profile, RANGES)
    assert calibrator.calibrate_value("AngleX", 5.5) == 0.0            # inside dead zone
    assert calibrator.calibrate_value("AngleX", 8.0) == pytest.approx(4.0)   # (3-1)*2
    assert calibrator.calibrate_value("AngleX", 100.0) == 30.0          # clamped
    assert calibrator.calibrate_value("EyeOpen", 0.8) == 1.0            # rest -> default
    profile.channels["AngleX"].invert = True
    assert calibrator.calibrate_value("AngleX", 8.0) == pytest.approx(-4.0)


def test_smoothing_is_frame_rate_independent():
    def run(fps):
        calibrator = Calibrator(InputProfile(smoothing=0.5, channels={
            "AngleX": ChannelCalibration(neutral=0.0, smoothing=0.5)}), RANGES)
        calibrator.apply({"AngleX": 0.0}, 0.0)
        value = None
        for i in range(1, fps + 1):
            value = calibrator.apply({"AngleX": 10.0}, i / fps)["AngleX"]
        return value

    assert run(30) == pytest.approx(run(60), abs=1e-6)
    assert 9.9 < run(30) <= 10.0


def test_lost_tracking_waits_then_eases_to_the_neutral_pose():
    profile = InputProfile(smoothing=0.0, lost_after=0.5, return_seconds=1.0,
                           neutral_pose={"AngleX": 10.0})
    calibrator = Calibrator(profile, RANGES)
    calibrator.apply({"AngleX": 20.0, "EyeOpen": 0.2}, 0.0)
    assert calibrator.lost(0.3) == {}
    halfway = calibrator.lost(1.0)
    assert 10.0 < halfway["AngleX"] < 20.0 and 0.2 < halfway["EyeOpen"] < 1.0
    done = calibrator.lost(1.5)                       # grace ended at 0.5, eased over 1 s
    assert done == {"AngleX": 10.0, "EyeOpen": 1.0}
    assert calibrator.lost(3.0) == {}                                  # settled: stop writing
    assert calibrator.apply({"AngleX": 1.0}, 3.1)                      # tracking resumes


def test_mic_gain_gate_and_smoothing():
    calibrator = Calibrator(InputProfile(mic_gain=2.0, mic_gate=0.1, mic_smoothing=0.0),
                            RANGES)
    assert calibrator.apply_mic({"Mouth": 0.04}, 0.0) == {"Mouth": 0.0}
    assert calibrator.apply_mic({"Mouth": 0.3}, 0.1) == {"Mouth": pytest.approx(0.6)}
    assert calibrator.apply_mic({"Mouth": 0.9}, 0.2) == {"Mouth": 1.0}


def test_neutral_capture_and_profiles_round_trip():
    neutral = capture_neutral([{"AngleX": 4.0}, {"AngleX": 6.0, "Bad": "x"}, {"AngleX": 5.0}])
    assert neutral == {"AngleX": 5.0}
    store: dict = {}
    profile = apply_neutral(InputProfile(name="Desk", mic_device="USB mic"), neutral)
    save_profile(store, profile)
    assert active_profile(store).channels["AngleX"].neutral == 5.0
    assert set(load_profiles(store)) == {"Desk", "Default"}
    assert InputProfile.from_dict({"sensitivity": 1e9, "smoothing": "x",
                                   "camera_index": -3}).sensitivity == 10.0
    assert delete_profile(store, "Default") is False
    assert delete_profile(store, "Desk") and active_profile(store).name == "Default"


# ---- recovery (R4.3) ------------------------------------------------------------


class Clock:
    def __init__(self):
        self.mono, self.wall = 100.0, 1_000_000.0

    def advance(self, seconds, slept=False):
        self.mono += 0 if slept else seconds
        self.wall += seconds


def test_unplugged_device_retries_with_backoff_then_gives_up():
    clock = Clock()
    sup = DeviceSupervisor(delays=(1, 2), clock=lambda: clock.mono, wall=lambda: clock.wall)
    sup.request(True)
    sup.observe("device_lost", "unplugged")
    assert sup.snapshot().state == "waiting_retry"
    assert sup.next_action("device_lost", True) == ACT_NONE
    clock.advance(1.0)
    assert sup.next_action("device_lost", True) == ACT_START
    sup.observe("device_lost")
    clock.advance(2.0)
    assert sup.next_action("device_lost", True) == ACT_START
    sup.observe("device_lost")
    assert sup.snapshot().state == "gave_up"
    sup.retry_now()
    assert sup.next_action("stopped", True) == ACT_START
    sup.observe("running")
    assert sup.snapshot().attempts == 0


def test_permission_and_model_failures_wait_for_the_user():
    sup = DeviceSupervisor()
    sup.request(True)
    for phase in ("permission_denied", "model_unavailable", "missing_dependency"):
        sup.observe(phase, "why")
        assert sup.snapshot().state == "needs_user"
        assert sup.next_action(phase, True) == ACT_NONE


def test_switching_device_stops_waits_for_release_then_starts():
    sup = DeviceSupervisor()
    sup.request(True)
    sup.switch_device(2)
    assert sup.next_action("running", False) == ACT_STOP
    assert sup.next_action("stopping", False) == ACT_NONE      # old capture still releasing
    assert sup.next_action("stopped", True) == ACT_SWITCH
    assert sup.take_pending_device() == 2


def test_sleep_and_wake_restarts_a_running_device_once():
    clock = Clock()
    sup = DeviceSupervisor(clock=lambda: clock.mono, wall=lambda: clock.wall)
    sup.request(True)
    clock.advance(600, slept=True)
    assert sup.next_action("running", False) == ACT_STOP
    assert sup.next_action("stopped", True) == ACT_START
    assert sup.next_action("running", True) == ACT_NONE
    assert DeviceSupervisor().next_action("device_lost", True) == ACT_NONE   # not wanted


class FakeCapture:
    """A camera that delivers ``frames`` frames and then is "unplugged"."""

    released = 0

    def __init__(self, frames):
        self.frames = frames

    def isOpened(self):   # noqa: N802 - cv2 API
        return True

    def read(self):
        if self.frames <= 0:
            return False, None
        self.frames -= 1
        time.sleep(0.005)
        import numpy as np
        return True, np.zeros((4, 4, 3), dtype=np.uint8)

    def release(self):
        FakeCapture.released += 1


def _fake_tracker_modules(monkeypatch, frames):
    import sys

    import numpy as np

    from rigora.puppet import webcam_tracker as wt
    cv2 = SimpleNamespace(VideoCapture=lambda _i: FakeCapture(frames),
                          cvtColor=lambda f, _c: f, COLOR_BGR2RGB=4)
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setitem(sys.modules, "mediapipe", SimpleNamespace())
    monkeypatch.setattr(wt, "_build_face_landmarker", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(wt, "_detect_face", lambda *_a: np.zeros((478, 3)))
    monkeypatch.setattr(wt, "landmarks_to_params", lambda _l: {"ParamAngleX": 12.0})


def test_tracker_reports_a_lost_device_and_releases_it(qapp, monkeypatch):
    from rigora.puppet.webcam_status import WebcamPhase
    from rigora.puppet.webcam_tracker import WebcamTracker
    _fake_tracker_modules(monkeypatch, frames=3)
    writes = []
    canvas = SimpleNamespace(document=lambda: object(), set_parameter_values=writes.append)
    tracker = WebcamTracker(canvas)
    tracker.set_calibrator(Calibrator(InputProfile(smoothing=0.0), {
        "ParamAngleX": (-30, 30, 0)}))
    FakeCapture.released = 0
    assert tracker.set_enabled(True)
    assert tracker.wait_released(5.0)
    assert tracker.status().phase == WebcamPhase.DEVICE_LOST
    tracker._pump_to_canvas()   # noqa: SLF001 - the GUI tick publishes the worker's status
    assert FakeCapture.released == 1 and tracker.can_configure()
    tracker._enabled = True   # noqa: SLF001 - the pump publishes what the worker saw
    tracker._pump_to_canvas()   # noqa: SLF001
    assert writes and writes[-1]["ParamAngleX"] == 12.0
    tracker.shutdown()


def test_tracker_classifies_model_download_failure(qapp, monkeypatch):
    from rigora.puppet import webcam_tracker as wt
    from rigora.puppet.webcam_status import WebcamPhase
    _fake_tracker_modules(monkeypatch, frames=1)

    def no_model():
        raise wt._WebcamSetupError("failed to download face_landmarker.task")   # noqa: SLF001

    monkeypatch.setattr(wt, "_build_face_landmarker", no_model)
    tracker = wt.WebcamTracker(SimpleNamespace(document=lambda: None))
    tracker.set_enabled(True)
    assert tracker.wait_released(5.0)
    assert tracker.status().phase == WebcamPhase.MODEL_UNAVAILABLE
    tracker.shutdown()


def test_mic_loss_is_reported_and_the_stream_released(qapp, monkeypatch):
    import sys

    from rigora.puppet.input_engine import InputEngine
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

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(InputStream=Stream))
    from PySide6.QtCore import QObject, Signal

    class Canvas(QObject):
        cursor_moved = Signal(float, float)

        def document(self):
            return None

    engine = InputEngine(Canvas())
    engine.set_mic_device("USB mic")
    assert engine.set_lipsync_enabled(True)
    assert streams[0].kwargs["device"] == "USB mic" and engine.mic_status()[0] == "running"
    streams[0].kwargs["finished_callback"]()          # the driver ended the stream
    qapp.processEvents()
    assert engine.mic_status()[0] == "device_lost" and streams[0].closed
    assert engine.restart_mic() and engine.mic_status()[0] == "running"
    engine.shutdown()
    assert streams[-1].closed


# ---- outputs (R4.4) ------------------------------------------------------------


def test_slow_receiver_drops_frames_without_blocking_the_producer():
    release = threading.Event()
    received = []

    def slow_send(frame):
        release.wait(2.0)
        received.append(frame)

    pump = FramePump(slow_send, OutputStats("test", target_fps=30), capacity=2)
    started = time.perf_counter()
    for frame in range(50):
        pump.offer(frame)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.05                                  # never waited on the receiver
    assert pump.stats.dropped >= 47 and pump.stats.queue_depth <= 2
    release.set()
    deadline = time.monotonic() + 2
    while len(received) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert received[-1] == 49                              # the newest frame is delivered
    assert pump.close() and not pump.alive


def test_failing_receiver_marks_the_output_failed():
    def broken(_frame):
        raise OSError("receiver closed")

    pump = FramePump(broken, OutputStats("test"), max_errors=3)
    for frame in range(3):
        pump.offer(frame)
        time.sleep(0.02)
    deadline = time.monotonic() + 2
    while not pump.failed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pump.failed and pump.stats.last_error == "receiver closed"
    assert not pump.stats.connected
    pump.close()
    with pytest.raises(ValueError):
        FramePump(broken, OutputStats("x"), capacity=0)


# ---- VTS API (R4.5) --------------------------------------------------------------


def test_tokens_expire_are_revocable_and_bound_to_the_plugin():
    now = [0.0]
    store = vs.TokenStore(ttl=10, clock=lambda: now[0])
    token = store.issue("Tracker", "Dev")
    assert store.check(token, "Tracker", "Dev") == (True, "ok")
    assert store.check(token, "Other")[0] is False
    assert store.check("", None)[1] == "authenticationToken is missing"
    now[0] = 11
    assert store.check(token) == (False, "token expired — request a new one")
    token = store.issue("Tracker", "Dev")
    assert store.revoke_all() == 1 and store.check(token)[0] is False
    for i in range(vs.MAX_TOKENS + 3):
        store.issue(f"plugin{i}", "dev")
    assert len(store.active()) == vs.MAX_TOKENS


def test_rate_limiter_allows_bursts_then_limits():
    now = [0.0]
    limiter = vs.RateLimiter(rate=10, burst=5, clock=lambda: now[0])
    assert all(limiter.allow() for _ in range(5)) and not limiter.allow()
    now[0] = 0.1
    assert limiter.allow() and limiter.limited == 1


class VtsCanvas:
    def __init__(self):
        from rigora.puppet.document import Parameter, PuppetDocument
        self.doc = PuppetDocument(parameters=[Parameter("A", -1, 1, 0), Parameter("B", 0, 1, 0)])
        self.values = {"A": 0.0, "B": 0.0}
        self.arbiter = InputArbiter()

    def document(self):
        return self.doc

    def parameter_values(self):
        return dict(self.values)

    def input_arbiter(self):
        return self.arbiter

    def submit_input(self, source, values, force=False):
        accepted = self.arbiter.submit(source, values)
        self.values.update(accepted)
        return accepted

    def release_input(self, source):
        self.arbiter.release(source)


def _session(canvas, tokens, name="Tracker one", limiter=None):
    from rigora.puppet.vts_api import VTubeStudioHandler
    handler = VTubeStudioHandler(canvas, tokens, limiter)
    token = handler.handle_message({"messageType": "AuthenticationTokenRequest", "data": {
        "pluginName": name, "pluginDeveloper": "Suite"}})["data"]["authenticationToken"]
    handler.handle_message({"messageType": "AuthenticationRequest", "data": {
        "authenticationToken": token, "pluginName": name, "pluginDeveloper": "Suite"}})
    return handler


def _inject(handler, values, **extra):
    return handler.handle_message({"messageType": "InjectParameterDataRequest",
                                   "data": {"parameterValues": values, **extra}})


def test_vts_injection_is_validated_all_or_nothing():
    canvas = VtsCanvas()
    handler = _session(canvas, vs.TokenStore())
    bad = _inject(handler, [{"id": "A", "value": 0.5}, {"id": "Nope", "value": 1}])
    assert bad["data"]["errorID"] == vs.ERR_INJECT_PARAM_NOT_FOUND and canvas.values["A"] == 0
    assert _inject(handler, [{"id": "A", "value": "x"}])["data"]["errorID"] == \
        vs.ERR_INJECT_VALUE_INVALID
    assert _inject(handler, [{"id": "A", "value": 1, "weight": 2}])["data"]["errorID"] == \
        vs.ERR_INJECT_WEIGHT_INVALID
    assert _inject(handler, [])["data"]["errorID"] == vs.ERR_INJECT_NO_DATA
    assert _inject(handler, [{"id": "A", "value": 1}], mode="mul")["data"]["errorID"] == \
        vs.ERR_INJECT_MODE_UNKNOWN
    assert _inject(handler, [{"id": "A", "value": 5}])["data"]["parameterValuesApplied"] == 1
    assert canvas.values["A"] == 1.0                                   # clamped to range
    _inject(handler, [{"id": "A", "value": -0.5}], mode="add")
    assert canvas.values["A"] == pytest.approx(0.5)
    _inject(handler, [{"id": "B", "value": 1, "weight": 0.25}])
    assert canvas.values["B"] == pytest.approx(0.25)
    too_many = [{"id": "A", "value": 0}] * (vs.MAX_VALUES_PER_INJECT + 1)
    assert _inject(handler, too_many)["data"]["errorID"] == vs.ERR_TOO_MANY_VALUES


def test_vts_second_plugin_is_refused_a_held_parameter_and_revocation_logs_out():
    canvas, tokens = VtsCanvas(), vs.TokenStore()
    first = _session(canvas, tokens, "Tracker one")
    second = _session(canvas, tokens, "Tracker two")
    _inject(first, [{"id": "A", "value": 0.4}])
    taken = _inject(second, [{"id": "A", "value": -0.4}])
    assert taken["data"]["errorID"] == vs.ERR_INJECT_PARAM_TAKEN and canvas.values["A"] == 0.4
    first.close()
    assert _inject(second, [{"id": "A", "value": -0.4}])["messageType"] == \
        "InjectParameterDataResponse"
    tokens.revoke_all()
    assert _inject(second, [{"id": "A", "value": 0}])["data"]["errorID"] == \
        vs.ERR_REQUIRES_AUTHENTICATION


def test_vts_rejects_bad_plugin_names_mismatches_and_floods():
    from rigora.puppet.vts_api import VTubeStudioHandler
    canvas, tokens = VtsCanvas(), vs.TokenStore()
    handler = VTubeStudioHandler(canvas, tokens)
    short = handler.handle_message({"messageType": "AuthenticationTokenRequest",
                                    "data": {"pluginName": "x", "pluginDeveloper": "Dev"}})
    assert short["data"]["errorID"] == vs.ERR_TOKEN_PLUGIN_NAME_INVALID
    token = handler.handle_message({"messageType": "AuthenticationTokenRequest", "data": {
        "pluginName": "Tracker", "pluginDeveloper": "Dev"}})["data"]["authenticationToken"]
    wrong = handler.handle_message({"messageType": "AuthenticationRequest", "data": {
        "authenticationToken": token, "pluginName": "Impostor"}})
    assert wrong["data"]["authenticated"] is False
    missing = handler.handle_message({"messageType": "AuthenticationRequest", "data": {}})
    assert missing["data"]["errorID"] == vs.ERR_AUTH_TOKEN_MISSING
    now = [0.0]
    flood = _session(canvas, tokens, "Flooder",
                     vs.RateLimiter(rate=1, burst=2, clock=lambda: now[0]))
    results = [_inject(flood, [{"id": "B", "value": 0.1}])["messageType"] for _ in range(3)]
    assert results[-1] == "APIError"


def test_mic_blocks_in_frames_by_channels_shape_produce_visemes():
    """sounddevice hands (frames, channels) arrays to the callback."""
    import numpy as np

    from rigora.puppet.input_drivers import DEFAULT_MOUTH_PARAM, audio_to_viseme
    tone = (0.5 * np.sin(np.linspace(0, 300, 1024))).astype(np.float32)
    mono = audio_to_viseme(tone)
    assert audio_to_viseme(tone.reshape(-1, 1)) == mono
    stereo = audio_to_viseme(np.stack([tone, tone], axis=1))
    assert stereo[DEFAULT_MOUTH_PARAM] == pytest.approx(mono[DEFAULT_MOUTH_PARAM])
    as_int = (tone * 32767).astype(np.int16)
    stereo_int = audio_to_viseme(np.stack([as_int, as_int], axis=1))
    assert stereo_int[DEFAULT_MOUTH_PARAM] == pytest.approx(mono[DEFAULT_MOUTH_PARAM], abs=1e-3)
