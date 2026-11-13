"""Drive a mouth-open parameter from a pre-recorded audio file.

The live input engine already lip-syncs from the microphone; this computes the
same kind of mouth-open envelope from an audio *file* so a puppet can mime to a
recorded clip. The envelope math is pure numpy and the WAV reader uses only the
standard library, so the whole pipeline is unit-testable without extra deps.
:func:`lipsync_motion` turns the curve into a :class:`Motion` on
``ParamMouthOpenY`` that plays the file as its sound — Puppet's **Live > Lip-sync
from Audio File…** adds it to the rig.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from rigora.puppet.document import Motion, MotionSegment, MotionTrack
from rigora.puppet.motion_compress import compress_track

# RMS below this fraction of the loudest frame reads as silence (mouth closed),
# so room tone / breaths don't keep the mouth flapping.
DEFAULT_GATE = 0.04
_INT_DTYPES = {1: np.uint8, 2: np.int16, 4: np.int32}
LIPSYNC_FPS = 30.0
# Keys within this share of the mouth's range of the line through their
# neighbours are dropped, so a minute of speech isn't 1800 keys.
LIPSYNC_TOLERANCE = 0.02


def samples_per_frame(sample_rate: int, fps: float) -> int:
    """Audio samples that map to one animation frame (at least 1)."""
    if sample_rate <= 0 or fps <= 0:
        return 1
    return max(1, round(sample_rate / fps))


def rms_envelope(samples: np.ndarray, sample_rate: int, fps: float) -> np.ndarray:
    """Per-frame RMS amplitude of mono *samples* chunked at the frame rate."""
    window = samples_per_frame(sample_rate, fps)
    if samples.size == 0:
        return np.zeros(0, dtype=np.float64)
    frame_count = -(-samples.size // window)  # ceil
    data = samples.astype(np.float64)
    out = np.zeros(frame_count, dtype=np.float64)
    for index in range(frame_count):
        chunk = data[index * window:(index + 1) * window]
        if chunk.size:
            out[index] = float(np.sqrt(np.mean(chunk * chunk)))
    return out


def normalize_envelope(envelope: np.ndarray, *, gate: float = DEFAULT_GATE) -> np.ndarray:
    """Scale an RMS envelope to ``[0, 1]`` by its peak, gating out near-silence."""
    if envelope.size == 0:
        return envelope
    peak = float(envelope.max())
    if peak <= 0.0:
        return np.zeros_like(envelope)
    normalized = envelope / peak
    normalized[normalized < gate] = 0.0
    return np.clip(normalized, 0.0, 1.0)


def mouth_open_curve(
    samples: np.ndarray,
    sample_rate: int,
    fps: float,
    *,
    gate: float = DEFAULT_GATE,
) -> list[float]:
    """Per-frame mouth-open values in ``[0, 1]`` for mono *samples*."""
    return normalize_envelope(
        rms_envelope(samples, sample_rate, fps), gate=gate).tolist()


def load_wav_mono(path: str | Path) -> tuple[np.ndarray, int]:
    """Read a WAV file as mono float64 samples in ``[-1, 1]`` and its rate.

    Stereo (or more) is averaged to mono. Only 8/16/32-bit integer PCM is
    supported (what ``wave`` exposes); anything else raises ``ValueError``.
    """
    with wave.open(str(path), "rb") as reader:
        rate = reader.getframerate()
        channels = reader.getnchannels()
        width = reader.getsampwidth()
        raw = reader.readframes(reader.getnframes())
    dtype = _INT_DTYPES.get(width)
    if dtype is None:
        raise ValueError(f"unsupported WAV sample width: {width} bytes")
    data = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    # 8-bit PCM is unsigned (centred on 128); wider widths are signed.
    data = ((data - 128.0) / 128.0 if width == 1
            else data / float(2 ** (8 * width - 1)))
    return data, rate


def mouth_open_curve_from_wav(
    path: str | Path,
    fps: float,
    *,
    gate: float = DEFAULT_GATE,
) -> list[float]:
    """Convenience: load a WAV and return its per-frame mouth-open curve."""
    samples, rate = load_wav_mono(path)
    return mouth_open_curve(samples, rate, fps, gate=gate)


def waveform_peaks(path: str | Path, buckets: int = 800) -> tuple[list[tuple[float, float]],
                                                                    float]:
    """``(min, max)`` sample pairs per bucket across the file, and its length in
    seconds — enough to draw a waveform under a motion's curves."""
    samples, rate = load_wav_mono(path)
    seconds = samples.size / rate if rate > 0 else 0.0
    if samples.size == 0 or buckets <= 0:
        return [], seconds
    edges = np.linspace(0, samples.size, min(buckets, samples.size) + 1).astype(int)
    peaks = [(float(samples[a:b].min()), float(samples[a:b].max()))
             for a, b in zip(edges, edges[1:], strict=False) if b > a]
    return peaks, seconds


def lipsync_motion(
    path: str | Path,
    *,
    name: str,
    param_id: str,
    mouth_range: tuple[float, float] = (0.0, 1.0),
    fps: float = LIPSYNC_FPS,
    lead: float = 0.0,
    gate: float = DEFAULT_GATE,
) -> Motion | None:
    """A motion that opens *param_id* with the loudness of the WAV at *path*.

    ``mouth_range`` is ``(closed, fully open)``; the motion lasts as long as
    the audio, ends closed, carries the file as its ``sound_path`` so the
    player plays it in sync, and keeps only the keys that matter. None when
    the file is silent. Raises ``ValueError`` / ``wave.Error`` / ``OSError``
    for a file it cannot read.
    """
    if fps <= 0 or lead < 0:
        raise ValueError("fps must be positive and lead not negative")
    curve = mouth_open_curve_from_wav(path, fps, gate=gate)
    if not curve or max(curve) <= 0.0:
        return None
    closed, wide = mouth_range
    duration = len(curve) / fps
    # ``lead`` opens the mouth slightly before the sound, which reads as in sync.
    points = [(max(0.0, i / fps - lead), closed + value * (wide - closed))
              for i, value in enumerate(curve)]
    points = [p for i, p in enumerate(points) if i == 0 or p[0] > points[i - 1][0]]
    points.append((duration, closed))
    track = MotionTrack(param_id, [
        MotionSegment("linear", a, b) for a, b in zip(points, points[1:], strict=False)
    ])
    track = compress_track(track, tol=LIPSYNC_TOLERANCE * abs(wide - closed))
    from rigora.puppet.takes import new_take_info
    return Motion(name=name, duration=duration, tracks=[track],
                  sound_path=str(Path(path).resolve()),
                  take=new_take_info("lip-sync from audio", fps=fps))


def find_missing_sounds(document) -> list[tuple[str, str]]:
    """``(motion name, sound path)`` for motions whose sound file is gone."""
    return [(m.name, m.sound_path) for m in document.motions
            if m.sound_path and not Path(m.sound_path).is_file()]


def locate_sounds(missing: list[tuple[str, str]], folders) -> dict[str, Path]:
    """First file under ``folders`` with the same file name as each missing sound."""
    found: dict[str, Path] = {}
    wanted = {name: Path(path).name.lower() for name, path in missing}
    for folder in folders:
        root = Path(folder)
        if not root.is_dir():
            continue
        for candidate in sorted(root.rglob("*")):
            lowered = candidate.name.lower()
            for motion_name, file_name in wanted.items():
                if motion_name not in found and lowered == file_name and candidate.is_file():
                    found[motion_name] = candidate
    return found


def relink_sound(document, motion_name: str, path: str | Path) -> None:
    """Point a motion at a sound file; it must be a readable WAV."""
    load_wav_mono(path)
    motion = next((m for m in document.motions if m.name == motion_name), None)
    if motion is None:
        raise ValueError(f"no motion {motion_name!r}")
    motion.sound_path = str(Path(path).resolve())
