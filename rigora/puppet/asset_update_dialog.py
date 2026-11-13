"""Dialogs for updating art from a PSD and relinking missing textures."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.gui.file_filters import image_filter
from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.asset_update import (
    KIND_CHANGED,
    KIND_NEW,
    KIND_NOT_IN_SOURCE,
    KIND_UNCHANGED,
    AssetUpdatePlan,
    MissingTexture,
    locate_textures,
    preview_relink,
)
from rigora.puppet.document import PuppetDocument

_KIND_FALLBACK = {KIND_CHANGED: "Changed", KIND_UNCHANGED: "Unchanged", KIND_NEW: "New layer",
                  KIND_NOT_IN_SOURCE: "Not in PSD"}
_ACTION_FALLBACK = {"update": "Replace pixels, keep mesh", "rebuild": "Rebuild mesh",
                    "skip": "Leave as is", "add": "Add drawable", "keep": "Keep",
                    "hide": "Hide"}
_CONFLICT_FALLBACK = {
    "art_outside_mesh": "new art reaches past the mesh",
    "unaligned_uvs": "UVs are not a plain rectangle",
    "shared_texture": "texture shared with other drawables",
    "texture_missing": "current texture missing",
    "possible_rename": "probably a renamed layer",
    "id_taken": "id already used",
}
_NOTE_FALLBACK = {"size_differs": "size differs; image is stretched over the mesh",
                  "aspect_differs": "aspect ratio differs",
                  "shared_texture": "shared by several drawables"}


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def _area(rect) -> str:
    if rect is None:
        return "—"
    x0, y0, x1, y1 = (round(v) for v in rect)
    return f"{x1 - x0}×{y1 - y0} @ {x0}, {y0}"


def _table(parent: QWidget, headers: list[str], rows: int) -> QTableWidget:
    table = QTableWidget(rows, len(headers), parent)
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


class AssetUpdateDialog(QDialog):
    """Per-drawable choices for an :class:`AssetUpdatePlan`."""

    def __init__(self, parent: QWidget, plan: AssetUpdatePlan) -> None:
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle(_tr("puppet_art_update_title", "Update art from PSD"))
        self.resize(960, 520)
        layout = QVBoxLayout(self)
        counts = {kind: sum(c.kind == kind for c in plan.changes) for kind in _KIND_FALLBACK}
        summary = QLabel(_tr(
            "puppet_art_update_summary",
            "{changed} changed, {new} new, {gone} not in the PSD, {same} unchanged. "
            "Replacing pixels keeps meshes, weights, morphs and motions.",
            changed=counts[KIND_CHANGED], new=counts[KIND_NEW],
            gone=counts[KIND_NOT_IN_SOURCE], same=counts[KIND_UNCHANGED]), self)
        summary.setObjectName("art_update_summary")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        for problem in plan.blocking:
            blocked = QLabel(problem, self)
            blocked.setObjectName("art_update_blocking")
            blocked.setWordWrap(True)
            layout.addWidget(blocked)
        self._combos: dict[str, QComboBox] = {}
        layout.addWidget(self._build_table(), 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(_tr("puppet_art_update_apply", "Apply"))
        ok.setEnabled(not plan.blocking)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_table(self) -> QTableWidget:
        table = _table(self, [
            _tr("puppet_import_col_drawable", "Drawable"),
            _tr("puppet_import_col_layer", "Layer"),
            _tr("puppet_art_update_col_change", "Change"),
            _tr("puppet_art_update_col_current", "Current area"),
            _tr("puppet_art_update_col_new", "New area"),
            _tr("puppet_art_update_col_issues", "Issues"),
            _tr("puppet_art_update_col_action", "Action"),
        ], len(self.plan.changes))
        table.setObjectName("art_update_changes")
        for row, change in enumerate(self.plan.changes):
            issues = ", ".join(_tr(f"puppet_art_update_conflict_{c}", _CONFLICT_FALLBACK[c])
                               for c in change.conflicts)
            values = [change.drawable_id or "—", change.layer_name or "—",
                      _tr(f"puppet_art_update_kind_{change.kind}", _KIND_FALLBACK[change.kind]),
                      _area(change.texture_rect), _area(change.new_bounds), issues]
            for column, value in enumerate(values):
                table.setItem(row, column, _cell(value))
            combo = QComboBox(table)
            for action in change.actions:
                combo.addItem(_tr(f"puppet_art_update_action_{action}",
                                  _ACTION_FALLBACK[action]), action)
            combo.setCurrentIndex(change.actions.index(change.default_action))
            table.setCellWidget(row, len(values), combo)
            self._combos[change.key] = combo
        return table

    def set_action(self, key: str, action: str) -> None:
        combo = self._combos[key]
        combo.setCurrentIndex(combo.findData(action))

    def actions(self) -> dict[str, str]:
        return {key: combo.currentData() for key, combo in self._combos.items()}


class RelinkTexturesDialog(QDialog):
    """Pick replacement images for missing or unreadable textures."""

    def __init__(self, parent: QWidget, document: PuppetDocument,
                 missing: list[MissingTexture]) -> None:
        super().__init__(parent)
        self.document = document
        self.missing = missing
        self._choices: dict[str, Path] = {}
        self.setWindowTitle(_tr("puppet_relink_title", "Relink textures"))
        self.resize(900, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_tr(
            "puppet_relink_summary",
            "{n} textures are missing or unreadable. Choose an image for each, or search a "
            "folder for files with the same name. Images keep the existing UVs.",
            n=len(missing)), self))
        self.table = _table(self, [
            _tr("puppet_relink_col_texture", "Texture"),
            _tr("puppet_relink_col_users", "Used by"),
            _tr("puppet_relink_col_problem", "Problem"),
            _tr("puppet_relink_col_expected", "Expected size"),
            _tr("puppet_relink_col_choice", "Replacement"),
            _tr("puppet_relink_col_notes", "Notes"),
        ], len(missing))
        self.table.setObjectName("relink_textures")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for row, item in enumerate(missing):
            size = f"{item.expected_size[0]}×{item.expected_size[1]}" if item.expected_size \
                else "—"
            values = [item.texture, ", ".join(item.drawables),
                      _tr(f"puppet_relink_reason_{item.reason}", item.reason), size, "", ""]
            for column, value in enumerate(values):
                self.table.setItem(row, column, _cell(value))
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        choose = QPushButton(_tr("puppet_relink_choose", "Choose image…"), self)
        choose.clicked.connect(self._choose_for_selection)
        search = QPushButton(_tr("puppet_relink_search", "Search folder…"), self)
        search.clicked.connect(self._search_folder)
        row.addWidget(choose)
        row.addWidget(search)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText(_tr("puppet_relink_apply", "Relink"))
        self._ok.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choose(self, texture: str, path: str | Path) -> bool:
        """Use ``path`` for ``texture``; ``False`` when it is not a usable image."""
        row = next(i for i, m in enumerate(self.missing) if m.texture == texture)
        try:
            preview = preview_relink(self.document, texture, path)
        except ValueError as exc:
            self.table.setItem(row, 5, _cell(str(exc)))
            return False
        self._choices[texture] = Path(path)
        width, height = preview.image_size
        self.table.setItem(row, 4, _cell(f"{Path(path).name} ({width}×{height})"))
        notes = ", ".join(_tr(f"puppet_relink_note_{n}", _NOTE_FALLBACK[n])
                          for n in preview.notes)
        self.table.setItem(row, 5, _cell(notes))
        self._ok.setEnabled(True)
        return True

    def search(self, folder: str | Path) -> int:
        """Fill rows without a choice from files named like their texture."""
        found = locate_textures(self.missing, [folder])
        filled = 0
        for item in self.missing:
            if item.texture in self._choices:
                continue
            for candidate in found.get(item.texture, []):
                if self.choose(item.texture, candidate):
                    filled += 1
                    break
        return filled

    def choices(self) -> dict[str, Path]:
        return dict(self._choices)

    def _choose_for_selection(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, _tr("puppet_relink_choose", "Choose image…"), "",
            image_filter(("png", "webp", "jpg", "jpeg", "bmp", "tif", "tiff")))
        if path:
            self.choose(self.missing[row].texture, path)

    def _search_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, _tr("puppet_relink_search", "Search folder…"))
        if folder:
            self.search(folder)
