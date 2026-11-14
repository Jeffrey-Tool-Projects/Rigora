"""The Characters tab: several desktop characters and their dialogue (R5.1 / R5.5 / R5.6)."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from rigora.desktop_pet import pet_roster
from rigora.desktop_pet import settings as pet_settings
from rigora.desktop_pet.pet_companions import CompanionManager
from rigora.desktop_pet.pet_workspace_toggles import _tr

logger = logging.getLogger(__name__)
STATS_REFRESH_MS = 2000


class PetWorkspaceCharactersMixin:
    def _init_companions(self) -> None:
        from rigora.desktop_pet.pet_placement import collect_screens
        self._companions = CompanionManager(primary=lambda: self._pet_window,
                                            screens=collect_screens, parent=self)
        self._companions.changed.connect(self._refresh_characters)
        self._screen_watcher = None

    def _build_characters_group(self) -> QGroupBox:
        group = QGroupBox(_tr("desktop_pet_group_characters", "Characters"))
        layout = QVBoxLayout(group)
        self._character_list = QListWidget()
        self._character_list.currentItemChanged.connect(lambda *_: self._show_character())
        layout.addWidget(self._character_list)
        buttons = (
            ("desktop_pet_character_add", "Add…", self._add_character),
            ("desktop_pet_character_remove", "Remove", self._remove_character),
            ("desktop_pet_character_toggle", "Start / stop", self._toggle_character),
            ("desktop_pet_character_copy", "Copy settings from…", self._copy_character),
            ("desktop_pet_character_rig", "Change rig…", self._change_character_rig),
            ("desktop_pet_character_script", "Change script…", self._change_character_script),
            ("desktop_pet_layout_save", "Save layout…", self._save_layout),
            ("desktop_pet_layout_restore", "Restore layout…", self._restore_layout),
            ("desktop_pet_behaviors_stop", "Stop behaviors", self._stop_character_behaviors),
        )
        row = None
        for index, (key, fallback, slot) in enumerate(buttons):
            if index % 3 == 0:
                row = QHBoxLayout()
                layout.addLayout(row)
            button = QPushButton(_tr(key, fallback))
            button.clicked.connect(slot)
            row.addWidget(button)
        self._character_stats = QLabel()
        self._character_stats.setWordWrap(True)
        self._character_stats.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._character_stats)
        layout.addWidget(self._build_dialogue_box())
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(STATS_REFRESH_MS)
        self._stats_timer.timeout.connect(self._show_character)
        self._refresh_characters()
        return group

    def _build_dialogue_box(self) -> QGroupBox:
        box = QGroupBox(_tr("desktop_pet_dialogue", "Local LLM dialogue"))
        layout = QVBoxLayout(box)
        self._llm_status = QLabel()
        layout.addWidget(self._llm_status)
        row = QHBoxLayout()
        for key, fallback, slot in (
                ("desktop_pet_llm_check", "Check connection", self._check_llm),
                ("desktop_pet_llm_cancel", "Cancel reply", self._cancel_llm),
                ("desktop_pet_llm_clear", "Clear history", self._clear_llm_history)):
            button = QPushButton(_tr(key, fallback))
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        self._llm_keep = QCheckBox(_tr("desktop_pet_llm_keep_history",
                                       "Keep conversation history between sessions"))
        self._llm_keep.toggled.connect(self._keep_llm_history)
        layout.addWidget(self._llm_keep)
        note = QLabel(_tr("desktop_pet_llm_actions_note",
                          "Replies can only play this character's own motions and "
                          "expressions; nothing else in a reply is carried out."))
        note.setWordWrap(True)
        layout.addWidget(note)
        return box

    # ---- list ------------------------------------------------------------------

    def _selected_character(self) -> str | None:
        item = self._character_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _refresh_characters(self) -> None:
        current = self._selected_character()
        self._character_list.blockSignals(True)
        self._character_list.clear()
        running = set(self._companions.running())
        if self._pet_window is not None and self._pet_window.isVisible():
            running.add(pet_settings.DEFAULT_PET_ID)
        for character in pet_roster.characters():
            state = _tr("desktop_pet_character_running", "running") \
                if character.id in running else _tr("desktop_pet_character_stopped", "stopped")
            item = QListWidgetItem(f"{character.name} — {state}")
            item.setData(Qt.ItemDataRole.UserRole, character.id)
            self._character_list.addItem(item)
            if character.id == current:
                self._character_list.setCurrentItem(item)
        self._character_list.blockSignals(False)
        self._show_character()

    def _show_character(self) -> None:
        pet_id = self._selected_character()
        window = self._companions.window(pet_id) if pet_id else None
        if window is None or not hasattr(window, "resource_stats"):
            self._character_stats.setText("")
            self._llm_status.setText("")
            self._stats_timer.stop()
            return
        stats = window.resource_stats()
        self._character_stats.setText(_tr(
            "desktop_pet_character_stats",
            "{drawables} drawables · {mib:.1f} MiB textures · GL {gl_textures} textures / "
            "{gl_buffers} buffers · {active_timers} timers · frame {interval}").format(
            mib=stats["texture_bytes"] / 1048576,
            interval=f"{stats['frame_interval_ms']} ms" if stats["frame_interval_ms"] else "—",
            **{k: v for k, v in stats.items() if k not in ("frame_interval_ms",)}))
        state, detail = window._llm.status()   # noqa: SLF001
        self._llm_status.setText(_tr("desktop_pet_llm_status", "Dialogue: {state} {detail}")
                                 .format(state=state, detail=detail))
        self._llm_keep.blockSignals(True)
        self._llm_keep.setChecked(window._llm.keeps_history())   # noqa: SLF001
        self._llm_keep.blockSignals(False)
        if not self._stats_timer.isActive():
            self._stats_timer.start()

    # ---- actions ---------------------------------------------------------------

    def _add_character(self) -> None:
        name, ok = QInputDialog.getText(self, _tr("desktop_pet_character_add", "Add…"),
                                        _tr("desktop_pet_character_name", "Name:"))
        if not ok or not name.strip():
            return
        source = self._selected_character()
        try:
            pet_roster.add_character(name, copy_from=source)
        except ValueError as exc:
            self._set_status_text(str(exc))
        self._refresh_characters()

    def _remove_character(self) -> None:
        pet_id = self._selected_character()
        if pet_id and not self._companions.remove(pet_id):
            self._set_status_text(_tr("desktop_pet_character_keep_primary",
                                      "The main character cannot be removed."))
        self._refresh_characters()

    def _toggle_character(self) -> None:
        pet_id = self._selected_character()
        if not pet_id:
            return
        if pet_id == pet_settings.DEFAULT_PET_ID:
            self._show_check.setChecked(not self._show_check.isChecked())
        elif pet_id in self._companions.running():
            self._companions.stop(pet_id)
        else:
            self._companions.start(pet_id)
        self._refresh_characters()

    def _copy_character(self) -> None:
        target = self._selected_character()
        others = [c for c in pet_roster.characters() if c.id != target]
        if not target or not others:
            return
        name, ok = QInputDialog.getItem(self, _tr("desktop_pet_character_copy",
                                                  "Copy settings from…"),
                                        _tr("desktop_pet_character_name", "Name:"),
                                        [c.name for c in others], 0, False)
        if ok:
            source = next(c.id for c in others if c.name == name)
            pet_roster.copy_settings(source, target)
            self._refresh_characters()

    def _change_character_rig(self) -> None:
        pet_id = self._selected_character()
        if not pet_id:
            return
        path, _ = QFileDialog.getOpenFileName(self, _tr("desktop_pet_character_rig",
                                                        "Change rig…"), "", "Puppet (*.puppet)")
        if path:
            self._companions.change_rig(pet_id, path)
            self._refresh_characters()

    def _change_character_script(self) -> None:
        pet_id = self._selected_character()
        if not pet_id:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, _tr("desktop_pet_character_script", "Change script…"), "",
            "Pet script (*.petscript.json *.json)")
        if path and not self._companions.change_script(pet_id, path):
            self._set_status_text(_tr("desktop_pet_script_invalid",
                                      "The script was not loaded; see the log for where "
                                      "it is wrong."))

    def _save_layout(self) -> None:
        name, ok = QInputDialog.getText(self, _tr("desktop_pet_layout_save", "Save layout…"),
                                        _tr("desktop_pet_character_name", "Name:"))
        if ok and name.strip():
            self._companions.save_layout(name)

    def _restore_layout(self) -> None:
        names = pet_roster.layout_names()
        if not names:
            return
        name, ok = QInputDialog.getItem(self, _tr("desktop_pet_layout_restore",
                                                  "Restore layout…"),
                                        _tr("desktop_pet_character_name", "Name:"),
                                        names, 0, False)
        if ok:
            self._companions.restore_layout(name)
            self._refresh_characters()

    def _stop_character_behaviors(self) -> None:
        window = self._companions.window(self._selected_character() or "")
        if window is not None and hasattr(window, "stop_behaviors"):
            window.stop_behaviors()

    def _selected_llm(self):
        window = self._companions.window(self._selected_character() or "")
        return getattr(window, "_llm", None)

    def _check_llm(self) -> None:
        llm = self._selected_llm()
        if llm is not None:
            try:
                llm.check_connection()
            except ValueError as exc:
                self._llm_status.setText(str(exc))

    def _cancel_llm(self) -> None:
        llm = self._selected_llm()
        if llm is not None:
            llm.cancel()

    def _clear_llm_history(self) -> None:
        llm = self._selected_llm()
        if llm is not None:
            llm.clear_history()

    def _keep_llm_history(self, keep: bool) -> None:
        llm = self._selected_llm()
        if llm is not None:
            llm.set_keep_history(keep)

    def _set_status_text(self, text: str) -> None:
        status = getattr(self, "_status", None)
        if status is not None:
            status.setText(text)

    # ---- screens (R5.2) --------------------------------------------------------

    def _start_screen_watch(self) -> None:
        if self._screen_watcher is None:
            from rigora.desktop_pet.pet_screens import ScreenWatcher
            self._screen_watcher = ScreenWatcher(self._companions.revalidate)

    def _shutdown_companions(self) -> None:
        timer = getattr(self, "_stats_timer", None)
        if timer is not None:
            timer.stop()
        if self._screen_watcher is not None:
            self._screen_watcher.stop()
            self._screen_watcher = None
        self._companions.shutdown()
