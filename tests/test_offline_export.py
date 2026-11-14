"""R3.5 / R3.6: settings, deterministic fixed-step frames, jobs, cancel, retry, conflicts."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from rigora.puppet.document import (
    Clip,
    Composition,
    CompositionLayer,
    Motion,
    MotionSegment,
    MotionTrack,
    Parameter,
    PhysicsParticle,
    PhysicsRig,
    PuppetDocument,
)
from rigora.puppet.offline_export import (
    CANCELLED,
    DONE,
    FAILED,
    ExportJob,
    ExportQueue,
    ExportSettings,
    FrameSource,
    encoder_capabilities,
    frame_times,
    resolve_destination,
    validate_settings,
)


def doc() -> PuppetDocument:
    return PuppetDocument(
        parameters=[Parameter("A", -1, 1, 0), Parameter("Hair", -1, 1, 0)],
        motions=[Motion("swing", 1.0, tracks=[MotionTrack("A", [
            MotionSegment("linear", (0.0, -1.0), (1.0, 1.0))])])],
        physics_rigs=[PhysicsRig("h", "A", "Hair", [PhysicsParticle() for _ in range(3)])],
        compositions=[Composition("c", 1.0, [CompositionLayer("l", [Clip("swing")])])],
    )


def fake_render(values):
    """A frame that encodes the values, so equal frames mean equal samples."""
    frame = np.zeros((16, 16, 4), dtype=np.uint8)
    frame[..., 0] = int((values["A"] + 1) * 100)
    frame[..., 1] = int((values.get("Hair", 0) + 1) * 100)
    frame[..., 3] = 255
    return frame


def settings(**kwargs) -> ExportSettings:
    return ExportSettings(width=16, height=16, **kwargs)


def test_frame_times_are_exact_and_count_matches_duration():
    times = frame_times(settings(fps=30), 1.0)
    assert len(times) == 30 and times[1] == pytest.approx(1 / 30)
    assert len(frame_times(settings(fps=24, start=0.5, end=1.0), 1.0)) == 12
    assert len(frame_times(settings(fps=30), 0.01)) == 1


def test_validation_names_every_problem():
    problems = validate_settings(ExportSettings(width=8, height=17, fps=0, start=2, end=1,
                                                format="mp4", conflict="ask",
                                                physics_warmup=-1), 1.0)
    assert len(problems) >= 6
    if encoder_capabilities()["mp4"]["available"]:
        transparent_video = validate_settings(settings(format="mp4"), 1.0)
        assert any("transparency" in p for p in transparent_video)


def test_physics_warmup_and_fixed_steps_are_deterministic():
    first = FrameSource(doc(), motion="swing")
    second = FrameSource(doc(), motion="swing")
    times = frame_times(settings(fps=30), 1.0)
    a = [first.values(t, 1.0) for t in times]
    b = [second.values(t, 1.0) for t in times]
    assert a == b
    cold = FrameSource(doc(), motion="swing")
    assert cold.values(0.0, 0.0)["Hair"] != a[0]["Hair"]          # warm-up settles the chain
    with pytest.raises(ValueError):
        FrameSource(doc(), motion="nope")


def test_snapshot_ignores_later_document_edits():
    document = doc()
    source = FrameSource(document, motion="swing")
    document.motions[0].tracks[0].segments[0].p1 = (1.0, -1.0)
    assert source.values(0.5, 0.0)["A"] == pytest.approx(0.0)


def test_png_sequence_job_and_identical_rerun(tmp_path):
    queue = ExportQueue(fake_render)
    jobs = [queue.add(ExportJob(FrameSource(doc(), motion="swing"), settings(fps=10),
                                tmp_path / name)) for name in ("a", "b")]
    queue.run_all()
    assert [j.state for j in jobs] == [DONE, DONE]
    frames_a = sorted(jobs[0].output.iterdir())
    frames_b = sorted(jobs[1].output.iterdir())
    assert len(frames_a) == 10
    for x, y in zip(frames_a, frames_b, strict=True):
        assert np.array_equal(np.asarray(Image.open(x)), np.asarray(Image.open(y)))
    assert not list(tmp_path.glob(".rigora-export-*"))


def test_cancel_and_failures_leave_no_output_and_retry_works(tmp_path):
    queue = ExportQueue(fake_render)
    job = queue.add(ExportJob(FrameSource(doc(), composition="c"), settings(fps=20),
                              tmp_path / "cancelled"))
    queue.step()
    queue.step()
    queue.cancel(job.id)
    queue.run_all()
    assert job.state == CANCELLED and job.progress == 2
    assert not (tmp_path / "cancelled").exists() and not list(tmp_path.glob(".rigora-*"))
    retry = queue.retry(job.id)
    queue.run_all()
    assert retry.state == DONE and len(list(retry.output.iterdir())) == 20

    def broken(values):
        if values["A"] > 0:
            raise RuntimeError("encoder exploded")
        return fake_render(values)

    failing = ExportQueue(broken)
    bad = failing.add(ExportJob(FrameSource(doc(), motion="swing"), settings(fps=10),
                                tmp_path / "bad"))
    failing.run_all()
    assert bad.state == FAILED and "exploded" in bad.error
    assert not (tmp_path / "bad").exists()
    with pytest.raises(ValueError):
        queue.retry(retry.id)


def test_conflict_policies(tmp_path):
    target = tmp_path / "clip.gif"
    target.write_bytes(b"old")
    assert resolve_destination(target, "overwrite") == target
    assert resolve_destination(target, "rename") == tmp_path / "clip (2).gif"
    with pytest.raises(FileExistsError):
        resolve_destination(target, "fail")
    queue = ExportQueue(fake_render)
    job = queue.add(ExportJob(FrameSource(doc(), motion="swing"),
                              settings(fps=5, conflict="fail"), tmp_path / "x"))
    (tmp_path / "x").mkdir()
    queue.run_all()
    assert job.state == FAILED and "exists" in job.error


@pytest.mark.skipif(not encoder_capabilities()["gif"]["available"], reason="imageio missing")
def test_gif_export_has_the_planned_frame_count(tmp_path):
    queue = ExportQueue(fake_render)
    job = queue.add(ExportJob(FrameSource(doc(), motion="swing"), settings(fps=12, format="gif"),
                              tmp_path / "loop"))
    queue.run_all()
    assert job.state == DONE and job.output.suffix == ".gif"
    with Image.open(job.output) as gif:
        assert gif.n_frames == 12


def test_shutdown_discards_the_running_job(tmp_path):
    closed = []

    class Renderer:
        def __call__(self, values):
            return fake_render(values)

        def close(self):
            closed.append(True)

    queue = ExportQueue(render_factory=lambda job: Renderer())
    job = queue.add(ExportJob(FrameSource(doc(), motion="swing"), settings(fps=10),
                              tmp_path / "x"))
    waiting = queue.add(ExportJob(FrameSource(doc(), motion="swing"), settings(fps=10),
                                  tmp_path / "y"))
    queue.step()
    queue.shutdown()
    assert (job.state, waiting.state) == (CANCELLED, CANCELLED)
    assert closed == [True] and not list(tmp_path.iterdir())
