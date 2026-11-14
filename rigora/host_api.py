"""Versioned interface for applications that embed Rigora (R6.4).

A host checks compatibility once with :func:`require` and then uses only the
functions below. The interface version follows these rules: a new function or
optional argument raises the minor version; removing or changing anything
raises the major version, and the previous major version stays importable for
one release. The direct module imports Imervue and FrontEngine already use
remain supported and are pinned by ``tests/test_host_contract.py``.

Every function that needs Qt imports it lazily, so ``import rigora.host_api``
works in a core install without the GUI extra.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

API_VERSION = (1, 0)

CAPABILITIES = {
    "settings": "configure / flush the independent settings store",
    "translation": "choose the UI language and translate keys",
    "background_jobs": "attach the host's job registry before work starts",
    "workspaces": "create the puppet editor and desktop-pet tabs",
    "io": "load / save puppets and run the shared headless commands",
    "shutdown": "confirm discarding edits, then release services",
}


class HostApiError(RuntimeError):
    """The installed Rigora cannot satisfy the requested interface version."""


def require(major: int, minor: int = 0) -> tuple[int, int]:
    """Fail clearly unless this Rigora provides interface ``major.minor`` or later
    within the same major version; returns the installed version."""
    if major != API_VERSION[0] or minor > API_VERSION[1]:
        raise HostApiError(
            f"this host needs Rigora host API {major}.{minor}; the installed Rigora "
            f"provides {API_VERSION[0]}.{API_VERSION[1]}")
    return API_VERSION


def capabilities() -> dict[str, Any]:
    from importlib.metadata import PackageNotFoundError, version
    try:
        package = version("rigora")
    except PackageNotFoundError:
        package = None
    return {"api_version": list(API_VERSION), "package_version": package,
            "capabilities": dict(CAPABILITIES), "commands": sorted(_commands())}


def _commands():
    from rigora.command_registry import COMMANDS
    return COMMANDS


# ---- settings and language -------------------------------------------------


def configure_settings(path=None) -> None:
    from rigora.system import settings
    settings.configure(path)


def flush_settings() -> None:
    from rigora.system.settings import flush
    flush()


def set_language(name: str) -> None:
    from rigora.i18n.language_wrapper import language_wrapper
    language_wrapper.reset_language(name)


def translate(key: str, fallback: str) -> str:
    from rigora.i18n.language_wrapper import language_wrapper
    return language_wrapper.language_word_dict.get(key, fallback)


# ---- background jobs -------------------------------------------------------


def attach_job_registry(registry) -> None:
    from rigora.gui.background_jobs import set_job_registry
    set_job_registry(registry)


# ---- workspaces and shutdown -------------------------------------------------


def create_puppet_workspace(parent=None):
    from rigora.puppet import PuppetWorkspace
    return PuppetWorkspace(parent)


def create_pet_workspace(parent=None):
    from rigora.desktop_pet import PetWorkspace
    return PetWorkspace(parent)


def close_workspace(workspace) -> bool:
    """Ask about unsaved edits, then release the workspace's services. ``False``
    means the user cancelled and the host must cancel its own close too."""
    confirm: Callable[[], bool] | None = getattr(workspace, "confirm_discard_changes", None)
    if confirm is not None and not confirm():
        return False
    shutdown = getattr(workspace, "shutdown", None)
    if shutdown is not None:
        shutdown()
    return True


# ---- input / output ----------------------------------------------------------


def load_puppet(path):
    from rigora.puppet.document_io import load_puppet as load
    return load(path)


def save_puppet(document, path) -> None:
    from rigora.puppet.document_io import save_puppet as save
    save(document, path)


def run_command(name: str, **arguments) -> dict:
    """Run a registered headless command (the same ones the CLI and MCP expose)."""
    commands = _commands()
    if name not in commands:
        raise KeyError(f"no command {name!r}")
    return commands[name]["handler"](**arguments)
