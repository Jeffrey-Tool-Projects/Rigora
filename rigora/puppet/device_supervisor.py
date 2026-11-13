"""Recovery policy for live capture devices (R4.3). Qt-free.

The supervisor watches one device's reported phase and decides what to do:

* ``running`` resets the retry count.
* ``device_lost`` / ``device_unavailable`` / ``failed`` while the user still
  wants the device: retry after 1, 2, 4, 8, 15 s, then give up and ask.
* ``permission_denied``, ``missing_dependency`` and ``model_unavailable``
  need the user (system settings, an install, a network) — no automatic
  retry; a manual retry resets the count.
* A jump between the wall clock and the monotonic clock larger than
  ``sleep_gap`` means the machine slept; a running device is restarted once.
* A device switch while capturing stops, waits until the old capture has
  released the device, then starts on the new one.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0, 15.0)
NEEDS_USER = frozenset({"permission_denied", "missing_dependency", "model_unavailable"})
RETRYABLE = frozenset({"device_lost", "device_unavailable", "failed"})

ACT_NONE = "none"
ACT_START = "start"
ACT_STOP = "stop"
ACT_SWITCH = "switch"


@dataclass
class SupervisorState:
    state: str = "idle"           # idle | running | waiting_retry | needs_user | gave_up
    attempts: int = 0
    next_retry_in: float | None = None
    reason: str = ""
    pending_device: int | None = None


class DeviceSupervisor:
    def __init__(self, *, delays=RETRY_DELAYS, sleep_gap: float = 5.0,
                 clock=time.monotonic, wall=time.time) -> None:
        self.delays = tuple(delays)
        self.sleep_gap = float(sleep_gap)
        self._clock, self._wall = clock, wall
        self.wanted = False
        self.attempts = 0
        self.retry_at: float | None = None
        self.state = "idle"
        self.reason = ""
        self.pending_device: int | None = None
        self._restart_requested = False
        self._offset = wall() - clock()

    # ---- user intent ---------------------------------------------------

    def request(self, on: bool) -> None:
        self.wanted = bool(on)
        self.attempts = 0
        self.retry_at = None
        self.state = "running" if on else "idle"
        self.reason = ""

    def retry_now(self) -> None:
        """A manual retry after the user fixed the cause."""
        self.request(True)
        self._restart_requested = True

    def switch_device(self, index: int) -> None:
        self.pending_device = int(index)

    # ---- observations ----------------------------------------------------

    def woke_from_sleep(self) -> bool:
        offset = self._wall() - self._clock()
        jumped = abs(offset - self._offset) > self.sleep_gap
        self._offset = offset
        return jumped

    def observe(self, phase: str, detail: str = "", now: float | None = None) -> None:
        now = self._clock() if now is None else now
        if not self.wanted:
            return
        if phase == "running":
            self.attempts, self.retry_at, self.state, self.reason = 0, None, "running", ""
        elif phase in NEEDS_USER:
            self.retry_at, self.state, self.reason = None, "needs_user", detail or phase
        elif phase in RETRYABLE and self.retry_at is None and self.state != "gave_up":
            if self.attempts >= len(self.delays):
                self.state, self.reason = "gave_up", detail or phase
                return
            self.retry_at = now + self.delays[self.attempts]
            self.attempts += 1
            self.state, self.reason = "waiting_retry", detail or phase

    def next_action(self, phase: str, can_configure: bool, now: float | None = None) -> str:
        """What the owner should do this tick, given the device's phase and
        whether its previous capture has released the device."""
        now = self._clock() if now is None else now
        if not self.wanted:
            return ACT_NONE
        if self.woke_from_sleep() and phase in ("running", "starting"):
            self._restart_requested = True
        if self.pending_device is not None or self._restart_requested:
            if phase in ("running", "starting"):
                return ACT_STOP
            if not can_configure:
                return ACT_NONE
            self._restart_requested = False
            return ACT_SWITCH if self.pending_device is not None else ACT_START
        if self.retry_at is not None and now >= self.retry_at and can_configure:
            self.retry_at = None
            return ACT_START
        return ACT_NONE

    def take_pending_device(self) -> int | None:
        device, self.pending_device = self.pending_device, None
        return device

    def snapshot(self, now: float | None = None) -> SupervisorState:
        now = self._clock() if now is None else now
        wait = None if self.retry_at is None else max(0.0, round(self.retry_at - now, 1))
        return SupervisorState(self.state if self.wanted else "idle", self.attempts, wait,
                               self.reason, self.pending_device)
