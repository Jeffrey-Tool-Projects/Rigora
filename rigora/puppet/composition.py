"""Multi-track motion compositions: clips on layers (R3.2).

A :class:`Composition` arranges existing motions as *clips* on *layers*.

Semantics, evaluated at composition time ``t``:

* A clip is active while ``start <= t < start + length``; ``length`` defaults
  to the motion's duration. Its local time is ``offset + (t - start)``,
  wrapped by the motion's duration when ``loop`` is set and held at the end
  otherwise.
* A clip's weight is ``weight`` times linear fade-in from ``start`` and
  fade-out to its end.
* Within a layer, active clips apply in list order; each blends from the
  value so far toward its own sample by its weight, so a later clip over an
  earlier one is a crossfade.
* Layers apply in list order — later layers have higher priority. An
  ``override`` layer blends the result toward its value by its weight; an
  ``additive`` layer adds its weighted difference from the parameter's
  default. Muted clips and layers are skipped.
* Only parameters some clip animates are returned; results are clamped to
  each parameter's range.

Storage: the optional ``compositions`` manifest key. Readers that predate it
ignore unknown keys, so they open such files without the compositions and
drop them when saving; documents without compositions are written exactly
as before. :func:`bake_composition` turns a composition into an ordinary
:class:`Motion` for playback and export.
"""
from __future__ import annotations

import math
from rigora.puppet.document import (
    Clip,
    Composition,
    CompositionLayer,
    Motion,
    MotionSegment,
    MotionTrack,
    PuppetDocument,
)
from rigora.puppet.format_values import PuppetFormatError
from rigora.puppet.motion_sampler import sample_motion

LAYER_BLENDS = ("override", "additive")

__all__ = ["Clip", "Composition", "CompositionLayer", "bake_composition", "clip_envelope",
           "clip_length", "clip_time", "composition_to_json", "parse_composition",
           "sample_composition", "validate_composition"]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def clip_length(clip: Clip, motion: Motion) -> float:
    return float(clip.length) if clip.length is not None else float(motion.duration)


def clip_envelope(clip: Clip, motion: Motion, t: float) -> float:
    """Clip weight at composition time ``t``; 0 when inactive or muted."""
    length = clip_length(clip, motion)
    local = t - clip.start
    if clip.muted or local < 0 or local >= length or length <= 0:
        return 0.0
    gain = clip.weight
    if clip.fade_in > 0:
        gain *= min(1.0, local / clip.fade_in)
    if clip.fade_out > 0:
        gain *= min(1.0, (length - local) / clip.fade_out)
    return max(0.0, gain)


def clip_time(clip: Clip, motion: Motion, t: float) -> float:
    local = clip.offset + (t - clip.start)
    duration = float(motion.duration)
    if duration <= 0:
        return 0.0
    if clip.loop:
        return math.fmod(local, duration) if local >= 0 else 0.0
    return min(max(local, 0.0), duration)


def sample_composition(document: PuppetDocument, composition: Composition,
                       t: float) -> dict[str, float]:
    motions = {m.name: m for m in document.motions}
    params = {p.id: p for p in document.parameters}
    result: dict[str, float] = {}

    def base(param_id: str) -> float:
        if param_id in result:
            return result[param_id]
        parameter = params.get(param_id)
        return parameter.default if parameter is not None else 0.0

    for layer in composition.layers:
        if layer.muted or layer.weight <= 0:
            continue
        # Clips composite "over" each other: each carries a value and a coverage,
        # so a later clip fading in crossfades from the earlier one, and the
        # layer then applies its combined coverage once.
        layer_values: dict[str, float] = {}
        coverage: dict[str, float] = {}
        for clip in layer.clips:
            motion = motions.get(clip.motion)
            if motion is None:
                continue
            gain = min(clip_envelope(clip, motion, t), 1.0)
            if gain <= 0:
                continue
            sample = sample_motion(motion, clip_time(clip, motion, t), loop=False)
            for param_id, value in sample.items():
                below = coverage.get(param_id, 0.0)
                total = gain + below * (1.0 - gain)
                previous = layer_values.get(param_id, value)
                layer_values[param_id] = (gain * value + below * (1.0 - gain) * previous) / total
                coverage[param_id] = total
        for param_id, value in layer_values.items():
            amount = layer.weight * coverage[param_id]
            if layer.blend == "additive":
                parameter = params.get(param_id)
                default = parameter.default if parameter is not None else 0.0
                result[param_id] = base(param_id) + (value - default) * amount
            else:
                current = base(param_id)
                result[param_id] = current + (value - current) * min(amount, 1.0)
    for param_id, value in result.items():
        parameter = params.get(param_id)
        if parameter is not None:
            result[param_id] = min(max(value, parameter.min), parameter.max)
    return result


def bake_composition(document: PuppetDocument, composition: Composition, *,
                     fps: float = 30.0, name: str | None = None) -> Motion:
    """Sample at ``fps`` into a linear-keyed :class:`Motion` for playback / export."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    frames = max(1, int(round(composition.duration * fps)))
    times = [min(composition.duration, i / fps) for i in range(frames + 1)]
    samples = [sample_composition(document, composition, t) for t in times]
    params = sorted({p for s in samples for p in s})
    tracks = []
    for param_id in params:
        values = [s.get(param_id, _default(document, param_id)) for s in samples]
        segments = [MotionSegment("linear", (times[i], values[i]), (times[i + 1], values[i + 1]))
                    for i in range(len(times) - 1)]
        tracks.append(MotionTrack(param_id, segments))
    from rigora.puppet.takes import new_take_info
    return Motion(name or f"{composition.name} (baked)", float(composition.duration),
                  tracks=tracks, take=new_take_info(f"composition {composition.name}", fps=fps))


def _default(document: PuppetDocument, param_id: str) -> float:
    parameter = document.parameter(param_id)
    return parameter.default if parameter is not None else 0.0


def validate_composition(document: PuppetDocument, composition: Composition) -> list[str]:
    problems = []
    if composition.duration <= 0:
        problems.append("duration must be positive")
    names = {m.name for m in document.motions}
    seen = set()
    for layer in composition.layers:
        if layer.id in seen:
            problems.append(f"layer id {layer.id!r} is used twice")
        seen.add(layer.id)
        if layer.blend not in LAYER_BLENDS:
            problems.append(f"layer {layer.id}: blend must be override or additive")
        for index, clip in enumerate(layer.clips):
            label = f"layer {layer.id} clip {index}"
            if clip.motion not in names:
                problems.append(f"{label}: no motion {clip.motion!r}")
            if clip.start < 0 or clip.offset < 0 or clip.fade_in < 0 or clip.fade_out < 0:
                problems.append(f"{label}: start, offset and fades must not be negative")
            if clip.length is not None and clip.length <= 0:
                problems.append(f"{label}: length must be positive")
    return problems


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def composition_to_json(composition: Composition) -> dict:
    return {"name": composition.name, "duration": composition.duration, "layers": [
        {"id": layer.id, "blend": layer.blend, "weight": layer.weight, "muted": layer.muted,
         "clips": [{key: value for key, value in vars(clip).items()
                    if not (key == "length" and value is None)} for clip in layer.clips]}
        for layer in composition.layers]}


def _number(raw: dict, key: str, default: float, label: str) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PuppetFormatError(f"{label}.{key} must be a number")
    return float(value)


def parse_composition(raw: object) -> Composition:
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
        raise PuppetFormatError("composition needs a name")
    label = f"composition {raw['name']!r}"
    layers = []
    for layer_raw in raw.get("layers") or []:
        if not isinstance(layer_raw, dict) or not isinstance(layer_raw.get("id"), str):
            raise PuppetFormatError(f"{label}: every layer needs an id")
        blend = layer_raw.get("blend", "override")
        if blend not in LAYER_BLENDS:
            raise PuppetFormatError(f"{label}: unknown layer blend {blend!r}")
        clips = []
        for clip_raw in layer_raw.get("clips") or []:
            if not isinstance(clip_raw, dict) or not isinstance(clip_raw.get("motion"), str):
                raise PuppetFormatError(f"{label}: every clip names a motion")
            clip_label = f"{label} clip"
            length = clip_raw.get("length")
            clips.append(Clip(
                motion=clip_raw["motion"],
                start=_number(clip_raw, "start", 0.0, clip_label),
                offset=_number(clip_raw, "offset", 0.0, clip_label),
                length=None if length is None else _number(clip_raw, "length", 0.0, clip_label),
                loop=bool(clip_raw.get("loop", False)),
                fade_in=_number(clip_raw, "fade_in", 0.0, clip_label),
                fade_out=_number(clip_raw, "fade_out", 0.0, clip_label),
                weight=_number(clip_raw, "weight", 1.0, clip_label),
                muted=bool(clip_raw.get("muted", False))))
        layers.append(CompositionLayer(layer_raw["id"], clips, blend,
                                       _number(layer_raw, "weight", 1.0, label),
                                       bool(layer_raw.get("muted", False))))
    return Composition(raw["name"], _number(raw, "duration", 0.0, label), layers)
