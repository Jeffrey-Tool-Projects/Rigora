"""Deterministic benchmark scenes for Rigora (R7.1).

Every scene except ``imeru`` is generated from code: flat-colour textures and
procedural meshes, so the scenes carry no third-party artwork and can ship
with the tests. ``imeru`` is the project's bundled example. ``scene_scale``
records the actual size of each scene; reports quote those numbers instead
of labels such as "large".

Scenes
    imeru            the bundled example rig
    many_drawables   400 grid meshes with bone weights and vertex morphs
    deep_deformers   a 32-level rotation/warp chain driven by 32 parameters
    masks            120 drawables, half clipped by the other half
    physics          48 physics chains of 8 particles driving warp deformers
    multi_pet        4 independent copies of ``imeru`` evaluated together
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

from rigora.puppet.deformers import default_rotation_form, default_warp_form
from rigora.puppet.document import (
    Deformer,
    Drawable,
    Motion,
    MotionSegment,
    MotionTrack,
    Parameter,
    ParameterKey,
    PhysicsParticle,
    PhysicsRig,
    PuppetDocument,
)

CANVAS = (2048, 2048)
SCENE_NAMES = ("imeru", "many_drawables", "deep_deformers", "masks", "physics", "multi_pet")


@dataclass
class Scene:
    name: str
    documents: list[PuppetDocument]
    description: str


def _texture(size: int, seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    pixels = np.zeros((size, size, 4), dtype=np.uint8)
    pixels[..., :3] = rng.integers(40, 220, 3, dtype=np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    centre = (size - 1) / 2
    inside = (xx - centre) ** 2 + (yy - centre) ** 2 <= centre ** 2
    pixels[..., 3] = np.where(inside, 255, 0).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(pixels, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


def _grid(x0: float, y0: float, w: float, h: float, n: int):
    vertices, uvs, indices = [], [], []
    for row in range(n):
        for col in range(n):
            u, v = col / (n - 1), row / (n - 1)
            vertices.append((x0 + u * w, y0 + v * h))
            uvs.append((u, v))
    for row in range(n - 1):
        for col in range(n - 1):
            a = row * n + col
            b, c, d = a + 1, a + n, a + n + 1
            indices.extend([a, b, d, a, d, c])
    return vertices, uvs, indices


def _param(pid: str, lo: float = -1.0, hi: float = 1.0) -> Parameter:
    return Parameter(pid, lo, hi, 0.0)


def _sweep_motion(params: list[Parameter], duration: float = 2.0) -> Motion:
    tracks = []
    for index, param in enumerate(params):
        phase = (index % 7) / 7
        mid = duration * (0.25 + 0.5 * phase)
        tracks.append(MotionTrack(param.id, [
            MotionSegment("linear", (0.0, param.min), (mid, param.max)),
            MotionSegment("cubic-bezier", (mid, param.max), (duration, param.min),
                          c0=(mid + 0.2, param.max), c1=(duration - 0.2, param.min)),
        ]))
    return Motion("bench_sweep", duration, loop=True, tracks=tracks)


def many_drawables(count: int = 400, grid: int = 6) -> PuppetDocument:
    doc = PuppetDocument(size=CANVAS)
    bones = []
    for b in range(4):
        bone = Deformer(f"bone{b}", "bone_rotation", None, [],
                        default_rotation_form((512 + 340 * b, 1024)))
        bones.append(bone)
    doc.deformers.extend(bones)
    params = [_param(f"ParamBone{b}", -30, 30) for b in range(4)]
    params += [_param(f"ParamMorph{m}") for m in range(4)]
    for b, bone in enumerate(bones):
        params[b].keys = [ParameterKey(-30, {bone.id: {"angle": -0.5}}),
                          ParameterKey(30, {bone.id: {"angle": 0.5}})]
    doc.parameters = params
    per_row = int(math.ceil(math.sqrt(count)))
    cell = CANVAS[0] / per_row
    for i in range(count):
        x0, y0 = (i % per_row) * cell, (i // per_row) * cell
        vertices, uvs, indices = _grid(x0 + 2, y0 + 2, cell - 4, cell - 4, grid)
        texture = f"textures/d{i % 16}.png"
        drawable = Drawable(f"d{i}", texture, vertices, indices, uvs, draw_order=i)
        if i % 2 == 0:
            first, second = bones[i % 4].id, bones[(i + 1) % 4].id
            weights = [(k % grid) / (grid - 1) for k in range(len(vertices))]
            drawable.bone_weights = {first: [1 - w for w in weights], second: weights}
            for bone_id in (first, second):
                doc.deformer(bone_id).drawables.append(drawable.id)
        else:
            delta = [(3.0, -2.0)] * len(vertices)
            drawable.vertex_morphs = [{"parameter": f"ParamMorph{i % 4}",
                                       "delta_at_min": [(-x, -y) for x, y in delta],
                                       "delta_at_max": delta}]
        doc.drawables.append(drawable)
    doc.textures = {f"textures/d{t}.png": _texture(64, t) for t in range(16)}
    doc.motions = [_sweep_motion(params)]
    return doc


def deep_deformers(depth: int = 32, drawables: int = 40) -> PuppetDocument:
    doc = PuppetDocument(size=CANVAS)
    params = []
    parent = None
    for level in range(depth):
        kind = "rotation" if level % 2 == 0 else "warp"
        form = (default_rotation_form((1024, 300 + level * 40)) if kind == "rotation"
                else default_warp_form((200, 200 + level * 20, 1848, 1848), 4, 4))
        deformer = Deformer(f"def{level}", kind, parent, [], form)
        doc.deformers.append(deformer)
        param = _param(f"ParamLevel{level}")
        if kind == "rotation":
            param.keys = [ParameterKey(-1, {deformer.id: {"angle": -0.05}}),
                          ParameterKey(1, {deformer.id: {"angle": 0.05}})]
        else:
            shifted = default_warp_form((220, 200 + level * 20, 1868, 1848), 4, 4)
            param.keys = [ParameterKey(0, {deformer.id: {"grid": form["grid"]}}),
                          ParameterKey(1, {deformer.id: {"grid": shifted["grid"]}})]
        params.append(param)
        parent = deformer.id
    for i in range(drawables):
        vertices, uvs, indices = _grid(300 + (i % 8) * 180, 300 + (i // 8) * 280, 160, 240, 8)
        drawable = Drawable(f"part{i}", "textures/part.png", vertices, indices, uvs,
                            draw_order=i)
        doc.drawables.append(drawable)
        # A drawable at hierarchy depth k is moved by every ancestor 0..k.
        for level in range(1 + (i * depth) // drawables):
            doc.deformers[level].drawables.append(drawable.id)
    doc.parameters = params
    doc.textures = {"textures/part.png": _texture(128, 99)}
    doc.motions = [_sweep_motion(params)]
    return doc


def masks(pairs: int = 60) -> PuppetDocument:
    doc = PuppetDocument(size=CANVAS)
    per_row = 10
    cell = CANVAS[0] / per_row
    for i in range(pairs):
        x0, y0 = (i % per_row) * cell, (i // per_row) * cell
        vertices, uvs, indices = _grid(x0 + 8, y0 + 8, cell - 16, cell - 16, 4)
        doc.drawables.append(Drawable(f"mask{i}", "textures/mask.png", vertices, indices, uvs,
                                      draw_order=2 * i))
        vertices, uvs, indices = _grid(x0, y0, cell, cell, 4)
        doc.drawables.append(Drawable(f"clipped{i}", "textures/fill.png", vertices, indices,
                                      uvs, draw_order=2 * i + 1, clip_mask=f"mask{i}"))
    rotation = Deformer("sway", "rotation", None, [d.id for d in doc.drawables],
                        default_rotation_form((1024, 1024)))
    doc.deformers.append(rotation)
    param = _param("ParamSway")
    param.keys = [ParameterKey(-1, {"sway": {"angle": -0.1}}),
                  ParameterKey(1, {"sway": {"angle": 0.1}})]
    doc.parameters = [param]
    doc.textures = {"textures/mask.png": _texture(64, 1), "textures/fill.png": _texture(64, 2)}
    doc.motions = [_sweep_motion(doc.parameters)]
    return doc


def physics(chains: int = 48, particles: int = 8) -> PuppetDocument:
    doc = PuppetDocument(size=CANVAS)
    head = _param("ParamAngleX", -30, 30)
    doc.parameters.append(head)
    for c in range(chains):
        x0 = 100 + (c % 12) * 160
        y0 = 200 + (c // 12) * 420
        vertices, uvs, indices = _grid(x0, y0, 120, 380, 6)
        doc.drawables.append(Drawable(f"hair{c}", "textures/hair.png", vertices, indices, uvs,
                                      draw_order=c))
        warp = Deformer(f"warp{c}", "warp", None, [f"hair{c}"],
                        default_warp_form((x0, y0, x0 + 120, y0 + 380), 4, 4))
        doc.deformers.append(warp)
        out = _param(f"ParamHair{c}")
        left = default_warp_form((x0 - 40, y0, x0 + 80, y0 + 380), 4, 4)
        right = default_warp_form((x0 + 40, y0, x0 + 160, y0 + 380), 4, 4)
        out.keys = [ParameterKey(-1, {warp.id: {"grid": left["grid"]}}),
                    ParameterKey(0, {warp.id: {"grid": warp.form["grid"]}}),
                    ParameterKey(1, {warp.id: {"grid": right["grid"]}})]
        doc.parameters.append(out)
        doc.physics_rigs.append(PhysicsRig(
            f"chain{c}", head.id, out.id,
            [PhysicsParticle(mass=1.0 + 0.1 * p, damping=0.6, spring=10.0 + p)
             for p in range(particles)]))
    doc.textures = {"textures/hair.png": _texture(64, 7)}
    doc.motions = [_sweep_motion([head])]
    return doc


def load_imeru() -> PuppetDocument:
    from rigora.puppet.document_io import load_puppet
    from rigora.system.app_paths import examples_dir
    return load_puppet(examples_dir() / "puppet" / "imeru.puppet")


def build_scene(name: str) -> Scene:
    if name == "imeru":
        return Scene(name, [load_imeru()], "bundled example rig")
    if name == "multi_pet":
        return Scene(name, [load_imeru() for _ in range(4)], "four independent Imeru copies")
    builders = {"many_drawables": many_drawables, "deep_deformers": deep_deformers,
                "masks": masks, "physics": physics}
    if name not in builders:
        raise ValueError(f"unknown scene {name!r}; choose from {', '.join(SCENE_NAMES)}")
    doc = builders[name]()
    return Scene(name, [doc], (builders[name].__doc__ or name).strip())


def _deformer_depth(doc: PuppetDocument) -> int:
    parents = {d.id: d.parent for d in doc.deformers}
    deepest = 0
    for deformer_id in parents:
        depth, seen, current = 0, set(), deformer_id
        while current is not None and current not in seen:
            seen.add(current)
            depth += 1
            current = parents.get(current)
        deepest = max(deepest, depth)
    return deepest


def scene_scale(scene: Scene) -> dict:
    """Actual size of a scene, summed over its documents."""
    totals = {"documents": len(scene.documents), "drawables": 0, "vertices": 0, "triangles": 0,
              "deformers": 0, "max_deformer_depth": 0, "deformer_drawable_links": 0,
              "parameters": 0, "parameter_keys": 0, "clip_masks": 0, "bone_weighted": 0,
              "vertex_morphs": 0, "physics_rigs": 0, "physics_particles": 0, "textures": 0,
              "texture_bytes": 0, "motions": 0, "motion_tracks": 0}
    for doc in scene.documents:
        totals["drawables"] += len(doc.drawables)
        totals["vertices"] += sum(len(d.vertices) for d in doc.drawables)
        totals["triangles"] += sum(len(d.indices) // 3 for d in doc.drawables)
        totals["deformers"] += len(doc.deformers)
        totals["max_deformer_depth"] = max(totals["max_deformer_depth"], _deformer_depth(doc))
        totals["deformer_drawable_links"] += sum(len(d.drawables) for d in doc.deformers)
        totals["parameters"] += len(doc.parameters)
        totals["parameter_keys"] += sum(len(p.keys) for p in doc.parameters)
        totals["clip_masks"] += sum(d.clip_mask is not None for d in doc.drawables)
        totals["bone_weighted"] += sum(bool(d.bone_weights) for d in doc.drawables)
        totals["vertex_morphs"] += sum(len(d.vertex_morphs or []) for d in doc.drawables)
        totals["physics_rigs"] += len(doc.physics_rigs)
        totals["physics_particles"] += sum(len(r.chain) for r in doc.physics_rigs)
        totals["textures"] += len(doc.textures)
        totals["texture_bytes"] += sum(len(b) for b in doc.textures.values())
        totals["motions"] += len(doc.motions)
        totals["motion_tracks"] += sum(len(m.tracks) for m in doc.motions)
    return totals
