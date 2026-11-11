# Rigora architecture

Rigora owns the character animation runtime and desktop-pet implementation.
Imervue and FrontEngine are consumers. No Rigora runtime module imports Imervue.

## Packages and entry points

| Package | Responsibility |
| --- | --- |
| `rigora.puppet` | `.puppet` data model, archives, schemas, animation, rigging, physics, Cubism import, editor, live inputs and outputs |
| `rigora.desktop_pet` | Pet windows, scripts, interaction, global hotkeys, scheduling, settings and integration interfaces |
| `rigora.rendering` | Context-aware OpenGL lifetime and shared pet shadow geometry |
| `rigora.psd` | Read-only PSD layer records and raw/RLE decoding without a Paint document dependency |
| `rigora.system` | Independent settings, paths, atomic writes, timers, job state, local-origin checks and local-LLM transport |
| `rigora.gui` | Editor UI helpers, background jobs, filters, tooltips, icons and scrollable panels |
| `rigora.i18n` | Five built-in language dictionaries and translation validation |
| `rigora.dependencies` | Optional dependency discovery, installation, cancellation and worker retirement |
| `rigora.resources` | Installed example rigs, pet scripts and schemas |
| `rigora.commands` | Four headless operation handlers shared with embedding applications |
| `rigora.command_registry` | CLI and MCP operation metadata |
| `rigora.cli` | `rigora` command line |
| `rigora.mcp_server` | `rigora-mcp` standard-input/output server |
| `rigora.app`, `rigora.editor_window` | Standalone startup, editor and Desktop Pet tabs, language selection and shutdown |

`python -m rigora` opens the standalone application. The `rigora-editor` entry
point does the same. `rigora` exposes headless commands plus `editor` and `mcp`.
Core model and archive imports do not initialize Qt or OpenGL. GUI dependencies
are installed through the `gui` extra; camera, microphone, virtual-camera, NDI
and hotkey integrations have separate extras.

## Ownership and persistence

The application initializes `rigora.system.settings` explicitly before creating
workspaces and flushes it after shutdown. `RIGORA_DATA_DIR` selects the writable
data root; `RIGORA_SETTINGS_PATH` overrides the settings file. Model caches and
optional dependency installations never write into the installed wheel.
`rigora.system.app_paths.examples_dir()` locates installed examples.

An embedding application may import relevant legacy preferences once through
`import_legacy_settings`. It does not share a live settings file with Rigora.
`rigora.gui.background_jobs.set_job_registry` attaches an existing host registry
before jobs are started. Its job-state contract is structural, so callers do
not need to import the host's implementation.

## Cross-project contracts

Imervue retains Puppet and Desktop Pet tabs and its existing CLI/MCP commands.
`Imervue.system.rigora_integration` initializes settings and language, attaches
the host job registry and flushes settings. It shows an installation notice
when the optional package is missing. Imervue owns only this integration;
the animation and pet implementations live here.

FrontEngine uses `rigora.puppet` model/runtime/canvas interfaces and
`rigora.desktop_pet.pet_script`. Existing `.puppet` files and serialized
FrontEngine scene/pet identifiers remain compatible.

The format MIME is still `application/vnd.imervue.puppet+zip`. Existing schema
URLs in Imervue's `docs/schemas/` remain permanent format identifiers. Moving
the implementation and changing the application name do not change those IDs.

## Verification

Feature tests live in this repository. Consumer tests remain with Imervue and
FrontEngine. Installed-wheel checks must run outside either source checkout
without Imervue installed; a passing source-tree import is insufficient.
Offscreen test runs skip tests that require a native OpenGL widget. Native
rendering and shutdown acceptance must be reported separately from those skips.
