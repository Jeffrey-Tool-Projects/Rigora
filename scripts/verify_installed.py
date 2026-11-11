"""Run with the installed wheel's interpreter from outside the source checkout."""

from __future__ import annotations
import importlib.util
import json
import sys
import tempfile
from importlib.resources import files
from pathlib import Path


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    if importlib.util.find_spec("Imervue") is not None:
        raise RuntimeError("Verification requires an environment without Imervue")
    from PIL import Image
    from rigora.commands import puppet_from_png, puppet_inspect, puppet_schema, puppet_validate
    from rigora.puppet.document_io import load_puppet, save_puppet
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
    response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    check(len(response["result"]["tools"]) == 4, "len(response['result']['tools']) == 4")
    check(
        not any(name.startswith(("Imervue", "PySide6", "OpenGL")) for name in sys.modules),
        "not any((name.startswith(('Imervue', 'PySide6', 'OpenGL')) for name in sys.modules))",
    )
    import rigora

    print(
        json.dumps(
            {
                "status": "passed",
                "package": str(Path(rigora.__file__).resolve()),
                "example_drawables": len(vertices),
                "host_installed": False,
                "gui_imported": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
