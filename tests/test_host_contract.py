"""R6.4 / R6.5: the versioned host API, consumer imports and the example adapter.

``CONSUMER_IMPORTS`` lists every Rigora name Imervue (76f1b609) and
FrontEngine (95d8678e) import outside their tests. Removing or renaming one
breaks a consumer, so it must go through a host-API major version instead.
"""
from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from rigora import host_api

ROOT = Path(__file__).resolve().parents[1]

CONSUMER_IMPORTS = {
    "rigora.app": ["main"],
    "rigora.commands": ["puppet_from_png", "puppet_inspect", "puppet_validate", "puppet_schema"],
    "rigora.dependencies.pip_installer": ["ensure_dependencies"],
    "rigora.desktop_pet": ["PetTrayIcon", "PetWorkspace", "edge_snap", "pet_script",
                           "pet_window", "pet_workspace", "settings", "tray_icon"],
    "rigora.desktop_pet.pet_script": ["PetScriptEngine", "load_script", "save_script"],
    "rigora.desktop_pet.pet_window": ["PetWindow"],
    "rigora.editor_window": ["EditorWindow"],
    "rigora.gui.background_jobs": ["set_job_registry"],
    "rigora.gui.panel_scroll": ["PanelScrollArea"],
    "rigora.gui.tool_icons": ["tool_icon"],
    "rigora.i18n.language_wrapper": ["language_wrapper"],
    "rigora.mcp_server": ["main"],
    "rigora.puppet": ["PuppetWorkspace"],
    "rigora.puppet.audio_lipsync": ["lipsync_motion"],
    "rigora.puppet.canvas": ["PuppetCanvas"],
    "rigora.puppet.document_io": ["load_puppet", "save_puppet"],
    "rigora.puppet.idle_driver": ["IdleDriver"],
    "rigora.puppet.input_engine": ["InputEngine"],
    "rigora.puppet.motion_player": ["MotionPlayer"],
    "rigora.puppet.operations": ["add_parameter"],
    "rigora.puppet.rig_repair": ["repair_rig"],
    "rigora.puppet.standard_params": ["PARAM_MOUTH_OPEN_Y"],
    "rigora.puppet.webcam_tracker": ["WebcamTracker"],
    "rigora.puppet.workspace_ui": ["size_inspectors"],
    "rigora.system": ["settings"],
    "rigora.system.qt_timers": ["call_later"],
    "rigora.system.settings": ["flush", "configure"],
}


@pytest.mark.parametrize("module", sorted(CONSUMER_IMPORTS))
def test_consumer_imports_still_resolve(qapp, module):
    loaded = importlib.import_module(module)
    for name in CONSUMER_IMPORTS[module]:
        assert hasattr(loaded, name), f"{module}.{name}"


def test_lipsync_signature_only_gained_keyword_options():
    import inspect

    from rigora.puppet.audio_lipsync import lipsync_motion
    parameters = inspect.signature(lipsync_motion).parameters
    assert list(parameters)[:5] == ["path", "name", "param_id", "mouth_range", "fps"]
    assert all(parameters[p].default is not inspect.Parameter.empty for p in ("lead", "gate"))


def test_version_negotiation():
    assert host_api.require(1) == host_api.API_VERSION
    assert host_api.require(1, 0) == (1, 0)
    with pytest.raises(host_api.HostApiError, match="needs Rigora host API 2.0"):
        host_api.require(2)
    with pytest.raises(host_api.HostApiError):
        host_api.require(1, 99)
    info = host_api.capabilities()
    assert info["api_version"] == [1, 0]
    assert {"settings", "translation", "background_jobs", "workspaces", "io",
            "shutdown"} <= set(info["capabilities"])
    assert "puppet_validate" in info["commands"]


def test_close_workspace_respects_cancel_and_shuts_down():
    calls = []

    class Workspace:
        def __init__(self, answer):
            self.answer = answer

        def confirm_discard_changes(self):
            calls.append("confirm")
            return self.answer

        def shutdown(self):
            calls.append("shutdown")

    assert host_api.close_workspace(Workspace(False)) is False and calls == ["confirm"]
    assert host_api.close_workspace(Workspace(True)) is True
    assert calls == ["confirm", "confirm", "shutdown"]


def test_host_api_without_qt_imports_and_reports_clearly():
    code = (
        "import sys; sys.modules['PySide6'] = None\n"
        "from rigora import host_api\n"
        "host_api.require(1); info = host_api.capabilities()\n"
        "assert 'io' in info['capabilities']\n"
        "try:\n    host_api.create_puppet_workspace()\nexcept ImportError as e:\n"
        "    print('missing-gui', type(e).__name__)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=ROOT, check=False)
    assert done.returncode == 0, done.stderr
    assert "missing-gui" in done.stdout


def _adapter_module():
    spec = importlib.util.spec_from_file_location(
        "example_adapter", ROOT / "examples" / "extensions" / "example_adapter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_example_adapter_loads_checks_and_unloads(tmp_path):
    from rigora.puppet.document import PuppetDocument
    module = _adapter_module()
    adapter = module.ExampleAdapter()
    with pytest.raises(RuntimeError, match="not loaded"):
        adapter.save_checked(PuppetDocument(), tmp_path / "a.puppet")
    info = adapter.load(host_api)
    assert info["requires"]["api"] == (1, 0)
    assert adapter.save_checked(PuppetDocument(), tmp_path / "a.puppet") == []
    adapter.unload()
    adapter.unload()                     # safe to call twice
    assert not adapter.loaded

    class OldRigora:
        @staticmethod
        def require(major, minor=0):
            raise host_api.HostApiError("too old")

    with pytest.raises(host_api.HostApiError):
        module.ExampleAdapter().load(OldRigora)
