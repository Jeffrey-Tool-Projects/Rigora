"""R5 acceptance with real, natively hidden pet windows, invoked by verify_gui.py.

Two companion characters run as real :class:`PetWindow` objects with their
own GL contexts, kept off the desktop with ``WA_DontShowOnScreen``. Checks:
independent start/stop, changing outfit (rig) and script, located script
errors, repeated schedules and self-triggering rules staying bounded, an
unreachable local LLM backing off instead of retrying forever, hidden pause,
idle frame pacing, screen recovery and that a full close leaves no timers or
threads. Native placement on real monitors, click-through and the tray are
not covered and stay a hands-on check.
"""
from __future__ import annotations

import ctypes
import json
import socket
import threading
import time
from pathlib import Path


def _require(value, message):
    if not value:
        raise RuntimeError(message)


def _pump(app, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def _hidden_window(pet_id):
    from PySide6.QtCore import Qt

    from rigora.desktop_pet.pet_window import PetWindow
    window = PetWindow(pet_id)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    return window


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def check_pet_workflow(window, root: Path) -> dict:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from rigora.desktop_pet import pet_roster
    from rigora.desktop_pet import settings as pet_settings
    from rigora.desktop_pet.pet_companions import CompanionManager
    from rigora.desktop_pet.pet_placement import collect_screens
    from rigora.desktop_pet.pet_resources import shared_rigs
    from rigora.system.app_paths import examples_dir

    app = QApplication.instance()
    report: dict = {}
    threads_before = threading.active_count()
    imeru = examples_dir() / "puppet" / "imeru.puppet"
    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    manager = CompanionManager(window_factory=_hidden_window, screens=collect_screens)
    ids = [pet_roster.add_character(name) for name in ("Verify A", "Verify B")]
    try:
        for pet_id in ids:
            # Speech bubbles are separate top-level windows: keep them off so
            # nothing appears on the desktop during verification.
            pet_settings.update(pet_id, last_rig_path=str(imeru), speech_enabled=False,
                                llm_base_url=f"http://127.0.0.1:{_closed_port()}")
        hits = shared_rigs.hits
        pets = {pet_id: manager.start(pet_id) for pet_id in ids}
        _pump(app, 1.0)
        for pet_id, pet in pets.items():
            _require(not user32.IsWindowVisible(int(pet.winId())),
                     f"pet {pet_id} became desktop-visible")
            _require(pet.document() is not None and len(pet.document().drawables) == 23,
                     f"pet {pet_id} did not load its rig")
        a, b = (pets[i] for i in ids)
        _require(shared_rigs.hits > hits, "the second character re-parsed the rig")
        _require(next(iter(a.document().textures.values()))
                 is next(iter(b.document().textures.values())),
                 "texture bytes are not shared between characters")
        stats = manager.stats()
        _require(all(s["gl_textures"] > 0 for s in stats.values()),
                 f"a character has no GL textures: {stats}")
        report["started"] = {pid: {k: s[k] for k in ("drawables", "texture_bytes",
                                                      "gl_textures", "active_timers")}
                             for pid, s in stats.items()}

        # Outfit change on B only.
        saved = root / "imeru-roundtrip.puppet"
        target = saved if saved.is_file() else imeru
        _require(manager.change_rig(ids[1], target), "rig change failed")
        _require(a.document() is not b.document(), "characters share one document")
        report["rig_changed"] = str(target.name)

        # Script with behaviors on B; a broken script is refused and B keeps its rules.
        script = root / "verify.petscript.json"
        script.write_text(json.dumps({"behaviors": {"rules": [
            {"id": "pat", "on": "click:*", "cooldown": 2, "do": [{"motion_group": "Idle"},
                                                                  {"wait": 30},
                                                                  {"say": "later"}]},
            {"id": "tick", "on": "every:0.2", "max_per_minute": 3, "do": [{"say": "."}]},
            {"id": "echo", "on": "ping", "do": [{"say": "x"}, {"emit": "ping"}]}]}}),
            encoding="utf-8")
        _require(manager.change_script(ids[1], script), "behavior script was refused")
        broken = root / "broken.petscript.json"
        broken.write_text(json.dumps({"behaviors": {"rules": [
            {"on": "click:*", "do": [{"run": "cmd"}]}]}}), encoding="utf-8")
        _require(not b.load_script_file(broken), "a broken script was accepted")
        _require(b.behavior_engine().active, "the refused script replaced the good one")
        steps = b.fire_behavior("click:head")
        _require([s.kind for s in steps] == ["motion_group", "say"]
                 and b.pending_behavior_actions() == 1, "click rule did not run")
        echo = b.fire_behavior("ping")
        _require(0 < len(echo) <= 8, f"self-triggering rule was not bounded ({len(echo)})")
        fired = 0
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            fired += len(b.behavior_engine().tick())
            _pump(app, 0.05)
        _require(fired <= 3, f"a repeating schedule ran {fired} times in a minute")
        b.stop_behaviors()
        _require(b.pending_behavior_actions() == 0 and b.fire_behavior("click:head") == [],
                 "safe stop left actions running")
        report["behaviors"] = {"click": True, "echo_steps": len(echo),
                               "schedule_runs_in_2_5s": fired, "safe_stop": True,
                               "broken_script_refused": True}

        # Unreachable local LLM: three failures, then offline without network traffic.
        _require(b.set_llm_dialogue_enabled(True), "LLM dialogue could not be enabled")
        attempts = 0
        deadline = time.monotonic() + 20
        while b._llm.status()[0] != "offline" and time.monotonic() < deadline:   # noqa: SLF001
            b._llm.request_line("greeting")   # noqa: SLF001
            attempts += 1
            _pump(app, 0.5)
        _pump(app, 3.0)                       # let replaced requests finish failing
        client = b._llm._client   # noqa: SLF001
        before = client._failures   # noqa: SLF001
        for _ in range(5):                    # while offline: refused without network
            b._llm.request_line("greeting")   # noqa: SLF001
        _pump(app, 0.5)
        _require(client._failures == before, "an offline server was contacted again")  # noqa: SLF001
        report["llm_attempts_before_offline"] = attempts
        state, detail = b._llm.status()   # noqa: SLF001
        _require(state == "offline", f"LLM state after failures: {state} {detail}")
        report["llm_offline_backoff"] = state

        # Stopping A leaves B running.
        manager.stop(ids[0])
        _pump(app, 0.3)
        _require(manager.running() == [ids[1]], "stopping A affected B")
        _require(b.resource_stats()["gl_textures"] > 0 and b._tick.isActive(),   # noqa: SLF001
                 "B lost its resources when A stopped")
        report["independent_stop"] = True

        # Hidden pause and idle pacing.
        b.hide()
        _pump(app, 0.2)
        paused = len(b._paused_while_hidden)   # noqa: SLF001
        _require(paused > 0 and not b._tick.isActive(), "hidden character kept animating")  # noqa: SLF001
        b.show()
        _pump(app, 0.3)
        _require(not b._paused_while_hidden, "drivers were not resumed")   # noqa: SLF001
        b._pacer.last_activity -= 60   # noqa: SLF001 - a minute without activity
        b._apply_frame_pacing()   # noqa: SLF001
        _require(b._tick.interval() == 66, "idle character kept 30 fps")   # noqa: SLF001
        report["hidden_pause_timers"] = paused
        report["idle_frame_interval_ms"] = b._tick.interval()   # noqa: SLF001

        # Screen recovery: a character left far off-screen comes back.
        b.move(100000, 100000)
        outcome = manager.revalidate("verify")
        _require(outcome.get(ids[1]) in ("moved", "default"), f"not recovered: {outcome}")
        screens = collect_screens()
        _require(any(s.available.x <= b.x() < s.available.right for s in screens),
                 "character still off-screen")
        report["screen_recovery"] = outcome[ids[1]]
        bubbles = [w for w in app.topLevelWidgets()
                   if type(w).__name__ == "SpeechBubble" and w.isVisible()]
        _require(not bubbles, "a speech bubble was shown on the desktop")
    finally:
        manager.shutdown()
        _pump(app, 0.5)
        for pet_id in ids:
            pet_roster.remove_character(pet_id)
    leftover = [t for t in app.allWidgets() if type(t).__name__ == "PetWindow"
                and not getattr(t, "_shutdown_complete", False)]
    timers = [t for w in app.allWidgets() if type(w).__name__ == "PetWindow"
              for t in w.findChildren(QTimer) if t.isActive()]
    _pump(app, 1.0)
    extra_threads = threading.active_count() - threads_before
    report["full_close"] = {"windows_left": len(leftover), "timers_left": len(timers),
                            "extra_threads": extra_threads}
    _require(not leftover and not timers, f"characters left behind: {report['full_close']}")
    _require(extra_threads <= 0, f"{extra_threads} threads still running")
    return report
