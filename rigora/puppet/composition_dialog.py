"""Composition editor: layers and clips over existing motions (R3.2).

Edits a copy of the document's compositions. Each table row is one layer
or clip; numeric cells are plain text checked on apply, so a typo is
reported instead of silently becoming zero. Nothing reaches the document
until the workspace applies :meth:`CompositionDialog.result` in one
transaction.
"""
from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.composition import LAYER_BLENDS, validate_composition
from rigora.puppet.document import Clip, Composition, CompositionLayer, PuppetDocument

_CLIP_COLUMNS = ("motion", "start", "offset", "length", "loop", "fade_in", "fade_out",
                 "weight", "muted")
_LAYER_COLUMNS = ("id", "blend", "weight", "muted")


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


def _text(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return ""
    return f"{value:g}" if isinstance(value, float) else str(value)


def _flag(text: str) -> bool:
    return text.strip().lower() in ("yes", "true", "1", "on")


def _number(text: str, label: str) -> float:
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number, got {text!r}") from exc


class CompositionDialog(QDialog):
    def __init__(self, parent: QWidget, document: PuppetDocument) -> None:
        super().__init__(parent)
        self.document = document
        self.compositions: list[Composition] = deepcopy(document.compositions)
        self.preview_requested = None
        self.bake_requested: str | None = None
        self.setWindowTitle(_tr("puppet_compositions_title", "Compositions"))
        self.resize(980, 600)
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self._shown: Composition | None = None
        self._clip_layer = -1
        self.list.currentRowChanged.connect(self._switch_composition)
        left.addWidget(self.list, 1)
        for key, fallback, slot in (("puppet_compositions_new", "New", self.add_composition),
                                    ("puppet_compositions_delete", "Delete", self._delete)):
            button = QPushButton(_tr(key, fallback))
            button.clicked.connect(slot)
            left.addWidget(button)
        root.addLayout(left, 1)
        root.addLayout(self._build_editor(), 4)
        self._refresh_list()

    def _build_editor(self) -> QVBoxLayout:
        right = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(QLabel(_tr("puppet_compositions_duration", "Duration (s)")))
        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.01, 3600.0)
        self.duration.setDecimals(3)
        top.addWidget(self.duration)
        top.addStretch(1)
        right.addLayout(top)
        right.addWidget(QLabel(_tr("puppet_compositions_layers",
                                   "Layers (later rows have priority)")))
        self.layers = QTableWidget(0, len(_LAYER_COLUMNS))
        self.layers.setHorizontalHeaderLabels(list(_LAYER_COLUMNS))
        self.layers.currentCellChanged.connect(lambda row, *_: self._switch_layer(row))
        right.addWidget(self.layers, 1)
        right.addLayout(self._row_buttons(self.add_layer, self._delete_layer))
        right.addWidget(QLabel(_tr("puppet_compositions_clips", "Clips of the selected layer")))
        self.clips = QTableWidget(0, len(_CLIP_COLUMNS))
        self.clips.setHorizontalHeaderLabels(list(_CLIP_COLUMNS))
        self.clips.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self.clips, 2)
        right.addLayout(self._row_buttons(self.add_clip, self._delete_clip))
        self.message = QLabel()
        self.message.setObjectName("composition_message")
        self.message.setWordWrap(True)
        right.addWidget(self.message)
        bottom = QHBoxLayout()
        preview = QPushButton(_tr("puppet_compositions_preview", "Preview"))
        preview.clicked.connect(self._preview)
        bottom.addWidget(preview)
        bake = QPushButton(_tr("puppet_compositions_bake", "Save and bake into motion"))
        bake.setToolTip(_tr("puppet_compositions_bake_tip",
                            "Save the compositions, then add the selected one as a new motion "
                            "that can be played, edited and exported like any other."))
        bake.clicked.connect(self._bake)
        bottom.addWidget(bake)
        bottom.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        right.addLayout(bottom)
        return right

    def _row_buttons(self, add, remove) -> QHBoxLayout:
        row = QHBoxLayout()
        for key, fallback, slot in (("puppet_compositions_add_row", "Add", add),
                                    ("puppet_compositions_remove_row", "Remove", remove)):
            button = QPushButton(_tr(key, fallback))
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        return row

    # ---- model <-> tables -------------------------------------------------

    def current(self) -> Composition | None:
        row = self.list.currentRow()
        return self.compositions[row] if 0 <= row < len(self.compositions) else None

    def _refresh_list(self, select: int = 0) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems([c.name for c in self.compositions])
        self.list.blockSignals(False)
        if self.compositions:
            self.list.setCurrentRow(min(select, len(self.compositions) - 1))
        self._show(self.list.currentRow())

    def _switch_composition(self, row: int) -> None:
        """Keep the edits of the composition being left, then show ``row``."""
        if self._shown is not None and self._shown in self.compositions:
            self.store(self._shown)
        self._show(row)

    def _switch_layer(self, row: int) -> None:
        if row != self._clip_layer and self._shown is not None:
            self.store(self._shown)
        self._show_clips(row)

    def _show(self, _row: int) -> None:
        composition = self.current()
        self._shown = composition
        self._clip_layer = -1
        self.layers.blockSignals(True)
        self.layers.setRowCount(0)
        self.clips.setRowCount(0)
        if composition is None:
            self.layers.blockSignals(False)
            return
        self.duration.setValue(composition.duration)
        self.layers.setRowCount(len(composition.layers))
        for row, layer in enumerate(composition.layers):
            self.layers.setItem(row, 0, QTableWidgetItem(layer.id))
            blend = QComboBox()
            blend.addItems(LAYER_BLENDS)
            blend.setCurrentText(layer.blend)
            self.layers.setCellWidget(row, 1, blend)
            self.layers.setItem(row, 2, QTableWidgetItem(_text(layer.weight)))
            self.layers.setItem(row, 3, QTableWidgetItem(_text(layer.muted)))
        if composition.layers:
            self.layers.setCurrentCell(0, 0)
        self.layers.blockSignals(False)
        if composition.layers:
            self._show_clips(0)

    def _show_clips(self, layer_row: int) -> None:
        composition = self.current()
        self.clips.setRowCount(0)
        if composition is None or not 0 <= layer_row < len(composition.layers):
            self._clip_layer = -1
            return
        clips = composition.layers[layer_row].clips
        self.clips.setRowCount(len(clips))
        for row, clip in enumerate(clips):
            motion = QComboBox()
            motion.addItems([m.name for m in self.document.motions])
            motion.setCurrentText(clip.motion)
            self.clips.setCellWidget(row, 0, motion)
            for column, name in enumerate(_CLIP_COLUMNS[1:], start=1):
                self.clips.setItem(row, column, QTableWidgetItem(_text(getattr(clip, name))))
        self._clip_layer = layer_row

    def store(self, composition: Composition | None = None) -> bool:
        """Read the tables back into the shown composition."""
        composition = composition or self._shown
        if composition is None:
            return True
        try:
            composition.duration = self.duration.value()
            layers = []
            for row in range(self.layers.rowCount()):
                old = composition.layers[row] if row < len(composition.layers) else None
                layers.append(CompositionLayer(
                    id=self.layers.item(row, 0).text().strip(),
                    clips=old.clips if old else [],
                    blend=self.layers.cellWidget(row, 1).currentText(),
                    weight=_number(self.layers.item(row, 2).text(), "layer weight"),
                    muted=_flag(self.layers.item(row, 3).text())))
            composition.layers = layers
            layer_row = self._clip_layer
            if 0 <= layer_row < len(layers):
                layers[layer_row].clips = [self._clip_from_row(r)
                                           for r in range(self.clips.rowCount())]
        except ValueError as exc:
            self.message.setText(str(exc))
            return False
        problems = validate_composition(self.document, composition)
        self.message.setText("\n".join(problems))
        return not problems

    def _clip_from_row(self, row: int) -> Clip:
        cell = {name: self.clips.item(row, column).text()
                for column, name in enumerate(_CLIP_COLUMNS) if column}
        length = cell["length"].strip()
        return Clip(
            motion=self.clips.cellWidget(row, 0).currentText(),
            start=_number(cell["start"], "start"), offset=_number(cell["offset"], "offset"),
            length=_number(length, "length") if length else None, loop=_flag(cell["loop"]),
            fade_in=_number(cell["fade_in"], "fade in"),
            fade_out=_number(cell["fade_out"], "fade out"),
            weight=_number(cell["weight"], "clip weight"), muted=_flag(cell["muted"]))

    # ---- actions -----------------------------------------------------------

    def add_composition(self, name: str | None = None) -> Composition:
        if self.current() is not None:
            self.store()
        taken = {c.name for c in self.compositions}
        base = name or "composition"
        candidate, index = base, 2
        while candidate in taken:
            candidate, index = f"{base} {index}", index + 1
        longest = max((m.duration for m in self.document.motions), default=1.0) or 1.0
        composition = Composition(candidate, float(longest), [CompositionLayer("base")])
        self.compositions.append(composition)
        self._refresh_list(len(self.compositions) - 1)
        return composition

    def _delete(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.compositions):
            del self.compositions[row]
            self._refresh_list(max(0, row - 1))

    def add_layer(self) -> None:
        composition = self.current()
        if composition is None or not self.store():
            return
        ids = {layer.id for layer in composition.layers}
        index = len(ids) + 1
        while f"layer{index}" in ids:
            index += 1
        composition.layers.append(CompositionLayer(f"layer{index}"))
        self._show(self.list.currentRow())

    def _delete_layer(self) -> None:
        composition = self.current()
        row = self.layers.currentRow()
        if composition is not None and 0 <= row < len(composition.layers) and self.store():
            del composition.layers[row]
            self._show(self.list.currentRow())

    def add_clip(self, motion: str | None = None) -> bool:
        composition = self.current()
        row = self._clip_layer
        if composition is None or not self.document.motions or not self.store() \
                or not 0 <= row < len(composition.layers):
            return False
        composition.layers[row].clips.append(Clip(motion or self.document.motions[0].name))
        self._show_clips(row)
        return True

    def _delete_clip(self) -> None:
        composition = self.current()
        layer_row, clip_row = self._clip_layer, self.clips.currentRow()
        if composition is None or not 0 <= layer_row < len(composition.layers) \
                or not self.store():
            return
        clips = composition.layers[layer_row].clips
        if 0 <= clip_row < len(clips):
            del clips[clip_row]
            self._show_clips(layer_row)

    def _preview(self) -> None:
        if self.store() and self.preview_requested is not None and self.current() is not None:
            self.preview_requested(deepcopy(self.current()))

    def _bake(self) -> None:
        if self.current() is None:
            return
        self.bake_requested = self.current().name
        self._accept()
        if self.result_code() != QDialog.DialogCode.Accepted:
            self.bake_requested = None

    def result_code(self):
        return QDialog.DialogCode(super().result())

    def rename(self, name: str) -> None:
        composition = self.current()
        if composition is not None and name.strip():
            composition.name = name.strip()
            self._refresh_list(self.list.currentRow())

    def _accept(self) -> None:
        if self.current() is not None and not self.store():
            return
        problems = [f"{c.name}: {p}" for c in self.compositions
                    for p in validate_composition(self.document, c)]
        names = [c.name for c in self.compositions]
        if len(set(names)) != len(names):
            problems.append("composition names must be unique")
        if problems:
            self.message.setText("\n".join(problems))
            return
        self.accept()

    def result(self) -> list[Composition]:
        return deepcopy(self.compositions)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_F2 and self.current() is not None:
            name, ok = QInputDialog.getText(self, _tr("puppet_compositions_rename", "Rename"),
                                            _tr("puppet_compositions_name", "Name:"),
                                            text=self.current().name)
            if ok:
                self.rename(name)
            return
        super().keyPressEvent(event)
