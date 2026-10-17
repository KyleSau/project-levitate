"""Smoke tests of the /api/propulsion endpoints (temporary DB from conftest)."""
from fastapi.testclient import TestClient

from levitate.api import app

client = TestClient(app)


def test_assumptions_and_compare():
    r = client.get("/api/propulsion/assumptions")
    assert r.status_code == 200 and "coldgas" in r.json()
    r = client.get("/api/propulsion/compare")
    assert r.status_code == 200 and "air_cushion" in r.json()["baselines"]


def test_evaluate_endpoints_save_to_db():
    r = client.post("/api/propulsion/skateboard/evaluate", json={"t_end": 20})
    assert r.status_code == 200
    body = r.json()
    assert body["experiment_id"] > 0 and abs(body["energy_ledger"]["rel_residual"]) < 1e-4
    r = client.post("/api/propulsion/hover/evaluate", json={"config": {"propulsion": "rocket"}, "run": True})
    assert r.status_code == 200 and r.json()["mission_completed"]
    rows = client.get("/api/propulsion/results?kind=rocket_hoverboard").json()
    assert any(x["id"] == r.json()["experiment_id"] for x in rows)
    r = client.post("/api/propulsion/tank", json={"tank": {"volume_l": 6.8}})
    assert r.status_code == 200 and r.json()["energy"]["Z_fill"] > 1.05


def test_bad_kind_rejected():
    assert client.post("/api/propulsion/studies", json={"kind": "warp_drive"}).status_code == 400
