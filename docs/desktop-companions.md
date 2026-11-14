---
title: Desktop companions
description: Several characters on the desktop, behavior rules, local LLM dialogue, screens and resource use.
permalink: /desktop-companions/
---

The **Desktop Pet** tab puts a rigged character on the desktop. This page
covers running several characters, scripting what they do, the optional
local LLM, and how they behave across monitors and while idle.

## Several characters

Open the **Characters** tab.

| Button | What it does |
| --- | --- |
| **Add…** | Creates a character. When a character is selected, its look and behaviour settings are copied (not its position). |
| **Remove** | Deletes only that character's settings. Other characters keep running. The main character cannot be removed, only stopped. |
| **Start / stop** | Starts or stops the selected character. Each runs in its own window with its own rig copy, script and timers, so stopping one does not affect the others. |
| **Copy settings from…** | Copies size, opacity, drivers, script, dialogue and sound settings from another character. |
| **Change rig…** / **Change script…** | Swaps that character's outfit or script while it runs. A script with a broken rule is refused and the old one stays. |
| **Save layout…** / **Restore layout…** | Remembers which characters run and where they stand; restoring starts and stops characters to match. Characters added after the layout was saved stay stopped. |
| **Stop behaviors** | Halts the selected character's behavior rules at once, including actions that are still waiting. |

Below the buttons, the tab shows what the selected character uses: drawables,
texture memory, GL textures and buffers, running timers and its current frame
interval. Characters that show the same `.puppet` file share its decoded
textures; changing one character's outfit does not change the others.

## Screens, scaling and sleep

Each character's position is stored both in pixels and relative to the work
area of its monitor (the screen minus the taskbar). When a monitor is
unplugged, a resolution or scaling setting changes, the taskbar moves, or the
computer wakes from sleep, Rigora checks every character:

- a character still at least half on a work area is pulled fully inside it;
- a character whose monitor is gone moves to the same relative spot on the
  monitor it was saved on, or on the primary monitor;
- a character with no saved position goes to the bottom-right corner.

*Hide on full-screen apps* still hides a character while a full-screen
program covers its monitor.

## Behavior rules

A pet script (`.petscript.json`) can have a `behaviors` section: rules that
react to events. Edit it in **Edit script… ▸ Behaviors**. **Check** lists every
problem with its place, such as `rules[2].do[0]: unknown action 'shout'` or the
line and column of a JSON mistake, and also warns about rules that cannot fire
as set up (a hit area the rig lacks, a hotkey action without a key or with a
clashing key, `beat` while music rhythm is off). **Preview events** runs a
list of simulated events — one `<seconds> <event>` per line, `tick` to advance
timed rules — and shows which rule ran, which were skipped and why, and the
state afterwards. A preview presses no keys, plays nothing and says nothing.

```json
{"behaviors": {
  "initial": "idle", "states": ["idle", "happy"],
  "rules": [
    {"id": "pat", "on": "click:Head", "when": {"state": "idle"}, "priority": 10,
     "cooldown": 4, "do": [{"say": "Hehe"}, {"motion_group": "TapHead"}, {"state": "happy"}]},
    {"id": "calm", "on": "state:happy", "do": [{"wait": 20}, {"state": "idle"}]}
  ]}}
```

A complete example is [`examples/desktop_pet/greeter.petscript.json`](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/examples/desktop_pet/greeter.petscript.json).

| Events | When |
| --- | --- |
| `start` | The script is loaded |
| `click:<hit area>`, `click:*` | A hit area is clicked (`*` matches any click) |
| `drop:puppet`, `drop:file` | A rig or another file is dropped on the character |
| `hotkey:<action>` | A global hotkey action fires |
| `beat` | Music rhythm hears a beat |
| `every:<seconds>` | Repeatedly |
| `at:HH:MM` | Once a day at that time |
| `idle:<seconds>` | After that long without clicks, drops, hotkeys or rule activity |
| `state:<name>` | The state machine enters `<name>` |
| any other name | Another rule `emit`s it |

Conditions under `when` must all hold: `state`, `hours` `[start, end]`,
`weekdays` (0 is Monday) and `chance` (0–1). Actions in `do` run in order:
`say`, `motion`, `motion_group`, `expression`, `state`, `emit` and `wait`
(seconds, at most 600; later actions wait with it).

Rules cannot run away:

- for one event only the highest-`priority` rule whose conditions hold runs;
- each rule has a `cooldown` and may run at most `max_per_minute` times
  (30 unless set);
- events that rules `emit` nest at most four deep, and one event performs at
  most 32 actions, so a rule that triggers itself stops;
- a script whose rules have any problem is not loaded.

## Local LLM dialogue

With *LLM dialogue* on, a click can also ask a local model (Ollama on
`http://localhost:11434` by default; remote servers must use HTTPS) for a fresh
line. The Characters tab shows the connection state for the selected
character and has **Check connection**, **Cancel reply** and **Clear
history**.

- Only the newest request's reply is shown; **Cancel reply** drops it.
- After three failed requests the server counts as offline for 30 seconds:
  requests fail at once without contacting it, so a stopped server never
  causes a retry loop.
- *Keep conversation history between sessions* is off by default. When it is
  on, recent lines are saved with the character's settings and given to the
  model so it repeats itself less; turning it off or **Clear history**
  deletes them.
- A reply can ask for at most two of the character's **own** motions, motion
  groups or expressions with tags such as `[motion:Wave]`. Any other tag is
  removed, the text is shortened to 200 characters, and nothing in a reply is
  run as a command.

## Resource use

A character repaints at 30 fps while you interact with it, it speaks or a
rule runs, and at 15 fps after ten quiet seconds (idle breathing and idle
motions keep moving). A hidden character does not repaint, and its idle,
blink and gaze timers pause until it is shown again. Stopping a character,
or closing Rigora, shuts down its timers, audio, hotkey hook, network
clients and worker threads.

## What is checked automatically

Automated checks run real characters in hidden windows. They do not move
characters on physical monitors, test click-through or the system tray, or
press global keys. Those need a hands-on check on the target desktop.
