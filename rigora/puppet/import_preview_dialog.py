"""Dialogs that show an import preview before the document changes.

The PSD dialog lists every layer — name, group, size, position, order,
opacity, blend, mask and clipping — and the differences the import cannot
carry over. The Cubism dialog lists the referenced files and differences.
Blocking differences disable the Import button so a doomed import is never
started. Builders return an unexecuted dialog; the workspace runs it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.cubism_preview import CubismImportPreview
from rigora.puppet.import_report import SEVERITY_ERROR, SEVERITY_WARNING, ImportDifference
from rigora.puppet.psd_import_report import PsdImportPreview

_SEVERITY_FALLBACK = {"error": "Blocks import", "warning": "Changes result", "info": "Note"}
_STATUS_FALLBACK = {
    "import": "Import", "hidden": "Hidden — skipped", "empty": "Empty — skipped",
    "clip_base_missing": "Clip base hidden — skipped",
}


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


def difference_label(diff: ImportDifference) -> str:
    """Translated short name of a difference code; the code itself as fallback."""
    return _tr(f"puppet_import_diff_{diff.code}", diff.code.replace("_", " "))


def _item(text: str, tooltip: str = "") -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if tooltip:
        item.setToolTip(tooltip)
    return item


def _table(headers: list[str], rows: list[list[str]], parent: QWidget) -> QTableWidget:
    table = QTableWidget(len(rows), len(headers), parent)
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            table.setItem(row, column, _item(value))
    return table


def differences_table(differences: tuple[ImportDifference, ...], parent: QWidget) -> QTableWidget:
    """Severity / subject / issue table; the English detail is the tooltip
    and the last column so nothing is hidden behind hover."""
    order = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1}
    ranked = sorted(differences, key=lambda d: order.get(d.severity, 2))
    rows = [[_tr(f"puppet_import_severity_{d.severity}", _SEVERITY_FALLBACK[d.severity]),
             d.subject, difference_label(d), d.detail] for d in ranked]
    table = _table([
        _tr("puppet_import_col_severity", "Severity"),
        _tr("puppet_import_col_subject", "Item"),
        _tr("puppet_import_col_issue", "Difference"),
        _tr("puppet_import_col_detail", "Detail"),
    ], rows, parent)
    table.setObjectName("import_differences")
    return table


def _dialog(parent: QWidget, title: str, summary: str) -> tuple[QDialog, QVBoxLayout]:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(900, 560)
    layout = QVBoxLayout(dialog)
    label = QLabel(summary, dialog)
    label.setObjectName("import_summary")
    label.setWordWrap(True)
    layout.addWidget(label)
    return dialog, layout


def _finish(dialog: QDialog, layout: QVBoxLayout,
            differences: tuple[ImportDifference, ...]) -> QDialog:
    if differences:
        layout.addWidget(QLabel(_tr("puppet_import_differences_heading",
                                    "Differences from the source ({n})", n=len(differences)),
                                dialog))
        layout.addWidget(differences_table(differences, dialog))
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
    ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
    ok.setText(_tr("puppet_import_confirm", "Import"))
    blocked = any(d.severity == SEVERITY_ERROR for d in differences)
    ok.setEnabled(not blocked)
    if blocked:
        ok.setToolTip(_tr("puppet_import_blocked", "Resolve the blocking items first."))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return dialog


def build_psd_preview_dialog(parent: QWidget, preview: PsdImportPreview) -> QDialog:
    width, height = preview.canvas_size
    summary = _tr(
        "puppet_import_psd_summary",
        "{n} of {total} layers become drawables on a {w}×{h} canvas. "
        "Bottom layers draw first.",
        n=len(preview.imported_layers), total=len(preview.layers), w=width, h=height)
    dialog, layout = _dialog(parent, _tr("puppet_import_psd_preview_title", "PSD import preview"),
                             summary)
    rows = []
    for layer in reversed(preview.layers):   # top of the stack first, as in Photoshop
        size = f"{layer.size[0]}×{layer.size[1]}" if layer.size else "—"
        position = f"{layer.bounds[0]}, {layer.bounds[1]}" if layer.bounds else "—"
        flags = [name for name, on in (
            (_tr("puppet_import_flag_mask", "mask"), layer.has_mask),
            (_tr("puppet_import_flag_clip", "clip → {target}", target=layer.clip_mask or "—"),
             layer.clipping)) if on]
        rows.append([
            str(layer.index), layer.name, " / ".join(layer.group_path),
            _tr(f"puppet_import_status_{layer.status}", _STATUS_FALLBACK[layer.status]),
            layer.drawable_id or "—", size, position, f"{layer.opacity:.0%}",
            layer.source_blend_mode if layer.blend_mode in (None, layer.source_blend_mode)
            else f"{layer.source_blend_mode} → {layer.blend_mode}",
            ", ".join(flags),
        ])
    table = _table([
        _tr("puppet_import_col_order", "Order"), _tr("puppet_import_col_layer", "Layer"),
        _tr("puppet_import_col_group", "Group"), _tr("puppet_import_col_status", "Status"),
        _tr("puppet_import_col_drawable", "Drawable"), _tr("puppet_import_col_size", "Size"),
        _tr("puppet_import_col_position", "Position"),
        _tr("puppet_import_col_opacity", "Opacity"), _tr("puppet_import_col_blend", "Blend"),
        _tr("puppet_import_col_flags", "Mask / clip"),
    ], rows, dialog)
    table.setObjectName("import_layers")
    layout.addWidget(table, 2)
    return _finish(dialog, layout, preview.differences)


def build_cubism_preview_dialog(parent: QWidget, preview: CubismImportPreview) -> QDialog:
    present = sum(ref.exists for ref in preview.references)
    key = "puppet_import_cubism_summary_" + preview.mode
    fallback = ("Convert the model into a new puppet. {found} of {total} referenced files "
                "found; {motions} motions, {expressions} expressions."
                if preview.mode == "convert" else
                "Add motions, expressions and metadata to the open puppet. {found} of {total} "
                "referenced files found; {motions} motions, {expressions} expressions.")
    summary = _tr(key, fallback, found=present, total=len(preview.references),
                  motions=len(preview.motion_names), expressions=len(preview.expression_names))
    dialog, layout = _dialog(
        parent, _tr("puppet_import_cubism_preview_title", "Cubism import preview"), summary)
    found = _tr("puppet_import_file_found", "Found")
    missing = _tr("puppet_import_file_missing", "Missing")
    rows = [[ref.kind, ref.path, ref.name, found if ref.exists else missing]
            for ref in preview.references]
    table = _table([
        _tr("puppet_import_col_kind", "Kind"), _tr("puppet_import_col_file", "File"),
        _tr("puppet_import_col_name", "Name"), _tr("puppet_import_col_status", "Status"),
    ], rows, dialog)
    table.setObjectName("import_references")
    layout.addWidget(table, 2)
    return _finish(dialog, layout, preview.differences)
