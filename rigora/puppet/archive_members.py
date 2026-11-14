"""Read typed JSON and texture members from a puppet ZIP archive."""
from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from typing import TypeVar

from rigora.puppet.document import (
    Expression,
    Motion,
    PhysicsRig,
)
from rigora.puppet.format_values import PuppetFormatError
from rigora.puppet.physics_codec import _parse_physics_rig

_PUPPET_JSON = "puppet.json"


_PHYSICS_JSON = "physics.json"


_TEXTURES_DIR = "textures/"


_MOTIONS_DIR = "motions/"


_EXPRESSIONS_DIR = "expressions/"


_NamedEntry = TypeVar("_NamedEntry", Motion, Expression)


def _load_textures(zf: zipfile.ZipFile) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for name in zf.namelist():
        if name.startswith(_TEXTURES_DIR) and not name.endswith("/"):
            with zf.open(name) as fp:
                out[name] = fp.read()
    return out


def _load_named_entries(
    zf: zipfile.ZipFile, names: list[str], directory: str, label: str,
    parse: Callable[[str, dict], _NamedEntry],
) -> list[_NamedEntry]:
    out: list[_NamedEntry] = []
    members = set(zf.namelist())
    for name in names:
        path = f"{directory}{name}.json"
        if path not in members:
            raise PuppetFormatError(f"{label} {name!r} listed but {path} missing")
        raw = _read_json(zf, path)
        out.append(parse(name, raw))
    return out


def _load_physics(zf: zipfile.ZipFile, path: str) -> list[PhysicsRig]:
    if path not in zf.namelist():
        raise PuppetFormatError(f"physics path {path!r} missing in archive")
    raw = _read_json(zf, path)
    return [_parse_physics_rig(r) for r in raw.get("rigs", [])]


def _reject_constant(token: str) -> float:
    raise ValueError(f"non-finite number {token}")


def _finite_float(text: str) -> float:
    value = float(text)
    if value in (float("inf"), float("-inf")):
        raise ValueError(f"number {text} is out of range")
    return value


_DIGIT_MAP = bytes(49 if 48 <= i <= 57 else 48 for i in range(256))   # digit -> "1"
_LIMIT = 100


def _may_overflow(data: bytes) -> bool:
    """True when some number might not fit a float.

    A number with fewer than 100 digits in a row and an exponent below 100 is
    under 1e200, so only files with a longer digit run or a larger exponent
    need the per-number check. Both scans run in C over the bytes.
    """
    if data.translate(_DIGIT_MAP).find(b"1" * _LIMIT) >= 0:
        return True
    for marker in (b"e", b"E"):
        pos = data.find(marker)
        while pos >= 0:
            start = pos + 1
            if start < len(data) and data[start] == 43:          # "+"
                start += 1
            end = start
            while end < len(data) and 48 <= data[end] <= 57:
                end += 1
            if end > start and int(data[start:end]) >= _LIMIT:
                return True
            pos = data.find(marker, pos + 1)
    return False


def _read_json(zf: zipfile.ZipFile, path: str) -> dict:
    """Parse a JSON member. ``NaN`` / ``Infinity`` and numbers too large for a
    float are refused: they would reach geometry and the GPU unchecked.

    The per-number overflow check runs only when the bytes contain a number
    that could overflow; checking every float tripled the parse time of the
    bundled rig."""
    with zf.open(path) as fp:
        data = fp.read()
        hooks = {"parse_constant": _reject_constant}
        if _may_overflow(data):
            hooks["parse_float"] = _finite_float
        try:
            return json.loads(data.decode("utf-8"), **hooks)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PuppetFormatError(f"{path}: malformed JSON ({exc})") from exc
        except ValueError as exc:
            raise PuppetFormatError(f"{path}: {exc}") from exc
