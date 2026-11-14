"""Hidden-canvas renderer for offline exports (R3.6).

Each export job renders its own document snapshot in a canvas that is never
shown on the desktop and whose physics clock is off: the job supplies every
parameter value, physics outputs included, for each frame. Frames come back
as straight-alpha RGBA arrays.
"""
from __future__ import annotations

import time

import numpy as np

from rigora.puppet.document import PuppetDocument


class CanvasRenderer:
    def __init__(self, document: PuppetDocument, width: int, height: int,
                 background: tuple[float, float, float, float]) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        from rigora.puppet.canvas import PuppetCanvas
        self.width, self.height, self.background = width, height, tuple(background)
        self._app = QApplication.instance()
        canvas = PuppetCanvas()
        canvas.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        canvas.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        canvas.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
        canvas.resize(64, 64)
        canvas.set_external_physics(True)
        canvas.show()
        deadline = time.monotonic() + 10
        while (canvas.context() is None or not canvas.context().isValid()) \
                and time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.01)
        if canvas.context() is None or not canvas.context().isValid():
            canvas.close()
            canvas.deleteLater()
            raise RuntimeError("no OpenGL context for offline rendering")
        canvas.load_document(document)
        canvas.set_external_physics(True)
        self.canvas = canvas

    def __call__(self, values: dict[str, float]) -> np.ndarray:
        from PySide6.QtGui import QImage
        self.canvas.force_parameter_values(values)
        image = self.canvas.render_offscreen_puppet(self.width, self.height,
                                                    background_rgba=self.background)
        if image is None or image.isNull():
            raise RuntimeError("offline frame could not be rendered")
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        data = np.frombuffer(rgba.constBits(), dtype=np.uint8)
        rows = data.reshape(self.height, rgba.bytesPerLine())
        return rows[:, :self.width * 4].reshape(self.height, self.width, 4).copy()

    def close(self) -> None:
        canvas, self.canvas = getattr(self, "canvas", None), None
        if canvas is not None:
            canvas.load_document(None)
            canvas.close()
            canvas.deleteLater()


def canvas_renderer_factory(job):
    return CanvasRenderer(job.source.document, job.settings.width, job.settings.height,
                          job.settings.background)
