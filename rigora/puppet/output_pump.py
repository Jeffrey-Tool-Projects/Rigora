"""Bounded frame delivery and statistics for live outputs (R4.4). Qt-free.

The GUI thread renders a frame each tick and hands it to :class:`FramePump`
with :meth:`FramePump.offer`, which never blocks: the queue holds at most
``capacity`` frames and a new frame replaces the oldest unsent one (counted
as dropped). A worker thread sends frames to the receiver, so a slow or
stalled receiver costs dropped frames, never a frozen editor.

:class:`OutputStats` is what the output panel shows: the real source name,
resolution, target and measured frame rates, dropped frames, connection
state and the last error.
"""
from __future__ import annotations

import collections
import threading
import time
from dataclasses import asdict, dataclass


@dataclass
class OutputStats:
    kind: str
    source_name: str = ""
    width: int = 0
    height: int = 0
    target_fps: float = 0.0
    measured_fps: float = 0.0
    sent: int = 0
    dropped: int = 0
    send_errors: int = 0
    queue_depth: int = 0
    connected: bool = False
    receivers: int | None = None
    alpha: bool = False
    last_error: str = ""
    send_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class FramePump:
    def __init__(self, send, stats: OutputStats, *, capacity: int = 2,
                 max_errors: int = 5, clock=time.monotonic) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._send = send
        self.stats = stats
        self.capacity = capacity
        self.max_errors = max_errors
        self._clock = clock
        self._queue: collections.deque = collections.deque()
        self._cond = threading.Condition()
        self._stop = False
        self._failed = False
        self._consecutive_errors = 0
        self._last_sent: float | None = None
        self._thread = threading.Thread(target=self._run, name=f"{stats.kind}-pump",
                                        daemon=True)
        self._thread.start()
        stats.connected = True

    @property
    def failed(self) -> bool:
        """True after ``max_errors`` consecutive send failures; the owner should
        stop the output and show :attr:`OutputStats.last_error`."""
        return self._failed

    def offer(self, frame) -> bool:
        """Queue ``frame`` without blocking; returns ``False`` if it displaced an
        unsent frame (that frame is counted as dropped)."""
        with self._cond:
            if self._stop:
                return False
            displaced = len(self._queue) >= self.capacity
            if displaced:
                self._queue.popleft()
                self.stats.dropped += 1
            self._queue.append(frame)
            self.stats.queue_depth = len(self._queue)
            self._cond.notify()
        return not displaced

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._queue and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                frame = self._queue.popleft()
                self.stats.queue_depth = len(self._queue)
            started = self._clock()
            try:
                self._send(frame)
            except Exception as exc:   # noqa: BLE001 - receivers raise anything
                self.stats.send_errors += 1
                self.stats.last_error = str(exc) or type(exc).__name__
                self._consecutive_errors += 1
                if self._consecutive_errors >= self.max_errors:
                    self._failed = True
                    self.stats.connected = False
                continue
            finished = self._clock()
            self._consecutive_errors = 0
            self.stats.sent += 1
            self.stats.send_ms = round((finished - started) * 1000, 2)
            if self._last_sent is not None and finished > self._last_sent:
                fps = 1.0 / (finished - self._last_sent)
                self.stats.measured_fps = round(
                    fps if self.stats.measured_fps == 0 else
                    0.9 * self.stats.measured_fps + 0.1 * fps, 2)
            self._last_sent = finished

    def close(self, timeout: float = 2.0) -> bool:
        """Stop the worker, dropping queued frames; ``True`` once it exited."""
        with self._cond:
            self._stop = True
            self.stats.dropped += len(self._queue)
            self._queue.clear()
            self.stats.queue_depth = 0
            self._cond.notify_all()
        self._thread.join(timeout)
        self.stats.connected = False
        return not self._thread.is_alive()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()
