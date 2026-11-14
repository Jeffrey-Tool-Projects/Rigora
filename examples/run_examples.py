"""Build every example and check its expected result.

    py -3 examples/run_examples.py [--output DIR] [--render]

Each example is built from files in this repository (MIT, see ``LICENSE``)
with the same commands its README shows. ``--render`` also runs the GPU export
steps, which need a desktop session with OpenGL; without it they are reported
as skipped, never as passed. Exit status 0 means every built example matched
its expected result.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def rigora(*args: str) -> dict:
    done = subprocess.run([sys.executable, "-m", "rigora.cli", *args, "--json"],
                          capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
                          check=False)
    payload = json.loads(done.stdout) if done.stdout.strip() else {}
    if isinstance(payload, list):
        payload = payload[0]
    if done.returncode != 0:
        raise RuntimeError(f"rigora {' '.join(args)} failed ({done.returncode}): "
                           f"{payload.get('error') or done.stderr.strip()}")
    return payload


def expect(condition, message) -> None:
    if not condition:
        raise AssertionError(message)


def basic(out: Path) -> dict:
    """PNG → rig, then inspect and validate it."""
    rig = out / "basic.puppet"
    rig.unlink(missing_ok=True)       # puppet-from-png has no --overwrite
    rigora("puppet-from-png", str(EXAMPLES / "puppet/imeru/artwork/master.png"),
           "--destination", str(rig), "--cell-size", "64")
    info = rigora("puppet-inspect", str(rig))
    report = rigora("puppet-validate", str(rig))
    expect(report["valid"], f"basic rig is invalid: {report}")
    expect(len(info["drawables"]) >= 1 and len(info["parameters"]) >= 5,
           f"unexpected rig: {info}")
    return {"drawables": len(info["drawables"]), "parameters": len(info["parameters"]),
            "motions": len(info["motions"])}


def advanced_rig(out: Path) -> dict:
    """The bundled Imeru rig: deformers, bones, physics; diagnose and repair."""
    rig = EXAMPLES / "puppet/imeru.puppet"
    info = rigora("puppet-inspect", str(rig))
    doctor = rigora("rig-doctor", str(rig))
    errors = [f for f in doctor["findings"] if f.get("severity") == "error"]
    expect(not errors, f"Imeru has rig errors: {errors}")
    repaired = out / "imeru-checked.puppet"
    rigora("rig-doctor", str(rig), "--fixes", '["safe"]', "--destination", str(repaired),
           "--overwrite")
    expect(rigora("puppet-validate", str(repaired))["valid"], "repaired copy is invalid")
    expect(len(info["deformers"]) == 6 and len(info["physics_rigs"]) == 3,
           f"unexpected Imeru rig: {info}")
    return {"drawables": len(info["drawables"]), "deformers": len(info["deformers"]),
            "physics_rigs": len(info["physics_rigs"]), "findings": len(doctor["findings"])}


def animation(out: Path, render: bool) -> dict:
    """A composition of Imeru's motions, baked into a motion and exported."""
    sys.path.insert(0, str(ROOT))
    from rigora.puppet.document import Clip, Composition, CompositionLayer
    from rigora.puppet.document_io import load_puppet, save_puppet
    document = load_puppet(EXAMPLES / "puppet/imeru.puppet")
    document.compositions = [Composition("hello", 4.0, [
        CompositionLayer("body", [Clip("idle_breath", loop=True, length=4.0),
                                  Clip("wave", start=0.5, fade_in=0.3, fade_out=0.3)]),
        CompositionLayer("face", [Clip("greet", start=0.2)], blend="additive", weight=0.6)])]
    source = out / "imeru-hello.puppet"
    save_puppet(document, source)
    baked = out / "imeru-hello-baked.puppet"
    result = rigora("bake-composition", str(source), "--composition", "hello",
                    "--destination", str(baked), "--overwrite")
    motions = {m.name: m for m in load_puppet(baked).motions}
    expect(result["motion"] in motions
           and math.isclose(motions[result["motion"]].duration, 4.0),
           f"baked motion missing: {result}")
    summary = {"baked_motion": result["motion"], "tracks": result["tracks"]}
    if render:
        frames = out / "hello-frames"
        export = rigora("export-animation", str(baked), "--destination", str(frames),
                        "--motion", result["motion"], "--width", "256", "--height", "416",
                        "--fps", "12", "--overwrite")
        pngs = sorted(frames.glob("*.png"))
        expect(len(pngs) == export["frames"] == 48, f"expected 4 s x 12 fps = 48: {export}")
        summary["exported_frames"] = len(pngs)
    else:
        summary["export"] = "skipped (needs --render and OpenGL)"
    return summary


def live(out: Path) -> dict:
    """The VTS example client talking to Rigora's protocol handler."""
    sys.path.insert(0, str(EXAMPLES / "live"))
    import vts_client
    from rigora.puppet.document_io import load_puppet
    from rigora.puppet.input_calibration import InputProfile
    profile = InputProfile.from_dict(json.loads(
        (EXAMPLES / "live/desk.input-profile.json").read_text(encoding="utf-8")))
    expect(profile.name == "Desk" and "ParamAngleX" in profile.channels, "profile not read")
    values = vts_client.run_offline(load_puppet(EXAMPLES / "puppet/imeru.puppet"), seconds=1.0)
    expect(abs(values["ParamAngleX"]) > 0.01, f"tracker did not move the head: {values}")
    return {"frames_sent": vts_client.FRAMES_PER_SECOND, "angle_x": round(values["ParamAngleX"],
                                                                          3)}


def desktop_pet(out: Path) -> dict:
    """Both pet scripts load, pass the rule checks against Imeru and behave."""
    sys.path.insert(0, str(ROOT))
    from rigora.desktop_pet.pet_behavior import BehaviorEngine, validate
    from rigora.desktop_pet.pet_script import load_script
    from rigora.puppet.document_io import load_puppet
    document = load_puppet(EXAMPLES / "puppet/imeru.puppet")
    context = {"motions": {m.name for m in document.motions},
               "groups": {m.group for m in document.motions if m.group},
               "expressions": {e.name for e in document.expressions},
               "hit_areas": {h.id for h in document.hit_areas}}
    results = {}
    for path in sorted((EXAMPLES / "desktop_pet").glob("*.petscript.json")):
        script = load_script(path)
        problems = validate(script.behaviors, **context)
        expect(not problems, f"{path.name}: {problems}")
        results[path.name] = {"greetings": len(script.greetings)}
        if script.behaviors:
            trace = BehaviorEngine(script.behaviors).simulate(
                [(0, "start"), (1, "click:Head"), (2, "click:Head"), (25, "tick")])
            ran = [t.rule for t in trace if t.outcome == "ran"]
            expect(ran[:3] == ["hello", "pat", "calm_down"], f"unexpected run: {ran}")
            results[path.name]["rules_ran"] = ran
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(argv)
    out = args.output or Path(tempfile.mkdtemp(prefix="rigora-examples-"))
    out.mkdir(parents=True, exist_ok=True)
    report, failed = {}, False
    for name, run in (("basic", basic), ("advanced_rig", advanced_rig),
                      ("animation", lambda o: animation(o, args.render)), ("live", live),
                      ("desktop_pet", desktop_pet)):
        try:
            report[name] = {"status": "passed", **run(out)}
        except Exception as exc:   # noqa: BLE001 - report every example
            report[name] = {"status": "failed", "error": str(exc)}
            failed = True
    print(json.dumps({"output": str(out), "examples": report}, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
