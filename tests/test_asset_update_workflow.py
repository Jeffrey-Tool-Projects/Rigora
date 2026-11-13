"""R2.2: art-update and relink dialogs drive one undoable workspace edit."""
from __future__ import annotations

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QComboBox, QLabel, QTableWidget, QWidget

from rigora.puppet import workspace_assets as assets_module
from rigora.puppet.asset_update import decode_texture, find_missing_textures
from rigora.puppet.asset_update_dialog import AssetUpdateDialog, RelinkTexturesDialog
from rigora.puppet.document_io import to_zip_bytes
from rigora.puppet.document_session import DocumentSession
from rigora.puppet.psd_import import plan_psd_import
from rigora.puppet.workspace_assets import PuppetAssetsMixin
from tests.psd_fixtures import FixtureLayer, save_psd_stack

SIZE = (12, 10)


def _psd(path, rgb, *, extra: bool = False) -> None:
    def art(box):
        image = np.zeros((SIZE[1], SIZE[0], 4), dtype=np.uint8)
        x0, y0, x1, y1 = box
        image[y0:y1, x0:x1] = (*rgb, 255)
        return image
    stack = [FixtureLayer("body", art((1, 1, 8, 9))), FixtureLayer("arm", art((8, 2, 11, 6)))]
    if extra:
        stack.append(FixtureLayer("eye", art((3, 3, 5, 5))))
    save_psd_stack(path, SIZE, stack)


class _Host(PuppetAssetsMixin, QWidget):
    def __init__(self, document, *, confirm: bool, configure=None) -> None:
        super().__init__()
        self.session = DocumentSession()
        self.session.bind(document, path="rig.puppet", saved=True)
        self._status_label = QLabel(self)
        self.confirm = confirm
        self.configure = configure
        self.loaded = 0
        host = self

        class _Canvas:
            def document(self):
                return host.session.document

            def load_document(self, _doc):
                host.loaded += 1

        self._canvas = _Canvas()

    def _begin_document_work(self):
        return self.session.revision

    def _accept_document_result(self, revision) -> bool:
        return self.session.accepts(revision)

    def _update_session_actions(self) -> None:
        pass

    def _announce(self, key, fallback, **fmt) -> None:
        self._status_label.setText(fallback.format(**fmt))

    def _run_asset_dialog(self, dialog) -> bool:
        if self.configure:
            self.configure(dialog)
        dialog.deleteLater()
        return self.confirm


def test_dialog_shows_each_change_with_its_default(qapp, tmp_path):
    _psd(tmp_path / "v1.psd", (200, 0, 0))
    document = plan_psd_import(tmp_path / "v1.psd").build(enable_auto_rig=False)
    _psd(tmp_path / "v2.psd", (0, 200, 0), extra=True)
    from rigora.puppet.asset_update import plan_asset_update
    plan = plan_asset_update(document, plan_psd_import(tmp_path / "v2.psd"))
    parent = QWidget()
    dialog = AssetUpdateDialog(parent, plan)
    table = dialog.findChild(QTableWidget, "art_update_changes")
    assert [table.item(r, 0).text() for r in range(table.rowCount())] == ["body", "arm", "—"]
    assert table.item(0, 3).text() == "7×8 @ 1, 1"
    combo = table.cellWidget(0, 6)
    assert isinstance(combo, QComboBox) and combo.currentData() == "update"
    dialog.set_action("arm", "skip")
    assert dialog.actions() == {"body": "update", "arm": "skip", "+eye": "add"}
    assert "1 new" in dialog.findChild(QLabel, "art_update_summary").text()
    parent.deleteLater()


def test_update_via_dialog_is_one_undo_step(qapp, tmp_path, monkeypatch):
    _psd(tmp_path / "v1.psd", (200, 0, 0))
    document = plan_psd_import(tmp_path / "v1.psd").build(enable_auto_rig=False)
    _psd(tmp_path / "v2.psd", (0, 200, 0), extra=True)
    monkeypatch.setattr(assets_module.QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(tmp_path / "v2.psd"), ""))
    before = to_zip_bytes(document)
    host = _Host(document, confirm=True, configure=lambda d: d.set_action("arm", "skip"))
    host._update_art_via_dialog()   # noqa: SLF001
    doc = host.session.document
    assert tuple(decode_texture(doc.textures["textures/body.png"])[0, 0]) == (0, 200, 0, 255)
    assert tuple(decode_texture(doc.textures["textures/arm.png"])[0, 0]) == (200, 0, 0, 255)
    assert doc.drawable("eye") is not None
    assert "1 replaced" in host._status_label.text()   # noqa: SLF001
    assert host.loaded == 1
    host.session.undo()
    assert to_zip_bytes(host.session.document) == before
    host.deleteLater()


def test_cancel_and_blocked_plans_change_nothing(qapp, tmp_path, monkeypatch):
    _psd(tmp_path / "v1.psd", (200, 0, 0))
    document = plan_psd_import(tmp_path / "v1.psd").build(enable_auto_rig=False)
    before = to_zip_bytes(document)
    _psd(tmp_path / "v2.psd", (0, 200, 0))
    monkeypatch.setattr(assets_module.QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(tmp_path / "v2.psd"), ""))
    host = _Host(document, confirm=False)
    host._update_art_via_dialog()   # noqa: SLF001
    assert to_zip_bytes(host.session.document) == before
    assert not host.session.dirty
    host.session.document.size = (99, 99)
    update = host.plan_art_update(tmp_path / "v2.psd")
    assert host.apply_art_update(update) is None
    assert "resize" in host._status_label.text()   # noqa: SLF001
    host.deleteLater()


def test_stale_plan_is_rejected(qapp, tmp_path):
    _psd(tmp_path / "v1.psd", (200, 0, 0))
    document = plan_psd_import(tmp_path / "v1.psd").build(enable_auto_rig=False)
    _psd(tmp_path / "v2.psd", (0, 200, 0))
    host = _Host(document, confirm=True)
    revision = host.session.revision
    update = host.plan_art_update(tmp_path / "v2.psd")
    with host.session.transaction("Other edit"):
        host.session.document.drawable("arm").opacity = 0.5
    assert host.apply_art_update(update, revision=revision) is None
    host.deleteLater()


def test_relink_dialog_searches_and_applies_in_one_step(qapp, tmp_path):
    _psd(tmp_path / "v1.psd", (200, 0, 0))
    document = plan_psd_import(tmp_path / "v1.psd").build(enable_auto_rig=False)
    del document.textures["textures/arm.png"]
    folder = tmp_path / "art"
    folder.mkdir()
    Image.fromarray(np.full((4, 3, 4), 77, dtype=np.uint8)).save(folder / "arm.png")
    Image.fromarray(np.full((4, 3, 4), 1, dtype=np.uint8)).save(folder / "unrelated.png")

    parent = QWidget()
    dialog = RelinkTexturesDialog(parent, document, find_missing_textures(document))
    assert dialog.search(folder) == 1
    assert dialog.choices() == {"textures/arm.png": folder / "arm.png"}
    assert not dialog.choose("textures/arm.png", tmp_path / "v1.psd")
    parent.deleteLater()

    host = _Host(document, confirm=True,
                 configure=lambda d: d.search(folder))
    host._relink_textures_via_dialog()   # noqa: SLF001
    assert find_missing_textures(host.session.document) == []
    assert "Relinked 1 textures; 0 still missing" in host._status_label.text()   # noqa: SLF001
    host.session.undo()
    assert "textures/arm.png" not in host.session.document.textures
    host._relink_textures_via_dialog()   # noqa: SLF001 - still missing after undo
    host.session.redo()
    host._relink_textures_via_dialog()   # noqa: SLF001
    assert "present and readable" in host._status_label.text()   # noqa: SLF001
    host.deleteLater()


def test_missing_texture_hint_names_the_menu(qapp, tmp_path):
    _psd(tmp_path / "v1.psd", (200, 0, 0))
    document = plan_psd_import(tmp_path / "v1.psd").build(enable_auto_rig=False)
    host = _Host(document, confirm=True)
    assert host._missing_texture_hint(document) == ""   # noqa: SLF001
    del document.textures["textures/body.png"]
    assert "Relink textures" in host._missing_texture_hint(document)   # noqa: SLF001
    host.deleteLater()
