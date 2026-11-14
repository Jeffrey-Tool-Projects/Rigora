"""Part template dialog: pick a template, map its roles, see what is missing (R2.7)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.document import PuppetDocument
from rigora.puppet.part_templates import TEMPLATES, check_template


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


class PartTemplateDialog(QDialog):
    def __init__(self, parent: QWidget, document: PuppetDocument) -> None:
        super().__init__(parent)
        self.document = document
        self.setWindowTitle(_tr("puppet_templates_title", "Part templates"))
        self.resize(560, 560)
        layout = QVBoxLayout(self)
        self.template_box = QComboBox()
        for template in TEMPLATES.values():
            self.template_box.addItem(_tr(f"puppet_template_{template.id}", template.title),
                                      template.id)
        self.template_box.currentIndexChanged.connect(self._build_roles)
        layout.addWidget(self.template_box)
        self.requirements = QLabel()
        self.requirements.setWordWrap(True)
        layout.addWidget(self.requirements)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        layout.addWidget(self.form_host, 1)
        self.status = QLabel()
        self.status.setObjectName("template_status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._inputs: dict[str, QComboBox | QListWidget] = {}
        self._build_roles()

    def template_id(self) -> str:
        return self.template_box.currentData()

    def select_template(self, template_id: str) -> None:
        self.template_box.setCurrentIndex(self.template_box.findData(template_id))

    def _build_roles(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._inputs = {}
        template = TEMPLATES[self.template_id()]
        lines = [_tr("puppet_templates_needs", "Needs:")]
        lines += [f"• {text}" for text in template.requirements]
        self.requirements.setText("\n".join(lines))
        ids = [d.id for d in self.document.drawables]
        for role in template.roles:
            if role.many:
                widget = QListWidget()
                widget.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
                widget.addItems(ids)
                widget.setMaximumHeight(110)
                widget.itemSelectionChanged.connect(self.refresh)
            else:
                widget = QComboBox()
                widget.addItem(_tr("puppet_templates_none", "(none)"), "")
                for drawable_id in ids:
                    widget.addItem(drawable_id, drawable_id)
                widget.currentIndexChanged.connect(self.refresh)
            label = role.name + ("" if not role.required else " *")
            widget.setToolTip(role.description)
            self.form.addRow(label, widget)
            self._inputs[role.name] = widget
        self.refresh()

    def set_role(self, role: str, drawable_ids: list[str]) -> None:
        widget = self._inputs[role]
        if isinstance(widget, QListWidget):
            for row in range(widget.count()):
                item = widget.item(row)
                item.setSelected(item.text() in drawable_ids)
        else:
            widget.setCurrentIndex(widget.findData(drawable_ids[0] if drawable_ids else ""))

    def mapping(self) -> dict[str, list[str]]:
        result = {}
        for role, widget in self._inputs.items():
            if isinstance(widget, QListWidget):
                ids = [item.text() for item in widget.selectedItems()]
            else:
                ids = [widget.currentData()] if widget.currentData() else []
            if ids:
                result[role] = ids
        return result

    def refresh(self) -> tuple[list[str], list[str]]:
        problems, warnings = check_template(self.document, self.template_id(), self.mapping())
        lines = [f"✗ {p}" for p in problems] + [f"! {w}" for w in warnings]
        self.status.setText("\n".join(lines) or _tr("puppet_templates_ready", "Ready to apply."))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not problems)
        return problems, warnings
