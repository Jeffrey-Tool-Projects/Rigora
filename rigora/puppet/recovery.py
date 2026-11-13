"""Atomic recovery archives isolated by a process-held store lock."""
from __future__ import annotations

from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
from uuid import uuid4
import zipfile

from rigora.puppet.document import PuppetDocument
from rigora.puppet.document_io import load_puppet, to_zip_bytes
from rigora.puppet.document_session import DocumentSession
from rigora.system.atomic_write import replace_atomically


def _lock(stream, *, release: bool = False) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        mode = msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK
        msvcrt.locking(stream.fileno(), mode, 1)
    else:
        import fcntl
        mode = fcntl.LOCK_UN if release else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(stream.fileno(), mode)


@dataclass(frozen=True)
class RecoveryCandidate:
    archive: Path
    source: Path | None


class RecoveryStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / uuid4().hex
        self.directory.mkdir(parents=True)
        self._owner = (self.directory / "owner.lock").open("w+b")
        self._owner.write(b"1")
        self._owner.flush()
        _lock(self._owner)
        self._written_revision = None

    def write(self, session: DocumentSession) -> Path | None:
        if session.document is None or not session.dirty:
            return None
        session.checkpoint("Edit document")
        target = self.directory / f"{session.revision.document_id}.puppet"
        if self._written_revision == session.revision and target.exists():
            return target
        metadata = json.dumps({"version": 1, "source": str(session.path) if session.path else None})
        buffer = io.BytesIO(to_zip_bytes(session.document))
        with zipfile.ZipFile(buffer, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("recovery.json", metadata)
        data = buffer.getvalue()
        replace_atomically(target, lambda temporary: temporary.write_bytes(data))
        self._written_revision = session.revision
        return target

    def discard(self, session: DocumentSession) -> None:
        (self.directory / f"{session.revision.document_id}.puppet").unlink(missing_ok=True)
        self._written_revision = None

    def candidates(self) -> tuple[list[RecoveryCandidate], list[str]]:
        found: list[RecoveryCandidate] = []
        errors: list[str] = []
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir() or folder == self.directory:
                continue
            try:
                with (folder / "owner.lock").open("r+b") as owner:
                    _lock(owner)
                    try:
                        self._read_candidates(folder, found, errors)
                    finally:
                        _lock(owner, release=True)
            except OSError:
                # A live owner or an inaccessible folder is not a recovery candidate.
                continue
        return found, errors

    @staticmethod
    def _read_candidates(folder: Path, found: list[RecoveryCandidate], errors: list[str]) -> None:
        for path in sorted(folder.glob("*.puppet")):
            try:
                with zipfile.ZipFile(path) as archive:
                    info = archive.getinfo("recovery.json")
                    if info.file_size > 65536:
                        raise ValueError("Recovery metadata is too large")
                    metadata = json.loads(archive.read(info))
                if not isinstance(metadata, dict) or metadata.get("version") != 1:
                    raise ValueError("Unsupported recovery metadata")
                source = metadata.get("source")
                if source is not None and not isinstance(source, str):
                    raise ValueError("Invalid recovery source path")
                load_puppet(path)
                found.append(RecoveryCandidate(path, Path(source) if source else None))
            except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
                errors.append(f"{path.name}: {exc}")

    @staticmethod
    def load(candidate: RecoveryCandidate) -> PuppetDocument:
        return load_puppet(candidate.archive)

    def close(self) -> None:
        if not self._owner.closed:
            _lock(self._owner, release=True)
            self._owner.close()
