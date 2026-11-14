"""Runs several desktop characters side by side (R5.1 / R5.2 / R5.6).

The primary character stays owned by :class:`PetWorkspace` (its existing
window); every other character gets its own :class:`PetWindow`, with its own
settings slot, rig copy, script, timers and GL context. Stopping or removing
one shuts down only that window.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from rigora.desktop_pet import pet_roster
from rigora.desktop_pet import settings as pet_settings
from rigora.desktop_pet.edge_snap import Rect
from rigora.desktop_pet.pet_screens import recover, relative_position
from rigora.system.best_effort import best_effort

logger = logging.getLogger(__name__)


class CompanionManager(QObject):
    changed = Signal()

    def __init__(self, primary=None, *, window_factory=None, show=True,
                 screens=None, parent=None) -> None:
        super().__init__(parent)
        self._primary = primary                  # callable -> the primary PetWindow
        self._factory = window_factory
        self._show = show
        self._screens = screens                  # callable -> list[ScreenInfo]
        self.windows: dict[str, object] = {}

    # ---- lifecycle -------------------------------------------------------

    def _make(self, pet_id: str):
        if self._factory is not None:
            return self._factory(pet_id)
        from rigora.desktop_pet.pet_window import PetWindow
        return PetWindow(pet_id)

    def window(self, pet_id: str):
        if pet_id == pet_settings.DEFAULT_PET_ID and self._primary is not None:
            return self._primary()
        return self.windows.get(pet_id)

    def running(self) -> list[str]:
        return [pet_id for pet_id, window in self.windows.items() if window is not None]

    def start(self, pet_id: str):
        """Create (if needed), load and show one character."""
        if pet_id == pet_settings.DEFAULT_PET_ID:
            raise ValueError("the primary character is started from its own controls")
        window = self.windows.get(pet_id)
        if window is None:
            window = self._make(pet_id)
            self.windows[pet_id] = window
            rig = str(pet_settings.load(pet_id).get("last_rig_path") or "")
            if rig:
                window.load_puppet_file(rig)
        pet_roster.set_enabled(pet_id, True)
        if self._show:
            window.show()
        self.changed.emit()
        return window

    def stop(self, pet_id: str, *, remember: bool = True) -> bool:
        """Shut down one character's window; the others keep running."""
        window = self.windows.pop(pet_id, None)
        if window is None:
            return False
        self._remember_position(pet_id, window)
        with best_effort(f"shut down character {pet_id}", logger):
            window.shutdown()
        with best_effort(f"close character {pet_id}", logger):
            window.close()
            window.deleteLater()
        if remember:
            pet_roster.set_enabled(pet_id, False)
        self.changed.emit()
        return True

    def remove(self, pet_id: str) -> bool:
        self.stop(pet_id, remember=False)
        removed = pet_roster.remove_character(pet_id)
        self.changed.emit()
        return removed

    def change_rig(self, pet_id: str, path) -> bool:
        window = self.window(pet_id)
        if window is None:
            pet_settings.update(pet_id, last_rig_path=str(path))
            return True
        return bool(window.load_puppet_file(path))

    def change_script(self, pet_id: str, path) -> bool:
        window = self.window(pet_id)
        if window is None:
            pet_settings.update(pet_id, script_path=str(path))
            return True
        return bool(window.load_script_file(path))

    def start_enabled(self) -> list[str]:
        """Start every enabled companion (on launch or after a layout)."""
        started = []
        for character in pet_roster.characters():
            if not character.primary and character.enabled and character.id not in self.windows:
                self.start(character.id)
                started.append(character.id)
        return started

    def shutdown(self) -> None:
        for pet_id in list(self.windows):
            self.stop(pet_id, remember=False)

    # ---- layouts and screens -------------------------------------------------

    def _remember_position(self, pet_id: str, window) -> None:
        screens = self._screens() if self._screens is not None else []
        rect = Rect(window.x(), window.y(), window.width(), window.height())
        fields = {"position": [rect.x, rect.y]}
        best = recover(rect, screens) if screens else None
        if best is not None:
            screen = next(s for s in screens if s.name == best.screen)
            fields["screen_name"] = screen.name
            fields["relative_position"] = list(relative_position(rect, screen))
        pet_settings.update(pet_id, **fields)

    def save_layout(self, name: str) -> dict:
        for pet_id, window in self.windows.items():
            self._remember_position(pet_id, window)
        primary = self._primary() if self._primary is not None else None
        if primary is not None:
            self._remember_position(pet_settings.DEFAULT_PET_ID, primary)
        return pet_roster.save_layout(name)

    def restore_layout(self, name: str) -> list[str]:
        running = set(pet_roster.restore_layout(name))
        for pet_id in list(self.windows):
            if pet_id not in running:
                self.stop(pet_id)
        for pet_id in running - {pet_settings.DEFAULT_PET_ID}:
            window = self.windows.get(pet_id) or self.start(pet_id)
            self._place(pet_id, window)
        return sorted(running)

    def _place(self, pet_id: str, window) -> None:
        screens = self._screens() if self._screens is not None else []
        data = pet_settings.load(pet_id)
        position = data.get("position") or [-1, -1]
        rect = Rect(int(position[0]), int(position[1]), window.width(), window.height())
        relative = data.get("relative_position")
        placement = recover(rect, screens, saved_screen=str(data.get("screen_name") or ""),
                            relative=tuple(relative) if isinstance(relative, list) else None)
        if placement is not None and (placement.x, placement.y) != (window.x(), window.y()):
            window.move(placement.x, placement.y)

    def revalidate(self, reason: str = "") -> dict[str, str]:
        """After a screen change or wake: bring every character back onto a
        work area. Returns what happened per character."""
        screens = self._screens() if self._screens is not None else []
        outcome = {}
        targets = dict(self.windows)
        primary = self._primary() if self._primary is not None else None
        if primary is not None:
            targets[pet_settings.DEFAULT_PET_ID] = primary
        for pet_id, window in targets.items():
            data = pet_settings.load(pet_id)
            rect = Rect(window.x(), window.y(), window.width(), window.height())
            relative = data.get("relative_position")
            placement = recover(rect, screens, saved_screen=str(data.get("screen_name") or ""),
                                relative=tuple(relative) if isinstance(relative, list) else None)
            if placement is None:
                continue
            if (placement.x, placement.y) != (rect.x, rect.y):
                window.move(placement.x, placement.y)
            outcome[pet_id] = placement.reason
        if outcome:
            logger.info("characters revalidated after %s: %s", reason or "change", outcome)
        return outcome

    def stats(self) -> dict[str, dict]:
        out = {}
        for pet_id in self.running():
            window = self.windows[pet_id]
            stats = getattr(window, "resource_stats", None)
            out[pet_id] = stats() if stats is not None else {}
        return out
