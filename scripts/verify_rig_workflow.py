"""R2 acceptance in the real hidden editor, invoked by verify_gui.py.

From a layered PSD: import, hand-edit the mesh, apply part templates, add an
expression and edit physics, run the rig doctor, save and reopen (pixels
must match), then render every extreme and blend-corner pose and a clip-mask
overlap case. Checks: no torn meshes, premultiplied alpha stays consistent at
transparent edges (no fringe brighter than its alpha), clipped pixels stay
inside the mask, and failed or cancelled operations leave the document as it
was. Dialogs are answered in code; no desktop input is generated.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from verify_asset_workflow import _digest, _fixtures, _pixels

SIZE = (160, 160)


def _art(box, rgb, alpha=255):
    image = np.zeros((SIZE[1], SIZE[0], 4), dtype=np.uint8)
    x0, y0, x1, y1 = box
    image[y0:y1, x0:x1] = (*rgb, alpha)
    # A soft one-pixel edge exercises the transparent-edge check.
    image[y0:y1, x0] = (*rgb, alpha // 3)
    return image


def _write_rig_psd(fx, path: Path) -> None:
    layers = {
        "body": ((40, 90, 120, 158), (200, 170, 150)),
        "face_base": ((50, 20, 110, 90), (240, 210, 190)),
        "hair_main": ((45, 10, 115, 40), (90, 60, 40)),
        "eye_open_l": ((62, 45, 74, 55), (40, 40, 90)),
        "eye_closed_l": ((62, 49, 74, 52), (40, 30, 30)),
        "eye_open_r": ((86, 45, 98, 55), (40, 40, 90)),
        "eye_closed_r": ((86, 49, 98, 52), (40, 30, 30)),
        "mouth_closed": ((72, 70, 88, 73), (150, 60, 60)),
        "mouth_open": ((72, 66, 88, 78), (120, 30, 40)),
        "ribbon": ((112, 15, 130, 60), (220, 60, 120)),
    }
    fx.save_psd_stack(path, SIZE, [fx.FixtureLayer(name, _art(box, rgb))
                                   for name, (box, rgb) in layers.items()])


def _fringe(pixels: np.ndarray) -> int:
    """Premultiplied pixels whose colour exceeds their alpha: a fringe left by
    straight-alpha texels or a broken blend at a transparent edge."""
    rgb = pixels[..., :3].astype(int)
    alpha = pixels[..., 3:4].astype(int)
    return int(np.count_nonzero((rgb > alpha + 2).any(axis=2)))


def check_rig_workflow(window, root: Path) -> dict:
    from PySide6.QtWidgets import QMessageBox
    from rigora.puppet import workspace_import
    from rigora.puppet.document import Expression, ExpressionParam
    from rigora.puppet.document_io import load_puppet, to_zip_bytes
    from rigora.puppet.rig_doctor import diagnose
    from rigora.puppet.rig_quality import check_poses, pose_samples

    def require(value, message):
        if not value:
            raise RuntimeError(message)

    fx = _fixtures()
    editor = window.editor
    canvas = editor.canvas()
    session = editor.session
    psd = root / "rig-v1.psd"
    _write_rig_psd(fx, psd)
    report: dict = {}

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard), \
            patch.object(workspace_import.QFileDialog, "getOpenFileName",
                         return_value=(str(psd), "")), \
            patch.object(type(editor), "_exec_preview_dialog", lambda self, dialog: True):
        editor._import_psd_via_dialog()
    require(len(canvas.document().drawables) == 10, "Layered import failed")

    # Hand edit: move one body vertex through the canvas gesture, then undo / redo.
    canvas.set_mesh_edit_enabled(True)
    body = canvas.document().drawable("body")
    x, y = body.vertices[0]
    require(canvas.begin_mesh_edit_at(x, y), "Could not grab a body vertex")
    canvas.update_mesh_edit_drag(x - 3, y - 2)
    canvas.end_mesh_edit_drag()
    require(session.can_undo and session.document.drawable("body").vertices[0] == (x - 3, y - 2),
            "Mesh gesture was not recorded")
    canvas.set_mesh_edit_enabled(False)

    templates = {
        "eye_blink": {"left_open": ["eye_open_l"], "left_closed": ["eye_closed_l"],
                      "right_open": ["eye_open_r"], "right_closed": ["eye_closed_r"]},
        "mouth_shapes": {"closed": ["mouth_closed"], "open": ["mouth_open"]},
        "head_turn": {"head": ["face_base", "hair_main"],
                      "features": ["eye_open_l", "eye_closed_l", "eye_open_r",
                                   "eye_closed_r", "mouth_closed", "mouth_open"]},
        "sway": {"parts": ["ribbon"]},
    }
    for template_id, mapping in templates.items():
        require(editor.apply_part_template(template_id, mapping) is not None,
                f"Template {template_id} failed")
    with session.transaction("Add expression"):
        session.document.expressions.append(
            Expression("smile", [ExpressionParam("ParamMouthOpenY", 0.6, "overwrite")]))
    canvas.load_document(session.document)
    rigs = [type(r)(r.id, r.input_param, r.output_param, r.chain, (0.0, -6.0))
            for r in session.document.physics_rigs]
    require(editor.apply_physics_rigs(rigs), "Physics edit failed")
    fixes = [f.id for f in diagnose(session.document) if f.kind in ("mesh", "weights")]
    if fixes:
        require(editor.apply_rig_fixes(fixes) is not None, "Rig doctor fixes failed")
    tilts = [d.id for d in session.document.deformers if d.id.startswith("head_tilt")]
    require(tilts == ["head_tilt"], f"Head tilt stacked twice: {tilts}")
    report["authoring"] = {"templates": list(templates), "doctor_fixes": fixes,
                           "deformers": [d.id for d in session.document.deformers],
                           "physics": [r.id for r in session.document.physics_rigs]}

    saved = root / "rig-v1.puppet"
    canvas.reset_parameters()
    require(editor.save_puppet(saved), "Rig save failed")
    before = _pixels(canvas, 256)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
        require(editor.open_puppet(saved), "Rig reopen failed")
    after = _pixels(canvas, 256)
    require(_digest(before) == _digest(after), "Save/reopen changed the neutral frame")
    require(to_zip_bytes(load_puppet(saved)) == to_zip_bytes(canvas.document()),
            "Reopened document differs from the saved file")

    poses = pose_samples(canvas.document())
    quality = check_poses(canvas.document(), poses)
    require(quality.clean, f"Torn or collapsed meshes: {quality.to_dict()}")
    fringe_total, frames = 0, set()
    for _label, values in poses:
        canvas.set_parameter_values(values)
        pixels = _pixels(canvas, 256, premultiplied=True)
        fringe_total += _fringe(pixels)
        frames.add(_digest(pixels))
    canvas.reset_parameters()
    require(fringe_total == 0, f"{fringe_total} pixels brighter than their alpha")
    require(len(frames) > 3, "Extreme poses did not change the picture")
    report["poses"] = {"count": len(poses), "distinct_frames": len(frames),
                       "fringe_pixels": fringe_total, "tears": quality.tears,
                       "folds_tolerated": quality.flipped_area}

    report["mask_overlap"] = _check_mask_overlap(editor, canvas, root, require)

    # Failures and cancellations leave the document as it was.
    snapshot = to_zip_bytes(canvas.document())
    broken = root / "broken.psd"
    broken.write_bytes(b"8BPS not really")
    require(not editor.import_psd(broken), "Corrupt PSD was accepted")
    with patch.object(type(editor), "_run_rig_dialog", lambda self, dialog: False):
        editor.run_rig_doctor_via_dialog()
        editor.part_templates_via_dialog()
        editor.edit_physics_via_dialog()
    require(to_zip_bytes(canvas.document()) == snapshot,
            "A failed import or cancelled dialog changed the document")
    report["failure_safety"] = True
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
        editor.open_puppet(saved)
    return report


def _check_mask_overlap(editor, canvas, root: Path, require) -> dict:
    """A large opaque drawable clipped by a small mask must only show inside
    the mask, also when both rotate to the parameter's extremes."""
    import io

    from PIL import Image
    from PySide6.QtWidgets import QMessageBox
    from rigora.puppet.deformers import default_rotation_form
    from rigora.puppet.document import (
        Deformer, Drawable, Parameter, ParameterKey, PuppetDocument,
    )
    from rigora.puppet.document_io import save_puppet

    def texture(rgba):
        buf = io.BytesIO()
        Image.fromarray(np.full((8, 8, 4), rgba, dtype=np.uint8)).save(buf, format="PNG")
        return buf.getvalue()

    def quad(drawable_id, box, tex, order, mask=None):
        x0, y0, x1, y1 = box
        return Drawable(drawable_id, tex, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                        [0, 1, 2, 0, 2, 3], [(0, 0), (1, 0), (1, 1), (0, 1)],
                        draw_order=order, clip_mask=mask)

    doc = PuppetDocument(
        size=(100, 100),
        drawables=[quad("mask", (40, 40, 60, 60), "textures/clear.png", 0),
                   quad("fill", (0, 0, 100, 100), "textures/red.png", 1, mask="mask")],
        deformers=[Deformer("spin", "rotation", None, ["mask", "fill"],
                            default_rotation_form((50, 50)))],
        parameters=[Parameter("ParamSpin", -1, 1, 0, [
            ParameterKey(-1, {"spin": {"angle": -0.6}}),
            ParameterKey(1, {"spin": {"angle": 0.6}})])],
        textures={"textures/clear.png": texture((0, 0, 0, 0)),
                  "textures/red.png": texture((255, 0, 0, 255))},
    )
    path = root / "mask-overlap.puppet"
    save_puppet(doc, path)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
        require(editor.open_puppet(path), "Mask document did not open")
    results = {}
    for value in (-1.0, 0.0, 1.0):
        canvas.set_parameter_values({"ParamSpin": value})
        pixels = _pixels(canvas, 200)
        opaque = pixels[..., 3] > 0
        ys, xs = np.nonzero(opaque)
        require(len(xs) > 0, "Clipped drawable vanished")
        # The 20-unit mask square renders 40 px wide; rotated, its corners stay within
        # its half-diagonal (≈28 px) of the centre. Unclipped fill would reach ≈141 px.
        radius = np.hypot(xs - 100, ys - 100).max()
        require(radius <= 31, f"Clipped pixels escaped the mask at {value}: radius {radius:.0f}")
        results[str(value)] = {"opaque_pixels": int(opaque.sum()),
                               "max_radius_px": round(float(radius), 1)}
    canvas.reset_parameters()
    return results
