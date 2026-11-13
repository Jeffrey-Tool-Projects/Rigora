"""Qt-free authored document history, save points and stale-result detection."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
import sys
from uuid import uuid4

from rigora.puppet.document import PuppetDocument
from rigora.puppet.document_io import save_puppet


def authored_copy(document: PuppetDocument | None) -> PuppetDocument | None:
    """Copy authored fields without the runtime's disposable numpy caches."""
    if document is None:
        return None
    result = deepcopy(document)
    for drawable in result.drawables:
        for name in list(vars(drawable)):
            if name.startswith("_np_"):
                delattr(drawable, name)
        for morph in drawable.vertex_morphs or []:
            for name in list(morph):
                if name.startswith("_np_"):
                    del morph[name]
    return result


def documents_equal(left: PuppetDocument | None, right: PuppetDocument | None) -> bool:
    """Compare authored fields without copying geometry on each dirty check."""
    if left is None or right is None:
        return left is right
    for field in fields(left):
        a, b = getattr(left, field.name), getattr(right, field.name)
        if field.name != "drawables":
            if a != b:
                return False
        elif len(a) != len(b) or any(not _drawable_equal(x, y) for x, y in zip(a, b, strict=True)):
            return False
    return True


def _drawable_equal(left, right) -> bool:
    for field in fields(left):
        a, b = getattr(left, field.name), getattr(right, field.name)
        if field.name == "vertex_morphs":
            a, b = (_authored_morphs(value) for value in (a, b))
        if a != b:
            return False
    return True


def _authored_morphs(morphs):
    if morphs is None:
        return None
    return [{key: value for key, value in morph.items() if not key.startswith("_np_")}
            for morph in morphs]


@dataclass(frozen=True)
class Revision:
    document_id: str
    number: int


@dataclass
class EditState:
    document: PuppetDocument
    selection: str | None
    label: str = ""


def _memory_size(value: object, seen: set[int]) -> int:
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if is_dataclass(value) and not isinstance(value, type):
        return size + sum(_memory_size(getattr(value, f.name), seen) for f in fields(value))
    if isinstance(value, dict):
        return size + sum(_memory_size(k, seen) + _memory_size(v, seen) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return size + sum(_memory_size(item, seen) for item in value)
    return size


class DocumentSession:
    """One document's authored state; playback values belong to the canvas.

    Edits may use ``transaction`` or call ``checkpoint`` after a completed
    gesture. Snapshots share immutable texture bytes through deepcopy. History
    is bounded by both count and retained bytes; an oversized edit remains
    dirty and saveable even when its undo state cannot fit the budget.
    """

    def __init__(self, *, max_history_bytes: int = 128 * 1024 * 1024,
                 max_history_steps: int = 100) -> None:
        if max_history_bytes < 0 or max_history_steps < 0:
            raise ValueError("History limits must be nonnegative")
        self.max_history_bytes = max_history_bytes
        self.max_history_steps = max_history_steps
        self.document: PuppetDocument | None = None
        self.path: Path | None = None
        self.selection: str | None = None
        self._identity = uuid4().hex
        self._revision = 0
        self._saved: PuppetDocument | None = None
        self.saved_revision: Revision | None = None
        self._current: EditState | None = None
        self._undo: list[EditState] = []
        self._redo: list[EditState] = []
        self._transaction_depth = 0

    @property
    def revision(self) -> Revision:
        return Revision(self._identity, self._revision)

    @property
    def dirty(self) -> bool:
        return self.document is not None and not documents_equal(self.document, self._saved)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def history_bytes(self) -> int:
        return _memory_size([*self._undo, *self._redo], set()) if self._undo or self._redo else 0

    def bind(self, document: PuppetDocument | None, *, path: str | Path | None = None,
             saved: bool = False) -> None:
        if self._transaction_depth:
            raise RuntimeError("Cannot replace a document during an edit transaction")
        self.document = document
        self.path = Path(path).resolve() if path is not None else None
        self.selection = None
        self._identity = uuid4().hex
        self._revision = 0
        self._saved = authored_copy(document) if saved else None
        self.saved_revision = self.revision if saved else None
        self._current = self._snapshot()
        self._undo.clear()
        self._redo.clear()

    def _snapshot(self, label: str = "") -> EditState | None:
        if self.document is None:
            return None
        return EditState(authored_copy(self.document), self.selection, label)

    def select(self, selection: str | None) -> None:
        self.selection = selection
        if self._current is not None:
            self._current.selection = selection

    def checkpoint(self, label: str) -> bool:
        if self._transaction_depth or self.document is None:
            return False
        if self._current is not None and documents_equal(self.document, self._current.document):
            self._current.selection = self.selection
            return False
        if self._current is not None:
            self._current.label = label
            self._undo.append(self._current)
        self._redo.clear()
        self._current = self._snapshot(label)
        self._revision += 1
        self._trim_history()
        return True

    def _trim_history(self) -> None:
        while (len(self._undo) + len(self._redo) > self.max_history_steps
               or self.history_bytes > self.max_history_bytes):
            if self._undo:
                self._undo.pop(0)
            elif self._redo:
                self._redo.pop(0)
            else:
                break

    def _restore(self, state: EditState) -> None:
        restored = deepcopy(state.document)
        if self.document is None:
            self.document = restored
        else:
            for field in fields(restored):
                setattr(self.document, field.name, getattr(restored, field.name))
        self.selection = state.selection
        self._current = self._snapshot(state.label)

    def undo(self) -> bool:
        if self._transaction_depth:
            raise RuntimeError("Finish the active gesture before undo")
        self.checkpoint("Edit document")
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        self._revision += 1
        self._trim_history()
        return True

    def redo(self) -> bool:
        if self._transaction_depth:
            raise RuntimeError("Finish the active gesture before redo")
        self.checkpoint("Edit document")
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        self._revision += 1
        self._trim_history()
        return True

    @contextmanager
    def transaction(self, label: str) -> Iterator[PuppetDocument]:
        if self.document is None:
            raise ValueError("Load a document before editing")
        before = self._snapshot()
        previous_current = self._current
        self._transaction_depth += 1
        try:
            yield self.document
        except BaseException:
            self._restore(before)
            self._current = previous_current
            raise
        finally:
            self._transaction_depth -= 1
        self.checkpoint(label)

    def save(self, path: str | Path | None = None) -> None:
        destination = Path(path).resolve() if path is not None else self.path
        if self.document is None or destination is None:
            raise ValueError("Choose a destination for the document")
        self.checkpoint("Edit document")
        save_puppet(self.document, destination)
        self.mark_saved(destination)

    def mark_saved(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self._saved = authored_copy(self.document)
        self.saved_revision = self.revision

    def accepts(self, revision: Revision) -> bool:
        """Reject results after replacement, edits, undo, or uncommitted edits."""
        expected = self._current.document if self._current is not None else None
        return self.revision == revision and documents_equal(self.document, expected)
