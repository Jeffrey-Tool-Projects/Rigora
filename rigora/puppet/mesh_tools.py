"""Qt-free mesh and weight tools for the editor (R2.3).

Selections are plain index sets held by the editor, not stored in the
document. Locked vertices are never moved or re-weighted by these tools.
Every operation edits one :class:`Drawable` in place and returns what it
changed, so the caller can wrap it in one undoable transaction.

Topology changes (deleting vertices) are previewed first with
:func:`topology_impact`, which lists the triangles, weights and vertex-morph
entries that would change and any per-vertex data that is already out of
step with the mesh.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

import numpy as np

from rigora.puppet.document import Drawable, PuppetDocument
from rigora.puppet.mesh_edit import _invalidate_rest_cache, remap_vertex_data
from rigora.puppet.symmetrize import mirror_id

_MORPH_SIDES = ("delta_at_min", "delta_at_max")


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def vertices_in_rect(
    drawable: Drawable, rect: tuple[float, float, float, float],
) -> set[int]:
    """Indices of rest vertices inside ``rect`` (any corner order)."""
    x0, y0, x1, y1 = rect
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    return {i for i, (x, y) in enumerate(drawable.vertices)
            if left <= x <= right and top <= y <= bottom}


def select_in_rect(
    document: PuppetDocument, rect: tuple[float, float, float, float],
) -> tuple[str, set[int]] | None:
    """Box selection on the topmost drawable with any vertex inside ``rect``."""
    for drawable in sorted(document.drawables, key=lambda d: -d.draw_order):
        hits = vertices_in_rect(drawable, rect)
        if hits:
            return drawable.id, hits
    return None


def adjacency(drawable: Drawable) -> list[set[int]]:
    """Neighbouring vertex indices through the triangle edges."""
    neighbours: list[set[int]] = [set() for _ in drawable.vertices]
    count = len(drawable.vertices)
    for start in range(0, len(drawable.indices) - 2, 3):
        tri = drawable.indices[start:start + 3]
        if any(not 0 <= i < count for i in tri):
            continue
        a, b, c = tri
        neighbours[a] |= {b, c}
        neighbours[b] |= {a, c}
        neighbours[c] |= {a, b}
    return neighbours


def grow_selection(drawable: Drawable, selection: set[int]) -> set[int]:
    links = adjacency(drawable)
    grown = set(selection)
    for index in selection:
        if 0 <= index < len(links):
            grown |= links[index]
    return grown


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def _editable(selection: Iterable[int], locked: Iterable[int], count: int) -> list[int]:
    locked_set = set(locked)
    return sorted(i for i in set(selection) if 0 <= i < count and i not in locked_set)


def translate_vertices(
    drawable: Drawable, selection: Iterable[int], dx: float, dy: float,
    *, locked: Iterable[int] = (),
) -> list[int]:
    """Move selected, unlocked vertices by ``(dx, dy)``. Returns moved indices."""
    moved = _editable(selection, locked, len(drawable.vertices))
    for index in moved:
        x, y = drawable.vertices[index]
        drawable.vertices[index] = (float(x) + dx, float(y) + dy)
    if moved:
        _invalidate_rest_cache(drawable)
    return moved


def mirror_vertices(
    drawable: Drawable, selection: Iterable[int], axis_x: float,
    *, locked: Iterable[int] = (),
) -> list[int]:
    """Reflect selected, unlocked vertices across the vertical line ``x = axis_x``."""
    moved = _editable(selection, locked, len(drawable.vertices))
    for index in moved:
        x, y = drawable.vertices[index]
        drawable.vertices[index] = (2.0 * axis_x - float(x), float(y))
    if moved:
        _invalidate_rest_cache(drawable)
    return moved


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------


def _weights(drawable: Drawable) -> dict[str, list[float]]:
    count = len(drawable.vertices)
    return {bone: [float(w[i]) if i < len(w) else 0.0 for i in range(count)]
            for bone, w in (drawable.bone_weights or {}).items()}


def normalize_weights(
    drawable: Drawable, *, selection: Iterable[int] | None = None,
    locked: Iterable[int] = (), locked_bones: Iterable[str] = (),
) -> list[int]:
    """Make each vertex's weights sum to 1.

    Weights of ``locked_bones`` stay as they are; the other bones share the
    remainder in proportion. A vertex whose unlocked weights are all zero is
    left alone. Returns the changed vertex indices.
    """
    weights = _weights(drawable)
    if not weights:
        return []
    count = len(drawable.vertices)
    targets = range(count) if selection is None else selection
    frozen = set(locked_bones)
    changed = []
    for index in _editable(targets, locked, count):
        fixed = sum(weights[b][index] for b in weights if b in frozen)
        free = [b for b in weights if b not in frozen]
        total = sum(max(0.0, weights[b][index]) for b in free)
        remainder = max(0.0, 1.0 - fixed)
        if total <= 0.0:
            continue
        before = [weights[b][index] for b in free]
        for bone in free:
            weights[bone][index] = max(0.0, weights[bone][index]) * remainder / total
        if any(abs(a - weights[b][index]) > 1e-9 for a, b in zip(before, free, strict=True)):
            changed.append(index)
    drawable.bone_weights = weights
    return changed


def smooth_weights(
    drawable: Drawable, selection: Iterable[int] | None = None, *, iterations: int = 1,
    strength: float = 0.5, locked: Iterable[int] = (), locked_bones: Iterable[str] = (),
) -> list[int]:
    """Blend each selected vertex's weights toward its neighbours' average,
    then renormalise. Locked vertices and bones keep their values."""
    if not 0.0 <= strength <= 1.0 or iterations < 1:
        raise ValueError("strength must be in [0, 1] and iterations positive")
    weights = _weights(drawable)
    if not weights:
        return []
    count = len(drawable.vertices)
    targets = _editable(range(count) if selection is None else selection, locked, count)
    links = adjacency(drawable)
    frozen = set(locked_bones)
    bones = [b for b in weights if b not in frozen]
    for _ in range(iterations):
        snapshot = {b: list(weights[b]) for b in bones}
        for index in targets:
            near = links[index]
            if not near:
                continue
            for bone in bones:
                average = sum(snapshot[bone][n] for n in near) / len(near)
                weights[bone][index] = ((1 - strength) * snapshot[bone][index]
                                        + strength * average)
    drawable.bone_weights = weights
    normalize_weights(drawable, selection=targets, locked=locked, locked_bones=locked_bones)
    return targets


def mirror_weights(
    drawable: Drawable, axis_x: float, *, source_side: str = "left",
    locked: Iterable[int] = (), tolerance: float = 2.0,
) -> list[int]:
    """Copy weights from one side of ``x = axis_x`` to the mirrored vertices on
    the other side, swapping left/right bone ids (``_L``↔``_R``…).

    A vertex receives weights only when a source vertex lies within
    ``tolerance`` pixels of its mirror image. Returns the changed indices.
    """
    if source_side not in ("left", "right"):
        raise ValueError("source_side must be 'left' or 'right'")
    weights = _weights(drawable)
    if not weights:
        return []
    points = np.asarray(drawable.vertices, dtype=float)
    on_source = points[:, 0] < axis_x if source_side == "left" else points[:, 0] > axis_x
    sources = np.flatnonzero(on_source)
    if not len(sources):
        return []
    locked_set = set(locked)
    renamed = {bone: mirror_id(bone) for bone in weights}
    for target in renamed.values():
        weights.setdefault(target, [0.0] * len(points))
    changed = []
    for index in np.flatnonzero(~on_source):
        if index in locked_set:
            continue
        reflected = np.array([2.0 * axis_x - points[index, 0], points[index, 1]])
        distances = np.hypot(*(points[sources] - reflected).T)
        best = int(np.argmin(distances))
        if distances[best] > tolerance:
            continue
        source = int(sources[best])
        if source == index:
            continue
        snapshot = {bone: weights[bone][source] for bone in renamed}
        for bone in weights:
            weights[bone][index] = 0.0
        for bone, value in snapshot.items():
            weights[renamed[bone]][index] += value
        changed.append(int(index))
    original = set(drawable.bone_weights or {})
    drawable.bone_weights = {b: w for b, w in weights.items() if b in original or any(w)}
    return changed


def weight_colors(drawable: Drawable, bone: str) -> np.ndarray:
    """``N×4`` RGBA heat colours for ``bone``'s weights: blue at 0, through
    green, to red at 1. Vertices without data are grey."""
    count = len(drawable.vertices)
    colours = np.tile(np.array([0.5, 0.5, 0.5, 0.9], dtype=np.float32), (count, 1))
    values = (drawable.bone_weights or {}).get(bone)
    if values is None:
        return colours
    w = np.clip(np.asarray([values[i] if i < len(values) else 0.0 for i in range(count)],
                           dtype=np.float32), 0.0, 1.0)
    colours[:, 0] = np.clip(2.0 * w - 1.0, 0.0, 1.0)
    colours[:, 1] = 1.0 - np.abs(2.0 * w - 1.0)
    colours[:, 2] = np.clip(1.0 - 2.0 * w, 0.0, 1.0)
    return colours


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TopologyImpact:
    drawable: str
    removed_vertices: tuple[int, ...]
    removed_triangles: int
    remaining_triangles: int
    weight_bones: tuple[str, ...]
    """Bones whose per-vertex lists lose entries."""
    morph_parameters: tuple[str, ...]
    """Vertex morphs whose delta lists lose entries."""
    mismatched: tuple[str, ...]
    """Per-vertex data already out of step with the vertex count."""
    blocked: tuple[str, ...]
    """Reasons the change cannot be applied."""

    def to_dict(self) -> dict:
        return asdict(self)


def check_per_vertex_data(drawable: Drawable) -> list[str]:
    """Names of weight / morph / UV lists whose length differs from the mesh."""
    count = len(drawable.vertices)
    problems = []
    if len(drawable.uvs) != count:
        problems.append(f"uvs has {len(drawable.uvs)} entries for {count} vertices")
    for bone, values in (drawable.bone_weights or {}).items():
        if len(values) != count:
            problems.append(f"weights of {bone} have {len(values)} entries")
    for morph in drawable.vertex_morphs or []:
        for side in _MORPH_SIDES:
            deltas = morph.get(side)
            if deltas is not None and len(deltas) != count:
                problems.append(f"morph {morph.get('parameter')} {side} has {len(deltas)} entries")
    if any(not 0 <= i < count for i in drawable.indices):
        problems.append("triangle indices point past the vertex list")
    return problems


def topology_impact(drawable: Drawable, remove: Iterable[int]) -> TopologyImpact:
    """What deleting ``remove`` would change; nothing is modified."""
    count = len(drawable.vertices)
    doomed = tuple(sorted({i for i in remove if 0 <= i < count}))
    gone = set(doomed)
    triangles = [drawable.indices[s:s + 3] for s in range(0, len(drawable.indices) - 2, 3)]
    removed = sum(1 for tri in triangles if gone & set(tri))
    blocked = []
    if not doomed:
        blocked.append("no vertex selected")
    if count - len(doomed) < 3 or removed == len(triangles):
        blocked.append("the drawable would have no triangles left")
    return TopologyImpact(
        drawable=drawable.id, removed_vertices=doomed, removed_triangles=removed,
        remaining_triangles=len(triangles) - removed,
        weight_bones=tuple(sorted(drawable.bone_weights or {})) if doomed else (),
        morph_parameters=tuple(str(m.get("parameter")) for m in drawable.vertex_morphs or [])
        if doomed else (),
        mismatched=tuple(check_per_vertex_data(drawable)), blocked=tuple(blocked),
    )


def delete_vertices(drawable: Drawable, remove: Iterable[int]) -> TopologyImpact:
    """Delete vertices with their triangles and per-vertex data, keeping every
    remaining weight, UV and morph entry aligned. Raises ``ValueError`` when
    :func:`topology_impact` reports the change as blocked."""
    impact = topology_impact(drawable, remove)
    if impact.blocked:
        raise ValueError("; ".join(impact.blocked))
    gone = set(impact.removed_vertices)
    keep = [i for i in range(len(drawable.vertices)) if i not in gone]
    new_index = {old: new for new, old in enumerate(keep)}
    remap_vertex_data(drawable, keep)
    drawable.vertices = [drawable.vertices[i] for i in keep]
    drawable.uvs = [drawable.uvs[i] for i in keep if i < len(drawable.uvs)]
    indices = []
    for start in range(0, len(drawable.indices) - 2, 3):
        tri = drawable.indices[start:start + 3]
        if not gone & set(tri) and all(i in new_index for i in tri):
            indices.extend(new_index[i] for i in tri)
    drawable.indices = indices
    _invalidate_rest_cache(drawable)
    return impact
