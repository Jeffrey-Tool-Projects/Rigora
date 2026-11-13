"""Who controls each parameter when several live inputs write at once (R4.2).

Every input source writes through :class:`InputArbiter`. Each parameter has
at most one *owner*: the source that last wrote it, as long as it keeps
writing within its hold time. A source with a higher priority takes a
parameter over at once; a lower one is ignored until the owner has been
quiet for ``hold`` seconds. That makes the outcome deterministic and lets the
user see, per parameter, which source is in control.

Expressions are not a writer: they are overlays applied on top of whatever
value the owner wrote, so the owner view lists them separately.

Default order, highest first::

    manual (a slider the user is dragging)  100
    external (VTS API plug-ins)              80
    motion (playing motions / takes)         70
    webcam (face tracking)                   50
    mic (lip-sync)                           40
    blink (auto-blink)                       30
    mouse (cursor / drag gaze)               20
    idle (idle sway and breathing)           10

Sources named ``kind:detail`` (``external:VTS plug-in``) use the priority of
their kind but own parameters separately, so two plug-ins cannot both drive
one parameter: the second is told the parameter is taken.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

DEFAULT_PRIORITIES: dict[str, int] = {
    "manual": 100, "external": 80, "motion": 70, "webcam": 50, "mic": 40,
    "blink": 30, "mouse": 20, "idle": 10,
}
DEFAULT_HOLD = 0.25
MANUAL_HOLD = 1.0
SOURCE_LABELS: dict[str, tuple[str, str]] = {
    "manual": ("puppet_input_source_manual", "Manual"),
    "external": ("puppet_input_source_external", "External plug-in"),
    "motion": ("puppet_input_source_motion", "Motion"),
    "webcam": ("puppet_input_source_webcam", "Webcam"),
    "mic": ("puppet_input_source_mic", "Microphone"),
    "blink": ("puppet_input_source_blink", "Auto-blink"),
    "mouse": ("puppet_input_source_mouse", "Mouse"),
    "idle": ("puppet_input_source_idle", "Idle"),
}


def source_kind(source: str) -> str:
    return source.split(":", 1)[0]


@dataclass
class Ownership:
    source: str
    last_write: float
    value: float


class InputArbiter:
    def __init__(self, priorities: dict[str, int] | None = None,
                 hold: float = DEFAULT_HOLD, clock=time.monotonic) -> None:
        self.priorities = dict(DEFAULT_PRIORITIES)
        self.priorities.update(priorities or {})
        self.hold = float(hold)
        self._clock = clock
        self._owners: dict[str, Ownership] = {}
        self.rejected: dict[str, int] = {}

    def priority(self, source: str) -> int:
        return self.priorities.get(source_kind(source), 0)

    def _hold_for(self, source: str) -> float:
        return MANUAL_HOLD if source_kind(source) == "manual" else self.hold

    def _can_write(self, source: str, param: str, now: float) -> bool:
        owner = self._owners.get(param)
        if owner is None or owner.source == source:
            return True
        if now - owner.last_write > self._hold_for(owner.source):
            return True
        return self.priority(source) > self.priority(owner.source)

    def submit(self, source: str, values: dict[str, float],
               now: float | None = None) -> dict[str, float]:
        """Record a write and return the values this source may apply."""
        now = self._clock() if now is None else now
        accepted: dict[str, float] = {}
        for param, value in values.items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(number):
                continue
            if self._can_write(source, param, now):
                self._owners[param] = Ownership(source, now, number)
                accepted[param] = number
            else:
                self.rejected[source] = self.rejected.get(source, 0) + 1
        return accepted

    def blocked(self, source: str, params, now: float | None = None) -> list[str]:
        """Parameters ``source`` may not write right now."""
        now = self._clock() if now is None else now
        return [p for p in params if not self._can_write(source, p, now)]

    def release(self, source: str) -> list[str]:
        """Give up everything ``source`` owns (it stopped or was disabled)."""
        freed = [p for p, o in self._owners.items() if o.source == source]
        for param in freed:
            del self._owners[param]
        return freed

    def release_kind(self, kind: str) -> list[str]:
        freed = [p for p, o in self._owners.items() if source_kind(o.source) == kind]
        for param in freed:
            del self._owners[param]
        return freed

    def clear(self) -> None:
        self._owners.clear()
        self.rejected.clear()

    def owners(self, now: float | None = None) -> dict[str, str]:
        """Parameter → the source in control (only owners still within hold)."""
        now = self._clock() if now is None else now
        return {p: o.source for p, o in self._owners.items()
                if now - o.last_write <= self._hold_for(o.source)}

    def owner_rows(self, parameter_ids, active_expressions=(), now: float | None = None):
        """Rows for an owner table: ``(param, owner or "", seconds since write,
        expression overlays)``."""
        now = self._clock() if now is None else now
        live = self.owners(now)
        rows = []
        for param in parameter_ids:
            owner = self._owners.get(param)
            age = None if owner is None else round(now - owner.last_write, 2)
            rows.append((param, live.get(param, ""), age, list(active_expressions)))
        return rows


def submit_values(canvas, source: str, values: dict[str, float], *, force: bool = False):
    """Write ``values`` for ``source`` through the canvas's arbiter; hosts without
    one (older embeddings, stand-ins) receive the plain write."""
    submit = getattr(type(canvas), "submit_input", None)
    if submit is not None:
        return canvas.submit_input(source, values, force=force)
    writer = getattr(canvas, "force_parameter_values" if force else "set_parameter_values", None)
    if writer is not None:
        writer(values)
    else:
        for param, value in values.items():
            canvas.set_parameter_value(param, value)
    return values


def release_source(canvas, source: str) -> None:
    release = getattr(type(canvas), "release_input", None)
    if release is not None:
        canvas.release_input(source)
