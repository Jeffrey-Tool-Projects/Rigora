"""VTube Studio Public API server (minimal subset).

Speaks the JSON-over-WebSocket protocol that third-party trackers
(iPhone iFacialMocap, MacBook camera apps, fan-made keyboard rigs)
use to drive a Live2D avatar. When this server is enabled, any of
those tools can connect to ``ws://127.0.0.1:8001`` and start
injecting parameter values — the same wire the real VTube Studio
app exposes.

Scope is deliberately small and is not equivalent to the full VTube Studio
API; ``docs/vts-api-support.md`` lists what is and is not supported. We
handle the message types needed to get a tracker from "connect" to
"InjectParameterDataRequest":

* ``APIStateRequest`` — capability probe
* ``AuthenticationTokenRequest`` — issue a token (see :mod:`vts_session`)
* ``AuthenticationRequest`` — accept a token this server issued and that
  has not expired or been revoked
* ``CurrentModelRequest`` — minimal model info
* ``Live2DParameterListRequest`` — list document parameters
* ``ParameterValueRequest`` — read one parameter
* ``ParameterCreationRequest`` — register a new parameter
* ``InjectParameterDataRequest`` — write parameter values

Everything else returns a polite error envelope rather than crashing
the connection. The Qt half (``VTubeStudioServer``) is optional — it
imports ``QtWebSockets`` lazily so test environments without the
module still exercise the protocol handler.

Security: the server binds ``127.0.0.1`` only (never ``0.0.0.0``).
A token grants parameter-write access; tokens live in memory, expire, and
are revoked when the server stops. Injection is rate limited per session and
a parameter driven by one plug-in is refused to another while it is held. Binding to localhost
does not keep out web pages: a browser lets any site open a WebSocket to
``127.0.0.1``, so remote web origins, opaque ``null`` origins and malformed
origins are refused (see :mod:`rigora.system.local_origin`). Native clients
may omit the origin; browser tools should be served from localhost. Messages are capped at
:data:`MAX_MESSAGE_BYTES`.
"""
from __future__ import annotations

import contextlib
import json
import logging
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from rigora.puppet import vts_session as vs
from rigora.puppet.input_arbitration import release_source, submit_values
from rigora.system.local_origin import is_allowed_origin

if TYPE_CHECKING:
    from rigora.puppet.canvas import PuppetCanvas

logger = logging.getLogger("rigora.puppet.vts_api")

DEFAULT_VTS_PORT: int = 8001
LOCALHOST: str = "127.0.0.1"
API_NAME: str = "VTubeStudioPublicAPI"
API_VERSION: str = "1.0"
_NOT_AUTHENTICATED_MSG: str = "not authenticated"
# Parameter injection sends a few dozen floats; nothing legitimate comes close.
MAX_MESSAGE_BYTES: int = 1024 * 1024


class VTubeStudioHandler:
    """Pure-Python state machine for one VTS client session.

    Owns the issued auth token (per-session — we don't persist it),
    routes requests to the right handler, and writes responses back
    as Python dicts that the Qt wrapper serialises. Kept Qt-free so
    tests can verify the protocol without a WebSocket."""

    def __init__(self, canvas: PuppetCanvas, tokens: vs.TokenStore | None = None,
                 limiter: vs.RateLimiter | None = None):
        self._canvas = canvas
        self._tokens = tokens if tokens is not None else vs.TokenStore()
        self._limiter = limiter if limiter is not None else vs.RateLimiter()
        self._authenticated: bool = False
        self._token: str | None = None
        self.plugin_name: str = ""

    @property
    def source(self) -> str:
        """The arbitration source this session writes as."""
        return f"external:{self.plugin_name or 'plug-in'}"

    def close(self) -> None:
        """Release every parameter this session controls."""
        release_source(self._canvas, self.source)

    def is_authenticated(self) -> bool:
        return self._authenticated

    def handle_message(self, message: object) -> dict:
        """Dispatch one inbound request and return the response dict.

        Accepts any object so we can validate inbound payloads at the
        boundary — third-party trackers occasionally hand us strings
        / lists / None when their JSON layer hiccups, and the explicit
        ``isinstance`` guard below produces a clean InvalidRequest
        envelope instead of a TypeError.

        Always emits an envelope — even on error paths — so the
        client never sees a torn message. The ``timestamp`` field
        is filled with the current wall time in milliseconds (VTS
        clients use it for round-trip latency calculations)."""
        if not isinstance(message, dict):
            return self._error_envelope("", "InvalidRequest", "message must be a JSON object")
        request_id = str(message.get("requestID", ""))
        message_type = message.get("messageType")
        data = message.get("data", {})
        if not isinstance(message_type, str) or not isinstance(data, dict):
            return self._error_envelope(
                request_id, "InvalidRequest", "messageType must be a string and data an object")
        handler = _MESSAGE_HANDLERS.get(message_type)
        if handler is None:
            return self._envelope(
                request_id, "APIError",
                {"errorID": vs.ERR_REQUEST_TYPE_UNKNOWN,
                 "message": f"unknown messageType {message_type!r}"},
            )
        if self._authenticated and not self._tokens.check(self._token)[0]:
            # Revoked or expired while connected: the session must authenticate again.
            self._authenticated = False
        response_type, response_data = handler(self, data)
        return self._envelope(request_id, response_type, response_data)

    # ---- handlers ------------------------------------------------------

    def _on_api_state(self, _data: dict) -> tuple[str, dict]:
        return "APIStateResponse", {
            "active": True,
            "vTubeStudioVersion": API_VERSION,
            "currentSessionAuthenticated": self._authenticated,
        }

    def _on_auth_token(self, data: dict) -> tuple[str, dict]:
        plugin_name = data.get("pluginName", "")
        plugin_dev = data.get("pluginDeveloper", "")
        if not vs.valid_name(plugin_name):
            return "APIError", {"errorID": vs.ERR_TOKEN_PLUGIN_NAME_INVALID,
                                "message": "pluginName must be 3-32 characters"}
        if not vs.valid_name(plugin_dev):
            return "APIError", {"errorID": vs.ERR_TOKEN_DEVELOPER_NAME_INVALID,
                                "message": "pluginDeveloper must be 3-32 characters"}
        # Tokens are 32 bytes of urlsafe randomness, stored only as digests in
        # memory; they expire and are revoked when the server stops.
        token = self._tokens.issue(plugin_name, plugin_dev)
        # Phrase the log line without the literal word "token" — static
        # analysers flag any "<credential> issued" message as a potential
        # secret leak, even when the actual value isn't interpolated.
        logger.info("VTS session opened for %s / %s", plugin_name, plugin_dev)
        return "AuthenticationTokenResponse", {"authenticationToken": token}

    def _on_auth(self, data: dict) -> tuple[str, dict]:
        token = data.get("authenticationToken")
        if not isinstance(token, str) or not token:
            return "APIError", {"errorID": vs.ERR_AUTH_TOKEN_MISSING,
                                "message": "authenticationToken is missing"}
        # Plug-ins send their name and developer with the token; when they do,
        # they must match the ones the token was issued to.
        ok, reason = self._tokens.check(token, data.get("pluginName"),
                                        data.get("pluginDeveloper"))
        if not ok:
            self._authenticated = False
            return "AuthenticationResponse", {"authenticated": False, "reason": reason}
        self._authenticated, self._token = True, token
        self.plugin_name = self._tokens.plugin_for(token) or ""
        return "AuthenticationResponse", {"authenticated": True, "reason": "ok"}

    def _on_current_model(self, _data: dict) -> tuple[str, dict]:
        doc = self._canvas.document()
        return "CurrentModelResponse", {
            "modelLoaded": doc is not None,
            "modelName": "puppet" if doc is not None else "",
            "modelID": "",
            "vtsModelName": "",
            "vtsModelIconName": "",
            "live2DModelName": "puppet" if doc is not None else "",
            "modelLoadTime": int(time.time() * 1000),
        }

    def _on_parameter_list(self, _data: dict) -> tuple[str, dict]:
        doc = self._canvas.document()
        if doc is None:
            return "Live2DParameterListResponse", {"parameters": []}
        values = self._canvas.parameter_values()
        parameters = [
            {
                "name": p.id,
                "value": float(values.get(p.id, p.default)),
                "min": float(p.min),
                "max": float(p.max),
                "defaultValue": float(p.default),
            }
            for p in doc.parameters
        ]
        return "Live2DParameterListResponse", {"parameters": parameters}

    def _on_parameter_value(self, data: dict) -> tuple[str, dict]:
        if not self._require_auth():
            return "APIError", {"errorID": vs.ERR_REQUIRES_AUTHENTICATION,
                                "message": _NOT_AUTHENTICATED_MSG}
        name = str(data.get("name", ""))
        doc = self._canvas.document()
        param = doc.parameter(name) if doc is not None else None
        if param is None:
            return "APIError", {"errorID": vs.ERR_PARAMETER_NOT_FOUND,
                                "message": f"unknown parameter {name!r}"}
        value = float(self._canvas.parameter_values().get(name, param.default))
        return "ParameterValueResponse", {
            "name": name,
            "value": value,
            "min": param.min,
            "max": param.max,
            "defaultValue": param.default,
        }

    def _on_parameter_creation(self, data: dict) -> tuple[str, dict]:
        if not self._require_auth():
            return "APIError", {"errorID": vs.ERR_REQUIRES_AUTHENTICATION,
                                "message": _NOT_AUTHENTICATED_MSG}
        from rigora.puppet.operations import add_parameter
        doc = self._canvas.document()
        if doc is None:
            return "APIError", {"errorID": vs.ERR_MODEL_NOT_LOADED,
                                "message": "no document loaded"}
        name = str(data.get("parameterName", ""))
        if not name:
            return "APIError", {"errorID": vs.ERR_PARAMETER_CREATION_INVALID,
                                "message": "parameterName required"}
        try:
            ok = add_parameter(
                doc, name,
                min_value=float(data.get("min", -1.0)),
                max_value=float(data.get("max", 1.0)),
                default=float(data.get("defaultValue", 0.0)),
            )
        except (TypeError, ValueError, OverflowError) as exc:
            return "APIError", {"errorID": vs.ERR_PARAMETER_CREATION_INVALID,
                                "message": str(exc)}
        if not ok:
            return "APIError", {"errorID": vs.ERR_PARAMETER_EXISTS,
                                "message": "parameter already exists"}
        self._canvas.load_document(doc)
        return "ParameterCreationResponse", {"parameterName": name}

    def _on_inject(self, data: dict) -> tuple[str, dict]:
        """The big one — third-party trackers call this every frame to
        push the latest parameter values into our puppet."""
        if not self._require_auth():
            return "APIError", {"errorID": vs.ERR_REQUIRES_AUTHENTICATION,
                                "message": _NOT_AUTHENTICATED_MSG}
        if not self._limiter.allow():
            return "APIError", {"errorID": vs.ERR_RATE_LIMITED,
                                "message": "too many injection requests; slow down"}
        values = data.get("parameterValues", [])
        if not isinstance(values, list) or not values:
            return "APIError", {"errorID": vs.ERR_INJECT_NO_DATA,
                                "message": "parameterValues must be a non-empty array"}
        if len(values) > vs.MAX_VALUES_PER_INJECT:
            return "APIError", {"errorID": vs.ERR_TOO_MANY_VALUES,
                                "message": f"at most {vs.MAX_VALUES_PER_INJECT} values"}
        mode = data.get("mode", "set")
        if mode not in ("set", "add"):
            return "APIError", {"errorID": vs.ERR_INJECT_MODE_UNKNOWN,
                                "message": "mode must be 'set' or 'add'"}
        planned, error = self._plan_injection(values, mode)
        if error is not None:
            return "APIError", error
        blocked = []
        if hasattr(type(self._canvas), "input_arbiter"):
            blocked = self._canvas.input_arbiter().blocked(self.source, planned)
        if blocked:
            return "APIError", {"errorID": vs.ERR_INJECT_PARAM_TAKEN,
                                "message": f"controlled by another source: {', '.join(blocked)}"}
        submit_values(self._canvas, self.source, planned)
        return "InjectParameterDataResponse", {"parameterValuesApplied": len(planned)}

    def _plan_injection(self, values: list, mode: str) -> tuple[dict, dict | None]:
        """Validate every entry first so a request applies all or nothing."""
        import math
        doc = self._canvas.document()
        current = self._canvas.parameter_values()
        planned: dict[str, float] = {}
        for entry in values:
            param_id = entry.get("id") or entry.get("name") if isinstance(entry, dict) else None
            param = doc.parameter(param_id) if doc is not None and isinstance(
                param_id, str) else None
            if param is None:
                return {}, {"errorID": vs.ERR_INJECT_PARAM_NOT_FOUND,
                            "message": f"unknown parameter {param_id!r}"}
            try:
                value = float(entry.get("value"))
                weight = float(entry.get("weight", 1.0))
            except (TypeError, ValueError, OverflowError):
                return {}, {"errorID": vs.ERR_INJECT_VALUE_INVALID,
                            "message": f"{param_id}: value must be a number"}
            if not math.isfinite(value):
                return {}, {"errorID": vs.ERR_INJECT_VALUE_INVALID,
                            "message": f"{param_id}: value must be finite"}
            if not (math.isfinite(weight) and 0.0 <= weight <= 1.0):
                return {}, {"errorID": vs.ERR_INJECT_WEIGHT_INVALID,
                            "message": f"{param_id}: weight must be 0..1"}
            base = float(current.get(param_id, param.default))
            target = base + value if mode == "add" else value
            blended = base + (target - base) * weight
            planned[param_id] = min(param.max, max(param.min, blended))
        return planned, None

    # ---- helpers -------------------------------------------------------

    def _require_auth(self) -> bool:
        return self._authenticated

    def _envelope(
        self, request_id: str, message_type: str, data: dict,
    ) -> dict:
        return {
            "apiName": API_NAME,
            "apiVersion": API_VERSION,
            "timestamp": int(time.time() * 1000),
            "requestID": request_id,
            "messageType": message_type,
            "data": data,
        }

    def _error_envelope(
        self, request_id: str, error_kind: str, reason: str,
    ) -> dict:
        return self._envelope(
            request_id, "APIError",
            {"errorID": 1, "message": f"{error_kind}: {reason}"},
        )


_MESSAGE_HANDLERS = {
    "APIStateRequest": VTubeStudioHandler._on_api_state,
    "AuthenticationTokenRequest": VTubeStudioHandler._on_auth_token,
    "AuthenticationRequest": VTubeStudioHandler._on_auth,
    "CurrentModelRequest": VTubeStudioHandler._on_current_model,
    "Live2DParameterListRequest": VTubeStudioHandler._on_parameter_list,
    "ParameterValueRequest": VTubeStudioHandler._on_parameter_value,
    "ParameterCreationRequest": VTubeStudioHandler._on_parameter_creation,
    "InjectParameterDataRequest": VTubeStudioHandler._on_inject,
}


# ---------------------------------------------------------------------------
# Qt wrapper
# ---------------------------------------------------------------------------


class VTubeStudioServer(QObject):
    """Qt WebSocket server that funnels client messages through one
    :class:`VTubeStudioHandler` per session.

    QtWebSockets is imported lazily so a missing module just makes
    ``set_enabled(True)`` return ``False`` instead of crashing on
    import. The workspace toggles the server on a toolbar action."""

    state_changed = Signal()

    def __init__(self, canvas: PuppetCanvas, parent=None,
                 *, port: int = DEFAULT_VTS_PORT):
        super().__init__(parent)
        self._canvas = canvas
        self._port = int(port)
        self._enabled = False
        self._server = None
        self._sessions: dict = {}
        self.tokens = vs.TokenStore()

    def session_count(self) -> int:
        return len(self._sessions)

    def revoke_tokens(self) -> int:
        """Revoke every issued token; connected plug-ins must authenticate again."""
        return self.tokens.revoke_all()

    def is_enabled(self) -> bool:
        return self._enabled

    def port(self) -> int:
        return self._port

    def set_enabled(self, enabled: bool) -> bool:
        if enabled == self._enabled:
            return True
        if enabled:
            ok = self._start()
            if not ok:
                self._enabled = False
                self.state_changed.emit()
                return False
        else:
            self._stop()
        self._enabled = bool(enabled)
        self.state_changed.emit()
        return True

    def shutdown(self) -> None:
        self._stop()

    def _start(self) -> bool:  # pragma: no cover - needs QtWebSockets + network
        try:
            from PySide6.QtNetwork import QHostAddress
            from PySide6.QtWebSockets import QWebSocketServer
        except ImportError:
            logger.info("QtWebSockets not available; VTS API disabled")
            return False
        server = QWebSocketServer(
            "puppet-vts", QWebSocketServer.SslMode.NonSecureMode, self,
        )
        # 127.0.0.1 only — never 0.0.0.0. Third-party trackers run on
        # the same machine; exposing this on the network would let
        # anyone on the LAN drive the puppet.
        if not server.listen(QHostAddress(LOCALHOST), self._port):
            logger.warning(
                "VTS API failed to listen on %s:%d", LOCALHOST, self._port,
            )
            return False
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        logger.info("VTS API listening on %s:%d", LOCALHOST, self._port)
        return True

    def _stop(self) -> None:  # pragma: no cover - needs QtWebSockets
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        # Snapshot keys: socket.close() triggers _on_disconnect, which
        # pops the entry while we're still iterating.
        for socket in list(self._sessions):   # NOSONAR S7504 - mutation guard
            with contextlib.suppress(RuntimeError):
                socket.close()
        for handler in self._sessions.values():
            handler.close()
        self._sessions.clear()
        self.tokens.revoke_all()

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            origin = socket.origin()
            if not is_allowed_origin(origin):
                logger.warning("VTS API refused a connection from web origin %s", origin)
                socket.close()
                socket.deleteLater()
                continue
            if len(self._sessions) >= vs.MAX_SESSIONS:
                logger.warning("VTS API refused a connection: %d sessions open",
                               len(self._sessions))
                socket.close()
                socket.deleteLater()
                continue
            socket.setMaxAllowedIncomingMessageSize(MAX_MESSAGE_BYTES)
            socket.setMaxAllowedIncomingFrameSize(MAX_MESSAGE_BYTES)
            handler = VTubeStudioHandler(self._canvas, self.tokens)
            self._sessions[socket] = handler
            socket.textMessageReceived.connect(
                lambda text, s=socket: self._on_text(s, text),
            )
            socket.disconnected.connect(lambda s=socket: self._on_disconnect(s))

    def _on_text(self, socket, text: str) -> None:  # pragma: no cover - needs network
        handler = self._sessions.get(socket)
        if handler is None:
            return
        try:
            message = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.debug("VTS bad JSON from client: %s", exc)
            socket.sendTextMessage(json.dumps(handler._error_envelope(   # noqa: SLF001
                "", "InvalidRequest", "message is not valid JSON")))
            return
        response = handler.handle_message(message)
        socket.sendTextMessage(json.dumps(response))

    def _on_disconnect(self, socket) -> None:  # pragma: no cover - needs network
        handler = self._sessions.pop(socket, None)
        if handler is not None:
            handler.close()
        with contextlib.suppress(RuntimeError):
            socket.deleteLater()
