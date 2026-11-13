"""Example host adapter for Rigora's host API (R6.5).

Rigora has no plugin loader or marketplace: none is extracted until a real
third-party extension needs one. Until then an integration is a small adapter
like this one, which a host imports itself. It follows three rules:

1. Declare what it needs in ``REQUIRES`` and check it with ``host_api.require``
   before touching anything, so an incompatible Rigora fails at load.
2. Use only :mod:`rigora.host_api` (and the published command registry) —
   never private modules — so the adapter survives internal refactors.
3. ``unload()`` undoes everything ``load()`` did, in reverse order, and is safe
   to call twice; the host calls it before closing or replacing Rigora.
"""
from __future__ import annotations

REQUIRES = {"api": (1, 0), "capabilities": ("io", "translation")}


class ExampleAdapter:
    """Adds a 'validate on save' check to a host that saves puppets."""

    def __init__(self) -> None:
        self._host_api = None
        self.loaded = False

    def load(self, host_api) -> dict:
        host_api.require(*REQUIRES["api"])
        missing = set(REQUIRES["capabilities"]) - set(host_api.capabilities()["capabilities"])
        if missing:
            raise RuntimeError(f"Rigora lacks capabilities: {', '.join(sorted(missing))}")
        self._host_api = host_api
        self.loaded = True
        return {"name": "example-validate-on-save", "requires": REQUIRES}

    def save_checked(self, document, path) -> list[dict]:
        """Save, then validate the written file with the shared command."""
        if not self.loaded:
            raise RuntimeError("adapter is not loaded")
        self._host_api.save_puppet(document, path)
        report = self._host_api.run_command("puppet_validate", path=str(path))
        return [issue for issue in report.get("issues", []) if issue.get("severity") == "error"]

    def unload(self) -> None:
        self._host_api = None
        self.loaded = False
