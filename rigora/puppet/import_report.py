"""Import differences shared by the PSD and Cubism previews.

A difference names one source feature that an import drops, approximates
or renames. ``error`` means the import as requested will fail, ``warning``
that the result looks or behaves differently, ``info`` that metadata changes
or something is skipped by design.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"


@dataclass(frozen=True)
class ImportDifference:
    """One source feature the import drops, approximates or renames."""

    code: str
    subject: str
    detail: str
    severity: str = SEVERITY_WARNING

    def to_dict(self) -> dict:
        return asdict(self)
