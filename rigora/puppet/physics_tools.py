"""Physics chain editing, presets and limit assessment (R2.5).

The simulation itself is unchanged (:mod:`rigora.puppet.physics`). These
helpers validate and edit :class:`PhysicsRig` entries, keep reusable
presets, and measure how a chain behaves under a sweeping input so a user
can see whether it needs a collision or limit feature that the engine does
not have yet: clipped output, output past the parameter's range, or a
chain that swings above its anchor.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rigora.puppet.document import PhysicsParticle, PhysicsRig, PuppetDocument
from rigora.puppet.physics import PhysicsEngine

PRESET_VERSION = 1

BUILTIN_PRESETS: dict[str, dict] = {
    "hair_short": {"gravity": [0.0, -9.8], "chain": [
        {"mass": 1.0, "damping": 0.7, "spring": 14.0} for _ in range(3)]},
    "hair_long": {"gravity": [0.0, -9.8], "chain": [
        {"mass": 1.0 + 0.1 * i, "damping": 0.6, "spring": 9.0} for i in range(6)]},
    "accessory": {"gravity": [0.0, -12.0], "chain": [
        {"mass": 1.5, "damping": 0.8, "spring": 18.0} for _ in range(2)]},
}


def validate_rig(document: PuppetDocument, rig: PhysicsRig) -> list[str]:
    """Problems that make a chain misbehave; empty when it is sound."""
    problems = []
    params = {p.id for p in document.parameters}
    if rig.input_param not in params:
        problems.append(f"input parameter {rig.input_param!r} does not exist")
    if rig.output_param not in params:
        problems.append(f"output parameter {rig.output_param!r} does not exist")
    if rig.input_param == rig.output_param:
        problems.append("input and output are the same parameter")
    if not rig.chain:
        problems.append("the chain has no particles")
    for index, particle in enumerate(rig.chain):
        if particle.mass <= 0:
            problems.append(f"particle {index}: mass must be positive")
        if not 0.0 <= particle.damping < 1.0:
            problems.append(f"particle {index}: damping must be in [0, 1)")
        if particle.spring <= 0:
            problems.append(f"particle {index}: spring must be positive")
    return problems


def rig_warnings(document: PuppetDocument, rig: PhysicsRig) -> list[str]:
    """Allowed but worth knowing: a later chain overrides an earlier one."""
    others = [r for r in document.physics_rigs if r is not rig]
    if any(r.output_param == rig.output_param for r in others):
        return [f"another chain also drives {rig.output_param!r}; the later one wins"]
    return []


def _chain(spec: list[dict]) -> list[PhysicsParticle]:
    return [PhysicsParticle(mass=float(p["mass"]), damping=float(p["damping"]),
                            spring=float(p["spring"])) for p in spec]


def upsert_rig(
    document: PuppetDocument, rig_id: str, *, input_param: str, output_param: str,
    chain: list[dict], gravity: tuple[float, float] = (0.0, -9.8),
) -> PhysicsRig:
    """Create or replace chain ``rig_id``; raises ``ValueError`` and leaves the
    document unchanged when the result would be invalid."""
    if not rig_id.strip():
        raise ValueError("chain id must not be empty")
    candidate = PhysicsRig(rig_id, input_param, output_param, _chain(chain),
                           (float(gravity[0]), float(gravity[1])))
    existing = next((r for r in document.physics_rigs if r.id == rig_id), None)
    others = [r for r in document.physics_rigs if r is not existing]
    probe = PuppetDocument(parameters=document.parameters, physics_rigs=[*others, candidate])
    problems = validate_rig(probe, candidate)
    if problems:
        raise ValueError("; ".join(problems))
    if existing is None:
        document.physics_rigs.append(candidate)
    else:
        document.physics_rigs[document.physics_rigs.index(existing)] = candidate
    return candidate


def remove_rig(document: PuppetDocument, rig_id: str) -> bool:
    before = len(document.physics_rigs)
    document.physics_rigs = [r for r in document.physics_rigs if r.id != rig_id]
    return len(document.physics_rigs) != before


def rig_to_preset(rig: PhysicsRig) -> dict:
    return {"gravity": list(rig.gravity), "chain": [asdict(p) for p in rig.chain]}


def apply_preset(document: PuppetDocument, rig_id: str, preset: dict) -> PhysicsRig:
    """Replace a chain's particles and gravity, keeping its parameter mapping."""
    rig = next((r for r in document.physics_rigs if r.id == rig_id), None)
    if rig is None:
        raise ValueError(f"no physics chain {rig_id!r}")
    _check_preset(preset)
    return upsert_rig(document, rig_id, input_param=rig.input_param,
                      output_param=rig.output_param, chain=preset["chain"],
                      gravity=tuple(preset["gravity"]))


def _check_preset(preset: dict) -> None:
    if not isinstance(preset, dict) or not isinstance(preset.get("chain"), list):
        raise ValueError("preset needs a chain list")
    gravity = preset.get("gravity")
    if not isinstance(gravity, list | tuple) or len(gravity) != 2:
        raise ValueError("preset gravity must be two numbers")
    for particle in preset["chain"]:
        if not isinstance(particle, dict) or not {"mass", "damping", "spring"} <= set(particle):
            raise ValueError("each preset particle needs mass, damping and spring")


class PresetStore:
    """User presets in one JSON file, written atomically; built-ins are read-only."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, dict]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        presets = data.get("presets", {}) if isinstance(data, dict) else {}
        valid = {}
        for name, preset in presets.items():
            try:
                _check_preset(preset)
            except ValueError:
                continue
            valid[str(name)] = preset
        return valid

    def names(self) -> list[str]:
        return [*BUILTIN_PRESETS, *sorted(self._read())]

    def get(self, name: str) -> dict:
        if name in BUILTIN_PRESETS:
            return BUILTIN_PRESETS[name]
        presets = self._read()
        if name not in presets:
            raise ValueError(f"no preset {name!r}")
        return presets[name]

    def save(self, name: str, preset: dict) -> None:
        if not name.strip() or name in BUILTIN_PRESETS:
            raise ValueError("choose a new, non-empty preset name")
        _check_preset(preset)
        from rigora.system.atomic_write import write_text_atomically
        presets = self._read()
        presets[name] = preset
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomically(
            self.path, json.dumps({"version": PRESET_VERSION, "presets": presets}, indent=2))


def default_preset_store() -> PresetStore:
    from rigora.system.app_paths import app_dir
    return PresetStore(Path(app_dir()) / "physics_presets.json")


# ---------------------------------------------------------------------------
# Limit assessment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LimitAssessment:
    rig: str
    output_min: float
    output_max: float
    saturated_fraction: float
    """Share of frames where the output sat at the engine's ±1 clamp."""
    outside_parameter_range: bool
    swings_above_anchor: bool
    settle_seconds: float | None
    """Time for the output to stay within 0.02 after the input stops; ``None``
    if it never settles in the sampled window."""
    needs: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return asdict(self)


def _sweep(seconds: float) -> Callable[[float], float]:
    """Input as a 0→1 share of the range: two full swings, then rest."""
    import math

    def value(t: float) -> float:
        if t >= seconds / 2:
            return 0.5
        return 0.5 + 0.5 * math.sin(2 * math.pi * 2 * t / (seconds / 2))
    return value


def assess_limits(document: PuppetDocument, rig_id: str, *, seconds: float = 4.0,
                  fps: float = 60.0) -> LimitAssessment:
    """Simulate ``rig_id`` alone under a sweeping input and report whether
    it would benefit from a limit or collision feature."""
    rig = next((r for r in document.physics_rigs if r.id == rig_id), None)
    if rig is None:
        raise ValueError(f"no physics chain {rig_id!r}")
    params = {p.id: p for p in document.parameters}
    source = params.get(rig.input_param)
    low, high = (source.min, source.max) if source else (-1.0, 1.0)
    engine = PhysicsEngine()
    engine.bind_document(PuppetDocument(parameters=document.parameters, physics_rigs=[rig]))
    sweep = _sweep(seconds)
    frames = int(seconds * fps)
    outputs, above = [], False
    for frame in range(frames):
        t = frame / fps
        value = low + (high - low) * sweep(t)
        outputs.append(engine.step(1.0 / fps, {rig.input_param: value})[rig.output_param])
        positions = engine.particle_positions(rig.id)
        above = above or bool((positions[1:, 1] > positions[0, 1]).any())
    saturated = sum(abs(o) >= 0.999 for o in outputs) / len(outputs)
    target = params.get(rig.output_param)
    outside = target is not None and (min(outputs) < target.min - 1e-9
                                      or max(outputs) > target.max + 1e-9)
    rest_start = int(frames / 2)
    final = outputs[-1]
    settle = None
    for index in range(rest_start, frames):
        if all(abs(o - final) <= 0.02 for o in outputs[index:]):
            settle = (index - rest_start) / fps
            break
    needs = []
    if saturated > 0.05:
        needs.append("output_clipped")
    if outside:
        needs.append("output_outside_parameter_range")
    if above:
        needs.append("swings_above_anchor")
    if settle is None:
        needs.append("does_not_settle")
    return LimitAssessment(rig.id, min(outputs), max(outputs), saturated, outside, above,
                           settle, tuple(needs))
