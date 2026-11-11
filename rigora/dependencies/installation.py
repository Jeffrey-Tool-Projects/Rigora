"""Exclude simultaneous pip writes to the same interpreter environment."""
from contextlib import contextmanager
from threading import RLock

_lock = RLock()
_active: set[str] = set()


@contextmanager
def resource_reservation(key: str):
    with _lock:
        if key in _active:
            raise FileExistsError(f"Installation already in progress: {key}")
        _active.add(key)
    try:
        yield
    finally:
        with _lock:
            _active.discard(key)
