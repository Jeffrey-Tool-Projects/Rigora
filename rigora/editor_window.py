"""Standalone owner of the character editor, desktop pets and background work."""

from __future__ import annotations

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from rigora.app import main

    raise SystemExit(main())

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget, QWidget

from rigora.gui.background_jobs import drain_background_jobs, open_background_jobs
from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.workspace import PuppetWorkspace
from rigora.system.settings import flush, user_setting_dict


class EditorWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Rigora")
        self.resize(1280, 850)
        self._shutdown = False
        self._pet = None
        self._tray = None
        self.tabs = QTabWidget(self)
        self.editor = PuppetWorkspace(self.tabs)
        self.tabs.addTab(self.editor, "Rigora")
        self._pet_page = QWidget(self.tabs)
        self.tabs.addTab(
            self._pet_page, language_wrapper.language_word_dict.get("desktop_pet", "Desktop Pet")
        )
        self.tabs.currentChanged.connect(self._select_tab)
        self.setCentralWidget(self.tabs)
        self._build_app_menu()

    def _build_app_menu(self) -> None:
        menu = self.menuBar().addMenu("Rigora")
        jobs = menu.addAction(
            language_wrapper.language_word_dict.get("background_jobs", "Background Jobs")
        )
        jobs.triggered.connect(lambda: open_background_jobs(self))
        languages = menu.addMenu("Language")
        group = QActionGroup(self)
        group.setExclusive(True)
        for name in language_wrapper.choose_language_dict:
            action = QAction(name.replace("_", " "), group)
            action.setCheckable(True)
            action.setChecked(name == language_wrapper.language)
            action.triggered.connect(lambda _checked=False, code=name: self._select_language(code))
            languages.addAction(action)

    def _select_language(self, language: str) -> None:
        user_setting_dict["language"] = language
        flush()
        QMessageBox.information(self, "Rigora", "Restart Rigora to apply the selected language.")

    def _select_tab(self, index: int) -> None:
        if index != 1 or self._pet is not None:
            return
        from PySide6.QtWidgets import QVBoxLayout
        from rigora.desktop_pet import PetTrayIcon, PetWorkspace

        self._pet = PetWorkspace(self._pet_page)
        layout = QVBoxLayout(self._pet_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._pet)
        if PetTrayIcon.is_available():
            self._tray = PetTrayIcon(self._pet, parent=self)
            self._pet.attach_tray(self._tray)
            self._tray.show()

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        try:
            self.editor.shutdown()
        finally:
            try:
                if self._pet is not None:
                    self._pet.shutdown()
            finally:
                drain_background_jobs()
                flush()

    def closeEvent(self, event) -> None:
        if not self._shutdown and not self.editor.confirm_discard_changes():
            event.ignore()
            return
        self.shutdown()
        super().closeEvent(event)
