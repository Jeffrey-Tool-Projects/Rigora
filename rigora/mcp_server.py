"""Line-delimited JSON-RPC transport for Rigora's headless tools.

Every registered command is a tool. Failures come back as ``isError`` with a
``structuredContent.error`` object carrying a stable ``code``. Long commands
can also run as jobs: ``job_start`` returns a job id at once, ``job_status``
reports progress, ``job_cancel`` stops it and removes partial output, and
``job_result`` returns the outcome. Repeating a ``request_id`` returns the
same job rather than running the command again.
"""

from __future__ import annotations

import json
import sys
from io import TextIOWrapper
from typing import Any

from rigora.command_ops import CommandError
from rigora.command_registry import COMMANDS
from rigora.puppet.schema_check import validate

_JOB_TOOLS = {
    "job_start": {
        "description": "Start a command as a background job; returns its job id.",
        "input_schema": {"type": "object", "properties": {
            "command": {"type": "string", "enum": sorted(COMMANDS)},
            "arguments": {"type": "object"},
            "request_id": {"type": "string"}}, "required": ["command"]},
    },
    "job_status": {
        "description": "State and frame progress of a job.",
        "input_schema": {"type": "object", "properties": {"job_id": {"type": "string"}},
                         "required": ["job_id"]},
    },
    "job_cancel": {
        "description": "Cancel a running job; its partial output is removed.",
        "input_schema": {"type": "object", "properties": {"job_id": {"type": "string"}},
                         "required": ["job_id"]},
    },
    "job_result": {
        "description": "The result or error of a finished job.",
        "input_schema": {"type": "object", "properties": {"job_id": {"type": "string"}},
                         "required": ["job_id"]},
    },
}
_jobs = None


def _job_manager():
    global _jobs
    if _jobs is None:
        from rigora.command_jobs import JobManager
        _jobs = JobManager()
    return _jobs


def _run_job_tool(name: str, arguments: dict) -> dict:
    manager = _job_manager()
    if name == "job_start":
        command = arguments["command"]
        inner = arguments.get("arguments", {})
        problems = validate(inner, {**COMMANDS[command]["input_schema"],
                                    "additionalProperties": False})
        if problems:
            raise CommandError("invalid_input", "; ".join(problems))
        return manager.start(command, inner, arguments.get("request_id"))
    return {"job_status": manager.status, "job_cancel": manager.cancel,
            "job_result": manager.result}[name](arguments["job_id"])


def _error_result(error: CommandError) -> dict:
    return {"content": [{"type": "text", "text": str(error)}],
            "structuredContent": {"error": error.to_dict()}, "isError": True}

PROTOCOL_VERSION = "2025-03-26"


class RequestError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _invoke(params: dict) -> dict:
    name = params.get("name")
    if not isinstance(name, str) or (name not in COMMANDS and name not in _JOB_TOOLS):
        raise RequestError(-32602, "Unknown tool name")
    command = COMMANDS.get(name) or _JOB_TOOLS[name]
    arguments = params.get("arguments", {})
    schema = {**command["input_schema"], "additionalProperties": False}
    problems = validate(arguments, schema)
    if problems:
        raise RequestError(-32602, "; ".join(problems))
    try:
        if name in _JOB_TOOLS:
            value = _run_job_tool(name, arguments)
        else:
            value = command["handler"](**arguments)
    except CommandError as error:
        return _error_result(error)
    except (OSError, ValueError) as error:
        return _error_result(CommandError("failed", str(error)))
    return {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
        "structuredContent": value,
        "isError": False,
    }


def _dispatch(method: str, params: dict) -> dict:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "rigora", "version": "0.1.1"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": name,
                    "description": item["description"],
                    "inputSchema": item["input_schema"],
                }
                for name, item in {**COMMANDS, **_JOB_TOOLS}.items()
            ]
        }
    if method == "tools/call":
        return _invoke(params)
    raise RequestError(-32601, "Method not found")


def handle_message(message: Any) -> dict | None:
    msg_id = message.get("id") if isinstance(message, dict) else None
    try:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise RequestError(-32600, "Invalid Request")
        if not isinstance(message.get("method"), str):
            raise RequestError(-32600, "method must be a string")
        params = message.get("params", {})
        if not isinstance(params, dict):
            raise RequestError(-32602, "params must be an object")
        if "id" not in message:
            return None
        if isinstance(msg_id, bool) or not isinstance(msg_id, (str, int, type(None))):
            msg_id = None
            raise RequestError(-32600, "Invalid request id")
        result = _dispatch(message["method"], params)
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    except RequestError as error:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": error.code, "message": str(error)},
        }


def main() -> int:
    # MCP stdio is UTF-8 even when the host's redirected streams use a locale codec.
    for stream in (sys.stdin, sys.stdout):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        try:
            response = handle_message(json.loads(line))
        except json.JSONDecodeError:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
