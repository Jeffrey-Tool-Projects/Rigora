"""Shared operation descriptors for CLI and MCP."""

from rigora.commands import puppet_from_png, puppet_inspect, puppet_validate, puppet_schema

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
    ]
}
