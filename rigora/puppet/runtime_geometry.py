"""Compose morphs, bone skinning, and ordered rigid deformations."""
from __future__ import annotations

from typing import Any

import numpy as np

from rigora.puppet.deformers import apply_rotation, apply_warp
from rigora.puppet.document import Deformer, Drawable, Parameter
from rigora.puppet.runtime_deformer_order import topologically_sorted_deformers
from rigora.puppet.runtime_morphs import _rest_vertices_array, apply_vertex_morphs
from rigora.puppet.runtime_skinning import _compose_bone_lbs, _form_for

_DEFORMER_FUNCS = {"rotation": apply_rotation, "warp": apply_warp}


def _apply_deformer(
    type_: str, vertices: np.ndarray, form: dict[str, Any],
) -> np.ndarray:
    fn = _DEFORMER_FUNCS.get(type_)
    if fn is None:
        return vertices
    return fn(vertices, form)


def compose_drawable_vertices(
    drawable: Drawable,
    deformers: list[Deformer],
    overrides: dict[str, dict[str, Any]],
    *,
    parameter_values: dict[str, float] | None = None,
    parameters_by_id: dict[str, Parameter] | None = None,
    sorted_deformers: list[Deformer] | None = None,
) -> np.ndarray:
    """Apply every deformer that targets ``drawable`` to its neutral
    vertices and return the deformed Nx2 array.

    ``overrides`` is the merged-parameter output from
    :func:`merge_parameter_samples`. A deformer not present in
    ``overrides`` runs with its authored neutral form (= identity in
    practice, since neutral forms produce identity transforms).

    All ``bone_rotation`` deformers targeting this drawable are
    aggregated into a single LBS pass that runs against the rest
    vertices — that's what makes opposing-bone weights cancel correctly
    instead of stacking sequentially. Other deformer types are then
    applied in FK order: a topological sort by ``Deformer.parent``
    ensures a parent rotation/warp always runs before its children,
    even when the document lists them in a different order.

    Performance note: ``sorted_deformers`` lets a batch caller pass
    in the topologically-sorted deformer list once instead of
    recomputing it per drawable. ``compose_all_drawables`` already
    does this — only direct callers need to pass it.
    """
    rest = _rest_vertices_array(drawable)
    # Cubism-style vertex morphs run *before* any deformer pipeline —
    # they replace the rest pose with the parameter-deformed pose
    # that .moc3 conversion captured, then deformers (if any) layer on
    # top.
    if drawable.vertex_morphs and parameter_values is not None and parameters_by_id is not None:
        rest = apply_vertex_morphs(rest, drawable.vertex_morphs, parameter_values, parameters_by_id)
    if sorted_deformers is None:
        sorted_deformers = topologically_sorted_deformers(deformers)
    bone_deformers: list[Deformer] = []
    other_deformers: list[Deformer] = []
    for deformer in sorted_deformers:
        if drawable.id not in deformer.drawables:
            continue
        if deformer.type == "bone_rotation":
            bone_deformers.append(deformer)
        else:
            other_deformers.append(deformer)
    if not bone_deformers and not other_deformers:
        # Fast path: morphs already produced the final vertex set,
        # no deformer chain to layer on top. Skips the redundant
        # bone-LBS branch + the float32 cast since rest is already
        # float32 from ``_rest_vertices_array``.
        return rest
    verts = _compose_bone_lbs(rest, drawable, bone_deformers, overrides)
    for deformer in other_deformers:
        form = _form_for(deformer, overrides)
        verts = _apply_deformer(deformer.type, verts, form)
    return verts.astype(np.float32, copy=False)


def compose_document_vertices(
    drawables: list[Drawable],
    sorted_deformers: list[Deformer],
    overrides: dict[str, dict[str, Any]],
    *,
    parameter_values: dict[str, float] | None,
    parameters_by_id: dict[str, Parameter] | None,
) -> dict[str, np.ndarray]:
    """:func:`compose_drawable_vertices` for many drawables at once.

    Rotation and warp deformers map each vertex independently, so a deformer
    runs once over the stacked vertices of every drawable it targets, in the
    same parent-first order, instead of once per drawable. Arrays of
    different dtypes are stacked separately so every drawable sees exactly
    the arithmetic the per-drawable path would apply.
    """
    bones: dict[str, list[Deformer]] = {d.id: [] for d in drawables}
    rigid: set[str] = set()
    for deformer in sorted_deformers:
        for target in dict.fromkeys(deformer.drawables):
            if target not in bones:
                continue
            if deformer.type == "bone_rotation":
                bones[target].append(deformer)
            else:
                rigid.add(target)
    current: dict[str, np.ndarray] = {}
    finished: set[str] = set()
    for drawable in drawables:
        rest = _rest_vertices_array(drawable)
        if drawable.vertex_morphs and parameter_values is not None \
                and parameters_by_id is not None:
            rest = apply_vertex_morphs(rest, drawable.vertex_morphs, parameter_values,
                                       parameters_by_id)
        if not bones[drawable.id] and drawable.id not in rigid:
            current[drawable.id] = rest
            finished.add(drawable.id)
        else:
            current[drawable.id] = _compose_bone_lbs(rest, drawable, bones[drawable.id],
                                                     overrides)
    for deformer in sorted_deformers:
        if deformer.type == "bone_rotation":
            continue
        targets = [t for t in dict.fromkeys(deformer.drawables)
                   if t in current and t not in finished]
        if targets:
            _apply_stacked(deformer, _form_for(deformer, overrides), targets, current)
    for drawable_id, vertices in current.items():
        if drawable_id not in finished:
            current[drawable_id] = vertices.astype(np.float32, copy=False)
    return current


def _apply_stacked(deformer: Deformer, form: dict[str, Any], targets: list[str],
                   current: dict[str, np.ndarray]) -> None:
    by_dtype: dict[np.dtype, list[str]] = {}
    for target in targets:
        by_dtype.setdefault(current[target].dtype, []).append(target)
    for group in by_dtype.values():
        arrays = [current[t] for t in group]
        stacked = arrays[0] if len(arrays) == 1 else np.concatenate(arrays)
        moved = _apply_deformer(deformer.type, stacked, form)
        if len(arrays) == 1:
            current[group[0]] = moved
            continue
        offset = 0
        for target, array in zip(group, arrays, strict=True):
            current[target] = moved[offset:offset + len(array)]
            offset += len(array)
