"""Pose sweeps for rig acceptance: torn meshes at extreme and blended poses.

:func:`pose_samples` lists the neutral pose, every parameter at its minimum
and maximum, and every corner of each multi-axis blend. :func:`check_poses`
composes each pose and counts triangles that flipped orientation (the mesh
folded over itself, which shows as a tear) or collapsed, per drawable, and
any non-finite vertex. The rendering side of the acceptance (transparent
edges, mask overlap) needs GL and lives in the native verification script.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import product

import numpy as np

from rigora.puppet.document import PuppetDocument
from rigora.puppet.runtime import compose_all_drawables, default_parameter_values

_COLLAPSE_RATIO = 1e-3
TEAR_AREA_RATIO = 0.01
"""Folded area above this share of a drawable's area counts as a tear; below it
(an elbow crease under a deep bend, say) the fold is listed but tolerated."""


def pose_samples(document: PuppetDocument, *, limit: int = 256) -> list[tuple[str, dict]]:
    """``(label, values)`` poses: neutral, each parameter's extremes, blend corners."""
    neutral = default_parameter_values(document)
    poses = [("neutral", dict(neutral))]
    for parameter in document.parameters:
        for bound, value in (("min", parameter.min), ("max", parameter.max)):
            poses.append((f"{parameter.id}={bound}", {**neutral, parameter.id: value}))
    by_id = {p.id: p for p in document.parameters}
    for blend in document.parameter_blends:
        axes = [by_id[p] for p in blend.parameters if p in by_id]
        for corner in product(*[(p.min, p.max) for p in axes]):
            label = f"{blend.id}:" + ",".join(f"{p.id}={v:g}" for p, v in zip(axes, corner,
                                                                              strict=True))
            poses.append((label, {**neutral, **{p.id: v for p, v in zip(axes, corner,
                                                                        strict=True)}}))
    return poses[:limit]


def _signed_areas(vertices: np.ndarray, indices: list[int]) -> np.ndarray:
    tris = np.asarray(indices[: len(indices) // 3 * 3], dtype=np.int64).reshape(-1, 3)
    if not len(tris) or tris.max(initial=-1) >= len(vertices):
        return np.zeros(0)
    a, b, c = vertices[tris[:, 0]], vertices[tris[:, 1]], vertices[tris[:, 2]]
    return 0.5 * ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                  - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))


@dataclass
class PoseReport:
    poses: int = 0
    flipped: dict[str, dict[str, int]] = field(default_factory=dict)
    """``{pose: {drawable: flipped triangles}}`` for poses with any."""
    flipped_area: dict[str, dict[str, float]] = field(default_factory=dict)
    """Folded area as a share of the drawable's rest area, per pose."""
    collapsed: dict[str, dict[str, int]] = field(default_factory=dict)
    non_finite: list[str] = field(default_factory=list)

    @property
    def tears(self) -> dict[str, dict[str, float]]:
        """Folds larger than :data:`TEAR_AREA_RATIO`."""
        found = {}
        for pose, shares in self.flipped_area.items():
            big = {d: r for d, r in shares.items() if r > TEAR_AREA_RATIO}
            if big:
                found[pose] = big
        return found

    @property
    def clean(self) -> bool:
        return not (self.tears or self.collapsed or self.non_finite)

    def to_dict(self) -> dict:
        return asdict(self) | {"clean": self.clean, "tears": self.tears}


def check_poses(document: PuppetDocument, poses: list[tuple[str, dict]] | None = None
                ) -> PoseReport:
    report = PoseReport()
    rest = {d.id: _signed_areas(np.asarray(d.vertices, dtype=float), d.indices)
            for d in document.drawables}
    for label, values in poses if poses is not None else pose_samples(document):
        report.poses += 1
        composed = compose_all_drawables(document, values)
        for drawable in document.drawables:
            vertices = np.asarray(composed.get(drawable.id, drawable.vertices), dtype=float)
            if not np.isfinite(vertices).all():
                report.non_finite.append(f"{label}:{drawable.id}")
                continue
            before, after = rest[drawable.id], _signed_areas(vertices, drawable.indices)
            if not len(before) or len(after) != len(before):
                continue
            live = np.abs(before) > 1e-9
            flipped = int(np.sum(live & (np.sign(after) != np.sign(before))
                                 & (np.abs(after) > 1e-9)))
            collapsed = int(np.sum(live & (np.abs(after) <= np.abs(before) * _COLLAPSE_RATIO)))
            if flipped:
                folded = live & (np.sign(after) != np.sign(before))
                share = float(np.abs(after[folded]).sum() / max(np.abs(before).sum(), 1e-9))
                report.flipped.setdefault(label, {})[drawable.id] = flipped
                report.flipped_area.setdefault(label, {})[drawable.id] = share
            if collapsed:
                report.collapsed.setdefault(label, {})[drawable.id] = collapsed
    return report
