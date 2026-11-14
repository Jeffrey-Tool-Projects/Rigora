# Puppet Guide — Live Streaming & Animation Production

Install the public Rigora source checkout with `python -m pip install ".[gui]"`, then run `python -m rigora`. These instructions install from source and do not assume a PyPI release. The editor described here also runs in Imervue’s Puppet tab when Rigora is installed. Packaged examples are resolved with `rigora.system.app_paths.examples_dir()`; the `examples/` paths below refer to the Rigora source checkout.

A walkthrough for getting from "I want to do VTuber-style streaming
or make a short animation" to "I'm live on OBS / I have an MP4
file on disk" using Rigora's **Puppet** tab.

Two paths are documented:

1. **Live streaming** — drive a puppet rig with mouse / mic /
   webcam, send the result into OBS for streaming or recording.
2. **Animation production** — record a take, edit the motion
   timeline, export to GIF / MP4 / WebM.

The two share the same rig and the same parameter system; the
only difference is whether your output is a live virtual camera
feed or a file on disk.

---

## Contents

- [Quick start](#quick-start)
- [From artwork to a finished character](#from-artwork-to-a-finished-character)
- [Part 1 — Live streaming to OBS](#part-1--live-streaming-to-obs)
- [Part 2 — Making animations](#part-2--making-animations)
- [Part 3 — Desktop companions](#part-3--desktop-companions)
- [Importing rigs](#importing-rigs)
- [Advanced rig features](#advanced-rig-features)
- [Optional dependencies](#optional-dependencies)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Troubleshooting](#troubleshooting)

---

## Quick start

1. Launch Rigora (`python -m rigora` if running from source).
2. Click the **Puppet** tab at the top of the window.
3. **File > Examples > Imeru** (or the toolbar's **Examples ▾**
   dropdown). The bundled rig, Rigora's mascot, opens centred.
4. In the bottom **Motions** dock, click any of the 8 motions.
   The rig animates immediately.
5. Press **Reset to rest** on the toolbar to snap the rig back to
   its neutral pose.

That's the baseline. The rest of this guide explains how to take
this idle rig and either go live or bake out a video.

---

## From artwork to a finished character

One path from a layered illustration to a character that streams, animates
and sits on the desktop. Each step links to its section.

1. **Import.** **File > Import PSD…** shows every layer and what the import
   cannot carry over (masks, unsupported blend modes) before anything changes
   ([From a PSD](#from-a-psd)). Cubism models go through
   **File > Import Cubism…**.
2. **Check the rig.** **Tools > Rig doctor…** lists broken meshes, weight and
   symmetry problems, missing standard rigging and validation errors, and
   previews each fix before applying it ([Rig doctor](#rig-doctor-and-part-templates)).
3. **Add standard parts.** **Tools > Part templates…** adds an eye blink,
   mouth shapes, head turn and sway to the drawables you pick
   ([Part templates](#rig-doctor-and-part-templates)).
4. **Refine.** Adjust meshes and weights in the **Mesh** menu
   ([Editing meshes and weights](#editing-meshes-and-weights)), order
   deformers and group parameters in the docks
   ([Organising deformers and parameters](#organising-deformers-and-parameters)),
   and tune hair and cloth in **Tools > Physics chains…** ([Physics](#physics)).
5. **Calibrate and perform.** Pick devices and tune tracking in
   **Live > Input devices and calibration…**, then stream
   ([Part 1](#part-1--live-streaming-to-obs)).
6. **Animate.** Record takes, edit keys, arrange compositions and export
   ([Part 2](#part-2--making-animations)).
7. **Put it on the desktop.** Load the rig in the Desktop Pet tab and give it
   a script ([Part 3](#part-3--desktop-companions)).
8. **When art changes.** **File > Update art from PSD…** replaces pixels and
   keeps the rig ([Updating art](#updating-art-from-a-psd)).

Every step that changes the rig is one **Edit > Undo** step.

---

## Part 1 — Live streaming to OBS

The goal: a webcam-style window in OBS showing your puppet
animated by your face / mic / mouse, ready to put in a stream.

### 1.1 Inputs (what drives the rig)

The Puppet toolbar exposes six live-input toggles (the **Live**
menu carries the same six). Combine them as needed — they don't
interfere as long as they drive different parameters.

| Toggle | Drives | Optional dep |
|---|---|---|
| **Drag-track head** | `ParamAngleX/Y`, `ParamEyeBallX/Y` follow the mouse cursor as it moves over the canvas | none |
| **Auto-blink** | `ParamEyeLOpen/ROpen` blink every ~4.5 s | none |
| **Mic lip-sync** | `ParamMouthOpenY` from microphone loudness, `ParamMouthForm` from its vowel colour | `sounddevice` |
| **Webcam tracking** | head yaw/pitch/roll, eye open, gaze and mouth open from face landmarks | `opencv-python` + `mediapipe` |
| **Auto idle** | Breath cycle + gentle drift on head / body | none |
| **Idle motions** | Plays a random motion from the `Idle` group every 8 s | none |

For a typical face-tracking VTuber setup, enable **Webcam
tracking** + **Auto-blink** + **Mic lip-sync**. When you toggle
*Webcam tracking* on, a preview window pops up showing the camera
feed with detected landmarks overlaid — useful for verifying the
tracker actually sees your face.

> **First-run note** — webcam tracking needs `mediapipe`'s
> face-landmark model. Rigora downloads it (~3.7 MB from Google
> Cloud Storage) to `<Rigora data directory>/models/face_landmarker.task` the
> first time you enable the toggle. Subsequent launches use the
> cached copy.

**Live > Input devices and calibration…** chooses the camera and
microphone and tunes how tracking moves the rig. Settings are kept
in named profiles (one per room or desk, say):

- **Sensitivity**, **Dead zone** and **Smoothing** shape every tracked
  parameter. Smoothing behaves the same at any camera frame rate.
- **Capture neutral pose (2 s)** — with webcam tracking on, sit
  relaxed and press it. Rigora records how you sit at rest, and that
  pose becomes each parameter's default, so a slightly turned head no
  longer reads as "looking away".
- **Return to neutral after** / **Return duration** — when your face
  leaves the frame, the rig waits this long and then eases back to its
  rest pose instead of freezing mid-expression.
- **Microphone gain**, **Microphone noise gate** and **Lip-sync
  smoothing** tune mic lip-sync; the gate keeps room noise from
  twitching the mouth.

Listing devices never opens them; the camera turns on only with
**Webcam tracking**.

When several inputs drive the same parameter, one of them controls it
at a time. A higher source takes over at once; a lower one waits until
the owner has stopped writing for a quarter of a second (a second for
a slider you dragged). The order is: slider you are dragging → VTS
plug-in → playing motion → webcam → microphone → auto-blink → mouse →
idle. So a playing motion wins over the webcam, and webcam eye tracking
suppresses auto-blink. **Live > Input sources…** shows, for every
parameter, which source controls it right now and which expressions
are layered on top.

**Output > VTS API** adds one more input: it opens a small VTube
Studio Public API server on `ws://127.0.0.1:8001` (this machine
only), so a face tracker that speaks that protocol can list the
rig's parameters and inject values into them. It covers the requests
a tracker needs, not the whole VTube Studio API — see
[VTS API support](docs/vts-api-support.md) for the list, the token
rules and the rate limits. Tokens expire after 12 hours, end when the
API is turned off, and can be revoked at once from **Output > Live
status…**.

### 1.2 Outputs (how OBS sees the rig)

Three paths work. Pick **A** if you're new, **B** if you want
pixel-perfect alpha compositing; **C** needs no setup at all.

#### Path A — Virtual Camera

The puppet canvas appears as a webcam in OBS's *Video Capture
Device* source list.

```bash
pip install pyvirtualcam
```

Plus the platform virtual-camera driver:

- **Windows**: OBS Studio 26+ ships the *OBS Virtual Camera*
  driver. After installing OBS, open it once and click **Start
  Virtual Camera** in the bottom-right panel — that registers
  the driver so `pyvirtualcam` can find it.
- **macOS**: OBS for Mac ships an OBS Virtual Camera system
  extension. First run will prompt to enable it under
  System Settings → Privacy & Security.
- **Linux**: `sudo apt install v4l2loopback-dkms` then
  `sudo modprobe v4l2loopback exclusive_caps=1 card_label="Rigora"`.

Wiring:

1. In the Puppet tab, open your rig, then toggle **Output >
   Virtual camera**. The status bar tells you the exact device
   name (typically *OBS Virtual Camera*).
2. In OBS: **Sources > + > Video Capture Device** → pick the
   device named in step 1.

**Why is the background magenta?**

Virtual cameras transport RGB only — DirectShow / AVFoundation /
v4l2loopback all share that limitation. OBS treats the input as
opaque RGB, so whatever colour Rigora puts behind the character
is what OBS displays. Magenta `#FF00FF` is the industry-standard
chroma-key colour because it almost never appears in skin /
hair / eye palettes.

**Removing it in OBS:**

1. Right-click the *Video Capture Device* source → **Filters**
2. **Effect Filters → + → Color Key**
3. Configure:
   - **Key Color Type**: `Custom Color`
   - **Custom Color**: HEX `FF00FF`
   - **Similarity**: start at `80`, raise to `200–300` if any
     magenta edges leak through
   - **Smoothness**: `30–50` so the cut isn't pixel-sharp
4. Close — the filter sticks to the source, so re-enabling the
   virtual camera later automatically picks it up.

#### Path B — NDI (pro grade, true alpha)

NDI carries RGBA over the LAN at sub-50 ms latency. No chroma
key needed — the alpha channel survives the wire intact.

```bash
pip install ndi-python
```

Plus:

1. Download **NDI Tools** from <https://ndi.video/tools/> — the
   installer includes the runtime DLL that `ndi-python` links
   against.
2. Install the **obs-ndi** plugin into OBS:
   <https://github.com/obs-ndi/obs-ndi/releases>

Wiring:

1. In the Puppet tab, toggle **Output > NDI output**. Status bar
   shows the source name (default *Imervue Puppet*, retained for existing receiver configurations).
2. In OBS: **Sources > + > NDI Source** → pick the source name
   from step 1.

The puppet composites directly onto your OBS scene with no
chroma-key filter. The render uses a fully-transparent
background outside the character.

**`ndi-python` build prerequisites (Windows)**

`ndi-python` ships only a source distribution; pip builds it
from C++ at install time. On Windows you need:

- **Visual Studio Build Tools 2022** with *Desktop development
  with C++* workload
- **CMake** (with *Add to system PATH* checked)
- **NDI SDK** (separate from NDI Tools — get it from
  <https://ndi.video/for-developers/ndi-sdk/>) installed at the
  default `C:\Program Files\NDI\NDI 6 SDK\`
- Environment variable `NDI_SDK_DIR` pointing at the SDK install

If that's more setup than you want, stay on Path A.

#### Path C — Window Capture (zero install)

OBS **Sources > + > Window Capture** can grab the Rigora window
directly. No virtual-camera driver, no SDK. Trade-offs:

- Captures the whole Rigora window, chrome included — you have
  to add an OBS *Crop/Pad* filter to chop down to just the
  puppet area.
- Whatever's in the puppet workspace's checker backdrop gets
  streamed too.
- Bound to whatever size the Rigora window is.

Only use this for quick demos. For anything you'd actually
stream, use A or B.

### 1.3 The character-only render path

Both Virtual Camera and NDI render the puppet to an off-screen
framebuffer **without the checker backdrop or any editor
chrome**. The toolbar / docks / status bar inside Rigora are
purely for your editing convenience; only the actual character
drawables hit the stream. The output's longest side is capped
at 1080 px (so a 3503×7777 Cubism canvas doesn't break the
DirectShow driver).

### 1.4 Reset between takes

A motion with **Loop** off stops on its last frame, **Pause** holds
the current pose, and live inputs leave their parameters wherever
they last put them. Click **Reset to rest** on the toolbar (or
**Edit > Reset to rest**) to snap everything back:

- Motion player snap-stops (no fade-out)
- All live-input toggles un-check, and **Record motion** stops (the take is kept)
- Active expressions drop
- Pose groups return to first-member default
- Physics chains snap back to rest
- Parameter values reset to authored defaults

Status bar confirms: *"Rig reset to neutral pose."*

### 1.5 Live status and device problems

**Output > Live status…** shows each output and device as it runs:
the name the receiver sees, resolution, actual and target frame rate,
frames dropped, connection state and the last error. For the VTS API it
shows the number of connected plug-ins.

Frames go to the virtual camera and NDI through a two-frame queue.
When a receiver is slower than the rig, older frames are dropped and
counted; the editor itself never waits for the receiver. If sending
keeps failing, the output turns off and the status bar says why.

Rigora recovers from common device problems on its own:

| Problem | What happens |
|---|---|
| Camera unplugged or taken by another app | Tracking reports it and retries after 1, 2, 4, 8 and 15 s, then stops and waits for **Retry devices** |
| Microphone unplugged | Lip-sync reports it and retries the same way |
| Camera access denied | No retry; allow camera access in the system settings, then press **Retry devices** |
| Face model download failed | No retry; check the network, then press **Retry devices** |
| Camera changed in the calibration dialog while tracking | The old camera is released first, then the new one starts |
| Computer slept | Tracking restarts once after waking |

Turning an input off stops its capture thread and releases the
device.

---

## Part 2 — Making animations

The goal: end up with a `.mp4` / `.webm` / `.gif` / `.png` file
on disk.

### 2.1 Recording a motion from a live take

This is the easiest path: drive the rig with your face / mic /
mouse, record the parameter values as they fly, and Rigora
bakes the take into a `Motion` you can later play / loop / save.

1. Open your rig.
2. Enable whichever live inputs you want driving the rig
   (webcam / drag / blink / lip-sync / idle), or plan to move the
   sliders in the **Parameters** dock yourself.
3. **Output > Record motion**. A dialog asks for the motion name
   (default `user_motion`); recording starts when you confirm.
4. Perform — move your face / talk into the mic / move the
   cursor — for however long you want.
5. Choose **Output > Record motion** again to stop.
6. The new motion appears in the **Motions** dock. If a motion
   already has that name, Rigora asks: **Replace it**, **Keep both**
   (the new take gets a numbered name) or **Discard new take**.
   Adding it reloads the rig, which resets parameters, expressions
   and physics to their defaults, and is one **Edit > Undo** step.
   Click the motion to play it back, or save the rig (**File > Save
   As…**) to persist it into the `.puppet` file.

Each take remembers when it was recorded, at what rate and which live
inputs were on; replacing a motion also records which take it
replaced. The **Motions** dock shows this in the motion's tooltip.

Motion recording captures at 30 Hz. Flat tracks (parameters that
didn't actually change during the take) are dropped automatically.
Each remaining track gets one linear segment between every pair of
consecutive samples. The recorder reads the parameters' own values
(sliders, motions, live inputs), so expression overlays and physics
outputs are not part of the take. A recorded motion has no group.

### 2.2 Editing a recorded motion

The **Motion Timeline** dialog lets you tweak a motion's keys
post-hoc.

1. Click the motion in the **Motions** dock so the player holds
   it, then choose **Edit > Edit motion…**.
2. Pick a parameter from the **Track** list. The graph shows that
   track's keys: time runs left to right over the motion's
   duration, and the value axis spans the parameter's own range
   (−1 to 1 when the rig doesn't define the parameter).
3. Drag a yellow point to move a key in time and value. On
   `cubic-bezier` segments, drag the purple handles to shape the
   curve. Each segment is drawn as a straight line between its
   keys.
4. **Ease** reshapes every segment of the shown track: pick an
   easing such as `ease-in-out-sine` and press **Apply to Track**.
   The keys stay where they are; `elastic` and `bounce` become 16
   linear keys per segment. **Simplify Keys** drops, on every
   track, the keys that sit within **Tolerance** (a percentage of
   the parameter's range) of the line through their neighbours —
   it thins a 30 Hz take to the keys that matter, and the label
   shows the key count before and after. The dialog doesn't add
   single keys.
5. Every drag updates the motion in memory and re-poses the
   canvas at the player's current time. **File > Save As…**
   writes the change into the `.puppet` file.

Working with several keys at once:

- Drag over empty space to select keys with a box. **Filter tracks…**
  narrows the **Track** list on a rig with many parameters.
- **Copy keys** and **Paste at…** copy the selected keys to another
  time on the same or another track; **Move…** shifts them in time and
  value; **Scale time…** stretches or compresses their spacing.
- **Snap** rounds key times to 1/30 s, 1/60 s or 0.1 s while dragging,
  moving and pasting.
- **Tangent** sets the selected keys' curves to `linear`, `smooth`,
  `flat` or `stepped`.
- When the motion has a sound, its waveform is drawn behind the keys
  so mouth keys can be lined up with syllables.

An operation that would change nothing (no keys selected, say) says so
under the graph and leaves the motion as it was. Each edit can be
undone with **Edit > Undo** after the dialog closes.

### 2.3 Authoring a motion by hand (no live take)

The Puppet tab has no keyframe editor for new motions. To build
one without a live performance:

1. Turn on **Output > Record motion** and move the sliders in the
   **Parameters** dock — slider changes are recorded like any
   live input.
2. Stop the take and adjust its keys in **Edit > Edit motion…**
   (see 2.2).
3. For exact keyframes, write `motions/<name>.json` inside the
   `.puppet` zip by hand and list the name under `motions` in
   `puppet.json` (see [`FORMAT.md`](rigora/puppet/FORMAT.md)).

The **Set key** button next to each slider is a rigging tool, not
a motion keyframe: it stores every deformer's current form as a
key on that parameter at the slider's value. **Edit > Add
Parameter** adds a new `ParamN` slider (−1 to 1) to key.

Parameter blends — deformer forms keyed on a grid over two or
more parameters, e.g. `ParamAngleX × ParamAngleY` steering the
head across a 2D grid — are read from `parameter_blends` in
`puppet.json`; the Puppet tab has no editor for them.

### 2.4 Exporting

| Action | Output |
|---|---|
| **Output > Capture frame…** | Single PNG of the current frame on a transparent background. Used for thumbnails / static portraits. |
| **Output > Record…** | Pick a GIF / WebM / MP4 file, then frames are written at 30 fps via `imageio` until you toggle it off; the codec follows the file extension. The toolbar button is the same toggle. |
| **Output > Export all motions…** | Pick a folder and a container (`.mp4`, `.gif` or `.webm`); every motion plays from its start and is recorded for its duration into `<motion-name>.<ext>`. Useful for batch-producing reaction clips, idle loops, etc. |
| **Output > Export animation…** | Render one motion or composition offline, frame by frame, independent of the screen's refresh rate. Choose a PNG sequence, GIF, MP4 or WebM, the size, frame rate, time range, transparency (PNG and WebM keep alpha) and a physics warm-up so hair has settled by the first frame. Video can carry the motion's sound. Exports wait in a queue that shows progress per job; a cancelled or failed export leaves no partial file, and **Retry** runs it again. An existing file is kept unless you choose to overwrite or rename. |

Recording uses the same **character-only off-screen render** as
the streaming outputs, so you don't have to crop the chrome out
of the file. GIF / WebM / MP4 frames fit the document's aspect
ratio into 1080 px on the long side, on a white background (these
files carry no alpha), with each side rounded to a multiple of 16.
The PNG capture keeps the document's size, up to 4096 px on the
long side.

### 2.5 Sound for recorded motions

A motion can carry a `sound_path` — an absolute path to a WAV
file. When playback of the motion starts, the WAV plays with it and
follows the motion: seeking moves the sound to the same time, a
looping motion restarts its sound each loop, and if playback drifts
more than 80 ms from the sound the motion follows the sound clock.
**Pause** and **Stop** silence it. Merging a
Cubism `.model3.json` onto an open rig (see *Importing rigs*)
fills it from the motion entry's `Sound` field, and **Live >
Lip-sync from Audio File…** builds a new motion around a WAV: the
mouth (`ParamMouthOpenY`) opens with its loudness, and the WAV is the
motion's sound. Its options set the key rate, how far the mouth leads
the sound (40 ms by default, which reads as in sync) and a silence
gate that keeps the mouth shut between words. For any other motion,
edit `motions/<name>.json` inside the `.puppet` zip — the Puppet
tab has no field for it. The WAV itself stays outside
the `.puppet` file. **Validate** lists motions whose sound file is
missing, and **File > Relink sounds…** looks for them by name in a
folder you choose and updates the paths in one undoable step.

If `PySide6.QtMultimedia` isn't installed the audio degrades
silently and the motion's visual track still plays.

### 2.6 Arranging motions in compositions

A composition plays several motions together on a timeline — a wave
on the body while the face smiles, say — without editing the motions
themselves. Open **Edit > Compositions…**:

1. **New** creates a composition; set its **Duration (s)**. F2
   renames it.
2. Add layers. A layer is either **override** (replaces what lower
   layers set, by its strength) or **additive** (adds its movement on
   top). Give each layer a weight, or mute it.
3. Select a layer and add clips: pick a motion, when it starts, an
   optional offset into the motion and length, looping, fade-in and
   fade-out, weight and mute. Within a layer a clip fading in
   cross-fades over the previous one.
4. **Preview** plays the composition on the canvas without changing
   the rig. Problems (a missing motion, overlapping layer names,
   negative times) are listed under the tables, and the dialog will
   not save until they are fixed.
5. **OK** saves the compositions in one undoable step. **Save and bake
   into motion** also adds the selected composition as an ordinary
   motion, which can be edited, played by hit areas or used by apps
   that don't understand compositions.

**Output > Export animation…** offers compositions as well as motions.
Compositions are stored in the `.puppet` file (see
[`FORMAT.md`](rigora/puppet/FORMAT.md#composition)).

---

## Part 3 — Desktop companions

The **Desktop Pet** tab puts the rig on your desktop. Its **Characters** tab
runs several characters at once, each with its own rig, script and settings;
stopping one leaves the others running, and layouts remember who runs where.
Scripts can hold behavior rules — clicks, drops, hotkeys, music beats and
timers, with conditions, cooldowns and priorities — which the script editor
checks and previews before they run. Characters return to a visible spot when
a monitor is unplugged, scaling changes or the computer wakes, repaint at
15 fps when nothing happens and stop repainting while hidden. An optional
local LLM can write fresh lines; its replies can only trigger the character's
own motions and expressions.

The [desktop companions guide](docs/desktop-companions.md) covers all of
this, including the full list of events and actions; the
[examples](examples/README.md) include a ready-made behavior script.

---

## Importing rigs

### From a PNG

**File > Import PNG…** asks for a mesh cell size (64 px by
default; smaller means a denser mesh), then runs `auto_mesh` on
the image:

- Covers the image with a grid of square cells and drops every
  cell that is fully transparent
- Seeds the Cubism-standard parameter catalogue
  (`ParamAngleX/Y/Z`, `ParamEyeLOpen/ROpen`, `ParamMouthOpenY`,
  `ParamBreath`, …)
- Produces a single-drawable rig with no deformers yet — add them
  from the **Edit** menu

Good for: quick prototyping, single-character art with no layer
separation.

### From a PSD

**File > Import PSD…** turns each visible, non-empty layer into
its own drawable — a quad cropped to the layer's opaque area,
stacked in layer order — and each layer group into a Part. It then
seeds the standard parameter catalogue and auto-rigs by layer name:

- Eye layers named with a side and a state (`eye_l_open`,
  `EyeRClose`, …) fade on `ParamEyeLOpen` / `ParamEyeROpen`, so
  Auto-blink swaps them
- Mouth layers (`mouth_open`, `mouth_close`, `mouth_a` …
  `mouth_o`) fade on `ParamMouthOpenY` and `ParamMouthForm`, so
  Mic lip-sync swaps them
- `head` / `face` layers share one rotation deformer keyed on
  `ParamAngleZ` (±15°)
- `hair` / `bang` / `fringe` layers share a warp deformer plus a
  physics chain from `ParamAngleX` to `ParamHairFront`; the warp
  is keyed on `ParamHairFront`, so the hair tips swing sideways

Other layers (body, arms, clothing) get no deformers.

Good for: artist-supplied multi-layer character files.

Before anything changes, an **import preview** lists every layer —
order (top first), group, status, drawable id, size, position,
opacity, blend, mask and clipping — and every difference from the
PSD, ranked *Blocks import*, *Changes result* or *Note*. Cancel
leaves the open document untouched. How PSD features map:

| PSD feature | In the puppet |
| --- | --- |
| Layer group, nested group | Part, child Part; hidden groups and group opacity carry over |
| Normal / Multiply / Linear Dodge | `normal` / `multiply` / `additive` |
| Other blend modes | drawn as `normal` (reported) |
| Clipping mask | `clip_mask` on the base layer's mesh — its alpha bounding box, not its exact pixels (reported) |
| Layer mask, vector mask, fill opacity, layer effects, adjustment layers | not applied (reported) |
| Text, smart object, fill layer | imported from the stored pixels (reported) |
| Hidden or empty layer, layer clipped to a hidden base | skipped (reported) |
| Name outside `A-Z a-z 0-9 _ -`, or a repeated name | stored under a sanitised, unique id (reported) |

### Updating art from a PSD

**File > Update art from PSD…** brings a re-exported PSD into the
open rig without rebuilding it. Each drawable is matched to the
layer with the same id (the id a fresh import gives the layer
name) and the dialog lists, per row, the change, current and new
area, issues and an action:

- **Replace pixels, keep mesh** (default for changed art) keeps
  vertices, bone weights, morphs, deformers and motions and only
  swaps the pixels under the existing mesh. *New art reaches past
  the mesh* warns when the new layer is bigger than the mesh.
- **Rebuild mesh** makes a new quad around the new art. The
  drawable's bone weights and vertex morphs are dropped and
  counted in the status bar.
- **Add drawable** (new layers) inserts the layer right above the
  layer below it in the PSD and into its group's Part.
- **Keep / Hide** for drawables that are no longer in the PSD.

A vanished drawable and a new layer in the same place are flagged
*probably a renamed layer*; adding it is off by default. A canvas
size that differs from the rig blocks the update. Drawables whose
UVs are not a plain rectangle, or that share a texture, can only
be rebuilt or skipped. The whole update is one Undo step.

### Relinking textures

A file whose textures are absent says so in the status bar after
opening. **File > Relink textures…** lists missing and unreadable
textures with the drawables that use them and the expected size.
*Search folder…* fills in files with the same name (any image
format); *Choose image…* picks one by hand. Images keep the
existing UVs, so a different size is stretched over the mesh and
noted. Relinking is one Undo step.

### From a Cubism `.moc3`

**File > Import Cubism…** first shows a note on the import modes
(tick *Don't show this again* to skip it). It accepts both raw
`.moc3` files and the matching `.model3.json` manifest —
whichever the user picks, when the workspace has no rig open yet
the importer runs the sample-and-reconstruct conversion
end-to-end:

1. Loads `.moc3` via the Cubism Native SDK (user-supplied — drop
   the SDK under `<cwd>/sdk/` or point `CUBISM_CORE_DLL` env var
   at the DLL). Picking the raw `.moc3` works as long as the
   matching `.model3.json` sits next to it; the workspace looks
   the manifest up automatically.
2. Sweeps every Cubism parameter through its min / max values
   and records the deformed vertex positions per drawable.
3. Captures parameter-driven *visibility* transitions too — so
   gesture toggles like "peace sign" / "face cover" / "cry" /
   etc. survive the conversion.
4. Folds the existing motion / expression / physics / hit-area /
   display-name sidecars from the `.model3.json` bundle into the
   puppet. Motions in the bundle's `motions/` folder that the
   manifest doesn't list join the `Idle` group.

The converted rig opens in the canvas; **File > Save As…** writes
it as a self-contained `.puppet` zip you can ship without
redistributing the Cubism SDK (the SDK is never bundled — that's
required by Live2D's Free Material License).

> **Merging onto an existing rig.** When a `.puppet` is already
> loaded, picking a `.model3.json` instead layers its JSON-only
> metadata onto the active document: the motions, expressions,
> physics, hit areas and pose groups whose name or id isn't there
> yet, plus display names — useful for retargeting a
> Cubism motion library onto a hand-authored PSD rig. The raw
> `.moc3` path always builds a fresh document; if you want to
> add motions to an existing rig, pick the `.model3.json` or one
> of the per-asset `.motion3.json` / `.exp3.json` /
> `.physics3.json` / `.pose3.json` / `.cdi3.json` files instead.

Picking a `.moc3` or `.model3.json` opens a **Cubism import
preview** first. It reads only the JSON files — it never loads the
Cubism SDK — and lists each referenced file as found or missing
plus the differences: motion curves the runtime does not model
(`PartOpacity`, `Model`), missing sounds, user data, pose groups
that a full conversion does not read, sampled keyform
approximation, and, when merging, motions or expressions skipped
because the name exists, hit areas without a matching drawable and
parameters the rig lacks. A missing `.moc3`, a missing Cubism
Core library or a missing sidecar that would stop a merge
disables **Import**.

---

## Advanced rig features

### Parameters

Every animated value is a *parameter* with a min, max, and
default. Each of a parameter's `keys` stores deformer forms at one
parameter value; the runtime interpolates linearly between the two
keys around the current value and holds the end keys beyond them.
See `rigora/puppet/standard_params.py` for the Cubism-standard
ids the input drivers expect.

### Deformers

- **Rotation** — anchor + angle, applied to the drawables in the
  deformer's own `drawables` list. `parent` only sets the order:
  parents run before their children, but a parent's rotation moves
  just the drawables it lists, and a child's anchor doesn't follow
  it. To carry the head and arms with a body lean, list them in
  the body deformer too.
- **Warp** — `rows × cols` bilinear lattice over a `bounds`
  rectangle; vertices inside follow the grid, vertices outside
  stay put. Used for cheek squashes, clothing folds, hair swing.
- **Bone rotation** — `bone_rotation` deformers (bone id, anchor,
  angle) skin the drawables that carry `bone_weights`: each vertex
  blends the bones' rotations by its weights. Bones don't inherit
  each other's rotation either.
- **Vertex morphs** — Cubism-style per-drawable delta arrays
  blended linearly between the parameter's default and its
  extremes. The `.moc3` converter produces these.

### Pose groups

Mutually-exclusive drawable visibility. Only one member of a
group is shown at a time: pick it in the **Pose** dock, which
lists each group's members, and the others are hidden.
Used for weapon swaps, mouth-shape variants, costume changes.
The group's first member is the one shown by default; the
members' own `visible` flags don't apply.

### Physics

Verlet pendulum chains for hair / cloth / ribbons. An *input
parameter* (e.g. `ParamAngleX`) moves the chain's anchor
sideways; gravity + damping + per-particle springs pull the chain
back toward rest; the tip's sideways displacement maps back to an
*output parameter* (e.g. `ParamHairFront`), clamped to −1…1. At
rest the output equals the input, so the chain reads as a swing
that lags and overshoots whenever the input changes.

While the Puppet tab is shown and the rig has chains, the canvas
steps them about 60 times a second on a clock of its own, so they
keep swinging after the input stops. A chain's output overrides
any slider, motion or expression value on that parameter.
**Reset to rest** snaps every chain back to rest.

Chains come from a Cubism import (`.physics3.json`), from the PSD
auto-rig's hair rule, from a part template, or from **Tools > Physics
chains…**, which edits them: the input and output parameters, particle
count, length, stiffness, damping and gravity, with presets you can save and
reuse. It warns about chains that cannot work (a missing parameter, an output
that is also the input) and about settings that saturate the output, and
each change is one Undo step. Chains are stored in `physics.json` inside the
`.puppet` file.

### Editing meshes and weights

Turn on **Mesh > Edit mesh**, then:

- click a vertex to select it, **Shift**-click to add one, or drag over empty
  canvas to box-select (**Shift** adds to the selection);
- drag a selected vertex to move the whole selection;
- **Lock selected vertices** keeps them still while you drag the rest;
  **Unlock all vertices** releases them;
- **Show weights…** colours the mesh by one bone's weights;
  **Smooth weights**, **Normalize weights** and **Mirror weights left →
  right** edit the selection's bone weights;
- **Mirror selected vertices** and **Delete selected vertices…** change the
  mesh; deleting lists what it will affect (triangles, weights, morphs) before
  it runs.

Every edit is one Undo step.

### Organising deformers and parameters

The **Bones** dock lists deformers as a tree. Search by name, drag a row onto
another to change its parent (or onto empty space to detach it), move rows
with **Up** / **Down**, **Lock** a deformer so it cannot be reparented or
reordered, and **Hide** it from the list (**Show hidden** brings hidden rows back). A parent cycle is
shown as a warning naming the deformers involved.

The **Parameters** dock groups sliders into Head, Eyes, Mouth, Body, Hair and
Other, and **Filter parameters…** narrows the list. Each slider's **⋯** menu
has **Edit range…** (a range that would leave existing keys, blend keys or
expression values outside it is refused) and **Preview key forms**, which steps through the parameter's keys. **Reset all** returns every
slider to its default.

### Rig doctor and part templates

**Tools > Rig doctor…** checks the rig and groups what it finds by kind:
mesh problems (zero-area or broken triangles, duplicate or unused vertices),
bone weights that do not add up to 1, left/right drawables without a mirrored
partner, standard rigging the auto-rig would add (such as a head tilt or hair
swing), and everything **Validate** reports. Pick findings to see a preview of
each fix, then apply them together as one Undo step. The same
checks run from the command line with `rigora rig-doctor`.

**Tools > Part templates…** adds ready-made rigging to the drawables you
choose: **eye blink**, **mouth shapes**, **head turn** (it reuses an existing
head tilt instead of stacking a second one) and **sway**. The dialog shows
what each template will create and warns when it overlaps existing rigging.

### Expressions

Stacks of parameter overrides applied on top of slider / motion
values. Modes: `additive` (final = base + value), `multiply`
(final = base × value), `overwrite` (final = value). Toggle them
from the **Expressions** dock; active expressions apply in the
order they were switched on.

Used for momentary moods: *smile*, *surprised*, *angry*. The
bundled Imeru rig ships with 7 expressions (`smile` / `happy` /
`surprised` / `sad` / `angry` / `blush` / `sleepy`).

### Hit areas

Named click regions. A hit area's region is the bounding box of
its drawables at their current, deformed positions; left-clicking
inside one (with **Edit mesh** off) runs its actions. Its `motion`
names a motion group — a random motion of that group plays
(`TapHead` picks one of the `TapHead` motions); when no motion
carries that group, the motion of that name plays. Its `expression`
toggles that expression (click body → toggle `surprised`). Where
boxes overlap, the area with the frontmost drawable wins.

The bundled Imeru rig defines two: clicking her head (`Head`)
plays a `TapHead` motion and clicking her body (`Body`) a `TapBody`
motion. A rig converted with **File > Import Cubism…** brings
the model's `HitAreas` along as regions without actions; give
them a `motion` or `expression` in the `hit_areas` list of
`puppet.json` to make them respond. The Puppet tab has no
hit-area editor.

---

## Optional dependencies

The Puppet tab's core (rendering, parameter system, motion
playback, PNG / PSD / Cubism import) runs on the default
`requirements.txt` set. Heavier dependencies are loaded behind
`try / except` so the rest of the tab keeps working when they're
missing.

| Feature | Optional dep | Install |
|---|---|---|
| Webcam face tracking | `opencv-python` + `mediapipe` | `pip install opencv-python mediapipe` |
| Microphone lip-sync | `sounddevice` | `pip install sounddevice` |
| Virtual camera output | `pyvirtualcam` + platform driver | `pip install pyvirtualcam`, see Path A above |
| NDI output | `ndi-python` + NDI runtime + NDI SDK (build-time) | see Path B above |
| Cubism `.moc3` import | user-supplied Cubism Native SDK DLL | <https://www.live2d.com/sdk/about/> |
| Motion sound playback | `PySide6.QtMultimedia` | Usually ships with PySide6 — install via your platform's QtMultimedia package if missing |
| Animation export as GIF / MP4 / WebM | `imageio` + `imageio-ffmpeg` (in the `gui` extra) | `pip install "rigora[gui]"`; PNG sequences need neither |
| VTS API input | `PySide6.QtWebSockets` | Ships with PySide6 |
| Desktop pet global hotkeys | `pynput` | `pip install "rigora[hotkeys]"` |
| Desktop pet music rhythm | `sounddevice` with a WASAPI loopback device (Windows) | `pip install "rigora[lipsync]"` |
| Desktop pet LLM dialogue | A local [Ollama](https://ollama.com) server (or any HTTPS endpoint with the same API) | Installed separately; nothing is downloaded by Rigora |

Toggling a feature whose Python package is missing opens the
package installer for it and switches the feature on once the
install finishes. When the package is there but the device or
runtime fails (no microphone, no virtual-camera driver, no NDI
runtime), the toggle switches back off and the status bar says
why. There's also a one-shot **File > Install dependencies…**
action that batch-installs every optional Python package; the
Cubism SDK and NDI runtime have to be installed by hand because
of licensing.

---

## Keyboard shortcuts

| Keys | Action |
|---|---|
| **Ctrl+S** | Save (asks for a file the first time) |
| **Ctrl+Z** / **Ctrl+Shift+Z** | Undo / redo the last rig edit |
| **F2** | Rename the selected composition (Compositions dialog) |
| **Shift** + click or drag | Add to the vertex selection (Edit mesh) |

Everything else is on the menus and toolbar. The canvas takes these mouse
inputs:

| Input | Action |
|---|---|
| **Middle-button drag** | Pan |
| **Mouse wheel** | Zoom (cursor-anchored); **Tools > Fit to Window** re-fits |
| **Left-click** | Run the hit area under the cursor; with **Edit mesh** on, select the vertex within 8 px of the cursor (frontmost drawable first), or start a box selection on empty canvas |
| **Left-drag** | With **Edit mesh** on, move the selected vertices (locked ones stay put) |
| **Right-click** | Clear bone-selection overlay |

---

## Troubleshooting

### "Webcam tracking starts and nothing happens"

The preview window pops up showing the camera feed; if there's
no face visible, no parameters get driven. The preview's status
line shows *"No face in frame"*. Move into frame or improve
lighting.

If the preview is black: the camera is busy (another app has
it) or the OS denied camera access. macOS asks for camera
permission on first use — check System Settings → Privacy &
Security → Camera.

### "Webcam tracking keeps saying the camera was lost"

The camera stopped delivering frames — usually it was unplugged or another
app took it. Rigora retries after 1, 2, 4, 8 and 15 seconds and then waits;
**Output > Live status…** shows the countdown, and **Retry devices** tries
again at once. If access was denied, allow the camera in the system privacy
settings first. A failed face-model download is not retried automatically:
check the network and press **Retry devices**.

### "A tracker's values are ignored"

Open **Live > Input sources…**: another source probably controls the
parameter. A slider you are dragging, a playing motion and other plug-ins take
precedence over a VTS plug-in. A plug-in sending more than 120 requests a
second gets error 6000; a parameter held by another plug-in gives error 454.
See [VTS API support](docs/vts-api-support.md).

### "Export animation says a capability is missing"

PNG sequences need a desktop session with OpenGL; GIF needs `imageio`; MP4
and WebM need `imageio-ffmpeg`. From the command line this is exit status 4
with error code `capability_missing`. A cancelled or failed export never
leaves a partial file.

### "OBS shows magenta background"

By design — see Path A in the streaming section above. Add an
OBS Color Key filter on the *Video Capture Device* source with
`Custom Color = #FF00FF`.

### "ndi-python install fails with `cmake` not found"

`ndi-python` builds from source. Install CMake, the Visual
Studio C++ Build Tools, and the NDI SDK — see Path B prereqs.
If you don't need NDI specifically, use Path A (Virtual Camera).

### "Motion plays but rig stays at last pose afterwards"

With **Loop** off in the Motions dock, a motion that reaches its
end holds its last frame, and **Pause** holds the current pose.
**Stop** eases the motion's parameters back to their defaults over
the motion's fade-out (0.5 s unless the motion sets its own).
**Reset to rest** on the toolbar puts every parameter,
expression, pose group and physics chain back in one step.

### "My pet script was not loaded"

A script whose behavior rules have a problem is refused as a whole, and the
character keeps its previous script. Open **Edit script… > Behaviors** and
press **Check**: each problem names its place, for example
`rules[2].do[0]: unknown action 'shout'`.

### Cubism converter shows the camera as a "phantom hand"

The peace-sign / camera / face-cover gestures on converted Cubism
rigs are driven by Cubism dynamic-visibility flags. The converter
records those transitions as `opacity_keys` curves, so each prop
only appears while its parameter is up. If a converted `.puppet`
shows the props all the time, its drawables lack those curves —
re-convert via **File > Import Cubism…** and save the result.

---

## File format reference

The `.puppet` file format is a zip container with JSON manifests
and PNG textures. Full spec at
[`rigora/puppet/FORMAT.md`](rigora/puppet/FORMAT.md).

Bundled demo rig: [`examples/puppet/imeru.puppet`](examples/puppet/imeru.puppet), rebuilt
by `examples/puppet/imeru/build.py`
(see [`examples/puppet/README.md`](examples/puppet/README.md)).
