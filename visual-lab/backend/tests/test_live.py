"""Live WebSocket session: real-time stepping, commands change set-points only, full recording returned."""
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from vlab.api import app  # noqa: E402


def test_live_session_commands_and_package():
    c = TestClient(app)
    with c.websocket_connect("/ws/live") as ws:
        ws.send_json({"type": "start", "speed": 4.0})
        h = ws.receive_json()
        assert h["type"] == "header" and h["summary"]["mode"] == "ideal"
        t = 0.0
        frames = 0
        while t < 4.0:                      # wait for takeoff to finish (sim time)
            m = ws.receive_json()
            if m["type"] == "frames":
                t = m["t"]
                frames += len(m.get("channels", {}).get("t", []))
        ws.send_json({"type": "cmd", "cmd": "goto", "rel": [0.2, 0.0, 0.0]})
        ws.send_json({"type": "push", "force_n": [0, 0.03, 0], "duration_s": 0.1})
        while t < 8.0:
            m = ws.receive_json()
            if m["type"] == "frames":
                t = m["t"]
        ws.send_json({"type": "stop"})
        while True:
            m = ws.receive_json()
            if m["type"] == "package":
                break
    res = m["result"]
    kinds = [e["kind"] for e in res["events"]]
    assert "LIFTOFF" in kinds and "COMMAND" in kinds and "PUSH" in kinds
    x_end = res["trajectory"]["pos"][-1][0]
    assert 0.12 < x_end < 0.28, x_end      # moved toward the +0.2 m set-point under its own dynamics
    assert frames > 100
