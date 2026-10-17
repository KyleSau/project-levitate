from fastapi.testclient import TestClient

from levitate.api import app
from levitate.db import ExperimentDB
from levitate.design import Design
from levitate.evaluate import evaluate
from levitate.optimize import RotorStudyConfig, plan_from_goal, run_rotor_study
from levitate.screening import screen_all

client = TestClient(app)


def test_verdict_and_scenarios_ordered():
    rep = evaluate(Design(rotor_diameter_mm=22.2, lateral_offset_mm=3.4, deck_material="eps_foam_cf",
                          board_height_mm=6.0, battery="lipo_1s_550"))
    e = {k: v.endurance_s for k, v in rep.scenarios.items()}
    assert e["pessimistic"] <= e["nominal"] <= e["optimistic"]
    assert rep.verdict in ("FEASIBLE", "MARGINAL", "INFEASIBLE")
    assert rep.evidence.value == "analytical_estimate"


def test_screening_covers_brief():
    keys = {s.key for s in screen_all()}
    for k in ("ionic_wind", "ehd", "electrostatic", "maglev", "hendo", "h2_buoyancy", "h2_fuel_cell", "edf",
              "micro_props", "flapping", "piezo", "cyclorotor", "ground_effect", "hybrid"):
        assert k in keys


def test_small_study_returns_feasible_pareto(tmp_path):
    db = ExperimentDB(tmp_path / "s.sqlite")
    r = run_rotor_study(db, RotorStudyConfig(n_trials=60, simulate_top_k=1, seed=1))
    assert r["n_trials"] == 60
    assert len(db.list_experiments(limit=1000)) >= 60
    for p in r["pareto"]:
        exp = db.get_experiment(p["experiment_id"])
        assert exp["verdict"] in ("FEASIBLE", "MARGINAL")


def test_goal_planner():
    p = plan_from_goal("find the longest endurance design under 30 g, 200 trials, robust")
    assert p.kind == "rotor_study"
    assert p.config["max_mass_g"] == 30 and p.config["n_trials"] == 200 and p.config["robust"]
    assert plan_from_goal("optimise an ionic wind board").kind == "ead_study"


def test_api_roundtrip_and_export_schema():
    assert client.get("/api/health").json()["status"] == "ok"
    r = client.post("/api/evaluate/rotor", json={"design": Design(rotor_diameter_mm=20, lateral_offset_mm=3.5).model_dump(),
                                                 "run_sim": True})
    assert r.status_code == 200
    eid = r.json()["experiment_id"]
    doc = client.get(f"/api/experiments/{eid}/export").json()
    for k in ("schema_version", "source", "kind", "evidence", "created", "config", "summary"):
        assert k in doc
    assert doc["schema_version"] == "levitate.experiment-result/v1"
    v = doc["vehicle"]
    assert len(v["actuators"]) == 4 and len(v["inertia_kgm2"]) == 3
    assert doc["trajectory"] and len(doc["trajectory"]["t"]) > 10
    solvers = client.get("/api/solvers").json()
    assert any(s["name"] == "comsol" and s["available"] is False for s in solvers)


def test_api_ehd_wire_with_fields():
    r = client.post("/api/solve/ehd_wire", json={"voltage_kv": 9, "gap_mm": 8, "grid": [24, 48],
                                                 "convergence_check": False})
    assert r.status_code == 200
    eid = r.json()["experiment_id"]
    doc = client.get(f"/api/experiments/{eid}/export").json()
    q = doc["fields"]["quantities"]
    assert "phi" in q and "rho" in q and len(doc["fields"]["grid"]["x"]) > 10
