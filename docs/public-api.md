# Rigora integration contract

This contract covers Rigora 0.1.1 plus the unreleased R0–R8 worktree changes listed in
[CHANGELOG.md](../CHANGELOG.md). A source checkout or authorized wheel is still required. No
registry release of these changes is claimed. New integrations should start from
`rigora.host_api` (version 1.0), which wraps the entry points below behind a version check.

## Supported entry points

| Interface | Contract |
| --- | --- |
| `rigora.puppet.document` | Qt-free authored dataclasses and format version |
| `rigora.puppet.document_io` | `load_puppet`, `save_puppet`, `new_blank`, `to_zip_bytes`, `from_zip_bytes`; invalid files raise `PuppetFormatError`, storage errors remain `OSError` |
| `rigora.puppet.runtime` | Parameter defaults and drawable composition without a GUI |
| `rigora.puppet.document_session.DocumentSession` | Authored history, save point, selection and revision tokens; independent of Qt |
| `rigora.host_api` | Versioned host interface (API 1.0): `require(major, minor)`, `capabilities()`, settings, language, job registry, workspace creation, `close_workspace`, load/save and `run_command`. New functions raise the minor version; removals or changes raise the major version, and the previous major stays importable for one release. Importable without Qt |
| `rigora.commands` | `puppet_from_png`, `puppet_inspect`, `puppet_validate`, `puppet_schema`; shared CLI/MCP behavior |
| `rigora.command_ops` | Shared operations behind the CLI and MCP tools (PSD/Cubism preview and import, rig doctor, art update, motion compression, composition bake, offline export). Failures raise `CommandError` with `code` and `exit_code` |
| `rigora.command_jobs.JobManager` | Runs a command in a child process with a job id, progress, cancel and idempotent `request_id` |
| `rigora.puppet.psd_import` | `plan_psd_import(path)` decodes once and returns a plan whose `preview` lists layers, groups and differences and whose `build()` creates the document; `preview_psd`, `puppet_from_psd` keep the one-step form. `ValueError`/`OSError` for unreadable files |
| `rigora.puppet.cubism_preview` | `preview_cubism_model(path, document=None, sdk_library=None)` reads only Cubism JSON; never loads the SDK. `CubismFormatError` for an unreadable manifest |
| `rigora.puppet.asset_update` | `plan_asset_update`, `apply_asset_update` (validates before mutating; `ValueError` for blocked, impossible or stale plans), `find_missing_textures`, `locate_textures`, `preview_relink`, `relink_texture` |
| `rigora.puppet.workspace.PuppetWorkspace` | Open/import/save operations, `canvas()`, docks, input/idle controllers, `confirm_discard_changes()`, `shutdown()`; `last_import_preview`, `plan_art_update`, `apply_art_update`, `relink_textures` (each applied change is one undoable transaction) |
| `rigora.puppet.canvas.PuppetCanvas` | Bind document, set live parameters, expressions/pose, render; direct binding is a low-level consumer operation, not a file-open confirmation flow |
| `rigora.puppet.motion_player.MotionPlayer` | Bind/play/pause/seek/stop and shutdown |
| `rigora.puppet.idle_driver.IdleDriver`, `input_engine.InputEngine` | Explicit controller lifecycle, never automatically enable camera/microphone |
| `rigora.puppet.input_arbitration` | `InputArbiter` and `submit_values(canvas, source, values)`: live inputs write as a named source and the canvas keeps one owner per parameter (`PuppetCanvas.submit_input`, `release_input`, `input_arbiter`) |
| `rigora.puppet.input_calibration` | Qt-free `InputProfile`, `Calibrator` and profile storage |
| `rigora.puppet.device_supervisor`, `output_pump` | Qt-free device recovery policy; bounded frame queue with `OutputStats` |
| `rigora.desktop_pet` | Lazy `PetWorkspace`, `PetWindow`, `PetTrayIcon` exports |
| `rigora.desktop_pet.pet_script` | `load_script`, `PetScriptEngine` used by FrontEngine |
| `rigora.desktop_pet.pet_feature_base` | `IntegrationController` for Imervue integrations |
| `rigora.system.settings` | Explicit `configure`, one-time `import_legacy_settings`, independent storage, `flush` |
| `rigora.system.app_paths` | Writable `app_dir`, `user_settings_path`; installed `examples_dir` |
| `rigora.gui.background_jobs.set_job_registry` | Attach a host job registry before starting work |
| `rigora.i18n.language_wrapper` | Host chooses language using `reset_language` |

Private underscored methods and canvas caches are not extension APIs. Consumers
must not treat transient parameter values or runtime numpy caches as document edits.

## Host close and edit lifecycle

Before tearing down an editor, call `confirm_discard_changes()`. A false result
means cancel the entire host close, including worker and GL cleanup. On success,
call `shutdown()` before deleting the widget, then flush settings. Shutdown is
idempotent and preserves a recovery copy of unconfirmed dirty work. A host that
only calls shutdown cannot offer the Save/Discard/Cancel choice.

Use `session.transaction(label)` for a composite authored edit, then reload the
same document into the canvas to rebuild inspector/render state. Transactions
roll back on failure. A gesture may mutate repeatedly and call `checkpoint`
once at its end. Document replacement must go through workspace open/import
operations, which handle pending edits and reset history. `Reset to rest`
changes playback state, retains a recorded take, and does not discard authored work.

Capture `session.revision` when starting work. Before applying its result,
check `session.accepts(token)`. Replacement, committed edits and undo/redo
invalidate tokens. An uncommitted document edit also rejects the result.
Snapshots exclude runtime caches; undo history defaults to 100 steps and
128 MiB of retained history, excluding the current document and save point.
An edit larger than the history budget is still dirty and saveable.

## Consumer matrix

| Consumer baseline | Existing usage | Missing-package behavior | R1 integration |
| --- | --- | --- | --- |
| Imervue `14a80a7ad136bdf6370a272450ebd60bdf1487c7` | Puppet/Desktop Pet tabs, four CLI/MCP operations, settings/language/jobs, integration controller | Tabs show installation notice; commands fail with actionable installation message; installed dependency errors are not masked as package absence | Local host change calls `confirm_discard_changes` before teardown; deploy it together with the R1 wheel |
| FrontEngine `9b0bc0364ebbde0ce8a491a923e21678e85fce3a` | Canvas, document loader, idle/input/player and pet scripts through `utils/imervue/runtime.py` | Adapter raises an installation `ValueError`; no developer-checkout path injection | Playback consumer does not own an authored editing session |

CI pins the Imervue baseline rather than following a moving branch. Update that
pin after the host-close change is committed and available remotely. FrontEngine
contracts are checked locally against the recorded revision; a remote job remains
deferred until its repository access and install dependencies are configured.
Do not count that absent CI job as a remote passing result.

## Import reports

Import previews are data, not dialogs. Each difference has a stable `code`, a
`subject` (layer, group, file or parameter), an English `detail` and a
`severity`: `error` means the requested import would fail, `warning` that the
result looks or behaves differently from the source, `info` that metadata
changes or something is skipped by design. `to_dict()` output is JSON-ready.
The GUI translates codes; machine callers should match on `code`, never on text.

Art updates match drawables to layers by the id a fresh import would assign.
Replacing pixels keeps vertices, UVs (adjusted only to whole-pixel crops),
weights, morphs and every reference. Rebuilding drops that drawable's weights
and morphs and reports them in `AssetUpdateResult.dropped`.
`rigora.psd.model.PsdLayer` gained defaulted fields (`group_path`,
`source_blend_key`, `clipping`, `has_mask`, `fill_opacity`, `info_keys`,
`bounds`), `PsdGroup` gained `parent`, `source_name`, `source_blend_key`, and
`PsdDocument` gained `empty_records`. Existing constructor calls keep working.

## Format and installation boundaries

The MIME type and original schema URLs are permanent compatibility identifiers.
Schema files ship in `rigora/resources/schemas`; they do not require a network
request. Package metadata, installed resources and build verifiers must resolve
from the installed distribution, never from a neighboring Imervue checkout.

Core installation requires neither Qt nor OpenGL. GUI and optional device
dependencies remain separate extras. The package directory may be read-only;
models, settings and recovery files belong under the writable data directory.
`RIGORA_DATA_DIR` and `RIGORA_SETTINGS_PATH` override those locations independently.

Recovery archives are atomic, per-document copies under process-isolated locked
directories. Active processes' copies are excluded from recovery choices. Use
File > Recover document to choose an abandoned copy; recovery opens an unsaved
document and requires Save As, leaving the original and recovery archive intact.
File > Autosave interval sets seconds; zero disables periodic recovery. Shutdown
still attempts a recovery save unless the user explicitly discarded that revision.
