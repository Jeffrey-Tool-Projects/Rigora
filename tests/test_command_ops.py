"""R6.1–R6.3: shared commands, exit codes, JSON errors, overwrite rules and jobs."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from rigora import cli, command_ops
from rigora.command_jobs import JobManager, cli_arguments
from rigora.command_registry import COMMANDS
from rigora.mcp_server import handle_message
from rigora.puppet.document import (
    Clip,
    Composition,
    CompositionLayer,
    Motion,
    MotionSegment,
    MotionTrack,
    Parameter,
)
from rigora.puppet.document_io import load_puppet, save_puppet
from rigora.puppet.psd_import import plan_psd_import
from tests.psd_fixtures import FixtureLayer, save_psd_stack

ROOT = Path(__file__).resolve().parents[1]


def _psd(path, rgb=(200, 0, 0)):
    image = np.zeros((12, 16, 4), dtype=np.uint8)
    image[2:8, 3:9] = (*rgb, 255)
    save_psd_stack(path, (16, 12), [FixtureLayer("body", image), FixtureLayer(
        "shade", image.copy(), mask=True)])
    return path


@pytest.fixture
def rig(tmp_path):
    psd = _psd(tmp_path / "art.psd")
    document = plan_psd_import(psd).build(enable_auto_rig=False)
    document.parameters.append(Parameter("A", -1, 1, 0))
    points = [(i / 10, (i % 3) / 2 - 0.5) for i in range(11)]
    document.motions.append(Motion("wiggle", 1.0, tracks=[MotionTrack("A", [
        MotionSegment("linear", points[i], points[i + 1]) for i in range(10)])]))
    document.compositions.append(Composition("show", 1.0, [CompositionLayer(
        "base", [Clip("wiggle")])]))
    path = tmp_path / "rig.puppet"
    save_puppet(document, path)
    return path


def run_cli(*argv):
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_every_command_has_a_schema_and_a_handler():
    for name, command in COMMANDS.items():
        assert command["input_schema"]["type"] == "object", name
        assert callable(command["handler"]), name
        assert set(command["input_schema"].get("required", [])) <= set(
            command["input_schema"]["properties"]), name


def test_psd_commands_preview_and_import(tmp_path):
    psd = _psd(tmp_path / "art.psd")
    code, out, err = run_cli("psd-preview", str(psd))
    assert code == 0 and json.loads(out)["drawable_count"] == 2 and err == ""
    target = tmp_path / "out.puppet"
    code, out, _ = run_cli("puppet-from-psd", str(psd), "--destination", str(target))
    assert code == 0 and json.loads(out)["differences"][0]["code"] == "layer_mask_ignored"
    code, out, err = run_cli("puppet-from-psd", str(psd), "--destination", str(target), "--json")
    assert code == 3 and json.loads(out) == {"error": {
        "code": "output_exists",
        "message": f"{target} exists; pass overwrite to replace it"}}
    assert err.startswith("output_exists:")
    assert run_cli("puppet-from-psd", str(psd), "--destination", str(target),
                   "--overwrite")[0] == 0


def test_doctor_update_compress_and_bake(rig, tmp_path):
    code, out, _ = run_cli("rig-doctor", str(rig))
    assert code == 0 and "findings" in json.loads(out)
    fixed = tmp_path / "fixed.puppet"
    code, out, _ = run_cli("rig-doctor", str(rig), "--fixes", '["safe"]',
                           "--destination", str(fixed))
    assert code == 0 and fixed.exists()
    new_psd = _psd(tmp_path / "v2.psd", rgb=(0, 200, 0))
    code, out, _ = run_cli("update-art", str(rig), "--psd", str(new_psd))
    plan = json.loads(out)["plan"]
    assert {c["key"]: c["kind"] for c in plan["changes"]}["body"] == "changed"
    updated = tmp_path / "updated.puppet"
    assert run_cli("update-art", str(rig), "--psd", str(new_psd), "--destination",
                   str(updated))[0] == 0
    small = tmp_path / "small.puppet"
    code, out, _ = run_cli("motion-compress", str(rig), "--motion", "wiggle", "--destination",
                           str(small), "--tolerance", "25")
    report = json.loads(out)
    assert code == 0 and report["keys_after"] < report["keys_before"]
    baked = tmp_path / "baked.puppet"
    code, out, _ = run_cli("bake-composition", str(rig), "--composition", "show",
                           "--destination", str(baked), "--fps", "20")
    assert code == 0 and "show (baked)" in [m.name for m in load_puppet(baked).motions]
    code, out, _ = run_cli("bake-composition", str(rig), "--composition", "nope",
                           "--destination", str(tmp_path / "x.puppet"), "--json")
    assert code == 1 and json.loads(out)["error"]["code"] == "not_found"


def test_rendering_reports_missing_capability_headless(rig, tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    code, out, _ = run_cli("export-animation", str(rig), "--destination", str(tmp_path / "f"),
                           "--motion", "wiggle", "--json")
    assert code == 4 and json.loads(out)["error"]["code"] == "capability_missing"
    code, out, _ = run_cli("export-animation", str(rig), "--destination", str(tmp_path / "f"),
                           "--json")
    assert code == 1 and "exactly one" in json.loads(out)["error"]["message"]


def test_stdout_is_only_the_result_in_a_subprocess(tmp_path):
    psd = _psd(tmp_path / "art.psd")
    done = subprocess.run([sys.executable, "-m", "rigora.cli", "psd-preview", str(psd)],
                          capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
                          check=False)
    assert done.returncode == 0
    json.loads(done.stdout)
    usage = subprocess.run([sys.executable, "-m", "rigora.cli", "psd-preview"],
                           capture_output=True, text=True, cwd=ROOT, check=False)
    assert usage.returncode == 2 and usage.stdout == ""


def test_mcp_reports_structured_errors(rig):
    response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "motion_compress", "arguments": {"path": str(rig), "motion": "x",
                                                  "destination": str(rig)}}})
    result = response["result"]
    assert result["isError"] and result["structuredContent"]["error"]["code"] == "output_exists"


def test_cli_arguments_translate_mcp_arguments():
    argv = cli_arguments("rig_doctor", {"path": "a.puppet", "fixes": ["safe"],
                                        "overwrite": True, "destination": "b"})
    assert argv == ["rig-doctor", "a.puppet", "--fixes", '["safe"]', "--overwrite",
                    "--destination", "b"]


def test_jobs_run_report_and_are_idempotent(rig, tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    manager = JobManager()
    first = manager.start("rig_doctor", {"path": str(rig)}, request_id="r1")
    again = manager.start("rig_doctor", {"path": str(rig)}, request_id="r1")
    assert first["job_id"] == again["job_id"]
    result = manager.wait(first["job_id"], timeout=60)
    assert result["state"] == "done" and "findings" in result["result"]
    failed = manager.start("motion_compress", {"path": str(rig), "motion": "wiggle",
                                               "destination": str(rig)})
    result = manager.wait(failed["job_id"], timeout=60)
    assert result["state"] == "failed" and result["error"]["code"] == "output_exists"
    from rigora.command_jobs import Job
    manager.jobs["quick"] = Job("quick", "rig_doctor", None)
    with pytest.raises(ValueError, match="too quickly"):
        manager.cancel("quick")
    manager.jobs["long"] = Job("long", "export_animation", None,
                               cancel_file=tmp_path / "long.cancel")
    assert manager.cancel("long")["state"] == "running"
    assert (tmp_path / "long.cancel").exists()
    with pytest.raises(ValueError):
        manager.status("missing")


def test_job_tools_over_mcp(rig, monkeypatch):
    monkeypatch.chdir(ROOT)

    def call(name, arguments):
        return handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": name, "arguments": arguments}})["result"]

    started = call("job_start", {"command": "cubism_preview",
                                 "arguments": {"path": str(rig)}})["structuredContent"]
    from rigora import mcp_server
    mcp_server._job_manager().wait(started["job_id"], timeout=60)   # noqa: SLF001
    finished = call("job_result", {"job_id": started["job_id"]})["structuredContent"]
    assert finished["state"] == "failed" and finished["error"]["code"] == "invalid_input"
    bad = call("job_start", {"command": "rig_doctor", "arguments": {"nope": 1}})
    assert bad["isError"] and bad["structuredContent"]["error"]["code"] == "invalid_input"


def test_error_codes_map_to_exit_statuses():
    assert command_ops.CommandError("x", "y").exit_code == command_ops.EXIT_FAILED
    with pytest.raises(command_ops.CommandError) as error:
        command_ops._destination("", False)   # noqa: SLF001
    assert error.value.code == "invalid_input"


def test_gui_and_cli_produce_the_same_documents(tmp_path):
    """R6 acceptance: the same input through the editor's code path and through
    the CLI gives byte-identical archives."""
    from types import SimpleNamespace

    from rigora.puppet.document_io import to_zip_bytes
    from rigora.puppet.workspace_rig_tools import PuppetRigToolsMixin
    psd = _psd(tmp_path / "art.psd")
    cli_rig = tmp_path / "cli.puppet"
    assert run_cli("puppet-from-psd", str(psd), "--destination", str(cli_rig))[0] == 0
    gui_document = plan_psd_import(psd).build()        # what File > Import PSD… builds
    gui_rig = tmp_path / "gui.puppet"
    save_puppet(gui_document, gui_rig)
    assert to_zip_bytes(load_puppet(cli_rig)) == to_zip_bytes(load_puppet(gui_rig))

    findings = json.loads(run_cli("rig-doctor", str(cli_rig))[1])["findings"]
    fixable = [f["id"] for f in findings if f["fixable"]]
    cli_fixed = tmp_path / "cli-fixed.puppet"
    assert run_cli("rig-doctor", str(cli_rig), "--fixes", json.dumps(fixable),
                   "--destination", str(cli_fixed))[0] == 0
    document = load_puppet(gui_rig)
    host = SimpleNamespace(
        _apply_rig_edit=lambda label, edit: edit(document),
        _announce=lambda *a, **k: None)
    PuppetRigToolsMixin.apply_rig_fixes(host, fixable)  # Tools > Rig doctor… > Apply
    gui_fixed = tmp_path / "gui-fixed.puppet"
    save_puppet(document, gui_fixed)
    assert to_zip_bytes(load_puppet(cli_fixed)) == to_zip_bytes(load_puppet(gui_fixed))
