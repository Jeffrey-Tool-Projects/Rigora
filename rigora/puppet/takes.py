"""Take management for recorded and generated motions (R3.3).

A take is a :class:`Motion` with a ``take`` record: a unique id, where it
came from, when, at what capture rate and from which inputs. Storing a take
under a name that already exists is an explicit choice — replace the old
motion, keep both under a unique name, or discard the new take — never a
silent overwrite.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from rigora.puppet.document import Motion, PuppetDocument

CONFLICT_REPLACE = "replace"
CONFLICT_RENAME = "rename"
CONFLICT_DISCARD = "discard"
CONFLICT_CHOICES = (CONFLICT_REPLACE, CONFLICT_RENAME, CONFLICT_DISCARD)


def new_take_info(source: str, *, fps: float | None = None, inputs: list[str] | None = None,
                  captured_seconds: float | None = None) -> dict:
    info = {"id": uuid4().hex, "source": source,
            "recorded_at": datetime.now(UTC).isoformat(timespec="seconds")}
    if fps is not None:
        info["fps"] = float(fps)
    if inputs:
        info["inputs"] = sorted(set(inputs))
    if captured_seconds is not None:
        info["captured_seconds"] = round(float(captured_seconds), 3)
    return info


def unique_motion_name(document: PuppetDocument, name: str) -> str:
    taken = {m.name for m in document.motions}
    if name not in taken:
        return name
    index = 2
    while f"{name} ({index})" in taken:
        index += 1
    return f"{name} ({index})"


def name_conflict(document: PuppetDocument, name: str) -> Motion | None:
    return next((m for m in document.motions if m.name == name), None)


def store_take(document: PuppetDocument, motion: Motion, conflict: str) -> str | None:
    """Add ``motion`` to the document resolving a name clash by ``conflict``.

    Returns the stored name, or ``None`` when the take was discarded. A motion
    without a take record gets one with source ``unknown``.
    """
    if conflict not in CONFLICT_CHOICES:
        raise ValueError(f"conflict must be one of {', '.join(CONFLICT_CHOICES)}")
    if motion.take is None:
        motion.take = new_take_info("unknown")
    existing = name_conflict(document, motion.name)
    if existing is not None:
        if conflict == CONFLICT_DISCARD:
            return None
        if conflict == CONFLICT_RENAME:
            motion.name = unique_motion_name(document, motion.name)
        else:
            motion.take = {**motion.take, "replaced": (existing.take or {}).get("id")}
            document.motions = [m for m in document.motions if m is not existing]
    document.motions.append(motion)
    return motion.name


def take_label(motion: Motion) -> str:
    """Short description for lists: source and recording time."""
    take = motion.take or {}
    when = str(take.get("recorded_at", ""))[:19].replace("T", " ")
    parts = [take.get("source", ""), when]
    return " · ".join(p for p in parts if p)
