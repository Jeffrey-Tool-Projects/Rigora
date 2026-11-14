"""Hands-on device acceptance session (R4.1 / R4.3 / R5.2).

Runs the real editor (main window hidden) and waits for one-line commands in
a control file, so a person can unplug devices, change display settings or
put the computer to sleep while the session records what Rigora does. Every
observation is appended as a JSON line to ``events.jsonl``.

    py scripts/device_session.py --dir .audit/device

Commands (write one per line to ``DIR/control.txt``; each is run once):

    devices                      list cameras and microphones (no device opened)
    cam_start [index]            start webcam tracking (opens the camera)
    calibrate                    capture a 2 s neutral pose
    track SECONDS                record tracked parameter ranges
    cam_switch INDEX             switch camera while tracking
    model_fail / model_restore   make the face-model download fail / restore it
    retry                        Live status > Retry devices
    cam_stop                     stop tracking and check the camera is released
    mic_start [name]             start microphone lip-sync on a device
    mic_track SECONDS            record mouth values
    mic_switch NAME              switch microphone
    mic_stop                     stop lip-sync and check the stream is closed
    pet_show                     show a desktop character (a visible window)
    pet_move X Y                 move it
    pet_stop                     close it
    status                       write the current state
    quit                         shut everything down
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TRACKED = ("ParamAngleX", "ParamAngleY", "ParamEyeLOpen", "ParamMouthOpenY")


class Session:
    def __init__(self, folder: Path) -> None:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import QApplication

        from rigora.editor_window import EditorWindow
        from rigora.system import settings
        from rigora.system.app_paths import examples_dir

        self.folder = folder
        self.events = folder / "events.jsonl"
        self.control = folder / "control.txt"
        self.done = 0
        settings.configure(folder / "settings.json")
        self.app = QApplication.instance() or QApplication([])
        self.app.setQuitOnLastWindowClosed(False)
        self.window = EditorWindow()
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.window.show()
        self.editor = self.window.editor
        deadline = time.monotonic() + 10
        while self.editor.canvas().context() is None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.editor.open_puppet(str(examples_dir() / "puppet" / "imeru.puppet"))
        self.canvas = self.editor.canvas()
        self.pets = None
        self.ranges: dict | None = None
        self.last_state: dict = {}
        self.timer = QTimer()
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.log("ready", pid=os.getpid())

    def log(self, event: str, **data) -> None:
        line = {"t": round(time.time(), 2), "event": event, **data}
        with self.events.open("a", encoding="utf-8") as out:
            out.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")

    # ---- observation ---------------------------------------------------------

    def state(self) -> dict:
        report = self.editor.device_report()
        values = self.canvas.parameter_values()
        state = {"camera": report["camera"]["phase"],
                 "camera_recovery": report["camera"]["recovery"]["state"],
                 "camera_detail": report["camera"]["detail"],
                 "mic": report["microphone"]["phase"],
                 "mic_recovery": report["microphone"]["recovery"]["state"],
                 "mic_device": report["microphone"]["device"]}
        state["owners"] = {p: o for p, o in self.canvas.input_arbiter().owners().items()
                           if p in TRACKED}
        state["values"] = {p: round(values.get(p, 0.0), 3) for p in TRACKED}
        if self.pets is not None and self.pets.running():
            pet = self.pets.windows[self.pets.running()[0]]
            state["pet"] = {"x": pet.x(), "y": pet.y(), "w": pet.width(), "h": pet.height(),
                            "visible": pet.isVisible()}
        return state

    def tick(self) -> None:
        try:
            state = self.state()
            keys = ("camera", "camera_recovery", "mic", "mic_recovery", "mic_device")
            changed = {k: state[k] for k in keys if state[k] != self.last_state.get(k)}
            if "pet" in state and state["pet"] != self.last_state.get("pet"):
                changed["pet"] = state["pet"]
            if changed:
                self.log("state", **changed, detail=state["camera_detail"])
            if self.ranges is not None:
                for p, v in state["values"].items():
                    low, high = self.ranges.setdefault(p, [v, v])
                    self.ranges[p] = [min(low, v), max(high, v)]
            self.last_state = state
            self.read_commands()
        except Exception:   # noqa: BLE001 - keep the session alive, report everything
            self.log("error", traceback=traceback.format_exc())

    def read_commands(self) -> None:
        if not self.control.exists():
            return
        lines = [line.strip() for line in self.control.read_text(encoding="utf-8").splitlines()]
        for line in lines[self.done:]:
            self.done += 1
            if line:
                self.run(line)

    # ---- commands ----------------------------------------------------------------

    def run(self, line: str) -> None:
        name, *args = line.split(maxsplit=1)
        argument = args[0] if args else ""
        self.log("command", command=line)
        handler = getattr(self, f"do_{name}", None)
        if handler is None:
            self.log("error", message=f"unknown command {name}")
            return
        handler(argument)

    def do_devices(self, _arg) -> None:
        from rigora.puppet.workspace_live_io import camera_devices, microphone_devices
        self.log("devices", cameras=camera_devices(), microphones=microphone_devices())

    def do_status(self, _arg) -> None:
        self.log("status", **self.state(), profile=self.editor._input_profile.to_dict())  # noqa: SLF001

    def do_cam_start(self, arg) -> None:
        index = int(arg or 0)
        self.editor.switch_camera(index)
        self.editor._webcam_supervisor.request(True)   # noqa: SLF001
        ok = self.editor._webcam.set_enabled(True)   # noqa: SLF001
        self.log("cam_start", accepted=ok, index=index)

    def do_calibrate(self, _arg) -> None:
        started = self.editor.capture_neutral_pose(
            2.0, done=lambda neutral: self.log("calibrated", neutral=neutral,
                                               channels=len(self.editor._input_profile.channels)))  # noqa: SLF001
        self.log("calibrate", started=started)

    def do_track(self, arg) -> None:
        from PySide6.QtCore import QTimer
        self.ranges = {}
        QTimer.singleShot(int(float(arg or 5) * 1000), self._end_track)

    def _end_track(self) -> None:
        ranges, self.ranges = self.ranges, None
        self.log("ranges", ranges=ranges)

    def do_mic_track(self, arg) -> None:
        self.do_track(arg)

    def do_cam_switch(self, arg) -> None:
        self.editor.switch_camera(int(arg))
        self.log("cam_switch", index=int(arg))

    def do_model_fail(self, _arg) -> None:
        from rigora.puppet import webcam_tracker as wt
        from rigora.system.app_paths import app_dir
        model = app_dir() / "models" / "face_landmarker.task"
        if model.exists():
            model.rename(model.with_suffix(".task.kept"))
        self._url = wt._FACE_LANDMARKER_MODEL_URL   # noqa: SLF001
        wt._FACE_LANDMARKER_MODEL_URL = "https://invalid.rigora-acceptance.example/face.task"  # noqa: SLF001
        self.log("model_fail", cache_hidden=True)

    def do_model_restore(self, _arg) -> None:
        from rigora.puppet import webcam_tracker as wt
        from rigora.system.app_paths import app_dir
        kept = app_dir() / "models" / "face_landmarker.task.kept"
        if kept.exists():
            kept.rename(kept.with_suffix("").with_suffix(".task"))
        wt._FACE_LANDMARKER_MODEL_URL = getattr(self, "_url", wt._FACE_LANDMARKER_MODEL_URL)  # noqa: SLF001
        self.log("model_restore")

    def do_retry(self, _arg) -> None:
        self.editor.retry_devices()
        self.log("retry")

    def do_cam_stop(self, _arg) -> None:
        self.editor._webcam_supervisor.request(False)   # noqa: SLF001
        self.editor._webcam.set_enabled(False)   # noqa: SLF001
        released = self.editor._webcam.wait_released(5.0)   # noqa: SLF001
        self.log("cam_stop", thread_released=released,
                 phase=self.editor._webcam.status().phase.value)   # noqa: SLF001

    def do_mic_start(self, arg) -> None:
        self.editor._input_engine.set_mic_device(arg)   # noqa: SLF001
        self.editor._lipsync_toggle.setChecked(True)   # noqa: SLF001
        self.log("mic_start", device=arg or "default",
                 running=self.editor._input_engine.lipsync_enabled())   # noqa: SLF001

    def do_mic_switch(self, arg) -> None:
        ok = self.editor._input_engine.set_mic_device(arg)   # noqa: SLF001
        self.log("mic_switch", device=arg, ok=ok)

    def do_mic_stop(self, _arg) -> None:
        self.editor._lipsync_toggle.setChecked(False)   # noqa: SLF001
        engine = self.editor._input_engine   # noqa: SLF001
        self.log("mic_stop", stream_open=engine._mic_stream is not None,   # noqa: SLF001
                 phase=engine.mic_status()[0])

    def do_pet_show(self, _arg) -> None:
        from rigora.desktop_pet import pet_roster
        from rigora.desktop_pet import settings as pet_settings
        from rigora.desktop_pet.pet_companions import CompanionManager
        from rigora.desktop_pet.pet_placement import collect_screens
        from rigora.desktop_pet.pet_screens import ScreenWatcher
        from rigora.system.app_paths import examples_dir
        self.pets = CompanionManager(screens=collect_screens)
        pet_id = pet_roster.add_character("Acceptance")
        pet_settings.update(pet_id, last_rig_path=str(examples_dir() / "puppet" / "imeru.puppet"),
                            speech_enabled=False, hide_on_fullscreen=True)
        self.pets.start(pet_id)

        def changed(reason):
            outcome = self.pets.revalidate(reason)
            self.log("screens_changed", reason=reason, outcome=outcome,
                     screens=[(s.name, s.available) for s in collect_screens()])

        self.watcher = ScreenWatcher(changed)
        self.log("pet_show", pet=pet_id, screens=[(s.name, s.available) for s in collect_screens()])

    def do_pet_move(self, arg) -> None:
        x, y = (int(v) for v in arg.split())
        pet = self.pets.windows[self.pets.running()[0]]
        pet.move(x, y)
        self.pets._remember_position(self.pets.running()[0], pet)   # noqa: SLF001
        self.log("pet_move", x=x, y=y)

    def do_pet_stop(self, _arg) -> None:
        from rigora.desktop_pet import pet_roster
        if self.pets is not None:
            ids = self.pets.running()
            self.watcher.stop()
            self.pets.shutdown()
            for pet_id in ids:
                pet_roster.remove_character(pet_id)
            self.pets = None
        self.log("pet_stop")

    def do_quit(self, _arg) -> None:
        self.do_pet_stop("")
        self.window.shutdown()
        self.log("quit")
        self.app.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args()
    args.dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    os.environ.setdefault("RIGORA_DATA_DIR", str(args.dir.resolve() / "data"))
    session = Session(args.dir.resolve())
    return session.app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
