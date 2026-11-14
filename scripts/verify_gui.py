"""Verify native Windows GL without displaying a window or using desktop input.

Run against the installed wheel by default; --source checks this checkout.
Reports and actual framebuffer PNGs are kept in --output. The child process
has a deadline and uses temporary settings. Desktop overlays/tray are excluded.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def desktop_state() -> dict:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError()
    return {"foreground_hwnd": user32.GetForegroundWindow(), "cursor": [point.x, point.y]}


def verify(output: Path, *, workflows: bool = True) -> dict:
    import numpy as np
    import rigora
    from OpenGL.GL import GL_RENDERER, GL_VERSION, glGetString
    from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from rigora.desktop_pet import PetTrayIcon
    from rigora.editor_window import EditorWindow
    from rigora.puppet.document import Motion, MotionSegment, MotionTrack
    from rigora.system import settings
    from rigora.system.app_paths import examples_dir

    settings.configure()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    report = {"package": str(Path(rigora.__file__).resolve()), "platform": app.platformName()}
    before = desktop_state()
    window = EditorWindow()
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
    # Qt needs its show lifecycle to allocate a native GL surface. The above
    # DontShowOnScreen attribute prevents mapping that surface to the desktop.
    window.show()
    canvas = window.editor.canvas()
    hwnd = int(window.winId())
    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    native_hidden = not bool(user32.IsWindowVisible(hwnd))
    try:
        deadline = time.monotonic() + 10
        while canvas.context() is None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        require(canvas.context() is not None and canvas.context().isValid(), "No native GL context")
        require(native_hidden, "Verification window became desktop-visible")
        canvas.makeCurrent()
        report["gl"] = {
            "renderer": glGetString(GL_RENDERER).decode(),
            "version": glGetString(GL_VERSION).decode(),
        }
        canvas.doneCurrent()
        require(
            window.editor.open_puppet(str(examples_dir() / "puppet" / "imeru.puppet")),
            "Packaged Imeru could not be opened",
        )
        doc = canvas.document()
        report["drawables"] = len(doc.drawables)
        require(report["drawables"] == 23, 'Verification failed: report["drawables"] == 23')

        def frame(name):
            image = canvas.render_offscreen_puppet(512, 512)
            require(image is not None and not image.isNull(), "Empty GL export")
            rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
            pixels = (
                np.frombuffer(rgba.constBits(), dtype=np.uint8)
                .reshape(512, rgba.bytesPerLine())[:, :2048]
                .reshape(512, 512, 4)
            )
            alpha = pixels[:, :, 3]
            opaque = int(np.count_nonzero(alpha))
            require(1000 < opaque < 512 * 512, f"Missing character/transparency: {opaque}")
            require(
                len(np.unique(pixels[alpha > 0, :3], axis=0)) > 50,
                "Framebuffer lacks textured character",
            )
            require(
                image.save(str(output / f"{name}.png")),
                'Verification failed: image.save(str(output / f"{name}.png"))',
            )
            return {
                "sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
                "nontransparent_pixels": opaque,
            }

        report["neutral"] = frame("imeru-neutral")
        parameter = next(p for p in doc.parameters if p.id == "ParamAngleX")
        player = window.editor._motion_dock.player()
        player.set_motion(
            Motion(
                "verification",
                1.0,
                tracks=[
                    MotionTrack(
                        parameter.id,
                        [MotionSegment("linear", (0.0, parameter.default), (1.0, parameter.max))],
                    )
                ],
            )
        )
        player.play()
        require(player.is_playing(), "Verification failed: player.is_playing()")
        player.seek(0.75)
        require(
            abs(
                canvas.parameter_values()[parameter.id]
                - (parameter.default + 0.75 * (parameter.max - parameter.default))
            )
            < 1e-5,
            "Motion parameter did not reach its expected interpolated value",
        )
        player.pause()
        report["animated"] = frame("imeru-animated")
        require(
            report["animated"]["sha256"] != report["neutral"]["sha256"],
            "Motion did not change rendered pixels",
        )
        canvas.reset_parameters()
        saved = Path(os.environ["RIGORA_DATA_DIR"]) / "roundtrip.puppet"
        require(
            window.editor.save_puppet(str(saved)),
            "Verification failed: window.editor.save_puppet(str(saved))",
        )
        require(
            window.editor.open_puppet(str(saved)),
            "Verification failed: window.editor.open_puppet(str(saved))",
        )
        require(
            len(canvas.document().drawables) == 23,
            "Verification failed: len(canvas.document().drawables) == 23",
        )
        report["roundtrip"] = frame("imeru-roundtrip")
        require(
            report["roundtrip"]["sha256"] == report["neutral"]["sha256"],
            "Save/reopen changed neutral frame",
        )
        from verify_editor_session import check_editor_session
        report["editor_session"] = check_editor_session(window, saved.parent)
        if workflows:
            from verify_asset_workflow import check_asset_workflow
            report["asset_workflow"] = check_asset_workflow(window, saved.parent)
            from verify_rig_workflow import check_rig_workflow
            report["rig_workflow"] = check_rig_workflow(window, saved.parent)
            from verify_animation_workflow import check_animation_workflow
            report["animation_workflow"] = check_animation_workflow(window, saved.parent)
            from verify_live_workflow import check_live_workflow
            report["live_workflow"] = check_live_workflow(window, saved.parent)
        require(window._pet is None, "Verification failed: window._pet is None")
        # Only the OS tray is suppressed; PetWorkspace itself is real.
        available = PetTrayIcon.is_available
        PetTrayIcon.is_available = staticmethod(lambda: False)
        try:
            window.tabs.setCurrentIndex(1)
        finally:
            PetTrayIcon.is_available = staticmethod(available)
        require(
            window._pet is not None and window._pet.pet_window() is None,
            "Verification failed: window._pet is not None and window._pet.pet_window() is None",
        )
        report["pet_control_page"] = True
        if workflows:
            from verify_pet_workflow import check_pet_workflow
            report["pet_workflow"] = check_pet_workflow(window, saved.parent)
        window.shutdown()
        window.shutdown()
        window.close()
        app.processEvents()
        active = [
            type(timer.parent()).__name__
            for timer in window.findChildren(QTimer)
            if timer.isActive()
        ]
        report["active_timers_after_close"] = active
        require(not active, f"Timers survived shutdown: {active}")
        report["shutdown"] = True
    finally:
        window.shutdown()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        settings.flush()
        after = desktop_state()
        report["desktop_observation"] = {
            "before": before,
            "after": after,
            "unchanged": before == after,
            "window_was_native_hidden": native_hidden,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["excluded"] = [
        "visible desktop overlay",
        "system tray",
        "camera",
        "microphone",
        "network outputs",
    ]
    report["status"] = "passed"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".audit/native-gui"))
    parser.add_argument("--source", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-workflows", action="store_true",
                        help="only render, round-trip and shut down (no R2-R5 workflow checks)")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        parser.error("This background native-GL verifier requires Windows")
    if not args.worker:
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--output",
            str(output),
        ]
        if args.source:
            command.append("--source")
        if args.skip_workflows:
            command.append("--skip-workflows")
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=420,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            print("Native GUI verification exceeded 420 seconds", file=sys.stderr)
            return 1
        (output / "process.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        return result.returncode
    if args.source:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    (output / "report.json").unlink(missing_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    with tempfile.TemporaryDirectory(prefix="rigora-gui-") as temporary:
        os.environ["RIGORA_DATA_DIR"] = temporary
        os.environ["RIGORA_SETTINGS_PATH"] = str(Path(temporary) / "settings.json")
        try:
            report = verify(output, workflows=not args.skip_workflows)
        except Exception:  # noqa: BLE001 - serialize any verification failure, then exit nonzero
            report_file = output / "report.json"
            report = (
                json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else {}
            )
            report.update(status="failed", traceback=traceback.format_exc())
        encoded = json.dumps(report, indent=2)
        (output / "report.json").write_text(encoded, encoding="utf-8")
        print(encoded)
        return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
