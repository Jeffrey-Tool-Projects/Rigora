---
title: Reference
description: Command-line operations, optional dependencies, archive schemas, and settings locations.
permalink: /reference/
---

## Command-line operations

The `rigora` executable is installed into the active Python environment.

| Command | Result |
| --- | --- |
| `rigora editor [path]` | Opens the editor, optionally with a `.puppet` document. |
| `rigora puppet-from-png SOURCE --destination DESTINATION` | Creates a rig from a PNG. `--cell-size` defaults to 64. |
| `rigora puppet-inspect PATH` | Reports geometry, parameters, motions, expressions, parts, and physics. |
| `rigora puppet-validate PATH --json` | Checks schemas, archive structure, and rig consistency. |
| `rigora puppet-schema --name NAME` | Prints a schema. Names are `puppet`, `motion`, `expression`, and `physics`. |
| `rigora mcp` | Starts the MCP server on standard input and output. |

Run `rigora --help` or add `--help` after a command for its arguments.
`python -m rigora` and `rigora-editor` start the GUI. The four model operations
are headless and do not initialize Qt or OpenGL.

## MCP tools

`rigora-mcp` starts the same server as `rigora mcp`. Configure a client to launch
the executable from the environment where Rigora is installed.

| Tool | Required inputs |
| --- | --- |
| `puppet_from_png` | `source`, `destination` |
| `puppet_inspect` | `path` |
| `puppet_validate` | `path` |
| `puppet_schema` | None. Optional `name` defaults to `puppet`. |

The server communicates over standard input and output rather than opening a
network listener. The CLI and MCP share their operation definitions.

## Optional features

| Extra | Packages | Use |
| --- | --- | --- |
| `gui` | PySide6, PyOpenGL, imageio, imageio-ffmpeg | Editor and rendered output |
| `webcam` | opencv-python, mediapipe | Face tracking |
| `lipsync` | sounddevice | Microphone lip-sync |
| `virtual-camera` | pyvirtualcam | Virtual camera output |
| `ndi` | ndi-python | NDI output |
| `hotkeys` | pynput | Global hotkeys |
| `dev` | Test, lint, build, security, and GUI dependencies | Repository development |

The base package requires Python 3.11+, NumPy, and Pillow. Installing an extra
does not replace operating-system drivers, permissions, or external software
required by a feature. Exact dependency constraints are in
[`pyproject.toml`](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/pyproject.toml).

## The `.puppet` archive

A `.puppet` file packages the manifest, textures, motion, expressions, and
physics data. The
[format specification](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/rigora/puppet/FORMAT.md)
defines the archive and its versioned fields.

Published schema files are available here:

- [Puppet manifest schema]({{ '/schemas/puppet.schema.json' | relative_url }})
- [Motion schema]({{ '/schemas/motion.schema.json' | relative_url }})
- [Expression schema]({{ '/schemas/expression.schema.json' | relative_url }})
- [Physics schema]({{ '/schemas/physics.schema.json' | relative_url }})

The [standalone reader example]({{ '/examples/read_puppet.py' | relative_url }})
shows how to inspect an archive without the GUI.

## Settings and packaged resources

| Name | Purpose |
| --- | --- |
| `RIGORA_DATA_DIR` | Overrides the writable application-data directory. |
| `RIGORA_SETTINGS_PATH` | Overrides the settings file path. |
| `rigora.system.app_paths.examples_dir()` | Returns the installed example directory. |

By default, writable data uses `%LOCALAPPDATA%/Rigora` on Windows,
`~/Library/Application Support/Rigora` on macOS, and
`$XDG_DATA_HOME/Rigora` or `~/.local/share/Rigora` on Linux.
Packaged examples are separate from writable settings and cached models.
