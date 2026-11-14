"""R7.4 resource lifecycle stress in hidden native windows (Windows).

* GL context rebuild — the canvas moves to another top-level window, Qt
  builds a new context, and the canvas must free the old objects, re-upload
  and render the same pixels.
* Frequent document switching — every switch must leave exactly the GL
  objects the new document needs, with memory and OS handles flat.
* Repeated close — editor windows are opened, used and closed; timers,
  threads, top-level widgets, handles and memory must return to baseline,
  and a motion's sound effect must be released with its player.

No window is shown on the desktop and no input is generated. The report
goes to ``--output``; exit status 1 means a check failed.
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
import os
import struct
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from benchmark import rss_bytes  # noqa: E402


def handle_counts() -> dict[str, int]:
    from ctypes import wintypes
    kernel, user = ctypes.windll.kernel32, ctypes.windll.user32
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    user.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    process = kernel.GetCurrentProcess()
    count = wintypes.DWORD()
    kernel.GetProcessHandleCount(process, ctypes.byref(count))
    return {"handles": count.value, "gdi": user.GetGuiResources(process, 0),
            "user": user.GetGuiResources(process, 1)}


def snapshot(app) -> dict:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    gc.collect()
    app.processEvents()
    timers = sum(1 for widget in QApplication.allWidgets()
                 for timer in widget.findChildren(QTimer) if timer.isActive())
    return {"rss_mib": round(rss_bytes() / 2 ** 20, 1), "threads": threading.active_count(),
            "top_level_widgets": len(QApplication.topLevelWidgets()),
            "active_timers": timers, **handle_counts()}


def hidden(widget):
    from PySide6.QtCore import Qt
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    widget.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
    return widget


def frame_hash(canvas, size: int = 256) -> str:
    from PySide6.QtGui import QImage
    image = canvas.render_offscreen_puppet(size, size)
    if image is None or image.isNull():
        raise RuntimeError("empty frame")
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return hashlib.sha256(bytes(rgba.constBits())).hexdigest()


def wait_valid(app, canvas) -> None:
    deadline = time.monotonic() + 10
    while (canvas.context() is None or not canvas.context().isValid()) \
            and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    if canvas.context() is None or not canvas.context().isValid():
        raise RuntimeError("no GL context")


def check_context_rebuild(app, imeru) -> dict:
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from rigora.puppet.canvas import PuppetCanvas
    first, second = hidden(QWidget()), hidden(QWidget())
    for host in (first, second):
        host.resize(300, 300)
        QVBoxLayout(host)
    canvas = PuppetCanvas()
    first.layout().addWidget(canvas)
    first.show()
    wait_valid(app, canvas)
    canvas.load_document(imeru)
    before = frame_hash(canvas)
    counts_before = canvas.gl_resource_counts()
    generation = canvas.gl_context_generation
    second.layout().addWidget(canvas)       # reparent into another window
    second.show()
    wait_valid(app, canvas)
    app.processEvents()
    after = frame_hash(canvas)
    result = {"generation_before": generation, "generation_after": canvas.gl_context_generation,
              "resources_before": counts_before, "resources_after": canvas.gl_resource_counts(),
              "pixels_identical": before == after}
    canvas.load_document(None)
    for host in (first, second):
        host.close()
        host.deleteLater()
    app.processEvents()
    if not result["pixels_identical"] or result["generation_after"] <= generation:
        raise RuntimeError(f"context rebuild failed: {result}")
    return result


def check_document_switching(app, documents: dict, cycles: int) -> dict:
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from rigora.puppet.canvas import PuppetCanvas
    host = hidden(QWidget())
    host.resize(300, 300)
    QVBoxLayout(host)
    canvas = PuppetCanvas()
    host.layout().addWidget(canvas)
    host.show()
    wait_valid(app, canvas)
    # Each visit to a document must hold exactly the GL objects its first visit
    # did (hidden drawables are never uploaded, so the first visit is the truth).
    first_visit: dict[str, dict] = {}
    trend, mismatches = [], []
    names = list(documents)
    for cycle in range(cycles):
        name = names[cycle % len(names)]
        canvas.load_document(documents[name])
        frame_hash(canvas)
        counts = canvas.gl_resource_counts()
        counts.pop("static_textures")          # shared backdrop, created once per context
        if first_visit.setdefault(name, counts) != counts or counts["textures"] == 0:
            mismatches.append({"cycle": cycle, "document": name, **counts})
        if cycle in (cycles // 5, cycles - 1):
            trend.append({"cycle": cycle, **snapshot(app)})
    canvas.load_document(None)
    leftover = canvas.gl_resource_counts()
    host.close()
    host.deleteLater()
    app.processEvents()
    growth = trend[-1]["rss_mib"] - trend[0]["rss_mib"]
    handle_growth = trend[-1]["handles"] - trend[0]["handles"]
    result = {"cycles": cycles, "trend": trend, "rss_growth_mib": round(growth, 1),
              "handle_growth": handle_growth, "gl_mismatches": mismatches,
              "gl_per_document": first_visit, "after_unload": leftover}
    if (mismatches or growth > 64 or handle_growth > 50 or leftover["buffers"]
            or leftover["textures"] or leftover["static_textures"] > 2):
        raise RuntimeError(f"document switching leaks: {result}")
    return result


def _silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(struct.pack("<h", 0) * 4000)


def check_repeated_close(app, imeru_path: Path, rounds: int, workdir: Path) -> dict:
    from PySide6.QtCore import QCoreApplication, QEvent
    from rigora.editor_window import EditorWindow
    from rigora.puppet.document import Motion, MotionSegment, MotionTrack
    wav = workdir / "silence.wav"
    _silent_wav(wav)
    baseline = snapshot(app)
    samples = []
    for index in range(rounds):
        window = hidden(EditorWindow())
        window.show()
        canvas = window.editor.canvas()
        wait_valid(app, canvas)
        if not window.editor.open_puppet(str(imeru_path)):
            raise RuntimeError("open failed")
        frame_hash(canvas)
        player = window.editor._motion_dock.player()   # noqa: SLF001
        parameter = canvas.document().parameters[0]
        motion = Motion("probe", 0.5, tracks=[MotionTrack(parameter.id, [
            MotionSegment("linear", (0.0, parameter.min), (0.5, parameter.max))])],
            sound_path=str(wav))
        player.set_motion(motion)
        player.play()
        app.processEvents()
        effect = getattr(player, "_sound_effect", None)
        if effect is not None:
            effect.setVolume(0.0)
        window.shutdown()
        released = getattr(player, "_sound_effect", None) is None
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        if not released:
            raise RuntimeError("motion sound effect survived shutdown")
        samples.append({"round": index, **snapshot(app)})
    final = samples[-1]
    second = samples[1] if len(samples) > 1 else samples[0]
    result = {"rounds": rounds, "baseline": baseline, "after_second": second, "final": final,
              "sound_released": True}
    problems = []
    if final["active_timers"] > baseline["active_timers"]:
        problems.append("timers")
    if final["threads"] > baseline["threads"] + 1:
        problems.append("threads")
    if final["top_level_widgets"] > baseline["top_level_widgets"]:
        problems.append("top-level widgets")
    if final["rss_mib"] - second["rss_mib"] > 96:
        problems.append("memory")
    if final["handles"] - second["handles"] > 100:
        problems.append("handles")
    if problems:
        raise RuntimeError(f"repeated close leaks {problems}: {result}")
    return result


def run(output: Path, cycles: int, rounds: int) -> dict:
    from PySide6.QtWidgets import QApplication
    from rigora.puppet.document_io import load_puppet
    from rigora.system import settings
    from rigora.system.app_paths import examples_dir
    sys.path.insert(0, str(ROOT / "scripts"))
    import bench_scenes

    settings.configure()
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    imeru_path = examples_dir() / "puppet" / "imeru.puppet"
    imeru = load_puppet(imeru_path)
    report = {"start": snapshot(app)}
    report["context_rebuild"] = check_context_rebuild(app, imeru)
    documents = {"imeru": imeru,
                 "many_drawables": bench_scenes.build_scene("many_drawables").documents[0],
                 "masks": bench_scenes.build_scene("masks").documents[0]}
    report["document_switching"] = check_document_switching(app, documents, cycles)
    with tempfile.TemporaryDirectory(prefix="rigora-life-") as tmp:
        report["repeated_close"] = check_repeated_close(app, imeru_path, rounds, Path(tmp))
    report["end"] = snapshot(app)
    report["status"] = "passed"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=60)
    parser.add_argument("--rounds", type=int, default=6)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("this hidden native-window check runs on Windows")
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    os.environ.setdefault("RIGORA_DATA_DIR", tempfile.mkdtemp(prefix="rigora-life-data-"))
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        report = run(args.output, args.cycles, args.rounds)
    except Exception as exc:   # noqa: BLE001 - every failure must land in the report
        import traceback
        report = {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
    (args.output / "lifecycle.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("status", "error")}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
