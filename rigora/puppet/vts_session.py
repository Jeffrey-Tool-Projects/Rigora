"""Token lifetime, request limits and error numbers for the VTS API (R4.5). Qt-free.

Trust boundary: the server listens on 127.0.0.1 only and refuses browser
origins other than localhost (``rigora.system.local_origin``), so a client is
a native program already running as the user. Such a program is granted a
token automatically, the way a developer tool would be; tokens are not
written to disk, expire after :data:`TOKEN_TTL` and are revoked when the
server stops or the user chooses *Revoke plug-in access*.

Error numbers follow VTube Studio's public ``ErrorID`` values for the
conditions Rigora implements (taken from the published API description, not
checked against a running VTube Studio). Numbers from 6000 up are
Rigora-specific.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

TOKEN_TTL = 12 * 3600.0
MAX_TOKENS = 32
MAX_SESSIONS = 8
INJECT_RATE = 120.0          # requests per second per session, sustained
INJECT_BURST = 240.0
MAX_VALUES_PER_INJECT = 100

ERR_INTERNAL = 0
ERR_API_NAME_INVALID = 1
ERR_API_VERSION_INVALID = 2
ERR_REQUEST_ID_INVALID = 3
ERR_REQUEST_TYPE_MISSING = 4
ERR_REQUEST_TYPE_UNKNOWN = 5
ERR_REQUIRES_AUTHENTICATION = 8
ERR_TOKEN_REQUEST_DENIED = 50
ERR_TOKEN_PLUGIN_NAME_INVALID = 52
ERR_TOKEN_DEVELOPER_NAME_INVALID = 53
ERR_AUTH_TOKEN_MISSING = 100
ERR_AUTH_PLUGIN_NAME_MISSING = 101
ERR_AUTH_DEVELOPER_MISSING = 102
ERR_MODEL_NOT_LOADED = 150
ERR_PARAMETER_NOT_FOUND = 300
ERR_PARAMETER_CREATION_INVALID = 350
ERR_PARAMETER_EXISTS = 351
ERR_INJECT_NO_DATA = 450
ERR_INJECT_VALUE_INVALID = 451
ERR_INJECT_WEIGHT_INVALID = 452
ERR_INJECT_PARAM_NOT_FOUND = 453
ERR_INJECT_PARAM_TAKEN = 454
ERR_INJECT_MODE_UNKNOWN = 455
ERR_RATE_LIMITED = 6000
ERR_TOO_MANY_VALUES = 6001


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def valid_name(name) -> bool:
    return isinstance(name, str) and 3 <= len(name.strip()) <= 32


@dataclass
class TokenInfo:
    plugin: str
    developer: str
    issued: float
    expires: float


class TokenStore:
    """Issued tokens, kept as SHA-256 digests in memory only."""

    def __init__(self, ttl: float = TOKEN_TTL, clock=time.time) -> None:
        self.ttl = float(ttl)
        self._clock = clock
        self._tokens: dict[str, TokenInfo] = {}

    def issue(self, plugin: str, developer: str) -> str:
        self._expire()
        if len(self._tokens) >= MAX_TOKENS:
            oldest = min(self._tokens, key=lambda k: self._tokens[k].issued)
            del self._tokens[oldest]
        token = secrets.token_urlsafe(32)
        now = self._clock()
        self._tokens[_digest(token)] = TokenInfo(plugin, developer, now, now + self.ttl)
        return token

    def check(self, token, plugin=None, developer=None) -> tuple[bool, str]:
        if not isinstance(token, str) or not token:
            return False, "authenticationToken is missing"
        info = self._tokens.get(_digest(token))
        if info is None:
            return False, "unknown or revoked token — request a new one"
        if self._clock() >= info.expires:
            del self._tokens[_digest(token)]
            return False, "token expired — request a new one"
        if plugin is not None and plugin != info.plugin:
            return False, "pluginName does not match the token"
        if developer is not None and developer != info.developer:
            return False, "pluginDeveloper does not match the token"
        return True, "ok"

    def plugin_for(self, token: str) -> str | None:
        info = self._tokens.get(_digest(token)) if isinstance(token, str) else None
        return None if info is None else info.plugin

    def revoke_all(self) -> int:
        count = len(self._tokens)
        self._tokens.clear()
        return count

    def active(self) -> list[TokenInfo]:
        self._expire()
        return sorted(self._tokens.values(), key=lambda i: i.issued)

    def _expire(self) -> None:
        now = self._clock()
        for key in [k for k, v in self._tokens.items() if now >= v.expires]:
            del self._tokens[key]


class RateLimiter:
    """Token bucket: ``rate`` requests per second with bursts up to ``burst``."""

    def __init__(self, rate: float = INJECT_RATE, burst: float = INJECT_BURST,
                 clock=time.monotonic) -> None:
        self.rate, self.burst = float(rate), float(burst)
        self._clock = clock
        self._level = self.burst
        self._last = clock()
        self.limited = 0

    def allow(self) -> bool:
        now = self._clock()
        self._level = min(self.burst, self._level + (now - self._last) * self.rate)
        self._last = now
        if self._level >= 1.0:
            self._level -= 1.0
            return True
        self.limited += 1
        return False
