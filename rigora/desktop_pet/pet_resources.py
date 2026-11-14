"""Frame pacing, a shared rig cache and per-character resource figures (R5.6).

* :class:`FramePacer` — a character repaints at 30 fps while something
  happens (a motion plays, the user clicks or drags it, it speaks) and drops
  to 15 fps after :data:`IDLE_AFTER` quiet seconds, where only idle breathing
  moves. A hidden character does not repaint at all.
* :class:`RigCache` — several characters showing the same ``.puppet`` file
  parse it once. Each gets its own document (so one can change outfit
  without touching the others), but the texture bytes inside are shared.
* :func:`resource_stats` — what one character costs: textures, GL objects,
  timers that are running, frame interval.
"""
from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from pathlib import Path

ACTIVE_INTERVAL_MS = 33
IDLE_INTERVAL_MS = 66
IDLE_AFTER = 10.0
CACHE_SIZE = 4


class FramePacer:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self.last_activity = clock()

    def note_activity(self) -> None:
        self.last_activity = self._clock()

    def interval(self, *, visible: bool, busy: bool) -> int | None:
        """Repaint interval in ms, or ``None`` when the character is hidden."""
        if not visible:
            return None
        if busy:
            self.last_activity = self._clock()
            return ACTIVE_INTERVAL_MS
        idle = self._clock() - self.last_activity >= IDLE_AFTER
        return IDLE_INTERVAL_MS if idle else ACTIVE_INTERVAL_MS


class RigCache:
    """Parsed rigs keyed by file identity (path, size, modification time)."""

    def __init__(self, size: int = CACHE_SIZE, loader=None) -> None:
        self.size = size
        self._loader = loader
        self._entries: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    @staticmethod
    def _key(path: Path):
        stat = path.stat()
        return str(path.resolve()), stat.st_size, stat.st_mtime_ns

    def load(self, path):
        """A private copy of the rig at ``path``; texture bytes are shared with
        every other copy of the same file (they are immutable)."""
        path = Path(path)
        key = self._key(path)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                self.hits += 1
                return copy.deepcopy(cached)
        loader = self._loader
        if loader is None:
            from rigora.puppet.document_io import load_puppet as loader
        document = loader(path)
        with self._lock:
            self.misses += 1
            self._entries[key] = document
            self._entries.move_to_end(key)
            while len(self._entries) > self.size:
                self._entries.popitem(last=False)
        return copy.deepcopy(document)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


shared_rigs = RigCache()


def texture_bytes(document) -> int:
    if document is None:
        return 0
    return sum(len(data) for data in getattr(document, "textures", {}).values()
               if isinstance(data, bytes | bytearray))


def resource_stats(window) -> dict:
    """What one character currently holds."""
    from PySide6.QtCore import QTimer
    document = window.document()
    canvas = window.canvas()
    counts = canvas.gl_resource_counts() if hasattr(canvas, "gl_resource_counts") else {}
    timers = [t for t in window.findChildren(QTimer) if t.isActive()]
    tick = getattr(window, "_tick", None)
    return {
        "pet_id": getattr(window, "_pet_id", ""),
        "visible": window.isVisible(),
        "drawables": len(document.drawables) if document is not None else 0,
        "texture_bytes": texture_bytes(document),
        "gl_textures": counts.get("textures", 0),
        "gl_buffers": counts.get("buffers", 0),
        "active_timers": len(timers),
        "frame_interval_ms": tick.interval() if tick is not None and tick.isActive() else None,
        "pending_behavior_actions": window.pending_behavior_actions()
        if hasattr(window, "pending_behavior_actions") else 0,
    }
