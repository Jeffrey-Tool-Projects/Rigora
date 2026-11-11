"""Build a clean installation boundary around the installed-package checks."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    verifier = Path(__file__).with_name("verify_installed.py").resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="rigora-wheel-") as folder:
        root = Path(folder)
        subprocess.run([sys.executable, "-m", "venv", str(root / "env")], check=True)
        interpreter = root / "env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(interpreter), "-m", "pip", "install", str(wheel)], check=True)
        subprocess.run([str(interpreter), "-I", str(verifier)], cwd=root, check=True)


if __name__ == "__main__":
    main()
