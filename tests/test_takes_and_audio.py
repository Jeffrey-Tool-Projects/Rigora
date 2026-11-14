"""R3.3 takes and R3.4 audio: no silent overwrite, one clock for sound and picture."""
from __future__ import annotations

import io
import struct
import time
import wave
import zipfile
import json

import numpy as np
import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QLabel, QWidget

from rigora.puppet.audio_lipsync import (
    find_missing_sounds,
    lipsync_motion,
    locate_sounds,
    relink_sound,
    waveform_peaks,
)
from rigora.puppet.document import Motion, MotionSegment, MotionTrack, Parameter, PuppetDocument
from rigora.puppet.document_io import from_zip_bytes, to_zip_bytes
from rigora.puppet.document_session import DocumentSession
from rigora.puppet.format_schema import SCHEMAS, validate
from rigora.puppet.motion_player import MotionPlayer
from rigora.puppet.takes import new_take_info, store_take, take_label, unique_motion_name
from rigora.puppet.validator import validate as validate_rig
from rigora.puppet.workspace_audio import PuppetAudioMixin
from rigora.puppet.workspace_motion_record import PuppetMotionRecordMixin


def wav(path, seconds=1.0, rate=8000, loud=(0.2, 0.6)):
    samples = np.zeros(int(seconds * rate))
    a, b = (int(x * rate) for x in loud)
    samples[a:b] = 0.5 * np.sin(np.linspace(0, 400, b - a))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"".join(struct.pack("<h", int(s * 32767)) for s in samples))
    return path


def motion(name="take", seconds=2.0, **kwargs):
    return Motion(name, seconds, tracks=[MotionTrack("P", [
        MotionSegment("linear", (0.0, 0.0), (seconds, 1.0))])], **kwargs)


def test_take_records_round_trip_and_validate():
    m = motion(take=new_take_info("live recording", fps=30, inputs=["webcam", "mouse"],
                                  captured_seconds=2.04))
    assert len(m.take["id"]) == 32 and m.take["inputs"] == ["mouse", "webcam"]
    doc = PuppetDocument(parameters=[Parameter("P", 0, 1, 0)], motions=[m])
    archive = to_zip_bytes(doc)
    assert from_zip_bytes(archive).motions[0].take == m.take
    raw = json.loads(zipfile.ZipFile(io.BytesIO(archive)).read("motions/take.json"))
    assert validate(raw, SCHEMAS["motion"]) == []
    assert "live recording" in take_label(m)


def test_name_conflicts_are_explicit():
    doc = PuppetDocument(motions=[motion("wave", take=new_take_info("live recording"))])
    old_id = doc.motions[0].take["id"]
    assert unique_motion_name(doc, "wave") == "wave (2)"
    assert store_take(doc, motion("wave"), "discard") is None
    assert [m.name for m in doc.motions] == ["wave"]
    assert store_take(doc, motion("wave"), "rename") == "wave (2)"
    replacement = motion("wave", take=new_take_info("live recording"))
    assert store_take(doc, replacement, "replace") == "wave"
    assert [m.name for m in doc.motions] == ["wave (2)", "wave"]
    assert doc.motions[1].take["replaced"] == old_id
    with pytest.raises(ValueError):
        store_take(doc, motion("x"), "merge")


class _Recorder(PuppetMotionRecordMixin, PuppetAudioMixin, QWidget):
    def __init__(self, document, choice):
        super().__init__()
        self.session = DocumentSession()
        self.session.bind(document, path="t.puppet", saved=True)
        self._status_label = QLabel(self)
        self.choice = choice
        self.selected = []
        host = self
        self._canvas = type("C", (), {"document": lambda s: host.session.document,
                                      "load_document": lambda s, d: None})()
        self._motion_dock = type("D", (), {"select_motion": lambda s, n: host.selected.append(n)})()

    def _choose_take_conflict(self, name):
        return self.choice

    def _update_session_actions(self):
        pass

    def _begin_document_work(self):
        return self.session.revision

    def _announce(self, key, fallback, **fmt):
        self._status_label.setText(fallback.format(**fmt))


@pytest.mark.parametrize("choice,names", [("rename", ["wave", "wave (2)"]),
                                          ("replace", ["wave"]), ("discard", ["wave"])])
def test_recording_over_a_name_asks_and_is_undoable(qapp, choice, names):
    host = _Recorder(PuppetDocument(motions=[motion("wave")]), choice)
    stored = host.store_motion_take(motion("wave", take=new_take_info("live recording")))
    assert [m.name for m in host.session.document.motions] == names
    if choice == "discard":
        assert stored is None and not host.session.dirty
    else:
        host.session.undo()
        assert [m.name for m in host.session.document.motions] == ["wave"]
    host.deleteLater()


def test_lipsync_options_waveform_and_missing_sound(qapp, tmp_path):
    path = wav(tmp_path / "line.wav")
    peaks, seconds = waveform_peaks(path, buckets=100)
    assert seconds == pytest.approx(1.0) and len(peaks) == 100
    assert max(high for _, high in peaks[:15]) == 0.0 and max(h for _, h in peaks) > 0.4
    plain = lipsync_motion(path, name="a", param_id="M", fps=30)
    early = lipsync_motion(path, name="b", param_id="M", fps=30, lead=0.1)
    first_open = lambda m: next(s.p0[0] for s in m.tracks[0].segments if s.p1[1] > 0)  # noqa: E731
    assert first_open(early) == pytest.approx(first_open(plain) - 0.1, abs=0.04)
    assert plain.take["source"] == "lip-sync from audio"
    with pytest.raises(ValueError):
        lipsync_motion(path, name="c", param_id="M", lead=-1)

    doc = PuppetDocument(parameters=[Parameter("M", 0, 1, 0)],
                         motions=[motion("talk", sound_path=str(tmp_path / "gone.wav"))])
    assert find_missing_sounds(doc) == [("talk", str(tmp_path / "gone.wav"))]
    assert any(i.code == "motion_sound_missing" for i in validate_rig(doc))
    (tmp_path / "audio").mkdir()
    wav(tmp_path / "audio" / "GONE.wav")
    found = locate_sounds(find_missing_sounds(doc), [tmp_path / "audio"])
    assert found == {"talk": tmp_path / "audio" / "GONE.wav"}
    relink_sound(doc, "talk", found["talk"])
    assert find_missing_sounds(doc) == []
    with pytest.raises((ValueError, wave.Error, EOFError, OSError)):
        relink_sound(doc, "talk", tmp_path / "audio")

    host = _Recorder(PuppetDocument(motions=[motion("talk", sound_path=str(tmp_path / "x.wav"))]),
                     "rename")
    (tmp_path / "x2").mkdir()
    wav(tmp_path / "x2" / "x.wav")
    assert host.relink_sounds_from(tmp_path / "x2") == 1
    host.session.undo()
    assert host.session.document.motions[0].sound_path == str(tmp_path / "x.wav")
    stored = host._add_lipsync_motion(path, Parameter("M", 0, 1, 0), conflict="rename")   # noqa: SLF001
    assert stored == "lipsync_line" and host.selected == ["lipsync_line"]
    host.deleteLater()


class _Canvas(QObject):
    def __init__(self):
        super().__init__()
        self.values = {}

    def parameter_values(self):
        return dict(self.values)

    def set_parameter_values(self, values):
        self.values.update(values)


class _Media:
    class PlaybackState:
        PlayingState = "playing"

    def __init__(self):
        self.calls, self.pos, self.state = [], 0, "stopped"

    def setSource(self, url):  # noqa: N802
        self.calls.append("source")

    def setPosition(self, ms):  # noqa: N802
        self.pos = ms
        self.calls.append(("pos", ms))

    def position(self):
        return self.pos

    def playbackState(self):  # noqa: N802
        return self.state

    def play(self):
        self.state = "playing"
        self.calls.append("play")

    def stop(self):
        self.state = "stopped"
        self.calls.append("stop")

    def deleteLater(self):  # noqa: N802
        self.calls.append("deleted")


def test_sound_follows_pause_seek_loop_and_drift(qapp, tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    sound = wav(tmp_path / "s.wav")
    player = MotionPlayer(_Canvas())
    media = _Media()
    player._sound_effect = media   # noqa: SLF001
    player.set_motion(motion(seconds=2.0, sound_path=str(sound)))
    player.set_loop(True)
    assert player.sound_status() == "ok"
    player.seek(0.5)
    player.play()
    assert media.calls[-2:] == [("pos", 500), "play"]
    player.pause()
    player.seek(1.25)
    player.play()
    assert media.calls[-2:] == [("pos", 1250), "play"]          # resumes where the picture is
    player.seek(0.25)
    assert media.calls[-1] == ("pos", 250)                       # scrub moves the sound
    clock[0] += 2.0                                              # wraps past the 2 s loop
    media.pos = 250
    player._on_tick()   # noqa: SLF001
    assert media.calls[-1] == ("pos", 250)
    clock[0] += 0.5
    media.pos = 900                                              # audio ran 0.15 s ahead
    player._on_tick()   # noqa: SLF001
    assert player.elapsed() % 2.0 == pytest.approx(0.9)
    player.shutdown()
    assert media.calls[-2:] == ["stop", "deleted"] and player._sound_effect is None   # noqa: SLF001
    player.set_motion(motion(sound_path=str(tmp_path / "none.wav")))
    assert player.sound_status() == "missing"
    player.deleteLater()


def test_motion_dock_tooltip_describes_the_take(qapp):
    from types import SimpleNamespace

    from rigora.puppet.document import Motion, PuppetDocument
    from rigora.puppet.motion_dock import MotionDock
    from rigora.puppet.takes import new_take_info
    document = PuppetDocument(motions=[
        Motion("take", 1.0, take=new_take_info("record", inputs=["webcam", "mic"])),
        Motion("hand", 1.0)])
    items = []
    dock = SimpleNamespace(_list=SimpleNamespace(clear=items.clear, addItem=items.append),
                           _canvas=SimpleNamespace(document=lambda: document))
    MotionDock._rebuild_motions(dock)   # noqa: SLF001
    recorded, hand = items
    assert recorded.toolTip().startswith("record · ")
    assert recorded.toolTip().splitlines()[-1] == "mic, webcam"      # stored sorted
    assert hand.toolTip() == ""
