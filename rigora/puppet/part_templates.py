"""Reusable part templates: eye blink, mouth shapes, head turn and sway (R2.7).

A template binds named *roles* to drawables the user picks, so it works
whatever the layers are called. Each template states what artwork it
needs; :func:`check_template` reports what is missing before anything is
changed. Templates add behaviour to parts that already exist as separate
layers — they do not split a single flat image into parts, and a rig made
from one PNG gets a warning instead of a claim of full layered rigging.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from rigora.puppet.auto_rig import _mouth_form_curve, _mouth_open_curve, _swayed_grid
from rigora.puppet.auto_rig_mutators import (
    _drawable_group_bounds,
    _drawable_group_centre,
    _ensure_opacity_keys,
    _ensure_parameter,
    _set_param_keys,
    _unique_deformer_id,
    _unique_physics_id,
)
from rigora.puppet.deformers import default_rotation_form, default_warp_form
from rigora.puppet.document import Deformer, PhysicsParticle, PhysicsRig, PuppetDocument

_VOWELS = ("a", "i", "u", "e", "o")


@dataclass(frozen=True)
class Role:
    name: str
    required: bool
    many: bool
    description: str


@dataclass(frozen=True)
class PartTemplate:
    id: str
    title: str
    roles: tuple[Role, ...]
    requirements: tuple[str, ...]
    """Artwork conditions the template needs, stated for the user."""
    parameters: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


TEMPLATES: dict[str, PartTemplate] = {
    "eye_blink": PartTemplate(
        "eye_blink", "Eye blink",
        (Role("left_open", False, False, "left eye, open"),
         Role("left_closed", False, False, "left eye, closed"),
         Role("right_open", False, False, "right eye, open"),
         Role("right_closed", False, False, "right eye, closed")),
        ("open and closed eyes drawn as separate layers in the same place",
         "at least one side with both states"),
        ("ParamEyeLOpen", "ParamEyeROpen")),
    "mouth_shapes": PartTemplate(
        "mouth_shapes", "Mouth shapes",
        (Role("closed", True, False, "closed mouth"), Role("open", True, False, "open mouth"),
         *(Role(v, False, False, f"vowel '{v}' mouth") for v in _VOWELS)),
        ("closed and open mouths as separate layers in the same place",
         "optional vowel layers (a, i, u, e, o) for lip-sync shapes"),
        ("ParamMouthOpenY", "ParamMouthForm")),
    "head_turn": PartTemplate(
        "head_turn", "Head turn",
        (Role("head", True, True, "head outline, hair and ears that rotate together"),
         Role("features", False, True, "eyes, brows, nose and mouth that shift for parallax")),
        ("the head separated from the body",
         "face features on their own layers for a left/right turn; without them only "
         "the tilt works"),
        ("ParamAngleZ", "ParamAngleX")),
    "sway": PartTemplate(
        "sway", "Sway",
        (Role("parts", True, True, "hair, ribbons or accessories that swing"),),
        ("swinging parts separated from what they hang from",
         "the attachment point at the top of the selected layers"),
        ("ParamAngleX",)),
}

_TILT = math.radians(12.0)
_TURN_SHIFT = 0.06
_PARALLAX = 2.0


def _drawables(document: PuppetDocument, ids) -> list[str]:
    return [i for i in ids if document.drawable(i) is not None]


def check_template(document: PuppetDocument, template_id: str,
                   mapping: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """``(problems, warnings)``. Problems block :func:`apply_template`."""
    template = TEMPLATES.get(template_id)
    if template is None:
        return [f"no template {template_id!r}"], []
    problems, warnings = [], []
    known = {role.name for role in template.roles}
    for name in mapping:
        if name not in known:
            problems.append(f"unknown role {name!r}")
    used: dict[str, str] = {}
    for role in template.roles:
        ids = mapping.get(role.name, [])
        missing = [i for i in ids if document.drawable(i) is None]
        if missing:
            problems.append(f"{role.name}: no drawable {', '.join(missing)}")
        empty = [i for i in ids if (d := document.drawable(i)) is not None and not d.vertices]
        if empty:
            problems.append(f"{role.name}: {', '.join(empty)} has no mesh")
        if role.required and not _drawables(document, ids):
            problems.append(f"{role.name} needs a drawable ({role.description})")
        if not role.many and len(ids) > 1:
            problems.append(f"{role.name} takes one drawable")
        for drawable_id in ids:
            if drawable_id in used and template_id != "head_turn":
                problems.append(f"{drawable_id} is used for both {used[drawable_id]} "
                                f"and {role.name}")
            used.setdefault(drawable_id, role.name)
    problems += _specific_checks(template_id, mapping, warnings)
    warnings += template_notes(document, template_id, mapping)
    if len(document.drawables) <= 1:
        warnings.append("this rig has a single drawable (e.g. from one PNG); templates "
                        "animate separate layers and cannot split a flat image into parts")
    return problems, warnings


def _specific_checks(template_id: str, mapping: dict[str, list[str]],
                     warnings: list[str]) -> list[str]:
    if template_id == "eye_blink":
        sides = [side for side in ("left", "right")
                 if mapping.get(f"{side}_open") and mapping.get(f"{side}_closed")]
        half = [side for side in ("left", "right")
                if bool(mapping.get(f"{side}_open")) != bool(mapping.get(f"{side}_closed"))]
        problems = [f"{side} eye needs both the open and the closed layer" for side in half]
        if not sides and not half:
            problems.append("map the open and closed layers of at least one eye")
        return problems
    if template_id == "head_turn" and not mapping.get("features"):
        warnings.append("no face-feature layers: the left/right turn has no parallax and "
                        "only shifts the head")
    return []


def template_notes(document: PuppetDocument, template_id: str,
                   mapping: dict[str, list[str]]) -> list[str]:
    """What the template reuses rather than adds."""
    if template_id == "head_turn" and mapping.get("head"):
        tilt = existing_head_tilt(document, _drawables(document, mapping["head"]))
        if tilt is not None:
            return [f"reuses the existing head tilt {tilt!r} instead of adding another"]
    return []


def apply_template(document: PuppetDocument, template_id: str,
                   mapping: dict[str, list[str]]) -> dict[str, list[str]]:
    """Apply a checked template in place; returns what was added or keyed.
    Raises ``ValueError`` with the problems when the mapping does not fit."""
    problems, _warnings = check_template(document, template_id, mapping)
    if problems:
        raise ValueError("; ".join(problems))
    mapping = {role: _drawables(document, ids) for role, ids in mapping.items()}
    return {"eye_blink": _eye_blink, "mouth_shapes": _mouth_shapes,
            "head_turn": _head_turn, "sway": _sway}[template_id](document, mapping)


def _eye_blink(document, mapping) -> dict[str, list[str]]:
    keyed = []
    for side, param in (("left", "ParamEyeLOpen"), ("right", "ParamEyeROpen")):
        if not (mapping.get(f"{side}_open") and mapping.get(f"{side}_closed")):
            continue
        _ensure_parameter(document, param)
        parameter = document.parameter(param)
        parameter.min, parameter.max = min(parameter.min, 0.0), max(parameter.max, 1.0)
        for role, stops in ((f"{side}_open", [(0.0, 0.0), (1.0, 1.0)]),
                            (f"{side}_closed", [(0.0, 1.0), (1.0, 0.0)])):
            drawable = document.drawable(mapping[role][0])
            _ensure_opacity_keys(drawable, param,
                                 [{"value": v, "alpha": a} for v, a in stops])
            keyed.append(drawable.id)
    return {"opacity_keys": keyed}


def _mouth_shapes(document, mapping) -> dict[str, list[str]]:
    keyed = []
    for param in ("ParamMouthOpenY", "ParamMouthForm"):
        _ensure_parameter(document, param)
    for role, variant in (("closed", "close"), ("open", "open"),
                          *((v, v) for v in _VOWELS)):
        for drawable_id in mapping.get(role, []):
            drawable = document.drawable(drawable_id)
            _ensure_opacity_keys(drawable, "ParamMouthOpenY", _mouth_open_curve(variant))
            form = _mouth_form_curve(variant)
            if form is not None:
                _ensure_opacity_keys(drawable, "ParamMouthForm", form)
            keyed.append(drawable_id)
    return {"opacity_keys": keyed}


def existing_head_tilt(document: PuppetDocument, head: list[str]) -> str | None:
    """A rotation deformer already keyed on ``ParamAngleZ`` that moves any of
    the head layers — the PSD auto-rig adds one — so a second tilt is not
    stacked on the layers they share."""
    keyed = {deformer_id for parameter in document.parameters if parameter.id == "ParamAngleZ"
             for key in parameter.keys for deformer_id in key.forms}
    for deformer in document.deformers:
        if (deformer.type == "rotation" and deformer.id in keyed
                and set(head) & set(deformer.drawables)):
            return deformer.id
    return None


def _head_turn(document, mapping) -> dict[str, list[str]]:
    head = mapping["head"]
    features = [i for i in mapping.get("features", []) if i not in head]
    everything = head + features
    added = []
    tilt_id = existing_head_tilt(document, head)
    if tilt_id is None:
        tilt_id = _unique_deformer_id(document, "head_tilt")
        document.deformers.append(Deformer(
            tilt_id, "rotation", None, everything,
            default_rotation_form(_drawable_group_centre(document, head))))
        added.append(tilt_id)
        _ensure_parameter(document, "ParamAngleZ")
        _set_param_keys(document, "ParamAngleZ", {
            -1.0: {tilt_id: {"angle": -_TILT}}, 0.0: {tilt_id: {"angle": 0.0}},
            1.0: {tilt_id: {"angle": _TILT}}})
    else:
        tilt = document.deformer(tilt_id)
        tilt.drawables += [i for i in everything if i not in tilt.drawables]
    bounds = _drawable_group_bounds(document, everything)
    turn_id = _unique_deformer_id(document, "head_turn")
    turn = Deformer(turn_id, "warp", tilt_id, list(head), default_warp_form(bounds, 3, 3))
    document.deformers.append(turn)
    added.append(turn_id)
    width = bounds[2] - bounds[0]
    _ensure_parameter(document, "ParamAngleX")
    keys = {value: {turn_id: {"grid": _shifted(turn.form, value * width * _TURN_SHIFT)}}
            for value in (-1.0, 0.0, 1.0)}
    if features:
        feature_id = _unique_deformer_id(document, "face_parallax")
        feature = Deformer(feature_id, "warp", tilt_id, features,
                           default_warp_form(_drawable_group_bounds(document, features), 3, 3))
        document.deformers.append(feature)
        added.append(feature_id)
        for value, forms in keys.items():
            forms[feature_id] = {"grid": _shifted(
                feature.form, value * width * _TURN_SHIFT * _PARALLAX)}
    _scale_keys_to_range(document, "ParamAngleX", keys)
    return {"deformers": added}


def _shifted(form: dict, dx: float) -> list[list[list[float]]]:
    return [[[x + dx, y] for x, y in row] for row in form["grid"]]


def _scale_keys_to_range(document, param_id, keys) -> None:
    """Place the ±1 keys at the parameter's own min / max (±30 for Cubism angles)."""
    parameter = document.parameter(param_id)
    scaled = {}
    for value, forms in keys.items():
        target = parameter.max if value > 0 else parameter.min if value < 0 else parameter.default
        scaled[target] = forms
    _set_param_keys(document, param_id, scaled)


def _sway(document, mapping) -> dict[str, list[str]]:
    parts = mapping["parts"]
    bounds = _drawable_group_bounds(document, parts)
    warp_id = _unique_deformer_id(document, "sway")
    warp = Deformer(warp_id, "warp", None, list(parts), default_warp_form(bounds, 4, 4))
    document.deformers.append(warp)
    output = _unique_parameter(document, "ParamSway")
    _ensure_parameter(document, output)
    shift = (bounds[2] - bounds[0]) * 0.1
    _set_param_keys(document, output, {
        v: {warp_id: {"grid": _swayed_grid(warp.form, v * shift)}} for v in (-1.0, 0.0, 1.0)})
    _ensure_parameter(document, "ParamAngleX")
    chain_id = _unique_physics_id(document, "sway_chain")
    document.physics_rigs.append(PhysicsRig(chain_id, "ParamAngleX", output,
                                            [PhysicsParticle() for _ in range(3)]))
    return {"deformers": [warp_id], "parameters": [output], "physics_rigs": [chain_id]}


def _unique_parameter(document, prefix: str) -> str:
    taken = {p.id for p in document.parameters}
    if prefix not in taken:
        return prefix
    index = 2
    while f"{prefix}{index}" in taken:
        index += 1
    return f"{prefix}{index}"
