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

Cubism import has separate requirements for source data and proprietary SDK
components. Those binaries are not bundled. Consult the
[detailed import guide](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/puppet_guide.md#importing-rigs)
before preparing Cubism assets.

## Record and export animation

1. Open a rig and set its starting pose.
2. Use the recording controls to capture parameter changes during a performance.
3. Review the motion in the timeline and adjust its keys.
4. Play the motion to check transitions and expression changes.
5. Use the output controls to export the image or animation format you need.

The editor supports animation and video output, including GIF, MP4, and WebM.
Video support uses the dependencies installed by the `gui` extra. Save the
`.puppet` document as well as the rendered output so you can continue editing.

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

Virtual camera and NDI output can send the rendered character to compatible
streaming software. Install the relevant extra and configure the receiving
application. The [reference]({{ '/reference/' | relative_url }}#optional-features)
lists their dependencies.

## Load a desktop companion

Open the **Desktop Pet** tab and select **Load bundled Imeru**, or load your
own supported model. Use its controls to adjust visibility and interaction.
Desktop companions also support scripts, schedules, and optional hotkeys.

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
