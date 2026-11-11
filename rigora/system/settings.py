"""Rigora-owned settings with explicit startup and atomic, debounced persistence."""
from __future__ import annotations

import copy
import json
import logging
import shutil
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from rigora.system.app_paths import user_settings_path
from rigora.system.atomic_write import write_text_atomically

logger = logging.getLogger(__name__)
_lock = threading.RLock()
_path: Path | None = None
_timer: threading.Timer | None = None
_generation = 0
_autosave = False
_unreadable: Path | None = None
_loaded_keys: set[str] = set()
_DEFAULTS = {"language": "English", "ui_scale_percent": 100}
_SAVE_DELAY = 0.5


class Settings(dict[str, Any]):
    """Keep ordinary dict access while scheduling saves for top-level changes."""

    def __setitem__(self, key: str, value: Any) -> None:
        with _lock:
            super().__setitem__(key, value)
            schedule_save()

    def __delitem__(self, key: str) -> None:
        with _lock:
            super().__delitem__(key)
            schedule_save()

    def update(self, *args, **kwargs) -> None:
        with _lock:
            super().update(*args, **kwargs)
            schedule_save()

    def clear(self) -> None:
        with _lock:
            super().clear()
            schedule_save()

    def pop(self, key, *default):
        with _lock:
            value = super().pop(key, *default)
            schedule_save()
            return value

    def popitem(self):
        with _lock:
            value = super().popitem()
            schedule_save()
            return value

    def setdefault(self, key, default=None):
        with _lock:
            if key not in self:
                self[key] = default
            return self[key]

    def __ior__(self, other):
        self.update(other)
        return self


user_setting_dict = Settings(_DEFAULTS)


def is_configured() -> bool:
    return _path is not None


def cancel_pending_save() -> None:
    global _timer, _generation
    with _lock:
        _generation += 1
        if _timer is not None:
            _timer.cancel()
            _timer = None


def configure(path: str | Path | None = None, *, autosave: bool = True) -> None:
    """Load settings once per application startup; tests may select an isolated path."""
    global _path, _autosave, _unreadable, _loaded_keys
    with _lock:
        cancel_pending_save()
        _autosave = False
        _path = Path(path) if path is not None else user_settings_path()
        _unreadable = None
        values: dict[str, Any] = {}
        try:
            loaded = json.loads(_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("Rigora settings must contain an object")
            values = loaded
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            _unreadable = _path
            logger.warning("Cannot read settings at %s; preserving it before any save", _path)
        _loaded_keys = set(values)
        dict.clear(user_setting_dict)
        dict.update(user_setting_dict, _DEFAULTS)
        dict.update(user_setting_dict, values)
        _autosave = autosave


def schedule_save() -> None:
    global _timer
    with _lock:
        if not _autosave or _path is None:
            return
        cancel_pending_save()
        generation = _generation
        _timer = threading.Timer(_SAVE_DELAY, _save_generation, args=(generation,))
        _timer.daemon = True
        _timer.start()


def _save_generation(generation: int) -> None:
    with _lock:
        if generation != _generation:
            return
        try:
            flush()
        except (OSError, TypeError, ValueError):
            logger.exception("Could not save Rigora settings")


def flush() -> None:
    """Persist current state; report errors to callers handling application shutdown."""
    global _unreadable
    with _lock:
        cancel_pending_save()
        if _path is None:
            return
        payload = json.dumps(copy.deepcopy(dict(user_setting_dict)), ensure_ascii=False, indent=2)
        _path.parent.mkdir(parents=True, exist_ok=True)
        if _unreadable is not None and _unreadable.exists():
            backup = _unreadable.with_name(f"{_unreadable.name}.unreadable-{uuid4().hex}")
            shutil.copy2(_unreadable, backup)
            _unreadable = None
        write_text_atomically(_path, payload + "\n")


def import_legacy_settings(values: Mapping[str, Any]) -> bool:
    """Import only Puppet preferences once, without overwriting saved Rigora choices."""
    if user_setting_dict.get("_legacy_imervue_imported"):
        return False
    selected = {
        key: copy.deepcopy(value) for key, value in values.items()
        if (key.startswith(("puppet_", "desktop_pet")) or key in _DEFAULTS)
        and key not in _loaded_keys
        and (key not in user_setting_dict or key in _DEFAULTS)
    }
    user_setting_dict.update(selected)
    user_setting_dict["_legacy_imervue_imported"] = True
    flush()
    return bool(selected)


def read_user_setting() -> None:
    configure()


def write_user_setting() -> None:
    flush()
