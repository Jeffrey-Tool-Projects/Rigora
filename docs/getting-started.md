---
title: Getting started
description: Install Rigora and play your first animation with the bundled Imeru character.
permalink: /getting-started/
---

[繁體中文入門]({{ '/getting-started-zh-tw/' | relative_url }})

## Use the Windows application

On 64-bit Windows 10 or 11, you can use the portable application without
installing Python. Download and extract `Rigora-windows-x64.zip`, then open
`Rigora/Rigora.exe`. Keep the full extracted folder together.

Follow the [Windows download guide]({{ '/windows/' | relative_url }}) for the
official release link, checksum verification, and optional-feature limitations.
For source development or other platforms, continue below.

## Create an environment

Install Python 3.11 or newer and Git. The editor needs a desktop environment
with working OpenGL support.

Clone the repository:

```text
git clone https://github.com/Jeffrey-Tool-Projects/Rigora.git
cd Rigora
```

On Windows, run:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install ".[gui]"
.venv\Scripts\python.exe -m rigora
```

On macOS or Linux, run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ".[gui]"
.venv/bin/python -m rigora
```

Using the environment's Python directly avoids activation and interpreter
mismatches. If your IDE asks for an interpreter, choose
`.venv\Scripts\python.exe` on Windows or `.venv/bin/python` on macOS and Linux.

## Play a motion

1. Open **File > Examples > Imeru** in the character editor.
2. Select a motion in the **Motions** dock at the bottom of the workspace.
3. Change a value in the **Parameters** dock to see its effect on the rig.
4. Select **Reset to rest** to return the character to its neutral pose.
5. Use **Save As** to save a working copy before editing the bundled example.

To open a saved document at startup, pass its path:

```powershell
.venv\Scripts\python.exe -m rigora path/to/model.puppet
```

After environment activation, `rigora-editor` and `rigora editor` also open the
editor. Continue with the [user guide]({{ '/user-guide/' | relative_url }}) to
import artwork, record animation, or use live inputs.

## Add an optional input

Install extras into the same environment that launches Rigora. For webcam and
microphone input on Windows:

```powershell
.venv\Scripts\python.exe -m pip install ".[gui,webcam,lipsync]"
```

See the [dependency table]({{ '/reference/' | relative_url }}#optional-features)
for the other extras. Webcam tracking downloads a face-landmark model on first
use. Camera and microphone permissions remain controlled by your operating
system.

## Use only the headless tools

Install the checkout without extras:

```powershell
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\rigora.exe puppet-validate examples/puppet/imeru.puppet --json
```

On macOS and Linux, use `.venv/bin/python` and `.venv/bin/rigora`. Headless
commands do not initialize Qt or OpenGL.

## Resolve startup problems

| Symptom | Check |
| --- | --- |
| `No module named rigora` | Run the install command from the repository root with the same Python used to launch the editor. |
| Missing `PySide6` or `OpenGL` | Install `.[gui]` into that environment. |
| `rigora` is not found | Activate the virtual environment, or use its executable path directly. |
| Qt cannot create a window or GL context | Check the desktop session and graphics driver. Linux may also need system Qt, EGL, OpenGL, and audio libraries. |
| Webcam or microphone feature is unavailable | Install its extra and check OS device permissions. |

`QT_QPA_PLATFORM=offscreen` is useful for widget tests. It does not provide the
native OpenGL rendering required for normal editor use.
