"""Rigora command line. Headless commands do not initialize the GUI.

Exit status: 0 success, 1 failed operation, 2 usage error, 3 the output
exists (pass ``--overwrite``), 4 a required capability (OpenGL, an encoder)
is missing, 130 cancelled. Results go to standard output as JSON; with
``--json`` a failure is also a JSON object on standard output
(``{"error": {"code", "message"}}``) and diagnostics stay on standard error.
"""

from __future__ import annotations

import argparse
import json
import sys
from io import TextIOWrapper
from pathlib import Path

from rigora.command_ops import EXIT_CANCELLED, EXIT_FAILED, CommandError
from rigora.command_registry import COMMANDS

_POSITIONAL = {"path", "source"}


def _json_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"expected JSON, got {text!r}") from exc


def _add_option(sub: argparse.ArgumentParser, key: str, field: dict, required: bool) -> None:
    if key in _POSITIONAL:
        sub.add_argument(key)
        return
    flag = "--" + key.replace("_", "-")
    kind = field.get("type")
    if kind == "boolean":
        default = field.get("default", False)
        sub.add_argument(flag, dest=key, action=argparse.BooleanOptionalAction, default=default)
        return
    options = {"dest": key, "required": required and "default" not in field}
    options["type"] = {"integer": int, "number": float, "array": _json_value,
                       "object": _json_value}.get(kind, str)
    if "default" in field:
        options["default"] = field["default"]
    if "enum" in field:
        options["choices"] = field["enum"]
    sub.add_argument(flag, **options)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rigora")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("editor", help="open the Rigora editor").add_argument("path", nargs="?")
    subparsers.add_parser("mcp", help="serve MCP on standard input/output")
    for name, command in COMMANDS.items():
        sub = subparsers.add_parser(name.replace("_", "-"), help=command["description"])
        schema = command["input_schema"]
        for key, field in schema["properties"].items():
            _add_option(sub, key, field, key in schema.get("required", []))
        sub.add_argument(
            "--json", action="store_true",
            help="emit JSON for failures too (path commands also wrap results in a list)")
        if command.get("long_running"):
            sub.add_argument("--progress", action="store_true",
                             help="print 'progress N/TOTAL' lines on standard error")
            sub.add_argument("--cancel-file", dest="cancel_file",
                             help="stop and clean up when this file appears")
    return parser


def _report_error(error: CommandError, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"error": error.to_dict()}, ensure_ascii=False))
    print(f"{error.code}: {error}", file=sys.stderr)
    return error.exit_code


def _long_running_hooks(values: dict) -> None:
    show_progress = values.pop("progress", False)
    cancel_file = values.pop("cancel_file", None)
    if show_progress:
        values["progress"] = lambda done, total: print(f"progress {done}/{total}",
                                                       file=sys.stderr, flush=True)
    if cancel_file:
        values["cancelled"] = lambda: Path(cancel_file).exists()


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
    as_json = values.pop("json")
    as_list = as_json and "path" in values
    command = COMMANDS[name.replace("-", "_")]
    if command.get("long_running"):
        _long_running_hooks(values)
    values = {k: v for k, v in values.items() if v is not None}
    try:
        result = command["handler"](**values)
    except CommandError as error:
        return _report_error(error, as_json)
    except (OSError, ValueError) as error:
        return _report_error(CommandError("failed", str(error), EXIT_FAILED), as_json)
    except KeyboardInterrupt:
        return _report_error(CommandError("cancelled", "cancelled", EXIT_CANCELLED), as_json)
    except Exception as error:   # noqa: BLE001 - e.g. the export's cancellation signal
        if type(error).__name__ == "ExportCancelledError":
            return _report_error(CommandError("cancelled", "cancelled", EXIT_CANCELLED),
                                 as_json)
        raise
    print(json.dumps([result] if as_list else result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
