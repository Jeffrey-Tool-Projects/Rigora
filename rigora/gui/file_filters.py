"""File-dialog name filters with translated labels.

A Qt name filter is ``"<label> (<patterns>)"``. The label is shown to the user,
so it comes from the language dictionary; the patterns are code and never do.
"""
from __future__ import annotations

from collections.abc import Iterable

from rigora.i18n.language_wrapper import language_wrapper


def name_filter(label: str, extensions: Iterable[str]) -> str:
    """Return ``"label (*.a *.b)"``; extensions may be given with or without the dot."""
    patterns = " ".join(f"*.{ext.lstrip('.')}" for ext in extensions)
    return f"{label} ({patterns})"


def translated_filter(key: str, default: str, extensions: Iterable[str]) -> str:
    """Return a name filter whose label is the ``key`` translation (``default`` if missing)."""
    return name_filter(language_wrapper.language_word_dict.get(key, default), extensions)


def image_filter(extensions: Iterable[str]) -> str:
    """Return the translated "Images (...)" filter for ``extensions``."""
    return translated_filter("file_filter_images", "Images", extensions)
