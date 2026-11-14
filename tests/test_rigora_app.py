"""Exercise the standalone application against a native, desktop-hidden GL surface."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from _qt_skip import pytestmark  # noqa: F401 - pytest module marker


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Native background verifier uses Windows visibility observations",
)
def test_standalone_editor_renders_and_closes_without_surviving_timers(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_gui.py"
    result = subprocess.run(
        [sys.executable, str(script), "--source", "--skip-workflows", "--output", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=100,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["platform"] == "windows"
    assert report["drawables"] == 23
    assert report["neutral"]["sha256"] == report["roundtrip"]["sha256"]
    assert report["neutral"]["sha256"] != report["animated"]["sha256"]
    assert report["pet_control_page"] and report["shutdown"]
    assert report["desktop_observation"]["window_was_native_hidden"]
    assert not report["active_timers_after_close"]
