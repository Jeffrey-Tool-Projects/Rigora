"""Headless operations shared by the CLI, MCP and embedding applications."""
from pathlib import Path
from typing import Any


def validated_file(path: str) -> Path:
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise ValueError(f"file {candidate} does not exist")
    return candidate


def puppet_from_png(
    source: str,
    destination: str,
    *,
    cell_size: int = 64,
) -> dict[str, Any]:
    """Run the Rigora PNG → ``.puppet`` import on ``source``
    and save the resulting document to ``destination``.

    Wraps :func:`rigora.puppet.auto_mesh.puppet_from_png` +
    :func:`rigora.puppet.document_io.save_puppet`."""
    src = validated_file(source)
    dst = Path(destination)
    if not dst.parent.exists():
        raise ValueError(f"destination parent {dst.parent} does not exist")
    from rigora.puppet.auto_mesh import puppet_from_png as build_puppet
    from rigora.puppet.document_io import save_puppet
    doc = build_puppet(src, cell_size=int(cell_size))
    save_puppet(doc, dst)
    drawable = doc.drawables[0]
    return {
        "destination": str(dst),
        "canvas_size": list(doc.size),
        "vertex_count": len(drawable.vertices),
        "triangle_count": len(drawable.indices) // 3,
        "parameter_count": len(doc.parameters),
    }


def puppet_inspect(path: str) -> dict[str, Any]:
    """Open a ``.puppet`` archive and return its top-level inventory:
    parameters, deformers, motions, expressions, hit areas, parts."""
    src = validated_file(path)
    from rigora.puppet.document_io import load_puppet
    doc = load_puppet(src)
    return {
        "path": str(src),
        "size": list(doc.size),
        "drawables": [d.id for d in doc.drawables],
        "deformers": [{"id": d.id, "type": d.type} for d in doc.deformers],
        "parameters": [
            {"id": p.id, "min": p.min, "max": p.max, "default": p.default,
             "key_count": len(p.keys)}
            for p in doc.parameters
        ],
        "motions": [
            {"name": m.name, "duration": m.duration, "loop": m.loop, "group": m.group}
            for m in doc.motions
        ],
        "expressions": [e.name for e in doc.expressions],
        "hit_areas": [h.id for h in doc.hit_areas],
        "parts": [p.id for p in doc.parts],
        "parameter_blends": [b.id for b in doc.parameter_blends],
        "physics_rigs": [r.id for r in doc.physics_rigs],
    }


def puppet_validate(path: str) -> dict[str, Any]:
    """Check a ``.puppet`` file against the v1 format: its JSON Schemas, the
    loader's structural rules and the rig checks (``rigora.puppet.format_schema``)."""
    from rigora.puppet.format_schema import check_puppet_file
    return check_puppet_file(validated_file(path))


def puppet_schema(name: str = "puppet") -> dict[str, Any]:
    """Return the published JSON Schema of one ``.puppet`` file kind
    (``puppet``, ``motion``, ``expression`` or ``physics``)."""
    from rigora.puppet.format_schema import SCHEMA_URLS, SCHEMAS
    if name not in SCHEMAS:
        raise ValueError(f"name must be one of {sorted(SCHEMAS)}, got {name!r}")
    return {"name": name, "url": SCHEMA_URLS[name], "schema": SCHEMAS[name]}
