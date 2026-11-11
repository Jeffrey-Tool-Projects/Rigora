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

This verifier checks a specific rendering path. Desktop overlays, tray behavior,
camera, microphone, and network outputs need their own checks.

## Build a distribution

```powershell
.venv\Scripts\python.exe -m build
.venv\Scripts\python.exe scripts/verify_wheel.py dist/rigora-0.1.0-py3-none-any.whl
```

Use the wheel filename produced by your build if the version changes. Package
verification checks installation outside the source checkout. A local build
does not publish a package or a GitHub release.

## Find the owning module

| Location | Responsibility |
| --- | --- |
| `rigora/app.py` | Application startup, settings, and shutdown |
| `rigora/editor_window.py` | Editor window and desktop-pet tab |
| `rigora/puppet/` | Document model, runtime, editor workspace, import, and output |
| `rigora/desktop_pet/` | Desktop companions and their controls |
| `rigora/commands.py` | Headless operations shared by CLI and MCP |
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
