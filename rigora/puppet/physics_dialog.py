"""Physics chain editor dialog (R2.5).

Edits a working copy of the document's chains: input / output mapping,
per-particle mass, damping and spring, gravity, presets and a limit
assessment. Nothing reaches the document until the workspace applies
:meth:`PhysicsDialog.result_rigs` in one transaction.
"""
from __future__ import annotations

from copy import deepcopy

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.document import PhysicsRig, PuppetDocument
from rigora.puppet.physics_tools import (
    PresetStore,
    apply_preset,
    assess_limits,
    remove_rig,
    rig_to_preset,
    rig_warnings,
    upsert_rig,
    validate_rig,
)

_COLUMNS = ("mass", "damping", "spring")
_NEED_FALLBACK = {
    "output_clipped": "output clips at ±1 — a stiffer spring or a limit would help",
    "output_outside_parameter_range": "output leaves the output parameter's range",
    "swings_above_anchor": "chain swings above its anchor — a collision or angle limit would help",
    "does_not_settle": "chain keeps moving after the input stops — raise damping",
}


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


class PhysicsDialog(QDialog):
    def __init__(self, parent: QWidget, document: PuppetDocument, presets: PresetStore) -> None:
        super().__init__(parent)
        self.setWindowTitle(_tr("puppet_physics_title", "Physics chains"))
        self.resize(760, 520)
        self.presets = presets
        self.working = PuppetDocument(parameters=document.parameters,
                                      physics_rigs=deepcopy(document.physics_rigs))
        self._loading = False
        layout = QHBoxLayout(self)
        left = QVBoxLayout()
        self.chains = QListWidget()
        self.chains.currentTextChanged.connect(self._show_chain)
        left.addWidget(self.chains)
        for label_key, fallback, slot in (
            ("puppet_physics_new", "New chain", self._new_chain),
            ("puppet_physics_delete", "Delete chain", self._delete_chain),
        ):
            button = QPushButton(_tr(label_key, fallback))
            button.clicked.connect(slot)
            left.addWidget(button)
        layout.addLayout(left, 1)
        layout.addLayout(self._build_editor(), 3)
        self._refresh_list()

    # ---- layout ----------------------------------------------------------

    def _build_editor(self) -> QVBoxLayout:
        right = QVBoxLayout()
        form = QFormLayout()
        names = [p.id for p in self.working.parameters]
        self.input_box, self.output_box = QComboBox(), QComboBox()
        for box in (self.input_box, self.output_box):
            box.addItems(names)
        self.gravity = [QDoubleSpinBox(), QDoubleSpinBox()]
        for box in self.gravity:
            box.setRange(-100.0, 100.0)
            box.setDecimals(2)
        gravity_row = QHBoxLayout()
        for box in self.gravity:
            gravity_row.addWidget(box)
        self.particle_count = QSpinBox()
        self.particle_count.setRange(1, 16)
        self.particle_count.valueChanged.connect(self._resize_table)
        form.addRow(_tr("puppet_physics_input", "Input parameter"), self.input_box)
        form.addRow(_tr("puppet_physics_output", "Output parameter"), self.output_box)
        form.addRow(_tr("puppet_physics_gravity", "Gravity (x, y)"), gravity_row)
        form.addRow(_tr("puppet_physics_particles", "Particles"), self.particle_count)
        right.addLayout(form)
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels([
            _tr("puppet_physics_mass", "Mass"), _tr("puppet_physics_damping", "Damping"),
            _tr("puppet_physics_spring", "Spring")])
        right.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.preset_box = QComboBox()
        self.preset_box.addItems(self.presets.names())
        row.addWidget(self.preset_box, 1)
        for label_key, fallback, slot in (
            ("puppet_physics_apply_preset", "Apply preset", self._apply_preset),
            ("puppet_physics_save_preset", "Save as preset…", self._save_preset),
            ("puppet_physics_store", "Update chain", self.store_current),
            ("puppet_physics_assess", "Assess limits", self.assess_current),
        ):
            button = QPushButton(_tr(label_key, fallback))
            button.clicked.connect(slot)
            row.addWidget(button)
        right.addLayout(row)
        self.message = QLabel()
        self.message.setObjectName("physics_message")
        self.message.setWordWrap(True)
        right.addWidget(self.message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        return right

    # ---- chain list ------------------------------------------------------

    def _refresh_list(self, select: str | None = None) -> None:
        self.chains.clear()
        self.chains.addItems([rig.id for rig in self.working.physics_rigs])
        if self.chains.count():
            ids = [rig.id for rig in self.working.physics_rigs]
            self.chains.setCurrentRow(ids.index(select) if select in ids else 0)

    def current_rig(self) -> PhysicsRig | None:
        item = self.chains.currentItem()
        if item is None:
            return None
        return next((r for r in self.working.physics_rigs if r.id == item.text()), None)

    def _show_chain(self, _rig_id: str) -> None:
        rig = self.current_rig()
        if rig is None:
            return
        self._loading = True
        self.input_box.setCurrentText(rig.input_param)
        self.output_box.setCurrentText(rig.output_param)
        for box, value in zip(self.gravity, rig.gravity, strict=True):
            box.setValue(float(value))
        self.particle_count.setValue(len(rig.chain))
        self.table.setRowCount(len(rig.chain))
        for row, particle in enumerate(rig.chain):
            for column, name in enumerate(_COLUMNS):
                self.table.setItem(row, column, QTableWidgetItem(f"{getattr(particle, name):g}"))
        self._loading = False
        problems = validate_rig(self.working, rig) + rig_warnings(self.working, rig)
        self.message.setText("\n".join(problems))

    def _resize_table(self, count: int) -> None:
        if self._loading:
            return
        old = self.table.rowCount()
        self.table.setRowCount(count)
        for row in range(old, count):
            source = row - 1 if row else None
            for column in range(len(_COLUMNS)):
                text = self.table.item(source, column).text() if source is not None \
                    and self.table.item(source, column) else ("1", "0.7", "12")[column]
                self.table.setItem(row, column, QTableWidgetItem(text))

    def _chain_spec(self) -> list[dict]:
        spec = []
        for row in range(self.table.rowCount()):
            values = {}
            for column, name in enumerate(_COLUMNS):
                item = self.table.item(row, column)
                try:
                    values[name] = float(item.text()) if item else float("nan")
                except ValueError as exc:
                    raise ValueError(f"particle {row}: {name} must be a number") from exc
            spec.append(values)
        return spec

    # ---- actions -----------------------------------------------------------

    def store_current(self) -> bool:
        """Write the editor fields back into the selected working chain."""
        rig = self.current_rig()
        if rig is None:
            return False
        try:
            upsert_rig(self.working, rig.id, input_param=self.input_box.currentText(),
                       output_param=self.output_box.currentText(), chain=self._chain_spec(),
                       gravity=(self.gravity[0].value(), self.gravity[1].value()))
        except ValueError as exc:
            self.message.setText(str(exc))
            return False
        self.message.setText(_tr("puppet_physics_stored", "Chain updated."))
        return True

    def _new_chain(self) -> None:
        names = [p.id for p in self.working.parameters]
        taken = {r.output_param for r in self.working.physics_rigs}
        free = [n for n in names if n not in taken]
        if len(names) < 2 or not free:
            self.message.setText(_tr("puppet_physics_need_params",
                                     "Add an unused output parameter first."))
            return
        index = len(self.working.physics_rigs) + 1
        rig_id = f"chain{index}"
        while any(r.id == rig_id for r in self.working.physics_rigs):
            index += 1
            rig_id = f"chain{index}"
        source = next(n for n in names if n != free[0])
        upsert_rig(self.working, rig_id, input_param=source, output_param=free[0],
                   chain=self.presets.get("hair_short")["chain"])
        self._refresh_list(rig_id)

    def _delete_chain(self) -> None:
        rig = self.current_rig()
        if rig is not None:
            remove_rig(self.working, rig.id)
            self._refresh_list()

    def _apply_preset(self) -> None:
        rig = self.current_rig()
        if rig is None:
            return
        try:
            apply_preset(self.working, rig.id, self.presets.get(self.preset_box.currentText()))
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        self._show_chain(rig.id)

    def _save_preset(self) -> None:
        rig = self.current_rig()
        if rig is None or not self.store_current():
            return
        name, ok = QInputDialog.getText(self, _tr("puppet_physics_save_preset", "Save as preset…"),
                                        _tr("puppet_physics_preset_name", "Preset name:"))
        if ok:
            self.save_preset_as(name)

    def save_preset_as(self, name: str) -> bool:
        rig = self.current_rig()
        try:
            self.presets.save(name.strip(), rig_to_preset(rig))
        except ValueError as exc:
            self.message.setText(str(exc))
            return False
        self.preset_box.clear()
        self.preset_box.addItems(self.presets.names())
        self.preset_box.setCurrentText(name.strip())
        return True

    def assess_current(self) -> object:
        rig = self.current_rig()
        if rig is None or not self.store_current():
            return None
        result = assess_limits(self.working, rig.id)
        lines = [_tr("puppet_physics_assessment",
                     "Output {low:.2f}..{high:.2f}; clipped {clip:.0%} of frames.",
                     low=result.output_min, high=result.output_max,
                     clip=result.saturated_fraction)]
        lines += [_tr(f"puppet_physics_need_{need}", _NEED_FALLBACK[need]) for need in result.needs]
        if not result.needs:
            lines.append(_tr("puppet_physics_no_limit",
                             "No limit or collision needed for this chain."))
        self.message.setText("\n".join(lines))
        return result

    def _accept(self) -> None:
        if self.current_rig() is not None and not self.store_current():
            return
        self.accept()

    def result_rigs(self) -> list[PhysicsRig]:
        return deepcopy(self.working.physics_rigs)
