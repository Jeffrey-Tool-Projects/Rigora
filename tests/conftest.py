import os
import sys
import time
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
_rng = np.random.default_rng(seed=0xC0FFEE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HEADLESS_CI = os.environ.get("CI") == "true" or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
skip_on_headless_ci = pytest.mark.skipif(HEADLESS_CI, reason="Native OpenGL widget requires a rendering context")


@pytest.fixture(scope="session")
def qapp():
    """Provide a single QApplication for tests that need Qt.

    Tests that don't import PySide6 are unaffected — the fixture is
    only instantiated when explicitly requested.
    """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    if sys.platform == "win32" and app.platformName() == "offscreen":
        from PySide6.QtGui import QFontDatabase

        # Windows' offscreen plugin does not discover the system font directory.
        # Real glyphs are needed for text layout and font-selector tests.
        if not QFontDatabase.families():
            font_dir = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "Fonts"
            for filename in ("segoeui.ttf", "cour.ttf"):
                if QFontDatabase.addApplicationFont(str(font_dir / filename)) < 0:
                    pytest.fail(f"Cannot load offscreen test font: {font_dir / filename}")
            font = app.font()
            font.setFamily("Segoe UI")
            app.setFont(font)
    return app


@pytest.fixture
def pump_until(qapp):
    """Pump the Qt event loop until *predicate* holds, or *timeout* seconds pass.

    Returns the predicate's final value. Use this instead of a fixed number of
    ``processEvents()`` passes: how many passes a queued cross-thread signal
    needs depends on machine load, so a fixed count makes the test flaky.
    """
    def _pump(predicate, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            qapp.processEvents()
            if predicate():
                return True
            if time.monotonic() >= deadline:
                return bool(predicate())
            time.sleep(0.01)

    return _pump


@pytest.fixture
def fake_clipboard(qapp, monkeypatch):
    """Replace ``QApplication.clipboard()`` with an in-process clipboard.

    The real one is OS state shared with every other process: another program
    can hold it open (so a set silently fails) or change it mid-test, and on
    Windows ``dataChanged`` arrives asynchronously, so two quick sets can
    coalesce into one signal. It also wiped the developer's own clipboard on
    every run. The fake keeps one ``QMimeData`` and emits ``dataChanged``
    synchronously on every change.
    """
    from PySide6.QtCore import QMimeData, QObject, Signal
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    class _FakeClipboard(QObject):
        dataChanged = Signal()  # noqa: N815 - mirrors QClipboard

        def __init__(self) -> None:
            super().__init__()
            self._mime = QMimeData()

        def _replace(self, mime) -> None:
            self._mime = mime
            self.dataChanged.emit()

        def setText(self, text, _mode=None) -> None:  # noqa: N802 - Qt API
            mime = QMimeData()
            mime.setText(text)
            self._replace(mime)

        def text(self, _mode=None) -> str:
            return self._mime.text()

        def setImage(self, image, _mode=None) -> None:  # noqa: N802 - Qt API
            mime = QMimeData()
            mime.setImageData(image)
            self._replace(mime)

        def image(self, _mode=None):
            data = self._mime.imageData() if self._mime.hasImage() else None
            return QImage(data) if data is not None else QImage()

        def mimeData(self, _mode=None):  # noqa: N802 - Qt API
            return self._mime

        def setMimeData(self, mime, _mode=None) -> None:  # noqa: N802 - Qt API
            self._replace(mime)

        def clear(self, _mode=None) -> None:
            self._replace(QMimeData())

    fake = _FakeClipboard()
    monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: fake))
    yield fake
    fake.deleteLater()


@pytest.fixture(scope="session", autouse=True)
def _qt_session_teardown():
    """Shut Qt down explicitly at the very end of the session.

    Why this exists: CI reported runs where every test passed
    (``test_workspace_manager`` was the last to print ``PASSED``),
    pytest's summary line never appeared, and the process exited
    with code 1 and a truncated log. Classic Windows symptom —
    ``QApplication`` is still alive when Python finalisation starts
    tearing down modules, and a stale ``shiboken`` wrapper held
    somewhere blows up during ``__del__``. The crash kills the
    process before pytest can flush its summary banner.

    Draining ``DeferredDelete``, spinning the event loop once, then
    quitting the app explicitly while the interpreter is still in
    a sane state — before Python starts unloading modules — keeps
    teardown deterministic. We deliberately do NOT drop the
    ``QApplication`` reference; on Windows that triggers the same
    finalisation race we're trying to avoid. Quitting is enough.
    """
    yield
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    # Two drain passes: first clears most pending DeferredDeletes,
    # second mops up the cascade (a parent being deleted enqueues
    # deletes for its children). We deliberately do NOT call
    # ``processEvents()`` — that would fire user-registered timers
    # (e.g. ``QTimer.singleShot`` callbacks from Paint tests) that
    # reference now-dead C++ objects and raise mid-teardown. The
    # DeferredDelete drain alone is the smallest cleanup that
    # frees the C++ side before Python finalises.
    for _ in range(2):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.quit()


@pytest.fixture(autouse=True, scope="session")
def _suppress_automatic_gc():
    """Stop Python's generational GC from firing inside test code.

    Crashes seen in CI:

        Garbage-collecting
        File "Imervue/paint/tool_bar.py", line 125 in _add_tool_action
        tests/test_paint_autosave_status.py::…

    Python's GC fires when allocation counters cross
    ``gc.get_threshold()`` — by default ``(700, 10, 10)``. Inside a
    test that constructs a ``PaintWorkspace`` (dozens of toolbar
    actions, dock widgets, sliders) the gen-0 threshold trips
    mid-construction. If a *prior* test leaked an orphan QObject
    wrapper (parented to ``None``, held by a closure / signal
    capture, never ``deleteLater()``'d), GC walks into the wrapper
    while its C++ partner is already gone → ``access violation``.
    The traceback then blames the unrelated test currently running.

    Drain-only (``sendPostedEvents`` of ``DeferredDelete``) handled
    the leaks that *did* call ``deleteLater()``. This raises the
    threshold so automatic GC effectively doesn't fire during the
    session; refcounting still cleans up almost everything, and
    pytest's per-test teardown runs the explicit Qt drain.

    A targeted ``gc.collect()`` would be cheaper conceptually but
    was rejected twice: full collect added ~350 ms / test (suite
    went from 3 min → 42 min); ``gc.collect(0)`` disturbed the
    Windows clipboard state on six tests.

    The original thresholds are restored on session teardown so
    Python's exit cleanup runs normally.
    """
    import gc
    original = gc.get_threshold()
    # 700_000 is comfortably above what any single test allocates,
    # so automatic GC effectively never fires in test code. We
    # leave gen-1 / gen-2 thresholds alone since they only matter
    # if gen-0 fires.
    gc.set_threshold(700_000, original[1], original[2])
    yield
    gc.set_threshold(*original)


@pytest.fixture(autouse=True)
def _drain_qt_deferred_delete():
    """Drain queued ``DeferredDelete`` events between tests.

    ``QObject.deleteLater()`` marks an object for deletion at the
    next event-loop spin. Many Qt-using tests in this suite call
    ``deleteLater()`` in fixture teardown without spinning the
    loop afterwards — those C++ objects then linger past the
    test, and when the next test's fixture setup triggers Python
    GC the stale Python wrappers ask the now-half-dead C++ side
    a question and segfault inside the GC pass. The traceback
    shows up as "Garbage-collecting" / "Windows fatal exception:
    access violation" with no obvious test responsible.

    This autouse fixture drains all queued ``DeferredDelete``
    events after every test, so the C++ side is fully freed
    before the next test starts. Cheap (a no-op in tests that
    didn't touch Qt) and prevents the cross-test contamination
    centrally rather than requiring each Qt fixture to remember
    to call ``sendPostedEvents`` itself.

    A ``gc.collect()`` after the drain was tried and rejected:
    full collection added ~350 ms per test (suite went from 3 min
    to 42 min), and ``gc.collect(0)`` happened to disturb the
    Windows clipboard state on a handful of tests. The drain
    alone — without forcing Python GC — has handled every
    reported crash so far.
    """
    yield
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
    except ImportError:
        return
    if QCoreApplication.instance() is None:
        return
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def _restore_app_appearance():
    """Put back the QApplication font and stylesheet a test changed (see ``tests/_app_appearance.py``)."""
    from tests._app_appearance import app_appearance_restored
    with app_appearance_restored():
        yield


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory."""
    return tmp_path


@pytest.fixture
def sample_rgb_array():
    """Create a simple 100x80 RGB numpy array."""
    return _rng.integers(0, 256, (80, 100, 3), dtype=np.uint8)


@pytest.fixture
def sample_rgba_array():
    """Create a simple 100x80 RGBA numpy array."""
    return _rng.integers(0, 256, (80, 100, 4), dtype=np.uint8)


@pytest.fixture
def sample_grayscale_array():
    """Create a simple 100x80 grayscale numpy array."""
    return _rng.integers(0, 256, (80, 100), dtype=np.uint8)


@pytest.fixture
def sample_png(tmp_path):
    """Create a temporary PNG image file."""
    path = tmp_path / "test_image.png"
    img = Image.fromarray(_rng.integers(0, 256, (64, 64, 3), dtype=np.uint8))
    img.save(str(path))
    return str(path)


@pytest.fixture
def sample_jpeg(tmp_path):
    """Create a temporary JPEG image file."""
    path = tmp_path / "test_image.jpg"
    img = Image.fromarray(_rng.integers(0, 256, (64, 64, 3), dtype=np.uint8))
    img.save(str(path))
    return str(path)


@pytest.fixture
def sample_grayscale_png(tmp_path):
    """Create a temporary grayscale PNG image file."""
    path = tmp_path / "gray_image.png"
    arr = _rng.integers(0, 256, (64, 64), dtype=np.uint8)
    img = Image.fromarray(arr, mode="L")
    img.save(str(path))
    return str(path)


@pytest.fixture
def sample_gif(tmp_path):
    """Create a temporary animated GIF file with 3 frames."""
    path = tmp_path / "anim.gif"
    frames = []
    for i in range(3):
        arr = np.full((32, 32, 3), i * 80, dtype=np.uint8)
        frames.append(Image.fromarray(arr))
    frames[0].save(
        str(path), save_all=True, append_images=frames[1:],
        duration=100, loop=0,
    )
    return str(path)


def _format_for_name(name: str) -> str:
    if name.endswith(".png"):
        return "PNG"
    if name.endswith(".jpg"):
        return "JPEG"
    return "BMP"


@pytest.fixture
def image_folder(tmp_path):
    """Create a temporary folder with several test images."""
    names = ["alpha.png", "beta.jpg", "gamma.png", "delta.bmp"]
    for name in names:
        p = tmp_path / name
        arr = _rng.integers(0, 256, (32, 32, 3), dtype=np.uint8)
        img = Image.fromarray(arr)
        fmt = _format_for_name(name)
        if fmt == "JPEG":
            img = img.convert("RGB")
        img.save(str(p), format=fmt)
    return str(tmp_path)


@pytest.fixture(autouse=True)
def isolate_settings(tmp_path, monkeypatch):
    from rigora.system import settings
    monkeypatch.setenv("RIGORA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RIGORA_SETTINGS_PATH", str(tmp_path / "settings.json"))
    settings.configure(tmp_path / "settings.json", autosave=False)
    yield
    settings.cancel_pending_save()
