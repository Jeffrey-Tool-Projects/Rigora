"""Key-level motion editing: select, move, scale, copy / paste, snap, tangents (R3.1).

A track is a chain of segments whose endpoints are its *keys*: key 0 is the
first segment's ``p0`` and key ``i`` (i ≥ 1) is segment ``i-1``'s ``p1``.
Every operation keeps that chain consistent (``segments[i].p1 ==
segments[i + 1].p0``), keeps keys in time order, carries bezier control
points along with the keys they belong to, and works on plain dataclasses so
the editor can wrap any of them in one undoable edit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from rigora.puppet.document import Motion, MotionSegment, MotionTrack

TANGENT_MODES = ("linear", "smooth", "flat", "stepped")
_EPSILON = 1e-6


def keys(track: MotionTrack) -> list[tuple[float, float]]:
    if not track.segments:
        return []
    return [tuple(track.segments[0].p0)] + [tuple(s.p1) for s in track.segments]


def keys_in_range(track: MotionTrack, start: float, end: float,
                  low: float | None = None, high: float | None = None) -> list[int]:
    """Indices of keys inside a time range and, optionally, a value range."""
    t0, t1 = sorted((start, end))
    return [i for i, (t, v) in enumerate(keys(track))
            if t0 - _EPSILON <= t <= t1 + _EPSILON
            and (low is None or v >= low) and (high is None or v <= high)]


def snap_time(t: float, step: float | None) -> float:
    """Nearest multiple of ``step`` (seconds); unchanged when snapping is off."""
    if not step or step <= 0:
        return t
    return round(round(t / step) * step, 9)


def filter_tracks(motion: Motion, text: str) -> list[MotionTrack]:
    needle = text.strip().lower()
    return [t for t in motion.tracks if not needle or needle in t.param_id.lower()]


# ---------------------------------------------------------------------------
# Rebuilding a track from keys while keeping segment shapes
# ---------------------------------------------------------------------------


@dataclass
class _Span:
    """A segment's type and bezier controls relative to its endpoints."""

    type: str
    c0: tuple[float, float] | None
    c1: tuple[float, float] | None


def _relative(segment: MotionSegment) -> _Span:
    if segment.type != "cubic-bezier" or segment.c0 is None or segment.c1 is None:
        return _Span(segment.type, None, None)
    (t0, v0), (t1, v1) = segment.p0, segment.p1
    width = (t1 - t0) or 1.0
    return _Span(segment.type,
                 ((segment.c0[0] - t0) / width, segment.c0[1] - v0),
                 ((segment.c1[0] - t0) / width, segment.c1[1] - v1))


def _segment(span: _Span, p0, p1) -> MotionSegment:
    if span.type != "cubic-bezier" or span.c0 is None:
        return MotionSegment(span.type, tuple(p0), tuple(p1))
    width = p1[0] - p0[0]
    return MotionSegment("cubic-bezier", tuple(p0), tuple(p1),
                         (p0[0] + span.c0[0] * width, p0[1] + span.c0[1]),
                         (p0[0] + span.c1[0] * width, p1[1] + span.c1[1]))


def _rebuild(track: MotionTrack, points: list[tuple[float, float]], spans: list[_Span]) -> None:
    track.segments = [_segment(spans[i], points[i], points[i + 1])
                      for i in range(len(points) - 1)]


def _clamp_time(t: float, duration: float | None) -> float:
    t = max(0.0, t)
    return t if duration is None else min(duration, t)


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def move_keys(track: MotionTrack, selection: list[int], dt: float, dv: float, *,
              duration: float | None = None, snap: float | None = None,
              value_range: tuple[float, float] | None = None) -> list[int]:
    """Shift keys in time and value. Moved keys never pass an unselected
    neighbour; a move that would reorder keys is clamped. Returns the moved
    indices. Bezier handles travel with their segment's endpoints."""
    points = keys(track)
    chosen = sorted({i for i in selection if 0 <= i < len(points)})
    if not chosen:
        return []
    spans = [_relative(s) for s in track.segments]
    fixed = [i for i in range(len(points)) if i not in chosen]
    for index in chosen:
        t, v = points[index]
        new_t = _clamp_time(snap_time(t + dt, snap), duration)
        lower = max((points[j][0] for j in fixed if j < index), default=0.0)
        upper = min((points[j][0] for j in fixed if j > index), default=math.inf)
        new_t = min(max(new_t, lower + _EPSILON if index else lower), upper - _EPSILON)
        new_v = v + dv
        if value_range is not None:
            new_v = min(max(new_v, value_range[0]), value_range[1])
        points[index] = (new_t, new_v)
    if any(b[0] < a[0] for a, b in zip(points, points[1:], strict=False)):
        return []    # a selection squeezed past itself; refuse rather than reorder
    _rebuild(track, points, spans)
    return chosen


def scale_keys(track: MotionTrack, selection: list[int], factor: float, *,
               pivot: float | None = None, duration: float | None = None) -> list[int]:
    """Stretch the time spacing of a contiguous key range around ``pivot``
    (default: its first key). Keys after the range shift to keep their gaps."""
    points = keys(track)
    chosen = sorted({i for i in selection if 0 <= i < len(points)})
    if len(chosen) < 2 or factor <= 0:
        return []
    if chosen != list(range(chosen[0], chosen[-1] + 1)):
        raise ValueError("scale a contiguous range of keys")
    spans = [_relative(s) for s in track.segments]
    first, last = chosen[0], chosen[-1]
    origin = points[first][0] if pivot is None else pivot
    for index in chosen:
        t, v = points[index]
        points[index] = (origin + (t - origin) * factor, v)
    shift = points[last][0] - keys(track)[last][0]
    for index in range(last + 1, len(points)):
        t, v = points[index]
        points[index] = (t + shift, v)
    if points[0][0] < -_EPSILON or (duration is not None and points[-1][0] > duration + _EPSILON):
        raise ValueError("scaled keys would leave the motion's duration")
    _rebuild(track, points, spans)
    return chosen


@dataclass(frozen=True)
class KeyClip:
    """Copied keys with times relative to the first one and the segment shapes
    between consecutive copied keys."""

    param_id: str
    points: tuple[tuple[float, float], ...]
    spans: tuple[_Span, ...]


def copy_keys(track: MotionTrack, selection: list[int]) -> KeyClip:
    points = keys(track)
    chosen = sorted({i for i in selection if 0 <= i < len(points)})
    if not chosen:
        raise ValueError("select keys to copy")
    start = points[chosen[0]][0]
    relative = tuple((points[i][0] - start, points[i][1]) for i in chosen)
    spans = tuple(_relative(track.segments[i]) if i + 1 in chosen
                  else _Span("linear", None, None) for i in chosen[:-1])
    return KeyClip(track.param_id, relative, spans)


def paste_keys(track: MotionTrack, clip: KeyClip, at: float, *,
               duration: float | None = None) -> list[int]:
    """Insert ``clip`` starting at time ``at``; existing keys inside the pasted
    span are replaced. Returns the indices of the pasted keys."""
    span_end = at + clip.points[-1][0]
    if at < 0 or (duration is not None and span_end > duration + _EPSILON):
        raise ValueError("pasted keys would leave the motion's duration")
    old_points = keys(track)
    old_spans = [_relative(s) for s in track.segments]
    before = [(p, old_spans[i] if i < len(old_spans) else None)
              for i, p in enumerate(old_points) if p[0] < at - _EPSILON]
    after = [(p, old_spans[i] if i < len(old_spans) else None)
             for i, p in enumerate(old_points) if p[0] > span_end + _EPSILON]
    pasted = [(t + at, v) for t, v in clip.points]
    points = [p for p, _ in before] + pasted + [p for p, _ in after]
    spans = ([s or _Span("linear", None, None) for _, s in before[:-1]]
             + ([_Span("linear", None, None)] if before else [])
             + list(clip.spans)
             + ([_Span("linear", None, None)] if after else [])
             + [s or _Span("linear", None, None) for _, s in after[:-1]])
    if len(points) == 1:
        points.append(points[0])
        spans = [_Span("linear", None, None)]
    _rebuild(track, points, spans)
    first = len(before)
    return list(range(first, first + len(pasted)))


def set_tangents(track: MotionTrack, selection: list[int], mode: str) -> list[int]:
    """Shape the segments around the selected keys.

    ``linear`` straight lines; ``stepped`` hold until the next key; ``flat``
    bezier handles level with each key (ease in and out); ``smooth`` bezier
    handles along the slope between the neighbouring keys (Catmull-Rom).
    """
    if mode not in TANGENT_MODES:
        raise ValueError(f"tangent mode must be one of {', '.join(TANGENT_MODES)}")
    points = keys(track)
    chosen = sorted({i for i in selection if 0 <= i < len(points)})
    touched = sorted({s for i in chosen for s in (i - 1, i) if 0 <= s < len(track.segments)})
    for index in touched:
        p0, p1 = points[index], points[index + 1]
        if mode in ("linear", "stepped"):
            track.segments[index] = MotionSegment(mode, p0, p1)
            continue
        third = (p1[0] - p0[0]) / 3.0
        slope0 = 0.0 if mode == "flat" else _slope(points, index)
        slope1 = 0.0 if mode == "flat" else _slope(points, index + 1)
        track.segments[index] = MotionSegment(
            "cubic-bezier", p0, p1, (p0[0] + third, p0[1] + slope0 * third),
            (p1[0] - third, p1[1] - slope1 * third))
    return touched


def _slope(points: list[tuple[float, float]], index: int) -> float:
    before = points[max(0, index - 1)]
    after = points[min(len(points) - 1, index + 1)]
    width = after[0] - before[0]
    return 0.0 if width <= _EPSILON else (after[1] - before[1]) / width
