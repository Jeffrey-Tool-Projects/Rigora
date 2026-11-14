"""R7.3: run summaries take medians across runs and enforce budgets."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _summary():
    name = "benchmark_summary"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def report(frame_ms: float, gl_ms: float) -> dict:
    stats = {"median_ms": frame_ms, "p95_ms": frame_ms * 1.5}
    return {"environment": {"cpu": "test cpu", "power": {"ac_power": True}},
            "scenes": {"s": {"frames": {"cpu_frame": stats},
                             "io": {"open": {"median_ms": 10.0}, "save": {"median_ms": 20.0}}}},
            "gl": {"scenes": {"s": {"render_readback": {"median_ms": gl_ms, "p95_ms": gl_ms}}}},
            "cold_start": {"import_core": {"median_ms": 400.0}, "broken": {"error": "x"}}}


def test_medians_spread_and_budgets(tmp_path):
    module = _summary()
    runs = []
    for index, (frame, gl) in enumerate(((4.0, 10.0), (6.0, 30.0), (5.0, 12.0))):
        path = tmp_path / f"run{index}.json"
        path.write_text(json.dumps(report(frame, gl)), encoding="utf-8")
        runs.append(str(path))
    budgets = tmp_path / "budgets.json"
    budgets.write_text(json.dumps({"scenes": {"s": {"cpu_frame_median_ms": 5.5,
                                                    "gl_render_ms": 11.0},
                                              "startup": {"import_core_ms": 500}}}),
                       encoding="utf-8")
    assert module.main([*runs, "--budgets", str(budgets), "--output", str(tmp_path / "o")]) == 0
    assert module.main([*runs, "--budgets", str(budgets), "--output", str(tmp_path / "o"),
                        "--enforce"]) == 1                    # gl median 12 > 11
    data = json.loads((tmp_path / "o" / "summary.json").read_text(encoding="utf-8"))
    cpu = data["summary"]["s"]["cpu_frame_median_ms"]
    assert (cpu["median"], cpu["min"], cpu["max"], cpu["runs"]) == (5.0, 4.0, 6.0, 3)
    assert {r["metric"]: r["pass"] for r in data["budgets"]} == {
        "cpu_frame_median_ms": True, "gl_render_ms": False, "import_core_ms": True}
    assert "| s | gl_render_ms | 12.00 |" in (tmp_path / "o" / "summary.md").read_text(
        encoding="utf-8")
