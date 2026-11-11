"""Standalone application startup and persistence ownership."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rigora-editor")
    parser.add_argument("path", nargs="?", help=".puppet document to open")
    args = parser.parse_args(argv)
    try:
        from PySide6.QtWidgets import QApplication
        from rigora.editor_window import EditorWindow
    except ImportError as error:
        print(f"Install rigora[gui] to launch the editor: {error}", file=sys.stderr)
        return 1
    from rigora.i18n.language_wrapper import language_wrapper
    from rigora.system.settings import configure, flush, user_setting_dict

    configure()
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("Rigora")
    app.setOrganizationName("Rigora")
    language_wrapper.reset_language(user_setting_dict.get("language", "English"))
    window = EditorWindow()
    app.aboutToQuit.connect(window.shutdown)
    if args.path:
        window.editor.open_puppet(args.path)
    window.show()
    try:
        return app.exec()
    finally:
        window.shutdown()
        flush()
