"""Separate writable Rigora state from installed package resources."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def app_dir() -> Path:
    """Writable state root, including downloaded models and optional packages."""
    override = os.environ.get("RIGORA_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "Rigora"


def user_settings_path() -> Path:
    override = os.environ.get("RIGORA_SETTINGS_PATH")
    return Path(override).expanduser().resolve() if override else app_dir() / "settings.json"


def examples_dir() -> Path:
    """Examples installed inside the package, independent of the current directory."""
    return Path(__file__).resolve().parents[1] / "resources" / "examples"


def embedded_python_dir() -> Path:
    return app_dir() / "python_embedded"


def frozen_site_packages() -> Path:
    return app_dir() / "lib" / "site-packages"


def ensure_frozen_site_packages_on_path() -> None:
    if not is_frozen():
        return
    directory = frozen_site_packages()
    if directory.is_dir() and str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
