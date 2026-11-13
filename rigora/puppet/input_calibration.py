"""Device choice and calibration for live inputs (R4.1). Qt-free.

An :class:`InputProfile` names the camera and microphone to use and how raw
tracking values become parameter values:

* ``neutral`` — the raw value measured while the performer sits at rest;
  it maps to the parameter's default.
* ``sensitivity`` multiplies movement away from neutral; ``invert`` flips it.
* ``dead_zone`` ignores movement smaller than this (in parameter units).
* ``smoothing`` 0..0.95 is the share of the previous value kept per 1/30 s,
  so it behaves the same at any frame rate.

When tracking is lost for ``lost_after`` seconds, the values ease to the
profile's neutral pose (the parameter defaults unless set) over
``return_seconds`` instead of freezing mid-expression.

Profiles live in the settings store under ``puppet_input_profiles``.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from statistics import median

PROFILES_KEY = "puppet_input_profiles"
ACTIVE_KEY = "puppet_input_profile"
DEFAULT_PROFILE = "Default"


def _clamped(value, low: float, high: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return min(high, max(low, number))


@dataclass
class ChannelCalibration:
    neutral: float = 0.0
    sensitivity: float = 1.0
    dead_zone: float = 0.0
    smoothing: float = 0.0
    invert: bool = False

    @classmethod
    def from_dict(cls, data) -> ChannelCalibration:
        data = data if isinstance(data, dict) else {}
        return cls(neutral=_clamped(data.get("neutral"), -1e4, 1e4, 0.0),
                   sensitivity=_clamped(data.get("sensitivity"), 0.0, 10.0, 1.0),
                   dead_zone=_clamped(data.get("dead_zone"), 0.0, 1e4, 0.0),
                   smoothing=_clamped(data.get("smoothing"), 0.0, 0.95, 0.0),
                   invert=bool(data.get("invert", False)))


@dataclass
class InputProfile:
    name: str = DEFAULT_PROFILE
    camera_index: int = 0
    camera_name: str = ""
    mic_device: str = ""
    sensitivity: float = 1.0
    dead_zone: float = 0.0
    smoothing: float = 0.3
    channels: dict[str, ChannelCalibration] = field(default_factory=dict)
    mic_gain: float = 1.0
    mic_gate: float = 0.05
    mic_smoothing: float = 0.3
    lost_after: float = 0.5
    return_seconds: float = 0.6
    neutral_pose: dict[str, float] = field(default_factory=dict)

    def channel(self, param: str) -> ChannelCalibration:
        found = self.channels.get(param)
        if found is not None:
            return found
        return ChannelCalibration(neutral=math.nan, sensitivity=self.sensitivity,
                                  dead_zone=self.dead_zone, smoothing=self.smoothing)

    def to_dict(self) -> dict:
        out = asdict(self)
        out["channels"] = {k: asdict(v) for k, v in self.channels.items()}
        return out

    @classmethod
    def from_dict(cls, data) -> InputProfile:
        data = data if isinstance(data, dict) else {}
        channels = data.get("channels") if isinstance(data.get("channels"), dict) else {}
        pose = data.get("neutral_pose") if isinstance(data.get("neutral_pose"), dict) else {}
        index = data.get("camera_index", 0)
        return cls(
            name=str(data.get("name") or DEFAULT_PROFILE)[:80],
            camera_index=index if isinstance(index, int) and 0 <= index < 64 else 0,
            camera_name=str(data.get("camera_name") or "")[:200],
            mic_device=str(data.get("mic_device") or "")[:200],
            sensitivity=_clamped(data.get("sensitivity"), 0.0, 10.0, 1.0),
            dead_zone=_clamped(data.get("dead_zone"), 0.0, 1e4, 0.0),
            smoothing=_clamped(data.get("smoothing"), 0.0, 0.95, 0.3),
            channels={str(k): ChannelCalibration.from_dict(v) for k, v in channels.items()},
            mic_gain=_clamped(data.get("mic_gain"), 0.0, 20.0, 1.0),
            mic_gate=_clamped(data.get("mic_gate"), 0.0, 1.0, 0.05),
            mic_smoothing=_clamped(data.get("mic_smoothing"), 0.0, 0.95, 0.3),
            lost_after=_clamped(data.get("lost_after"), 0.0, 30.0, 0.5),
            return_seconds=_clamped(data.get("return_seconds"), 0.0, 10.0, 0.6),
            neutral_pose={str(k): _clamped(v, -1e4, 1e4, 0.0) for k, v in pose.items()},
        )


def _ema(previous: float | None, value: float, smoothing: float, dt: float) -> float:
    if previous is None or smoothing <= 0:
        return value
    keep = smoothing ** max(0.0, dt * 30.0)
    return keep * previous + (1.0 - keep) * value


class Calibrator:
    """Turns raw tracker values into calibrated parameter values."""

    def __init__(self, profile: InputProfile,
                 ranges: dict[str, tuple[float, float, float]]) -> None:
        self.profile = profile
        self.ranges = dict(ranges)          # param -> (min, max, default)
        self._last: dict[str, float] = {}
        self._last_time: float | None = None
        self._last_seen: float | None = None
        self._lost_from: dict[str, float] | None = None
        self._lost_since: float | None = None
        self._mic: dict[str, float] = {}

    def reset(self) -> None:
        self._last.clear()
        self._mic.clear()
        self._last_time = self._last_seen = self._lost_since = None
        self._lost_from = None

    def _limits(self, param: str) -> tuple[float, float, float]:
        return self.ranges.get(param, (-math.inf, math.inf, 0.0))

    def calibrate_value(self, param: str, raw: float) -> float:
        low, high, default = self._limits(param)
        channel = self.profile.channel(param)
        neutral = default if math.isnan(channel.neutral) else channel.neutral
        delta = (raw - neutral) * (-1.0 if channel.invert else 1.0)
        if abs(delta) <= channel.dead_zone:
            delta = 0.0
        else:
            delta = math.copysign(abs(delta) - channel.dead_zone, delta)
        return min(high, max(low, default + delta * channel.sensitivity))

    def apply(self, raw: dict[str, float], now: float) -> dict[str, float]:
        """Calibrate one frame of tracked values (tracking is present)."""
        dt = 0.0 if self._last_time is None else now - self._last_time
        self._last_time = self._last_seen = now
        self._lost_from = self._lost_since = None
        out: dict[str, float] = {}
        for param, value in raw.items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(number):
                continue
            target = self.calibrate_value(param, number)
            smoothed = _ema(self._last.get(param), target,
                            self.profile.channel(param).smoothing, dt)
            self._last[param] = out[param] = smoothed
        return out

    def neutral_value(self, param: str) -> float:
        if param in self.profile.neutral_pose:
            low, high, _ = self._limits(param)
            return min(high, max(low, self.profile.neutral_pose[param]))
        return self._limits(param)[2]

    def lost(self, now: float) -> dict[str, float]:
        """Values to write while tracking is missing: nothing until ``lost_after``
        has passed, then an ease to the neutral pose; ``{}`` once settled."""
        if self._last_seen is None or not self._last:
            return {}
        if now - self._last_seen < self.profile.lost_after:
            return {}
        if self._lost_from is None:
            # The ease starts when the grace period ended, not at the first call.
            self._lost_from = dict(self._last)
            self._lost_since = self._last_seen + self.profile.lost_after
        span = self.profile.return_seconds
        t = 1.0 if span <= 0 else min(1.0, (now - self._lost_since) / span)
        eased = t * t * (3 - 2 * t)
        out = {p: v + (self.neutral_value(p) - v) * eased for p, v in self._lost_from.items()}
        self._last_time = now
        if t >= 1.0:
            self._last.clear()
            self._last_seen = None
        else:
            self._last.update(out)
        return out

    def apply_mic(self, viseme: dict[str, float], now: float) -> dict[str, float]:
        """Gain, noise gate and smoothing for lip-sync values in 0..1."""
        dt = 0.0 if self._last_time is None else now - self._last_time
        out = {}
        for param, value in viseme.items():
            level = float(value) * self.profile.mic_gain
            if abs(level) < self.profile.mic_gate:
                level = 0.0
            low, high, _ = self._limits(param)
            level = min(high, max(low, level))
            self._mic[param] = out[param] = _ema(self._mic.get(param), level,
                                                 self.profile.mic_smoothing, dt)
        return out


def capture_neutral(samples: list[dict[str, float]]) -> dict[str, float]:
    """Median raw value per parameter over frames recorded at rest."""
    collected: dict[str, list[float]] = {}
    for frame in samples:
        for param, value in frame.items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                collected.setdefault(param, []).append(number)
    return {param: float(median(values)) for param, values in collected.items() if values}


def apply_neutral(profile: InputProfile, neutral: dict[str, float]) -> InputProfile:
    for param, value in neutral.items():
        channel = profile.channels.get(param) or ChannelCalibration(
            sensitivity=profile.sensitivity, dead_zone=profile.dead_zone,
            smoothing=profile.smoothing)
        channel.neutral = value
        profile.channels[param] = channel
    return profile


def parameter_ranges(document) -> dict[str, tuple[float, float, float]]:
    if document is None:
        return {}
    return {p.id: (float(p.min), float(p.max), float(p.default)) for p in document.parameters}


# ---- storage ----------------------------------------------------------------


def load_profiles(store) -> dict[str, InputProfile]:
    raw = store.get(PROFILES_KEY) if hasattr(store, "get") else None
    profiles = {}
    if isinstance(raw, dict):
        for name, data in list(raw.items())[:50]:
            profile = InputProfile.from_dict({**(data if isinstance(data, dict) else {}),
                                              "name": name})
            profiles[profile.name] = profile
    profiles.setdefault(DEFAULT_PROFILE, InputProfile())
    return profiles


def active_profile(store) -> InputProfile:
    profiles = load_profiles(store)
    name = store.get(ACTIVE_KEY) if hasattr(store, "get") else None
    return profiles.get(name if isinstance(name, str) else "", profiles[DEFAULT_PROFILE])


def save_profile(store, profile: InputProfile, *, activate: bool = True) -> None:
    raw = store.get(PROFILES_KEY)
    profiles = dict(raw) if isinstance(raw, dict) else {}
    profiles[profile.name] = profile.to_dict()
    store[PROFILES_KEY] = profiles
    if activate:
        store[ACTIVE_KEY] = profile.name


def delete_profile(store, name: str) -> bool:
    raw = store.get(PROFILES_KEY)
    if not isinstance(raw, dict) or name not in raw or name == DEFAULT_PROFILE:
        return False
    profiles = dict(raw)
    del profiles[name]
    store[PROFILES_KEY] = profiles
    if store.get(ACTIVE_KEY) == name:
        store[ACTIVE_KEY] = DEFAULT_PROFILE
    return True
