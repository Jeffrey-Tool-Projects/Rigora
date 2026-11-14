"""Unchecked GL entry points for the per-drawable draw loop (R7.3).

PyOpenGL calls ``glGetError`` after every GL call. After a draw call that
forces the driver to finish queued work, which made error checking cost about
70 % of a frame on a 400-drawable rig. The draw loop runs inside
:func:`unchecked`, which suspends that per-call check the same way PyOpenGL
does between ``glBegin`` / ``glEnd``, and calls :func:`check` once when the
pass ends, so a GL error still raises :class:`OpenGL.error.GLError` — once per
pass instead of once per call. The raw entry points also skip PyOpenGL's
per-call argument wrappers. Everything outside the loop keeps the checked,
wrapped functions.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from OpenGL.error import GLError
from OpenGL.raw.GL._errors import _error_checker
from OpenGL.raw.GL.VERSION.GL_1_1 import (
    glBindTexture,
    glBlendFunc,
    glColor4f,
    glColorMask,
    glDisable,
    glDrawElements,
    glEnable,
    glGetError,
    glStencilFunc,
    glStencilOp,
    glTexCoordPointer,
    glVertexPointer,
)
from OpenGL.raw.GL.VERSION.GL_1_5 import glBindBuffer, glBufferData, glBufferSubData

__all__ = [
    "check", "unchecked", "glBindBuffer", "glBindTexture", "glBlendFunc", "glBufferData",
    "glBufferSubData", "glColor4f", "glColorMask", "glDisable", "glDrawElements", "glEnable",
    "glStencilFunc", "glStencilOp", "glTexCoordPointer", "glVertexPointer",
]


def check(operation: str) -> None:
    """Raise the first pending GL error, naming the batched ``operation``."""
    error = glGetError()
    if error:
        raise GLError(err=error, baseOperation=operation)


@contextmanager
def unchecked(operation: str) -> Iterator[None]:
    """Suspend per-call error checks for a batch, then check once."""
    _error_checker.onBegin()
    try:
        yield
    finally:
        _error_checker.onEnd()
    check(operation)
