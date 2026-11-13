"""Which live input controls each parameter right now (R4.2)."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.input_arbitration import DEFAULT_PRIORITIES, SOURCE_LABELS, source_kind

REFRESH_MS = 250


def _tr(key: str, fallback: str) -> str:
    return language_wrapper.language_word_dict.get(key, fallback)


def owner_label(source: str) -> str:
    if not source:
        return "—"
    key, fallback = SOURCE_LABELS.get(source_kind(source), ("", source_kind(source)))
    label = _tr(key, fallback) if key else fallback
    detail = source.split(":", 1)[1] if ":" in source else ""
    return f"{label} ({detail})" if detail else label


class InputSourcesDialog(QDialog):
    def __init__(self, canvas, parent=None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self.setWindowTitle(_tr("puppet_input_sources_title", "Input Sources"))
        order = " > ".join(_tr(*SOURCE_LABELS[k]) for k in sorted(
            DEFAULT_PRIORITIES, key=DEFAULT_PRIORITIES.get, reverse=True))
        hint = QLabel(_tr("puppet_input_sources_hint",
                          "A higher source takes over a parameter at once; a lower one waits "
                          "until the owner stops writing. Priority: {order}").format(order=order))
        hint.setWordWrap(True)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels([
            _tr("puppet_input_sources_parameter", "Parameter"),
            _tr("puppet_input_sources_owner", "Controlled by"),
            _tr("puppet_input_sources_age", "Last write (s)"),
            _tr("puppet_input_sources_overlays", "Expression overlays")])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self._table)
        self.resize(560, 420)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, event) -> None:   # noqa: N802 - Qt override
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:   # noqa: N802 - Qt override
        self._timer.stop()
        super().hideEvent(event)

    def rows(self) -> list[tuple[str, str, str, str]]:
        document = self._canvas.document()
        if document is None:
            return []
        rows = self._canvas.input_arbiter().owner_rows(
            [p.id for p in document.parameters], self._canvas.active_expressions())
        return [(param, owner_label(owner), "" if age is None else f"{age:.2f}",
                 ", ".join(overlays)) for param, owner, age, overlays in rows]

    def refresh(self) -> None:
        rows = self.rows()
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = self._table.item(r, c)
                if item is None:
                    self._table.setItem(r, c, QTableWidgetItem(text))
                elif item.text() != text:
                    item.setText(text)
