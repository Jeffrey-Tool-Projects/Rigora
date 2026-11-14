"""Rig doctor: diagnose → preview changes → apply → undo (R2.6).

One list of findings from mesh repair, weight normalisation, symmetry
gaps, pending auto-rig rules and the validator. Each finding names the
part it concerns (``drawable:arm_l``, ``deformer:head``…) so the editor
can select it. Fixable findings are previewed on a copy, which reports
exactly what would change, and applied to the document only on request.

Auto-rig rules are offered only when their result is not already in the
document, because running a rule twice would add duplicate deformers.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field

from rigora.puppet.auto_rig import _rig_eyes, _rig_hair_swing, _rig_head_tilt, _rig_mouth
from rigora.puppet.auto_rig_detect import (
    detect_eye,
    detect_hair,
    detect_head,
    detect_mouth_variant,
)
from rigora.puppet.bone_weights import needs_repair, normalize_drawable_weights
from rigora.puppet.document import PuppetDocument
from rigora.puppet.mesh_repair import repair_mesh
from rigora.puppet.rig_repair import RigRepairReport, _repair_drawable_mesh
from rigora.puppet.symmetrize import auto_mirror_pair, mirror_id
from rigora.puppet.validator import validate

KIND_MESH = "mesh"
KIND_WEIGHTS = "weights"
KIND_SYMMETRY = "symmetry"
KIND_AUTO_RIG = "auto_rig"
KIND_VALIDATION = "validation"

_RULES = {"eyes": _rig_eyes, "mouth": _rig_mouth, "head_tilt": _rig_head_tilt,
          "hair_swing": _rig_hair_swing}


@dataclass(frozen=True)
class Finding:
    id: str
    kind: str
    subject: str
    location: str
    severity: str
    message: str
    fixable: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FixPreview:
    applied: list[str] = field(default_factory=list)
    changed_drawables: dict[str, str] = field(default_factory=dict)
    added: dict[str, list[str]] = field(default_factory=dict)
    remaining: int = 0
    """Findings still reported after the fixes."""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------


def diagnose(document: PuppetDocument) -> list[Finding]:
    findings: list[Finding] = []
    findings += _mesh_findings(document)
    findings += _symmetry_findings(document)
    findings += _auto_rig_findings(document)
    findings += _validation_findings(document)
    return findings


def _mesh_findings(document: PuppetDocument) -> list[Finding]:
    found = []
    for drawable in document.drawables:
        location = f"drawable:{drawable.id}"
        if drawable.vertices and len(drawable.uvs) == len(drawable.vertices):
            report = repair_mesh(drawable.vertices, drawable.indices, drawable.uvs,
                                 match_uvs=True).report
            if report.changed:
                parts = [f"{count} {label}" for count, label in (
                    (report.removed_degenerate, "zero-area triangles"),
                    (report.dropped_out_of_range, "broken triangles"),
                    (report.merged_vertices, "duplicate vertices"),
                    (report.removed_unreferenced, "unused vertices")) if count]
                found.append(Finding(f"mesh:{drawable.id}", KIND_MESH, drawable.id, location,
                                     "warning", "mesh has " + ", ".join(parts), True))
        if drawable.bone_weights and needs_repair(drawable.bone_weights, len(drawable.vertices)):
            found.append(Finding(f"weights:{drawable.id}", KIND_WEIGHTS, drawable.id, location,
                                 "warning", "bone weights do not sum to 1 on every vertex",
                                 True))
    return found


def _symmetry_findings(document: PuppetDocument) -> list[Finding]:
    ids = {d.id for d in document.drawables}
    found = []
    for drawable in document.drawables:
        partner = mirror_id(drawable.id)
        if partner.endswith("_mirrored") or partner in ids:
            continue
        found.append(Finding(f"symmetry:{drawable.id}", KIND_SYMMETRY, drawable.id,
                             f"drawable:{drawable.id}", "info",
                             f"no mirrored partner {partner!r}; a mirrored copy can be added",
                             True))
    return found


def _rule_done(document: PuppetDocument, rule: str) -> bool:
    drawables = document.drawables
    if rule == "eyes":
        targets = [d for d in drawables if detect_eye(d.id)]
        return all(d.opacity_keys for d in targets)
    if rule == "mouth":
        targets = [d for d in drawables if detect_mouth_variant(d.id)]
        return all(d.opacity_keys for d in targets)
    detector = detect_head if rule == "head_tilt" else detect_hair
    kind = "rotation" if rule == "head_tilt" else "warp"
    targets = {d.id for d in drawables if detector(d.id)}
    return any(f.type == kind and targets <= set(f.drawables) for f in document.deformers)


def _auto_rig_findings(document: PuppetDocument) -> list[Finding]:
    detectors = {"eyes": detect_eye, "mouth": detect_mouth_variant, "head_tilt": detect_head,
                 "hair_swing": detect_hair}
    found = []
    for rule, detector in detectors.items():
        targets = [d.id for d in document.drawables if detector(d.id)]
        if not targets or _rule_done(document, rule):
            continue
        found.append(Finding(f"auto_rig:{rule}", KIND_AUTO_RIG, ", ".join(targets),
                             f"drawable:{targets[0]}", "info",
                             f"auto-rig rule {rule!r} applies to {len(targets)} drawable(s)",
                             True))
    return found


def _validation_findings(document: PuppetDocument) -> list[Finding]:
    found = []
    for index, issue in enumerate(validate(document)):
        if issue.code == "bone_weights_not_normalised":
            continue   # reported (and fixable) as a weights finding
        subject = issue.location.split(":", 1)[1] if ":" in issue.location else issue.location
        found.append(Finding(f"validation:{index}:{issue.code}", KIND_VALIDATION, subject,
                             issue.location, issue.severity, issue.message, False))
    return found


# ---------------------------------------------------------------------------
# Fixes
# ---------------------------------------------------------------------------


def _apply_one(document: PuppetDocument, finding_id: str) -> bool:
    kind, _, subject = finding_id.partition(":")
    if kind == KIND_MESH:
        drawable = document.drawable(subject)
        return drawable is not None and _repair_drawable_mesh(drawable, RigRepairReport())
    if kind == KIND_WEIGHTS:
        drawable = document.drawable(subject)
        return drawable is not None and normalize_drawable_weights(drawable)
    if kind == KIND_SYMMETRY:
        return auto_mirror_pair(document, subject) is not None
    if kind == KIND_AUTO_RIG and subject in _RULES and not _rule_done(document, subject):
        return bool(_RULES[subject](document))
    return False


def _diff(before: PuppetDocument, after: PuppetDocument) -> tuple[dict, dict]:
    old = {d.id: d for d in before.drawables}
    changed = {}
    for drawable in after.drawables:
        previous = old.get(drawable.id)
        if previous is None:
            continue
        notes = []
        if len(previous.vertices) != len(drawable.vertices):
            notes.append(f"vertices {len(previous.vertices)}→{len(drawable.vertices)}")
        if len(previous.indices) != len(drawable.indices):
            notes.append(f"triangles {len(previous.indices) // 3}→{len(drawable.indices) // 3}")
        if previous.bone_weights != drawable.bone_weights:
            notes.append("weights normalised")
        if previous.opacity_keys != drawable.opacity_keys:
            notes.append("opacity keys added")
        if notes:
            changed[drawable.id] = ", ".join(notes)
    added = {}
    for name in ("drawables", "deformers", "parameters", "physics_rigs"):
        before_ids = {item.id for item in getattr(before, name)}
        new = [item.id for item in getattr(after, name) if item.id not in before_ids]
        if new:
            added[name] = new
    return changed, added


def preview_fixes(document: PuppetDocument, finding_ids: list[str]) -> FixPreview:
    """What applying ``finding_ids`` would change, computed on a copy."""
    copy = deepcopy(document)
    return _run(copy, document, finding_ids)


def apply_fixes(document: PuppetDocument, finding_ids: list[str]) -> FixPreview:
    """Apply ``finding_ids`` in place; unknown or unfixable ids are skipped."""
    before = deepcopy(document)
    return _run(document, before, finding_ids)


def _run(target: PuppetDocument, reference: PuppetDocument, finding_ids: list[str]) -> FixPreview:
    fixable = {f.id for f in diagnose(target) if f.fixable}
    preview = FixPreview()
    for finding_id in finding_ids:
        if finding_id in fixable and _apply_one(target, finding_id):
            preview.applied.append(finding_id)
    preview.changed_drawables, preview.added = _diff(reference, target)
    preview.remaining = len(diagnose(target))
    return preview
