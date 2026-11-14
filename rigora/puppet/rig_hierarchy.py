"""Qt-free deformer hierarchy and parameter edits with validation (R2.4).

Every function either changes the document consistently or raises
``ValueError`` without touching it, so the editor can run it inside one
transaction. Sibling order in ``document.deformers`` is the order deformers
sharing a parent run in, so reordering is a real rig change.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from rigora.puppet.document import Deformer, Parameter, PuppetDocument

# ---------------------------------------------------------------------------
# Deformer hierarchy
# ---------------------------------------------------------------------------


def ancestors(document: PuppetDocument, deformer_id: str) -> list[str]:
    """Parent chain from the nearest parent upward; stops at a cycle."""
    by_id = {d.id: d for d in document.deformers}
    chain: list[str] = []
    current = by_id.get(deformer_id)
    while current is not None and current.parent and current.parent not in chain:
        chain.append(current.parent)
        current = by_id.get(current.parent)
    return chain


def find_cycles(document: PuppetDocument) -> list[list[str]]:
    """Each parent cycle once, as the ids along the loop."""
    by_id = {d.id: d for d in document.deformers}
    seen: set[str] = set()
    cycles: list[list[str]] = []
    for start in by_id:
        path: list[str] = []
        current = start
        while current in by_id and current not in seen and current not in path:
            path.append(current)
            current = by_id[current].parent
        if current in path:
            loop = path[path.index(current):]
            cycles.append(loop)
        seen.update(path)
    return cycles


def missing_parents(document: PuppetDocument) -> list[str]:
    known = {d.id for d in document.deformers}
    return [d.id for d in document.deformers if d.parent and d.parent not in known]


def reparent_deformer(document: PuppetDocument, child_id: str, parent_id: str | None) -> bool:
    """Set ``child_id``'s parent. Returns ``False`` when nothing changes;
    raises ``ValueError`` for unknown ids or a move that would form a cycle."""
    child = document.deformer(child_id)
    if child is None:
        raise ValueError(f"no deformer {child_id!r}")
    if parent_id is not None:
        if document.deformer(parent_id) is None:
            raise ValueError(f"no deformer {parent_id!r}")
        if parent_id == child_id or child_id in ancestors(document, parent_id):
            raise ValueError(f"{child_id} cannot move under its own descendant {parent_id}")
    if child.parent == parent_id:
        return False
    child.parent = parent_id
    return True


def siblings(document: PuppetDocument, deformer_id: str) -> list[Deformer]:
    deformer = document.deformer(deformer_id)
    if deformer is None:
        raise ValueError(f"no deformer {deformer_id!r}")
    return [d for d in document.deformers if d.parent == deformer.parent]


def move_deformer(document: PuppetDocument, deformer_id: str, offset: int) -> bool:
    """Move a deformer ``offset`` places among its siblings (negative = earlier,
    i.e. applied first). Returns ``False`` when it is already at that end."""
    step = 1 if offset > 0 else -1
    moved = False
    for _ in range(abs(offset)):
        group = siblings(document, deformer_id)
        index = next(i for i, d in enumerate(group) if d.id == deformer_id)
        if not 0 <= index + step < len(group):
            break
        items = document.deformers
        a = next(i for i, d in enumerate(items) if d is group[index])
        b = next(i for i, d in enumerate(items) if d is group[index + step])
        items[a], items[b] = items[b], items[a]
        moved = True
    return moved


def search_deformers(document: PuppetDocument, text: str) -> list[str]:
    """Deformer ids whose id, type or target drawables contain ``text``
    (case-insensitive). An empty query matches everything."""
    needle = text.strip().lower()
    return [d.id for d in document.deformers
            if not needle or needle in d.id.lower() or needle in d.type
            or any(needle in drawable.lower() for drawable in d.drawables)]


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

_GROUP_PATTERNS = (
    ("Head", r"angle|head|face|neck"),
    ("Eyes", r"eye|brow|pupil|blink"),
    ("Mouth", r"mouth|lip|cheek|tongue"),
    ("Body", r"body|breath|arm|hand|leg|shoulder|bust|waist"),
    ("Hair", r"hair|bang|fringe|tail|ahoge"),
)


def parameter_group(parameter_id: str) -> str:
    """A display group from the id, following Cubism naming (``ParamEyeLOpen``
    → Eyes). Unmatched ids land in ``Other``."""
    lowered = parameter_id.lower().removeprefix("param")
    for name, pattern in _GROUP_PATTERNS:
        if re.search(pattern, lowered):
            return name
    return "Other"


def grouped_parameters(document: PuppetDocument, text: str = "") -> dict[str, list[str]]:
    """``{group: [parameter ids]}`` in document order, filtered by ``text``
    against the id and its display name."""
    needle = text.strip().lower()
    groups: dict[str, list[str]] = {}
    for parameter in document.parameters:
        label = document.display_names.get(parameter.id, "")
        if needle and needle not in parameter.id.lower() and needle not in label.lower():
            continue
        groups.setdefault(parameter_group(parameter.id), []).append(parameter.id)
    order = [name for name, _ in _GROUP_PATTERNS] + ["Other"]
    return {name: groups[name] for name in order if name in groups}


@dataclass(frozen=True)
class KeySummary:
    value: float
    deformers: tuple[str, ...]
    fields: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def key_summary(document: PuppetDocument, parameter_id: str) -> list[KeySummary]:
    """Each key form on a parameter with the deformers and form fields it sets."""
    parameter = document.parameter(parameter_id)
    if parameter is None:
        raise ValueError(f"no parameter {parameter_id!r}")
    return [KeySummary(key.value, tuple(sorted(key.forms)),
                       tuple(sorted({field for form in key.forms.values() for field in form})))
            for key in sorted(parameter.keys, key=lambda k: k.value)]


def blend_axes(document: PuppetDocument, parameter_id: str) -> list[str]:
    """Multi-axis blends that use the parameter, which a range change also affects."""
    return [blend.id for blend in document.parameter_blends if parameter_id in blend.parameters]


def set_parameter_range(
    document: PuppetDocument, parameter_id: str, minimum: float, maximum: float,
    default: float,
) -> Parameter:
    """Change a parameter's range and default.

    Refuses (``ValueError``) a range that would strand existing keys, blend
    keys or expression values outside it, so a range edit never silently
    changes how the rig moves.
    """
    parameter = document.parameter(parameter_id)
    if parameter is None:
        raise ValueError(f"no parameter {parameter_id!r}")
    if not minimum < maximum:
        raise ValueError("minimum must be below maximum")
    if not minimum <= default <= maximum:
        raise ValueError("default must lie within the range")
    outside = [k.value for k in parameter.keys if not minimum <= k.value <= maximum]
    for blend in document.parameter_blends:
        if parameter_id in blend.parameters:
            axis = blend.parameters.index(parameter_id)
            outside += [k.coords[axis] for k in blend.keys
                        if axis < len(k.coords) and not minimum <= k.coords[axis] <= maximum]
    for expression in document.expressions:
        outside += [p.value for p in expression.params
                    if p.id == parameter_id and p.mode == "overwrite"
                    and not minimum <= p.value <= maximum]
    if outside:
        listing = ", ".join(f"{v:g}" for v in sorted(set(outside)))
        raise ValueError(f"keys at {listing} would fall outside {minimum:g}..{maximum:g}")
    parameter.min, parameter.max, parameter.default = float(minimum), float(maximum), \
        float(default)
    return parameter
