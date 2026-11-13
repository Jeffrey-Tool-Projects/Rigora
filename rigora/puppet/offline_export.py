"""Offline animation export: fixed time steps, settings, jobs (R3.5 / R3.6).

Frames are sampled at exact times ``start + i / fps`` from a snapshot of the
document, never from a GUI timer, so the frame count and every sampled
value depend only on the settings. Physics runs in its own engine with a
fixed step: it first settles for ``physics_warmup`` seconds at the first
frame's pose, then advances exactly one frame interval (in fixed sub-steps)
per frame. The offline path has no randomness; ``seed`` is recorded with the
job so a future random feature can be reproduced.

Rendering is injected (``render(values) -> HxWx4 uint8``), so the planning,
evaluation, encoding and job logic run and are tested without OpenGL; the
workspace supplies a hidden-canvas renderer. Output is written to a
temporary file beside the target and moved into place only when the whole
export succeeds — a cancelled or failed export leaves no file that could be
mistaken for a finished one.
"""
from __future__ import annotations

import logging
import math
import shutil
import tempfile
from collections.abc import Callable, Iterator
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

import numpy as np

from rigora.puppet.composition import sample_composition
from rigora.puppet.document import Motion, PuppetDocument
from rigora.puppet.motion_sampler import sample_motion
from rigora.puppet.physics import PhysicsEngine
from rigora.puppet.runtime import default_parameter_values

logger = logging.getLogger("rigora.puppet.offline_export")

FORMATS = ("png_sequence", "gif", "mp4", "webm")
CONFLICTS = ("rename", "overwrite", "fail")
PHYSICS_STEP = 1.0 / 120.0

Render = Callable[[dict[str, float]], np.ndarray]


@dataclass
class ExportSettings:
    width: int = 1024
    height: int = 1024
    fps: float = 30.0
    start: float = 0.0
    end: float | None = None
    """Seconds; ``None`` exports to the end of the source."""
    background: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    format: str = "png_sequence"
    conflict: str = "rename"
    physics_warmup: float = 1.0
    seed: int = 0
    include_audio: bool = True
    """Mux the motion's sound into MP4 / WebM when the range starts at 0."""

    def to_dict(self) -> dict:
        return asdict(self)


def encoder_capabilities() -> dict[str, dict]:
    """What each format can store here: alpha, and whether its encoder is installed."""
    try:
        import imageio.v2  # noqa: F401
        imageio_ok = True
    except ImportError:
        imageio_ok = False
    try:
        import imageio_ffmpeg  # noqa: F401
        ffmpeg_ok = imageio_ok
    except ImportError:
        ffmpeg_ok = False
    return {
        "png_sequence": {"alpha": "full", "available": True, "extension": ""},
        "gif": {"alpha": "1-bit", "available": imageio_ok, "extension": ".gif"},
        "mp4": {"alpha": "none", "available": ffmpeg_ok, "extension": ".mp4"},
        "webm": {"alpha": "none", "available": ffmpeg_ok, "extension": ".webm"},
    }


def validate_settings(settings: ExportSettings, source_duration: float) -> list[str]:
    problems = []
    if settings.format not in FORMATS:
        problems.append(f"format must be one of {', '.join(FORMATS)}")
    elif not encoder_capabilities()[settings.format]["available"]:
        problems.append(f"the {settings.format} encoder is not installed")
    if settings.conflict not in CONFLICTS:
        problems.append(f"conflict must be one of {', '.join(CONFLICTS)}")
    if not (16 <= settings.width <= 8192 and 16 <= settings.height <= 8192):
        problems.append("width and height must be 16..8192 pixels")
    if settings.format in ("mp4", "webm") and (settings.width % 2 or settings.height % 2):
        problems.append("video sizes must be even")
    if not 1 <= settings.fps <= 240:
        problems.append("fps must be 1..240")
    end = source_duration if settings.end is None else settings.end
    if not 0 <= settings.start < end:
        problems.append("the range must start at 0 or later and before it ends")
    if end > source_duration + 1e-9:
        problems.append(f"the range ends after the source ({source_duration:g} s)")
    if settings.physics_warmup < 0:
        problems.append("physics warm-up must not be negative")
    if settings.format != "png_sequence" and settings.background[3] < 1.0 \
            and encoder_capabilities()[settings.format]["alpha"] == "none":
        problems.append(f"{settings.format} cannot store transparency; choose an opaque "
                        "background or the PNG sequence")
    return problems


def frame_times(settings: ExportSettings, source_duration: float) -> list[float]:
    """Exact sample times; the last frame starts before the range ends."""
    end = source_duration if settings.end is None else settings.end
    count = max(1, math.ceil((end - settings.start) * settings.fps - 1e-9))
    return [settings.start + index / settings.fps for index in range(count)]


# ---------------------------------------------------------------------------
# Deterministic evaluation
# ---------------------------------------------------------------------------


class FrameSource:
    """Parameter values per frame for a motion or a composition, with physics."""

    def __init__(self, document: PuppetDocument, *, motion: str | None = None,
                 composition: str | None = None) -> None:
        self.document = deepcopy(document)          # later edits cannot change the export
        self.defaults = default_parameter_values(self.document)
        if motion is not None:
            self.motion: Motion | None = next(
                (m for m in self.document.motions if m.name == motion), None)
            if self.motion is None:
                raise ValueError(f"no motion {motion!r}")
            self.composition = None
            self.duration = float(self.motion.duration)
        else:
            self.composition = next(
                (c for c in self.document.compositions if c.name == composition), None)
            if self.composition is None:
                raise ValueError(f"no composition {composition!r}")
            self.motion = None
            self.duration = float(self.composition.duration)
        self.physics = PhysicsEngine()
        self.physics.bind_document(self.document)
        sound = self.motion.sound_path if self.motion is not None else None
        self.sound_path = sound if sound and Path(sound).is_file() else None
        self.missing_sound = bool(sound) and self.sound_path is None
        self._physics_time: float | None = None
        self._outputs: dict[str, float] = {}

    def driven(self, t: float) -> dict[str, float]:
        values = dict(self.defaults)
        if self.motion is not None:
            values.update(sample_motion(self.motion, t, loop=False))
        else:
            values.update(sample_composition(self.document, self.composition, t))
        return values

    def _advance(self, values: dict[str, float], seconds: float) -> None:
        steps = int(round(seconds / PHYSICS_STEP))
        for _ in range(steps):
            self._outputs = self.physics.step(PHYSICS_STEP, values) or self._outputs

    def values(self, t: float, warmup: float) -> dict[str, float]:
        """Values for frame time ``t``; frames must be requested in order."""
        driven = self.driven(t)
        if self.physics.chain_ids():
            if self._physics_time is None:
                self._advance(driven, warmup)
            else:
                self._advance(driven, t - self._physics_time)
            self._physics_time = t
        return {**driven, **self._outputs}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def resolve_destination(path: Path, conflict: str) -> Path:
    if not path.exists() or conflict == "overwrite":
        return path
    if conflict == "fail":
        raise FileExistsError(f"{path} already exists")
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


class _Writer:
    """Writes frames under a temporary name; :meth:`commit` moves it into place."""

    def __init__(self, destination: Path, settings: ExportSettings,
                 audio: str | None = None) -> None:
        self.destination = destination
        self.settings = settings
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.temporary = Path(tempfile.mkdtemp(prefix=".rigora-export-",
                                               dir=destination.parent))
        self.frames = 0
        self._video = None
        if settings.format != "png_sequence":
            import imageio.v2 as imageio
            target = self.temporary / ("out" + destination.suffix)
            kwargs: dict = {"fps": settings.fps}
            if settings.format == "gif":
                kwargs = {"duration": 1.0 / settings.fps, "loop": 0}
            elif audio is not None:
                kwargs.update(audio_path=audio, output_params=["-shortest"],
                              audio_codec="aac" if settings.format == "mp4" else "libopus")
            self._video = imageio.get_writer(str(target), **kwargs)

    def add(self, frame: np.ndarray) -> None:
        if frame.shape != (self.settings.height, self.settings.width, 4):
            raise ValueError(f"renderer returned {frame.shape}, expected "
                             f"{(self.settings.height, self.settings.width, 4)}")
        if self._video is None:
            from PIL import Image
            Image.fromarray(frame, mode="RGBA").save(
                self.temporary / f"frame_{self.frames:05d}.png")
        else:
            self._video.append_data(frame if self.settings.format == "gif" else frame[..., :3])
        self.frames += 1

    def commit(self) -> Path:
        if self._video is not None:
            self._video.close()
            self._video = None
            produced = self.temporary / ("out" + self.destination.suffix)
            if not produced.is_file() or produced.stat().st_size == 0:
                raise OSError("the encoder produced no file")
            produced.replace(self.destination)
        else:
            if self.destination.exists():
                shutil.rmtree(self.destination)
            self.temporary.replace(self.destination)
            return self.destination
        self.discard()
        return self.destination

    def discard(self) -> None:
        if self._video is not None:
            try:
                self._video.close()
            except Exception as exc:   # noqa: BLE001 - imageio raises a zoo while aborting
                logger.debug("closing an aborted export failed: %s", exc)
            self._video = None
        shutil.rmtree(self.temporary, ignore_errors=True)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"


@dataclass
class ExportJob:
    source: FrameSource
    settings: ExportSettings
    target: Path
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    state: str = QUEUED
    progress: int = 0
    total: int = 0
    output: Path | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    def label(self) -> str:
        name = (self.source.motion or self.source.composition).name
        return f"{name} → {self.target.name}"


def run_steps(job: ExportJob, render: Render, *, cancelled: Callable[[], bool]) -> Iterator[int]:
    """Render ``job`` one frame per step; yields the frame number done."""
    settings = job.settings
    problems = validate_settings(settings, job.source.duration)
    if problems:
        raise ValueError("; ".join(problems))
    extension = encoder_capabilities()[settings.format]["extension"]
    target = job.target if job.target.suffix or not extension else job.target.with_suffix(
        extension)
    destination = resolve_destination(target, settings.conflict)
    times = frame_times(settings, job.source.duration)
    job.total = len(times)
    audio = None
    if settings.format in ("mp4", "webm") and settings.include_audio:
        if job.source.missing_sound:
            job.notes.append("the motion's sound file is missing; exported without sound")
        elif job.source.sound_path and settings.start > 0:
            job.notes.append("sound is only included when the range starts at 0")
        else:
            audio = job.source.sound_path
    writer = _Writer(destination, settings, audio)
    try:
        for index, t in enumerate(times):
            if cancelled():
                raise ExportCancelledError(job.id)
            writer.add(render(job.source.values(t, settings.physics_warmup)))
            job.progress = index + 1
            yield index
        job.output = writer.commit()
    except BaseException:
        writer.discard()
        raise


class ExportCancelledError(Exception):
    """The job was cancelled; its partial output was removed."""


class ExportQueue:
    """Runs export jobs one at a time; each :meth:`step` renders one frame so a
    GUI timer can drive it without freezing the editor."""

    def __init__(self, render: Render | None = None, *, render_factory=None) -> None:
        """``render`` draws every job; ``render_factory(job)`` instead makes a
        renderer per job (closed with its ``close()`` when the job ends)."""
        self.render = render
        self.render_factory = render_factory
        self._renderer = None
        self.jobs: list[ExportJob] = []
        self._active: tuple[ExportJob, Iterator[int]] | None = None
        self._cancel: set[str] = set()

    def add(self, job: ExportJob) -> ExportJob:
        self.jobs.append(job)
        return job

    def cancel(self, job_id: str) -> None:
        job = self._job(job_id)
        if job.state == QUEUED:
            job.state = CANCELLED
        elif job.state == RUNNING:
            self._cancel.add(job_id)

    def retry(self, job_id: str) -> ExportJob:
        job = self._job(job_id)
        if job.state not in (FAILED, CANCELLED):
            raise ValueError("only failed or cancelled exports can be retried")
        return self.add(ExportJob(_fresh_source(job.source), job.settings, job.target))

    def busy(self) -> bool:
        return self._active is not None or any(j.state == QUEUED for j in self.jobs)

    def step(self) -> bool:
        """Advance by one frame; ``False`` when nothing is left to do."""
        if self._active is None:
            job = next((j for j in self.jobs if j.state == QUEUED), None)
            if job is None:
                return False
            job.state = RUNNING
            try:
                renderer = self.render_factory(job) if self.render_factory else self.render
            except (RuntimeError, OSError) as exc:
                job.state, job.error = FAILED, str(exc)
                return True
            self._renderer = renderer
            self._active = (job, run_steps(job, renderer,
                                           cancelled=lambda j=job: j.id in self._cancel))
        job, frames = self._active
        try:
            next(frames)
            return True
        except StopIteration:
            job.state = DONE
        except ExportCancelledError:
            job.state, job.error = CANCELLED, "cancelled"
        except (ValueError, OSError, RuntimeError) as exc:
            job.state, job.error = FAILED, str(exc)
        self._finish_active()
        return True

    def _finish_active(self) -> None:
        self._active = None
        renderer, self._renderer = self._renderer, None
        if renderer is not None and renderer is not self.render and hasattr(renderer, "close"):
            renderer.close()

    def shutdown(self) -> None:
        """Cancel everything and release the active renderer."""
        for job in self.jobs:
            if job.state == QUEUED:
                job.state = CANCELLED
        if self._active is not None:
            job, frames = self._active
            frames.close()          # discards the partial output
            job.state, job.error = CANCELLED, "cancelled"
            self._finish_active()

    def run_all(self) -> None:
        while self.step():
            pass

    def _job(self, job_id: str) -> ExportJob:
        return next(j for j in self.jobs if j.id == job_id)


def _fresh_source(source: FrameSource) -> FrameSource:
    if source.motion is not None:
        return FrameSource(source.document, motion=source.motion.name)
    return FrameSource(source.document, composition=source.composition.name)
