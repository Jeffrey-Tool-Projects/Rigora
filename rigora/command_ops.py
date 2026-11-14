"""Shared headless operations for the CLI, MCP and embedding hosts (R6.1 / R6.2).

Each operation calls the same core functions the editor uses (PSD import
plans, the rig doctor, asset updates, motion tools, compositions, offline
export), so the CLI, MCP and GUI cannot drift apart.

Rules every command here follows:

* Inputs are validated against the command's JSON schema before running.
* Outputs go to an explicit ``destination``. An existing file is an
  ``output_exists`` error unless ``overwrite`` is true; writes are atomic.
* Failures raise :class:`CommandError` with a stable ``code`` and the CLI exit
  status for it. Diagnostics never go to standard output.
* Model-only commands never import Qt. Commands that render say so in their
  result (``requires``) and fail with ``capability_missing`` without GL.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_OUTPUT_EXISTS = 3
EXIT_CAPABILITY = 4
EXIT_CANCELLED = 130


class CommandError(Exception):
    """A failure with a machine-readable code and its CLI exit status."""

    def __init__(self, code: str, message: str, exit_code: int = EXIT_FAILED) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self)}


def _existing_file(path: str, label: str = "path") -> Path:
    if not isinstance(path, str) or not path:
        raise CommandError("invalid_input", f"{label} must be a non-empty string")
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise CommandError("not_found", f"{label} {candidate} does not exist")
    return candidate


def _destination(path: str, overwrite: bool) -> Path:
    if not isinstance(path, str) or not path:
        raise CommandError("invalid_input", "destination must be a non-empty string")
    target = Path(path).expanduser()
    if not target.parent.exists():
        raise CommandError("not_found", f"destination folder {target.parent} does not exist")
    if target.exists() and not overwrite:
        raise CommandError("output_exists",
                           f"{target} exists; pass overwrite to replace it", EXIT_OUTPUT_EXISTS)
    return target


def _load(path: str):
    from rigora.puppet.document_io import PuppetFormatError, load_puppet
    try:
        return load_puppet(_existing_file(path))
    except PuppetFormatError as exc:
        raise CommandError("invalid_input", str(exc)) from exc


def _save(document, destination: Path) -> None:
    from rigora.puppet.document_io import save_puppet
    save_puppet(document, destination)


# ---------------------------------------------------------------------------
# Import and repair
# ---------------------------------------------------------------------------


def psd_preview(source: str) -> dict[str, Any]:
    from rigora.puppet.psd_import import preview_psd
    try:
        return preview_psd(_existing_file(source, "source")).to_dict()
    except ValueError as exc:
        raise CommandError("invalid_input", str(exc)) from exc


def puppet_from_psd(source: str, destination: str, *, overwrite: bool = False,
                    auto_rig: bool = True) -> dict[str, Any]:
    from rigora.puppet.psd_import import plan_psd_import
    target = _destination(destination, overwrite)
    try:
        plan = plan_psd_import(_existing_file(source, "source"))
        document = plan.build(enable_auto_rig=bool(auto_rig))
    except ValueError as exc:
        raise CommandError("invalid_input", str(exc)) from exc
    _save(document, target)
    return {"destination": str(target), "drawables": len(document.drawables),
            "differences": [d.to_dict() for d in plan.preview.differences]}


def cubism_preview(path: str, against: str | None = None) -> dict[str, Any]:
    from rigora.puppet.cubism_import_common import CubismFormatError
    from rigora.puppet.cubism_preview import preview_cubism_model
    document = _load(against) if against else None
    try:
        return preview_cubism_model(_existing_file(path), document=document).to_dict()
    except CubismFormatError as exc:
        raise CommandError("invalid_input", str(exc)) from exc


def rig_doctor(path: str, fixes: list[str] | None = None, destination: str | None = None,
               *, overwrite: bool = False) -> dict[str, Any]:
    """Diagnose; with ``fixes`` (finding ids, or ``["safe"]`` for mesh and weight
    repairs) and ``destination``, apply them and save."""
    from rigora.puppet.rig_doctor import apply_fixes, diagnose, preview_fixes
    document = _load(path)
    findings = diagnose(document)
    wanted = list(fixes or [])
    if wanted == ["safe"]:
        wanted = [f.id for f in findings if f.fixable and f.kind in ("mesh", "weights")]
    result: dict[str, Any] = {"findings": [f.to_dict() for f in findings]}
    if destination is None:
        if not wanted:
            return result
        result["preview"] = preview_fixes(document, wanted).to_dict()
        return result
    target = _destination(destination, overwrite)
    result["applied"] = apply_fixes(document, wanted).to_dict()
    _save(document, target)
    result["destination"] = str(target)
    return result


def update_art(path: str, psd: str, destination: str | None = None, *,
               overwrite: bool = False, actions: dict | None = None,
               mapping: dict | None = None) -> dict[str, Any]:
    """Plan an art update; with ``destination``, apply it and save."""
    from rigora.puppet.asset_update import apply_asset_update, plan_asset_update
    from rigora.puppet.psd_import import plan_psd_import
    document = _load(path)
    try:
        plan = plan_asset_update(document, plan_psd_import(_existing_file(psd, "psd")),
                                 mapping=mapping)
    except ValueError as exc:
        raise CommandError("invalid_input", str(exc)) from exc
    result: dict[str, Any] = {"plan": plan.to_dict()}
    if destination is None:
        return result
    target = _destination(destination, overwrite)
    try:
        result["applied"] = apply_asset_update(document, plan, actions).to_dict()
    except ValueError as exc:
        raise CommandError("invalid_input", str(exc)) from exc
    _save(document, target)
    result["destination"] = str(target)
    return result


# ---------------------------------------------------------------------------
# Motions
# ---------------------------------------------------------------------------


def _motion(document, name: str):
    motion = next((m for m in document.motions if m.name == name), None)
    if motion is None:
        raise CommandError("not_found", f"no motion {name!r}")
    return motion


def motion_compress(path: str, motion: str, destination: str, *, tolerance: float = 1.0,
                    overwrite: bool = False) -> dict[str, Any]:
    """Drop keys within ``tolerance`` percent of each parameter's range."""
    from rigora.puppet.motion_compress import compress_track, count_keys
    if not 0 <= tolerance <= 25:
        raise CommandError("invalid_input", "tolerance must be 0..25 percent")
    target = _destination(destination, overwrite)
    document = _load(path)
    chosen = _motion(document, motion)
    ranges = {p.id: (p.min, p.max) for p in document.parameters}
    before = sum(count_keys(t) for t in chosen.tracks)
    for track in chosen.tracks:
        low, high = ranges.get(track.param_id, (-1.0, 1.0))
        track.segments[:] = compress_track(track, tol=tolerance / 100 * (high - low)).segments
    after = sum(count_keys(t) for t in chosen.tracks)
    _save(document, target)
    return {"destination": str(target), "keys_before": before, "keys_after": after}


def bake_composition(path: str, composition: str, destination: str, *, fps: float = 30.0,
                     overwrite: bool = False) -> dict[str, Any]:
    from rigora.puppet.composition import bake_composition as bake
    from rigora.puppet.takes import CONFLICT_RENAME, store_take
    target = _destination(destination, overwrite)
    document = _load(path)
    chosen = next((c for c in document.compositions if c.name == composition), None)
    if chosen is None:
        raise CommandError("not_found", f"no composition {composition!r}")
    try:
        baked = bake(document, chosen, fps=fps)
    except ValueError as exc:
        raise CommandError("invalid_input", str(exc)) from exc
    stored = store_take(document, baked, CONFLICT_RENAME)
    _save(document, target)
    return {"destination": str(target), "motion": stored, "tracks": len(baked.tracks)}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def gl_available() -> bool:
    """Whether a native OpenGL context can be created here (never on offscreen Qt)."""
    import os
    if os.environ.get("QT_QPA_PLATFORM", "") in ("offscreen", "minimal"):
        return False
    try:
        import OpenGL.GL  # noqa: F401
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return False
    app = QApplication.instance() or QApplication([])
    surface = QOffscreenSurface()
    surface.create()
    context = QOpenGLContext()
    ok = context.create() and context.makeCurrent(surface)
    if ok:
        context.doneCurrent()
    del app
    return bool(ok)


def export_animation(path: str, destination: str, *, motion: str | None = None,
                     composition: str | None = None, width: int = 1024, height: int = 1024,
                     fps: float = 30.0, start: float = 0.0, end: float | None = None,
                     format: str = "png_sequence",   # noqa: A002 - schema field name
                     transparent: bool = True, overwrite: bool = False,
                     physics_warmup: float = 1.0, progress=None,
                     cancelled=None) -> dict[str, Any]:
    """Render a motion or composition offline. Needs a native OpenGL context
    and, for video, the ffmpeg encoder; both are reported when missing."""
    from rigora.puppet.offline_export import (
        DONE,
        ExportJob,
        ExportSettings,
        FrameSource,
        encoder_capabilities,
        run_steps,
        validate_settings,
    )
    if (motion is None) == (composition is None):
        raise CommandError("invalid_input", "give exactly one of motion or composition")
    if format in encoder_capabilities() and not encoder_capabilities()[format]["available"]:
        raise CommandError("capability_missing", f"the {format} encoder is not installed",
                           EXIT_CAPABILITY)
    document = _load(path)
    try:
        source = FrameSource(document, motion=motion) if motion else \
            FrameSource(document, composition=composition)
    except ValueError as exc:
        raise CommandError("not_found", str(exc)) from exc
    background = (0.0, 0.0, 0.0, 0.0) if transparent else (1.0, 1.0, 1.0, 1.0)
    settings = ExportSettings(width=width, height=height, fps=fps, start=start, end=end,
                              background=background, format=format,
                              conflict="overwrite" if overwrite else "fail",
                              physics_warmup=physics_warmup)
    problems = validate_settings(settings, source.duration)
    if problems:
        raise CommandError("invalid_input", "; ".join(problems))
    target = Path(destination).expanduser()
    if target.exists() and not overwrite:
        raise CommandError("output_exists", f"{target} exists; pass overwrite to replace it",
                           EXIT_OUTPUT_EXISTS)
    if not gl_available():
        raise CommandError("capability_missing",
                           "rendering needs a native OpenGL context (a desktop session)",
                           EXIT_CAPABILITY)
    from rigora.puppet.offline_render_gl import canvas_renderer_factory
    job = ExportJob(source, settings, target)
    renderer = canvas_renderer_factory(job)
    try:
        for frame in run_steps(job, renderer, cancelled=cancelled or (lambda: False)):
            if progress is not None:
                progress(frame + 1, job.total)
    finally:
        renderer.close()
    job.state = DONE
    return {"destination": str(job.output), "frames": job.total, "notes": job.notes,
            "requires": ["opengl"] + (["ffmpeg"] if format in ("mp4", "webm") else [])}
