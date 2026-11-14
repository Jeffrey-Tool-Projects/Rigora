"""R2.1: Cubism import preview reports files, skipped data and blockers."""
from __future__ import annotations

import json

import pytest

from rigora.puppet.cubism_import_common import CubismFormatError
from rigora.puppet.cubism_preview import preview_cubism_model
from rigora.puppet.document import Motion, Parameter, PuppetDocument


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("CUBISM_CORE_DLL", raising=False)
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "model"
    (root / "tex").mkdir(parents=True)
    (root / "tex" / "a.png").write_bytes(b"png")
    _write(root / "idle.motion3.json", {"Meta": {"Duration": 1}, "Curves": [
        {"Target": "Parameter", "Id": "ParamAngleX", "Segments": [0, 0, 0, 1, 1]},
        {"Target": "PartOpacity", "Id": "PartArm", "Segments": [0, 1, 0, 1, 0]},
        {"Target": "Model", "Id": "Opacity", "Segments": [0, 1, 0, 1, 1]},
    ]})
    _write(root / "phys.physics3.json", {"PhysicsSettings": []})
    _write(root / "pose.pose3.json", {"Groups": []})
    _write(root / "motions" / "extra.motion3.json", {"Meta": {"Duration": 1}, "Curves": []})
    _write(root / "rig.model3.json", {
        "Version": 3,
        "FileReferences": {
            "Moc": "rig.moc3",
            "Textures": ["tex/a.png", "tex/b.png"],
            "Motions": {"Idle": [{"File": "idle.motion3.json", "Sound": "voice.wav"}],
                        "Tap": [{"File": "gone.motion3.json"}]},
            "Expressions": [{"Name": "smile", "File": "smile.exp3.json"}],
            "Physics": "phys.physics3.json",
            "Pose": "pose.pose3.json",
            "UserData": "rig.userdata3.json",
        },
        "HitAreas": [{"Id": "HitHead", "Name": "Head"}],
    })
    return root / "rig.model3.json"


def _codes(preview) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for diff in preview.differences:
        out.setdefault(diff.code, set()).add(diff.subject)
    return out


def test_conversion_preview_lists_blockers_and_skips_without_loading_sdk(bundle):
    preview = preview_cubism_model(bundle)
    codes = _codes(preview)
    assert preview.mode == "convert"
    assert preview.sdk_library is None
    assert {d.code for d in preview.blocking} == {"moc_missing", "sdk_unavailable"}
    assert codes["texture_missing"] == {"tex/b.png"}
    assert codes["motion_missing"] == {"Tap/gone"}
    assert codes["sound_missing"] == {"Idle/idle"}
    assert codes["expression_missing"] == {"smile"}
    assert codes["motion_curves_skipped"] == {"Idle/idle"}
    detail = next(d.detail for d in preview.differences if d.code == "motion_curves_skipped")
    assert "1 Model" in detail and "1 PartOpacity" in detail
    assert {"pose_not_converted", "user_data_ignored", "keyforms_sampled",
            "unlisted_motions_added"} <= set(codes)
    assert preview.motion_names == ("Idle/idle",)
    assert preview.hit_area_ids == ("Head",)
    refs = {(ref.kind, ref.path): ref.exists for ref in preview.references}
    assert refs[("texture", "tex/a.png")] is True
    assert refs[("moc", "rig.moc3")] is False
    json.dumps(preview.to_dict())


def test_conversion_preview_finds_explicit_library(bundle, tmp_path):
    library = tmp_path / "core.dll"
    library.write_bytes(b"not loaded")
    (bundle.parent / "rig.moc3").write_bytes(b"MOC3")
    preview = preview_cubism_model(bundle, sdk_library=library)
    assert preview.sdk_library == str(library)
    assert preview.blocking == ()


def test_merge_preview_reports_failures_duplicates_and_inert_data(bundle):
    document = PuppetDocument(
        motions=[Motion(name="Idle/idle", duration=1.0)],
        parameters=[Parameter("ParamAngleY", -30, 30, 0)],
    )
    preview = preview_cubism_model(bundle, document=document)
    codes = _codes(preview)
    assert preview.mode == "merge"
    assert {d.subject for d in preview.blocking} == {"Tap/gone", "smile"}
    assert codes["duplicate_motion_skipped"] == {"Idle/idle"}
    assert codes["motion_parameter_missing"] == {"ParamAngleX"}
    assert codes["hit_area_unbound"] == {"Head"}
    assert "mesh_not_imported" in codes
    assert "sdk_unavailable" not in codes


def test_unreadable_manifest_is_a_format_error(tmp_path):
    with pytest.raises(CubismFormatError):
        preview_cubism_model(tmp_path / "missing.model3.json")
    bad = tmp_path / "bad.model3.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(CubismFormatError):
        preview_cubism_model(bad)
