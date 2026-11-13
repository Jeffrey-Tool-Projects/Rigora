"""Mesh menu: selection, locks, weight tools and safe vertex deletion (R2.3).

Every document change runs in one session transaction, so each command is
one Undo step. Commands act on the canvas's vertex selection; locked
vertices are never moved or re-weighted. Deleting vertices shows the
topology impact (triangles, weights and morph entries) and asks first.
"""
from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.mesh_tools import (
    delete_vertices,
    mirror_vertices,
    mirror_weights,
    normalize_weights,
    smooth_weights,
    topology_impact,
)


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


class PuppetMeshToolsMixin:
    """Mesh and weight commands of :class:`~rigora.puppet.workspace.PuppetWorkspace`."""

    def _mesh_target(self, *, need_selection: bool = True):
        """``(drawable, selection, locked)`` or ``None`` after announcing why."""
        selection = self._canvas.vertex_selection()
        document = self._canvas.document()
        if document is None or (need_selection and selection is None):
            self._announce("puppet_mesh_no_selection",
                           "Turn on Edit mesh and select vertices first.")
            return None
        drawable = document.drawable(selection[0]) if selection else None
        if drawable is None:
            self._announce("puppet_mesh_no_selection",
                           "Turn on Edit mesh and select vertices first.")
            return None
        return drawable, selection[1], self._canvas.locked_vertices(drawable.id)

    def _run_mesh_edit(self, label: str, edit) -> object:
        self._begin_document_work()
        try:
            with self.session.transaction(label):
                result = edit()
        except ValueError as exc:
            self._canvas.load_document(self.session.document)
            self._announce("puppet_mesh_failed", "{label} failed: {error}",
                           label=label, error=str(exc))
            return None
        selection = self._canvas.vertex_selection()
        self._canvas.load_document(self.session.document)
        if selection is not None:
            self._canvas.set_vertex_selection(*selection)
        self._update_session_actions()
        return result

    def _mesh_select_all(self) -> None:
        if not self._canvas.select_all_vertices():
            self._announce("puppet_mesh_no_selection",
                           "Turn on Edit mesh and select vertices first.")

    def _mesh_lock_selection(self) -> None:
        if self._mesh_target() is not None:
            count = self._canvas.lock_selected_vertices(True)
            self._announce("puppet_mesh_locked", "Locked {n} vertices.", n=count)

    def _mesh_unlock_all(self) -> None:
        self._canvas.unlock_all_vertices()
        self._announce("puppet_mesh_unlocked", "All vertices unlocked.")

    def mesh_normalize_weights(self) -> list[int] | None:
        target = self._mesh_target()
        if target is None:
            return None
        drawable, selection, locked = target
        changed = self._run_mesh_edit("Normalize weights", lambda: normalize_weights(
            drawable, selection=selection, locked=locked))
        if changed is not None:
            self._announce("puppet_mesh_weights_done", "{n} vertices updated.", n=len(changed))
        return changed

    def mesh_smooth_weights(self, strength: float = 0.5, iterations: int = 2) -> list[int] | None:
        target = self._mesh_target()
        if target is None:
            return None
        drawable, selection, locked = target
        changed = self._run_mesh_edit("Smooth weights", lambda: smooth_weights(
            drawable, selection, iterations=iterations, strength=strength, locked=locked))
        if changed is not None:
            self._announce("puppet_mesh_weights_done", "{n} vertices updated.", n=len(changed))
        return changed

    def _mirror_axis(self) -> float:
        document = self._canvas.document()
        return document.size[0] / 2.0

    def mesh_mirror_weights(self, source_side: str = "left") -> list[int] | None:
        target = self._mesh_target(need_selection=False)
        if target is None:
            return None
        drawable, _selection, locked = target
        changed = self._run_mesh_edit("Mirror weights", lambda: mirror_weights(
            drawable, self._mirror_axis(), source_side=source_side, locked=locked))
        if changed is not None:
            self._announce("puppet_mesh_weights_done", "{n} vertices updated.", n=len(changed))
        return changed

    def mesh_mirror_vertices(self) -> list[int] | None:
        target = self._mesh_target()
        if target is None:
            return None
        drawable, selection, locked = target
        return self._run_mesh_edit("Mirror vertices", lambda: mirror_vertices(
            drawable, selection, self._mirror_axis(), locked=locked))

    def mesh_delete_vertices(self, *, confirm: bool = True) -> bool:
        target = self._mesh_target()
        if target is None:
            return False
        drawable, selection, locked = target
        remove = selection - locked
        impact = topology_impact(drawable, remove)
        if impact.blocked:
            self._announce("puppet_mesh_failed", "{label} failed: {error}",
                           label="Delete vertices", error="; ".join(impact.blocked))
            return False
        if confirm and not self._confirm_topology(impact):
            return False
        if self._run_mesh_edit("Delete vertices",
                               lambda: delete_vertices(drawable, remove)) is None:
            return False
        self._canvas.clear_vertex_selection()
        self._announce("puppet_mesh_deleted",
                       "Deleted {v} vertices and {t} triangles; weights and morphs re-aligned.",
                       v=len(impact.removed_vertices), t=impact.removed_triangles)
        return True

    def _confirm_topology(self, impact) -> bool:
        lines = [_tr("puppet_mesh_delete_summary",
                     "Delete {v} vertices and {t} triangles from {d}? {left} triangles remain.",
                     v=len(impact.removed_vertices), t=impact.removed_triangles,
                     d=impact.drawable, left=impact.remaining_triangles)]
        if impact.weight_bones:
            lines.append(_tr("puppet_mesh_delete_weights", "Bone weights updated: {bones}",
                             bones=", ".join(impact.weight_bones)))
        if impact.morph_parameters:
            lines.append(_tr("puppet_mesh_delete_morphs", "Vertex morphs updated: {params}",
                             params=", ".join(impact.morph_parameters)))
        if impact.mismatched:
            lines.append(_tr("puppet_mesh_delete_mismatch",
                             "Already out of step: {items}", items="; ".join(impact.mismatched)))
        answer = QMessageBox.question(
            self, _tr("puppet_mesh_delete_title", "Delete vertices"), "\n".join(lines),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Ok

    def _mesh_show_weights(self) -> None:
        document = self._canvas.document()
        bones = sorted({bone for d in (document.drawables if document else [])
                        for bone in (d.bone_weights or {})})
        if not bones:
            self._canvas.set_weight_view(None)
            self._announce("puppet_mesh_no_weights", "No drawable has bone weights.")
            return
        none_label = _tr("puppet_mesh_weights_off", "(hide weights)")
        choice, ok = QInputDialog.getItem(
            self, _tr("puppet_mesh_show_weights", "Show weights…"),
            _tr("puppet_mesh_pick_bone", "Bone:"), [none_label, *bones], 0, False)
        if ok:
            self._canvas.set_weight_view(None if choice == none_label else choice)
