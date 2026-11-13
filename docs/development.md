---
title: Development
description: Install a development checkout, run checks, and find the modules behind the editor and runtime.
permalink: /development/
---

## Install the checkout

Follow [Getting started]({{ '/getting-started/' | relative_url }}) to clone
the repository and create a virtual environment. Install the development extra
in editable mode:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

On macOS and Linux, use `.venv/bin/python`. Editable installation lets the
environment load changes from this checkout.

## Run checks

From the repository root:

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m bandit -c pyproject.toml -r rigora
.venv\Scripts\python.exe -m pytest tests/ -q
```

To run widget tests without visible windows, set `QT_QPA_PLATFORM=offscreen`.
Native OpenGL tests are skipped in that mode, so a passing run does not verify
rendering.

On Windows, the native verifier uses a hidden window and writes its report and
framebuffer images to `.audit/`:

```powershell
.venv\Scripts\python.exe scripts/verify_gui.py --source --output .audit/native-gui
```

The run chains the editor-session, asset, rig, animation, live-input
(`verify_live_workflow.py`) and desktop-companion (`verify_pet_workflow.py`)
checks. Capture devices are replaced at the driver boundary, so no camera,
microphone or visible window is used. Visible desktop overlays, tray behavior,
real cameras, microphones and stream receivers still need their own checks.

`py -3 examples/run_examples.py` builds and checks every example; add
`--render` for the GPU export. Release steps, including clean-environment
installs, upgrade/downgrade checks and checksums, are in
[releasing](releasing.md).

## Measure performance

`scripts/benchmark.py` measures cold start, open, save, motion sampling, CPU
frame time, memory and a soak run on generated scenes (many drawables, a deep
deformer chain, clip masks, physics chains, four pets) plus the bundled example.
`--gl` adds hidden-window GPU render, read-back and PNG export throughput on
Windows. The report records the machine, versions, source revision and every
scene's actual size; compare runs only from the same machine.

```powershell
.venv\Scripts\python.exe scripts/benchmark.py --gl --soak 300 --output .audit/benchmark
```

## Build a distribution

```powershell
.venv\Scripts\python.exe -m build
.venv\Scripts\python.exe scripts/verify_wheel.py dist/rigora-0.1.1-py3-none-any.whl
```

Use the wheel filename produced by your build if the version changes. Package
verification checks installation outside the source checkout. A local build
does not publish a package or a GitHub release.

## Build a Windows release

The [Windows release workflow](https://github.com/Jeffrey-Tool-Projects/Rigora/actions/workflows/windows-release.yml)
compiles the portable application with Nuitka and MSVC. A manual `workflow_dispatch` run uploads a
test artifact without publishing a release.

To build locally, use 64-bit Python 3.12 and Visual Studio Build Tools with the
C++ compiler installed:

```powershell
.venv\Scripts\python.exe -m pip install ".[gui]" -r packaging/requirements-windows.txt
.venv\Scripts\python.exe scripts/build_windows.py --native
```

The build script uses four compiler jobs and writes the ZIP, checksum,
smoke-test reports, and Nuitka compilation report to `dist/windows/`.
The optional `--native` check renders a character through a hidden OpenGL window.
CI runs the offscreen startup, resource, video-export, and shutdown checks.

To publish a version, use a `v`-prefixed tag that matches the version in
`pyproject.toml`, such as `v0.1.1` for package version `0.1.1`. The workflow
checks that match before publishing. Its release job uses the artifact built
and verified in the same workflow run.

Release assets are `Rigora-windows-x64.zip` and `SHA256SUMS.txt`. The ZIP keeps
`Rigora.exe`, DLLs, and companion folders together in a `Rigora` directory. The
[Windows guide]({{ '/windows/' | relative_url }}) covers the end-user steps and
the features excluded from the portable build.

## Find the owning module

| Location | Responsibility |
| --- | --- |
| `rigora/app.py` | Application startup, settings, and shutdown |
| `rigora/editor_window.py` | Editor window and desktop-pet tab |
| `rigora/puppet/` | Document model, runtime, editor workspace, import, and output |
| `rigora/desktop_pet/` | Desktop companions and their controls |
| `rigora/commands.py`, `rigora/command_ops.py` | Headless operations shared by CLI and MCP |
| `rigora/host_api.py` | Versioned host interface |
| `rigora/resources/` | Installed examples and schemas |
| `examples/` | Source artwork, model builders, and examples |
| `tests/` | Runtime, UI, archive, and integration checks |

The [architecture document](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/architecture.md)
describes module boundaries. Rigora was extracted from Imervue. The
[provenance record](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/migration/PROVENANCE.md)
records that migration, while consuming applications own their integration tests.

## Edit this documentation

The GitHub Pages site is built from `docs/` on `main` with Jekyll. Pages use
Markdown and front matter, a shared layout in `docs/_layouts/`, and local CSS
in `docs/assets/`. There is no client-side JavaScript or remote font dependency.

Keep links within the site relative to its `/Rigora` base path by using Jekyll's
`relative_url` filter. Keep the existing `docs/schemas/` and `docs/examples/`
downloads available when reorganizing pages. Check the Pages build and deployed
links after publishing changes.

## Contribute a change

Open an [issue](https://github.com/Jeffrey-Tool-Projects/Rigora/issues) with the
behavior you expected, what happened, and steps to reproduce it. Include your
operating system, Python version, and relevant output. For rendering issues,
include a small model that you have permission to share.

Keep changes focused and include verification appropriate to the affected
behavior. Preserve attribution and review the
[third-party notices](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/THIRD_PARTY_LICENSES.md)
before adding assets or dependencies.
