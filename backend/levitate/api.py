"""FastAPI service for the research harness (port 8000). See docs/API_CONTRACT.md."""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .catalog import BATTERIES, ELECTRONICS, MATERIALS, MOTORS, global_assumptions
from .db import ExperimentDB
from .design import Design
from .ehd_board import EADDesign, ehd_assumptions, evaluate_ead, load_surrogate
from .evaluate import evaluate
from .optimize import (EADStudyConfig, RotorStudyConfig, ead_sensitivity, plan_from_goal, run_ead_study,
                       run_rotor_study, sensitivity, sweep)
from .physics import rotor as rotor_model
from .physics.battery import V_OC_AVG_PER_CELL, max_deliverable_power
from .physics.dynamics import SimConfig
from .provenance import environment_versions
from .screening import screen_all
from .solvers.adapters import REGISTRY, ead_summary, rotor_summary
from .solvers.base import SolverJob

app = FastAPI(title="Project Levitate research harness", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
DB = ExperimentDB()
SCHEMA_VERSION = "levitate.experiment-result/v1"


# ------------------------------------------------------------------------------------------- basics
@app.get("/api/health")
def health():
    return {"status": "ok", "versions": environment_versions(), "experiments": DB.count()}


@app.get("/api/catalog")
def catalog():
    return {"motors": [m.model_dump() for m in MOTORS.values()],
            "batteries": [b.model_dump() for b in BATTERIES.values()],
            "materials": [m.model_dump() for m in MATERIALS.values()],
            "electronics": [e.model_dump() for e in ELECTRONICS.values()],
            "assumptions_rotor": [a.model_dump() for a in global_assumptions().items.values()],
            "assumptions_ead": [a.model_dump() for a in ehd_assumptions().items.values()],
            "default_design": Design().model_dump(), "default_ead_design": EADDesign().model_dump()}


@app.get("/api/solvers")
def solvers():
    return [a.info() for a in REGISTRY]


@app.get("/api/screening")
def screening():
    return [s.model_dump(mode="json") for s in screen_all()]


# ------------------------------------------------------------------------------------------- evaluation
class RotorEvalRequest(BaseModel):
    design: Design
    overrides: dict[str, float] | None = None
    run_sim: bool = False
    sim: SimConfig | None = None
    save: bool = True


@app.post("/api/evaluate/rotor")
def evaluate_rotor(req: RotorEvalRequest):
    try:
        rep = evaluate(req.design, req.overrides, run_sim=req.run_sim, sim_cfg=req.sim)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    out = rep.model_dump(mode="json")
    if req.save:
        cfg = {**req.design.model_dump(), "run_sim": req.run_sim}
        out["experiment_id"] = DB.add_experiment(
            kind="rotor_design", solver="levitate.rotor_momentum_6dof" + ("+rk4_6dof" if rep.sim else ""),
            evidence=rep.evidence.value, config=cfg, results=out, summary=rotor_summary(rep), verdict=rep.verdict,
            name=req.design.name, assumptions=rep.assumptions_used)
    return out


class EADEvalRequest(BaseModel):
    design: EADDesign
    overrides: dict[str, float] | None = None
    save: bool = True


@app.post("/api/evaluate/ead")
def evaluate_ead_ep(req: EADEvalRequest):
    rep = evaluate_ead(req.design, req.overrides)
    out = rep.model_dump(mode="json")
    if req.save:
        out["experiment_id"] = DB.add_experiment(
            kind="ead_design", solver="levitate.ead_board_surrogate", evidence=rep.evidence.value,
            config=req.design.model_dump(), results=out, summary=ead_summary(rep), verdict=rep.verdict,
            name=req.design.name)
    return out


class WireRequest(BaseModel):
    voltage_kv: float = 10.0
    gap_mm: float = 10.0
    wire_radius_um: float = 25.0
    mobility: float = 2.0e-4
    grid: tuple[int, int] = (48, 96)
    convergence_check: bool = True
    save: bool = True


@app.post("/api/solve/ehd_wire")
def solve_wire(req: WireRequest):
    """Runs the coupled corona solver synchronously (FastAPI threadpool); typically 2-20 s."""
    if req.grid[0] * req.grid[1] > 200 * 400:
        raise HTTPException(400, "grid too large for an interactive request")
    adapter = next(a for a in REGISTRY if a.name == "levitate.corona_bipolar_fv")
    cfg = req.model_dump(exclude={"save"})
    cfg["grid"] = list(req.grid)
    try:
        out = adapter.run(SolverJob(kind="ehd_wire", config=cfg))
    except RuntimeError as e:
        raise HTTPException(422, str(e)) from e
    res = out.model_dump(mode="json")
    if req.save:
        res["experiment_id"] = DB.add_experiment(
            kind="ehd_wire", solver=out.solver, evidence=out.evidence.value, config=cfg, results=out.results,
            summary=out.summary, verdict=out.verdict, notes="; ".join(out.validity_notes))
    return res


@app.get("/api/ehd/surrogate")
def surrogate():
    s = load_surrogate()
    return {k: v for k, v in s.items() if k != "entries"} | {
        "entries": [{k: v for k, v in e.items()} for e in s["entries"]]}


@app.post("/api/sensitivity/rotor")
def sens_rotor(design: Design):
    return sensitivity(design)


@app.post("/api/sensitivity/ead")
def sens_ead(design: EADDesign):
    return ead_sensitivity(design)


class SweepRequest(BaseModel):
    design: Design
    param: str
    values: list[Any]


@app.post("/api/sweep/rotor")
def sweep_rotor(req: SweepRequest):
    if req.param not in Design.model_fields:
        raise HTTPException(400, f"unknown parameter {req.param}")
    return sweep(req.design, req.param, req.values)


# ------------------------------------------------------------------------------------------- experiments
@app.get("/api/experiments")
def list_experiments(kind: str | None = None, verdict: str | None = None, study_id: int | None = None,
                     limit: int = 200, offset: int = 0):
    return DB.list_experiments(kind=kind, verdict=verdict, study_id=study_id, limit=min(limit, 2000), offset=offset)


@app.get("/api/experiments/{exp_id}")
def get_experiment(exp_id: int):
    e = DB.get_experiment(exp_id)
    if not e:
        raise HTTPException(404, "not found")
    return e


def _vehicle_from_rotor_results(res: dict) -> dict:
    d = Design(**res["design"])
    nom = res["scenarios"]["nominal"]
    vals = res["assumptions_used"]["nominal"]
    mb = res["mass_budget"]
    motor = MOTORS[d.motor]
    batt = BATTERIES[d.battery]
    D = d.rotor_diameter_mm / 1000
    kduct = rotor_model.duct_power_factor(d.propulsion == "ducted_rotor", vals["duct_effectiveness"])
    return {
        "mass_kg": mb["total_g"] / 1000, "inertia_kgm2": mb["inertia_kgm2"], "cg_m": list(mb["cg_m"]),
        "dimensions_m": [d.length_mm / 1000, d.width_mm / 1000, d.board_height_mm / 1000],
        "actuators": [{"pos_m": list(p), "axis": [0.0, 0.0, 1.0], "max_force_n": nom["max_thrust_per_rotor_n"],
                       "spin": s, "torque_ratio_m": vals["rotor_torque_ratio"],
                       "time_constant_s": vals["motor_time_constant"], "radius_m": D / 2,
                       "mechanism": f"{d.propulsion.replace('_', ' ')} ({motor.name}): momentum exchange with air"}
                      for p, s in zip(res["layout"]["positions_m"], res["layout"]["spins"])],
        "power_model": {"type": "momentum_theory", "disk_area_m2": 3.14159265 * (D / 2) ** 2,
                        "figure_of_merit": vals["figure_of_merit"], "duct_factor": kduct,
                        "motor_efficiency": min(motor.efficiency * vals["motor_eff_scale"], 0.95),
                        "avionics_w": d.electronics.power_w,
                        "battery_energy_j": batt.capacity_mah / 1000 * V_OC_AVG_PER_CELL * batt.cells * 3600
                        * vals["battery_specific_energy_derate"],
                        "battery_max_power_w": max_deliverable_power(batt.cells, batt.internal_resistance_ohm,
                                                                     batt.capacity_mah, batt.max_continuous_c)},
        "drag": {"cd": 1.1, "area_xy_m2": d.length_mm * d.board_height_mm * 1e-6,
                 "area_z_m2": d.length_mm * d.width_mm * 1e-6},
    }


@app.get("/api/experiments/{exp_id}/export")
def export_experiment(exp_id: int):
    e = DB.get_experiment(exp_id)
    if not e:
        raise HTTPException(404, "not found")
    doc: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "source": "research_harness", "experiment_id": e["id"],
                           "kind": e["kind"], "evidence": e["evidence"], "solver": e["solver"],
                           "created": e["created"], "config": e["config"], "summary": e["summary"],
                           "verdict": e["verdict"], "assumptions": e.get("assumptions"),
                           "versions": e.get("versions"), "vehicle": None, "fields": None, "trajectory": None}
    res = e.get("results") or {}
    if e["kind"] == "rotor_design" and "design" in res:
        doc["vehicle"] = _vehicle_from_rotor_results(res)
        sim = res.get("sim")
        if sim:
            doc["trajectory"] = {k: sim[k] for k in ("t", "pos", "quat", "vel", "omega", "thrusts")}
    if e["kind"] == "ehd_wire" and res.get("fields"):
        f = res["fields"]
        doc["fields"] = {"grid": {"x": f["x"], "y": f["y"]},
                         "frame": "2D cross-section; x = height above collector plane, y = lateral; metres",
                         "quantities": {"phi": {"unit": "V", "values": f["phi"]},
                                        "rho": {"unit": "C/m^3", "values": f["rho"]}}}
    return doc


# ------------------------------------------------------------------------------------------- studies
class StudyRequest(BaseModel):
    kind: str                  # rotor_study | ead_study
    config: dict[str, Any] = {}
    goal: str | None = None
    name: str | None = None


def _run_study(study_id: int, kind: str, config: dict):
    DB.update_study(study_id, status="running", progress=0.0)
    try:
        prog = lambda f: DB.update_study(study_id, progress=round(f, 4))  # noqa: E731
        if kind == "rotor_study":
            result = run_rotor_study(DB, RotorStudyConfig(**config), study_id, prog)
        elif kind == "ead_study":
            result = run_ead_study(DB, EADStudyConfig(**config), study_id, prog)
        else:
            raise ValueError(f"unknown study kind {kind}")
        DB.update_study(study_id, status="done", progress=1.0, result=result)
    except Exception as e:  # noqa: BLE001 - surfaced to the UI
        DB.update_study(study_id, status="failed", result={"error": str(e), "trace": traceback.format_exc()})


@app.post("/api/studies")
def create_study(req: StudyRequest):
    if req.kind not in ("rotor_study", "ead_study"):
        raise HTTPException(400, "kind must be rotor_study or ead_study")
    cfg = (RotorStudyConfig if req.kind == "rotor_study" else EADStudyConfig)(**req.config).model_dump()
    sid = DB.create_study(req.name or f"{req.kind} {time.strftime('%Y-%m-%d %H:%M')}", req.kind, cfg, req.goal)
    threading.Thread(target=_run_study, args=(sid, req.kind, cfg), daemon=True).start()
    return {"study_id": sid, "config": cfg}


@app.get("/api/studies")
def list_studies():
    return DB.list_studies()


@app.get("/api/studies/{sid}")
def get_study(sid: int):
    s = DB.get_study(sid)
    if not s:
        raise HTTPException(404, "not found")
    return s


class GoalRequest(BaseModel):
    goal: str


@app.post("/api/plan")
def plan(req: GoalRequest):
    return plan_from_goal(req.goal).model_dump()


@app.get("/api/compare")
def compare():
    """Best stored conventional design vs best stored ionic-wind design."""
    rot = [e for e in DB.list_experiments(kind="rotor_design", limit=2000) if e["verdict"] in ("FEASIBLE", "MARGINAL")]
    ead = DB.list_experiments(kind="ead_design", limit=2000)
    best_rot = max(rot, key=lambda e: e["summary"].get("endurance_s_nom", 0), default=None)
    best_ead = max(ead, key=lambda e: e["summary"].get("thrust_to_weight_opt", 0), default=None)
    return {"rotor": best_rot, "ead": best_ead}


# ------------------------------------------------------------------------------------------- static UI
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="ui")
