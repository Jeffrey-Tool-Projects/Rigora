"""Deformer selection and vertex editing gestures."""
from __future__ import annotations

from rigora.puppet.canvas_rig import refresh_rig

from rigora.puppet.mesh_edit import find_drawable_at, move_vertex
from rigora.puppet.mesh_tools import translate_vertices
from rigora.puppet.render_prep import build_draw_list


class PuppetCanvasEditingMixin:
    """Deformer selection and vertex editing gestures."""

    def selected_deformer(self) -> str | None:
        return self._selected_deformer

    def set_selected_deformer(self, deformer_id: str | None) -> None:
        """Pick which deformer the editor wants highlighted on canvas.
        The selection overlay draws an anchor marker plus a bounding
        box around the targeted drawables so the user can see what
        the bone tree click referred to. An empty string is treated
        the same as ``None`` so callers that pump signal payloads
        through can clear via either spelling."""
        new_value = (
            deformer_id if isinstance(deformer_id, str) and deformer_id else None
        )
        if new_value == self._selected_deformer:
            return
        self._selected_deformer = new_value
        self.deformer_selection_changed.emit(new_value or "")
        self.update()

    def clear_selection(self) -> None:
        """Drop the selection overlay. Convenience wrapper used by the
        right-click clear path; equivalent to ``set_selected_deformer(None)``
        followed by emitting :attr:`selection_cleared`."""
        if self._selected_deformer is None:
            return
        self._selected_deformer = None
        self.deformer_selection_changed.emit("")
        self.update()
        self.selection_cleared.emit()

    def set_mesh_edit_enabled(self, enabled: bool) -> None:
        """Toggle the click-to-drag vertex editor. Switching off also
        clears any active drag target."""
        self._mesh_edit_enabled = bool(enabled)
        if not enabled:
            self.end_mesh_edit_drag()

    def mesh_edit_enabled(self) -> bool:
        return self._mesh_edit_enabled

    def begin_mesh_edit_at(
        self, image_x: float, image_y: float, *, additive: bool = False,
    ) -> bool:
        """Pick the topmost vertex within the snap radius of ``(image_x,
        image_y)`` and start a drag. Returns ``True`` if a vertex was
        grabbed.

        Grabbing a selected vertex drags the whole selection; grabbing another
        vertex selects it (``additive`` adds it instead). Pressing on empty
        canvas starts a box selection."""
        if not self._mesh_edit_enabled or self._document is None:
            return False
        hit = find_drawable_at(self._document, image_x, image_y)
        self._mesh_edit_target = hit
        if hit is None:
            self.begin_box_select(image_x, image_y, additive=additive)
            return False
        selection = self.vertex_selection()
        drawable_id, index = hit
        if selection is None or selection[0] != drawable_id:
            self.set_vertex_selection(drawable_id, {index})
        elif index not in selection[1]:
            self.set_vertex_selection(
                drawable_id, selection[1] | {index} if additive else {index})
        return True

    def update_mesh_edit_drag(self, image_x: float, image_y: float) -> bool:
        """Move the grabbed vertex to ``(image_x, image_y)`` and rebuild
        the draw list so the renderer picks up the change."""
        if not self._mesh_edit_enabled or self._mesh_edit_target is None:
            return False
        if self._document is None:
            return False
        drawable_id, vertex_idx = self._mesh_edit_target
        drawable = self._document.drawable(drawable_id)
        if drawable is None:
            return False
        locked = self.locked_vertices(drawable_id) if hasattr(self, "_locked_vertices") \
            else set()
        if vertex_idx in locked:
            return False
        selection = self.vertex_selection() if hasattr(self, "_vertex_selection") else None
        others = selection[1] - {vertex_idx} \
            if selection is not None and selection[0] == drawable_id else set()
        before = drawable.vertices[vertex_idx] if others else None
        if not move_vertex(drawable, vertex_idx, image_x, image_y):
            return False
        if before is not None:
            translate_vertices(drawable, others, float(image_x) - before[0],
                               float(image_y) - before[1], locked=locked)
        self._draw_list = build_draw_list(self._document)
        refresh_rig(self)
        return True

    def end_mesh_edit_drag(self) -> None:
        if getattr(self, "_box_select", None) is not None:
            self.finish_box_select()
        editing = self._mesh_edit_target is not None
        self._mesh_edit_target = None
        if editing:
            self.edit_finished.emit("Edit mesh")
