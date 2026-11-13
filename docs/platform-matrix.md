# Platform capability matrix

Updated 2026-11-12. Support is claimed only where a check below ran. "CI
offscreen" means the test suite passed with `QT_QPA_PLATFORM=offscreen`, which
skips every native OpenGL widget test — it is not rendering evidence.

| Capability | Windows 11 | Linux | macOS |
| --- | --- | --- | --- |
| Core: model, archive, runtime, CLI, MCP (no Qt) | Verified: local suite, clean wheel in a read-only directory, remote CI (3.11, 3.13) | CI offscreen (Ubuntu, 3.12) at `88b3ebf` | Not verified |
| GUI editor widgets | Verified: offscreen suite and hidden native editor | CI offscreen only | Not verified |
| Native OpenGL rendering | Verified on NVIDIA RTX 5060 Laptop, OpenGL 4.6 (hidden window): editor flows, extreme poses, masks, context rebuild | Not verified | Not verified |
| GPU performance numbers | Measured on the machine above only ([verification record](r2-r8-verification.md)) | Not measured | Not measured |
| Desktop pet: control page, scripts, behavior rules, several characters | Verified: offscreen tests, hidden control page, two hidden native character windows (start/stop, outfit and script changes, full close) | CI offscreen only | Not verified |
| Desktop pet: visible transparent window, click-through, tray, multi-monitor placement | Recovery decisions tested with geometry stand-ins; not verified on a visible desktop or real monitors | Not verified | Not verified |
| Webcam tracking | Calibration, arbitration and device recovery run in the hidden editor with scripted capture; no camera opened | Not verified | Not verified |
| Microphone lip-sync | Lip-sync and reconnect run in the hidden editor with scripted audio blocks; no microphone opened | Not verified | Not verified |
| Global hotkeys | Conflict detection tested; no system hook installed | Not verified | Not verified |
| Virtual camera output | Hidden GL frames through the bounded send queue to a stand-in driver; no real receiver | Not verified | Not verified |
| NDI output | Frame pipeline tested; no receiver | Not verified | Not verified |
| VTS-compatible API | Loopback WebSocket clients in the hidden editor: tokens, injection, rate limits, origin refusal | CI offscreen only | Not verified |
| Portable EXE (Nuitka) | Built and smoke-checked by the release workflow | Not provided | Not provided |

## What each status needs to change

- **Linux native GL**: run `scripts/verify_gui.py`-equivalent checks on a
  desktop session with a real GL driver; the current verifier uses Windows
  window APIs to prove the window stayed hidden.
- **macOS**: no CI job or machine yet. Add a CI job for core and offscreen GUI
  first, then a machine check for GL. Rigora draws with the fixed-function
  pipeline, which macOS offers only through its deprecated legacy OpenGL 2.1
  context, so whether the canvas renders there is unknown until tested.
- **Devices and outputs**: need real cameras, microphones and receivers
  (OBS Virtual Camera, an NDI receiver) attended by a person, because the
  verification rules forbid opening devices or visible windows in background
  runs. See the R4 / R5 records for what was checked without them.
