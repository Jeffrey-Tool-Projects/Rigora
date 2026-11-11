"""Public command behavior and stdio protocol boundaries."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from PIL import Image

from rigora import commands
from rigora.cli import main
from rigora.mcp_server import handle_message


def test_png_command_roundtrip(tmp_path, capsys):
    source, target = tmp_path / "part.png", tmp_path / "part.puppet"
    Image.new("RGBA", (32, 24), (10, 30, 70, 255)).save(source)
    assert (
        main(["puppet-from-png", str(source), "--destination", str(target), "--cell-size", "8"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["canvas_size"] == [32, 24]
    assert commands.puppet_inspect(str(target))["drawables"]
    assert commands.puppet_validate(str(target))["valid"]


@pytest.mark.parametrize("path", ["", None, 123, "missing.puppet"])
def test_invalid_input_paths_fail(path):
    with pytest.raises(ValueError):
        commands.puppet_inspect(path)


@pytest.mark.parametrize(
    "message,code",
    [
        ([], -32600),
        ({"jsonrpc": "2.0", "id": 1, "method": "missing"}, -32601),
        ({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": []}, -32602),
        ({"jsonrpc": "2.0", "id": True, "method": "ping"}, -32600),
        ({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": []}}, -32602),
        (
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "puppet_from_png",
                    "arguments": {"source": "a", "destination": "b", "cell_size": True},
                },
            },
            -32602,
        ),
    ],
)
def test_invalid_requests_report_protocol_errors(message, code):
    assert handle_message(message)["error"]["code"] == code


def test_stdio_handshake_and_tool_call():
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "puppet_schema", "arguments": {"name": "motion"}},
        },
    ]
    result = subprocess.run(
        [sys.executable, "-m", "rigora.mcp_server"],
        input="\n".join(map(json.dumps, messages)) + "\n",
        text=True,
        capture_output=True,
        timeout=20,
        check=True,
    )
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert responses[0]["result"]["serverInfo"]["name"] == "rigora"
    assert len(responses[1]["result"]["tools"]) == 4
    assert responses[2]["result"]["structuredContent"]["name"] == "motion"


def test_tool_failures_are_visible():
    result = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "puppet_inspect", "arguments": {"path": "missing.puppet"}},
        }
    )
    assert result["result"]["isError"] is True
    assert "does not exist" in result["result"]["content"][0]["text"]


def test_mcp_uses_utf8_for_paths_and_survives_unicode_tool_error(tmp_path):
    source, target = tmp_path / "狐狸🦊.png", tmp_path / "狐狸🦊.puppet"
    Image.new("RGBA", (16, 24), (10, 30, 70, 255)).save(source)
    missing = tmp_path / "不存在🦊.puppet"
    calls = [
        ("puppet_from_png", {"source": str(source), "destination": str(target)}),
        ("puppet_inspect", {"path": str(target)}),
        ("puppet_inspect", {"path": str(missing)}),
        ("puppet_inspect", {"path": str(target)}),
    ]
    messages = [
        {
            "jsonrpc": "2.0",
            "id": index,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        for index, (name, arguments) in enumerate(calls)
    ]
    # Mix raw UTF-8 and JSON escapes: both must address the same real filename.
    payload = (
        "\n".join(
            json.dumps(message, ensure_ascii=index % 2 == 1)
            for index, message in enumerate(messages)
        )
        + "\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "rigora.mcp_server"],
        input=payload.encode("utf-8"),
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp950"},
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    responses = [json.loads(line)["result"] for line in result.stdout.decode("utf-8").splitlines()]
    assert len(responses) == 4
    assert responses[0]["structuredContent"]["destination"] == str(target)
    assert responses[1]["structuredContent"]["path"] == str(target)
    assert responses[2]["isError"] is True
    assert str(missing) in responses[2]["content"][0]["text"]
    assert responses[3]["structuredContent"]["size"] == [16, 24]


def test_cli_outputs_utf8_json_and_errors_under_legacy_locale(tmp_path):
    source, target = tmp_path / "狐狸🦊.png", tmp_path / "狐狸🦊.puppet"
    Image.new("RGBA", (16, 24), (10, 30, 70, 255)).save(source)
    environment = {**os.environ, "PYTHONIOENCODING": "cp950"}
    converted = subprocess.run(
        [
            sys.executable,
            "-m",
            "rigora.cli",
            "puppet-from-png",
            str(source),
            "--destination",
            str(target),
        ],
        capture_output=True,
        env=environment,
        timeout=20,
        check=False,
    )
    assert converted.returncode == 0, converted.stderr.decode("utf-8", errors="replace")
    assert json.loads(converted.stdout.decode("utf-8"))["destination"] == str(target)
    missing = tmp_path / "不存在🦊.puppet"
    failed = subprocess.run(
        [sys.executable, "-m", "rigora.cli", "puppet-inspect", str(missing)],
        capture_output=True,
        env=environment,
        timeout=20,
        check=False,
    )
    assert failed.returncode == 1
    assert str(missing) in failed.stderr.decode("utf-8")
    assert "Traceback" not in failed.stderr.decode("utf-8")
