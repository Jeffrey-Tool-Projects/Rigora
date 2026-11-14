"""Live input pumping into a :class:`PuppetCanvas`.

Owns the QTimers that drive auto-blink, the active drag-tracking
state, and (when ``sounddevice`` is installed) a microphone stream
feeding lip-sync. Each driver is independently toggleable; absent
optional deps degrade silently rather than blocking the rest.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from rigora.puppet.input_arbitration import release_source, submit_values
from rigora.puppet.input_drivers import (
    DEFAULT_EYE_PARAMS,
    DEFAULT_MOUTH_FORM_PARAM,
    DEFAULT_MOUTH_PARAM,
    audio_to_viseme,
    blink_curve_value,
    cursor_to_angle_params,
)

if TYPE_CHECKING:
    from rigora.puppet.canvas import PuppetCanvas

logger = logging.getLogger("rigora.puppet.input_engine")

_BLINK_TICK_HZ: int = 30
_AUDIO_BLOCK_SAMPLES: int = 1024
_AUDIO_SAMPLE_RATE: int = 22050


class InputEngine(QObject):
    """Holds the state for the three live-input sources."""

    state_changed = Signal()
    # Marshals a viseme computed on the audio thread onto the GUI thread. A
    # queued cross-thread signal is delivered on this object's (GUI) thread;
    # QTimer.singleShot would have scheduled on the loop-less audio thread and
    # never fired.
    _viseme_ready = Signal(dict)
    # The audio stream ended on its own (device unplugged / driver reset).
    _mic_finished = Signal()

    def __init__(self, canvas: PuppetCanvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self._viseme_ready.connect(self._apply_viseme)
        self._mic_finished.connect(self._on_mic_lost)
        self._mic_device: str = ""
        self._mic_phase: str = "stopped"
        self._mic_detail: str = ""
        self._calibrator = None
        self._closing_mic = False
        canvas.cursor_moved.connect(self.push_cursor)
        self._blink_enabled = False
        self._drag_enabled = False
        self._lipsync_enabled = False
        self._blink_anchor: float = time.monotonic()
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(int(1000 / _BLINK_TICK_HZ))
        # Default is repeating, but be explicit — a future PySide6
        # default change would silently break the periodic blink.
        self._blink_timer.setSingleShot(False)
        self._blink_timer.timeout.connect(self._on_blink_tick)
        self._mic_stream = None

    # ---- public ---------------------------------------------------------

    def set_drag_enabled(self, enabled: bool) -> None:
        self._drag_enabled = bool(enabled)
        if not enabled:
            self._reset_drag_params()
        self.state_changed.emit()

    def drag_enabled(self) -> bool:
        return self._drag_enabled

    def push_cursor(self, image_x: float, image_y: float) -> None:
        """Turn the head toward an image-space point (the canvas's
        ``cursor_moved``). No-op when drag tracking is off."""
        if not self._drag_enabled or self._canvas.document() is None:
            return
        size = self._canvas.document().size
        values = cursor_to_angle_params(image_x, image_y, size[0], size[1])
        submit_values(self._canvas, "mouse", values)

    def set_blink_enabled(self, enabled: bool) -> None:
        if enabled == self._blink_enabled:
            return
        self._blink_enabled = bool(enabled)
        if enabled:
            self._blink_anchor = time.monotonic()
            self._blink_timer.start()
        else:
            self._blink_timer.stop()
            self._reset_blink_params()
        self.state_changed.emit()

    def blink_enabled(self) -> bool:
        return self._blink_enabled

    def set_lipsync_enabled(self, enabled: bool) -> bool:
        """Returns ``True`` if the requested state was reached. Mic
        capture failure (no device / no sounddevice) sets back to
        ``False`` and reports failure to the caller."""
        if enabled == self._lipsync_enabled:
            return True
        if enabled:
            ok = self._start_mic()
            if not ok:
                self._lipsync_enabled = False
                self.state_changed.emit()
                return False
        else:
            self._stop_mic()
        self._lipsync_enabled = bool(enabled)
        self.state_changed.emit()
        return True

    def lipsync_enabled(self) -> bool:
        return self._lipsync_enabled

    def set_mic_device(self, name: str) -> bool:
        """Use the named input device (``""`` = system default). Restarts a
        running lip-sync stream on the new device."""
        self._mic_device = str(name or "")
        if not self._lipsync_enabled:
            return True
        self._stop_mic()
        ok = self._start_mic()
        if not ok:
            self._lipsync_enabled = False
            self.state_changed.emit()
        return ok

    def mic_device(self) -> str:
        return self._mic_device

    def mic_status(self) -> tuple[str, str]:
        """``(phase, detail)``: stopped, running, device_lost, device_unavailable
        or missing_dependency."""
        return self._mic_phase, self._mic_detail

    def set_calibrator(self, calibrator) -> None:
        self._calibrator = calibrator

    def shutdown(self) -> None:
        self._lipsync_enabled = False
        self._blink_enabled = False
        self._blink_timer.stop()
        self._stop_mic()

    # ---- blink ----------------------------------------------------------

    def _on_blink_tick(self) -> None:
        if not self._blink_enabled or self._canvas.document() is None:
            return
        elapsed = time.monotonic() - self._blink_anchor
        value = blink_curve_value(elapsed)
        # ``force_parameter_values`` bypasses the canvas's no-change
        # optimisation: when motion player / webcam tracker / face-
        # landmark mapper write the same eye-param value in between
        # blink ticks, the equality check would otherwise mask the
        # blink curve's downward sweep and the user only sees the
        # very first blink before everything looks frozen.
        submit_values(self._canvas, "blink", dict.fromkeys(DEFAULT_EYE_PARAMS, value),
                      force=True)

    def _reset_blink_params(self) -> None:
        if self._canvas.document() is None:
            return
        submit_values(self._canvas, "blink", dict.fromkeys(DEFAULT_EYE_PARAMS, 1.0))
        release_source(self._canvas, "blink")

    def _reset_drag_params(self) -> None:
        if self._canvas.document() is None:
            return
        submit_values(self._canvas, "mouse", {
            "ParamAngleX": 0.0,
            "ParamAngleY": 0.0,
            "ParamEyeBallX": 0.0,
            "ParamEyeBallY": 0.0,
        })
        release_source(self._canvas, "mouse")

    # ---- microphone -----------------------------------------------------

    def _start_mic(self) -> bool:
        try:
            import sounddevice as sd
        except ImportError as exc:
            logger.info("sounddevice not installed; lip-sync unavailable")
            self._mic_phase, self._mic_detail = "missing_dependency", str(exc)
            return False
        self._closing_mic = False
        try:
            self._mic_stream = sd.InputStream(
                samplerate=_AUDIO_SAMPLE_RATE, channels=1,
                blocksize=_AUDIO_BLOCK_SAMPLES, dtype="float32",
                device=self._mic_device or None,
                callback=self._on_audio_block,
                finished_callback=self._on_stream_finished,
            )
            self._mic_stream.start()
        except Exception as exc:   # noqa: BLE001 - sounddevice raises a zoo of types
            logger.warning("mic stream failed: %s", exc)
            self._mic_stream = None
            self._mic_phase, self._mic_detail = "device_unavailable", str(exc)
            return False
        self._mic_phase, self._mic_detail = "running", ""
        return True

    def _on_stream_finished(self) -> None:
        """Runs on the audio thread when the stream ends; only an unexpected
        end (not our own stop) counts as a lost device."""
        if not self._closing_mic:
            self._mic_finished.emit()

    def _on_mic_lost(self) -> None:
        if self._mic_stream is None or self._closing_mic:
            return
        logger.warning("microphone stream ended unexpectedly")
        self._stop_mic()
        self._mic_phase, self._mic_detail = "device_lost", "the input stream ended"
        self.state_changed.emit()

    def restart_mic(self) -> bool:
        """Retry after a lost device; keeps lip-sync on when it succeeds."""
        if not self._lipsync_enabled:
            return False
        self._stop_mic()
        return self._start_mic()

    def _stop_mic(self) -> None:
        stream = self._mic_stream
        self._mic_stream = None
        self._mic_phase = "stopped" if self._mic_phase == "running" else self._mic_phase
        if stream is None:
            return
        self._closing_mic = True
        try:
            stream.stop()
            stream.close()
        except Exception as exc:   # noqa: BLE001 - same; never want to crash teardown
            logger.warning("mic stream close failed: %s", exc)
        if self._calibrator is not None:
            self._calibrator.reset()
        if self._canvas.document() is not None:
            submit_values(self._canvas, "mic", {
                DEFAULT_MOUTH_PARAM: 0.0,
                DEFAULT_MOUTH_FORM_PARAM: 0.0,
            })
            release_source(self._canvas, "mic")

    def _on_audio_block(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if status:
            logger.debug("mic status %s", status)
        if not self._lipsync_enabled:
            return
        viseme = audio_to_viseme(indata, sample_rate=_AUDIO_SAMPLE_RATE)
        # Marshal onto the GUI thread. Qt slots aren't safe to call from
        # sounddevice's callback thread, and QTimer.singleShot here would post to
        # that loop-less thread and never run; a queued signal is delivered on
        # the GUI thread instead.
        self._viseme_ready.emit(viseme)

    def _apply_viseme(self, viseme: dict[str, float]) -> None:
        if not self._lipsync_enabled or self._canvas.document() is None:
            return
        values = {
            DEFAULT_MOUTH_PARAM: float(viseme.get(DEFAULT_MOUTH_PARAM, 0.0)),
            DEFAULT_MOUTH_FORM_PARAM: float(
                viseme.get(DEFAULT_MOUTH_FORM_PARAM, 0.0),
            ),
        }
        if self._calibrator is not None:
            values = self._calibrator.apply_mic(values, time.monotonic())
        submit_values(self._canvas, "mic", values)
