"""Verify the frozen runtime without displaying a desktop window."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import traceback


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify(report_path: Path, *, native: bool) -> dict:
    import imageio.v2 as imageio
    import imageio_ffmpeg
    import numpy as np
    from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
    from PySide6.QtWidgets import QApplication

    from rigora.editor_window import EditorWindow
    from rigora.puppet.format_schema import check_puppet_file
    from rigora.puppet.runtime import compose_all_drawables, default_parameter_values
    from rigora.system import settings
    from rigora.system.app_paths import examples_dir, is_frozen

    settings.configure()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = EditorWindow()
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
    report = {
        "frozen": is_frozen(), "compiler": "Nuitka" if "__compiled__" in globals() else None,
        "platform": app.platformName(),
    }
    try:
        schemas = examples_dir().parent / "schemas"
        for name in ("puppet", "motion", "expression", "physics"):
            schema = json.loads((schemas / f"{name}.schema.json").read_text(encoding="utf-8"))
            require(schema.get("type") == "object", f"Invalid bundled {name} schema")
        report["schemas"] = 4
        example = examples_dir() / "puppet" / "imeru.puppet"
        checked = check_puppet_file(example)
        require(checked["valid"] and not checked["issues"], "Bundled Imeru failed validation")
        require(window.editor.open_puppet(str(example)), "Editor could not load bundled Imeru")
        canvas = window.editor.canvas()
        document = canvas.document()
        require(len(document.drawables) == 23 and bool(document.motions), "Incomplete bundled rig")
        values = default_parameter_values(document)
        rest = compose_all_drawables(document, values)
        moved = compose_all_drawables(document, {**values, "ParamAngleX": 30.0})
        require(all(np.isfinite(vertices).all() for vertices in rest.values()), "Invalid geometry")
        require(any(not np.array_equal(rest[key], moved[key]) for key in rest), "Pose did not move")
        report.update(drawables=len(document.drawables), textures=len(document.textures), pose=True)
        ffmpeg = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-version"], capture_output=True,
            timeout=15, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        require(b"ffmpeg version" in ffmpeg.stdout, "Bundled video encoder unavailable")
        report["ffmpeg"] = True
        with tempfile.TemporaryDirectory(prefix="rigora-video-") as temporary:
            video = Path(temporary) / "smoke.mp4"
            with imageio.get_writer(video, format="FFMPEG", fps=2) as writer:
                writer.append_data(np.zeros((32, 32, 3), dtype=np.uint8))
                writer.append_data(np.full((32, 32, 3), 255, dtype=np.uint8))
            reader = imageio.get_reader(video, format="FFMPEG")
            try:
                require(reader.get_data(0).shape == (32, 32, 3), "Video round trip failed")
            finally:
                reader.close()
        report["video_export"] = True
        if native:
            report["native"] = native_frame(window, app, report_path)
        else:
            require(not window.isVisible(), "Offscreen smoke unexpectedly showed the editor")
            report["native_rendering"] = "not tested"
    finally:
        window.shutdown()
        window.close()
        app.processEvents()
        active = [timer.interval() for timer in window.findChildren(QTimer) if timer.isActive()]
        require(not active, f"Timers survived shutdown: {active}")
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        settings.flush()
    report["shutdown"] = True
    return report


def native_frame(window, app, report_path: Path) -> dict:
    import ctypes

    from PySide6.QtGui import QImage

    window.show()
    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    require(not user32.IsWindowVisible(int(window.winId())), "Native window became visible")
    canvas = window.editor.canvas()
    deadline = time.monotonic() + 10
    while canvas.context() is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    require(canvas.context() is not None and canvas.context().isValid(), "Native GL unavailable")
    image = canvas.render_offscreen_puppet(512, 512)
    require(image is not None and not image.isNull(), "Empty native frame")
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    alpha = bytes(rgba.constBits())[3::4]
    require(any(alpha) and not all(alpha), "Missing character or transparency")
    require(image.save(str(report_path.with_suffix(".png"))), "Could not save native frame")
    return {"hidden": True, "gl_valid": True, "frame": report_path.with_suffix(".png").name}


def run(report_path: Path, *, native: bool = False) -> int:
    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "windows" if native else "offscreen"
    with tempfile.TemporaryDirectory(prefix="rigora-bundle-") as temporary:
        os.environ["RIGORA_DATA_DIR"] = temporary
        os.environ["RIGORA_SETTINGS_PATH"] = str(Path(temporary) / "settings.json")
        try:
            report = verify(report_path, native=native)
            report["status"] = "passed"
        except Exception:  # noqa: BLE001 - process verification writes every failure to its report
            report = {"status": "failed", "traceback": traceback.format_exc()}
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1
