"""Write or check SHA256SUMS.txt for release artifacts.

    py -3 scripts/release_checksums.py DIR            # write DIR/SHA256SUMS.txt
    py -3 scripts/release_checksums.py DIR --check    # verify every listed file

Covers wheels, sdists and the Windows archive in DIR (not subfolders).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

PATTERNS = ("*.whl", "*.tar.gz", "*.zip")
SUMS = "SHA256SUMS.txt"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifacts(folder: Path) -> list[Path]:
    return sorted({p for pattern in PATTERNS for p in folder.glob(pattern) if p.is_file()})


def write(folder: Path) -> str:
    lines = [f"{digest(path)}  {path.name}" for path in artifacts(folder)]
    if not lines:
        raise SystemExit(f"no release artifacts in {folder}")
    text = "\n".join(lines) + "\n"
    (folder / SUMS).write_text(text, encoding="utf-8")
    return text


def check(folder: Path) -> list[str]:
    problems = []
    listed = {}
    for line in (folder / SUMS).read_text(encoding="utf-8").splitlines():
        expected, _, name = line.partition("  ")
        listed[name] = expected
        path = folder / name
        if not path.is_file():
            problems.append(f"{name}: missing")
        elif digest(path) != expected:
            problems.append(f"{name}: checksum differs")
    problems += [f"{p.name}: not listed" for p in artifacts(folder) if p.name not in listed]
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        problems = check(args.folder)
        print("\n".join(problems) if problems else "all checksums match")
        return 1 if problems else 0
    sys.stdout.write(write(args.folder))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
