# Examples

Every example is built from files in this repository with the commands shown
below. `py -3 examples/run_examples.py` builds all of them into a temporary
folder and checks each expected result; add `--render` on a desktop with
OpenGL to include the video/frame export, which is otherwise reported as
skipped. All files here are part of Rigora and released under the
[MIT License](../LICENSE); Imeru is Rigora's own character (see
[`puppet/README.md`](puppet/README.md) and the
[artwork notes](puppet/imeru/artwork/README.md)).

## Basic rig

Turn one transparent PNG into an animatable rig with the standard parameters.

- **Source:** [`puppet/imeru/artwork/master.png`](puppet/imeru/artwork/master.png)
- **License:** MIT (Rigora)
- **Steps:**

  ```
  rigora puppet-from-png examples/puppet/imeru/artwork/master.png --destination basic.puppet --cell-size 64
  rigora puppet-inspect basic.puppet
  rigora puppet-validate basic.puppet --json
  rigora editor basic.puppet
  ```

- **Expected result:** a valid rig with one drawable and the standard
  parameters (27). In the editor, the Parameters dock moves the head, eyes and
  mouth regions of the single image.

## Advanced rigging

Imeru: one continuous body mesh, rotation and bone deformers, elbow bones,
three physics chains, hit areas, pose parts, 8 motions and 7 expressions.

- **Source:** [`puppet/imeru/`](puppet/imeru/) (build scripts and
  [artwork](puppet/imeru/artwork/)); built archive
  [`puppet/imeru.puppet`](puppet/imeru.puppet)
- **License:** MIT (Rigora)
- **Steps:**

  ```
  py -3 examples/puppet/imeru/build.py
  rigora puppet-inspect examples/puppet/imeru.puppet
  rigora rig-doctor examples/puppet/imeru.puppet
  rigora rig-doctor examples/puppet/imeru.puppet --fixes "[\"safe\"]" --destination imeru-checked.puppet
  ```

- **Expected result:** 23 drawables, 6 deformers and 3 physics chains; the rig
  doctor reports no errors (one informational finding), and the repaired copy
  validates. Open it and use **Tools > Rig doctor…**, **Physics chains…** and
  **Part templates…** to see the same checks in the editor.

## Animation production

Arrange Imeru's existing motions in a composition, bake it into a motion and
render it.

- **Source:** [`puppet/imeru.puppet`](puppet/imeru.puppet); the composition is
  created by `animation()` in [`run_examples.py`](run_examples.py)
- **License:** MIT (Rigora)
- **Steps:** in the editor, **Edit > Compositions… > New**, add a `body`
  layer with `idle_breath` (looping, 4 s) and `wave` (start 0.5 s, fades
  0.3 s), and an additive `face` layer at weight 0.6 with `greet`; press
  **Save and bake into motion**, then **Output > Export animation…**. The same
  from the command line, after saving the rig with the composition:

  ```
  rigora bake-composition imeru-hello.puppet --composition hello --destination imeru-hello-baked.puppet
  rigora export-animation imeru-hello-baked.puppet --motion "hello (baked)" --destination hello-frames --width 256 --height 416 --fps 12
  ```

- **Expected result:** a 4-second motion `hello (baked)` driving 12
  parameters, and 48 transparent PNG frames (4 s × 12 fps; the end time is
  not a frame).

## Live streaming

Drive the rig from an external tracker over the VTS API and tune live input.

- **Source:** [`live/vts_client.py`](live/vts_client.py) (a minimal tracker)
  and [`live/desk.input-profile.json`](live/desk.input-profile.json) (an input
  profile)
- **License:** MIT (Rigora)
- **Steps:** open Imeru, turn on **Output > VTS API**, then run
  `py -3 examples/live/vts_client.py --seconds 10`. Open **Live > Input
  sources…** while it runs. To try the input profile, copy its values into
  **Live > Input devices and calibration…**.
- **Expected result:** the head sways for ten seconds; Input sources shows
  `ParamAngleX` and `ParamAngleY` controlled by *External plug-in (Rigora
  example tracker)*; dragging the slider takes over and the plug-in's next
  writes are refused until you let go. The check in `run_examples.py` sends
  the same messages in process and expects the head angle to move.

## Desktop pet scripts

Two scripts for the desktop companion: Imeru's voice lines, and a script with
behavior rules (clicks, a mood state, drops, music beats, a nap after ten idle
minutes, a weekday stretch reminder).

- **Source:** [`desktop_pet/imeru.petscript.json`](desktop_pet/imeru.petscript.json),
  [`desktop_pet/greeter.petscript.json`](desktop_pet/greeter.petscript.json)
- **License:** MIT (Rigora)
- **Steps:** **Desktop Pet > Load bundled Imeru**, then **Pet script > Load
  script…** and pick a file. Open **Edit script… > Behaviors**, press
  **Check**, then **Preview events** with the default event list.
- **Expected result:** both scripts load with no problems against Imeru.
  With the greeter, a head click says "Hehe", plays a `TapHead` motion and
  makes the character happy for 20 seconds; a second click while happy says
  "Again?". See the [desktop companions guide](../docs/desktop-companions.md).

## Extensions

[`extensions/example_adapter.py`](extensions/example_adapter.py) shows how a
host application uses the versioned host API; it is covered by
`tests/test_host_contract.py`.
