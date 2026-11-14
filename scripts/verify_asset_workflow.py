"""R2.1 / R2.2 acceptance in the real hidden editor, invoked by verify_gui.py.

Imports a layered PSD through the preview dialog, updates its art from a
re-exported PSD and relinks a missing texture, checking the native GL
framebuffer after each step and that Undo restores the exact pixels.
Dialogs are answered in code; no desktop input is generated.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SIZE = (96, 80)


def _fixtures():
    spec = importlib.util.spec_from_file_location("rigora_psd_fixtures",
                                                  ROOT / "tests" / "psd_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _art(box, rgb) -> np.ndarray:
    image = np.zeros((SIZE[1], SIZE[0], 4), dtype=np.uint8)
    x0, y0, x1, y1 = box
    image[y0:y1, x0:x1] = (*rgb, 255)
    return image


def _write_psd(fx, path: Path, arm_rgb, *, with_eye: bool) -> None:
    stack = [
        fx.FixtureLayer("body", _art((10, 10, 60, 75), (220, 170, 140))),
        fx.GroupEnd(),
        fx.FixtureLayer("arm", _art((60, 20, 90, 40), arm_rgb), mask=True),
    ]
    if with_eye:
        stack.append(fx.FixtureLayer("eye", _art((25, 20, 35, 28), (20, 20, 20))))
    stack += [fx.GroupHeader("limbs"),
              fx.FixtureLayer("hat", _art((15, 0, 55, 12), (40, 60, 200)))]
    fx.save_psd_stack(path, SIZE, stack)


def _pixels(canvas, size: int = 192, *, premultiplied: bool = False) -> np.ndarray:
    from PySide6.QtGui import QImage
    image = canvas.render_offscreen_puppet(size, size)
    if image is None or image.isNull():
        raise RuntimeError("Empty GL frame")
    target = (QImage.Format.Format_RGBA8888_Premultiplied if premultiplied
              else QImage.Format.Format_RGBA8888)
    rgba = image.convertToFormat(target)
    data = np.frombuffer(rgba.constBits(), dtype=np.uint8)
    return data.reshape(size, rgba.bytesPerLine())[:, :size * 4].reshape(size, size, 4).copy()


def _digest(pixels: np.ndarray) -> str:
    return hashlib.sha256(pixels.tobytes()).hexdigest()


def check_asset_workflow(window, root: Path) -> dict:
    from PySide6.QtWidgets import QFileDialog, QMessageBox, QTableWidget
    from rigora.puppet import workspace_assets, workspace_import
    from rigora.puppet.asset_update import find_missing_textures
    from rigora.puppet.document_io import save_puppet

    def require(value, message):
        if not value:
            raise RuntimeError(message)

    fx = _fixtures()
    editor = window.editor
    canvas = editor.canvas()
    session = editor.session
    v1, v2 = root / "art-v1.psd", root / "art-v2.psd"
    _write_psd(fx, v1, (180, 120, 90), with_eye=False)
    _write_psd(fx, v2, (30, 160, 60), with_eye=True)
    report: dict = {}

    seen: list = []

    def accept_preview(dialog):
        table = dialog.findChild(QTableWidget, "import_layers")
        seen.append([table.item(r, 1).text() for r in range(table.rowCount())])
        dialog.deleteLater()
        return True

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard), \
            patch.object(workspace_import.QFileDialog, "getOpenFileName",
                         return_value=(str(v1), "")), \
            patch.object(type(editor), "_exec_preview_dialog",
                         lambda self, dialog: accept_preview(dialog)):
        editor._import_psd_via_dialog()
    require(seen == [["hat", "arm", "body"]], f"Preview did not list the layers: {seen}")
    document = canvas.document()
    require([d.id for d in document.drawables] == ["body", "arm", "hat"], "PSD import failed")
    codes = {d.code for d in editor.last_import_preview.differences}
    require("layer_mask_ignored" in codes, "Mask loss was not reported")
    imported = _pixels(canvas)
    require(np.count_nonzero(imported[..., 3]) > 1000, "Imported rig did not render")
    report["psd_preview_import"] = {"layers_listed": seen[0], "differences": sorted(codes),
                                    "frame_sha256": _digest(imported)}

    with session.transaction("Rig the arm"):
        arm = session.document.drawable("arm")
        arm.bone_weights = {"shoulder": [1.0] * len(arm.vertices)}
    canvas.load_document(session.document)
    rigged_path = root / "art-rigged.puppet"
    require(editor.save_puppet(rigged_path), "Rigged save failed")
    before = _pixels(canvas)

    def accept_update(dialog):
        dialog.set_action("+eye", "add")
        dialog.deleteLater()
        return True

    with patch.object(workspace_assets.QFileDialog, "getOpenFileName",
                      return_value=(str(v2), "")), \
            patch.object(type(editor), "_run_asset_dialog",
                         lambda self, dialog: accept_update(dialog)):
        editor._update_art_via_dialog()
    updated = canvas.document()
    require(updated.drawable("arm").bone_weights == {"shoulder": [1.0] * 4},
            "Art update lost bone weights")
    require(updated.drawable("eye") is not None, "New layer was not added")
    after = _pixels(canvas)
    require(_digest(after) != _digest(before), "Art update did not change the frame")
    require(session.dirty and session.can_undo, "Art update was not one undoable edit")
    editor.undo()
    require(_digest(_pixels(canvas)) == _digest(before), "Undo did not restore the pixels")
    editor.redo()
    require(_digest(_pixels(canvas)) == _digest(after), "Redo did not restore the update")
    report["art_update"] = {"frame_before": _digest(before), "frame_after": _digest(after),
                            "undo_exact": True, "weights_kept": True}

    broken = session.document
    missing_path = root / "art-missing.puppet"
    texture = broken.drawable("hat").texture
    kept = broken.textures.pop(texture)
    save_puppet(broken, missing_path)
    broken.textures[texture] = kept
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
        require(editor.open_puppet(missing_path), "Document with a missing texture did not open")
    require("missing" in editor._status_label.text(), "Missing texture was not announced")
    folder = root / "relink"
    folder.mkdir(exist_ok=True)
    (folder / Path(texture).name).write_bytes(kept)
    with patch.object(type(editor), "_run_asset_dialog",
                      lambda self, dialog: (dialog.search(folder), dialog.deleteLater(), True)[2]):
        editor._relink_textures_via_dialog()
    require(find_missing_textures(canvas.document()) == [], "Relink left a texture missing")
    relinked = _pixels(canvas)
    require(_digest(relinked) == _digest(after), "Relinked texture renders differently")
    report["relink"] = {"texture": texture, "frame_matches_original": True}
    with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")), \
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
        editor.open_puppet(rigged_path)
    return report
