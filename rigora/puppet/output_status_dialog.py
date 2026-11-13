"""Live output and device status (R4.3 / R4.4 / R4.5)."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from rigora.i18n.language_wrapper import language_wrapper

REFRESH_MS = 500
_KINDS = {"virtual_camera": ("puppet_virtual_camera", "Virtual camera"),
          "ndi": ("puppet_ndi_output", "NDI output"),
          "vts_api": ("puppet_vts_api", "VTS API")}


def _tr(key: str, fallback: str) -> str:
    return language_wrapper.language_word_dict.get(key, fallback)


def output_row(stats: dict) -> list[str]:
    key, fallback = _KINDS.get(stats.get("kind", ""), ("", stats.get("kind", "")))
    size = (f"{stats['width']}×{stats['height']}" if stats.get("width") else "—")
    fps = (f"{stats.get('measured_fps', 0):.1f} / {stats.get('target_fps', 0):.0f}"
           if "target_fps" in stats else "—")
    state = _tr("puppet_output_connected", "Connected") if stats.get("connected") else \
        _tr("puppet_output_stopped", "Stopped")
    receivers = stats.get("receivers")
    if receivers is not None:
        state += f" · {receivers}"
    return [_tr(key, fallback) if key else fallback, stats.get("source_name") or "—", size, fps,
            str(stats.get("dropped", "—")), state, stats.get("last_error") or ""]


def device_rows(report: dict) -> list[list[str]]:
    rows = []
    for name, key, fallback in (("camera", "puppet_input_camera", "Camera"),
                                ("microphone", "puppet_input_microphone", "Microphone")):
        item = report.get(name, {})
        recovery = item.get("recovery", {})
        state = item.get("phase", "")
        if recovery.get("state") == "waiting_retry":
            state += " · " + _tr("puppet_device_retry_in", "retry in {seconds}s").format(
                seconds=recovery.get("next_retry_in"))
        rows.append([_tr(key, fallback), str(item.get("device", "")) or "—", "", "", "", state,
                     item.get("detail", "") or recovery.get("reason", "")])
    return rows


class OutputStatusDialog(QDialog):
    def __init__(self, outputs, devices, revoke, retry, parent=None) -> None:
        super().__init__(parent)
        self._outputs, self._devices = outputs, devices
        self.setWindowTitle(_tr("puppet_output_status_title", "Live Status"))
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels([
            _tr("puppet_output_col_kind", "Output / device"),
            _tr("puppet_output_col_source", "Source name"),
            _tr("puppet_output_col_size", "Resolution"),
            _tr("puppet_output_col_fps", "FPS (actual / target)"),
            _tr("puppet_output_col_dropped", "Dropped"),
            _tr("puppet_output_col_state", "State"),
            _tr("puppet_output_col_error", "Last error")])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        revoke_button = QPushButton(_tr("puppet_vts_revoke", "Revoke plug-in access"))
        revoke_button.clicked.connect(lambda: (revoke(), self.refresh()))
        retry_button = QPushButton(_tr("puppet_device_retry", "Retry devices"))
        retry_button.clicked.connect(lambda: (retry(), self.refresh()))
        buttons = QHBoxLayout()
        buttons.addWidget(retry_button)
        buttons.addWidget(revoke_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addLayout(buttons)
        self.resize(820, 260)
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

    def rows(self) -> list[list[str]]:
        return [output_row(s) for s in self._outputs()] + device_rows(self._devices())

    def refresh(self) -> None:
        rows = self.rows()
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                self._table.setItem(r, c, QTableWidgetItem(text))
