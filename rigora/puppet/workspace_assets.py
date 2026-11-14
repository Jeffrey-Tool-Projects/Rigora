"""Updating art from a PSD and relinking textures in the puppet workspace.

Both run as one authored transaction, so Undo restores the previous
textures and meshes in a single step. The plan is made against the
document revision current when the dialog opened; a document that changed
meanwhile rejects the result instead of applying it to the wrong state.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.asset_update import (
    AssetUpdatePlan,
    AssetUpdateResult,
    apply_asset_update,
    find_missing_textures,
    plan_asset_update,
    relink_texture,
)
from rigora.puppet.asset_update_dialog import AssetUpdateDialog, RelinkTexturesDialog
from rigora.puppet.psd_import import plan_psd_import

logger = logging.getLogger("rigora.puppet.workspace")


class PuppetAssetsMixin:
    """Art update and texture relinking of :class:`~rigora.puppet.workspace.PuppetWorkspace`."""

    def _update_art_via_dialog(self) -> None:
        if self._canvas.document() is None:
            self._announce("puppet_art_update_no_doc", "Open a puppet before updating its art.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, language_wrapper.language_word_dict.get(
                "puppet_art_update_pick", "Choose the updated PSD"), "", "PSD (*.psd)")
        if not path:
            return
        revision = self._begin_document_work()
        update = self.plan_art_update(path)
        if update is None:
            return
        dialog = AssetUpdateDialog(self, update)
        if not self._run_asset_dialog(dialog):
            self._announce("puppet_import_cancelled", "Import cancelled; nothing changed.")
            return
        self.apply_art_update(update, dialog.actions(), revision=revision)

    def plan_art_update(self, path: str | Path, *, mapping=None) -> AssetUpdatePlan | None:
        """Compare the open puppet with ``path``; ``None`` after reporting a failure."""
        try:
            return plan_asset_update(self.session.document, plan_psd_import(path),
                                     mapping=mapping)
        except (ValueError, OSError) as exc:
            logger.warning("art update planning failed for %s: %s", path, exc)
            self._announce("puppet_art_update_failed",
                           "Art update failed: {error}", error=str(exc))
            return None

    def apply_art_update(self, update: AssetUpdatePlan, actions=None, *,
                         revision=None) -> AssetUpdateResult | None:
        """Apply ``update`` as one undoable edit. ``None`` when nothing applied."""
        if revision is not None and not self._accept_document_result(revision):
            return None
        try:
            with self.session.transaction("Update art from PSD"):
                result = apply_asset_update(self.session.document, update, actions)
        except ValueError as exc:
            self._announce("puppet_art_update_failed",
                           "Art update failed: {error}", error=str(exc))
            return None
        self._canvas.load_document(self.session.document)
        self._update_session_actions()
        dropped = sum(len(items) for items in result.dropped.values())
        self._announce(
            "puppet_art_update_done",
            "Art updated: {updated} replaced, {rebuilt} rebuilt ({dropped} rig items dropped), "
            "{added} added, {hidden} hidden.",
            updated=len(result.updated), rebuilt=len(result.rebuilt), dropped=dropped,
            added=len(result.added), hidden=len(result.hidden))
        return result

    def _relink_textures_via_dialog(self) -> None:
        document = self._canvas.document()
        if document is None:
            self._announce("puppet_art_update_no_doc", "Open a puppet before updating its art.")
            return
        missing = find_missing_textures(document)
        if not missing:
            self._announce("puppet_relink_none", "Every texture is present and readable.")
            return
        revision = self._begin_document_work()
        dialog = RelinkTexturesDialog(self, document, missing)
        if self._run_asset_dialog(dialog) and self._accept_document_result(revision):
            self.relink_textures(dialog.choices())

    def relink_textures(self, choices: dict[str, str | Path]) -> bool:
        """Store each chosen image as its texture, as one undoable edit."""
        if not choices:
            return False
        try:
            with self.session.transaction("Relink textures"):
                for texture, path in choices.items():
                    relink_texture(self.session.document, texture, path)
        except ValueError as exc:
            # The transaction restored the textures in place; rebuild GPU state from them.
            self._canvas.load_document(self.session.document)
            self._announce("puppet_relink_failed", "Relink failed: {error}", error=str(exc))
            return False
        self._canvas.load_document(self.session.document)
        self._update_session_actions()
        remaining = len(find_missing_textures(self.session.document))
        self._announce("puppet_relink_done", "Relinked {n} textures; {left} still missing.",
                       n=len(choices), left=remaining)
        return True

    def _run_asset_dialog(self, dialog: QDialog) -> bool:
        try:
            return dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            dialog.deleteLater()

    def _missing_texture_hint(self, document) -> str:
        """Status suffix for an opened document whose textures are absent."""
        absent = {d.texture for d in document.drawables} - set(document.textures)
        if not absent:
            return ""
        return " · " + language_wrapper.language_word_dict.get(
            "puppet_textures_missing_hint",
            "{n} textures missing: use File > Relink textures…",
        ).format(n=len(absent))
