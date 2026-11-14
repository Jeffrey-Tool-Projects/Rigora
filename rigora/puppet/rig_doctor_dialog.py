"""Rig doctor dialog: tick findings, preview the change, locate parts (R2.6)."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.document import PuppetDocument
from rigora.puppet.rig_doctor import Finding, preview_fixes

_KIND_FALLBACK = {"mesh": "Mesh", "weights": "Weights", "symmetry": "Symmetry",
                  "auto_rig": "Auto-rig", "validation": "Check"}


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


class RigDoctorDialog(QDialog):
    def __init__(self, parent: QWidget, document: PuppetDocument, findings: list[Finding],
                 locate: Callable[[str], None]) -> None:
        super().__init__(parent)
        self.document = document
        self.findings = findings
        self._locate = locate
        self.setWindowTitle(_tr("puppet_doctor_title", "Rig doctor"))
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        fixable = sum(f.fixable for f in findings)
        layout.addWidget(QLabel(_tr(
            "puppet_doctor_summary",
            "{n} findings, {fixable} fixable. Tick fixes, preview them, then apply; "
            "Undo reverts the whole set.", n=len(findings), fixable=fixable)))
        self.table = QTableWidget(len(findings), 5, self)
        self.table.setObjectName("doctor_findings")
        self.table.setHorizontalHeaderLabels([
            _tr("puppet_doctor_col_fix", "Fix"), _tr("puppet_import_col_severity", "Severity"),
            _tr("puppet_doctor_col_kind", "Kind"), _tr("puppet_doctor_col_location", "Part"),
            _tr("puppet_import_col_detail", "Detail")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, finding in enumerate(findings):
            check = QTableWidgetItem()
            if finding.fixable:
                check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                default = finding.kind in ("mesh", "weights")
                check.setCheckState(Qt.CheckState.Checked if default else Qt.CheckState.Unchecked)
            else:
                check.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 0, check)
            for column, text in enumerate((
                _tr(f"puppet_import_severity_{finding.severity}", finding.severity),
                _tr(f"puppet_doctor_kind_{finding.kind}", _KIND_FALLBACK[finding.kind]),
                finding.location, finding.message), start=1):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        preview = QPushButton(_tr("puppet_doctor_preview", "Preview changes"))
        preview.clicked.connect(self.show_preview)
        locate_button = QPushButton(_tr("puppet_doctor_locate", "Select part"))
        locate_button.clicked.connect(self._locate_selected)
        row.addWidget(preview)
        row.addWidget(locate_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.preview_label = QLabel()
        self.preview_label.setObjectName("doctor_preview")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            _tr("puppet_doctor_apply", "Apply ticked fixes"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_checked(self, finding_id: str, checked: bool) -> None:
        row = next(i for i, f in enumerate(self.findings) if f.id == finding_id)
        self.table.item(row, 0).setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def selected_fixes(self) -> list[str]:
        return [f.id for row, f in enumerate(self.findings)
                if f.fixable and self.table.item(row, 0).checkState() == Qt.CheckState.Checked]

    def show_preview(self) -> object:
        result = preview_fixes(self.document, self.selected_fixes())
        lines = [_tr("puppet_doctor_preview_head", "{n} fixes would change the rig:",
                     n=len(result.applied))]
        lines += [f"• {drawable}: {notes}" for drawable, notes in result.changed_drawables.items()]
        lines += [f"• + {kind}: {', '.join(ids)}" for kind, ids in result.added.items()]
        lines.append(_tr("puppet_doctor_remaining", "{n} findings would remain.",
                         n=result.remaining))
        self.preview_label.setText("\n".join(lines))
        return result

    def _locate_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self._locate(self.findings[row].location)
