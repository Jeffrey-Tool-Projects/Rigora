"""Upgrade and downgrade checks between a released version and this tree (R8.5).

    py -3 scripts/verify_upgrade.py --old-tag v0.1.1 --output DIR
        [--old-exe OLD/Rigora.exe --new-exe NEW/Rigora.exe]

Documents: the old version is built from its git tag into a throwaway virtual
environment. Files written by this tree (with compositions and recorded
takes) must open in the old version, which keeps every motion; files written
by the old version must open here unchanged.

Frozen executables (optional): the old and new ``Rigora.exe`` run their
hidden ``--smoke-test`` one after another against one isolated settings
folder — old, new, old — and the settings file must stay readable and keep
its values. Nothing touches the user's real settings.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_TAG = re.compile(r"v\d+(\.\d+){1,3}((a|b|rc|\.post|\.dev)\d+)?")

OLD_SCRIPT = r"""
import json, sys
from rigora.puppet.document_io import load_puppet, save_puppet
src, out = sys.argv[1], sys.argv[2]
doc = load_puppet(src)
save_puppet(doc, out)
print(json.dumps({"motions": sorted(m.name for m in doc.motions),
                  "drawables": len(doc.drawables),
                  "version": __import__("importlib.metadata").metadata.version("rigora")}))
"""


def _run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8",
                          **kwargs)


def old_environment(tag: str, work: Path) -> Path:
    """A venv with ``rigora`` built from ``tag`` (dependencies from this Python)."""
    if not _TAG.fullmatch(tag):   # never let a tag be read as a git option or a revision range
        raise ValueError(f"not a release tag: {tag!r}")
    archive = work / "old.tar"
    _run(["git", "archive", "--format=tar", f"--output={archive}", f"refs/tags/{tag}"], cwd=ROOT)
    source = work / "old-src"
    with tarfile.open(archive) as tar:
        tar.extractall(source, filter="data")
    env = work / "old-env"
    _run([sys.executable, "-m", "venv", "--system-site-packages", str(env)])
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _run([str(python), "-m", "pip", "install", "--no-deps", "-q", str(source)])
    return python


def check_documents(tag: str, work: Path) -> dict:
    sys.path.insert(0, str(ROOT))
    from rigora.puppet.document import Clip, Composition, CompositionLayer
    from rigora.puppet.document_io import load_puppet, save_puppet
    from rigora.puppet.takes import new_take_info

    python = old_environment(tag, work)
    current = load_puppet(ROOT / "examples" / "puppet" / "imeru.puppet")
    current.motions[0].take = new_take_info("record", fps=30.0, inputs=["webcam"])
    current.compositions = [Composition("show", 2.0, [CompositionLayer(
        "base", [Clip(current.motions[1].name)])])]
    new_file = work / "written-by-new.puppet"
    save_puppet(current, new_file)
    old_saved = work / "resaved-by-old.puppet"
    result = json.loads(_run([str(python), "-I", "-c", OLD_SCRIPT, str(new_file),
                              str(old_saved)], cwd=work).stdout)
    expected = sorted(m.name for m in current.motions)
    if result["motions"] != expected or result["drawables"] != len(current.drawables):
        raise AssertionError(f"old version lost data: {result}")
    back = load_puppet(old_saved)              # old → new (upgrade of an old file)
    if sorted(m.name for m in back.motions) != expected:
        raise AssertionError("an old file did not open with every motion")
    return {"old_version": result["version"], "new_file_opens_in_old": True,
            "old_file_opens_in_new": True,
            "kept_by_old_resave": {"compositions": len(back.compositions),
                                   "takes": sum(1 for m in back.motions if m.take)}}


def check_executables(old_exe: Path, new_exe: Path, work: Path) -> dict:
    data = work / "data"
    data.mkdir()
    settings = data / "settings.json"
    settings.write_text(json.dumps({"language": "English", "ui_scale_percent": 125,
                                    "upgrade_sentinel": "keep me"}), encoding="utf-8")
    env = {**os.environ, "RIGORA_DATA_DIR": str(data), "RIGORA_SETTINGS_PATH": str(settings)}
    runs = []
    for label, exe in (("old", old_exe), ("new", new_exe), ("old again", old_exe)):
        report = work / f"{label.replace(' ', '-')}.json"
        subprocess.run([str(exe), "--smoke-test", str(report)], cwd=work, env=env, check=True,
                       timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result = json.loads(report.read_text(encoding="utf-8"))
        stored = json.loads(settings.read_text(encoding="utf-8"))
        if result.get("status") != "passed":
            raise AssertionError(f"{label} smoke test failed: {result}")
        if stored.get("upgrade_sentinel") != "keep me" or stored.get("ui_scale_percent") != 125:
            raise AssertionError(f"{label} lost settings: {stored}")
        runs.append({"run": label, "status": result["status"], "frozen": result["frozen"]})
    return {"sequence": runs, "settings_kept": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--old-tag", default="v0.1.1")
    parser.add_argument("--old-exe", type=Path)
    parser.add_argument("--new-exe", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"old_tag": args.old_tag}
    with tempfile.TemporaryDirectory(prefix="rigora-upgrade-") as directory:
        work = Path(directory)
        report["documents"] = check_documents(args.old_tag, work)
        if args.old_exe and args.new_exe:
            exe_work = work / "exe"
            exe_work.mkdir()
            report["executables"] = check_executables(args.old_exe.resolve(),
                                                      args.new_exe.resolve(), exe_work)
        else:
            report["executables"] = "skipped (pass --old-exe and --new-exe)"
    report["status"] = "passed"
    (args.output / "upgrade.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
