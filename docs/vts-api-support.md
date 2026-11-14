# VTS API support in Rigora

Rigora can accept parameter input from tools written for the VTube Studio
public API. It is a **small compatible subset**, not a replacement for VTube
Studio: models, hotkeys, items, physics overrides and events are not
available. This page lists what works and how a plug-in is trusted.

## Supported requests

| Request | Behaviour in Rigora |
| --- | --- |
| `APIStateRequest` | Reports that the API is active and whether this session is authenticated. |
| `AuthenticationTokenRequest` | Issues a token to a plug-in whose `pluginName` and `pluginDeveloper` are 3–32 characters. No pop-up is shown (see *Trust boundary*). |
| `AuthenticationRequest` | Accepts a token this server issued that has not expired or been revoked. When `pluginName` / `pluginDeveloper` are sent, they must match the ones the token was issued to. |
| `CurrentModelRequest` | Whether a rig is open, under the generic name `puppet`. |
| `Live2DParameterListRequest` | The open rig's parameters with value, range and default. |
| `ParameterValueRequest` | One parameter's current value (authenticated). |
| `ParameterCreationRequest` | Adds a parameter to the open rig (authenticated). |
| `InjectParameterDataRequest` | Writes parameter values (authenticated): `mode` `set` or `add`, per-value `weight` 0–1, values clamped to each parameter's range. A request is validated in full first and then applied completely or not at all. |

Every other request type gets an `APIError` with `errorID` 5 (unknown request
type); the connection stays open.

## Not supported

Hotkeys, expressions through the API, model loading and moving, items,
artmeshes, colour tinting, physics overrides, NDI configuration, event
subscriptions, custom parameter deletion, the UDP discovery broadcast, and the
plug-in permission pop-ups. Rigora does not claim equivalence with the full
VTube Studio API.

## Trust boundary

* The server listens on `127.0.0.1` only. Other machines cannot connect.
* Browser pages are refused unless they come from a localhost origin, because
  any website could otherwise open a WebSocket to `127.0.0.1`. Native programs
  send no origin and are accepted.
* A native program on this machine already runs as the user, so Rigora issues
  tokens without asking. Tokens are random 32-byte values, stored only as
  SHA-256 digests in memory, never written to disk.
* Tokens expire after 12 hours and are revoked when the API is turned off.
  **Output ▸ Live status… ▸ Revoke plug-in access** revokes them immediately;
  connected plug-ins must authenticate again.
* At most 8 plug-ins can be connected at once, and messages are limited to
  1 MiB.

## Rate and ownership

* Each session may send 120 injection requests per second, with bursts up to
  240. Beyond that the reply is `errorID` 6000 and nothing is applied.
* One request carries at most 100 values (`errorID` 6001 beyond that).
* Each plug-in writes as its own input source (`external:<plug-in name>`), at
  the *external* priority described in the user guide. While one plug-in is
  driving a parameter, another plug-in's write to it is refused with
  `errorID` 454 until the first stops for 0.25 s. Manual slider changes and
  playing motions take precedence in their own order. A plug-in that
  disconnects releases its parameters.

## Error numbers

Rigora reuses VTube Studio's `errorID` numbers for the conditions it
implements: 0 internal, 5 unknown request type, 8 authentication required,
50 token denied, 52/53 invalid plug-in or developer name, 100 token missing,
150 no model loaded, 300 parameter not found, 350/351 invalid or existing
parameter on creation, 450–455 injection errors (no data, invalid value,
invalid weight, unknown parameter, parameter controlled by another plug-in,
unknown mode). The numbers were taken from the published API description and
have not been checked against a running VTube Studio. Numbers from 6000 up
are Rigora's own.
