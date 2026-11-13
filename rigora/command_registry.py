"""Shared operation descriptors for CLI and MCP."""

from rigora import command_ops
from rigora.commands import puppet_from_png, puppet_inspect, puppet_validate, puppet_schema

_STR = {"type": "string"}
_BOOL_FALSE = {"type": "boolean", "default": False}
_OUT = {"destination": _STR, "overwrite": _BOOL_FALSE}

COMMANDS = {
    item["name"]: item
    for item in [
        {
            "name": "puppet_from_png",
            "description": "Build an animated .puppet rig from a PNG with standard parameters.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                    "cell_size": {"type": "integer", "minimum": 4, "maximum": 1024, "default": 64},
                },
                "required": ["source", "destination"],
            },
            "handler": puppet_from_png,
        },
        {
            "name": "puppet_inspect",
            "description": "Inspect rig geometry, animation, expressions, parts and physics.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            "handler": puppet_inspect,
        },
        {
            "name": "puppet_validate",
            "description": "Validate archive schemas, structure and rig consistency.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            "handler": puppet_validate,
        },
        {
            "name": "puppet_schema",
            "description": "Return the published JSON Schema for a .puppet member type.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": ["puppet", "motion", "expression", "physics"],
                        "default": "puppet",
                    }
                },
                "required": [],
            },
            "handler": puppet_schema,
        },
        {
            "name": "psd_preview",
            "description": "List a PSD's layers and every feature an import cannot carry over.",
            "input_schema": {"type": "object", "properties": {"source": _STR},
                             "required": ["source"]},
            "handler": command_ops.psd_preview,
        },
        {
            "name": "puppet_from_psd",
            "description": "Import a layered PSD as a .puppet rig; reports the differences.",
            "input_schema": {"type": "object", "properties": {
                "source": _STR, **_OUT, "auto_rig": {"type": "boolean", "default": True}},
                "required": ["source", "destination"]},
            "handler": command_ops.puppet_from_psd,
        },
        {
            "name": "cubism_preview",
            "description": "Preview a Cubism .model3.json import without the Cubism SDK.",
            "input_schema": {"type": "object", "properties": {"path": _STR, "against": _STR},
                             "required": ["path"]},
            "handler": command_ops.cubism_preview,
        },
        {
            "name": "rig_doctor",
            "description": "Diagnose a rig; preview or apply fixes (ids, or [\"safe\"]).",
            "input_schema": {"type": "object", "properties": {
                "path": _STR, "fixes": {"type": "array", "items": _STR}, **_OUT},
                "required": ["path"]},
            "handler": command_ops.rig_doctor,
        },
        {
            "name": "update_art",
            "description": "Plan, or apply and save, an art update from a re-exported PSD.",
            "input_schema": {"type": "object", "properties": {
                "path": _STR, "psd": _STR, **_OUT,
                "actions": {"type": "object", "additionalProperties": _STR},
                "mapping": {"type": "object", "additionalProperties": _STR}},
                "required": ["path", "psd"]},
            "handler": command_ops.update_art,
        },
        {
            "name": "motion_compress",
            "description": "Drop redundant keys from a motion and save the rig.",
            "input_schema": {"type": "object", "properties": {
                "path": _STR, "motion": _STR, **_OUT,
                "tolerance": {"type": "number", "minimum": 0, "maximum": 25, "default": 1.0}},
                "required": ["path", "motion", "destination"]},
            "handler": command_ops.motion_compress,
        },
        {
            "name": "bake_composition",
            "description": "Bake a composition into a motion take and save the rig.",
            "input_schema": {"type": "object", "properties": {
                "path": _STR, "composition": _STR, **_OUT,
                "fps": {"type": "number", "minimum": 1, "maximum": 240, "default": 30}},
                "required": ["path", "composition", "destination"]},
            "handler": command_ops.bake_composition,
        },
        {
            "name": "export_animation",
            "description": "Render a motion or composition offline (needs OpenGL; video needs "
                           "ffmpeg).",
            "input_schema": {"type": "object", "properties": {
                "path": _STR, **_OUT, "motion": _STR, "composition": _STR,
                "width": {"type": "integer", "minimum": 16, "maximum": 8192, "default": 1024},
                "height": {"type": "integer", "minimum": 16, "maximum": 8192, "default": 1024},
                "fps": {"type": "number", "minimum": 1, "maximum": 240, "default": 30},
                "start": {"type": "number", "minimum": 0, "default": 0},
                "end": {"type": "number", "minimum": 0},
                "format": {"type": "string", "enum": ["png_sequence", "gif", "mp4", "webm"],
                           "default": "png_sequence"},
                "transparent": {"type": "boolean", "default": True},
                "physics_warmup": {"type": "number", "minimum": 0, "default": 1.0}},
                "required": ["path", "destination"]},
            "handler": command_ops.export_animation,
            "long_running": True,
        },
    ]
}
