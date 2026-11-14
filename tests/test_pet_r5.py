"""R5: several characters, screen recovery, behavior rules, LLM safety and resources.

Windows here are stand-ins: the native placement, click-through and tray
behaviour of real desktop windows are not covered by these tests.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from rigora.desktop_pet import pet_roster
from rigora.desktop_pet import settings as pet_settings
from rigora.desktop_pet.edge_snap import Rect, ScreenInfo
from rigora.desktop_pet.pet_behavior import (
    MAX_DEPTH,
    BehaviorEngine,
    overview,
    parse_simulation,
    validate,
)
from rigora.desktop_pet.pet_resources import FramePacer, RigCache, texture_bytes
from rigora.desktop_pet.pet_screens import SleepCheck, from_relative, recover, \
    relative_position


@pytest.fixture
def store(tmp_path):
    from rigora.system import settings
    settings.configure(tmp_path / "settings.json", autosave=False)
    yield settings.user_setting_dict


# ---- R5.1 roster ------------------------------------------------------------------


def test_add_copy_enable_and_remove_characters_independently(store):
    pet_settings.update(pet_settings.DEFAULT_PET_ID, size_preset="large", opacity=0.5,
                        last_rig_path="main.puppet", position=[10, 20])
    first = pet_roster.add_character("Sora", copy_from=pet_settings.DEFAULT_PET_ID)
    second = pet_roster.add_character("Sora")
    assert (first, second) == ("sora", "sora-2")
    copied = pet_settings.load(first)
    assert copied["size_preset"] == "large" and copied["last_rig_path"] == "main.puppet"
    assert copied["position"] == [-1, -1]                      # placement is not copied
    pet_roster.set_enabled(second, True)
    names = {c.id: (c.name, c.enabled) for c in pet_roster.characters()}
    assert names[first] == ("Sora", False) and names[second] == ("Sora", True)
    assert pet_roster.remove_character(first)
    assert pet_settings.load(second)["enabled"] is True        # untouched
    assert not pet_roster.remove_character(pet_settings.DEFAULT_PET_ID)
    with pytest.raises(ValueError):
        pet_roster.add_character("  ")
    with pytest.raises(KeyError):
        pet_roster.set_enabled("ghost", True)


def test_layouts_restore_running_set_and_positions(store):
    pet = pet_roster.add_character("Kumo")
    pet_roster.set_enabled(pet, True)
    pet_settings.update(pet, position=[300, 400], screen_name="DISPLAY2")
    pet_roster.save_layout("stream")
    pet_settings.update(pet, position=[1, 1], enabled=False)
    late = pet_roster.add_character("Late")
    pet_roster.set_enabled(late, True)
    running = pet_roster.restore_layout("stream")
    assert pet in running and late not in running
    assert pet_settings.load(pet)["position"] == [300, 400]
    assert pet_settings.load(late)["enabled"] is False
    pet_roster.remove_character(pet)
    assert pet not in pet_roster.restore_layout("stream")      # removed since: skipped
    assert pet_roster.delete_layout("stream") and pet_roster.layout_names() == []


def test_companion_manager_stops_only_one_window(store):
    from rigora.desktop_pet.pet_companions import CompanionManager

    class Window:
        def __init__(self, pet_id):
            self.pet_id, self.calls, self.pos = pet_id, [], (0, 0)

        def load_puppet_file(self, path):
            self.calls.append(("rig", path))
            return True

        def load_script_file(self, path):
            self.calls.append(("script", path))
            return True

        def shutdown(self):
            self.calls.append("shutdown")

        def close(self):
            self.calls.append("close")

        def deleteLater(self):   # noqa: N802 - Qt API
            pass

        def x(self):
            return self.pos[0]

        def y(self):
            return self.pos[1]

        def width(self):
            return 100

        def height(self):
            return 100

        def move(self, x, y):
            self.pos = (x, y)

        def resource_stats(self):
            return {"pet_id": self.pet_id}

    made = {}
    screens = [ScreenInfo("A", Rect(0, 0, 1000, 800))]
    manager = CompanionManager(window_factory=lambda pid: made.setdefault(pid, Window(pid)),
                               show=False, screens=lambda: screens)
    one, two = pet_roster.add_character("One"), pet_roster.add_character("Two")
    pet_settings.update(one, last_rig_path="one.puppet")
    manager.start(one)
    manager.start(two)
    assert made[one].calls == [("rig", "one.puppet")]
    manager.change_script(two, "two.json")
    manager.stop(one)
    assert "shutdown" in made[one].calls and "shutdown" not in made[two].calls
    assert manager.running() == [two] and pet_settings.load(one)["enabled"] is False
    made[two].pos = (5000, 5000)                                # its screen went away
    assert manager.revalidate("screen_removed") == {two: "default"}
    assert 0 <= made[two].pos[0] <= 900 and 0 <= made[two].pos[1] <= 700
    assert manager.stats() == {two: {"pet_id": two}}
    with pytest.raises(ValueError):
        manager.start(pet_settings.DEFAULT_PET_ID)
    manager.shutdown()
    assert manager.running() == []


# ---- R5.2 screens -----------------------------------------------------------------


def test_recover_keeps_clamps_moves_and_handles_no_screen():
    left = ScreenInfo("L", Rect(0, 0, 1920, 1040))
    right = ScreenInfo("R", Rect(1920, 0, 2560, 1400))
    pet = Rect(100, 100, 200, 200)
    assert recover(pet, [left, right]) .reason == "kept"
    clamped = recover(Rect(1750, 880, 200, 200), [left])      # 68 % still visible
    assert clamped.reason == "clamped" and (clamped.x, clamped.y) == (1720, 840)
    gone = Rect(3000, 500, 200, 200)                            # right screen unplugged
    relative = relative_position(gone, right)
    moved = recover(gone, [left], saved_screen="R", relative=relative)
    assert moved.reason == "moved" and moved.screen == "L"
    assert (moved.x, moved.y) == from_relative(relative, 200, 200, left)
    assert recover(pet, []) is None


def test_relative_position_survives_a_resolution_or_dpi_change():
    before = ScreenInfo("A", Rect(0, 0, 1920, 1040))
    after = ScreenInfo("A", Rect(0, 0, 1280, 680))              # 150 % scaling
    pet = Rect(1720, 840, 200, 200)                             # bottom-right corner
    rel = relative_position(pet, before)
    x, y = from_relative(rel, 200, 200, after)
    assert (x, y) == (1080, 480)                                # still bottom-right
    assert recover(pet, [after], saved_screen="A", relative=rel).x == 1080


def test_sleep_check_reports_a_wall_clock_jump_once():
    mono, wall = [0.0], [1000.0]
    check = SleepCheck(gap=5, clock=lambda: mono[0], wall=lambda: wall[0])
    mono[0] += 1
    wall[0] += 1
    assert not check.woke()
    wall[0] += 3600
    assert check.woke() and not check.woke()


# ---- R5.3 / R5.4 behaviors ---------------------------------------------------------

RULES = {
    "initial": "idle", "states": ["idle", "happy"],
    "rules": [
        {"id": "pat", "on": "click:head", "when": {"state": "idle"}, "priority": 5,
         "cooldown": 3, "do": [{"say": "hehe"}, {"motion": "Nod"}, {"state": "happy"}]},
        {"id": "pat_happy", "on": "click:head", "when": {"state": "happy"},
         "do": [{"expression": "smile"}]},
        {"id": "any", "on": "click:*", "priority": -1, "do": [{"say": "?"}]},
        {"id": "calm", "on": "state:happy", "do": [{"wait": 5}, {"state": "idle"}]},
    ]}


def engine(rules=RULES, **kwargs):
    clock = [100.0]
    eng = BehaviorEngine(rules, clock=lambda: clock[0],
                         now=kwargs.get("now", lambda: datetime(2026, 1, 5, 10, 0)))
    return eng, clock


def test_priority_conditions_cooldown_and_state_transitions():
    eng, clock = engine()
    steps = eng.fire("click:head")
    assert [(s.kind, s.value, s.delay) for s in steps] == [
        ("say", "hehe", 0), ("motion", "Nod", 0), ("state", "happy", 0), ("state", "idle", 5)]
    assert eng.state == "happy"          # the change back to idle waits 5 s
    assert eng.tick() == [] and eng.state == "happy"
    clock[0] += 5
    eng.tick()
    assert eng.state == "idle"
    eng.state = "happy"
    assert [s.value for s in eng.fire("click:head")] == ["smile"]
    eng.stop()
    eng.resume()                                                   # drops the pending change
    eng.state = "idle"
    assert eng.fire("click:head")[0].value == "hehe"              # pat runs (t = 105)
    eng.stop()
    eng.resume()
    eng.state = "idle"
    clock[0] += 1
    assert [s.value for s in eng.fire("click:head")] == ["?"]     # pat cooling down
    assert eng.fire("click:tail")[0].value == "?" or eng.trace[-1].outcome == "skipped"
    clock[0] += 3
    assert eng.fire("click:head")[0].value == "hehe"


def test_self_triggering_rules_stop_at_the_chain_and_rate_limits():
    loop = {"rules": [{"id": "echo", "on": "ping", "do": [{"say": "x"}, {"emit": "ping"}]}]}
    eng, clock = engine(loop)
    steps = eng.fire("ping")
    assert len([s for s in steps if s.kind == "say"]) == MAX_DEPTH
    assert any("chain deeper" in t.detail for t in eng.trace)
    flood = {"rules": [{"id": "f", "on": "beat", "max_per_minute": 3, "do": [{"say": "b"}]}]}
    eng, clock = engine(flood)
    said = 0
    for _ in range(10):
        clock[0] += 1
        said += len(eng.fire("beat"))
    assert said == 3


def test_safe_stop_blocks_everything_until_resumed():
    eng, _clock = engine()
    eng.stop()
    assert eng.fire("click:head") == [] and eng.trace[-1].outcome == "blocked"
    assert eng.tick() == []
    eng.resume()
    assert eng.fire("click:head")


def test_timed_events_every_at_and_idle():
    rules = {"rules": [
        {"id": "e", "on": "every:10", "do": [{"say": "ten"}]},
        {"id": "a", "on": "at:10:00", "do": [{"say": "ten o'clock"}]},
        {"id": "i", "on": "idle:30", "do": [{"motion_group": "Idle"}]}]}
    eng, clock = engine(rules)
    assert [s.value for s in eng.tick()] == ["ten o'clock"]     # at most once a day
    assert eng.tick() == []
    clock[0] += 10
    assert [s.value for s in eng.tick()] == ["ten"]
    clock[0] += 25
    assert [s.value for s in eng.tick()] == ["ten", "Idle"]


def test_validation_names_where_each_problem_is():
    bad = {"initial": "sleepy", "states": ["idle"], "rules": [
        {"id": "a", "on": "click:tail", "do": [{"shout": "x"}]},
        {"id": "a", "on": "at:25:00", "when": {"hours": [1]}, "do": []},
        {"on": "beat", "cooldown": -1, "do": [{"motion": "Missing"}, {"wait": 9999}]}]}
    problems = {p.path: p.message for p in validate(
        bad, motions={"Nod"}, hit_areas={"head"})}
    assert problems["initial"].startswith("'sleepy'")
    assert "no hit area" in problems["rules[0].on"]
    assert "unknown action" in problems["rules[0].do[0]"]
    assert "duplicate id" in problems["rules[1].id"]
    assert "unknown event" in problems["rules[1].on"]
    assert "rules[1].when.hours" in problems and "rules[1].do" in problems
    assert "rules[2].cooldown" in problems and "unknown motion" in problems["rules[2].do[0]"]
    assert "wait must be" in problems["rules[2].do[1]"]
    with pytest.raises(ValueError):
        BehaviorEngine(bad)


def test_preview_simulates_without_side_effects_and_reports_input_errors():
    events, problems = parse_simulation("0 click:head\n1 click:head # cooling\nx bad\n2\n")
    assert events == [(0.0, "click:head"), (1.0, "click:head")]
    assert [p.path for p in problems] == ["line 3", "line 4"]
    eng, _clock = engine()
    trace = eng.simulate(events)
    assert [t.rule for t in trace if t.outcome == "ran"][:2] == ["pat", "calm"]


def test_overview_flags_zones_hotkeys_and_music():
    rules = {"rules": [{"id": "h", "on": "hotkey:speak", "do": [{"say": "x"}]},
                       {"id": "h2", "on": "hotkey:wave", "do": [{"say": "x"}]},
                       {"id": "z", "on": "click:tail", "do": [{"say": "x"}]},
                       {"id": "m", "on": "beat", "do": [{"say": "x"}]}]}
    notes = overview(rules, hit_areas={"head"},
                     hotkeys={"speak": "ctrl+shift+p", "other": "shift+ctrl+p"})
    joined = " | ".join(notes)
    assert "clashes" in joined and "'wave' has no key" in joined
    assert "no hit area 'tail'" in joined and "music rhythm is off" in joined


def test_scripts_with_broken_rules_are_refused_with_the_location(tmp_path):
    from rigora.desktop_pet.pet_script import PetScriptEngine, PetScriptError, load_script
    path = tmp_path / "bad.petscript.json"
    path.write_text(json.dumps({"greetings": ["hi"], "behaviors": {"rules": [
        {"on": "click:*", "do": [{"run": "calc.exe"}]}]}}), encoding="utf-8")
    with pytest.raises(PetScriptError, match=r"rules\[0\]\.do\[0\]: unknown action 'run'"):
        load_script(path)
    good = tmp_path / "good.petscript.json"
    good.write_text(json.dumps({"behaviors": RULES}), encoding="utf-8")
    script = load_script(good)
    assert script.to_dict()["behaviors"] == RULES
    engine_ = PetScriptEngine(script)
    assert engine_.behaviors.active and engine_.behaviors.fire("click:head")


def test_behavior_editor_checks_and_previews(qapp):
    from rigora.desktop_pet.pet_behavior_editor import BehaviorEditor
    editor = BehaviorEditor(RULES, {"hit_areas": {"head"}, "motions": {"Nod"}})
    assert editor.check() == [] and "No problems" in editor.report.toPlainText()
    trace = editor.preview()
    assert trace and "pat" in editor.report.toPlainText()
    editor.text.setPlainText('{"rules": [\n  {"on": }\n]}')
    problems = editor.check()
    assert problems[0].path.startswith("line 2")
    with pytest.raises(ValueError):
        editor.behaviors()
    editor.text.setPlainText('{"initial": "idle", "rules": []}')
    assert editor.behaviors() is None
    editor.deleteLater()


def test_pet_window_runs_and_cancels_delayed_actions(qapp):
    from rigora.desktop_pet.pet_behavior import Step
    from rigora.desktop_pet.pet_window_behavior import PetWindowBehaviorMixin
    from PySide6.QtWidgets import QWidget

    class Host(PetWindowBehaviorMixin, QWidget):
        def __init__(self):
            super().__init__()
            self._init_behaviors()
            self.done = []
            self._script_engine = SimpleNamespace(behaviors=BehaviorEngine(RULES))
            self._canvas = SimpleNamespace(active_expressions=lambda: [],
                                           add_expression=lambda n: self.done.append(("e", n)))

        def _show_speech(self, text):
            self.done.append(("say", text))

        def _play_motion_by_name(self, name):
            self.done.append(("motion", name))

        def play_random_motion_in_group(self, group):
            self.done.append(("group", group))

    host = Host()
    host.fire_behavior("click:head")
    assert host.done == [("say", "hehe"), ("motion", "Nod")]
    assert host.pending_behavior_actions() == 1                 # the 5 s "calm" step
    host.stop_behaviors()
    assert host.pending_behavior_actions() == 0 and host.fire_behavior("click:head") == []
    host._perform_behavior_step(Step("expression", "smile"))    # noqa: SLF001
    assert host.done[-1] == ("e", "smile")
    host.deleteLater()


def test_music_rhythm_emits_a_beat_on_a_sharp_rise(qapp):
    from rigora.desktop_pet.music_rhythm import MusicRhythmDriver
    canvas = SimpleNamespace(document=lambda: object(), parameter_values=lambda: {},
                             set_parameter_values=lambda v: None)
    driver = MusicRhythmDriver(canvas)
    beats = []
    driver.beat.connect(lambda: beats.append(1))
    driver._enabled, driver._last_tick = True, time.monotonic()   # noqa: SLF001
    driver._envelope_target = 0.02   # noqa: SLF001
    driver._on_tick()   # noqa: SLF001
    driver._envelope_target = 0.8   # noqa: SLF001
    driver._on_tick()   # noqa: SLF001
    driver._on_tick()   # noqa: SLF001 - too soon for a second beat
    assert beats == [1]
    driver.deleteLater()


# ---- R5.5 LLM ------------------------------------------------------------------------


def test_replies_only_trigger_the_rigs_own_actions():
    from rigora.desktop_pet.llm_dialogue import MAX_LINE_CHARS, parse_reply
    allowed = {"motion": {"Wave"}, "expression": {"smile"}, "motion_group": set()}
    line, actions = parse_reply(
        'Hello! [motion:Wave] [expression:smile] [run:rm -rf /] [motion:Explode]\x07', allowed)
    assert line == "Hello!" and actions == [("motion", "Wave"), ("expression", "smile")]
    assert parse_reply("x" * 500, {})[0].endswith("…")
    assert len(parse_reply("x" * 500, {})[0]) == MAX_LINE_CHARS


def test_prompt_lists_allowed_actions_and_recent_history():
    from rigora.desktop_pet.llm_dialogue import DialogueHistory, build_prompt
    history = DialogueHistory([["greeting", "Hi!"], ["bad"], ["hit:head", "Ouch"]])
    assert history.entries() == [("greeting", "Hi!"), ("hit:head", "Ouch")]
    prompt = build_prompt("", "greeting", history=history.entries(),
                          allowed={"motion": {"Wave"}})
    assert "[motion:NAME]" in prompt and "Wave" in prompt and "Ouch" in prompt
    assert "[motion" not in build_prompt("", "greeting")
    history.clear()
    assert len(history) == 0


def test_client_backs_off_when_offline_and_drops_cancelled_replies(qapp, monkeypatch):
    import urllib.error

    from rigora.desktop_pet import llm_dialogue
    calls, release = [], threading.Event()

    def post(url, payload, timeout):
        calls.append(payload["prompt"])
        if payload["prompt"].endswith("slow\nMessage:"):
            release.wait(2)
            return {"response": "late"}
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(llm_dialogue, "post_json", post)
    clock = [0.0]
    client = llm_dialogue.LlmDialogueClient(clock=lambda: clock[0])
    lines, failures = [], []
    client.line_received.connect(lines.append)
    client.request_failed.connect(failures.append)

    def settle():
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            qapp.processEvents()
            if not client.busy():
                return
            time.sleep(0.01)

    for _ in range(3):
        client.request_line("hi")
        settle()
    assert client.state == "offline" and len(calls) == 3
    assert client.request_line("hi") is False and len(calls) == 3   # no network, no loop
    clock[0] += 31
    client._failures = 0   # noqa: SLF001 - recovered server
    client.request_line("slow")
    client.cancel()
    release.set()
    time.sleep(0.2)
    qapp.processEvents()
    assert client.state == "cancelled" and lines == []
    client.shutdown()


def test_controller_keeps_and_clears_history_on_request(store, monkeypatch):
    from rigora.desktop_pet.pet_drivers import LlmDialogueController, allowed_actions
    from rigora.puppet.document import Expression, Motion, PuppetDocument
    persisted, performed = {}, []
    doc = PuppetDocument(motions=[Motion("Wave", 1.0, group="Greet")],
                         expressions=[Expression("smile", [])])
    host = SimpleNamespace(setting=lambda k, d=None: persisted.get(k, d),
                           persist=lambda **f: persisted.update(f),
                           document=lambda: doc,
                           _perform_behavior_step=lambda step: performed.append(step))
    assert allowed_actions(host) == {"motion": {"Wave"}, "motion_group": {"Greet"},
                                     "expression": {"smile"}}
    shown = []
    controller = LlmDialogueController(host, shown.append, lambda _r: None)
    persisted["llm_enabled"] = True
    controller._allowed = allowed_actions(host)   # noqa: SLF001
    controller._on_reply("Hi [motion:Wave] [motion:Nope]")   # noqa: SLF001
    assert shown == ["Hi"] and [(s.kind, s.value) for s in performed] == [("motion", "Wave")]
    assert "llm_history" not in persisted                      # not kept by default
    controller.set_keep_history(True)
    assert persisted["llm_history"] == [["", "Hi"]]
    controller.clear_history()
    assert persisted["llm_history"] == [] and len(controller.history) == 0
    controller.set_keep_history(False)
    assert persisted["llm_keep_history"] is False


# ---- R5.6 resources --------------------------------------------------------------------


def test_frame_pacer_slows_when_idle_and_stops_when_hidden():
    clock = [0.0]
    pacer = FramePacer(clock=lambda: clock[0])
    assert pacer.interval(visible=True, busy=False) == 33
    clock[0] = 11
    assert pacer.interval(visible=True, busy=False) == 66
    assert pacer.interval(visible=True, busy=True) == 33
    assert pacer.interval(visible=False, busy=True) is None
    pacer.note_activity()
    assert pacer.interval(visible=True, busy=False) == 33


def test_rig_cache_shares_texture_bytes_but_not_documents(tmp_path):
    from rigora.puppet.document import Parameter, PuppetDocument
    loads = []

    def loader(path):
        loads.append(path)
        return PuppetDocument(parameters=[Parameter("A", 0, 1, 0)],
                              textures={"t.png": b"x" * 1000})

    rig = tmp_path / "a.puppet"
    rig.write_bytes(b"zip")
    cache = RigCache(size=1, loader=loader)
    one, two = cache.load(rig), cache.load(rig)
    assert len(loads) == 1 and cache.hits == 1
    assert one is not two and one.textures["t.png"] is two.textures["t.png"]
    one.parameters[0].max = 5                                  # outfits stay separate
    assert two.parameters[0].max == 1
    assert texture_bytes(one) == 1000
    rig.write_bytes(b"changed zip")                            # edited file reloads
    cache.load(rig)
    assert len(loads) == 2 and len(cache) == 1
