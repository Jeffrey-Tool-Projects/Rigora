"""Document binding and parameter mutation contracts."""
from __future__ import annotations

from rigora.puppet.canvas_rig import refresh_rig

from rigora.puppet.document import PuppetDocument
from rigora.puppet.render_prep import build_draw_list
from rigora.puppet.runtime import default_parameter_values


class PuppetCanvasParametersMixin:
    """Document binding and parameter mutation contracts."""

    def load_document(self, document: PuppetDocument | None) -> None:
        """Bind ``document`` to the canvas. Pass ``None`` to clear.

        Texture cache is invalidated on every document swap; the next
        ``paintGL`` re-uploads everything against the bound document's
        ``textures`` map. Parameter values reset to each parameter's
        ``default``.
        """
        self._document = document
        self._mesh_edit_target = None
        if hasattr(self, "_vertex_selection"):
            self._box_select = None
            self._prune_mesh_tool_state()
        self._selected_deformer = None
        self._draw_list = build_draw_list(document) if document is not None else []
        # Frees run off paintGL (file-open / undo / pet rig swap) — need a
        # current GL context or the textures/VBOs leak on every reload.
        with self._current_gl_context():
            self._invalidate_texture_cache()
            self._invalidate_buffer_cache()
        self._user_view_locked = False
        self._parameter_values = (
            default_parameter_values(document) if document is not None else {}
        )
        self._active_expressions = []
        self._active_pose = {}
        if getattr(self, "_input_arbiter", None) is not None:
            self._input_arbiter.clear()
        self._physics.bind_document(document)
        self._physics_outputs = {}
        self._sync_physics_timer()
        self._recompute_deformed_vertices()
        self.document_loaded.emit()
        self.parameters_changed.emit()
        self.update()

    def document(self) -> PuppetDocument | None:
        return self._document

    def parameter_values(self) -> dict[str, float]:
        return dict(self._parameter_values)

    def input_arbiter(self):
        """The arbiter deciding which live input controls each parameter (R4.2)."""
        arbiter = getattr(self, "_input_arbiter", None)
        if arbiter is None:
            from rigora.puppet.input_arbitration import InputArbiter
            arbiter = self._input_arbiter = InputArbiter()
        return arbiter

    def submit_input(self, source: str, values: dict[str, float], *,
                     force: bool = False) -> dict[str, float]:
        """Write live-input values for ``source``; parameters a higher-priority
        source controls are skipped. Returns what was applied."""
        accepted = self.input_arbiter().submit(source, values)
        if accepted:
            self._write_parameters(accepted, force=force)
        return accepted

    def release_input(self, source: str) -> None:
        self.input_arbiter().release(source)

    def set_parameter_value(self, param_id: str, value: float) -> None:
        """Push a slider / motion / physics output into the parameter
        bag. Triggers a per-frame vertex recomposition + redraw."""
        self._write_parameters({param_id: value}, force=True)

    def set_parameter_values(self, values: dict[str, float]) -> None:
        """Batch-update many parameters in one go, recomputing the
        rig only once at the end. Big perf win for motion playback
        on Cubism-converted rigs where each frame writes 3+ tracks —
        per-call recompute was paying the full 307-drawable
        composition once per track instead of once per frame."""
        self._write_parameters(values, force=False)

    def force_parameter_values(self, values: dict[str, float]) -> None:
        """Batch-update parameters and recompute even when the values
        already match the cached state.

        Use case: a periodic driver (the auto-blink loop) needs to
        own the eye parameter every tick — without ``force``, another
        driver (motion player / webcam tracker) could write the same
        numeric value between blink ticks and the equality check
        below would skip the recompute, making the blink appear to
        stall after the first cycle."""
        self._write_parameters(values, force=True)

    def reset_parameters(self) -> None:
        """Restore every parameter to its authored default."""
        if self._document is None:
            return
        self._parameter_values = default_parameter_values(self._document)
        self._recompute_deformed_vertices()
        self.parameters_changed.emit()
        self.update()

    def _write_parameters(self, values: dict[str, float], *, force: bool) -> None:
        """Commit known parameters in order; redraw only after a complete batch.

        Forced writes include equal values. A failed conversion retains earlier
        writes without publishing a recomposed frame, matching individual setters.
        """
        if self._document is None:
            return
        changed = False
        for param_id, value in values.items():
            if param_id not in self._parameter_values:
                continue
            float_value = float(value)
            if force or self._parameter_values[param_id] != float_value:
                self._parameter_values[param_id] = float_value
                changed = True
        if changed:
            refresh_rig(self)
