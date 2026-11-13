"""Event → condition → action rules for a desktop character (R5.3 / R5.4). Qt-free.

A script's optional ``behaviors`` section::

    {"initial": "idle",
     "states": ["idle", "happy"],
     "rules": [
       {"id": "pat", "on": "click:head", "when": {"state": "idle"},
        "do": [{"say": "Hehe"}, {"motion": "Nod"}, {"state": "happy"}],
        "cooldown": 5, "priority": 10},
       {"id": "calm", "on": "state:happy",
        "do": [{"wait": 8}, {"state": "idle"}]}]}

Events: ``start``, ``click:<hit area>`` (``click:*`` for any), ``drop:puppet``,
``drop:file``, ``hotkey:<action>``, ``beat``, ``every:<seconds>``,
``at:<HH:MM>``, ``idle:<seconds>``, ``state:<name>`` (entering a state) and
any name a rule ``emit``s. Conditions (all must hold): ``state``, ``hours``
``[start, end]``, ``weekdays`` (0 = Monday), ``chance`` 0..1.
Actions: ``say``, ``motion``, ``motion_group``, ``expression``, ``state``,
``emit``, ``wait`` (seconds, at most 600).

Safety: for one event only the highest-priority eligible rule runs; each rule
has a cooldown and may run at most ``max_per_minute`` times a minute; events a
rule emits nest at most :data:`MAX_DEPTH` deep and one external event runs at
most :data:`MAX_STEPS` actions, so a rule that triggers itself stops instead of
looping. :meth:`BehaviorEngine.stop` halts everything, including actions still
waiting.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

MAX_RULES = 200
MAX_ACTIONS_PER_RULE = 20
MAX_DEPTH = 4
MAX_STEPS = 32
MAX_WAIT = 600.0
DEFAULT_MAX_PER_MINUTE = 30
ACTIONS = ("say", "motion", "motion_group", "expression", "state", "emit", "wait")
_EVENT = re.compile(r"^(start|beat|drop:(puppet|file)|click:[^\s]+|hotkey:[^\s]+|"
                    r"every:\d+(\.\d+)?|at:([01]\d|2[0-3]):[0-5]\d|idle:\d+(\.\d+)?|"
                    r"state:[^\s]+|[a-z][a-z0-9_.-]{0,40})$")


@dataclass(frozen=True)
class Problem:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def validate(behaviors, *, motions=None, groups=None, expressions=None,
             hit_areas=None) -> list[Problem]:
    """Every problem with its location (``rules[2].do[0]``). Names of motions,
    expressions and hit areas are checked when the rig's lists are given."""
    problems: list[Problem] = []
    if behaviors is None:
        return problems
    if not isinstance(behaviors, dict):
        return [Problem("behaviors", "must be an object")]
    states = behaviors.get("states", [])
    if not isinstance(states, list) or not all(isinstance(s, str) and s for s in states):
        problems.append(Problem("states", "must be a list of names"))
        states = []
    initial = behaviors.get("initial", "idle")
    if states and initial not in states:
        problems.append(Problem("initial", f"{initial!r} is not one of the states"))
    rules = behaviors.get("rules", [])
    if not isinstance(rules, list):
        return problems + [Problem("rules", "must be a list")]
    if len(rules) > MAX_RULES:
        problems.append(Problem("rules", f"at most {MAX_RULES} rules"))
    seen: set = set()
    for index, rule in enumerate(rules):
        problems += _check_rule(rule, f"rules[{index}]", index, seen, states,
                                motions, groups, expressions, hit_areas)
    return problems


def _check_rule(rule, where, index, seen, states, motions, groups, expressions,
                hit_areas) -> list[Problem]:
    if not isinstance(rule, dict):
        return [Problem(where, "must be an object")]
    problems = []
    rule_id = rule.get("id", str(index))
    if rule_id in seen:
        problems.append(Problem(f"{where}.id", f"duplicate id {rule_id!r}"))
    seen.add(rule_id)
    problems += _check_event(rule.get("on"), f"{where}.on", states, hit_areas)
    problems += _check_when(rule.get("when", {}), f"{where}.when", states)
    for key, low, high in (("cooldown", 0, 86400), ("priority", -1000, 1000),
                           ("max_per_minute", 1, 600)):
        if key in rule and not (isinstance(rule[key], int | float)
                                and not isinstance(rule[key], bool)
                                and low <= rule[key] <= high):
            problems.append(Problem(f"{where}.{key}", f"must be a number {low}..{high}"))
    actions = rule.get("do", [])
    if not isinstance(actions, list) or not actions:
        return problems + [Problem(f"{where}.do", "needs at least one action")]
    if len(actions) > MAX_ACTIONS_PER_RULE:
        problems.append(Problem(f"{where}.do", f"at most {MAX_ACTIONS_PER_RULE} actions"))
    for a_index, action in enumerate(actions):
        problems += _check_action(action, f"{where}.do[{a_index}]", states, motions,
                                  groups, expressions)
    return problems


def _check_event(event, where, states, hit_areas) -> list[Problem]:
    if not isinstance(event, str) or not _EVENT.match(event):
        return [Problem(where, f"unknown event {event!r}")]
    named_click = event.startswith("click:") and event != "click:*"
    if named_click and hit_areas is not None and event[6:] not in hit_areas:
        return [Problem(where, f"the rig has no hit area {event[6:]!r}")]
    if event.startswith("state:") and states and event[6:] not in states:
        return [Problem(where, f"unknown state {event[6:]!r}")]
    return []


def _check_when(when, where: str, states) -> list[Problem]:
    if not isinstance(when, dict):
        return [Problem(where, "must be an object")]
    problems = []
    unknown = set(when) - {"state", "hours", "weekdays", "chance"}
    if unknown:
        problems.append(Problem(where, f"unknown condition {sorted(unknown)[0]!r}"))
    if "state" in when and (not isinstance(when["state"], str)
                            or (states and when["state"] not in states)):
        problems.append(Problem(f"{where}.state", f"unknown state {when['state']!r}"))
    hours = when.get("hours")
    if hours is not None and not (isinstance(hours, list) and len(hours) == 2 and all(
            isinstance(h, int) and 0 <= h <= 23 for h in hours)):
        problems.append(Problem(f"{where}.hours", "must be [start, end] hours 0..23"))
    days = when.get("weekdays")
    if days is not None and not (isinstance(days, list) and all(
            isinstance(d, int) and 0 <= d <= 6 for d in days)):
        problems.append(Problem(f"{where}.weekdays", "must list days 0..6"))
    chance = when.get("chance")
    if chance is not None and not (isinstance(chance, int | float) and 0 <= chance <= 1):
        problems.append(Problem(f"{where}.chance", "must be 0..1"))
    return problems


def _check_action(action, where, states, motions, groups, expressions) -> list[Problem]:
    if not isinstance(action, dict) or len(action) != 1:
        return [Problem(where, "must be one {action: value} pair")]
    (kind, value), = action.items()
    if kind not in ACTIONS:
        return [Problem(where, f"unknown action {kind!r}")]
    if kind == "wait":
        if not (isinstance(value, int | float) and 0 <= value <= MAX_WAIT):
            return [Problem(where, f"wait must be 0..{MAX_WAIT:g} seconds")]
        return []
    if not isinstance(value, str) or not value:
        return [Problem(where, f"{kind} needs a non-empty text")]
    known = {"motion": motions, "motion_group": groups, "expression": expressions,
             "state": states or None}.get(kind)
    if known is not None and value not in known:
        return [Problem(where, f"unknown {kind.replace('_', ' ')} {value!r}")]
    if kind == "emit" and not _EVENT.match(value):
        return [Problem(where, f"cannot emit {value!r}")]
    return []


@dataclass
class Step:
    """One action to perform ``delay`` seconds after the event."""
    kind: str
    value: object
    delay: float = 0.0
    rule: str = ""


@dataclass
class TraceEntry:
    time: float
    event: str
    rule: str | None
    outcome: str                 # "ran" | "skipped" | "blocked" | "no rule"
    detail: str = ""
    steps: list[Step] = field(default_factory=list)
    state: str = ""


class BehaviorEngine:
    def __init__(self, behaviors=None, *, clock=time.monotonic, now=datetime.now,
                 rng: random.Random | None = None) -> None:
        self._clock, self._now = clock, now
        self._rng = rng or random.Random()
        self.trace: list[TraceEntry] = []
        self.halted = False
        self.load(behaviors)

    def load(self, behaviors) -> None:
        behaviors = behaviors if isinstance(behaviors, dict) else {}
        problems = validate(behaviors)
        if problems:
            raise ValueError("; ".join(map(str, problems[:5])))
        self.rules = [r for r in behaviors.get("rules", []) if isinstance(r, dict)]
        self.state = behaviors.get("initial", "idle")
        self._last_run: dict[str, float] = {}
        self._runs: dict[str, list[float]] = {}
        self._every: dict[str, float] = {}
        self._fired_at: set[tuple[str, str]] = set()
        self._pending_states: list[tuple[float, str]] = []
        self._last_activity = self._clock()
        self.halted = False

    @property
    def active(self) -> bool:
        return bool(self.rules) and not self.halted

    def stop(self) -> None:
        """Safe stop: no further rules run until :meth:`resume`, and state
        changes still waiting are dropped."""
        self.halted = True
        self._pending_states.clear()

    def resume(self) -> None:
        self.halted = False
        self._last_activity = self._clock()

    # ---- running -------------------------------------------------------------

    def fire(self, event: str, *, now: float | None = None) -> list[Step]:
        """Handle one event and return the actions to perform, in order."""
        now = self._clock() if now is None else now
        if not event.startswith(("every:", "at:", "idle:")):
            self._last_activity = now
        due = self._apply_due_states(now)
        budget = [MAX_STEPS]
        return due + self._fire(event, now, 0, budget, 0.0)

    def _apply_due_states(self, now: float) -> list[Step]:
        """State changes that waited behind a ``wait`` and are now due."""
        steps: list[Step] = []
        while self._pending_states and self._pending_states[0][0] <= now and not self.halted:
            _due, value = self._pending_states.pop(0)
            if value != self.state:
                self.state = value
                steps += self._fire(f"state:{value}", now, 1, [MAX_STEPS], 0.0)
        return steps

    def _fire(self, event, now, depth, budget, offset) -> list[Step]:
        if self.halted:
            self._log(now, event, None, "blocked", "stopped")
            return []
        if depth >= MAX_DEPTH:
            self._log(now, event, None, "blocked", f"chain deeper than {MAX_DEPTH}")
            return []
        rule, reason = self._choose(event, now)
        if rule is None:
            self._log(now, event, None, "no rule" if not reason else "skipped", reason)
            return []
        rule_id = str(rule.get("id", self.rules.index(rule)))
        self._last_run[rule_id] = now
        self._runs.setdefault(rule_id, []).append(now)
        steps: list[Step] = []
        delay = offset
        entered = None
        for action in rule["do"]:
            if budget[0] <= 0:
                self._log(now, event, rule_id, "blocked", f"more than {MAX_STEPS} actions")
                break
            (kind, value), = action.items()
            budget[0] -= 1
            if kind == "wait":
                delay += float(value)
                continue
            steps.append(Step(kind, value, delay, rule_id))
            if kind == "state" and delay > offset:
                self._pending_states.append((now + delay, value))
                self._pending_states.sort()
            elif kind == "state" and value != self.state:
                self.state = value
                entered = value
            elif kind == "emit":
                steps += self._fire(value, now, depth + 1, budget, delay)
        self._log(now, event, rule_id, "ran", "", steps)
        if entered is not None:
            steps += self._fire(f"state:{entered}", now, depth + 1, budget, delay)
        return steps

    def _choose(self, event: str, now: float):
        candidates = [r for r in self.rules
                      if r.get("on") == event or (r.get("on") == "click:*"
                                                  and event.startswith("click:"))]
        if not candidates:
            return None, ""
        candidates.sort(key=lambda r: -float(r.get("priority", 0)))
        reasons = []
        for rule in candidates:
            ok, why = self._eligible(rule, now)
            if ok:
                return rule, ""
            reasons.append(f"{rule.get('id', '?')}: {why}")
        return None, "; ".join(reasons)

    def _eligible(self, rule: dict, now: float) -> tuple[bool, str]:
        rule_id = str(rule.get("id", self.rules.index(rule)))
        cooldown = float(rule.get("cooldown", 0))
        last = self._last_run.get(rule_id)
        if last is not None and now - last < cooldown:
            return False, f"cooldown {cooldown - (now - last):.1f}s left"
        window = [t for t in self._runs.get(rule_id, []) if now - t < 60]
        self._runs[rule_id] = window
        if len(window) >= int(rule.get("max_per_minute", DEFAULT_MAX_PER_MINUTE)):
            return False, "ran too often in the last minute"
        when = rule.get("when", {})
        if "state" in when and when["state"] != self.state:
            return False, f"state is {self.state!r}, needs {when['state']!r}"
        wall = self._now()
        hours = when.get("hours")
        if hours is not None:
            start, end = hours
            inside = start <= wall.hour <= end if start <= end else (
                wall.hour >= start or wall.hour <= end)
            if not inside:
                return False, f"outside hours {start}–{end}"
        if "weekdays" in when and wall.weekday() not in when["weekdays"]:
            return False, "not on this weekday"
        if "chance" in when and self._rng.random() >= float(when["chance"]):
            return False, "chance roll failed"
        return True, ""

    def tick(self, now: float | None = None) -> list[Step]:
        """Timed events: ``every:``, ``at:`` and ``idle:``. Call about once a second."""
        now = self._clock() if now is None else now
        steps: list[Step] = self._apply_due_states(now)
        wall = self._now()
        for rule in self.rules:
            event = rule.get("on", "")
            if event.startswith("every:"):
                period = float(event[6:])
                last = self._every.setdefault(event, now)
                if period > 0 and now - last >= period:
                    self._every[event] = now
                    steps += self.fire(event, now=now)
            elif event.startswith("at:"):
                key = (event, wall.strftime("%Y-%m-%d"))
                if wall.strftime("%H:%M") == event[3:] and key not in self._fired_at:
                    self._fired_at.add(key)
                    steps += self.fire(event, now=now)
            elif event.startswith("idle:"):
                if now - self._last_activity >= float(event[5:]):
                    self._last_activity = now
                    steps += self.fire(event, now=now)
        return steps

    def simulate(self, events: list[tuple[float, str]]) -> list[TraceEntry]:
        """Preview: run ``(seconds, event)`` pairs on a copy of the timing state
        and return the trace. ``tick`` events advance timed rules."""
        self.trace = []
        start = self._clock()
        for offset, event in sorted(events, key=lambda e: e[0]):
            now = start + float(offset)
            if event == "tick":
                self.tick(now=now)
            else:
                self.fire(event, now=now)
        return list(self.trace)

    def _log(self, now, event, rule, outcome, detail, steps=None) -> None:
        self.trace.append(TraceEntry(round(now, 3), event, rule, outcome, detail,
                                     list(steps or []), self.state))
        if len(self.trace) > 500:
            del self.trace[:-500]


def parse_simulation(text: str) -> tuple[list[tuple[float, str]], list[Problem]]:
    """Lines ``<seconds> <event>`` (``#`` starts a comment) for the preview."""
    events, problems = [], []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        try:
            seconds = float(parts[0])
        except ValueError:
            problems.append(Problem(f"line {number}", "starts with the time in seconds"))
            continue
        if len(parts) != 2 or not (parts[1] == "tick" or _EVENT.match(parts[1])):
            problems.append(Problem(f"line {number}", "needs one event after the time"))
            continue
        events.append((seconds, parts[1]))
    return events, problems


def overview(behaviors, *, hit_areas=(), hotkeys=None, music_enabled=False) -> list[str]:
    """What the rules listen to and what will not work as configured (R5.4):
    click zones without a hit area, hotkey actions without a binding or with a
    clashing one, ``beat`` rules while music rhythm is off."""
    from rigora.desktop_pet.hotkey_conflicts import find_conflicts
    notes = []
    rules = (behaviors or {}).get("rules", []) if isinstance(behaviors, dict) else []
    bindings = dict(hotkeys or {})
    clashes = find_conflicts(bindings)
    for rule in rules:
        event = str(rule.get("on", ""))
        rule_id = rule.get("id", "?")
        if event.startswith("click:") and event != "click:*" and event[6:] not in hit_areas:
            notes.append(f"{rule_id}: no hit area {event[6:]!r} on this rig")
        if event.startswith("hotkey:"):
            action = event[7:]
            if action not in bindings:
                notes.append(f"{rule_id}: hotkey action {action!r} has no key")
            elif any(action in actions for actions in clashes.values()):
                notes.append(f"{rule_id}: the key for {action!r} clashes with another action")
        if event == "beat" and not music_enabled:
            notes.append(f"{rule_id}: music rhythm is off, so 'beat' never fires")
    return notes
