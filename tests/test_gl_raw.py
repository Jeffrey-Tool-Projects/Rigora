"""R7.3: the draw loop suspends per-call GL checks but still raises once."""
from __future__ import annotations

import pytest

pytest.importorskip("OpenGL")

from OpenGL.error import GLError  # noqa: E402

from rigora.rendering import gl_raw  # noqa: E402


def test_unchecked_restores_checker_and_reports_pending_error(monkeypatch):
    checker = gl_raw._error_checker   # noqa: SLF001
    registered = checker._registeredChecker   # noqa: SLF001
    monkeypatch.setattr(gl_raw, "glGetError", lambda: 0)
    with gl_raw.unchecked("batch"):
        assert checker._currentChecker == checker.nullGetError   # noqa: SLF001
    assert checker._currentChecker == registered   # noqa: SLF001
    monkeypatch.setattr(gl_raw, "glGetError", lambda: 1282)
    with pytest.raises(GLError) as error, gl_raw.unchecked("draw drawables"):
        pass
    assert error.value.err == 1282 and error.value.baseOperation == "draw drawables"


def test_exception_inside_batch_restores_checking_without_masking(monkeypatch):
    checker = gl_raw._error_checker   # noqa: SLF001
    monkeypatch.setattr(gl_raw, "glGetError", lambda: 0)
    with pytest.raises(RuntimeError, match="boom"), gl_raw.unchecked("x"):
        raise RuntimeError("boom")
    assert checker._currentChecker == checker._registeredChecker   # noqa: SLF001
