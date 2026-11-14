"""R2.1: preview dialogs and the confirm-before-import workflow (offscreen-safe)."""
from __future__ import annotations

import json

import numpy as np
import pytest
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QTableWidget, QWidget

from rigora.puppet import workspace_import as workspace_import_module
from rigora.puppet.cubism_preview import preview_cubism_model
from rigora.puppet.document import PuppetDocument
from rigora.puppet.document_session import DocumentSession
from rigora.puppet.import_preview_dialog import (
    build_cubism_preview_dialog,
    build_psd_preview_dialog,
)
from rigora.puppet.psd_import import preview_psd
from rigora.puppet.workspace_import import PuppetImportMixin
from tests.psd_fixtures import FixtureLayer, save_psd_stack


def _psd(path, *, masked: bool = True) -> None:
    image = np.zeros((8, 10, 4), dtype=np.uint8)
    image[1:5, 2:7] = (10, 20, 30, 255)
    save_psd_stack(path, (10, 8), [
        FixtureLayer("body", image.copy()),
        FixtureLayer("shade", image.copy(), mask=masked, blend_key=b"scrn"),
    ])


def _cells(table: QTableWidget) -> list[list[str]]:
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def _ok(dialog) -> object:
    return dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)


def test_psd_dialog_lists_layers_top_first_and_differences(qapp, tmp_path):
    path = tmp_path / "a.psd"
    _psd(path)
    parent = QWidget()
    dialog = build_psd_preview_dialog(parent, preview_psd(path))
    layers = _cells(dialog.findChild(QTableWidget, "import_layers"))
    assert [row[1] for row in layers] == ["shade", "body"]
    assert layers[0][5:7] == ["5×4", "2, 1"]
    assert layers[0][8] == "screen → normal"
    assert layers[0][9] == "mask"
    issues = _cells(dialog.findChild(QTableWidget, "import_differences"))
    assert {row[1] for row in issues} == {"shade"}
    assert any("mask" in row[3] for row in issues)
    assert _ok(dialog).isEnabled()
    assert "2 of 2 layers" in dialog.findChild(QLabel, "import_summary").text()
    parent.deleteLater()


def test_cubism_dialog_blocks_a_conversion_that_cannot_run(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("CUBISM_CORE_DLL", raising=False)
    monkeypatch.chdir(tmp_path)
    model = tmp_path / "rig.model3.json"
    model.write_text(json.dumps({"FileReferences": {"Moc": "rig.moc3"}}), encoding="utf-8")
    parent = QWidget()
    dialog = build_cubism_preview_dialog(parent, preview_cubism_model(model))
    assert not _ok(dialog).isEnabled()
    rows = _cells(dialog.findChild(QTableWidget, "import_differences"))
    # Blocking rows sort first: the missing .moc3 and the missing Cubism Core.
    assert {row[1] for row in rows[:2]} == {"rig.moc3", "Cubism Core"}
    assert "Resolve" in _ok(dialog).toolTip()
    parent.deleteLater()


class _Host(PuppetImportMixin, QWidget):
    """Just enough workspace for the import mixin."""

    def __init__(self, *, confirm: bool) -> None:
        super().__init__()
        self.session = DocumentSession()
        self._status_label = QLabel(self)
        self.confirm = confirm
        self.dialogs = []
        self.replaced: list[PuppetDocument] = []

        class _Canvas:
            def document(inner):  # noqa: N805
                return self.session.document

        self._canvas = _Canvas()

    def _begin_document_work(self):
        return self.session.revision

    def _accept_document_result(self, revision) -> bool:
        return self.session.accepts(revision)

    def _replace_document(self, document, **_kwargs) -> bool:
        self.session.bind(document)
        self.replaced.append(document)
        return True

    def _announce(self, key, fallback, **fmt) -> None:
        self._status_label.setText(fallback.format(**fmt))

    def _exec_preview_dialog(self, dialog) -> bool:
        self.dialogs.append(dialog)
        return self.confirm


@pytest.mark.parametrize("confirm", [True, False])
def test_psd_import_runs_only_after_preview_is_confirmed(qapp, tmp_path, monkeypatch, confirm):
    path = tmp_path / "a.psd"
    _psd(path)
    monkeypatch.setattr(workspace_import_module.QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(path), ""))
    host = _Host(confirm=confirm)
    host._import_psd_via_dialog()   # noqa: SLF001
    assert len(host.dialogs) == 1
    if confirm:
        assert [d.id for d in host.replaced[0].drawables] == ["body", "shade"]
        assert host.last_import_preview.source == str(path)
        assert "source features changed" in host._status_label.text()   # noqa: SLF001
    else:
        assert host.replaced == []
        assert "cancelled" in host._status_label.text()   # noqa: SLF001
    host.deleteLater()


def test_unreadable_psd_reports_without_dialog(qapp, tmp_path):
    bad = tmp_path / "bad.psd"
    bad.write_bytes(b"nope")
    host = _Host(confirm=True)
    assert host.import_psd(bad) is False
    assert host.dialogs == []
    assert "PSD import failed" in host._status_label.text()   # noqa: SLF001
    host.deleteLater()


def test_cubism_preview_cancel_leaves_document_untouched(qapp, tmp_path, monkeypatch):
    model = tmp_path / "rig.model3.json"
    model.write_text(json.dumps({"FileReferences": {}}), encoding="utf-8")
    host = _Host(confirm=False)
    host.session.bind(PuppetDocument())
    called = []
    monkeypatch.setattr(_Host, "import_cubism", lambda self, p: called.append(p), raising=False)
    assert host._confirm_cubism_preview(str(model)) is False   # noqa: SLF001
    assert len(host.dialogs) == 1
    assert host._confirm_cubism_preview(str(tmp_path / "x.motion3.json")) is True   # noqa: SLF001
    assert len(host.dialogs) == 1
    host.deleteLater()
