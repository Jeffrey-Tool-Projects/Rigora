"""Animation commands: compositions, takes and exports (R3).

Compositions are validated and applied in one transaction; previews bake a
copy to a temporary motion so playback never changes the document.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtWidgets import QDialog

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.composition import bake_composition, validate_composition


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


class PuppetAnimationMixin:
    """Composition, take and export commands of the puppet workspace."""

    def _animation_edit(self, label: str, edit):
        if self.session.document is None:
            self._announce("puppet_rig_no_doc", "Open a puppet first.")
            return None
        self._begin_document_work()
        try:
            with self.session.transaction(label):
                result = edit(self.session.document)
        except ValueError as exc:
            self._announce("puppet_rig_edit_failed", "{label} failed: {error}",
                           label=label, error=str(exc))
            return None
        self._canvas.load_document(self.session.document)
        self._update_session_actions()
        return result

    def apply_compositions(self, compositions) -> bool:
        def edit(document):
            problems = [f"{c.name}: {p}" for c in compositions
                        for p in validate_composition(document, c)]
            if len({c.name for c in compositions}) != len(compositions):
                problems.append("composition names must be unique")
            if problems:
                raise ValueError("; ".join(problems))
            document.compositions = deepcopy(list(compositions))
            return len(compositions)

        count = self._animation_edit("Edit compositions", edit)
        if count is None:
            return False
        self._announce("puppet_compositions_saved", "{n} compositions saved.", n=count)
        return True

    def preview_composition(self, composition, *, fps: float = 30.0) -> bool:
        """Play a baked copy; the document is not changed."""
        document = self._canvas.document()
        if document is None:
            return False
        baked = bake_composition(document, composition, fps=fps)
        player = self._motion_dock.player()
        player.set_motion(baked)
        player.play()
        self._announce("puppet_compositions_previewing", "Previewing {name}.",
                       name=composition.name)
        return True

    def bake_composition_to_motion(self, name: str, *, fps: float = 30.0) -> str | None:
        """Add a baked motion of composition ``name`` to the document; returns its name."""
        def edit(document):
            composition = next((c for c in document.compositions if c.name == name), None)
            if composition is None:
                raise ValueError(f"no composition {name!r}")
            taken = {m.name for m in document.motions}
            baked = bake_composition(document, composition, fps=fps)
            base, index = baked.name, 2
            while baked.name in taken:
                baked.name = f"{base} {index}"
                index += 1
            document.motions.append(baked)
            return baked.name

        motion = self._animation_edit("Bake composition", edit)
        if motion is not None:
            self._announce("puppet_compositions_baked", "Baked {name} into motion {motion}.",
                           name=name, motion=motion)
        return motion

    def edit_compositions_via_dialog(self) -> bool:
        from rigora.puppet.composition_dialog import CompositionDialog
        document = self._canvas.document()
        if document is None:
            self._announce("puppet_rig_no_doc", "Open a puppet first.")
            return False
        dialog = CompositionDialog(self, document)
        dialog.preview_requested = self.preview_composition
        accepted = self._run_animation_dialog(dialog)
        result = dialog.result()
        bake = dialog.bake_requested
        dialog.deleteLater()
        applied = accepted and self.apply_compositions(result)
        if applied and bake:
            self.bake_composition_to_motion(bake)
        return applied

    # ---- offline export (R3.5 / R3.6) --------------------------------------

    def export_queue(self):
        """The workspace's export queue, driven by a zero-interval timer."""
        queue = getattr(self, "_export_queue", None)
        if queue is None:
            from PySide6.QtCore import QTimer

            from rigora.puppet.offline_export import ExportQueue
            from rigora.puppet.offline_render_gl import canvas_renderer_factory
            queue = ExportQueue(render_factory=canvas_renderer_factory)
            self._export_queue = queue
            self._export_timer = QTimer(self)
            self._export_timer.setInterval(0)
            self._export_timer.timeout.connect(self._step_exports)
        return queue

    def _step_exports(self) -> None:
        queue = self._export_queue
        if not queue.step() or not queue.busy():
            self._export_timer.stop()
            finished = [j for j in queue.jobs if j.state in ("done", "failed", "cancelled")]
            if finished:
                last = finished[-1]
                self._announce("puppet_export_finished", "Export {state}: {label}",
                               state=last.state, label=last.label())

    def queue_export(self, kind: str, name: str, settings, target):
        """Queue an export of a motion or composition from the current document."""
        from rigora.puppet.offline_export import ExportJob, FrameSource
        document = self._canvas.document()
        if document is None:
            raise ValueError("open a puppet first")
        source = (FrameSource(document, motion=name) if kind == "motion"
                  else FrameSource(document, composition=name))
        job = self.export_queue().add(ExportJob(source, settings, Path(target)))
        self._export_timer.start()
        return job

    def export_animation_via_dialog(self) -> None:
        from rigora.puppet.export_dialog import ExportDialog
        document = self._canvas.document()
        if document is None:
            self._announce("puppet_rig_no_doc", "Open a puppet first.")
            return
        dialog = ExportDialog(self, document, self.export_queue(), self.queue_export)
        self._run_animation_dialog(dialog)
        dialog.deleteLater()

    def _shutdown_exports(self) -> None:
        queue = getattr(self, "_export_queue", None)
        if queue is not None:
            self._export_timer.stop()
            queue.shutdown()

    def _run_animation_dialog(self, dialog: QDialog) -> bool:
        return dialog.exec() == QDialog.DialogCode.Accepted
