"""A minimal tracker that drives Rigora through its VTS API.

Run Rigora, open a rig, turn on **Output > VTS API**, then:

    py -3 examples/live/vts_client.py [--port 8001] [--seconds 10]

The client authenticates as the plug-in "Rigora example tracker" and sends a
slow head sway (ParamAngleX / ParamAngleY) at 30 requests per second, well
under Rigora's limit of 120 per second. Watch the rig turn its head; open
**Live > Input sources…** to see the parameters owned by
"External plug-in (Rigora example tracker)".

``run_offline`` sends the same messages to Rigora's protocol handler in
process, which is what ``examples/run_examples.py`` checks.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

PLUGIN = {"pluginName": "Rigora example tracker", "pluginDeveloper": "Rigora examples"}
FRAMES_PER_SECOND = 30


def request(message_type: str, data: dict | None = None, request_id: str = "1") -> dict:
    return {"apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": request_id,
            "messageType": message_type, "data": data or {}}


def sway(t: float) -> list[dict]:
    """Head angles in -1..1 (Imeru's range) for time ``t`` seconds."""
    return [{"id": "ParamAngleX", "value": 0.6 * math.sin(t * 1.3)},
            {"id": "ParamAngleY", "value": 0.3 * math.sin(t * 0.7 + 1.0)}]


def run_offline(document, seconds: float = 1.0) -> dict:
    """Send the tracker's messages to an in-process handler; return the values."""
    from rigora.puppet.input_arbitration import InputArbiter
    from rigora.puppet.vts_api import VTubeStudioHandler

    class Canvas:
        def __init__(self):
            self.values = {p.id: p.default for p in document.parameters}
            self.arbiter = InputArbiter()

        def document(self):
            return document

        def parameter_values(self):
            return dict(self.values)

        def input_arbiter(self):
            return self.arbiter

        def submit_input(self, source, values, force=False):
            accepted = self.arbiter.submit(source, values)
            self.values.update(accepted)
            return accepted

        def release_input(self, source):
            self.arbiter.release(source)

    canvas = Canvas()
    handler = VTubeStudioHandler(canvas)
    token = handler.handle_message(request("AuthenticationTokenRequest", PLUGIN))
    handler.handle_message(request("AuthenticationRequest", {
        "authenticationToken": token["data"]["authenticationToken"], **PLUGIN}))
    for frame in range(int(seconds * FRAMES_PER_SECOND)):
        reply = handler.handle_message(request("InjectParameterDataRequest", {
            "parameterValues": sway(0.4 + frame / FRAMES_PER_SECOND)}))
        if reply["messageType"] != "InjectParameterDataResponse":
            raise RuntimeError(f"Rigora refused the values: {reply['data']}")
    return canvas.values


def run_live(port: int, seconds: float) -> int:   # pragma: no cover - needs a running Rigora
    from PySide6.QtCore import QCoreApplication, QTimer, QUrl
    from PySide6.QtWebSockets import QWebSocket

    app = QCoreApplication(sys.argv)
    socket = QWebSocket()
    state = {"frame": 0, "token": None}

    def send(message):
        socket.sendTextMessage(json.dumps(message))

    def on_message(text):
        data = json.loads(text)
        if data["messageType"] == "AuthenticationTokenResponse":
            state["token"] = data["data"]["authenticationToken"]
            send(request("AuthenticationRequest", {"authenticationToken": state["token"],
                                                   **PLUGIN}))
        elif data["messageType"] == "AuthenticationResponse":
            if not data["data"]["authenticated"]:
                print("authentication refused:", data["data"].get("reason"))
                app.exit(1)
                return
            timer.start()
        elif data["messageType"] == "APIError":
            print("Rigora:", data["data"].get("message"))

    def tick():
        state["frame"] += 1
        send(request("InjectParameterDataRequest", {
            "parameterValues": sway(state["frame"] / FRAMES_PER_SECOND)}))
        if state["frame"] >= seconds * FRAMES_PER_SECOND:
            socket.close()
            app.exit(0)

    timer = QTimer()
    timer.setInterval(int(1000 / FRAMES_PER_SECOND))
    timer.timeout.connect(tick)
    socket.textMessageReceived.connect(on_message)
    socket.connected.connect(lambda: send(request("AuthenticationTokenRequest", PLUGIN)))
    socket.errorOccurred.connect(lambda _e: (print("cannot connect:", socket.errorString()),
                                             app.exit(1)))
    socket.open(QUrl(f"ws://127.0.0.1:{port}"))
    return app.exec()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--seconds", type=float, default=10.0)
    options = parser.parse_args()
    raise SystemExit(run_live(options.port, options.seconds))
