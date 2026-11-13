"""R7.3: batched composition is bit-identical to the per-drawable path."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from rigora.puppet.document import Deformer, Drawable, PuppetDocument
from rigora.puppet.runtime import compose_all_drawables, default_parameter_values
from rigora.puppet.runtime_deformer_order import topologically_sorted_deformers
from rigora.puppet.runtime_geometry import compose_drawable_vertices
from rigora.puppet.runtime_parameters import merge_parameter_samples

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _scenes():
    if "bench_scenes" not in sys.modules:
        sys.path.insert(0, str(SCRIPTS))
        spec = importlib.util.spec_from_file_location("bench_scenes", SCRIPTS / "bench_scenes.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["bench_scenes"] = module
        spec.loader.exec_module(module)
    return sys.modules["bench_scenes"]


def reference(document, values):
    overrides = merge_parameter_samples(document, values)
    by_id = {p.id: p for p in document.parameters}
    ordered = topologically_sorted_deformers(document.deformers)
    return {d.id: compose_drawable_vertices(d, document.deformers, overrides,
                                            parameter_values=values, parameters_by_id=by_id,
                                            sorted_deformers=ordered)
            for d in document.drawables}


@pytest.mark.parametrize("name", ["imeru", "many_drawables", "deep_deformers", "masks",
                                  "physics"])
def test_batched_matches_reference_bit_for_bit(name):
    document = _scenes().build_scene(name).documents[0]
    rng = np.random.default_rng(7)
    for _ in range(4):
        values = default_parameter_values(document)
        for parameter in document.parameters:
            values[parameter.id] = float(rng.uniform(parameter.min, parameter.max))
        expected, actual = reference(document, values), compose_all_drawables(document, values)
        assert expected.keys() == actual.keys()
        for drawable_id, vertices in expected.items():
            assert actual[drawable_id].dtype == vertices.dtype
            np.testing.assert_array_equal(actual[drawable_id], vertices)


def test_duplicate_targets_unknown_types_and_duplicate_ids_behave_as_before():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    doc = PuppetDocument(
        drawables=[Drawable("a", "t", square, [0, 1, 2], [(0, 0)] * 3),
                   Drawable("b", "t", square, [0, 1, 2], [(0, 0)] * 3)],
        deformers=[Deformer("r", "rotation", None, ["a", "a", "missing"],
                            {"anchor": [0, 0], "angle": 0.5}),
                   Deformer("odd", "future_type", None, ["b"], {})])
    values = {}
    for drawable_id, vertices in reference(doc, values).items():
        np.testing.assert_array_equal(compose_all_drawables(doc, values)[drawable_id], vertices)
    doc.drawables.append(Drawable("a", "t", [(1.0, 1.0)], [], [(0, 0)]))
    np.testing.assert_array_equal(compose_all_drawables(doc, values)["a"],
                                  reference(doc, values)["a"])
