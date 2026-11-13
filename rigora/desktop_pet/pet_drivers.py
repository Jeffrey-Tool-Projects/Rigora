"""Canvas-driven feature controllers for the desktop-pet overlay.

A second family of feature hooks, complementary to the integration
controllers in :mod:`rigora.desktop_pet.pet_features`. Where those
wrap network / OS clients with a ``start`` / ``stop`` / ``is_running``
lifecycle, the controllers here wrap *canvas drivers* — objects bound
to the puppet canvas that animate it and report their state through
``set_enabled`` / ``is_enabled``.

Extracting them keeps :class:`~rigora.desktop_pet.pet_window.PetWindow`
a thin coordinator: it owns a registry of these controllers and
delegates its public ``set_*_enabled`` / ``*_enabled`` toggles to
them, preserving the original behaviour (lazy construction, settings
round-trip, persistence) byte-for-byte.

The LLM dialogue and click-SFX controllers don't fit the canvas-driver
mould but share the same "thin lazy subsystem owned by the window"
shape, so they live here too rather than bloating the window.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from rigora.system.best_effort import best_effort
from rigora.desktop_pet.click_sfx import ClickSfxPlayer
from rigora.desktop_pet.idle_minigame import IdleMinigameDriver
from rigora.desktop_pet.llm_dialogue import (
    DEFAULT_BASE_URL as LLM_DEFAULT_BASE_URL,
    DEFAULT_MODEL as LLM_DEFAULT_MODEL,
    DEFAULT_PERSONA as LLM_DEFAULT_PERSONA,
    LlmDialogueClient,
)
from rigora.desktop_pet.llm_dialogue import DialogueHistory, parse_reply
from rigora.desktop_pet.music_rhythm import MusicRhythmDriver
from rigora.desktop_pet.pet_feature_base import FeatureHost

logger = logging.getLogger("rigora.desktop_pet.pet_drivers")

DEFAULT_SFX_VOLUME = 0.6


class CanvasDriverController:
    """Base for a lazy canvas driver toggled via ``set_enabled``.

    Subclasses supply :meth:`_build_driver` (construct + wire the
    driver bound to the host's canvas) and a ``driver_key`` naming the
    slot inside the persisted ``drivers`` dict. The base owns the lazy
    construction, the enable / disable call, and the persistence,
    matching the original inline driver methods exactly.
    """

    #: Slot inside the persisted ``drivers`` dict for this driver.
    driver_key: str = ""

    def __init__(self, host: FeatureHost) -> None:
        self._host = host
        self._driver: object | None = None

    def _build_driver(self) -> object:
        """Construct + wire the canvas driver. Called once, lazily."""
        raise NotImplementedError

    def set_enabled(self, enabled: bool) -> bool:
        """Enable or disable the driver and persist the result.

        Returns the driver's own ``set_enabled`` result on enable
        (``False`` when an optional dependency is missing), ``True``
        on disable.
        """
        if enabled:
            if self._driver is None:
                self._driver = self._build_driver()
            ok = bool(self._driver.set_enabled(True))   # type: ignore[attr-defined]
            self._host.persist_driver(self.driver_key, ok)   # type: ignore[attr-defined]
            return ok
        if self._driver is not None:
            self._driver.set_enabled(False)   # type: ignore[attr-defined]
        self._host.persist_driver(self.driver_key, False)   # type: ignore[attr-defined]
        return True

    def is_enabled(self) -> bool:
        return (
            self._driver is not None
            and bool(self._driver.is_enabled())   # type: ignore[attr-defined]
        )

    def shutdown(self) -> None:
        """Stop the driver WITHOUT persisting a disabled state (despawn / close)."""
        if self._driver is not None:
            with best_effort("disable the driver"):
                self._driver.set_enabled(False)   # type: ignore[attr-defined]


class MusicRhythmController(CanvasDriverController):
    """System-audio rhythm driver (WASAPI loopback → puppet motion)."""

    driver_key = "music_rhythm"

    def _build_driver(self) -> MusicRhythmDriver:
        driver = MusicRhythmDriver(self._host.canvas(), parent=self._host)
        fire = getattr(self._host, "fire_behavior", None)
        if fire is not None:
            driver.beat.connect(lambda: fire("beat"))
        return driver


class IdleMinigameController(CanvasDriverController):
    """Idle minigame (phantom curiosity + yawn / sleep escalation).

    Overrides :meth:`set_enabled` because the persisted flag tracks
    the *requested* enable state rather than the driver's return value
    (the minigame has no optional dependency that can refuse), and the
    driver needs a motion callback wired on first build.
    """

    driver_key = "idle_minigame"

    def _build_driver(self) -> IdleMinigameDriver:
        driver = IdleMinigameDriver(self._host.canvas(), parent=self._host)
        driver.set_motion_callback(self._host.play_group)
        return driver

    def set_enabled(self, enabled: bool) -> bool:
        if enabled and self._driver is None:
            self._driver = self._build_driver()
        if self._driver is not None:
            self._driver.set_enabled(bool(enabled))   # type: ignore[attr-defined]
        self._host.persist_driver(self.driver_key, bool(enabled))   # type: ignore[attr-defined]
        return True

    def notify_activity(self) -> None:
        """Reset the idle clock when the user interacts with the pet."""
        if self._driver is not None:
            self._driver.notify_activity()   # type: ignore[attr-defined]


class ClickSfxController:
    """Optional per-event click sound effects.

    Not a canvas driver — a standalone player the window asks to
    ``play`` an event tag. Paths + volume are re-read from settings on
    every (re)configure so a workspace edit round-trips without a
    restart.
    """

    def __init__(self, host: FeatureHost) -> None:
        self._host = host
        self._player: ClickSfxPlayer | None = None

    def set_enabled(self, enabled: bool) -> None:
        """Toggle the subsystem, persisting the flag either way."""
        self._host.persist(click_sfx_enabled=bool(enabled))
        if enabled:
            self.ensure_player()
        elif self._player is not None:
            self._player.shutdown()
            self._player = None

    def shutdown(self) -> None:
        """Stop sounds without changing the saved preference."""
        player, self._player = self._player, None
        if player is not None:
            player.shutdown()

    def is_enabled(self) -> bool:
        return self._player is not None

    def ensure_player(self) -> ClickSfxPlayer:
        """Lazy-build + (re)configure the player from settings."""
        if self._player is None:
            self._player = ClickSfxPlayer(parent=self._host)
        self._player.set_volume(
            float(self._host.setting("click_sfx_volume", DEFAULT_SFX_VOLUME)),
        )
        self._player.set_paths(self._host.setting("click_sfx_paths", {}) or {})
        return self._player

    def play(self, event: str) -> None:
        """Best-effort play. No-op when off or the event is unmapped."""
        if self._player is None:
            return
        self._player.play(event)


def allowed_actions(host) -> dict[str, set[str]]:
    """The motions, motion groups and expressions of the pet's own rig."""
    document = host.document() if hasattr(host, "document") else None
    if document is None:
        return {}
    return {"motion": {m.name for m in document.motions},
            "motion_group": {m.group for m in document.motions if m.group},
            "expression": {e.name for e in document.expressions}}


class LlmDialogueController:
    """Local-LLM-backed speech generation.

    Lazy async client; the persisted ``llm_enabled`` flag is the
    enabled gate. Disabling keeps the client alive to preserve its
    config — stale in-flight replies are dropped by the host's
    ``on_llm_line`` because the flag is off.
    """

    def __init__(
        self,
        host: FeatureHost,
        on_line: Callable[[str], None],
        on_failed: Callable[[str], None],
    ) -> None:
        self._host = host
        self._on_line = on_line
        self._on_failed = on_failed
        self._client: LlmDialogueClient | None = None
        self._allowed: dict = {}
        self._situation = ""
        keep = bool(host.setting("llm_keep_history", False))
        self.history = DialogueHistory(host.setting("llm_history", []) if keep else ())

    def set_enabled(self, enabled: bool) -> bool:
        """Configure / disable LLM speech, persisting the actual flag.

        Returns ``False`` on enable when the saved base URL is invalid
        (the client's ``set_endpoint`` raises ``ValueError``); the
        flag is then forced off so the next launch doesn't auto-retry.
        """
        if not enabled:
            self._host.persist(llm_enabled=False)
            return True
        try:
            self.ensure_client()
        except ValueError as exc:
            logger.warning("LLM disabled: %s", exc)
            self._host.persist(llm_enabled=False)
            return False
        self._host.persist(llm_enabled=True)
        return True

    def is_enabled(self) -> bool:
        return bool(self._host.setting("llm_enabled", False))

    def ensure_client(self) -> LlmDialogueClient:
        """Lazy-build the client; re-configure each call so a settings
        edit takes effect on the next request without a restart."""
        if self._client is None:
            self._client = LlmDialogueClient(parent=self._host)
            self._client.line_received.connect(self._on_reply)
            self._client.request_failed.connect(self._on_failed)
        self._client.set_endpoint(
            base_url=str(self._host.setting("llm_base_url", "") or LLM_DEFAULT_BASE_URL),
            model=str(self._host.setting("llm_model", "") or LLM_DEFAULT_MODEL),
            persona=str(
                self._host.setting("llm_persona", "") or LLM_DEFAULT_PERSONA
            ),
        )
        return self._client

    def request_line(self, situation: str) -> None:
        """Fire an async line request for ``situation`` tag. The model may
        only ask for the rig's own motions and expressions (R5.5)."""
        self._allowed = allowed_actions(self._host)
        self._situation = situation
        self.ensure_client().request_line(situation, history=self.history.entries(),
                                          allowed=self._allowed)

    def _on_reply(self, text: str) -> None:
        line, actions = parse_reply(text, self._allowed)
        if line:
            self.history.add(self._situation, line)
            if self.keeps_history():
                self._host.persist(llm_history=self.history.to_list())
            self._on_line(line)
        perform = getattr(self._host, "_perform_behavior_step", None)
        if perform is not None and self.is_enabled():
            from rigora.desktop_pet.pet_behavior import Step
            for kind, name in actions:
                perform(Step(kind, name))

    def status(self) -> tuple[str, str]:
        if self._client is None:
            return "idle", ""
        return self._client.state, self._client.detail

    def check_connection(self) -> None:
        self.ensure_client().check_connection()

    def cancel(self) -> None:
        if self._client is not None:
            self._client.cancel()

    def keeps_history(self) -> bool:
        return bool(self._host.setting("llm_keep_history", False))

    def set_keep_history(self, keep: bool) -> None:
        """Keeping history saves recent lines with the pet's settings; turning
        it off deletes what was saved."""
        self._host.persist(llm_keep_history=bool(keep),
                           llm_history=self.history.to_list() if keep else [])

    def clear_history(self) -> None:
        self.history.clear()
        self._host.persist(llm_history=[])

    def shutdown(self) -> None:
        """Mark any in-flight request dead so it can't emit on the client after
        the window is destroyed. Called from ``PetWindow.shutdown`` on despawn —
        ``request_line`` spawns a daemon thread that can block in ``urlopen`` for
        seconds, well past ``deleteLater``."""
        if self._client is not None:
            self._client.shutdown()
