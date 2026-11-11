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
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LICENSES = (
    "numpy", "Pillow", "PySide6", "PySide6_Addons", "PySide6_Essentials",
    "shiboken6", "PyOpenGL", "imageio", "imageio-ffmpeg", "Nuitka",
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
    if (result.get("status") != "passed" or result.get("compiler") != "Nuitka"
            or not result.get("frozen")):
        raise RuntimeError(f"Compiled executable verification failed: {result}")


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
        [sys.executable, "-m", "nuitka", "--mode=standalone", "--msvc=latest", "--jobs=4",
         "--assume-yes-for-downloads", "--enable-plugin=pyside6", "--windows-console-mode=disable",
         "--output-filename=Rigora.exe", "--output-folder-name=Rigora", f"--output-dir={output}",
         f"--report={output / 'compilation-report.xml'}", "--include-distribution-metadata=rigora",
         f"--include-data-dir={ROOT / 'rigora' / 'resources'}=rigora/resources",
         f"--include-data-files={ROOT / 'rigora' / 'puppet' / 'FORMAT.md'}=rigora/puppet/FORMAT.md",
         "--include-module=OpenGL.platform.win32", "--include-module=OpenGL.arrays.numpymodule",
         "--include-module=imageio.plugins.ffmpeg", "--include-module=imageio.plugins.pillow",
         "--nofollow-import-to=cv2,mediapipe,sounddevice,pyvirtualcam,NDIlib,pynput",
         str(ROOT / "packaging" / "windows_entry.py")], cwd=ROOT, check=True,
    )
    bundle = output / "Rigora.dist"
    copy_licenses(bundle)
    verify_executable(bundle / "Rigora.exe", output / "smoke-report.json")
    if args.native:
        verify_executable(bundle / "Rigora.exe", output / "native-report.json", native=True)
    archive = output / "Rigora-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as packaged:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                packaged.write(path, Path("Rigora") / path.relative_to(bundle))
    with archive.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    (output / "SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    print(json.dumps({"version": version, "archive": str(archive), "sha256": checksum}))


if __name__ == "__main__":
    main()
