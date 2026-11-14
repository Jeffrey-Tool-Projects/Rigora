"""Motion sound playback for :class:`MotionPlayer`, kept on the motion's clock.

A ``QMediaPlayer`` is created lazily the first time a motion with a
``sound_path`` plays. Unlike ``QSoundEffect`` it can seek, so the sound
always starts at the playhead: after a pause, a scrub, a loop wrap or a
resume it plays the part that matches the picture. While sound plays its
position is the clock — when the wall-clock playhead drifts more than
:data:`DRIFT_TOLERANCE` from it, the playhead follows the audio (R3.4).
Missing files and a missing QtMultimedia never stop the visual timeline;
:meth:`sound_status` reports them.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

from PySide6.QtCore import QUrl

logger = logging.getLogger("rigora.puppet.motion_player")

DRIFT_TOLERANCE = 0.08
"""Seconds of disagreement between audio and playhead before re-anchoring."""

SOUND_NONE = "none"
SOUND_MISSING = "missing"
SOUND_UNAVAILABLE = "unavailable"
SOUND_OK = "ok"


class MotionPlayerSoundMixin:
    """Start, seek, pause and lazily create the motion's sound player."""

    def sound_status(self) -> str:
        """``none`` (no sound), ``missing`` (file gone), ``unavailable``
        (QtMultimedia missing) or ``ok``."""
        if self._motion is None or not self._motion.sound_path:
            return SOUND_NONE
        if not Path(self._motion.sound_path).is_file():
            return SOUND_MISSING
        try:
            import PySide6.QtMultimedia  # noqa: F401
        except ImportError:
            return SOUND_UNAVAILABLE
        return SOUND_OK

    def _sound_time(self, t_sec: float) -> float:
        """The audio position for motion time ``t_sec``: wrapped when looping."""
        duration = self.duration()
        if self._loop and duration > 0:
            return math.fmod(max(0.0, t_sec), duration)
        return max(0.0, t_sec)

    def _maybe_play_sound(self) -> None:
        """If the bound motion has a ``sound_path``, play it from the playhead.
        Failures (missing file, missing QtMultimedia, codec issues) are
        logged at debug level and never raised — the motion's visual
        timeline must keep running even when audio is unavailable."""
        if self._motion is None or not self._motion.sound_path:
            return
        path = Path(self._motion.sound_path)
        if not path.is_file():
            logger.debug("motion sound %s missing on disk", path)
            return
        media = self._ensure_sound_effect()
        if media is None:
            return
        if getattr(self, "_sound_source", None) != str(path):
            media.setSource(QUrl.fromLocalFile(str(path)))
            self._sound_source = str(path)
        media.setPosition(int(round(self._sound_time(self._elapsed) * 1000)))
        media.play()
        self._sound_cycle = self._loop_cycle(self._elapsed)

    def _seek_sound(self, t_sec: float) -> None:
        """Move playing sound to motion time ``t_sec`` (after a scrub or loop wrap)."""
        media = self._sound_effect
        if media is None or not self._is_playing or self._motion is None \
                or not self._motion.sound_path:
            return
        try:
            media.setPosition(int(round(self._sound_time(t_sec) * 1000)))
        except RuntimeError as exc:
            logger.debug("sound seek failed: %s", exc)
        self._sound_cycle = self._loop_cycle(t_sec)

    def _loop_cycle(self, t_sec: float) -> int:
        duration = self.duration()
        return int(t_sec // duration) if self._loop and duration > 0 else 0

    def _follow_sound_clock(self, elapsed: float, now: float) -> float:
        """The playhead to use this tick: re-sync the sound at a loop wrap and,
        while sound plays, follow its position when the two drift apart."""
        media = self._sound_effect
        if media is None or self._motion is None or not self._motion.sound_path:
            return elapsed
        cycle = self._loop_cycle(elapsed)
        if cycle != getattr(self, "_sound_cycle", cycle):
            self._seek_sound(elapsed)
            return elapsed
        try:
            playing = media.playbackState() == media.PlaybackState.PlayingState
            position = media.position() / 1000.0
        except (AttributeError, RuntimeError):
            return elapsed
        if not playing:
            return elapsed
        expected = self._sound_time(elapsed)
        if abs(position - expected) > DRIFT_TOLERANCE:
            elapsed += position - expected
            self._wall_anchor = now - elapsed
        return elapsed

    def _stop_sound(self) -> None:
        if self._sound_effect is None:
            return
        try:
            self._sound_effect.stop()
        except RuntimeError as exc:
            # The C++ side may already be deleted during teardown.
            logger.debug("sound stop failed: %s", exc)

    def _release_sound(self) -> None:
        """Stop and delete the sound player so its audio output is freed (R7.4)."""
        self._stop_sound()
        media, self._sound_effect = self._sound_effect, None
        self._sound_source = None
        if media is not None:
            try:
                media.deleteLater()
            except RuntimeError as exc:
                logger.debug("sound release failed: %s", exc)

    def _ensure_sound_effect(self):
        """Lazy-create the sound player. Returns ``None`` if
        ``PySide6.QtMultimedia`` isn't available — keeps the player
        usable in headless test environments without the audio module."""
        if self._sound_effect is not None:
            return self._sound_effect
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            logger.info("PySide6.QtMultimedia not available; motion audio disabled")
            return None
        media = QMediaPlayer(self)
        output = QAudioOutput(media)
        media.setAudioOutput(output)
        self._sound_effect = media
        return media
