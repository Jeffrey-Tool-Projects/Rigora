"""R7.1 / R7.2: benchmark scenes are deterministic, valid and measurable headless."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

from rigora.puppet.document_io import from_zip_bytes, to_zip_bytes
from rigora.puppet.runtime import compose_all_drawables
from rigora.puppet.validator import validate

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module   # dataclasses resolve their module while executing
    spec.loader.exec_module(module)
    return module


scenes = _load("bench_scenes")

EXPECTED = {
    "many_drawables": {"drawables": 400, "vertices": 14400, "triangles": 20000,
                       "bone_weighted": 200, "vertex_morphs": 200, "textures": 16},
    "deep_deformers": {"drawables": 40, "deformers": 32, "max_deformer_depth": 32,
                       "parameters": 32},
    "masks": {"drawables": 120, "clip_masks": 60},
    "physics": {"drawables": 48, "physics_rigs": 48, "physics_particles": 384,
                "parameters": 49},
}


def _entries(archive: bytes) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        return [(info.filename, zf.read(info)) for info in zf.infolist()]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_synthetic_scenes_are_deterministic_valid_and_sized(name):
    first, second = scenes.build_scene(name), scenes.build_scene(name)
    archive = to_zip_bytes(first.documents[0])
    # Compare the entries, not the raw bytes: zip headers carry the wall-clock write time.
    assert _entries(archive) == _entries(to_zip_bytes(second.documents[0]))
    errors = [i for i in validate(first.documents[0]) if i.severity == "error"]
    assert errors == []
    scale = scenes.scene_scale(first)
    for key, value in EXPECTED[name].items():
        assert scale[key] == value, key
    assert scenes.scene_scale(scenes.Scene(name, [from_zip_bytes(archive)], "")) == scale


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_scene_motion_actually_deforms(name):
    doc = scenes.build_scene(name).documents[0]
    bench = _load("benchmark")
    evaluator = bench.FrameEvaluator(doc)
    start = compose_all_drawables(doc, evaluator.values_at(0.0))
    later = compose_all_drawables(doc, {**evaluator.values_at(0.7),
                                        **evaluator.physics.step(0.7, evaluator.values_at(0.7))})
    moved = sum(not np.allclose(start[k], later[k]) for k in start)
    assert moved > 0
    assert evaluator.frame(0.5) == len(doc.drawables)


def test_imeru_and_multi_pet_use_the_bundled_example():
    multi = scenes.build_scene("multi_pet")
    assert len(multi.documents) == 4
    assert multi.documents[0] is not multi.documents[1]
    assert scenes.scene_scale(multi)["drawables"] == 4 * len(multi.documents[0].drawables)


def test_unknown_scene_is_rejected():
    with pytest.raises(ValueError, match="unknown scene"):
        scenes.build_scene("huge")


def test_quick_benchmark_report_records_environment_and_results(tmp_path):
    bench = _load("benchmark")
    assert bench.main(["--scenes", "masks", "--repeat", "1", "--frames", "3",
                       "--cold-repeat", "0", "--soak", "0.3", "--soak-scene", "masks",
                       "--output", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "benchmark.json").read_text(encoding="utf-8"))
    env = report["environment"]
    assert env["cpu"] and env["logical_cpus"] and env["packages"]["numpy"]
    assert report["parameters"]["frames"] == 3
    masks = report["scenes"]["masks"]
    assert masks["scale"]["clip_masks"] == 60
    assert masks["io"]["roundtrip_scale_matches"] is True
    assert masks["frames"]["cpu_frame"]["n"] == 3
    assert report["soak"]["frames"] > 0 and report["soak"]["rss_end_bytes"] > 0
    assert "| masks | 120 |" in (tmp_path / "benchmark.md").read_text(encoding="utf-8")


def test_rss_probe_reports_this_process():
    bench = _load("benchmark")
    assert bench.rss_bytes() > 10 * 2**20
