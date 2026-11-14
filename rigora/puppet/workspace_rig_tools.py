"""Rig-structure commands of the puppet workspace (R2.4–R2.7).

Parameter ranges, physics chains, rig diagnostics and part templates are
edited here. Each change validates first, then runs as one transaction.
"""
from __future__ import annotations

from copy import deepcopy

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
)

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.document import PuppetDocument
from rigora.puppet.physics_tools import validate_rig
from rigora.puppet.rig_hierarchy import blend_axes, set_parameter_range


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


def _spin(value: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(3)
    box.setRange(-1e6, 1e6)
    box.setValue(value)
    return box


class PuppetRigToolsMixin:
    """Validated rig-structure edits of :class:`~rigora.puppet.workspace.PuppetWorkspace`."""

    def _apply_rig_edit(self, label: str, edit) -> object:
        """Run ``edit`` in one transaction; report ``ValueError`` without changes."""
        if self.session.document is None:
            self._announce("puppet_rig_no_doc", "Open a puppet first.")
            return None
        self._begin_document_work()
        try:
            with self.session.transaction(label):
                result = edit(self.session.document)
        except ValueError as exc:
            self._announce("puppet_rig_edit_failed", "{label} failed: {error}",
                           label=label, error=str(exc))
            return None
        self._canvas.load_document(self.session.document)
        self._update_session_actions()
        return result

    def edit_parameter_range(self, param_id: str, minimum: float, maximum: float,
                             default: float) -> bool:
        result = self._apply_rig_edit("Edit parameter range", lambda doc: set_parameter_range(
            doc, param_id, minimum, maximum, default))
        if result is None:
            return False
        affected = blend_axes(self.session.document, param_id)
        self._announce("puppet_parameter_range_done",
                       "{id} now runs {minimum}..{maximum} (default {default}).",
                       id=param_id, minimum=f"{minimum:g}", maximum=f"{maximum:g}",
                       default=f"{default:g}")
        if affected:
            self._status_label.setText(self._status_label.text() + " " + _tr(
                "puppet_parameter_range_blends", "Also used by blends: {ids}",
                ids=", ".join(affected)))
        return True

    def edit_parameter_range_via_dialog(self, param_id: str) -> bool:
        document = self._canvas.document()
        parameter = document.parameter(param_id) if document is not None else None
        if parameter is None:
            return False
        dialog = QDialog(self)
        dialog.setWindowTitle(_tr("puppet_parameter_range_title", "Range of {id}", id=param_id))
        form = QFormLayout(dialog)
        boxes = [_spin(parameter.min), _spin(parameter.max), _spin(parameter.default)]
        for label, box in zip((_tr("puppet_parameter_min", "Minimum"),
                               _tr("puppet_parameter_max", "Maximum"),
                               _tr("puppet_parameter_default", "Default")), boxes, strict=True):
            form.addRow(label, box)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        accepted = self._run_rig_dialog(dialog)
        values = [box.value() for box in boxes]
        dialog.deleteLater()
        return accepted and self.edit_parameter_range(param_id, *values)

    def apply_physics_rigs(self, rigs) -> bool:
        """Replace every physics chain at once after validating them together."""
        def edit(document):
            probe = PuppetDocument(parameters=document.parameters, physics_rigs=list(rigs))
            problems = [f"{rig.id}: {problem}" for rig in rigs
                        for problem in validate_rig(probe, rig)]
            if problems:
                raise ValueError("; ".join(problems))
            document.physics_rigs = deepcopy(list(rigs))
            return len(rigs)

        count = self._apply_rig_edit("Edit physics chains", edit)
        if count is None:
            return False
        self._announce("puppet_physics_applied", "{n} physics chains saved to the rig.", n=count)
        return True

    def edit_physics_via_dialog(self) -> bool:
        from rigora.puppet.physics_dialog import PhysicsDialog
        from rigora.puppet.physics_tools import default_preset_store
        document = self._canvas.document()
        if document is None:
            self._announce("puppet_rig_no_doc", "Open a puppet first.")
            return False
        dialog = PhysicsDialog(self, document, default_preset_store())
        accepted = self._run_rig_dialog(dialog)
        rigs = dialog.result_rigs()
        dialog.deleteLater()
        return accepted and self.apply_physics_rigs(rigs)

    def apply_rig_fixes(self, finding_ids: list[str]):
        """Apply rig-doctor fixes as one undoable edit; returns the change summary."""
        from rigora.puppet.rig_doctor import apply_fixes
        result = self._apply_rig_edit("Rig doctor fixes",
                                      lambda doc: apply_fixes(doc, list(finding_ids)))
        if result is None:
            return None
        self._announce("puppet_doctor_done",
                       "Applied {n} fixes; {left} findings remain.",
                       n=len(result.applied), left=result.remaining)
        return result

    def locate_rig_part(self, location: str) -> bool:
        """Select the part a finding points at: a drawable's vertices or a deformer."""
        kind, _, ident = location.partition(":")
        ident = ident.split(":", 1)[0]
        document = self._canvas.document()
        if document is None:
            return False
        if kind == "drawable" and document.drawable(ident) is not None:
            self._canvas.set_vertex_selection(
                ident, range(len(document.drawable(ident).vertices)))
            return True
        if kind == "deformer" and document.deformer(ident) is not None:
            self._canvas.set_selected_deformer(ident)
            self._bone_tree_dock.select_deformer(ident)
            return True
        return False

    def run_rig_doctor_via_dialog(self) -> bool:
        from rigora.puppet.rig_doctor import diagnose
        from rigora.puppet.rig_doctor_dialog import RigDoctorDialog
        document = self._canvas.document()
        if document is None:
            self._announce("puppet_rig_no_doc", "Open a puppet first.")
            return False
        findings = diagnose(document)
        if not findings:
            self._announce("puppet_doctor_clean", "The rig doctor found nothing to report.")
            return False
        dialog = RigDoctorDialog(self, document, findings, self.locate_rig_part)
        accepted = self._run_rig_dialog(dialog)
        chosen = dialog.selected_fixes()
        dialog.deleteLater()
        return accepted and bool(chosen) and self.apply_rig_fixes(chosen) is not None

    def apply_part_template(self, template_id: str, mapping: dict[str, list[str]]):
        """Apply a part template as one undoable edit; returns what it added."""
        from rigora.puppet.part_templates import apply_template
        result = self._apply_rig_edit(
            "Apply part template", lambda doc: apply_template(doc, template_id, mapping))
        if result is None:
            return None
        count = sum(len(items) for items in result.values())
        self._announce("puppet_templates_done", "Template {name} applied ({n} changes).",
                       name=template_id, n=count)
        return result

    def part_templates_via_dialog(self) -> bool:
        from rigora.puppet.part_template_dialog import PartTemplateDialog
        document = self._canvas.document()
        if document is None:
            self._announce("puppet_rig_no_doc", "Open a puppet first.")
            return False
        dialog = PartTemplateDialog(self, document)
        accepted = self._run_rig_dialog(dialog)
        template_id, mapping = dialog.template_id(), dialog.mapping()
        dialog.deleteLater()
        return accepted and self.apply_part_template(template_id, mapping) is not None

    def _run_rig_dialog(self, dialog: QDialog) -> bool:
        return dialog.exec() == QDialog.DialogCode.Accepted
