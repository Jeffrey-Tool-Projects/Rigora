"""Build, verify and archive the Windows x64 portable distribution."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LICENSES = (
    "numpy", "Pillow", "PySide6", "PySide6_Addons", "PySide6_Essentials",
    "shiboken6", "PyOpenGL", "imageio", "imageio-ffmpeg", "PyInstaller", "setuptools",
)


def copy_licenses(bundle: Path) -> None:
    python_license = bundle / "licenses" / "Python" / "LICENSE.txt"
    python_license.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", python_license)
    for name in ("LICENSE", "THIRD_PARTY_LICENSES.md"):
        shutil.copy2(ROOT / name, bundle / name)
    for name in RUNTIME_LICENSES:
        distribution = importlib.metadata.distribution(name)
        for item in distribution.files or []:
            if not any(word in str(item).lower() for word in ("license", "copying", "notice")):
                continue
            source = Path(distribution.locate_file(item))
            if source.is_file():
                target = bundle / "licenses" / name / str(item).replace("..", "_")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)


def verify_executable(executable: Path, report: Path, *, native: bool = False) -> None:
    mode = "--native-smoke-test" if native else "--smoke-test"
    report.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="rigora-exe-cwd-") as directory:
        subprocess.run(
            [str(executable), mode, str(report)], cwd=directory, check=True,
            timeout=90, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    result = json.loads(report.read_text(encoding="utf-8"))
    if result.get("status") != "passed" or not result.get("frozen"):
        raise RuntimeError(f"Frozen verification failed: {result}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "windows")
    parser.add_argument("--native", action="store_true", help="also verify hidden native OpenGL")
    parser.add_argument("--tag", help="require the release tag to match the package version")
    args = parser.parse_args()
    if (sys.platform != "win32" or sys.maxsize <= 2**32
            or platform.machine().lower() not in {"amd64", "x86_64"}):
        parser.error("Build on Windows x64 with 64-bit Python")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    if args.tag and args.tag != f"v{version}":
        parser.error(f"Release tag must be v{version}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(output), "--workpath", str(ROOT / "build" / "windows"),
         str(ROOT / "packaging" / "windows.spec")], cwd=ROOT, check=True,
    )
    bundle = output / "Rigora"
    copy_licenses(bundle)
    verify_executable(bundle / "Rigora.exe", output / "smoke-report.json")
    if args.native:
        verify_executable(bundle / "Rigora.exe", output / "native-report.json", native=True)
    archive = Path(shutil.make_archive(str(output / "Rigora-windows-x64"), "zip", output, "Rigora"))
    with archive.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    (output / "SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    print(json.dumps({"version": version, "archive": str(archive), "sha256": checksum}))


if __name__ == "__main__":
    main()
