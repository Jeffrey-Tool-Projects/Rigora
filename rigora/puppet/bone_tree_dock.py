"""Bone-hierarchy editor — QTreeView over :attr:`Deformer.parent`.

The runtime's ``compose_drawable_vertices`` already honours the
parent chain (topological sort), so anything the user does here
changes how the rig renders without further wiring.

The widget supports:

* **Read** — every deformer in the active document shows up under its
  ``parent`` (root-level deformers sit at the top).
* **Reparent** — drag a deformer onto another row to set its
  ``parent`` to that row's id.
* **Detach** — drag onto the empty area to clear ``parent`` (the
  deformer becomes a root).
* **Select** — clicking a row emits :attr:`deformer_selected` so the
  workspace can highlight the same deformer elsewhere (parameter
  dock filter, mesh-edit focus, …).
* **Order** — Up / Down move a deformer among its siblings, which is
  the order siblings are applied in.
* **Search, hide, lock** — the filter matches ids, types and target
  drawables; hidden rows show only with *Show hidden*; locked deformers
  refuse reparenting and reordering. Hide and lock are editor state and
  are not saved in the document.
* **Check** — parent cycles and parents that no longer exist are listed
  above the tree.

Kept Qt-thin — the data model is just ``document.deformers``; we
read it on rebuild and write back on drop.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from rigora.i18n.language_wrapper import language_wrapper
from rigora.puppet.rig_hierarchy import (
    ancestors,
    find_cycles,
    missing_parents,
    move_deformer,
    reparent_deformer,
    search_deformers,
)

if TYPE_CHECKING:
    from rigora.puppet.canvas import PuppetCanvas
    from rigora.puppet.document import Deformer


_ID_ROLE = Qt.ItemDataRole.UserRole


def _tr(key: str, fallback: str, **fmt) -> str:
    return language_wrapper.language_word_dict.get(key, fallback).format(**fmt)


class BoneTreeDock(QDockWidget):
    """Tree view of every deformer in the loaded document.

    Each row's ``UserRole`` stores the deformer id so drag-and-drop /
    selection handlers can resolve back to a :class:`Deformer`
    without a separate lookup."""

    deformer_selected = Signal(str)
    """Fires with the deformer id when the user clicks a row."""

    hierarchy_changed = Signal()
    """Fires after any reparent or reorder — the workspace records the
    edit and re-renders so the canvas reflects the new FK order."""

    def __init__(self, canvas: PuppetCanvas, parent=None):
        super().__init__(_tr("puppet_bone_tree_dock", "Bones"), parent)
        self._canvas = canvas
        self._hidden: set[str] = set()
        self._locked: set[str] = set()
        self._inner = QWidget()
        layout = QVBoxLayout(self._inner)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText(_tr("puppet_bone_search", "Search deformers…"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _text: self._rebuild())
        layout.addWidget(self._search)

        self._problems = QLabel()
        self._problems.setObjectName("bone_tree_problems")
        self._problems.setWordWrap(True)
        self._problems.setStyleSheet("color: #d08020;")
        self._problems.setVisible(False)
        layout.addWidget(self._problems)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels([
            _tr("puppet_bone_tree_col_id", "ID"),
            _tr("puppet_bone_tree_col_type", "Type"),
        ])
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._tree.itemClicked.connect(self._on_item_clicked)
        # Right-click anywhere on the tree clears the selection. We
        # use the customContextMenuRequested signal rather than
        # overriding mousePressEvent so the default drag-and-drop path
        # stays untouched.
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(
            self._on_tree_context_request,
        )
        layout.addWidget(self._tree)
        layout.addLayout(self._build_buttons())

        self._empty_state = QLabel(
            _tr("puppet_bone_tree_empty", "No deformers yet — add one from the toolbar."),
        )
        self._empty_state.setWordWrap(True)
        self._empty_state.setStyleSheet("color: #888; padding: 8px;")
        layout.addWidget(self._empty_state)

        self.setWidget(self._inner)

        # The dock listens for new documents and (when present) the
        # canvas's deformer change signal. The canvas may or may not
        # emit such a signal yet — connect defensively.
        canvas.document_loaded.connect(self._rebuild)
        self._rebuild()

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._up_button = QPushButton(_tr("puppet_bone_up", "Up"))
        self._up_button.clicked.connect(lambda: self.move_selected(-1))
        self._down_button = QPushButton(_tr("puppet_bone_down", "Down"))
        self._down_button.clicked.connect(lambda: self.move_selected(1))
        self._lock_button = QPushButton(_tr("puppet_bone_lock", "Lock"))
        self._lock_button.clicked.connect(self._toggle_lock_selected)
        self._hide_button = QPushButton(_tr("puppet_bone_hide", "Hide"))
        self._hide_button.clicked.connect(self._toggle_hide_selected)
        self._show_hidden = QCheckBox(_tr("puppet_bone_show_hidden", "Show hidden"))
        self._show_hidden.toggled.connect(lambda _on: self._rebuild())
        for widget in (self._up_button, self._down_button, self._lock_button,
                       self._hide_button, self._show_hidden):
            row.addWidget(widget)
        return row

    # ---- public --------------------------------------------------------

    def tree(self) -> QTreeWidget:
        return self._tree

    def rebuild(self) -> None:
        """Public re-entry point — workspace calls this after toolbar
        actions add / remove deformers."""
        self._rebuild()

    def clear_selection(self) -> None:
        """Drop the tree-row highlight without emitting
        ``deformer_selected`` — used when the canvas already cleared
        its overlay (e.g. via a right-click) and we just need the
        tree state to match."""
        self._tree.clearSelection()

    def select_deformer(self, identifier: str | None) -> None:
        self._tree.clearSelection()
        iterator = QTreeWidgetItemIterator(self._tree)
        while iterator.value() is not None:
            item = iterator.value()
            if item.data(0, _ID_ROLE) == identifier:
                self._tree.setCurrentItem(item)
                item.setSelected(True)
                return
            iterator += 1

    def selected_id(self) -> str | None:
        item = self._tree.currentItem()
        value = item.data(0, _ID_ROLE) if item is not None else None
        return value if isinstance(value, str) else None

    def set_search_text(self, text: str) -> None:
        self._search.setText(text)

    def visible_ids(self) -> list[str]:
        found = []
        iterator = QTreeWidgetItemIterator(self._tree)
        while iterator.value() is not None:
            found.append(iterator.value().data(0, _ID_ROLE))
            iterator += 1
        return found

    def problems_text(self) -> str:
        return self._problems.text()

    def set_locked(self, deformer_id: str, locked: bool) -> None:
        if locked:
            self._locked.add(deformer_id)
        else:
            self._locked.discard(deformer_id)
        self._rebuild()

    def set_hidden(self, deformer_id: str, hidden: bool) -> None:
        if hidden:
            self._hidden.add(deformer_id)
        else:
            self._hidden.discard(deformer_id)
        self._rebuild()

    def set_show_hidden(self, show: bool) -> None:
        self._show_hidden.setChecked(show)

    def is_locked(self, deformer_id: str) -> bool:
        return deformer_id in self._locked

    def _on_tree_context_request(self, _pos) -> None:
        """Right-click in the tree clears the selection on both
        sides. Emits an empty ``deformer_selected`` so the canvas
        overlay drops in lockstep."""
        self._tree.clearSelection()
        self.deformer_selected.emit("")

    # ---- rebuild -------------------------------------------------------

    def _rebuild(self) -> None:
        self._tree.clear()
        document = self._canvas.document()
        deformers = list(document.deformers) if document is not None else []
        self._report_problems(document)
        if not deformers:
            self._tree.setVisible(False)
            self._empty_state.setVisible(True)
            return
        self._tree.setVisible(True)
        self._empty_state.setVisible(False)
        shown = self._shown_ids(document)
        items: dict[str, QTreeWidgetItem] = {
            d.id: self._row_for(d) for d in deformers if d.id in shown
        }
        # Rows exist first; parent links are wired after, because a child
        # can appear in document order before its parent.
        for deformer in deformers:
            item = items.get(deformer.id)
            if item is None:
                continue
            parent_item = items.get(deformer.parent) if deformer.parent else None
            if parent_item is None or deformer.id in ancestors(document, deformer.parent):
                self._tree.addTopLevelItem(item)   # orphans and cycle members
            else:
                parent_item.addChild(item)
        self._tree.expandAll()

    def _shown_ids(self, document) -> set[str]:
        """Matches of the search plus their ancestors, minus hidden rows."""
        matches = set(search_deformers(document, self._search.text()))
        if self._search.text().strip():
            for deformer_id in list(matches):
                matches.update(ancestors(document, deformer_id))
        if not self._show_hidden.isChecked():
            matches -= self._hidden
        return matches

    def _report_problems(self, document) -> None:
        lines = []
        if document is not None:
            for cycle in find_cycles(document):
                lines.append(_tr("puppet_bone_cycle", "Parent cycle: {ids}",
                                 ids=" → ".join([*cycle, cycle[0]])))
            for deformer_id in missing_parents(document):
                lines.append(_tr("puppet_bone_missing_parent",
                                 "{id} points at a parent that does not exist",
                                 id=deformer_id))
        self._problems.setText("\n".join(lines))
        self._problems.setVisible(bool(lines))

    def _row_for(self, deformer: Deformer) -> QTreeWidgetItem:
        label = deformer.id
        if deformer.id in self._locked:
            label += " [" + _tr("puppet_bone_locked_tag", "locked") + "]"
        if deformer.id in self._hidden:
            label += " (" + _tr("puppet_bone_hidden_tag", "hidden") + ")"
        item = QTreeWidgetItem([label, deformer.type])
        item.setData(0, _ID_ROLE, deformer.id)
        flags = item.flags() | Qt.ItemFlag.ItemIsDropEnabled
        if deformer.id not in self._locked:
            flags |= Qt.ItemFlag.ItemIsDragEnabled
        item.setFlags(flags)
        return item

    # ---- slots ---------------------------------------------------------

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        deformer_id = item.data(0, _ID_ROLE)
        if isinstance(deformer_id, str):
            self.deformer_selected.emit(deformer_id)

    def _toggle_lock_selected(self) -> None:
        selected = self.selected_id()
        if selected is not None:
            self.set_locked(selected, selected not in self._locked)

    def _toggle_hide_selected(self) -> None:
        selected = self.selected_id()
        if selected is not None:
            self.set_hidden(selected, selected not in self._hidden)

    def move_selected(self, offset: int) -> bool:
        selected = self.selected_id()
        return selected is not None and self.move(selected, offset)

    def move(self, deformer_id: str, offset: int) -> bool:
        """Reorder among siblings; refused for locked deformers."""
        document = self._canvas.document()
        if document is None or deformer_id in self._locked:
            return False
        if not move_deformer(document, deformer_id, offset):
            return False
        self._rebuild()
        self.select_deformer(deformer_id)
        self.hierarchy_changed.emit()
        return True

    def reparent(self, child_id: str, new_parent: str | None) -> bool:
        """Programmatic equivalent of the drag-and-drop path — also
        the entry point used by tests so we don't need a real drop
        event. Returns ``True`` when the document was mutated. Cycles,
        unknown ids and locked deformers are refused."""
        document = self._canvas.document()
        if document is None or child_id in self._locked:
            return False
        try:
            changed = reparent_deformer(document, child_id, new_parent)
        except ValueError:
            return False
        if not changed:
            return False
        self._rebuild()
        self.hierarchy_changed.emit()
        return True
