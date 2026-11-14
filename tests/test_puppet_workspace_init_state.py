"""Characterisation test for what ``PuppetWorkspace``'s constructor builds.

Pins every instance attribute (name, type, simple values, timer settings) and
where each dock sits: Parameters, Expressions and Bones tabbed together on the
right, Motions alone at the bottom. Generated before the constructor was split
into ``_build_docks`` / ``_build_controllers`` / ``_build_status_bar``.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDockWidget

from _qt_skip import pytestmark  # noqa: E402,F401

_EXPECTED = {'_add_param_action': ('QAction',),
 '_add_rot_action': ('QAction',),
 '_add_warp_action': ('QAction',),
 '_autosave_action': ('QAction',),
 '_batch_export_action': ('QAction',),
 '_batch_exporter': ('BatchMotionExporter',),
 '_blink_toggle': ('QAction',),
 '_bone_tree_dock': ('BoneTreeDock',),
 '_canvas': ('PuppetCanvas',),
 '_capture_action': ('QAction',),
 '_compositions_action': ('QAction',),
 '_device_timer': ('QTimer', 1000, False),
 '_doctor_action': ('QAction',),
 '_document_state_label': ('QLabel',),
 '_drag_toggle': ('QAction',),
 '_edit_motion_action': ('QAction',),
 '_examples_menu': ('QMenu',),
 '_export_animation_action': ('QAction',),
 '_expression_dock': ('ExpressionDock',),
 '_fit_action': ('QAction',),
 '_idle_driver': ('IdleDriver',),
 '_idle_motion_cycler': ('IdleMotionCycler',),
 '_idle_motion_toggle': ('QAction',),
 '_idle_toggle': ('QAction',),
 '_import_cubism_action': ('QAction',),
 '_import_png_action': ('QAction',),
 '_import_psd_action': ('QAction',),
 '_input_engine': ('InputEngine',),
 '_input_profile': ('InputProfile',),
 '_input_settings_action': ('QAction',),
 '_input_sources_action': ('QAction',),
 '_input_store': ('Settings',),
 '_install_deps_action': ('QAction',),
 '_lipsync_audio_action': ('QAction',),
 '_lipsync_toggle': ('QAction',),
 '_live_status_action': ('QAction',),
 '_mesh_delete_action': ('QAction',),
 '_mesh_edit_toggle': ('QAction',),
 '_mesh_lock_action': ('QAction',),
 '_mesh_mirror_vertices_action': ('QAction',),
 '_mesh_mirror_weights_action': ('QAction',),
 '_mesh_normalize_action': ('QAction',),
 '_mesh_select_all_action': ('QAction',),
 '_mesh_smooth_action': ('QAction',),
 '_mesh_unlock_action': ('QAction',),
 '_mesh_weights_action': ('QAction',),
 '_mic_supervisor': ('DeviceSupervisor',),
 '_mirror_action': ('QAction',),
 '_motion_dock': ('MotionDock',),
 '_motion_record_toggle': ('QAction',),
 '_motion_recorder': ('MotionRecorder',),
 '_ndi_output': ('NDIOutput',),
 '_ndi_toggle': ('QAction',),
 '_open_action': ('QAction',),
 '_parameter_dock': ('ParameterDock',),
 '_physics_action': ('QAction',),
 '_pose_dock': ('PoseDock',),
 '_recent_menu': ('QMenu',),
 '_record_action': ('QAction',),
 '_recorder': ('RecordingSession',),
 '_recovery': ('NoneType', None),
 '_recovery_action': ('QAction',),
 '_recovery_timer': ('QTimer', 60000, False),
 '_redo_action': ('QAction',),
 '_relink_sounds_action': ('QAction',),
 '_relink_textures_action': ('QAction',),
 '_repair_action': ('QAction',),
 '_reset_action': ('QAction',),
 '_save_action': ('QAction',),
 '_save_current_action': ('QAction',),
 '_status_label': ('QLabel',),
 '_templates_action': ('QAction',),
 '_undo_action': ('QAction',),
 '_update_art_action': ('QAction',),
 '_validate_action': ('QAction',),
 '_virtual_camera': ('VirtualCameraOutput',),
 '_virtual_camera_toggle': ('QAction',),
 '_vts_server': ('VTubeStudioServer',),
 '_vts_toggle': ('QAction',),
 '_webcam': ('WebcamTracker',),
 '_webcam_supervisor': ('DeviceSupervisor',),
 '_webcam_toggle': ('QAction',),
 '_welcome': ('WorkspaceWelcome',),
 'customContextMenuRequested': ('SignalInstance',),
 'destroyed': ('SignalInstance',),
 'iconSizeChanged': ('SignalInstance',),
 'objectNameChanged': ('SignalInstance',),
 'session': ('DocumentSession',),
 'tabifiedDockWidgetActivated': ('SignalInstance',),
 'toolButtonStyleChanged': ('SignalInstance',),
 'windowIconChanged': ('SignalInstance',),
 'windowIconTextChanged': ('SignalInstance',),
 'windowTitleChanged': ('SignalInstance',)}


def _describe(value):
    if isinstance(value, QTimer):
        return ("QTimer", value.interval(), value.isSingleShot())
    if value is None or isinstance(value, (bool, int, float, str)):
        return (type(value).__name__, value)
    return (type(value).__name__,)


@pytest.fixture
def workspace(qapp):
    from rigora.puppet.workspace import PuppetWorkspace
    ws = PuppetWorkspace()
    yield ws
    ws.deleteLater()


def test_constructed_attributes_are_unchanged(workspace):
    actual = {k: _describe(v) for k, v in sorted(vars(workspace).items()) if k != "__METAOBJECT__"}
    assert sorted(actual) == sorted(_EXPECTED)
    for name, expected in _EXPECTED.items():
        assert actual[name] == expected, name


def test_dock_layout(workspace):
    docks = {type(d).__name__: d for d in workspace.findChildren(QDockWidget)}
    right = Qt.DockWidgetArea.RightDockWidgetArea
    assert {n: workspace.dockWidgetArea(d) for n, d in docks.items()} == {
        "ParameterDock": right, "ExpressionDock": right, "PoseDock": right,
        "BoneTreeDock": right, "MotionDock": Qt.DockWidgetArea.BottomDockWidgetArea,
    }
    tabbed = {type(t).__name__ for t in workspace.tabifiedDockWidgets(docks["ExpressionDock"])}
    assert tabbed == {"ParameterDock", "PoseDock", "BoneTreeDock"}
    assert workspace.tabifiedDockWidgets(docks["MotionDock"]) == []
    assert [docks[n].windowTitle() for n in ("ParameterDock", "ExpressionDock", "PoseDock",
                                             "BoneTreeDock", "MotionDock")] == [
        "Parameters", "Expressions", "Pose", "Bones", "Motions"]
