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
| `rigora psd-preview SOURCE` | Lists a PSD's layers and every feature an import cannot carry over. |
| `rigora puppet-from-psd SOURCE --destination DESTINATION` | Imports a layered PSD as a rig and reports the differences. `--no-auto-rig` skips the automatic rig. |
| `rigora cubism-preview PATH [--against RIG]` | Previews a Cubism `.model3.json` import without the Cubism SDK. |
| `rigora rig-doctor PATH [--fixes JSON] [--destination OUT]` | Diagnoses a rig. With `--fixes '["safe"]'` (or finding ids) it previews the repairs, and with `--destination` applies and saves them. |
| `rigora update-art PATH --psd PSD [--destination OUT]` | Plans an art update from a re-exported PSD; with `--destination` applies it. `--actions` and `--mapping` take JSON objects. |
| `rigora motion-compress PATH --motion NAME --destination OUT` | Drops redundant keys; `--tolerance` is a percentage of each parameter's range (0–25, default 1). |
| `rigora bake-composition PATH --composition NAME --destination OUT` | Bakes a composition into a new motion; `--fps` defaults to 30. |
| `rigora export-animation PATH --destination OUT (--motion NAME \| --composition NAME)` | Renders offline: `--format png_sequence\|gif\|mp4\|webm`, `--width`, `--height`, `--fps`, `--start`, `--end`, `--no-transparent`, `--physics-warmup`. Needs a desktop OpenGL context; video needs ffmpeg. `--progress` prints `progress N/TOTAL` on standard error and `--cancel-file PATH` stops the export when that file appears. |
| `rigora mcp` | Starts the MCP server on standard input and output. |

Run `rigora --help` or add `--help` after a command for its arguments.
`python -m rigora` and `rigora-editor` start the GUI. The model operations are
headless and do not initialize Qt or OpenGL; only `export-animation` renders.

Every command writes only to the `--destination` it is given. An existing file
is kept unless `--overwrite` is passed, and files are written atomically, so a
failed or cancelled command leaves the previous file untouched. Results are
JSON on standard output; diagnostics go to standard error. With `--json` a
failure is also printed as `{"error": {"code": ..., "message": ...}}`.

| Exit status | Meaning | Error code |
| --- | --- | --- |
| 0 | Success | — |
| 1 | The operation failed | `failed`, `invalid_input`, `not_found` |
| 2 | Wrong command-line usage | — |
| 3 | The destination exists; pass `--overwrite` | `output_exists` |
| 4 | A needed capability is missing (OpenGL context, video encoder) | `capability_missing` |
| 130 | Cancelled | `cancelled` |

## MCP tools

`rigora-mcp` starts the same server as `rigora mcp`. Configure a client to launch
the executable from the environment where Rigora is installed.

| Tool | Required inputs |
| --- | --- |
| `puppet_from_png` | `source`, `destination` |
| `puppet_inspect` | `path` |
| `puppet_validate` | `path` |
| `puppet_schema` | None. Optional `name` defaults to `puppet`. |
| `psd_preview`, `puppet_from_psd`, `cubism_preview`, `rig_doctor`, `update_art`, `motion_compress`, `bake_composition`, `export_animation` | The same inputs as the commands above, by their long option names |
| `job_start` | `command`; optional `arguments` and `request_id` |
| `job_status`, `job_cancel`, `job_result` | `job_id` |

The server communicates over standard input and output rather than opening a
network listener. The CLI and MCP share their operation definitions and their
input schemas. A failed tool call returns `isError` with
`structuredContent.error.code` set to one of the error codes above.

Long work, such as `export_animation`, can run as a job: `job_start` returns a
`job_id` at once and runs the command in its own process; `job_status` reports
frame progress; `job_cancel` stops it and removes partial output; `job_result`
returns the result or error. Starting again with the same `request_id` returns
the existing job instead of running the command — and its writes — twice.

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
