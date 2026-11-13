"""Tests for ``PuppetMenusMixin._build_actions`` on a GL-free host.

Pins every action the puppet workspace creates: its label, whether it is
checkable, and which workspace slot it drives (``triggered`` for plain
actions, ``toggled`` for checkable ones), so restructuring the builder cannot
drop, relabel or rewire an action.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QWidget

from rigora.puppet.workspace_menus import PuppetMenusMixin, example_label

# (attribute, label, checkable, slot)
_ACTIONS = [
    ("_save_current_action", "Save", False, "save_current_document"),
    ("_recovery_action", "Recover document…", False, "_recover_document"),
    ("_autosave_action", "Autosave interval…", False, "_configure_autosave"),
    ("_undo_action", "Undo", False, "undo"),
    ("_redo_action", "Redo", False, "redo"),
    ("_open_action", "Open Puppet…", False, "_open_via_dialog"),
    ("_save_action", "Save As…", False, "_save_via_dialog"),
    ("_import_png_action", "Import PNG…", False, "_import_png_via_dialog"),
    ("_import_psd_action", "Import PSD…", False, "_import_psd_via_dialog"),
    ("_import_cubism_action", "Import Cubism…", False, "_import_cubism_via_dialog"),
    ("_update_art_action", "Update art from PSD…", False, "_update_art_via_dialog"),
    ("_relink_textures_action", "Relink textures…", False, "_relink_textures_via_dialog"),
    ("_install_deps_action", "Install dependencies…", False, "_install_all_optional_deps"),
    ("_add_rot_action", "Add Rotation Deformer", False, "_add_rotation_deformer"),
    ("_add_warp_action", "Add Warp Deformer", False, "_add_warp_deformer"),
    ("_add_param_action", "Add Parameter", False, "_add_parameter"),
    ("_mirror_action", "Mirror drawable…", False, "_mirror_drawable_via_dialog"),
    ("_edit_motion_action", "Edit motion…", False, "_edit_active_motion"),
    ("_mesh_edit_toggle", "Edit mesh", True, "_toggle_mesh_edit"),
    ("_drag_toggle", "Drag-track head", True, "_toggle_drag"),
    ("_blink_toggle", "Auto-blink", True, "_toggle_blink"),
    ("_lipsync_audio_action", "Lip-sync from Audio File…", False, "_lipsync_from_audio_file"),
    ("_lipsync_toggle", "Mic lip-sync", True, "_toggle_lipsync"),
    ("_webcam_toggle", "Webcam tracking", True, "_toggle_webcam"),
    ("_idle_toggle", "Auto idle", True, "_toggle_idle"),
    ("_idle_motion_toggle", "Idle motions", True, "_toggle_idle_motions"),
    ("_capture_action", "Capture frame…", False, "_capture_via_dialog"),
    ("_record_action", "Record…", True, "_toggle_recording"),
    ("_motion_record_toggle", "Record motion", True, "_toggle_motion_record"),
    ("_batch_export_action", "Export all motions…", False, "_batch_export_via_dialog"),
    ("_virtual_camera_toggle", "Virtual camera", True, "_toggle_virtual_camera"),
    ("_ndi_toggle", "NDI output", True, "_toggle_ndi"),
    ("_vts_toggle", "VTS API", True, "_toggle_vts_api"),
    ("_validate_action", "Validate", False, "_run_validator"),
    ("_repair_action", "Repair Rig", False, "_run_rig_repair"),
    ("_fit_action", "Fit to Window", False, "_canvas_reset_view"),
    ("_reset_action", "Reset to rest", False, "_reset_to_rest"),
    ("_input_settings_action", "Input devices and calibration…", False, "input_settings_via_dialog"),
    ("_input_sources_action", "Input sources…", False, "show_input_sources"),
    ("_live_status_action", "Live status…", False, "show_output_status"),
    ("_export_animation_action", "Export animation…", False, "export_animation_via_dialog"),
    ("_relink_sounds_action", "Relink sounds…", False, "_relink_sounds_via_dialog"),
    ("_compositions_action", "Compositions…", False, "edit_compositions_via_dialog"),
    ("_templates_action", "Part templates…", False, "part_templates_via_dialog"),
    ("_doctor_action", "Rig doctor…", False, "run_rig_doctor_via_dialog"),
    ("_physics_action", "Physics chains…", False, "edit_physics_via_dialog"),
    ("_mesh_select_all_action", "Select all vertices", False, "_mesh_select_all"),
    ("_mesh_lock_action", "Lock selected vertices", False, "_mesh_lock_selection"),
    ("_mesh_unlock_action", "Unlock all vertices", False, "_mesh_unlock_all"),
    ("_mesh_smooth_action", "Smooth weights", False, "mesh_smooth_weights"),
    ("_mesh_normalize_action", "Normalize weights", False, "mesh_normalize_weights"),
    ("_mesh_mirror_weights_action", "Mirror weights left → right", False, "mesh_mirror_weights"),
    ("_mesh_mirror_vertices_action", "Mirror selected vertices", False, "mesh_mirror_vertices"),
    ("_mesh_delete_action", "Delete selected vertices…", False, "mesh_delete_vertices"),
    ("_mesh_weights_action", "Show weights…", False, "_mesh_show_weights"),
]
_MENUS = [
    ("_recent_menu", "Recent", "_rebuild_recent_menu"),
    ("_examples_menu", "Examples", "_rebuild_examples_menu"),
]
_SLOTS = {slot for *_x, slot in _ACTIONS} | {slot for *_x, slot in _MENUS}


class _Host(PuppetMenusMixin, QWidget):
    """Records every workspace slot call instead of doing the work."""

    def __init__(self):
        super().__init__()
        self.calls: list[tuple] = []
        for slot in _SLOTS:
            setattr(self, slot, lambda *args, s=slot: self.calls.append((s, *args)))


@pytest.fixture
def host(qapp, monkeypatch):
    from rigora.puppet import workspace_menus
    monkeypatch.setattr(workspace_menus.language_wrapper, "language_word_dict", {})
    widget = _Host()
    widget._build_actions()  # noqa: SLF001
    yield widget
    widget.deleteLater()


def test_every_action_label_and_checkable(host):
    for attr, label, checkable, _slot in _ACTIONS:
        action = getattr(host, attr)
        assert isinstance(action, QAction), attr
        assert action.parent() is host, attr
        assert (action.text(), action.isCheckable()) == (label, checkable), attr


def test_actions_are_distinct_objects(host):
    assert len({id(getattr(host, attr)) for attr, *_x in _ACTIONS}) == len(_ACTIONS)


@pytest.mark.parametrize(("attr", "checkable", "slot"),
                         [(a, c, s) for a, _l, c, s in _ACTIONS])
def test_action_drives_its_slot(host, attr, checkable, slot):
    action = getattr(host, attr)
    action.trigger()
    expected = (slot, True) if checkable else (slot,)
    assert host.calls == [expected]


def test_checkable_action_reports_both_toggle_directions(host):
    host._drag_toggle.trigger()  # noqa: SLF001
    host._drag_toggle.trigger()  # noqa: SLF001
    assert host.calls == [("_toggle_drag", True), ("_toggle_drag", False)]


@pytest.mark.parametrize(("attr", "title", "slot"), _MENUS)
def test_submenus_rebuild_before_showing(host, attr, title, slot):
    menu = getattr(host, attr)
    assert isinstance(menu, QMenu)
    assert menu.title() == title
    assert menu.parent() is host
    menu.aboutToShow.emit()
    assert host.calls == [(slot,)]


def test_labels_come_from_the_language_dict(qapp, monkeypatch):
    from rigora.puppet import workspace_menus
    monkeypatch.setattr(workspace_menus.language_wrapper, "language_word_dict",
                        {"puppet_open": "OPEN", "puppet_recent": "RECENT"})
    widget = _Host()
    try:
        widget._build_actions()  # noqa: SLF001
        assert widget._open_action.text() == "OPEN"  # noqa: SLF001
        assert widget._recent_menu.title() == "RECENT"  # noqa: SLF001
        assert widget._save_action.text() == "Save As…"  # noqa: SLF001
    finally:
        widget.deleteLater()



@pytest.mark.parametrize(("stem", "label"), [
    ("imeru_2nd_outfit", "Imeru 2nd Outfit"),  # str.title() made this "Imeru 2Nd Outfit"
    ("vivian", "Vivian"),
    ("my__rig_v2", "My Rig V2"),
    ("already_Upper", "Already Upper"),
    ("", ""),
])
def test_example_label(stem, label):
    assert example_label(stem) == label
