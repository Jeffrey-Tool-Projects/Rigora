"""Combine benchmark runs, compare with a baseline and check budgets (R7.3).

One run on a laptop can move by 2× with power state and temperature, so a
budget is checked against the median of several runs from the same machine,
and the spread is reported next to it.

    py -3 scripts/benchmark_summary.py .audit/r7/after-run*/benchmark.json \\
        --baseline .audit/r2-r7/benchmark-run*/benchmark.json \\
        --budgets scripts/perf_budgets.json --output .audit/r7/summary --enforce
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def metrics(report: dict) -> dict[str, dict[str, float]]:
    """``{scene: {metric: value}}`` from one benchmark report."""
    out: dict[str, dict[str, float]] = {}
    for scene, data in report.get("scenes", {}).items():
        frames, io = data["frames"], data["io"]
        out[scene] = {
            "cpu_frame_median_ms": frames["cpu_frame"]["median_ms"],
            "cpu_frame_p95_ms": frames["cpu_frame"]["p95_ms"],
            "open_ms": io["open"]["median_ms"],
            "save_ms": io["save"]["median_ms"],
        }
    gl = report.get("gl") or {}
    for scene, data in gl.get("scenes", {}).items():
        if "render_readback" in data:
            out.setdefault(scene, {})["gl_render_ms"] = data["render_readback"]["median_ms"]
            out[scene]["gl_render_p95_ms"] = data["render_readback"]["p95_ms"]
    startup = {f"{name}_ms": value["median_ms"]
               for name, value in report.get("cold_start", {}).items() if "median_ms" in value}
    if startup:
        out["startup"] = startup
    return out


def combine(reports: list[dict]) -> dict[str, dict[str, dict[str, float]]]:
    """Median, min and max of every metric across runs."""
    values: dict[str, dict[str, list[float]]] = {}
    for report in reports:
        for scene, items in metrics(report).items():
            for name, value in items.items():
                values.setdefault(scene, {}).setdefault(name, []).append(value)
    return {scene: {name: {"median": statistics.median(v), "min": min(v), "max": max(v),
                           "runs": len(v)} for name, v in items.items()}
            for scene, items in values.items()}


def check_budgets(summary: dict, budgets: dict) -> list[dict]:
    rows = []
    for scene, limits in budgets.get("scenes", {}).items():
        for name, limit in limits.items():
            measured = summary.get(scene, {}).get(name)
            rows.append({"scene": scene, "metric": name, "budget": limit,
                         "median": None if measured is None else measured["median"],
                         "pass": measured is not None and measured["median"] <= limit})
    return rows


def _load(paths: list[Path]) -> list[dict]:
    return [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]


def markdown(summary: dict, baseline: dict | None, budget_rows: list[dict],
             environments: list[dict]) -> str:
    power = {json.dumps(env.get("power"), sort_keys=True) for env in environments}
    lines = ["# Benchmark summary", "",
             f"- Runs: {len(environments)}; machine: {environments[0]['cpu']}",
             f"- Power states seen: {', '.join(sorted(power))}", "",
             "| Scene | Metric | Median | Min–max | Baseline median | Change | Budget |",
             "| --- | --- | ---: | --- | ---: | ---: | --- |"]
    budgets = {(r["scene"], r["metric"]): r for r in budget_rows}
    for scene, items in summary.items():
        for name, value in items.items():
            base = (baseline or {}).get(scene, {}).get(name)
            change = f"{value['median'] / base['median']:.2f}×" if base else "—"
            row = budgets.get((scene, name))
            budget = "—" if row is None else f"{row['budget']:g} {'✓' if row['pass'] else '✗'}"
            base_text = f"{base['median']:.2f}" if base else "—"
            lines.append(f"| {scene} | {name} | {value['median']:.2f} | "
                         f"{value['min']:.2f}–{value['max']:.2f} | {base_text} | {change} | "
                         f"{budget} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--baseline", nargs="*", type=Path, default=[])
    parser.add_argument("--budgets", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enforce", action="store_true", help="exit 1 when a budget fails")
    args = parser.parse_args(argv)
    reports = _load(args.reports)
    summary = combine(reports)
    baseline = combine(_load(args.baseline)) if args.baseline else None
    budgets = json.loads(args.budgets.read_text(encoding="utf-8")) if args.budgets else {}
    rows = check_budgets(summary, budgets)
    args.output.mkdir(parents=True, exist_ok=True)
    result = {"runs": [str(p) for p in args.reports], "baseline": [str(p) for p in args.baseline],
              "summary": summary, "baseline_summary": baseline, "budgets": rows,
              "environments": [r["environment"] for r in reports]}
    (args.output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (args.output / "summary.md").write_text(
        markdown(summary, baseline, rows, result["environments"]), encoding="utf-8")
    failed = [r for r in rows if not r["pass"]]
    for row in failed:
        print(f"over budget: {row['scene']} {row['metric']} {row['median']} > {row['budget']}",
              file=sys.stderr)
    return 1 if failed and args.enforce else 0


if __name__ == "__main__":
    raise SystemExit(main())
