"""Puppet workspace Qt shell, child ownership and action identity."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QStatusBar,
)
from rigora.gui.control_tooltips import enable_control_tooltips
from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.canvas import PuppetCanvas
from rigora.puppet.expression_dock import ExpressionDock
from rigora.puppet.idle_driver import IdleDriver
from rigora.puppet.idle_motion_cycler import IdleMotionCycler
from rigora.puppet.batch_export import BatchMotionExporter
from rigora.puppet.bone_tree_dock import BoneTreeDock
from rigora.puppet.ndi_output import NDIOutput
from rigora.puppet.virtual_camera import VirtualCameraOutput
from rigora.puppet.vts_api import VTubeStudioServer
from rigora.puppet.input_engine import InputEngine
from rigora.puppet.motion_dock import MotionDock
from rigora.puppet.motion_recorder import MotionRecorder
from rigora.puppet.parameter_dock import ParameterDock
from rigora.puppet.pose_dock import PoseDock
from rigora.puppet.recorder import RecordingSession
from rigora.puppet.webcam_tracker import WebcamTracker
from rigora.puppet.workspace_assets import PuppetAssetsMixin
from rigora.puppet.workspace_mesh_tools import PuppetMeshToolsMixin
from rigora.puppet.workspace_rig_tools import PuppetRigToolsMixin
from rigora.puppet.workspace_animation import PuppetAnimationMixin
from rigora.puppet.workspace_import import PuppetImportMixin
from rigora.puppet.workspace_live import PuppetLiveMixin
from rigora.puppet.workspace_live_io import PuppetLiveIOMixin
from rigora.puppet.workspace_menus import RECENT_KEY, PuppetMenusMixin
from rigora.puppet.workspace_files import PuppetFilesMixin
from rigora.puppet.workspace_authoring import PuppetAuthoringMixin
from rigora.puppet.workspace_keyframes import PuppetKeyframesMixin
from rigora.puppet.workspace_reset import PuppetResetMixin
from rigora.puppet.workspace_input import PuppetInputMixin
from rigora.puppet.workspace_validation import PuppetValidationMixin
from rigora.puppet.workspace_export import PuppetExportMixin
from rigora.puppet.workspace_motion_edit import PuppetMotionEditMixin
from rigora.puppet.workspace_motion_record import PuppetMotionRecordMixin
from rigora.puppet.workspace_audio import PuppetAudioMixin
from rigora.puppet.workspace_files import _push_recent
from rigora.puppet.workspace_session import PuppetSessionMixin

__all__ = ["PuppetWorkspace", "_push_recent", "RECENT_KEY", "QFileDialog"]


class PuppetWorkspace(
    PuppetSessionMixin, PuppetFilesMixin, PuppetAuthoringMixin, PuppetKeyframesMixin,
    PuppetResetMixin,
    PuppetInputMixin, PuppetValidationMixin, PuppetExportMixin, PuppetMotionEditMixin,
    PuppetMotionRecordMixin, PuppetAudioMixin, PuppetMenusMixin, PuppetLiveMixin,
    PuppetImportMixin, PuppetAssetsMixin, PuppetMeshToolsMixin, PuppetRigToolsMixin,
    PuppetAnimationMixin, PuppetLiveIOMixin, QMainWindow,
):
    def __init__(self, parent=None):
        super().__init__(parent)
        # The window flag keeps QMainWindow from being treated as a
        # real top-level window when embedded in a tab.
        self.setWindowFlags(Qt.WindowType.Widget)

        self._canvas = PuppetCanvas(self)
        self.setCentralWidget(self._canvas)

        # Build the actions first; menu and toolbar both reference the
        # same QAction objects so toggling one updates the other.
        self._build_actions()
        self.setMenuBar(self._build_menu_bar())
        self.addToolBar(
            Qt.ToolBarArea.TopToolBarArea, self._build_toggle_toolbar(),
        )

        self._build_docks()
        self._build_controllers()
        self._build_status_bar()
        self._init_session()
        self._update_session_actions()
        self._refresh_status_for_no_document()
        from rigora.puppet.workspace_ui import build_welcome, configure_inspectors
        self._welcome = build_welcome(self)
        configure_inspectors(self)
        enable_control_tooltips(self)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.property("initialInspectorSized"):
            from rigora.puppet.workspace_ui import size_inspectors
            from rigora.system.qt_timers import call_later
            self.setProperty("initialInspectorSized", True)
            call_later(0, self, lambda: size_inspectors(self))

    def _build_docks(self) -> None:
        """Parameters / Expressions / Bones tabbed on the right, Motions at the bottom."""
        self._parameter_dock = ParameterDock(self._canvas, self, workspace=self)
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self._parameter_dock,
        )

        self._expression_dock = ExpressionDock(self._canvas, self)
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self._expression_dock,
        )
        self._bone_tree_dock = BoneTreeDock(self._canvas, self)
        self._bone_tree_dock.hierarchy_changed.connect(
            self._on_bone_hierarchy_changed,
        )
        self._bone_tree_dock.deformer_selected.connect(
            self._canvas.set_selected_deformer,
        )
        # Right-click on canvas clears overlay → tree-row deselects in
        # lockstep so the user can't end up with one side highlighted
        # and the other not.
        self._canvas.selection_cleared.connect(
            self._bone_tree_dock.clear_selection,
        )
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self._bone_tree_dock,
        )
        # Tabify so the user gets Parameters/Expressions/Bones as
        # three tabs in the same right pane instead of a cramped split.
        # Parameters is the most-frequent one so it stays on top.
        self._pose_dock = PoseDock(self._canvas, self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._pose_dock)
        self.tabifyDockWidget(self._expression_dock, self._parameter_dock)
        self.tabifyDockWidget(self._expression_dock, self._pose_dock)
        self.tabifyDockWidget(self._expression_dock, self._bone_tree_dock)

        self._motion_dock = MotionDock(self._canvas, self)
        # Live2D-style transition feel: when the user switches motions
        # we ease across 0.5s rather than snap. Per-motion fade fields
        # (e.g. from a Cubism .motion3.json import) override this.
        self._motion_dock.player().set_default_fade(0.5, 0.5)
        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self._motion_dock,
        )

    def _build_controllers(self) -> None:
        """Input, idle, streaming, export and recording controllers bound to the canvas."""
        self._input_engine = InputEngine(self._canvas, self)
        self._idle_driver = IdleDriver(self._canvas, self)
        self._idle_motion_cycler = IdleMotionCycler(
            self._motion_dock.player(), self._canvas, self,
        )
        self._vts_server = VTubeStudioServer(self._canvas, self)
        self._virtual_camera = VirtualCameraOutput(self._canvas, self)
        self._ndi_output = NDIOutput(self._canvas, self)
        self._batch_exporter = BatchMotionExporter(
            self._canvas, self._motion_dock.player(), self,
        )
        self._batch_exporter.progress.connect(self._on_batch_progress)
        self._batch_exporter.finished.connect(self._on_batch_finished)
        self._batch_exporter.failed.connect(self._on_batch_failed)
        self._recorder = RecordingSession(self._canvas, self)
        self._recorder.finished.connect(self._on_recording_finished)
        self._recorder.failed.connect(self._on_recording_failed)
        self._webcam = WebcamTracker(self._canvas, self)
        self._webcam.state_changed.connect(self._on_webcam_state_changed)
        self._motion_recorder = MotionRecorder(self._canvas, self)
        self._motion_recorder.finished.connect(self._on_motion_recorded)
        self._canvas.hit_area_triggered.connect(self._on_hit_area_triggered)
        self._init_live_io()

    def _build_status_bar(self) -> None:
        """Status bar with the stretching message label."""
        self._status_label = QLabel("")
        self._document_state_label = QLabel("")
        bar = QStatusBar()
        bar.addWidget(self._status_label, stretch=1)
        bar.addPermanentWidget(self._document_state_label)
        self.setStatusBar(bar)

    def canvas(self) -> PuppetCanvas:
        return self._canvas

    def parameter_dock(self) -> ParameterDock:
        return self._parameter_dock

    def expression_dock(self) -> ExpressionDock:
        return self._expression_dock

    def idle_driver(self) -> IdleDriver:
        return self._idle_driver

    def _canvas_reset_view(self) -> None:
        self._canvas.reset_view()

    def _announce(self, key: str, fallback: str, **fmt) -> None:
        self._status_label.setText(
            language_wrapper.language_word_dict.get(key, fallback).format(**fmt),
        )

    def input_engine(self) -> InputEngine:
        return self._input_engine

    def closeEvent(self, event):  # noqa: N802 - Qt naming
        if not getattr(self, "_shutdown_complete", False) and not self.confirm_discard_changes():
            event.ignore()
            return
        self.shutdown()
        super().closeEvent(event)

    def idle_motion_cycler(self) -> IdleMotionCycler:
        return self._idle_motion_cycler

    def _refresh_status_for_no_document(self) -> None:
        self._status_label.setText(
            language_wrapper.language_word_dict.get(
                "puppet_status_empty",
                "No puppet loaded — use Open to load a .puppet file.",
            ),
        )

    @property
    def _status(self) -> QLabel:
        return self._status_label
