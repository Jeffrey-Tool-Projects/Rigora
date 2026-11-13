"""Export settings and job queue dialog (R3.5)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.document import PuppetDocument
from rigora.puppet.offline_export import (
    CONFLICTS,
    FORMATS,
    ExportSettings,
    encoder_capabilities,
    frame_times,
    validate_settings,
)


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


class ExportDialog(QDialog):
    """Pick a motion or composition, set the export, and watch the queue."""

    def __init__(self, parent: QWidget, document: PuppetDocument, queue,
                 enqueue) -> None:
        super().__init__(parent)
        self.document = document
        self.queue = queue
        self.enqueue = enqueue
        self.setWindowTitle(_tr("puppet_export_title", "Export animation"))
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.source = QComboBox()
        for motion in document.motions:
            self.source.addItem(_tr("puppet_export_motion", "Motion: {name}", name=motion.name),
                                ("motion", motion.name, motion.duration))
        for composition in document.compositions:
            self.source.addItem(_tr("puppet_export_composition", "Composition: {name}",
                                    name=composition.name),
                                ("composition", composition.name, composition.duration))
        self.source.currentIndexChanged.connect(self._source_changed)
        form.addRow(_tr("puppet_export_source", "Source"), self.source)
        self.width_box, self.height_box = QSpinBox(), QSpinBox()
        for box, value in ((self.width_box, 1024), (self.height_box, 1024)):
            box.setRange(16, 8192)
            box.setValue(value)
        size_row = QHBoxLayout()
        size_row.addWidget(self.width_box)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.height_box)
        form.addRow(_tr("puppet_export_size", "Size (px)"), size_row)
        self.fps = QDoubleSpinBox()
        self.fps.setRange(1, 240)
        self.fps.setValue(30)
        form.addRow(_tr("puppet_export_fps", "Frames per second"), self.fps)
        self.start, self.end = QDoubleSpinBox(), QDoubleSpinBox()
        for box in (self.start, self.end):
            box.setDecimals(3)
            box.setRange(0, 3600)
        range_row = QHBoxLayout()
        range_row.addWidget(self.start)
        range_row.addWidget(QLabel("–"))
        range_row.addWidget(self.end)
        form.addRow(_tr("puppet_export_range", "Range (s)"), range_row)
        self.transparent = QCheckBox(_tr("puppet_export_transparent", "Transparent background"))
        self.transparent.setChecked(True)
        form.addRow("", self.transparent)
        self.format = QComboBox()
        for name in FORMATS:
            self.format.addItem(name, name)
        self.format.currentIndexChanged.connect(self.refresh)
        form.addRow(_tr("puppet_export_format", "Format"), self.format)
        self.capability = QLabel()
        self.capability.setWordWrap(True)
        form.addRow("", self.capability)
        self.conflict = QComboBox()
        for name in CONFLICTS:
            self.conflict.addItem(_tr(f"puppet_export_conflict_{name}", name), name)
        form.addRow(_tr("puppet_export_conflict", "If the file exists"), self.conflict)
        self.warmup = QDoubleSpinBox()
        self.warmup.setRange(0, 30)
        self.warmup.setValue(1.0)
        form.addRow(_tr("puppet_export_warmup", "Physics warm-up (s)"), self.warmup)
        self.audio = QCheckBox(_tr("puppet_export_audio", "Include the motion's sound (video)"))
        self.audio.setChecked(True)
        form.addRow("", self.audio)
        target_row = QHBoxLayout()
        self.target = QLineEdit()
        browse = QPushButton(_tr("puppet_export_browse", "Browse…"))
        browse.clicked.connect(self._browse)
        target_row.addWidget(self.target, 1)
        target_row.addWidget(browse)
        form.addRow(_tr("puppet_export_target", "Save to"), target_row)
        layout.addLayout(form)
        self.summary = QLabel()
        self.summary.setObjectName("export_summary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        add = QPushButton(_tr("puppet_export_add", "Add to queue"))
        add.clicked.connect(self.add_job)
        layout.addWidget(add)
        self.jobs = QTableWidget(0, 4)
        self.jobs.setObjectName("export_jobs")
        self.jobs.setHorizontalHeaderLabels([
            _tr("puppet_export_col_job", "Export"), _tr("puppet_export_col_state", "State"),
            _tr("puppet_export_col_progress", "Frames"), _tr("puppet_export_col_detail", "Detail")])
        self.jobs.horizontalHeader().setStretchLastSection(True)
        self.jobs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.jobs, 1)
        row = QHBoxLayout()
        for key, fallback, slot in (("puppet_export_cancel", "Cancel export", self._cancel),
                                    ("puppet_export_retry", "Retry", self._retry)):
            button = QPushButton(_tr(key, fallback))
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        close = QPushButton(_tr("close", "Close"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh_jobs)
        self._timer.start()
        for box in (self.width_box, self.height_box, self.fps, self.start, self.end):
            box.valueChanged.connect(self.refresh)
        self.transparent.toggled.connect(self.refresh)
        self._source_changed()

    def _source_changed(self) -> None:
        data = self.source.currentData()
        if data is not None:
            self.end.setValue(float(data[2]))
            if not self.target.text():
                self.target.setText(str(Path.home() / f"{data[1]}"))
        self.refresh()

    def settings(self) -> ExportSettings:
        background = (0.0, 0.0, 0.0, 0.0) if self.transparent.isChecked() else (1, 1, 1, 1)
        return ExportSettings(
            width=self.width_box.value(), height=self.height_box.value(),
            fps=self.fps.value(), start=self.start.value(), end=self.end.value(),
            background=background, format=self.format.currentData(),
            conflict=self.conflict.currentData(), physics_warmup=self.warmup.value(),
            include_audio=self.audio.isChecked())

    def refresh(self) -> list[str]:
        data = self.source.currentData()
        if data is None:
            self.summary.setText(_tr("puppet_export_no_source",
                                     "Add a motion or composition first."))
            return ["no source"]
        capability = encoder_capabilities()[self.format.currentData()]
        self.capability.setText(_tr(
            "puppet_export_capability", "Transparency: {alpha}. Encoder installed: {ok}.",
            alpha=capability["alpha"], ok=_tr("puppet_export_yes", "yes") if capability["available"]
            else _tr("puppet_export_no", "no")))
        settings = self.settings()
        problems = validate_settings(settings, float(data[2]))
        if problems:
            self.summary.setText("\n".join(problems))
        else:
            frames = len(frame_times(settings, float(data[2])))
            self.summary.setText(_tr("puppet_export_plan", "{frames} frames at {fps:g} fps.",
                                     frames=frames, fps=settings.fps))
        return problems

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, _tr("puppet_export_target", "Save to"),
                                              self.target.text())
        if path:
            self.target.setText(path)

    def add_job(self):
        data = self.source.currentData()
        if data is None or self.refresh() or not self.target.text().strip():
            return None
        job = self.enqueue(data[0], data[1], self.settings(), Path(self.target.text().strip()))
        self.refresh_jobs()
        return job

    def refresh_jobs(self) -> None:
        jobs = self.queue.jobs
        self.jobs.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            detail = job.error or "; ".join(job.notes) or (str(job.output) if job.output else "")
            values = (job.label(), _tr(f"puppet_export_state_{job.state}", job.state),
                      f"{job.progress}/{job.total or '?'}", detail)
            for column, value in enumerate(values):
                self.jobs.setItem(row, column, QTableWidgetItem(value))

    def _selected_job(self):
        row = self.jobs.currentRow()
        return self.queue.jobs[row] if 0 <= row < len(self.queue.jobs) else None

    def _cancel(self) -> None:
        job = self._selected_job()
        if job is not None:
            self.queue.cancel(job.id)

    def _retry(self) -> None:
        job = self._selected_job()
        if job is not None:
            try:
                self.queue.retry(job.id)
            except ValueError as exc:
                self.summary.setText(str(exc))
