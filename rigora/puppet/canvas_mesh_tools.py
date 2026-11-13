"""Vertex selection, box select, vertex locks and the weight overlay (R2.3).

Selection, locks and the weight view are editor state on the canvas; the
document only changes through the mesh tools the workspace runs inside a
transaction. The overlay draws rest-pose vertices because editing works on
rest positions.
"""
from __future__ import annotations

from rigora.puppet.mesh_tools import vertices_in_rect, weight_colors

_POINT_SIZE = 5.0


class PuppetCanvasMeshToolsMixin:
    """Selection and overlay state for the mesh editor."""

    def _init_mesh_tool_state(self) -> None:
        self._vertex_selection: tuple[str, set[int]] | None = None
        self._locked_vertices: dict[str, set[int]] = {}
        self._weight_view_bone: str | None = None
        self._box_select: list[float] | None = None
        self._box_additive = False

    # ---- selection ---------------------------------------------------------

    def vertex_selection(self) -> tuple[str, set[int]] | None:
        selection = getattr(self, "_vertex_selection", None)
        if selection is None:
            return None
        return selection[0], set(selection[1])

    def set_vertex_selection(self, drawable_id: str | None, indices=()) -> None:
        doc = self._document
        drawable = doc.drawable(drawable_id) if doc is not None and drawable_id else None
        valid = {int(i) for i in indices if drawable is not None
                 and 0 <= int(i) < len(drawable.vertices)}
        self._vertex_selection = (drawable_id, valid) if valid else None
        self.update()

    def clear_vertex_selection(self) -> None:
        self.set_vertex_selection(None)

    def select_all_vertices(self, drawable_id: str | None = None) -> bool:
        target = drawable_id or (self._vertex_selection or (None,))[0]
        drawable = self._document.drawable(target) if self._document and target else None
        if drawable is None:
            return False
        self.set_vertex_selection(drawable.id, range(len(drawable.vertices)))
        return True

    def _prune_mesh_tool_state(self) -> None:
        """Drop selection entries that no longer exist after a reload."""
        if self._document is None:
            self._vertex_selection = None
            self._locked_vertices = {}
            return
        if self._vertex_selection is not None:
            self.set_vertex_selection(*self._vertex_selection)
        kept = {}
        for drawable_id, indices in self._locked_vertices.items():
            drawable = self._document.drawable(drawable_id)
            if drawable is not None:
                kept[drawable_id] = {i for i in indices if i < len(drawable.vertices)}
        self._locked_vertices = {k: v for k, v in kept.items() if v}

    # ---- locks -------------------------------------------------------------

    def locked_vertices(self, drawable_id: str) -> set[int]:
        return set(getattr(self, "_locked_vertices", {}).get(drawable_id, set()))

    def lock_selected_vertices(self, locked: bool = True) -> int:
        if self._vertex_selection is None:
            return 0
        drawable_id, indices = self._vertex_selection
        current = self._locked_vertices.setdefault(drawable_id, set())
        before = len(current)
        if locked:
            current |= indices
        else:
            current -= indices
        self.update()
        return abs(len(current) - before)

    def unlock_all_vertices(self) -> None:
        self._locked_vertices = {}
        self.update()

    # ---- weight view -------------------------------------------------------

    def set_weight_view(self, bone: str | None) -> None:
        self._weight_view_bone = bone or None
        self.update()

    def weight_view(self) -> str | None:
        return getattr(self, "_weight_view_bone", None)

    # ---- box select --------------------------------------------------------

    def begin_box_select(self, x: float, y: float, *, additive: bool = False) -> None:
        self._box_select = [x, y, x, y]
        self._box_additive = additive

    def update_box_select(self, x: float, y: float) -> bool:
        if getattr(self, "_box_select", None) is None:
            return False
        self._box_select[2:] = [x, y]
        self.update()
        return True

    def finish_box_select(self) -> tuple[str, set[int]] | None:
        """Select the vertices inside the box on the topmost drawable that has
        any. An additive box on the same drawable extends the selection."""
        rect, self._box_select = getattr(self, "_box_select", None), None
        if rect is None or self._document is None:
            return None
        current = self._vertex_selection
        candidates = sorted(self._document.drawables, key=lambda d: -d.draw_order)
        if self._box_additive and current is not None:
            candidates = [d for d in candidates if d.id == current[0]]
        for drawable in candidates:
            hits = vertices_in_rect(drawable, tuple(rect))
            if hits:
                if self._box_additive and current is not None:
                    hits |= current[1]
                self.set_vertex_selection(drawable.id, hits)
                return drawable.id, hits
        if not self._box_additive:
            self.clear_vertex_selection()
        self.update()
        return None

    # ---- overlay -----------------------------------------------------------

    def mesh_overlay_points(self) -> list[tuple[float, float, tuple[float, ...]]]:
        """``(x, y, rgba)`` for every vertex dot the overlay draws: weight heat
        colours when a bone is viewed, then locked (red) and selected (cyan)."""
        doc = self._document
        if doc is None or not self._mesh_edit_enabled:
            return []
        points: list[tuple[float, float, tuple[float, ...]]] = []
        bone = self.weight_view()
        if bone:
            for drawable in doc.drawables:
                if drawable.bone_weights and bone in drawable.bone_weights:
                    colours = weight_colors(drawable, bone)
                    points.extend((x, y, tuple(map(float, c)))
                                  for (x, y), c in zip(drawable.vertices, colours, strict=True))
        for drawable_id, indices in self._locked_vertices.items():
            drawable = doc.drawable(drawable_id)
            if drawable is not None:
                points.extend((*drawable.vertices[i], (1.0, 0.2, 0.2, 1.0))
                              for i in sorted(indices) if i < len(drawable.vertices))
        selection = self._vertex_selection
        if selection is not None:
            drawable = doc.drawable(selection[0])
            if drawable is not None:
                points.extend((*drawable.vertices[i], (0.2, 0.9, 1.0, 1.0))
                              for i in sorted(selection[1]) if i < len(drawable.vertices))
        return points

    def _draw_mesh_overlay(self) -> None:   # pragma: no cover - GL needs display
        from OpenGL.GL import (
            GL_LINE_LOOP, GL_POINTS, GL_TEXTURE_2D, glBegin, glColor4f, glDisable,
            glEnable, glEnd, glPointSize, glVertex2f,
        )
        points = self.mesh_overlay_points()
        box = getattr(self, "_box_select", None)
        if not points and box is None:
            return
        glDisable(GL_TEXTURE_2D)
        glPointSize(_POINT_SIZE)
        glBegin(GL_POINTS)
        for x, y, (r, g, b, a) in points:
            glColor4f(r, g, b, a)
            glVertex2f(float(x), float(y))
        glEnd()
        if box is not None:
            x0, y0, x1, y1 = box
            glColor4f(0.2, 0.9, 1.0, 0.9)
            glBegin(GL_LINE_LOOP)
            for vx, vy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                glVertex2f(vx, vy)
            glEnd()
        glEnable(GL_TEXTURE_2D)
        glColor4f(1.0, 1.0, 1.0, 1.0)
