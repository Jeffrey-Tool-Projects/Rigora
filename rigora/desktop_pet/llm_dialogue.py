"""Local-LLM dialogue client for the desktop pet.

The scripted speech engine (:mod:`rigora.desktop_pet.pet_script`)
gives the pet a fixed pool of lines per bucket. That's robust and
fast, but a long-running pet eventually feels like a stuck record.
This module connects to a *local* LLM (default: an Ollama server
running on ``localhost:11434``) so the pet can generate fresh lines
per click — same speech-bubble UX, dynamic content.

Why local-only by default: pets chat constantly, and routing every
greeting through a paid API would burn through credits and leak
"my desktop pet says hi" requests to a third party. Ollama runs the
model on the user's machine, never touching the network. Remote
LLMs are still supported via HTTPS base URLs for users who want
that — the URL guard accepts ``https://`` anywhere, ``http://``
only on localhost.

The class is structured to mirror the other optional-dep clients
in this package (``ObsEventClient``, ``TwitchChatClient``): pure
helpers are stateless and Qt-free, the QObject wrapper runs the
blocking HTTP call on a worker thread, and signal emissions queue
back onto the GUI thread.
"""
from __future__ import annotations

import collections
import logging
import re
import threading
import time
import urllib.error

from PySide6.QtCore import QObject, Signal

from rigora.system.local_llm import get_json, post_json, validate_base_url

logger = logging.getLogger("rigora.desktop_pet.llm_dialogue")

DEFAULT_BASE_URL: str = "http://localhost:11434"
"""Ollama's default listen address. The HTTP scheme is fine because
the URL guard restricts ``http://`` to loopback only."""

DEFAULT_MODEL: str = "llama3.2:1b"
"""Smallest commonly-pulled Ollama model — completes a short
greeting in well under a second on CPU. Heavier models work too;
the user picks via settings."""

DEFAULT_PERSONA: str = (
    "You are a cheerful desktop pet living on the user's screen. "
    "Reply with ONE short, warm message (under 15 words). "
    "No quotation marks, no preamble, just the message itself."
)
"""System-prompt persona. Kept terse on purpose — long prompts
slow first-token latency on local CPU inference, and the speech
bubble can't show much text anyway."""

DEFAULT_TIMEOUT_S: float = 8.0
"""Hard cap on how long the user waits for a reply. Local models
on CPU can take a few seconds; 8 s leaves margin without making a
broken Ollama install feel like a hang."""

MAX_LINE_CHARS = 200
MAX_ACTIONS = 2
FAILURES_BEFORE_OFFLINE = 3
OFFLINE_SECONDS = 30.0
HISTORY_LIMIT = 50
ACTION_KINDS = ("motion", "motion_group", "expression")
_ACTION_TAG = re.compile(r"\[(motion_group|motion|expression)\s*:\s*([^\]\n]{1,60})\]",
                         re.IGNORECASE)
_ANY_TAG = re.compile(r"\[[^\]\n]{0,80}\]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# Connection states shown to the user (R5.5).
STATE_IDLE, STATE_CHECKING, STATE_OK, STATE_WAITING = "idle", "checking", "ok", "waiting"
STATE_OFFLINE, STATE_ERROR, STATE_CANCELLED = "offline", "error", "cancelled"


def action_instructions(allowed: dict[str, set[str]] | None) -> str:
    """Tell the model which character actions it may ask for, if any."""
    if not allowed or not any(allowed.values()):
        return ""
    listed = "; ".join(f"{kind}: {', '.join(sorted(names)[:20])}"
                       for kind, names in allowed.items() if names)
    return ("You may add at most one tag such as [motion:NAME] or [expression:NAME], "
            f"using only these names — {listed}.")


def build_prompt(persona: str, situation: str, *, history=(),
                 allowed: dict[str, set[str]] | None = None) -> str:
    """Compose the prompt the LLM sees.

    ``situation`` is one of ``"greeting"``, ``"hit:<area>"``,
    ``"motion:<name>"``, ``"time_of_day:<band>"``, free-form. The
    persona stays on top; the situation tag goes in a labelled
    section so a small model has a clear pattern to follow. Recent
    lines (when history is kept) help it avoid repeating itself."""
    persona = (persona or DEFAULT_PERSONA).strip()
    situation = (situation or "greeting").strip()
    parts = [persona]
    rules = action_instructions(allowed)
    if rules:
        parts.append(rules)
    recent = [line for _situation, line in list(history)[-4:]]
    if recent:
        parts.append("You said recently: " + " / ".join(recent))
    return "\n\n".join(parts) + f"\n\nSituation: {situation}\nMessage:"


def parse_reply(text: str, allowed: dict[str, set[str]] | None) -> tuple[str, list]:
    """Split a reply into the line to show and the actions it asked for.

    Only ``[motion:…]``, ``[motion_group:…]`` and ``[expression:…]`` tags
    naming something in ``allowed`` become actions (at most two); every
    other bracketed tag is removed, control characters are dropped and the
    line is cut to :data:`MAX_LINE_CHARS`. Nothing in a reply is executed
    as a command."""
    allowed = allowed or {}
    actions = []
    for match in _ACTION_TAG.finditer(text or ""):
        kind, name = match.group(1).lower(), match.group(2).strip()
        if name in allowed.get(kind, ()) and len(actions) < MAX_ACTIONS:
            actions.append((kind, name))
    line = _CONTROL.sub(" ", _ANY_TAG.sub("", text or ""))
    line = " ".join(line.split()).strip().strip('"').strip("'").strip()
    if len(line) > MAX_LINE_CHARS:
        line = line[:MAX_LINE_CHARS - 1].rstrip() + "…"
    return line, actions


class DialogueHistory:
    """Recent ``(situation, line)`` pairs; kept on disk only when the user
    turns on *Keep conversation history*."""

    def __init__(self, entries=()) -> None:
        self._entries = collections.deque(maxlen=HISTORY_LIMIT)
        for entry in entries or ():
            if isinstance(entry, list | tuple) and len(entry) == 2 \
                    and all(isinstance(v, str) for v in entry):
                self._entries.append((entry[0], entry[1][:MAX_LINE_CHARS]))

    def add(self, situation: str, line: str) -> None:
        self._entries.append((situation, line))

    def clear(self) -> None:
        self._entries.clear()

    def entries(self) -> list[tuple[str, str]]:
        return list(self._entries)

    def to_list(self) -> list[list[str]]:
        return [list(entry) for entry in self._entries]

    def __len__(self) -> int:
        return len(self._entries)


def extract_line(response_payload: dict) -> str | None:
    """Pull the message string out of Ollama's response envelope.

    Ollama's ``/api/generate`` (non-streaming) returns
    ``{"response": "...", "done": True, ...}``. We strip
    quotes / outer whitespace and reject empty strings so the
    speech bubble never pops with an empty line."""
    raw = response_payload.get("response") if isinstance(response_payload, dict) else None
    if not isinstance(raw, str):
        return None
    text = raw.strip().strip('"').strip("'").strip()
    if not text:
        return None
    return text


class LlmDialogueClient(QObject):
    """Async LLM client. Fire-and-forget per request; results come
    back via :attr:`line_received` / :attr:`request_failed`.

    Each :meth:`request_line` call spawns a daemon thread so the
    GUI never blocks waiting for the model. The previous request's
    thread is *not* cancelled — Python doesn't expose a clean way to
    interrupt a blocking ``urlopen``. If two requests overlap, both
    will eventually emit; the receiver should ignore stale results
    based on its own state (e.g. "is the bubble still up?").
    """

    line_received = Signal(str)
    """Emitted with the LLM's reply string on success. Stripped of
    surrounding quotes and whitespace."""

    request_failed = Signal(str)
    """Emitted with a short error message on any failure (bad URL,
    timeout, connection refused, malformed response). The receiver
    typically falls back to the scripted line set."""

    status_changed = Signal(str, str)
    """``(state, detail)``: idle, checking, waiting, ok, offline, error or
    cancelled."""

    def __init__(self, parent=None, *, clock=time.monotonic) -> None:
        super().__init__(parent)
        self._base_url: str = DEFAULT_BASE_URL
        self._model: str = DEFAULT_MODEL
        self._persona: str = DEFAULT_PERSONA
        self._timeout_s: float = DEFAULT_TIMEOUT_S
        self._alive: bool = True
        self._clock = clock
        self._generation = 0
        self._failures = 0
        self._offline_until = 0.0
        self.state, self.detail = STATE_IDLE, ""

    def _set_status(self, state: str, detail: str = "") -> None:
        self.state, self.detail = state, detail
        if self._alive:
            self.status_changed.emit(state, detail)

    def cancel(self) -> None:
        """Drop the reply of any request still running (R5.5)."""
        self._generation += 1
        if self.state == STATE_WAITING:
            self._set_status(STATE_CANCELLED)

    def busy(self) -> bool:
        return self.state in (STATE_WAITING, STATE_CHECKING)

    def check_connection(self) -> None:
        """Ask the server which models it has, on a worker thread."""
        generation = self._generation = self._generation + 1
        self._set_status(STATE_CHECKING)
        threading.Thread(target=self._run_check, args=(generation,), daemon=True,
                         name="llm-dialogue-check").start()

    def _run_check(self, generation: int) -> None:
        try:
            data = get_json(self._base_url.rstrip("/") + "/api/tags", timeout=self._timeout_s)
        except (OSError, ValueError) as exc:
            if generation == self._generation:
                self._set_status(STATE_OFFLINE, str(exc))
            return
        names = {m.get("name") for m in data.get("models", []) if isinstance(m, dict)} \
            if isinstance(data, dict) else set()
        if generation != self._generation:
            return
        self._failures, self._offline_until = 0, 0.0
        if self._model in names or f"{self._model}:latest" in names:
            self._set_status(STATE_OK, self._model)
        else:
            self._set_status(STATE_ERROR, f"model {self._model} is not installed")

    def shutdown(self) -> None:
        """Mark the client dead so a request still blocked in ``urlopen`` drops
        its result instead of emitting on this QObject after the owning window
        has been ``deleteLater``'d (which would raise ``RuntimeError: Internal
        C++ object already deleted`` on the worker thread)."""
        self._alive = False

    def _safe_fail(self, message: str) -> None:
        if self._alive:
            self.request_failed.emit(message)

    def _safe_line(self, line: str) -> None:
        if self._alive:
            self.line_received.emit(line)

    # ---- configuration -------------------------------------------

    def set_endpoint(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        persona: str = DEFAULT_PERSONA,
    ) -> None:
        """Cache the endpoint params. URL is validated immediately;
        :class:`ValueError` propagates so the caller can reject the
        user's typed URL with a clear message."""
        validate_base_url(base_url)
        self._base_url = base_url
        self._model = str(model) or DEFAULT_MODEL
        self._persona = str(persona) or DEFAULT_PERSONA

    def base_url(self) -> str:
        return self._base_url

    def model(self) -> str:
        return self._model

    def persona(self) -> str:
        return self._persona

    # ---- fire a request ------------------------------------------

    def request_line(self, situation: str = "greeting", *, history=(),
                     allowed: dict[str, set[str]] | None = None) -> bool:
        """Spawn a worker thread, hit the LLM, emit the result.
        Returns immediately — the actual response lands later via
        :attr:`line_received` / :attr:`request_failed`. A newer request
        replaces an older one (its reply is dropped). After repeated
        failures the server counts as offline for a while and requests fail
        at once, so a dead server never causes a retry loop."""
        if self._clock() < self._offline_until:
            self._safe_fail("offline")
            return False
        prompt = build_prompt(self._persona, situation, history=history, allowed=allowed)
        self._generation += 1
        self._set_status(STATE_WAITING, situation)
        thread = threading.Thread(
            target=self._run_request,
            args=(prompt, self._generation),
            name=f"llm-dialogue-{situation[:16]}",
            daemon=True,
        )
        thread.start()
        return True

    def _failed(self, generation: int, message: str) -> None:
        # Every failure says something about the server, even from a request
        # a newer one replaced; only the current request reports it.
        self._failures += 1
        if self._failures >= FAILURES_BEFORE_OFFLINE:
            self._offline_until = self._clock() + OFFLINE_SECONDS
        if generation != self._generation:
            return
        self._set_status(STATE_OFFLINE if self._failures >= FAILURES_BEFORE_OFFLINE
                         else STATE_ERROR, message)
        self._safe_fail(message)

    def _run_request(self, prompt: str, generation: int | None = None) -> None:
        generation = self._generation if generation is None else generation
        """Worker-thread body. Catches every exception and routes
        it through :attr:`request_failed` so a misbehaving LLM
        can't take the GUI thread down with it."""
        url = self._base_url.rstrip("/") + "/api/generate"
        payload = {"model": self._model, "prompt": prompt, "stream": False}
        try:
            data = post_json(url, payload, timeout=self._timeout_s)
        except urllib.error.URLError as exc:
            logger.info("llm request URLError: %s", exc)
            self._failed(generation, f"connection: {exc}")
            return
        except OSError as exc:
            # TimeoutError is an OSError subclass on Python 3, so a
            # bare OSError catches both connect-refused and read-
            # timeout paths.
            logger.info("llm request OSError: %s", exc)
            self._failed(generation, f"network: {exc}")
            return
        except ValueError as exc:
            logger.warning("llm bad URL / payload: %s", exc)
            self._failed(generation, f"config: {exc}")
            return
        except Exception as exc:   # noqa: BLE001 - last-ditch safety on the worker thread
            logger.warning("llm request unexpected: %s", exc)
            self._failed(generation, f"unknown: {exc}")
            return
        if generation != self._generation:
            return                      # cancelled or replaced by a newer request
        line = extract_line(data)
        if line is None:
            self._failed(generation, "empty response")
            return
        self._failures = 0
        self._set_status(STATE_OK, self._model)
        self._safe_line(line)
