"""R3 acceptance in the real hidden editor, invoked by verify_gui.py.

Record a take, trim it with key edits, arrange clips in a composition, add a
lip-sync motion from a WAV, and export through the hidden-canvas offline
renderer. Checks the planned frame count and length of each output, that the
MP4 carries a sound stream, that PNG frames keep real transparency, that two
renders of the same input are identical, and that a cancelled export leaves
no file. No device, window or desktop input is used.
"""
from __future__ import annotations

import hashlib
import re
import struct
import subprocess
import time
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np


def _wav(path: Path, seconds: float = 2.0, rate: int = 16000) -> Path:
    samples = np.zeros(int(seconds * rate))
    start, end = int(0.4 * rate), int(1.4 * rate)
    samples[start:end] = 0.4 * np.sin(np.linspace(0, 2000, end - start))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"".join(struct.pack("<h", int(s * 32767)) for s in samples))
    return path


def _probe(path: Path) -> dict:
    import imageio_ffmpeg
    frames, seconds = imageio_ffmpeg.count_frames_and_secs(str(path))
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                            capture_output=True, text=True, check=False)
    return {"frames": frames, "seconds": round(seconds, 3),
            "audio": bool(re.search(r"Stream #\S+: Audio", result.stderr))}


def _require(value, message):
    if not value:
        raise RuntimeError(message)


def _record_take(editor, app) -> str:
    """Drive a parameter for about a second while the recorder samples it."""
    canvas = editor.canvas()
    parameter = canvas.document().parameters[0]
    recorder = editor._motion_recorder   # noqa: SLF001
    _require(recorder.start("verify_take", inputs=["scripted"]), "Recorder did not start")
    begin = time.monotonic()
    while time.monotonic() - begin < 1.0:
        phase = (time.monotonic() - begin) / 1.0
        canvas.set_parameter_value(parameter.id, parameter.min
                                   + (parameter.max - parameter.min) * phase)
        app.processEvents()
        time.sleep(0.01)
    take = recorder.stop()
    _require(take is not None and take.tracks, "Recording produced no take")
    return take.name


def check_animation_workflow(window, root: Path) -> dict:
    from PySide6.QtWidgets import QApplication
    from rigora.puppet.document import Clip, Composition, CompositionLayer
    from rigora.puppet.motion_keys import keys, move_keys
    from rigora.puppet.offline_export import CANCELLED, DONE, ExportSettings, frame_times

    app = QApplication.instance()
    editor = window.editor
    canvas = editor.canvas()
    session = editor.session
    report: dict = {}

    take_name = _record_take(editor, app)
    document = session.document
    take = next(m for m in document.motions if m.name == take_name)
    _require(take.take and take.take["source"] == "live recording", "Take record missing")
    # Same name again: the editor asks; "Keep both" is answered in code.
    with patch.object(type(editor), "_choose_take_conflict", lambda self, name: "rename"):
        _record_take(editor, app)
    names = [m.name for m in session.document.motions if m.name.startswith("verify_take")]
    _require(names == ["verify_take", "verify_take (2)"], f"Retake overwrote: {names}")
    report["takes"] = {"names": names, "source": take.take["source"],
                       "fps": take.take.get("fps")}

    track = take.tracks[0]
    before = len(keys(track))
    with session.transaction("Trim take"):
        track = next(m for m in session.document.motions if m.name == take_name).tracks[0]
        move_keys(track, [len(keys(track)) - 1], 0.0, 0.0)
    _require(session.can_undo, "Key edit was not recorded")

    wav = _wav(root / "line.wav")
    mouth = next(p for p in session.document.parameters if p.id == "ParamMouthOpenY")
    lipsync = editor._add_lipsync_motion(wav, mouth, fps=30.0, lead=0.04,   # noqa: SLF001
                                         conflict="rename")
    _require(lipsync is not None, "Lip-sync motion was not added")

    composition = Composition("verify_show", 2.0, [
        CompositionLayer("body", [Clip(take_name, length=2.0, loop=True)]),
        CompositionLayer("mouth", [Clip(lipsync)], blend="override"),
    ])
    _require(editor.apply_compositions([composition]), "Composition was refused")
    report["edits"] = {"take_keys": before, "lipsync": lipsync, "composition": "verify_show"}

    queue = editor.export_queue()
    exports = root / "exports"
    jobs = {
        "png": editor.queue_export("composition", "verify_show",
                                   ExportSettings(width=320, height=320, fps=24,
                                                  format="png_sequence"), exports / "show_png"),
        "png_again": editor.queue_export("composition", "verify_show",
                                         ExportSettings(width=320, height=320, fps=24,
                                                        format="png_sequence"),
                                         exports / "show_png_again"),
        "mp4": editor.queue_export("motion", lipsync,
                                   ExportSettings(width=320, height=320, fps=30, format="mp4",
                                                  background=(1, 1, 1, 1)),
                                   exports / "talk.mp4"),
        "cancelled": editor.queue_export("composition", "verify_show",
                                         ExportSettings(width=320, height=320, fps=24,
                                                        format="gif"), exports / "never.gif"),
    }
    queue.cancel(jobs["cancelled"].id)
    deadline = time.monotonic() + 120
    while queue.busy() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    states = {name: job.state for name, job in jobs.items()}
    _require(states == {"png": DONE, "png_again": DONE, "mp4": DONE, "cancelled": CANCELLED},
             f"Export states: {states} {[j.error for j in jobs.values()]}")
    _require(not (exports / "never.gif").exists(), "Cancelled export left a file")

    expected_png = len(frame_times(jobs["png"].settings, 2.0))
    frames = sorted(jobs["png"].output.iterdir())
    again = sorted(jobs["png_again"].output.iterdir())
    _require(len(frames) == expected_png == len(again), "PNG frame count is wrong")
    digest = [hashlib.sha256(p.read_bytes()).hexdigest() for p in frames]
    _require(digest == [hashlib.sha256(p.read_bytes()).hexdigest() for p in again],
             "Two renders of the same input differ")
    from PIL import Image
    alpha = np.asarray(Image.open(frames[len(frames) // 2]))[..., 3]
    _require(alpha.min() == 0 and alpha.max() == 255, "PNG frames lost transparency")

    talk = next(m for m in session.document.motions if m.name == lipsync)
    expected_mp4 = len(frame_times(jobs["mp4"].settings, talk.duration))
    probe = _probe(jobs["mp4"].output)
    _require(probe["audio"], "MP4 has no sound stream")
    _require(abs(probe["frames"] - expected_mp4) <= 1, f"MP4 frames {probe} vs {expected_mp4}")
    _require(abs(probe["seconds"] - talk.duration) <= 0.1, f"MP4 length {probe}")
    report["exports"] = {
        "png": {"frames": len(frames), "expected": expected_png, "identical_rerun": True,
                "alpha_range": [int(alpha.min()), int(alpha.max())]},
        "mp4": {**probe, "expected_frames": expected_mp4,
                "expected_seconds": round(talk.duration, 3)},
        "cancelled_left_no_file": True,
    }
    canvas.reset_parameters()
    return report
