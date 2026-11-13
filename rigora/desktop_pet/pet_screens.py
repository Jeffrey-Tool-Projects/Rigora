"""Keep desktop characters on a usable screen (R5.2).

:func:`recover` decides, from plain geometry, where a character should be
after the screen layout changed: a monitor unplugged, a resolution or DPI
change, the taskbar moved, or the machine woke from sleep. A character that
is still mostly on a screen's work area stays (pulled fully inside it); one
that lost its screen goes to the same relative spot on the screen it was
saved on, or the primary screen when that one is gone.

Positions are also stored relative to the work area (0..1), so a resolution
or scaling change keeps the character in the same corner instead of
pushing it off-screen.

:class:`ScreenWatcher` connects Qt's screen signals and a sleep check to a
callback; it never moves windows itself.
"""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass

from rigora.desktop_pet.edge_snap import Rect, ScreenInfo

KEEP_VISIBLE_SHARE = 0.5          # at least half the character must stay on a work area
DEFAULT_RELATIVE = (1.0, 1.0)     # bottom-right corner
MARGIN = 16


@dataclass(frozen=True)
class Placement:
    screen: str
    x: int
    y: int
    reason: str          # "kept" | "clamped" | "moved" | "default"


def _overlap(a: Rect, b: Rect) -> int:
    width = min(a.right, b.right) - max(a.x, b.x)
    height = min(a.bottom, b.bottom) - max(a.y, b.y)
    return max(0, width) * max(0, height)


def relative_position(rect: Rect, screen: ScreenInfo) -> tuple[float, float]:
    """Where ``rect`` sits inside the work area, as 0..1 per axis."""
    area = screen.available
    free_w, free_h = max(1, area.w - rect.w), max(1, area.h - rect.h)
    return (min(1.0, max(0.0, (rect.x - area.x) / free_w)),
            min(1.0, max(0.0, (rect.y - area.y) / free_h)))


def from_relative(relative: tuple[float, float], width: int, height: int,
                  screen: ScreenInfo) -> tuple[int, int]:
    area = screen.available
    fx, fy = (min(1.0, max(0.0, float(v))) for v in relative)
    free_w, free_h = max(0, area.w - width), max(0, area.h - height)
    return area.x + round(fx * free_w), area.y + round(fy * free_h)


def _clamp(rect: Rect, screen: ScreenInfo) -> tuple[int, int]:
    area = screen.available
    x = min(max(rect.x, area.x), max(area.x, area.right - rect.w))
    y = min(max(rect.y, area.y), max(area.y, area.bottom - rect.h))
    return x, y


def recover(rect: Rect, screens: list[ScreenInfo], *, saved_screen: str = "",
            relative: tuple[float, float] | None = None) -> Placement | None:
    """Where a character with geometry ``rect`` belongs on ``screens`` (the
    primary first). ``None`` when there is no screen at all."""
    if not screens:
        return None
    best = max(screens, key=lambda s: _overlap(rect, s.available))
    visible = _overlap(rect, best.available)
    if visible >= KEEP_VISIBLE_SHARE * max(1, rect.w * rect.h):
        x, y = _clamp(rect, best)
        return Placement(best.name, x, y, "kept" if (x, y) == (rect.x, rect.y) else "clamped")
    target = next((s for s in screens if s.name == saved_screen), screens[0])
    if relative is None:
        relative = DEFAULT_RELATIVE
        reason = "default"
    else:
        reason = "moved"
    x, y = from_relative(relative, rect.w, rect.h, target)
    if reason == "default":
        x = min(x, target.available.right - rect.w - MARGIN)
        y = min(y, target.available.bottom - rect.h - MARGIN)
        x, y = max(target.available.x, x), max(target.available.y, y)
    return Placement(target.name, x, y, reason)


class SleepCheck:
    """True once after the wall clock jumped ahead of the monotonic clock."""

    def __init__(self, gap: float = 5.0, clock=time.monotonic, wall=time.time) -> None:
        self.gap, self._clock, self._wall = gap, clock, wall
        self._offset = wall() - clock()

    def woke(self) -> bool:
        offset = self._wall() - self._clock()
        jumped = abs(offset - self._offset) > self.gap
        self._offset = offset
        return jumped


class ScreenWatcher:
    """Calls ``on_change(reason)`` when screens are added or removed, a work
    area or DPI changes, or the machine wakes."""

    def __init__(self, on_change, *, poll_ms: int = 5000) -> None:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QGuiApplication
        self._on_change = on_change
        self._app = QGuiApplication.instance()
        self._sleep = SleepCheck()
        self._connected = []
        if self._app is not None:
            self._app.screenAdded.connect(self._screen_added)
            self._app.screenRemoved.connect(self._screen_removed)
            for screen in QGuiApplication.screens():
                self._watch(screen)
        self._timer = QTimer()
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def _watch(self, screen) -> None:
        screen.availableGeometryChanged.connect(self._geometry_changed)
        screen.logicalDotsPerInchChanged.connect(self._dpi_changed)
        self._connected.append(screen)

    def _screen_added(self, screen) -> None:
        self._watch(screen)
        self._on_change("screen_added")

    def _screen_removed(self, screen) -> None:
        if screen in self._connected:
            self._connected.remove(screen)
        self._on_change("screen_removed")

    def _geometry_changed(self, *_args) -> None:
        self._on_change("work_area_changed")

    def _dpi_changed(self, *_args) -> None:
        self._on_change("dpi_changed")

    def _poll(self) -> None:
        if self._sleep.woke():
            self._on_change("woke")

    def stop(self) -> None:
        self._timer.stop()
        if self._app is not None:
            for signal, slot in ((self._app.screenAdded, self._screen_added),
                                 (self._app.screenRemoved, self._screen_removed)):
                with contextlib.suppress(RuntimeError, TypeError):
                    signal.disconnect(slot)
        for screen in self._connected:
            for signal, slot in ((screen.availableGeometryChanged, self._geometry_changed),
                                 (screen.logicalDotsPerInchChanged, self._dpi_changed)):
                with contextlib.suppress(RuntimeError, TypeError):
                    signal.disconnect(slot)
        self._connected.clear()
