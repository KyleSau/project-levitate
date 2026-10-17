"""FastAPI endpoint tests (in-process TestClient; no server needed)."""
import warnings

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from vlab.api import app  # noqa: E402

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_defaults_round_trip_through_analyse():
    d = client.get("/api/defaults").json()
    for preset in ("ideal", "reality_baseline", "underpowered"):
        r = client.post("/api/analyse", json={"vehicle": d["vehicle"], "mode": d["presets"][preset]})
        assert r.status_code == 200, r.text
    j = r.json()
    assert j["feasibility"]["verdict"] == "INFEASIBLE"
    assert "power_limit" in j["feasibility"]["limiting_toggles"]


def test_mass_and_cg_change_updates_inertia_consistently():
    a = client.post("/api/analyse", json={"total_mass_kg": 0.020}).json()["vehicle"]
    b = client.post("/api/analyse", json={"total_mass_kg": 0.040}).json()["vehicle"]
    assert b["inertia_kgm2"][2][2] == pytest.approx(2 * a["inertia_kgm2"][2][2], rel=1e-9)
    c = client.post("/api/analyse", json={"cg_m": [0.005, 0, 0]}).json()["vehicle"]
    assert c["cg_m"][0] == pytest.approx(0.005, abs=1e-12)
    assert c["inertia_kgm2"][1][1] != pytest.approx(a["inertia_kgm2"][1][1], rel=1e-6)


def test_unreachable_cg_is_rejected_with_reason():
    r = client.post("/api/analyse", json={"cg_m": [0.04, 0, 0]})
    assert r.status_code == 422 and "not reachable" in r.json()["detail"]


def test_simulate_short_custom_mission():
    body = {"mission": [{"kind": "arm", "duration_s": 0.3}, {"kind": "takeoff", "duration_s": 1.0, "alt_m": 0.1},
                        {"kind": "hold", "duration_s": 0.5}], "name": "api-test"}
    r = client.post("/api/simulate", json=body)
    assert r.status_code == 200
    j = r.json()
    assert j["summary"]["takeoffs"] == 1
    assert len(j["trajectory"]["t"]) > 100
