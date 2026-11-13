"""R8.3: every example builds from repository files and matches its expected result."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _runner():
    spec = importlib.util.spec_from_file_location("run_examples",
                                                  ROOT / "examples" / "run_examples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_example_builds_without_a_gpu(tmp_path, capsys):
    assert _runner().main(["--output", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)["examples"]
    assert set(report) == {"basic", "advanced_rig", "animation", "live", "desktop_pet"}
    assert all(item["status"] == "passed" for item in report.values()), report
    assert report["animation"]["export"].startswith("skipped")     # never counted as passed


def test_every_example_is_documented_with_source_license_steps_and_result():
    readme = (ROOT / "examples" / "README.md").read_text(encoding="utf-8")
    for heading in ("Basic rig", "Advanced rigging", "Animation production", "Live streaming",
                    "Desktop pet scripts"):
        section = readme.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
        for field in ("Source", "License", "Steps", "Expected result"):
            assert f"**{field}" in section, (heading, field)


def test_bundled_examples_match_the_repository_copies():
    """The installed app ships the same rigs and pet scripts as ``examples/``."""
    bundled = ROOT / "rigora" / "resources" / "examples"
    for pattern in ("puppet/*.puppet", "desktop_pet/*.petscript.json"):
        sources = sorted((ROOT / "examples").glob(pattern))
        assert sources, pattern
        for source in sources:
            copy = bundled / source.relative_to(ROOT / "examples")
            assert copy.read_bytes() == source.read_bytes(), f"{copy} is out of date"


def test_release_checksums_write_and_detect_tampering(tmp_path):
    from importlib import util
    spec = util.spec_from_file_location("release_checksums",
                                        ROOT / "scripts" / "release_checksums.py")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "rigora-1.0.0-py3-none-any.whl").write_bytes(b"wheel")
    (tmp_path / "rigora-1.0.0.tar.gz").write_bytes(b"sdist")
    module.write(tmp_path)
    assert module.check(tmp_path) == []
    (tmp_path / "rigora-1.0.0.tar.gz").write_bytes(b"changed")
    (tmp_path / "Rigora-windows-x64.zip").write_bytes(b"zip")
    assert module.check(tmp_path) == ["rigora-1.0.0.tar.gz: checksum differs",
                                      "Rigora-windows-x64.zip: not listed"]
