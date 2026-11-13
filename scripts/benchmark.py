"""Measure Rigora on the R7.1 benchmark scenes and save a reproducible report (R7.2).

CPU measurements run headless. ``--gl`` adds GPU render, read-back and export
throughput through a native canvas that is never shown on the desktop
(Windows; the window is created with WA_DontShowOnScreen, like
``verify_gui.py``). No mouse, keyboard or focus is touched.

The report records hardware, OS, Python and library versions, the source
revision and dirty state, the command line and every scene's actual scale,
so a rerun on the same machine can be compared number for number.

    py -3 scripts/benchmark.py --output .audit/r7/baseline
    py -3 scripts/benchmark.py --gl --soak 120 --output .audit/r7/baseline-gl
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from bench_scenes import SCENE_NAMES, Scene, build_scene, scene_scale  # noqa: E402

FPS = 60.0


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def rss_bytes() -> int:
    """Resident set size of this process, without third-party packages."""
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters),
                                          counters.cb):
            raise ctypes.WinError()
        return int(counters.WorkingSetSize)
    statm = Path("/proc/self/statm")
    if statm.exists():
        return int(statm.read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    import resource
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor()


def _total_memory() -> int | None:
    if sys.platform == "win32":
        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = Status()
        status.dwLength = ctypes.sizeof(Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def power_state() -> dict:
    """Power plan and supply, which move laptop timings by up to 2× (R7.3)."""
    state: dict = {"ac_power": None, "battery_percent": None, "battery_saver": None,
                   "power_scheme": None}
    if sys.platform != "win32":
        return state

    class Status(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    status = Status()
    if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        state["ac_power"] = {0: False, 1: True}.get(status.ACLineStatus)
        state["battery_percent"] = None if status.BatteryLifePercent == -1 \
            else int(status.BatteryLifePercent) & 0xFF
        state["battery_saver"] = bool(status.SystemStatusFlag)
    try:
        out = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, timeout=10,
                             check=False).stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return state
    import re
    match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out)
    state["power_scheme"] = match.group(0) if match else None
    return state


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                             timeout=20, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def _version(module: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(module)
    except Exception:   # noqa: BLE001 - metadata backends vary; absence is the answer
        return None


def environment(argv: list[str]) -> dict:
    status = _git("status", "--porcelain")
    return {
        "command": [sys.executable, *argv],
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": _cpu_name(),
        "logical_cpus": os.cpu_count(),
        "memory_bytes": _total_memory(),
        "power": power_state(),
        "packages": {name: _version(name) for name in ("rigora", "numpy", "Pillow", "PySide6",
                                                       "PyOpenGL")},
        "source": {"root": str(ROOT), "revision": _git("rev-parse", "HEAD"),
                   "dirty_files": len(status.splitlines()) if status is not None else None},
    }


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------


def _stats(samples: list[float]) -> dict:
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {"n": len(samples), "median_ms": statistics.median(ordered) * 1e3,
            "p95_ms": p95 * 1e3, "max_ms": ordered[-1] * 1e3,
            "mean_ms": statistics.fmean(ordered) * 1e3}


def _timed(func, repeat: int) -> list[float]:
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        func()
        samples.append(time.perf_counter() - start)
    return samples


def cold_start(repeat: int) -> dict:
    """Fresh interpreter wall time; the median hides one-off disk-cache misses."""
    probes = {
        "import_core": "import rigora.puppet.document_io, rigora.puppet.runtime",
        "import_gui": "import rigora.editor_window",
        "open_imeru": ("from rigora.puppet.document_io import load_puppet;"
                       "from rigora.system.app_paths import examples_dir;"
                       "load_puppet(examples_dir() / 'puppet' / 'imeru.puppet')"),
    }
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    out = {}
    for name, code in probes.items():
        samples, failure = [], None
        for _ in range(repeat):
            start = time.perf_counter()
            done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                                  capture_output=True, text=True, timeout=120, check=False)
            if done.returncode:
                failure = done.stderr.strip().splitlines()[-1:] or [f"exit {done.returncode}"]
                break
            samples.append(time.perf_counter() - start)
        out[name] = {"error": failure[0]} if failure else _stats(samples)
    return out


class FrameEvaluator:
    """What the editor canvas computes per frame, without GL: motion sampling,
    physics, vertex composition, pose / part visibility, opacity and tint."""

    def __init__(self, document) -> None:
        from rigora.puppet.physics import PhysicsEngine
        from rigora.puppet.runtime import default_parameter_values
        self.document = document
        self.motion = document.motions[0] if document.motions else None
        self.defaults = default_parameter_values(document)
        self.physics = PhysicsEngine()
        self.physics.bind_document(document)

    def values_at(self, t: float) -> dict[str, float]:
        from rigora.puppet.motion_sampler import sample_motion
        values = dict(self.defaults)
        if self.motion is not None:
            values.update(sample_motion(self.motion, t, loop=True))
        return values

    def frame(self, t: float) -> int:
        from rigora.puppet.runtime import (
            compose_all_drawables,
            resolve_drawable_color,
            resolve_drawable_opacity,
            resolve_part_state,
            resolve_pose_visibility,
        )
        doc = self.document
        values = self.values_at(t)
        values.update(self.physics.step(1.0 / FPS, values))
        vertices = compose_all_drawables(doc, values)
        resolve_pose_visibility(doc, None)
        resolve_part_state(doc)
        for drawable in doc.drawables:
            resolve_drawable_opacity(drawable, values)
            resolve_drawable_color(drawable, values)
        return len(vertices)


def measure_io(scene: Scene, repeat: int, workdir: Path) -> dict:
    from rigora.puppet.document_io import load_puppet, save_puppet
    paths = [workdir / f"{scene.name}_{i}.puppet" for i in range(len(scene.documents))]
    save = _timed(lambda: [save_puppet(doc, p) for doc, p in zip(scene.documents, paths,
                                                                   strict=True)], repeat)
    gc.collect()
    before = rss_bytes()
    loaded = []
    open_samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        loaded = [load_puppet(p) for p in paths]
        open_samples.append(time.perf_counter() - start)
    gc.collect()
    after = rss_bytes()
    roundtrip = [scene_scale(Scene(scene.name, loaded, ""))[k] == scene_scale(scene)[k]
                 for k in ("drawables", "vertices", "parameters", "physics_rigs")]
    return {"save": _stats(save), "open": _stats(open_samples),
            "archive_bytes": sum(p.stat().st_size for p in paths),
            "rss_delta_after_open_bytes": after - before,
            "roundtrip_scale_matches": all(roundtrip)}


def measure_frames(scene: Scene, frames: int) -> dict:
    evaluators = [FrameEvaluator(doc) for doc in scene.documents]
    for warm in range(10):
        for evaluator in evaluators:
            evaluator.frame(warm / FPS)
    sample_times, frame_times = [], []
    for index in range(frames):
        t = index / FPS
        start = time.perf_counter()
        for evaluator in evaluators:
            evaluator.values_at(t)
        sample_times.append(time.perf_counter() - start)
        start = time.perf_counter()
        for evaluator in evaluators:
            evaluator.frame(t)
        frame_times.append(time.perf_counter() - start)
    return {"motion_sampling": _stats(sample_times), "cpu_frame": _stats(frame_times),
            "frames": frames, "sim_fps": FPS}


def soak(scene: Scene, seconds: float) -> dict:
    """Run frames for ``seconds`` and fit RSS against time to expose growth."""
    evaluators = [FrameEvaluator(doc) for doc in scene.documents]
    gc.collect()
    points: list[tuple[float, int]] = []
    start = time.perf_counter()
    next_sample, frame = start, 0
    while (now := time.perf_counter()) - start < seconds:
        for evaluator in evaluators:
            evaluator.frame(frame / FPS)
        frame += 1
        if now >= next_sample:
            points.append((now - start, rss_bytes()))
            next_sample = now + 0.5
    points.append((time.perf_counter() - start, rss_bytes()))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs) or 1.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator
    half = len(ys) // 2
    return {"seconds": seconds, "frames": frame, "samples": len(points),
            "rss_start_bytes": ys[0], "rss_end_bytes": ys[-1], "rss_max_bytes": max(ys),
            "rss_slope_bytes_per_min": slope * 60,
            "rss_second_half_growth_bytes": ys[-1] - ys[half] if half else 0}


# ---------------------------------------------------------------------------
# GPU (native, never shown)
# ---------------------------------------------------------------------------


def _hidden_canvas(app, size: int):
    """A native GL canvas that is never mapped to the desktop or focused."""
    from PySide6.QtCore import Qt
    from rigora.puppet.canvas import PuppetCanvas

    canvas = PuppetCanvas()
    canvas.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    canvas.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    canvas.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
    canvas.resize(size, size)
    canvas.show()
    deadline = time.monotonic() + 10
    while ((canvas.context() is None or not canvas.context().isValid())
           and time.monotonic() < deadline):
        app.processEvents()
        time.sleep(0.01)
    if canvas.context() is None or not canvas.context().isValid():
        _close(app, canvas)
        return None
    return canvas


def _close(app, canvas) -> None:
    canvas.load_document(None)
    canvas.close()
    canvas.deleteLater()
    app.processEvents()


def _window_hidden(canvas) -> bool:
    if sys.platform != "win32":
        return True
    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    return not bool(user32.IsWindowVisible(int(canvas.winId())))


def measure_gl(scenes: list[Scene], frames: int, size: int, workdir: Path) -> dict:
    from OpenGL.GL import GL_RENDERER, GL_VERSION, glGetString
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    probe = _hidden_canvas(app, size)
    if probe is None:
        return {"error": "no native GL context"}
    probe.makeCurrent()
    out = {"renderer": glGetString(GL_RENDERER).decode(),
           "gl_version": glGetString(GL_VERSION).decode(), "target_px": size, "scenes": {}}
    probe.doneCurrent()
    _close(app, probe)
    hidden = []
    for scene in scenes:
        out["scenes"][scene.name] = _gl_scene(app, scene, frames, size, workdir, hidden)
    out["window_hidden"] = all(hidden)
    return out


def _gl_scene(app, scene: Scene, frames: int, size: int, workdir: Path,
              hidden: list[bool]) -> dict:
    """``render_offscreen_puppet`` (draw + FBO read-back, what streaming and
    export use) and PNG export throughput. A multi-document scene gets one
    canvas per document, as separate pets would; times add up per frame."""
    canvases = []
    try:
        for _ in scene.documents:
            canvas = _hidden_canvas(app, size)
            if canvas is None:
                return {"error": "no native GL context"}
            canvases.append(canvas)
            hidden.append(_window_hidden(canvas))
        return _gl_frames(app, scene, canvases, frames, size, workdir)
    finally:
        for canvas in canvases:
            _close(app, canvas)


def _gl_frames(app, scene: Scene, canvases: list, frames: int, size: int,
               workdir: Path) -> dict:
    load, render, encode = [], [], []
    evaluators = [FrameEvaluator(doc) for doc in scene.documents]
    for canvas, evaluator in zip(canvases, evaluators, strict=True):
        start = time.perf_counter()
        canvas.load_document(evaluator.document)
        app.processEvents()
        load.append(time.perf_counter() - start)
    image = None
    for index in range(frames):
        t = index / FPS
        frame_render = 0.0
        for canvas, evaluator in zip(canvases, evaluators, strict=True):
            canvas.set_parameter_values(evaluator.values_at(t))
            start = time.perf_counter()
            image = canvas.render_offscreen_puppet(size, size)
            frame_render += time.perf_counter() - start
            if image is None or image.isNull():
                return {"error": f"empty render at frame {index}"}
        render.append(frame_render)
        if index < 30:
            start = time.perf_counter()
            image.save(str(workdir / f"{scene.name}_{index:03d}.png"))
            encode.append(time.perf_counter() - start)
    per_frame = statistics.median(render) + statistics.median(encode)
    return {"canvases": len(canvases), "upload_and_bind": _stats(load),
            "render_readback": _stats(render), "png_encode": _stats(encode),
            "export_frames_per_second": 1.0 / per_frame if per_frame else None}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace, argv: list[str]) -> dict:
    report = {"environment": environment(argv),
              "parameters": {"scenes": args.scenes, "repeat": args.repeat, "frames": args.frames,
                             "cold_repeat": args.cold_repeat,
                             "soak_seconds": args.soak, "soak_scene": args.soak_scene,
                             "gl": args.gl, "gl_frames": args.gl_frames, "gl_size": args.gl_size},
              "cold_start": cold_start(args.cold_repeat) if args.cold_repeat else {},
              "scenes": {}}
    scenes = []
    with tempfile.TemporaryDirectory(prefix="rigora-bench-") as tmp:
        workdir = Path(tmp)
        for name in args.scenes:
            gc.collect()
            start = time.perf_counter()
            scene = build_scene(name)
            built = time.perf_counter() - start
            scenes.append(scene)
            report["scenes"][name] = {
                "description": scene.description, "scale": scene_scale(scene),
                "build_seconds": built, "io": measure_io(scene, args.repeat, workdir),
                "frames": measure_frames(scene, args.frames),
            }
            print(f"{name}: cpu frame median "
                  f"{report['scenes'][name]['frames']['cpu_frame']['median_ms']:.2f} ms",
                  flush=True)
        if args.soak > 0:
            soak_scene = next((s for s in scenes if s.name == args.soak_scene), None) \
                or build_scene(args.soak_scene)
            report["soak"] = {"scene": soak_scene.name, **soak(soak_scene, args.soak)}
        if args.gl:
            report["gl"] = measure_gl(scenes, args.gl_frames, args.gl_size, workdir)
    report["rss_end_bytes"] = rss_bytes()
    return report


def _row(name: str, data: dict) -> str:
    frames, io = data["frames"], data["io"]
    scale = data["scale"]
    return (f"| {name} | {scale['drawables']} | {scale['vertices']} | {scale['deformers']} "
            f"(depth {scale['max_deformer_depth']}) | {scale['clip_masks']} | "
            f"{scale['physics_rigs']} | {io['open']['median_ms']:.1f} | "
            f"{io['save']['median_ms']:.1f} | {frames['motion_sampling']['median_ms']:.3f} | "
            f"{frames['cpu_frame']['median_ms']:.2f} / {frames['cpu_frame']['p95_ms']:.2f} |")


def markdown(report: dict) -> str:
    env = report["environment"]
    lines = [
        "# Rigora benchmark", "",
        f"- Started: {env['started']}",
        f"- Source: `{env['source']['revision']}` ({env['source']['dirty_files']} changed files)",
        f"- Machine: {env['cpu']}, {env['logical_cpus']} logical CPUs, "
        f"{(env['memory_bytes'] or 0) / 2**30:.1f} GiB, {env['platform']}",
        f"- Python {env['python'].split()[0]}; " + ", ".join(
            f"{k} {v}" for k, v in env["packages"].items() if v),
        f"- Parameters: `{json.dumps(report['parameters'])}`", "",
        "| Scene | Drawables | Vertices | Deformers | Masks | Physics | Open ms | Save ms | "
        "Sample ms | CPU frame median / p95 ms |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    lines += [_row(name, data) for name, data in report["scenes"].items()]
    if report["cold_start"]:
        lines += ["", "Cold start (fresh process, median ms): " + ", ".join(
            f"{k} {v['median_ms']:.0f}" if "error" not in v else f"{k} failed: {v['error']}"
            for k, v in report["cold_start"].items())]
    if "soak" in report:
        s = report["soak"]
        lines.append(f"Soak `{s['scene']}` {s['seconds']:.0f} s, {s['frames']} frames: RSS "
                     f"{s['rss_start_bytes'] / 2**20:.1f} → {s['rss_end_bytes'] / 2**20:.1f} MiB, "
                     f"slope {s['rss_slope_bytes_per_min'] / 2**10:.1f} KiB/min")
    gl = report.get("gl")
    if gl and "error" not in gl:
        lines += ["", f"GPU: {gl['renderer']} ({gl['gl_version']}), {gl['target_px']} px target, "
                  f"window hidden: {gl['window_hidden']}", "",
                  "| Scene | Render + read-back median / p95 ms | PNG encode ms | Export fps |",
                  "| --- | --- | ---: | ---: |"]
        for name, data in gl["scenes"].items():
            if "error" in data:
                lines.append(f"| {name} | {data['error']} | | |")
                continue
            r = data["render_readback"]
            lines.append(f"| {name} | {r['median_ms']:.2f} / {r['p95_ms']:.2f} | "
                         f"{data['png_encode']['median_ms']:.1f} | "
                         f"{data['export_frames_per_second']:.1f} |")
    elif gl:
        lines += ["", f"GPU: {gl['error']}"]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenes", nargs="+", default=list(SCENE_NAMES), choices=SCENE_NAMES)
    parser.add_argument("--repeat", type=int, default=5,
                        help="repetitions for open, save and cold start")
    parser.add_argument("--cold-repeat", type=int, default=5,
                        help="fresh-process start-up probes; 0 disables")
    parser.add_argument("--frames", type=int, default=300, help="CPU frames per scene")
    parser.add_argument("--soak", type=float, default=30.0, help="seconds; 0 disables")
    parser.add_argument("--soak-scene", default="imeru", choices=SCENE_NAMES)
    parser.add_argument("--gl", action="store_true", help="also measure native hidden GL")
    parser.add_argument("--gl-frames", type=int, default=120)
    parser.add_argument("--gl-size", type=int, default=1024)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if min(args.repeat, args.frames, args.gl_frames, args.gl_size) < 1 or args.cold_repeat < 0:
        parser.error("repeat, frames, gl-frames and gl-size must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    if not args.gl:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    report = run(args, [str(Path(__file__)), *argv])
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.output / "benchmark.md").write_text(markdown(report), encoding="utf-8")
    print(f"report: {args.output / 'benchmark.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
