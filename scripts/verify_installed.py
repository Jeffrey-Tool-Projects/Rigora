"""Run with the installed wheel's interpreter from outside the source checkout."""

from __future__ import annotations
import importlib.util
import json
import os
import platform
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from importlib.metadata import version


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    if importlib.util.find_spec("Imervue") is not None:
        raise RuntimeError("Verification requires an environment without Imervue")
    import rigora
    package = Path(rigora.__file__).resolve().parent
    sys.dont_write_bytecode = True

    def deny_package_writes(event, args):
        if event == "open" and isinstance(args[0], (str, bytes)):
            flags = args[2]
            writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            if writing and Path(os.fsdecode(args[0])).resolve().is_relative_to(package):
                raise PermissionError("Installed Rigora package is read-only during verification")
    sys.addaudithook(deny_package_writes)
    try:
        (package / "write-probe").write_bytes(b"denied")
    except PermissionError:
        pass
    else:
        raise RuntimeError("Package write protection was not enforced")
    from PIL import Image
    from rigora.commands import puppet_from_png, puppet_inspect, puppet_schema, puppet_validate
    from rigora.puppet.document_io import load_puppet, save_puppet
    from rigora.puppet.document_session import DocumentSession
    from rigora.puppet.runtime import compose_all_drawables, default_parameter_values
    from rigora.desktop_pet.pet_script import load_script
    from rigora.mcp_server import handle_message

    resources = files("rigora") / "resources"
    example = resources / "examples/puppet/imeru.puppet"
    document = load_puppet(Path(str(example)))
    vertices = compose_all_drawables(document, default_parameter_values(document))
    check(
        vertices and len(vertices) == len(document.drawables),
        "vertices and len(vertices) == len(document.drawables)",
    )
    load_script(Path(str(resources / "examples/desktop_pet/imeru.petscript.json")))
    for name in ("puppet", "motion", "expression", "physics"):
        published = json.loads((resources / f"schemas/{name}.schema.json").read_text())
        check(
            puppet_schema(name)["schema"] == published, "puppet_schema(name)['schema'] == published"
        )
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        source = root / "source.png"
        destination = root / "converted.puppet"
        Image.new("RGBA", (32, 32), (120, 60, 30, 255)).save(source)
        puppet_from_png(str(source), str(destination), cell_size=8)
        check(
            puppet_validate(str(destination))["valid"], "puppet_validate(str(destination))['valid']"
        )
        check(
            puppet_inspect(str(destination))["size"] == [32, 32],
            "puppet_inspect(str(destination))['size'] == [32, 32]",
        )
        save_puppet(load_puppet(destination), root / "roundtrip.puppet")
        check(
            puppet_validate(str(root / "roundtrip.puppet"))["valid"],
            "puppet_validate(str(root / 'roundtrip.puppet'))['valid']",
        )
        session = DocumentSession()
        session.bind(load_puppet(destination), saved=True)
        with session.transaction("Resize") as edited:
            edited.size = (64, 32)
        check(session.dirty and session.undo(), "Headless editor undo failed")
        check(session.document.size == (32, 32) and not session.dirty, "Save point was lost")
        check(session.redo(), "Headless editor redo failed")
        session.save(root / "session.puppet")
        check(puppet_validate(str(session.path))["valid"], "Edited document is invalid")
        from rigora.command_ops import rig_doctor
        check("findings" in rig_doctor(str(destination)), "rig_doctor runs headless")
    response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = {tool["name"] for tool in response["result"]["tools"]}
    check({"puppet_from_png", "puppet_inspect", "puppet_validate", "puppet_schema",
           "psd_preview", "rig_doctor", "export_animation", "job_start", "job_result"} <= tools,
          f"MCP tools: {sorted(tools)}")
    from rigora import host_api
    check(host_api.require(1) == host_api.API_VERSION, "host API 1.x")
    check(
        not any(name.startswith(("Imervue", "PySide6", "OpenGL")) for name in sys.modules),
        "not any((name.startswith(('Imervue', 'PySide6', 'OpenGL')) for name in sys.modules))",
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "package": str(Path(rigora.__file__).resolve()),
                "example_drawables": len(vertices),
                "host_installed": False,
                "gui_imported": False,
                "headless_edit_history": True,
                "version": version("rigora"),
                "python": sys.version,
                "platform": platform.platform(),
                "package_python_writes_denied": True,
                "optional_available": {
                    name: importlib.util.find_spec(name) is not None
                    for name in ("PySide6", "cv2", "mediapipe", "sounddevice", "pyvirtualcam")
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
