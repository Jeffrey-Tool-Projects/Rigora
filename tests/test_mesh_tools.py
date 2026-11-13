"""R2.3: selection, box select, mirror, smooth, normalise, locks, weight view, topology."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QLabel, QWidget

from rigora.puppet.canvas_editing import PuppetCanvasEditingMixin
from rigora.puppet.canvas_mesh_tools import PuppetCanvasMeshToolsMixin
from rigora.puppet.document import Drawable, PuppetDocument
from rigora.puppet.document_io import from_zip_bytes, to_zip_bytes
from rigora.puppet.document_session import DocumentSession
from rigora.puppet.mesh_tools import (
    adjacency,
    check_per_vertex_data,
    delete_vertices,
    grow_selection,
    mirror_vertices,
    mirror_weights,
    normalize_weights,
    select_in_rect,
    smooth_weights,
    topology_impact,
    translate_vertices,
    vertices_in_rect,
    weight_colors,
)
from rigora.puppet.workspace_mesh_tools import PuppetMeshToolsMixin


def grid(n: int = 3, size: float = 10.0, *, drawable_id: str = "g") -> Drawable:
    vertices, uvs, indices = [], [], []
    for r in range(n):
        for c in range(n):
            vertices.append((c * size, r * size))
            uvs.append((c / (n - 1), r / (n - 1)))
    for r in range(n - 1):
        for c in range(n - 1):
            a = r * n + c
            indices += [a, a + 1, a + n + 1, a, a + n + 1, a + n]
    return Drawable(drawable_id, "textures/g.png", vertices, indices, uvs)


def test_box_and_adjacency_selection():
    d = grid()
    assert vertices_in_rect(d, (12, 12, -1, -1)) == {0, 1, 3, 4}
    doc = PuppetDocument(drawables=[d, Drawable("top", "t", [(5.0, 5.0)], [], [(0, 0)],
                                                draw_order=5)])
    assert select_in_rect(doc, (0, 0, 6, 6)) == ("top", {0})
    assert adjacency(d)[4] == {0, 1, 3, 5, 7, 8}   # grid diagonals run down-right
    assert grow_selection(d, {0}) == {0, 1, 3, 4}


def test_translate_and_mirror_skip_locked_vertices():
    d = grid()
    assert translate_vertices(d, {0, 1}, 2.0, 3.0, locked={1}) == [0]
    assert d.vertices[0] == (2.0, 3.0) and d.vertices[1] == (10.0, 0.0)
    assert mirror_vertices(d, {2}, axis_x=10.0) == [2]
    assert d.vertices[2] == (0.0, 0.0)


def test_normalize_respects_locked_bones_and_vertices():
    d = grid(2)
    d.bone_weights = {"a": [0.2, 0.0, 3.0, 1.0], "b": [0.2, 0.0, 1.0, 1.0],
                      "pin": [0.5, 0.0, 0.0, 0.0]}
    changed = normalize_weights(d, locked={3}, locked_bones={"pin"})
    assert changed == [0, 2]
    assert d.bone_weights["pin"][0] == 0.5
    assert d.bone_weights["a"][0] == pytest.approx(0.25)
    assert d.bone_weights["a"][2] == pytest.approx(0.75)
    assert d.bone_weights["a"][3] == 1.0          # locked vertex untouched
    assert d.bone_weights["a"][1] == 0.0          # nothing to distribute


def test_smooth_blends_toward_neighbours_and_stays_normalised():
    d = grid()
    hard = [1.0 if x < 10 else 0.0 for x, _ in d.vertices]
    d.bone_weights = {"left": hard, "right": [1.0 - w for w in hard]}
    smooth_weights(d, {4}, strength=1.0)
    assert 0.0 < d.bone_weights["left"][4] < 1.0
    for i in range(len(d.vertices)):
        assert d.bone_weights["left"][i] + d.bone_weights["right"][i] == pytest.approx(1.0)
    assert d.bone_weights["left"][0] == 1.0
    with pytest.raises(ValueError):
        smooth_weights(d, {4}, strength=2.0)


def test_mirror_weights_swaps_side_bones():
    d = Drawable("m", "t", [(10.0, 0.0), (90.0, 0.0), (50.0, 0.0)], [0, 1, 2],
                 [(0, 0), (1, 0), (0.5, 0)])
    d.bone_weights = {"arm_l": [1.0, 0.0, 0.5], "body": [0.0, 0.0, 0.5]}
    changed = mirror_weights(d, axis_x=50.0, source_side="left")
    assert changed == [1]
    assert d.bone_weights["arm_r"] == [0.0, 1.0, 0.0]
    assert d.bone_weights["arm_l"][1] == 0.0
    assert d.bone_weights["body"][2] == 0.5
    with pytest.raises(ValueError):
        mirror_weights(d, 50.0, source_side="up")


def test_weight_colours_run_blue_to_red():
    d = grid(2)
    d.bone_weights = {"b": [0.0, 0.5, 1.0]}          # short list reads as zero
    colours = weight_colors(d, "b")
    np.testing.assert_allclose(colours[0, :3], [0, 0, 1])
    np.testing.assert_allclose(colours[1, :3], [0, 1, 0])
    np.testing.assert_allclose(colours[2, :3], [1, 0, 0])
    np.testing.assert_allclose(colours[3, :3], [0, 0, 1])
    assert weight_colors(d, "missing")[0, 0] == pytest.approx(0.5)


def test_topology_preview_then_delete_keeps_data_aligned():
    d = grid()
    d.bone_weights = {"b": [float(i) for i in range(9)]}
    d.vertex_morphs = [{"parameter": "P", "delta_at_min": [(i, 0) for i in range(9)],
                        "delta_at_max": [(0, i) for i in range(9)]}]
    impact = topology_impact(d, {4})
    assert impact.removed_triangles == 6 and impact.remaining_triangles == 2
    assert impact.weight_bones == ("b",) and impact.morph_parameters == ("P",)
    assert impact.blocked == () and impact.mismatched == ()
    assert len(d.vertices) == 9                       # preview changes nothing
    delete_vertices(d, {4})
    assert len(d.vertices) == len(d.uvs) == 8
    assert d.bone_weights["b"] == [0, 1, 2, 3, 5, 6, 7, 8]
    assert d.vertex_morphs[0]["delta_at_max"][4] == (0.0, 5.0)
    assert check_per_vertex_data(d) == []
    assert max(d.indices) < 8
    reopened = from_zip_bytes(to_zip_bytes(PuppetDocument(drawables=[d])))
    assert reopened.drawables[0].bone_weights == d.bone_weights


def test_topology_blocks_and_reports_mismatch():
    d = grid(2)
    assert topology_impact(d, set()).blocked == ("no vertex selected",)
    assert "no triangles left" in topology_impact(d, {0, 1}).blocked[0]
    with pytest.raises(ValueError):
        delete_vertices(d, {0, 1})
    d.bone_weights = {"b": [1.0]}
    assert topology_impact(d, {0}).mismatched == ("weights of b have 1 entries",)


class _Canvas(PuppetCanvasMeshToolsMixin, PuppetCanvasEditingMixin):
    def __init__(self, document):
        self._document = document
        self._mesh_edit_enabled = True
        self._mesh_edit_target = None
        self._draw_list = []
        self.edits = []
        self.edit_finished = SimpleNamespace(emit=self.edits.append)
        self._init_mesh_tool_state()

    def update(self):
        pass

    def document(self):
        return self._document

    def _recompute_deformed_vertices(self):
        pass


def test_canvas_gestures_select_box_and_drag_selection_with_locks():
    doc = PuppetDocument(drawables=[grid()])
    canvas = _Canvas(doc)
    assert canvas.begin_mesh_edit_at(-20, -20) is False      # empty → box
    canvas.update_box_select(11, 11)
    canvas.end_mesh_edit_drag()
    assert canvas.vertex_selection() == ("g", {0, 1, 3, 4})
    assert canvas.edits == []                                 # selection is not an edit
    canvas.set_vertex_selection("g", {1})
    canvas.lock_selected_vertices()
    canvas.set_vertex_selection("g", {0, 1, 3})
    assert canvas.begin_mesh_edit_at(0, 0) is True
    canvas.update_mesh_edit_drag(5, 5)
    canvas.end_mesh_edit_drag()
    d = doc.drawables[0]
    assert d.vertices[0] == (5.0, 5.0) and d.vertices[3] == (5.0, 15.0)
    assert d.vertices[1] == (10.0, 0.0)                       # locked
    assert canvas.edits == ["Edit mesh"]
    canvas.begin_mesh_edit_at(20, 20, additive=True)
    assert canvas.vertex_selection()[1] == {0, 1, 3, 8}
    canvas.end_mesh_edit_drag()
    canvas.set_weight_view("b")
    d.bone_weights = {"b": [1.0] * 9}
    colours = [p[2] for p in canvas.mesh_overlay_points()]
    assert colours.count((1.0, 0.2, 0.2, 1.0)) == 1 and (0.2, 0.9, 1.0, 1.0) in colours
    d.vertices = d.vertices[:2]
    canvas._prune_mesh_tool_state()   # noqa: SLF001
    assert canvas.vertex_selection() == ("g", {0, 1})


class _Workspace(PuppetMeshToolsMixin, QWidget):
    def __init__(self, document):
        super().__init__()
        self.session = DocumentSession()
        self.session.bind(document, path="m.puppet", saved=True)
        self._status_label = QLabel(self)
        self._canvas = _Canvas(document)
        self._canvas.load_document = lambda doc: self._canvas._prune_mesh_tool_state()

    def _begin_document_work(self):
        return self.session.revision

    def _update_session_actions(self):
        pass

    def _announce(self, key, fallback, **fmt):
        self._status_label.setText(fallback.format(**fmt))


def test_workspace_commands_are_single_undo_steps(qapp, monkeypatch):
    d = grid()
    d.bone_weights = {"a": [2.0] * 9, "b": [2.0] * 9}
    ws = _Workspace(PuppetDocument(drawables=[d]))
    ws.mesh_normalize_weights()
    assert "select vertices" in ws._status_label.text()   # noqa: SLF001
    ws._canvas.set_vertex_selection("g", {0, 4})   # noqa: SLF001
    assert ws.mesh_normalize_weights() == [0, 4]
    assert ws.session.document.drawables[0].bone_weights["a"][0] == 0.5
    ws.session.undo()
    assert ws.session.document.drawables[0].bone_weights["a"][0] == 2.0
    ws.session.redo()
    monkeypatch.setattr("rigora.puppet.workspace_mesh_tools.QMessageBox.question",
                        lambda *a, **k: __import__("PySide6.QtWidgets").QtWidgets
                        .QMessageBox.StandardButton.Cancel)
    assert ws.mesh_delete_vertices() is False
    assert len(ws.session.document.drawables[0].vertices) == 9
    assert ws.mesh_delete_vertices(confirm=False) is True
    assert len(ws.session.document.drawables[0].vertices) == 7
    assert "Deleted 2 vertices" in ws._status_label.text()   # noqa: SLF001
    ws.session.undo()
    assert len(ws.session.document.drawables[0].vertices) == 9
    ws.deleteLater()
