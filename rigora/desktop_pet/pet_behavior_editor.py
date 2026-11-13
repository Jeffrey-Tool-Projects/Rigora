"""The Behaviors tab of the pet script editor: edit, check and preview (R5.3 / R5.4).

Rules are edited as JSON. **Check** reports every problem with its place
(``rules[1].do[0]``, or the line and column of a JSON error). **Preview** runs
a list of simulated events through a copy of the engine and shows which rule
ran, which were skipped and why, and the resulting state — no global key is
pressed, no motion plays and nothing is said.
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rigora.desktop_pet.pet_behavior import (
    BehaviorEngine,
    Problem,
    overview,
    parse_simulation,
    validate,
)
from rigora.desktop_pet.pet_script_string_list import _tr

EXAMPLE_EVENTS = "0 start\n1 click:head\n2 click:head   # inside the cooldown\n8 tick\n"


class BehaviorEditor(QWidget):
    def __init__(self, behaviors: dict | None, context: dict | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._context = dict(context or {})
        self.text = QPlainTextEdit(json.dumps(behaviors or {"initial": "idle", "rules": []},
                                              indent=2, ensure_ascii=False))
        self.events = QPlainTextEdit(EXAMPLE_EVENTS)
        self.events.setMaximumHeight(110)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        check = QPushButton(_tr("desktop_pet_behaviors_check", "Check"))
        check.clicked.connect(self.check)
        preview = QPushButton(_tr("desktop_pet_behaviors_preview", "Preview events"))
        preview.clicked.connect(self.preview)
        buttons = QHBoxLayout()
        buttons.addWidget(check)
        buttons.addWidget(preview)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_tr("desktop_pet_behaviors_rules",
                                    "Rules (JSON; see the user guide for events and actions)")))
        layout.addWidget(self.text, 3)
        layout.addWidget(QLabel(_tr("desktop_pet_behaviors_events",
                                    "Simulated events: one '<seconds> <event>' per line")))
        layout.addWidget(self.events)
        layout.addLayout(buttons)
        layout.addWidget(self.report, 2)

    def parsed(self) -> tuple[dict | None, list[Problem]]:
        raw = self.text.toPlainText().strip()
        if not raw:
            return None, []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, [Problem(f"line {exc.lineno}, column {exc.colno}", exc.msg)]
        problems = validate(data, motions=self._context.get("motions"),
                            groups=self._context.get("groups"),
                            expressions=self._context.get("expressions"),
                            hit_areas=self._context.get("hit_areas"))
        return data, problems

    def check(self) -> list[Problem]:
        data, problems = self.parsed()
        notes = overview(data, hit_areas=self._context.get("hit_areas") or (),
                         hotkeys=self._context.get("hotkeys"),
                         music_enabled=bool(self._context.get("music_enabled"))) \
            if data and not problems else []
        lines = [str(p) for p in problems] + [f"note: {n}" for n in notes]
        self.report.setPlainText("\n".join(lines) if lines else
                                 _tr("desktop_pet_behaviors_ok", "No problems found."))
        return problems

    def preview(self) -> list:
        data, problems = self.parsed()
        events, event_problems = parse_simulation(self.events.toPlainText())
        if problems or event_problems:
            self.report.setPlainText("\n".join(map(str, problems + event_problems)))
            return []
        engine = BehaviorEngine(data, now=self._context.get("now") or _wall_now)
        trace = engine.simulate(events)
        self.report.setPlainText("\n".join(_describe(entry) for entry in trace) or "—")
        return trace

    def behaviors(self) -> dict | None:
        data, problems = self.parsed()
        if problems:
            raise ValueError("; ".join(map(str, problems[:5])))
        return data if data and data.get("rules") else None   # no rules = no section


def _wall_now():
    from datetime import datetime
    return datetime.now()


def _describe(entry) -> str:
    head = f"{entry.time - 0:8.2f}s  {entry.event:<16} "
    if entry.outcome == "ran":
        actions = ", ".join(f"{s.kind}={s.value}" + (f" (+{s.delay:g}s)" if s.delay else "")
                            for s in entry.steps)
        return head + f"→ {entry.rule}: {actions}  [state {entry.state}]"
    return head + f"{entry.outcome}" + (f": {entry.detail}" if entry.detail else "")
