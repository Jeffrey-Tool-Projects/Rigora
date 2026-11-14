"""The editor file shares the application's command-line entry point."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("argument", "exit_code", "message"),
    [
        ("--help", 0, ".puppet document to open"),
        ("--unknown-option", 2, "unrecognized arguments: --unknown-option"),
    ],
)
def test_editor_file_from_another_directory(tmp_path, argument, exit_code, message):
    script = Path(__file__).resolve().parents[1] / "rigora" / "editor_window.py"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(script), argument],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert "usage: rigora-editor" in result.stdout + result.stderr
    assert message in result.stdout + result.stderr
