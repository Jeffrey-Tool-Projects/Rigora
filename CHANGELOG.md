# Changelog

Versions follow the rules in [docs/releasing.md](docs/releasing.md). Entries
under *Unreleased* are in the working tree and not part of any published
release.

## Unreleased

### Added

- **Import and art updates:** PSD and Cubism import previews that list every
  layer and every feature the import cannot keep; nested PSD groups, blend
  modes and clipping; updating art from a re-exported PSD while keeping the
  rig; relinking missing textures and sounds.
- **Rigging tools:** vertex selection, box select, locks, weight view and
  weight smoothing, normalising and mirroring; a searchable deformer tree with
  reparenting, ordering, locks and cycle warnings; grouped, filterable
  parameters with range editing and key previews; a physics chain editor with
  presets; the rig doctor with previewed fixes; part templates for blinking,
  mouth shapes, head turns and sway.
- **Animation:** multi-key editing (box select, copy and paste, move, scale,
  snap, tangents) with the sound's waveform; recorded takes with conflict
  choices and provenance; compositions with layers, clips, fades and weights,
  baked into motions on request; sound kept in sync while seeking and looping;
  lip-sync options; an offline export queue for PNG sequences, GIF, MP4 and
  WebM with transparency, sound, physics warm-up, cancel and retry.
- **Live performance:** camera and microphone selection, calibration profiles
  (sensitivity, dead zone, smoothing, neutral pose, return to rest); one owner
  per parameter across live inputs with an Input sources view; automatic
  recovery from unplugged devices, denied access, model download failures,
  device switches and sleep; a Live status panel with real source names,
  frame rates and dropped frames; outputs that never block the editor on a
  slow receiver; VTS API token expiry and revocation, plug-in name checks,
  rate limits and atomic, range-checked injection.
- **Desktop companions:** several characters with layouts; recovery after
  monitor, scaling or sleep changes; behavior rules (events, conditions,
  actions, cooldowns, priorities, loop limits, safe stop) with checks and a
  preview in the script editor; local LLM dialogue with connection status,
  cancel, opt-in history and replies limited to the character's own motions
  and expressions; 15 fps when idle, no repaint while hidden, shared rig
  textures and per-character resource figures.
- **Automation:** new CLI commands and MCP tools (`psd-preview`,
  `puppet-from-psd`, `cubism-preview`, `rig-doctor`, `update-art`,
  `motion-compress`, `bake-composition`, `export-animation`), stable exit
  codes and JSON errors, overwrite protection, and MCP jobs with progress,
  cancel and idempotent request ids; the versioned host interface
  `rigora.host_api` 1.0 with an example adapter.
- **Format:** optional `compositions` in `puppet.json` and `take` in motions,
  readable by older versions (they ignore both).
- **Documentation and examples:** a walkthrough from artwork to a finished
  character, a desktop companions guide, VTS API support notes, a release
  guide, and five checked examples with sources and expected results.

### Changed

- Faster rendering and composition (batched deformation, fewer GL error
  checks per frame); images stored without recompression in `.puppet` files.
- Invalid or oversized numbers in `.puppet` files are rejected with a clear
  error.
- `THIRD_PARTY_LICENSES.md` now lists Rigora's actual dependencies;
  `pyvirtualcam` is correctly listed as GPL-2.0.

### Fixed

- Microphone lip-sync failed on every audio block delivered as
  frames × channels.
- Several unit-test stand-ins and native-only tests that had drifted from the
  current behaviour.

## 0.1.1 — 2026-11-12

- The Windows portable build is compiled with Nuitka.

## 0.1.0 — 2026-11-12

- First standalone Rigora package, extracted from Imervue: runtime, editor,
  desktop pet, CLI and MCP server.
- Windows portable executable built and published from version tags, with a
  usage guide; Rigora handbook for GitHub Pages.
