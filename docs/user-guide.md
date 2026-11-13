---
title: User guide
description: Choose a workflow for character artwork, animation, live output, or desktop companions.
permalink: /user-guide/
---

## Start from an existing model

Open a `.puppet` file or select **File > Examples > Imeru**. The bundled example
contains parameters, motions, expressions, and physics bindings. Save a copy
before changing it.

Use **Parameters** to pose the model and **Motions** to play authored motion.
**Reset to rest** restores the neutral pose. The same parameter system drives
manual editing, recorded animation, and live inputs.

## Import your artwork

Use the editor's import actions for PNG, PSD, or Cubism content. A PNG can also
be converted through the command line:

```text
rigora puppet-from-png character.png --destination character.puppet --cell-size 64
rigora puppet-validate character.puppet --json
rigora editor character.puppet
```

PNG conversion creates a textured mesh and standard parameters. Refine the
mesh and bindings in the editor to suit the drawing. Layered artwork gives you
more control over parts that need to move independently.

PSD and Cubism imports open a preview first. It lists every layer or referenced
file and each feature the rig cannot reproduce, such as layer masks, unsupported
blend modes or motion curves the runtime does not model, so nothing is dropped
silently. When the artwork changes later, **File > Update art from PSD…** swaps
the pixels into the existing rig and keeps meshes, weights and motions;
**File > Relink textures…** repairs missing textures. Both are a single Undo step.

Cubism import has separate requirements for source data and proprietary SDK
components. Those binaries are not bundled. Consult the
[detailed import guide](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/puppet_guide.md#importing-rigs)
before preparing Cubism assets.

## Record and export animation

1. Open a rig and set its starting pose.
2. Choose **Output > Record motion** and perform. When the name is taken,
   choose whether the new take replaces the motion, is kept beside it, or is
   discarded.
3. Open **Edit > Edit motion…** to adjust keys: box-select, copy and paste,
   move, scale time, snap and set tangents. A motion's sound is drawn as a
   waveform behind its keys.
4. Arrange several motions in **Edit > Compositions…** — layers, clips, fades
   and weights — and preview them without changing the rig.
5. Choose **Output > Export animation…** to render a motion or composition
   frame by frame as a PNG sequence, GIF, MP4 or WebM, with or without
   transparency and sound.

Exports run in a queue that shows progress and can be cancelled or retried; a
cancelled export leaves no partial file. Video support uses the dependencies
installed by the `gui` extra. Save the `.puppet` document as well as the
rendered output so you can continue editing.

## Perform live

Live controls can drive head movement, blinking, mouth movement, and other
parameters. Start with mouse tracking and automatic blinking, then add the
inputs you need.

| Input | Purpose |
| --- | --- |
| Drag-track head | Move head and gaze parameters with the pointer over the canvas. |
| Auto-blink | Blink without a camera. |
| Mic lip-sync | Drive mouth parameters from microphone input. |
| Webcam tracking | Drive facial parameters from face landmarks. |
| Auto idle and idle motions | Add movement while no motion is being performed. |

**Live > Input devices and calibration…** chooses the camera and microphone,
sets sensitivity, dead zone and smoothing, captures your neutral pose, and
decides how the rig returns to rest when tracking is lost. When several inputs
drive the same parameter, one controls it at a time; **Live > Input sources…**
shows which. Unplugged devices are retried automatically, and **Output > Live
status…** shows each output's real name, resolution, frame rate, dropped frames
and errors.

Virtual camera and NDI output can send the rendered character to compatible
streaming software. Install the relevant extra and configure the receiving
application. The VTS API accepts parameter input from compatible trackers; see
[VTS API support](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/docs/vts-api-support.md)
for what it covers. The [reference]({{ '/reference/' | relative_url }}#optional-features)
lists their dependencies.

## Load a desktop companion

Open the **Desktop Pet** tab and select **Load bundled Imeru**, or load your
own supported model. Use its controls to adjust visibility and interaction.
Desktop companions also support scripts, schedules, and optional hotkeys.

The **Characters** tab runs several characters at once, each with its own rig,
script and settings, and saves their arrangement as layouts. Scripts can hold
behavior rules — events such as clicks, drops, hotkeys, beats and timers,
with conditions and actions — that the script editor checks and previews
before they run. The [desktop companions guide]({{ '/desktop-companions/' | relative_url }})
covers characters, behavior rules, the local LLM, monitors and resource use.

Global hotkeys need the `hotkeys` extra. System tray availability and desktop
window behavior depend on the operating system and desktop session.

## Read the detailed workflows

The repository maintains longer guides for live streaming, animation, import,
shortcuts, and troubleshooting:

- [English Puppet guide](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/puppet_guide.md)
- [繁體中文指南](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/puppet_guide.zh-TW.md)
- [简体中文指南](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/puppet_guide.zh-CN.md)

Use this site's [getting-started instructions]({{ '/getting-started/' | relative_url }})
for installation. Some longer-guide screenshots and wording also describe the
editor when embedded in Imervue.
