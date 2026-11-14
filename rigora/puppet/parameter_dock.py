"""Parameter slider dock for the Puppet workspace.

One row per parameter: label + horizontal QSlider + numeric label.
Slider drag pushes a float into the bound canvas via
``set_parameter_value``. The dock listens to the canvas's
``parameters_changed`` signal so the next document load (or a
``reset_parameters`` call) repopulates / re-syncs the sliders without
the workspace having to wire that up.

Rows are grouped (Head, Eyes, Mouth, Body, Hair, Other) by the Cubism
naming of their ids and can be filtered by id or display name. Each row's
menu edits the parameter's range and previews its key forms by moving the
slider to each key's value.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.rig_hierarchy import grouped_parameters, key_summary
from rigora.system.ui_scale import scaled_px
from rigora.puppet.input_arbitration import submit_values

if TYPE_CHECKING:
    from rigora.puppet.canvas import PuppetCanvas
    from rigora.puppet.document import Parameter


# How many integer steps each slider holds — finer than the slider's
# default 100 so warps and rotations feel smooth.
_SLIDER_STEPS: int = 1000
_GROUP_FALLBACK = {"Head": "Head", "Eyes": "Eyes", "Mouth": "Mouth", "Body": "Body",
                   "Hair": "Hair", "Other": "Other"}


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


class ParameterDock(QDockWidget):
    """Right-dockable panel with one slider per parameter."""

    value_changed = Signal(str, float)
    """Emitted when the user moves a slider — ``(param_id, value)``.

    The dock also pushes into the bound canvas directly so consumers
    who only care about the rendered output don't need to subscribe.
    """

    def __init__(self, canvas: PuppetCanvas, parent=None, *, workspace=None):
        super().__init__(_tr("puppet_parameters_dock", "Parameters"), parent)
        self._canvas = canvas
        self._workspace = workspace
        self._sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}
        self._group_labels: dict[str, QLabel] = {}
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(8, 8, 8, 0)
        self._search = QLineEdit()
        self._search.setPlaceholderText(_tr("puppet_parameter_search", "Filter parameters…"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _text: self._rebuild_from_canvas())
        outer_layout.addWidget(self._search)
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(0, 0, 0, 8)
        self._layout.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidget(self._inner)
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)
        self.setWidget(outer)

        canvas.parameters_changed.connect(self._rebuild_from_canvas)
        canvas.document_loaded.connect(self._rebuild_from_canvas)
        self._rebuild_from_canvas()

    # ---- public ---------------------------------------------------------

    def slider_for(self, param_id: str) -> QSlider | None:
        return self._sliders.get(param_id)

    def set_filter(self, text: str) -> None:
        self._search.setText(text)

    def group_names(self) -> list[str]:
        return list(self._group_labels)

    def preview_key(self, param_id: str, value: float) -> None:
        """Show a key form by moving the parameter to the key's value."""
        submit_values(self._canvas, "manual", {param_id: value}, force=True)
        self.value_changed.emit(param_id, value)

    # ---- rebuild --------------------------------------------------------

    def _rebuild_from_canvas(self) -> None:
        document = self._canvas.document()
        self._clear_rows()
        if document is None or not document.parameters:
            self._layout.addWidget(self._build_empty_state())
            return
        values = self._canvas.parameter_values()
        groups = grouped_parameters(document, self._search.text())
        for group, ids in groups.items():
            heading = QLabel(_tr(f"puppet_parameter_group_{group.lower()}",
                                 _GROUP_FALLBACK[group]))
            heading.setStyleSheet("font-weight: bold; padding-top: 4px;")
            self._group_labels[group] = heading
            self._layout.addWidget(heading)
            for param_id in ids:
                param = document.parameter(param_id)
                row, slider, value_label = self._build_row(
                    param, values.get(param.id, param.default),
                )
                self._sliders[param.id] = slider
                self._value_labels[param.id] = value_label
                self._layout.addWidget(row)
        if not groups:
            self._layout.addWidget(QLabel(_tr("puppet_parameter_no_match",
                                              "No parameter matches the filter.")))
        self._layout.addWidget(self._build_reset_button())
        self._layout.addStretch(1)

    def _clear_rows(self) -> None:
        self._sliders.clear()
        self._value_labels.clear()
        self._group_labels.clear()
        # Walk in reverse so widget removal doesn't shift indices.
        for i in range(self._layout.count() - 1, -1, -1):
            item = self._layout.takeAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _build_empty_state(self) -> QLabel:
        label = QLabel(_tr(
            "puppet_parameters_empty",
            "No parameters yet — load a puppet with parameters to see sliders here.",
        ))
        label.setWordWrap(True)
        label.setStyleSheet("color: #888; padding: 8px;")
        return label

    def _build_row(
        self, param: Parameter, value: float,
    ) -> tuple[QWidget, QSlider, QLabel]:
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(scaled_px(4))
        row.setMinimumWidth(scaled_px(240))
        heading = QHBoxLayout()
        row_layout.addLayout(heading)

        document = self._canvas.document()
        display = document.display_names.get(param.id) if document is not None else None
        name = QLabel(f"{display} ({param.id})" if display else param.id)
        name.setWordWrap(True)
        heading.addWidget(name, 1)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, _SLIDER_STEPS)
        slider.setValue(_value_to_step(param, value))
        slider.setToolTip(_tr(
            "puppet_parameter_range_tip", "{name}: adjust from {minimum} to {maximum}.",
            name=param.id, minimum=param.min, maximum=param.max))
        slider.valueChanged.connect(
            lambda step, p=param: self._on_slider_changed(p, step),
        )
        slider.setAccessibleName(param.id)
        row_layout.addWidget(slider)

        value_label = QLabel(_format_value(value))
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        heading.addWidget(value_label)

        if self._workspace is not None:
            set_key_btn = QPushButton(_tr("puppet_set_key", "Set key"))
            set_key_btn.setToolTip(_tr(
                "puppet_set_key_tip",
                "Snapshot current deformer forms as a key on this parameter"))
            set_key_btn.clicked.connect(
                lambda _checked=False, p=param: self._set_key(p),
            )
            heading.addWidget(set_key_btn)
        heading.addWidget(self._build_row_menu(param))
        return row, slider, value_label

    def _build_row_menu(self, param: Parameter) -> QToolButton:
        button = QToolButton()
        button.setText("⋯")
        button.setAccessibleName(_tr("puppet_parameter_menu", "Parameter options"))
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        if self._workspace is not None:
            menu.addAction(_tr("puppet_parameter_edit_range", "Edit range…"),
                           lambda p=param.id: self._workspace.edit_parameter_range_via_dialog(p))
        document = self._canvas.document()
        keys = key_summary(document, param.id) if document is not None else []
        preview = menu.addMenu(_tr("puppet_parameter_preview_keys", "Preview key forms"))
        preview.setEnabled(bool(keys))
        for key in keys:
            label = _tr("puppet_parameter_key_label", "{value} — {deformers}",
                        value=_format_value(key.value),
                        deformers=", ".join(key.deformers) or "—")
            preview.addAction(label, lambda p=param.id, v=key.value: self.preview_key(p, v))
        button.setMenu(menu)
        return button

    def _set_key(self, param: Parameter) -> None:
        if self._workspace is None:
            return
        self._workspace.set_key_at_current_slider(param.id)

    def _build_reset_button(self) -> QPushButton:
        btn = QPushButton(_tr("puppet_parameters_reset", "Reset all"))
        btn.clicked.connect(self._reset_all)
        return btn

    # ---- slots ----------------------------------------------------------

    def _on_slider_changed(self, param: Parameter, step: int) -> None:
        value = _step_to_value(param, step)
        self._value_labels[param.id].setText(_format_value(value))
        submit_values(self._canvas, "manual", {param.id: value}, force=True)
        self.value_changed.emit(param.id, value)

    def _reset_all(self) -> None:
        self._canvas.reset_parameters()
        # The canvas emits parameters_changed → rebuild syncs sliders.


def _value_to_step(param: Parameter, value: float) -> int:
    span = param.max - param.min
    if span <= 0:
        return 0
    norm = (float(value) - param.min) / span
    return max(0, min(_SLIDER_STEPS, int(round(norm * _SLIDER_STEPS))))


def _step_to_value(param: Parameter, step: int) -> float:
    if _SLIDER_STEPS == 0:
        return param.min
    norm = step / _SLIDER_STEPS
    return param.min + (param.max - param.min) * norm


def _format_value(value: float) -> str:
    return f"{value:.2f}"
