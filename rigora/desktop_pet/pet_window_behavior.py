"""Runs a pet script's behavior rules on a :class:`PetWindow` (R5.3 / R5.4).

The window forwards its events (clicks, drops, hotkeys, beats, the 1 Hz
script tick) to :meth:`fire_behavior`; the engine decides which rule runs and
returns the actions, which this mixin performs. Delayed actions wait on
single-shot timers the window owns, so :meth:`stop_behaviors` (and window
shutdown) cancels anything still pending.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QTimer

from rigora.desktop_pet.pet_behavior import BehaviorEngine, Step

logger = logging.getLogger(__name__)
MAX_PENDING = 64


class PetWindowBehaviorMixin:
    def _init_behaviors(self) -> None:
        self._behavior_timers: list[QTimer] = []

    def behavior_engine(self) -> BehaviorEngine:
        return self._script_engine.behaviors

    def fire_behavior(self, event: str) -> list[Step]:
        engine = self._script_engine.behaviors
        if not engine.active:
            return []
        steps = engine.fire(event)
        if steps and getattr(self, "_pacer", None) is not None:
            self._pacer.note_activity()
        self._run_behavior_steps(steps)
        return steps

    def _behavior_tick(self) -> None:
        engine = self._script_engine.behaviors
        if engine.active:
            self._run_behavior_steps(engine.tick())

    def _run_behavior_steps(self, steps: list[Step]) -> None:
        for step in steps:
            if step.delay <= 0:
                self._perform_behavior_step(step)
                continue
            if len(self._behavior_timers) >= MAX_PENDING:
                logger.warning("pet behavior: too many delayed actions; dropping %s", step.kind)
                continue
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(int(step.delay * 1000))
            timer.timeout.connect(lambda s=step, t=timer: self._run_delayed_step(s, t))
            self._behavior_timers.append(timer)
            timer.start()

    def _run_delayed_step(self, step: Step, timer: QTimer) -> None:
        if timer in self._behavior_timers:
            self._behavior_timers.remove(timer)
        timer.deleteLater()
        if self._script_engine.behaviors.active:
            self._perform_behavior_step(step)

    def _perform_behavior_step(self, step: Step) -> None:
        if step.kind == "say":
            self._show_speech(str(step.value))
        elif step.kind == "motion":
            self._play_motion_by_name(str(step.value))
        elif step.kind == "motion_group":
            self.play_random_motion_in_group(str(step.value))
        elif step.kind == "expression" and \
                str(step.value) not in self._canvas.active_expressions():
            self._canvas.add_expression(str(step.value))
        # "state" and "emit" are handled inside the engine.

    def stop_behaviors(self) -> None:
        """Safe stop: halt the rules and cancel actions still waiting."""
        self._script_engine.behaviors.stop()
        for timer in self._behavior_timers:
            timer.stop()
            timer.deleteLater()
        self._behavior_timers.clear()

    def resume_behaviors(self) -> None:
        self._script_engine.behaviors.resume()

    def pending_behavior_actions(self) -> int:
        return len(self._behavior_timers)
