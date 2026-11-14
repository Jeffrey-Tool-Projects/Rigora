"""Temporarily deny writes only inside a freshly created verification environment."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import subprocess


@contextmanager
def readonly_package(interpreter: Path, environment: Path):
    result = subprocess.run(
        [str(interpreter), "-I", "-c",
         "import pathlib, rigora; print(pathlib.Path(rigora.__file__).resolve().parent)"],
        capture_output=True, text=True, check=True,
    )
    package = Path(result.stdout.strip()).resolve(strict=True)
    if not package.is_relative_to(environment.resolve(strict=True)):
        raise RuntimeError("Refusing to change permissions outside the verification environment")
    if os.name == "nt":
        identity = subprocess.run(["whoami"], capture_output=True, text=True,
                                  check=True).stdout.strip()
        subprocess.run(["icacls", str(package), "/deny",
                        f"{identity}:(OI)(CI)(WD,AD,WEA,WA)"], check=True)
        def restore():
            subprocess.run(["icacls", str(package), "/remove:d", identity], check=True)
    else:
        paths = [package, *package.rglob("*")]
        modes = {path: path.stat().st_mode for path in paths}
        for path, mode in modes.items():
            path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        def restore():
            for path, mode in modes.items():
                path.chmod(mode)
    try:
        probe = subprocess.run(
            [str(interpreter), "-I", "-c",
             "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'probe')",
             str(package / "readonly-probe")], capture_output=True, text=True, check=False,
        )
        if probe.returncode == 0 or "PermissionError" not in probe.stderr:
            raise RuntimeError("OS permissions did not deny a package-directory write")
        yield
    finally:
        restore()
