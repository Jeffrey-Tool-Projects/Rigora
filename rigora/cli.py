"""Rigora command line. Headless commands do not initialize the GUI."""

from __future__ import annotations

import argparse
import json
import sys
from io import TextIOWrapper

from rigora.command_registry import COMMANDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rigora")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("editor", help="open the Rigora editor").add_argument("path", nargs="?")
    subparsers.add_parser("mcp", help="serve MCP on standard input/output")
    for name, command in COMMANDS.items():
        sub = subparsers.add_parser(name.replace("_", "-"), help=command["description"])
        schema = command["input_schema"]
        for key, field in schema["properties"].items():
            flags = {} if key in {"path", "source"} else {"dest": key}
            if key not in {"path", "source"}:
                flags["required"] = key in schema.get("required", [])
            flags["type"] = int if field["type"] == "integer" else str
            if "default" in field:
                flags["default"] = field["default"]
            if "enum" in field:
                flags["choices"] = field["enum"]
            sub.add_argument(
                key if key in {"path", "source"} else "--" + key.replace("_", "-"), **flags
            )
        sub.add_argument(
            "--json", action="store_true", help="emit a JSON report list for path commands"
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    values = vars(build_parser().parse_args(argv))
    name = values.pop("command")
    if name == "editor":
        from rigora.app import main as open_editor

        return open_editor([values["path"]] if values["path"] else [])
    if name == "mcp":
        from rigora.mcp_server import main as serve

        return serve()
    as_list = values.pop("json") and "path" in values
    try:
        result = COMMANDS[name.replace("-", "_")]["handler"](**values)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps([result] if as_list else result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
