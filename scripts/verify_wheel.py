"""Build a clean installation boundary around the installed-package checks."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from verification_permissions import readonly_package


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--sdist", action="store_true", help="Rebuild the sdist before installing")
    parser.add_argument("--readonly", action="store_true", help="Enforce OS package write denial")
    parser.add_argument("--output", type=Path, default=Path(".audit/installed-verification"))
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    if wheel.is_dir():
        pattern = "rigora-*.tar.gz" if args.sdist else "rigora-*.whl"
        candidates = sorted(wheel.glob(pattern))
        if len(candidates) != 1:
            parser.error(f"Expected exactly one {pattern} in {wheel}, found {len(candidates)}")
        wheel = candidates[0]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "verification.json").unlink(missing_ok=True)
    verifier = Path(__file__).with_name("verify_installed.py").resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="rigora-wheel-") as folder:
        root = Path(folder)
        if args.sdist:
            subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps",
                            "--wheel-dir", str(root / "rebuilt"), str(wheel)], check=True)
            wheel, = (root / "rebuilt").glob("rigora-*.whl")
        (output / "artifact.json").write_text(json.dumps({
            "wheel": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "sdist_rebuilt": args.sdist,
        }, indent=2), encoding="utf-8")
        subprocess.run([sys.executable, "-m", "venv", str(root / "env")], check=True)
        interpreter = root / "env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(interpreter), "-m", "pip", "install", str(wheel)], check=True)
        def permissions():
            return readonly_package(interpreter, root / "env") if args.readonly else nullcontext()
        with permissions():
            result = subprocess.run([str(interpreter), "-I", str(verifier)], cwd=root,
                                    capture_output=True, text=True, check=False)
        (output / "core.json").write_text(result.stdout, encoding="utf-8")
        (output / "core.stderr.log").write_text(result.stderr, encoding="utf-8")
        result.check_returncode()
        print(result.stdout)
        if args.gui:
            subprocess.run([str(interpreter), "-m", "pip", "install", f"{wheel}[gui]"], check=True)
            gui_verifier = verifier.with_name("verify_gui.py")
            with permissions():
                subprocess.run(
                    [str(interpreter), str(gui_verifier), "--output", str(output / "gui")],
                    cwd=root, check=True,
                )
        (output / "verification.json").write_text(json.dumps({
            "status": "passed", "os_readonly": args.readonly, "gui": args.gui,
            "sdist_rebuilt": args.sdist,
        }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
