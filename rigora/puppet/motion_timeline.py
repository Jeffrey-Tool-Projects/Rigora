"""Motion timeline editor — graph view of one :class:`MotionTrack`'s
curve with draggable endpoint and bezier-handle markers.

Far from Cubism Editor's full timeline, but covers the common workflow:
pick a track, see the curve, drag a point to tweak it. The widget is
self-contained QGraphicsView + QGraphicsItems so the workspace can
either embed it inline or wrap it in a dialog (we ship the dialog
form).

Pure-Qt — no GL — so the headless test suite can drive it under
``qapp`` and assert that a dragged handle ends up writing to the
correct segment field.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from rigora.system.qt_timers import call_later
from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.document import MotionTrack
from rigora.puppet.easing import EASING_NAMES, ease_track
from rigora.puppet.motion_compress import compress_track, count_keys
from rigora.puppet.motion_keys import (
    TANGENT_MODES,
    KeyClip,
    copy_keys,
    filter_tracks,
    move_keys,
    paste_keys,
    scale_keys,
    set_tangents,
    snap_time,
)

if TYPE_CHECKING:
    from rigora.puppet.document import Motion


# Scene units are pixels at zoom = 1; the view auto-fits on first show.
_SCENE_WIDTH: float = 800.0
_SCENE_HEIGHT: float = 240.0
_MARGIN: float = 20.0
_ENDPOINT_RADIUS: float = 5.0
_CONTROL_RADIUS: float = 3.5


class MotionTimelineWidget(QGraphicsView):
    """Graph view of one :class:`MotionTrack`'s curve.

    Each segment endpoint (``p1``) is a draggable circle; cubic-bezier
    segments also expose their ``c0`` and ``c1`` as smaller handles.
    Mouse drag updates the underlying segment in place and emits
    :attr:`track_modified` so the workspace can refresh the player
    or persist the change.

    Value-axis range is taken from the bound parameter when the
    workspace passes one in; otherwise we use a symmetric ``[-1, 1]``
    range which matches every Cubism-style parameter we ship."""

    track_modified = Signal()
    edit_started = Signal()
    edit_finished = Signal()

    def mousePressEvent(self, event):
        self.edit_started.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        call_later(0, self, self.edit_finished.emit)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(self.renderHints())
        # Dragging empty space draws a rubber band that selects keys.
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setBackgroundBrush(QBrush(QColor(35, 35, 40)))
        self._selection: set[int] = set()
        self._waveform: list[tuple[float, float]] = []
        self._waveform_seconds = 0.0
        self.snap_step: float | None = None
        self._scene.selectionChanged.connect(self._remember_selection)
        self._motion: Motion | None = None
        self._track: MotionTrack | None = None
        self._duration: float = 1.0
        self._value_min: float = -1.0
        self._value_max: float = 1.0

    def set_track(
        self,
        motion: Motion | None,
        track: MotionTrack | None,
        *,
        value_min: float = -1.0,
        value_max: float = 1.0,
    ) -> None:
        self._motion = motion
        self._track = track
        self._duration = float(motion.duration) if motion is not None else 1.0
        self._value_min = float(value_min)
        self._value_max = float(value_max)
        self._rebuild()

    def motion(self) -> Motion | None:
        return self._motion

    def track(self) -> MotionTrack | None:
        return self._track

    def set_waveform(self, peaks: list[tuple[float, float]], seconds: float) -> None:
        """Draw the motion's sound under the curve, on the motion's time axis."""
        self._waveform = list(peaks)
        self._waveform_seconds = float(seconds)
        self._rebuild()

    def waveform_item_count(self) -> int:
        return len(self._waveform)

    def selected_keys(self) -> list[int]:
        return sorted(self._selection)

    def select_keys(self, indices) -> None:
        wanted = set(indices)
        self._rebuilding = True       # each setSelected fires selectionChanged
        try:
            for item in self._scene.items():
                if isinstance(item, _EndpointHandle):
                    item.setSelected(item.key_index in wanted)
        finally:
            self._rebuilding = False
        self._selection = wanted

    def _remember_selection(self) -> None:
        if getattr(self, "_rebuilding", False):
            return
        self._selection = {item.key_index for item in self._scene.selectedItems()
                           if isinstance(item, _EndpointHandle)}

    # ---- rebuild --------------------------------------------------------

    def _rebuild(self) -> None:
        self._rebuilding = True
        try:
            self._scene.clear()
            self._scene.setSceneRect(0.0, 0.0, _SCENE_WIDTH, _SCENE_HEIGHT)
            self._draw_grid()
            if self._track is not None:
                self._draw_segments()
        finally:
            self._rebuilding = False
        self.select_keys(self._selection)

    def _draw_grid(self) -> None:
        pen = QPen(QColor(60, 60, 70))
        # Horizontal grid line at value = 0.
        zero_y = self._value_to_y(0.0)
        self._scene.addLine(_MARGIN, zero_y, _SCENE_WIDTH - _MARGIN, zero_y, pen)
        self._draw_waveform()
        # Border frame.
        frame = QPen(QColor(80, 80, 95))
        self._scene.addRect(
            QRectF(
                _MARGIN, _MARGIN,
                _SCENE_WIDTH - 2 * _MARGIN, _SCENE_HEIGHT - 2 * _MARGIN,
            ),
            frame,
        )

    def _draw_waveform(self) -> None:
        if not self._waveform or self._waveform_seconds <= 0:
            return
        pen = QPen(QColor(70, 110, 90))
        middle = _SCENE_HEIGHT / 2.0
        half = (_SCENE_HEIGHT - 2 * _MARGIN) / 2.0
        step = self._waveform_seconds / len(self._waveform)
        for index, (low, high) in enumerate(self._waveform):
            t = index * step
            if t > self._duration:
                break
            x = self._time_to_x(t)
            self._scene.addLine(x, middle - high * half, x, middle - low * half, pen)

    def _draw_segments(self) -> None:
        # _rebuild() gates on ``self._track is None`` before calling this,
        # so the early-return keeps the runtime defined on the ``-O`` path
        # (which strips asserts) without a NotImplementedError surface.
        if self._track is None:
            return
        curve_pen = QPen(QColor(150, 200, 255), 2)
        ctrl_pen = QPen(QColor(160, 120, 200), 1, Qt.PenStyle.DashLine)
        for index, segment in enumerate(self._track.segments):
            p0 = self._scene_point(*segment.p0)
            p1 = self._scene_point(*segment.p1)
            self._scene.addLine(QGraphicsLineItem(p0.x(), p0.y(), p1.x(), p1.y()).line(), curve_pen)
            if segment.type == "cubic-bezier" and segment.c0 and segment.c1:
                c0 = self._scene_point(*segment.c0)
                c1 = self._scene_point(*segment.c1)
                # Dashed lines from endpoints to control handles.
                self._scene.addLine(p0.x(), p0.y(), c0.x(), c0.y(), ctrl_pen)
                self._scene.addLine(p1.x(), p1.y(), c1.x(), c1.y(), ctrl_pen)
                self._scene.addItem(_ControlHandle(
                    self, segment_index=index, field="c0",
                    center=c0, color=QColor(220, 150, 220),
                ))
                self._scene.addItem(_ControlHandle(
                    self, segment_index=index, field="c1",
                    center=c1, color=QColor(220, 150, 220),
                ))
            # p1 endpoint handle. The first segment's p0 is the curve's
            # absolute start; subsequent segments share p0 with the
            # previous p1, so we only render p1 to avoid stacking.
            self._scene.addItem(_EndpointHandle(
                self, segment_index=index, center=p1,
            ))
        # Render the very first p0 too so the user can drag the start.
        if self._track.segments:
            start = self._scene_point(*self._track.segments[0].p0)
            self._scene.addItem(_EndpointHandle(
                self, segment_index=0, center=start, is_start=True,
            ))

    # ---- coordinate mapping --------------------------------------------

    def _scene_point(self, t: float, v: float) -> QPointF:
        return QPointF(self._time_to_x(t), self._value_to_y(v))

    def scene_to_track(self, point: QPointF) -> tuple[float, float]:
        return self._x_to_time(point.x()), self._y_to_value(point.y())

    def _time_to_x(self, t: float) -> float:
        usable = _SCENE_WIDTH - 2 * _MARGIN
        if self._duration <= 0:
            return _MARGIN
        return _MARGIN + (t / self._duration) * usable

    def _x_to_time(self, x: float) -> float:
        usable = _SCENE_WIDTH - 2 * _MARGIN
        if usable <= 0:
            return 0.0
        return max(0.0, min(self._duration, (x - _MARGIN) / usable * self._duration))

    def _value_to_y(self, v: float) -> float:
        usable = _SCENE_HEIGHT - 2 * _MARGIN
        span = self._value_max - self._value_min
        if span <= 0:
            return _SCENE_HEIGHT / 2.0
        # Y axis is inverted so higher values render upward.
        norm = (v - self._value_min) / span
        return _SCENE_HEIGHT - _MARGIN - norm * usable

    def _y_to_value(self, y: float) -> float:
        usable = _SCENE_HEIGHT - 2 * _MARGIN
        if usable <= 0:
            return self._value_min
        norm = (_SCENE_HEIGHT - _MARGIN - y) / usable
        return self._value_min + norm * (self._value_max - self._value_min)

    # ---- mutation -------------------------------------------------------

    def update_endpoint(
        self, segment_index: int, point: QPointF, *, is_start: bool = False,
    ) -> None:
        if self._track is None:
            return
        if not 0 <= segment_index < len(self._track.segments):
            return
        t, v = self.scene_to_track(point)
        t = snap_time(t, self.snap_step)
        segment = self._track.segments[segment_index]
        if is_start:
            segment.p0 = (t, v)
        else:
            segment.p1 = (t, v)
            # Keep the following segment's p0 in sync — Cubism's contract
            # is that segment[i].p1 == segment[i+1].p0.
            if segment_index + 1 < len(self._track.segments):
                self._track.segments[segment_index + 1].p0 = (t, v)
        self._rebuild()
        self.track_modified.emit()

    def update_control(
        self, segment_index: int, field: str, point: QPointF,
    ) -> None:
        if self._track is None or field not in ("c0", "c1"):
            return
        if not 0 <= segment_index < len(self._track.segments):
            return
        t, v = self.scene_to_track(point)
        segment = self._track.segments[segment_index]
        if field == "c0":
            segment.c0 = (t, v)
        else:
            segment.c1 = (t, v)
        self._rebuild()
        self.track_modified.emit()


# ---------------------------------------------------------------------------
# Handle items
# ---------------------------------------------------------------------------


class _EndpointHandle(QGraphicsEllipseItem):
    def __init__(
        self,
        view: MotionTimelineWidget,
        *,
        segment_index: int,
        center: QPointF,
        is_start: bool = False,
    ):
        super().__init__(
            -_ENDPOINT_RADIUS, -_ENDPOINT_RADIUS,
            _ENDPOINT_RADIUS * 2, _ENDPOINT_RADIUS * 2,
        )
        self.setBrush(QBrush(QColor(240, 220, 120)))
        self.setPen(QPen(QColor(60, 60, 60)))
        self.setPos(center)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges, True)
        self.setZValue(2.0)
        self._view = view
        self._segment_index = segment_index
        self._is_start = is_start
        self.key_index = 0 if is_start else segment_index + 1

    def itemChange(self, change, value):  # type: ignore[override]
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # Defer the model update: it rebuilds the scene, which deletes THIS
            # handle — doing it synchronously would return into super().itemChange
            # on a freed C++ object. singleShot(0) runs it after we return.
            from PySide6.QtCore import QPointF
            seg, is_start, pos = self._segment_index, self._is_start, QPointF(value)
            view = self._view
            track = view.track()
            call_later(0, view, lambda: (
                view.update_endpoint(seg, pos, is_start=is_start) if view.track() is track else None
            ))
        return super().itemChange(change, value)


class _ControlHandle(QGraphicsEllipseItem):
    def __init__(
        self,
        view: MotionTimelineWidget,
        *,
        segment_index: int,
        field: str,
        center: QPointF,
        color: QColor,
    ):
        super().__init__(
            -_CONTROL_RADIUS, -_CONTROL_RADIUS,
            _CONTROL_RADIUS * 2, _CONTROL_RADIUS * 2,
        )
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(60, 60, 60)))
        self.setPos(center)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges, True)
        self.setZValue(2.5)
        self._view = view
        self._segment_index = segment_index
        self._field = field

    def itemChange(self, change, value):  # type: ignore[override]
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # Defer the rebuild — see _EndpointHandle.itemChange (it deletes this
            # handle, so a synchronous call is a use-after-free).
            from PySide6.QtCore import QPointF
            seg, field, pos = self._segment_index, self._field, QPointF(value)
            view, track = self._view, self._view.track()
            call_later(0, view, lambda: (
                view.update_control(seg, field, pos) if view.track() is track else None
            ))
        return super().itemChange(change, value)


# ---------------------------------------------------------------------------
# Dialog wrapper
# ---------------------------------------------------------------------------


class MotionTimelineDialog(QDialog):
    """Modal-ish dialog wrapping a :class:`MotionTimelineWidget` with a
    track picker. The workspace hands it the active motion; the user
    picks one of the motion's tracks and edits the curve in place.

    ``ranges`` maps a parameter id to its ``(min, max)``; a track's value
    axis spans that range (a Cubism head angle runs −30…30), and −1…1
    for a parameter it doesn't list or an empty range.

    Under the graph, **Ease** reshapes every segment of the shown track to a
    named easing (:meth:`apply_easing`) and **Simplify Keys** drops the keys
    of every track that sit within a tolerance — a percentage of each
    parameter's range — of the line through their neighbours
    (:meth:`simplify_keys`); recorded motions carry one key per frame.
    """

    def __init__(
        self, motion: Motion, parent=None, *,
        ranges: dict[str, tuple[float, float]] | None = None,
    ):
        lang = language_wrapper.language_word_dict
        super().__init__(parent)
        self.setWindowTitle(
            lang.get("puppet_timeline_title", "Edit motion timeline"),
        )
        self.setMinimumSize(880, 380)
        layout = QVBoxLayout(self)

        picker_row = QHBoxLayout()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(lang.get("puppet_timeline_filter", "Filter tracks…"))
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self.set_track_filter)
        picker_row.addWidget(self._filter)
        picker_row.addWidget(QLabel(
            lang.get("puppet_timeline_track", "Track:"),
        ))
        self._track_picker = QComboBox()
        for track in motion.tracks:
            self._track_picker.addItem(track.param_id, track.param_id)
        self._track_picker.currentIndexChanged.connect(self._on_track_changed)
        picker_row.addWidget(self._track_picker, stretch=1)
        layout.addLayout(picker_row)
        self._clip: KeyClip | None = None

        self._view = MotionTimelineWidget()
        layout.addWidget(self._view, stretch=1)

        self._motion = motion
        self._ranges = dict(ranges or {})
        self._load_waveform()
        layout.addLayout(self._build_tools_row())
        layout.addLayout(self._build_key_row())
        if motion.tracks:
            self._on_track_changed(0)

    def widget(self) -> MotionTimelineWidget:
        return self._view

    def apply_easing(self, name: str) -> bool:
        """Reshape every segment of the shown track to the easing *name*; False with no track."""
        track = self._view.track()
        if track is None or not track.segments:
            return False
        track.segments[:] = ease_track(track, name).segments
        self._show_track(track)
        self._view.track_modified.emit()
        return True

    def simplify_keys(self, percent: float) -> tuple[int, int]:
        """Drop redundant keys from every track; returns the key count ``(before, after)``.

        A key goes when the curve without it stays within *percent* of the
        parameter's range of the original everywhere.
        """
        before = self.key_count()
        for track in self._motion.tracks:
            low, high = self._range_of(track.param_id)
            tol = max(0.0, float(percent)) / 100.0 * (high - low)
            track.segments[:] = compress_track(track, tol=tol).segments
        after = self.key_count()
        current = self._view.track()
        if current is not None:
            self._show_track(current)
        self._show_key_count(before, after)
        if after != before:
            self._view.track_modified.emit()
        return before, after

    def key_count(self) -> int:
        """Keys across all of the motion's tracks."""
        return sum(count_keys(track) for track in self._motion.tracks)

    def _build_tools_row(self) -> QHBoxLayout:
        lang = language_wrapper.language_word_dict
        row = QHBoxLayout()
        row.addWidget(QLabel(lang.get("puppet_timeline_ease", "Ease:")))
        self._ease_box = QComboBox()
        self._ease_box.addItems(EASING_NAMES)
        self._ease_box.setCurrentText("ease-in-out-sine")
        row.addWidget(self._ease_box)
        apply_ease = QPushButton(lang.get("puppet_timeline_apply_ease", "Apply to Track"))
        apply_ease.setToolTip(lang.get(
            "puppet_timeline_apply_ease_tooltip",
            "Reshape every segment of this track to the chosen easing, keeping its keys"))
        apply_ease.clicked.connect(lambda: self.apply_easing(self._ease_box.currentText()))
        row.addWidget(apply_ease)
        row.addStretch(1)
        row.addWidget(QLabel(lang.get("puppet_timeline_tolerance", "Tolerance:")))
        self._tolerance = QDoubleSpinBox()
        self._tolerance.setRange(0.0, 25.0)
        self._tolerance.setSingleStep(0.5)
        self._tolerance.setValue(1.0)
        self._tolerance.setSuffix(" %")
        row.addWidget(self._tolerance)
        simplify = QPushButton(lang.get("puppet_timeline_simplify", "Simplify Keys"))
        simplify.setToolTip(lang.get(
            "puppet_timeline_simplify_tooltip",
            "Drop the keys of every track that sit within the tolerance (a share of the "
            "parameter's range) of the line through their neighbours"))
        simplify.clicked.connect(lambda: self.simplify_keys(self._tolerance.value()))
        row.addWidget(simplify)
        self._keys_label = QLabel()
        row.addWidget(self._keys_label)
        self._show_key_count(self.key_count())
        return row

    def _show_key_count(self, before: int, after: int | None = None) -> None:
        lang = language_wrapper.language_word_dict
        if after is None:
            text = lang.get("puppet_timeline_keys", "{count} keys").format(count=before)
        else:
            text = lang.get("puppet_timeline_keys_simplified", "{before} → {after} keys").format(
                before=before, after=after)
        self._keys_label.setText(text)

    def _range_of(self, param_id: str) -> tuple[float, float]:
        low, high = self._ranges.get(param_id, (-1.0, 1.0))
        return (low, high) if high > low else (-1.0, 1.0)

    def _show_track(self, track: MotionTrack) -> None:
        low, high = self._range_of(track.param_id)
        self._view.set_track(self._motion, track, value_min=low, value_max=high)

    def _on_track_changed(self, index: int) -> None:
        param_id = self._track_picker.itemData(index)
        track = next((t for t in self._motion.tracks if t.param_id == param_id), None)
        if track is None:
            self._view.set_track(None, None)
            return
        self._view.select_keys(())
        self._show_track(track)

    # ---- key operations (R3.1) ----------------------------------------------

    def set_track_filter(self, text: str) -> None:
        """Show only tracks whose parameter id contains ``text``."""
        current = self._track_picker.currentData()
        self._track_picker.blockSignals(True)
        self._track_picker.clear()
        for track in filter_tracks(self._motion, text):
            self._track_picker.addItem(track.param_id, track.param_id)
        self._track_picker.blockSignals(False)
        index = self._track_picker.findData(current)
        self._track_picker.setCurrentIndex(max(index, 0))
        self._on_track_changed(self._track_picker.currentIndex())

    def select_track(self, param_id: str) -> bool:
        index = self._track_picker.findData(param_id)
        if index < 0:
            return False
        self._track_picker.setCurrentIndex(index)
        self._on_track_changed(index)
        return True

    def track_ids(self) -> list[str]:
        return [self._track_picker.itemData(i) for i in range(self._track_picker.count())]

    def _load_waveform(self) -> None:
        """Show the motion's sound under its curves; a missing or unreadable file
        is noted instead (the motion still plays, silently)."""
        self.sound_note = ""
        if not self._motion.sound_path:
            return
        import wave

        from rigora.puppet.audio_lipsync import waveform_peaks
        try:
            peaks, seconds = waveform_peaks(self._motion.sound_path)
        except (OSError, EOFError, ValueError, wave.Error) as exc:
            self.sound_note = language_wrapper.language_word_dict.get(
                "puppet_timeline_sound_missing",
                "Sound unavailable ({error}); relink it from the File menu.").format(error=exc)
            return
        self._view.set_waveform(peaks, seconds)

    def set_snap(self, step: float | None) -> None:
        self._view.snap_step = step

    def _key_edit(self, operation) -> bool:
        """Run one key operation on the shown track as one recorded edit."""
        track = self._view.track()
        if track is None:
            return False
        try:
            result = operation(track)
        except ValueError as exc:
            self._key_status.setText(str(exc))
            return False
        if result == []:
            self._key_status.setText(language_wrapper.language_word_dict.get(
                "puppet_timeline_no_change", "Select keys first; nothing changed."))
            return False
        self._key_status.setText("")
        if isinstance(result, list):
            self._view.select_keys(result)
        self._show_track(track)
        self._view.track_modified.emit()
        return True

    def copy_selected(self) -> bool:
        track = self._view.track()
        if track is None:
            return False
        try:
            self._clip = copy_keys(track, self._view.selected_keys())
        except ValueError as exc:
            self._key_status.setText(str(exc))
            return False
        return True

    def paste_at(self, time: float) -> bool:
        if self._clip is None:
            return False
        return self._key_edit(lambda track: paste_keys(
            track, self._clip, snap_time(time, self._view.snap_step),
            duration=self._motion.duration))

    def move_selected(self, dt: float, dv: float) -> bool:
        low, high = self._range_of(self._view.track().param_id) if self._view.track() \
            else (-1.0, 1.0)
        return self._key_edit(lambda track: move_keys(
            track, self._view.selected_keys(), dt, dv, duration=self._motion.duration,
            snap=self._view.snap_step, value_range=(low, high)))

    def scale_selected(self, factor: float) -> bool:
        return self._key_edit(lambda track: scale_keys(
            track, self._view.selected_keys(), factor, duration=self._motion.duration))

    def tangent_selected(self, mode: str) -> bool:
        selection = self._view.selected_keys()
        return self._key_edit(lambda track: (set_tangents(track, selection, mode), selection)[1])

    def _ask_numbers(self, title: str, fields: list[tuple[str, float, float, float]]):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        form = QFormLayout(dialog)
        boxes = []
        for label, value, low, high in fields:
            box = QDoubleSpinBox()
            box.setDecimals(3)
            box.setRange(low, high)
            box.setValue(value)
            form.addRow(label, box)
            boxes.append(box)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        values = [box.value() for box in boxes]
        dialog.deleteLater()
        return values if accepted else None

    def _build_key_row(self) -> QHBoxLayout:
        lang = language_wrapper.language_word_dict
        row = QHBoxLayout()
        duration = float(self._motion.duration)
        actions = (
            ("puppet_timeline_copy", "Copy keys", self.copy_selected),
            ("puppet_timeline_paste", "Paste at…", lambda: (
                (v := self._ask_numbers(lang.get("puppet_timeline_paste", "Paste at…"),
                                        [("t", 0.0, 0.0, max(duration, 0.0))]))
                and self.paste_at(v[0]))),
            ("puppet_timeline_move", "Move…", lambda: (
                (v := self._ask_numbers(lang.get("puppet_timeline_move", "Move…"),
                                        [("Δt", 0.0, -duration, duration),
                                         ("Δv", 0.0, -1e4, 1e4)]))
                and self.move_selected(*v))),
            ("puppet_timeline_scale", "Scale time…", lambda: (
                (v := self._ask_numbers(lang.get("puppet_timeline_scale", "Scale time…"),
                                        [("×", 1.0, 0.01, 100.0)]))
                and self.scale_selected(v[0]))),
        )
        for key, fallback, slot in actions:
            button = QPushButton(lang.get(key, fallback))
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addWidget(QLabel(lang.get("puppet_timeline_snap", "Snap:")))
        self._snap_box = QComboBox()
        for label, step in ((lang.get("puppet_timeline_snap_off", "Off"), None),
                            ("1/30 s", 1 / 30), ("1/60 s", 1 / 60), ("0.1 s", 0.1)):
            self._snap_box.addItem(label, step)
        self._snap_box.currentIndexChanged.connect(
            lambda i: self.set_snap(self._snap_box.itemData(i)))
        row.addWidget(self._snap_box)
        row.addWidget(QLabel(lang.get("puppet_timeline_tangent", "Tangent:")))
        self._tangent_box = QComboBox()
        for mode in TANGENT_MODES:
            self._tangent_box.addItem(lang.get(f"puppet_timeline_tangent_{mode}", mode), mode)
        row.addWidget(self._tangent_box)
        apply_tangent = QPushButton(lang.get("puppet_timeline_apply_tangent", "Apply to keys"))
        apply_tangent.clicked.connect(
            lambda: self.tangent_selected(self._tangent_box.currentData()))
        row.addWidget(apply_tangent)
        self._key_status = QLabel()
        self._key_status.setObjectName("timeline_key_status")
        row.addWidget(self._key_status, 1)
        return row
