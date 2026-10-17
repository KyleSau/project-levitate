"""FastAPI routes for the propulsion experiments, mounted under /api/propulsion by levitate.api."""
from __future__ import annotations

import json
import threading
import time
import traceback
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import ExperimentDB
from .assumptions import all_assumption_sets, hazard_thresholds
from .coldgas import ColdGasSystem, TankConfig, ThrusterConfig, energy_report
from .hover import HoverConfig, evaluate_hover
from .rocket import turbojet_comparator
from .skateboard import Controls, SkateConfig, default_scenario, evaluate_skateboard
from .studies import SUMMARY, PropStudyConfig, practical, run_propulsion_study

KINDS = ("coldgas_skateboard", "coldgas_hoverboard", "rocket_hoverboard")


class SkateRequest(BaseModel):
    config: SkateConfig = SkateConfig()
    scenario: list[tuple[float, Controls]] | None = None
    t_end: float = 30.0
    save: bool = True


class HoverRequest(BaseModel):
    config: HoverConfig = HoverConfig()
    run: bool = True
    save: bool = True


class TankRequest(BaseModel):
    tank: TankConfig = TankConfig()
    thruster: ThrusterConfig = ThrusterConfig()
    throttle: float = 1.0


class PropStudyRequest(BaseModel):
    kind: str
    n_trials: int = 100
    name: str | None = None


def make_router(db: ExperimentDB) -> APIRouter:
    r = APIRouter(prefix="/api/propulsion", tags=["propulsion"])

    @r.get("/assumptions")
    def assumptions():
        return {k: [a.model_dump() for a in s.items.values()] for k, s in all_assumption_sets().items()} | {
            "hazard_thresholds": hazard_thresholds()}

    @r.post("/tank")
    def tank(req: TankRequest):
        sys_ = ColdGasSystem(req.tank, req.thruster)
        bd = sys_.blowdown_ivp(req.throttle, n_out=150)
        return {"energy": energy_report(req.tank).model_dump(), "blowdown": bd, "dry_mass_kg": sys_.dry_mass,
                "tank_mass_kg": sys_.m_wall, "gas_kg": sys_.m0}

    @r.post("/skateboard/evaluate")
    def skate(req: SkateRequest):
        res = evaluate_skateboard(req.config, req.scenario or default_scenario(True), req.t_end, keep_trace=True)
        out = json.loads(res.model_dump_json())
        if req.save:
            out["experiment_id"] = db.add_experiment(
                kind="coldgas_skateboard", solver="levitate.propulsion.skateboard(fixed-step)",
                evidence="simplified_numerical_simulation", config=json.loads(req.config.model_dump_json()),
                results={k: v for k, v in out.items() if k != "trace"}, verdict="FEASIBLE" if res.feasible else "INFEASIBLE",
                summary={"speed_gain_m_s": round(res.speed_gain_m_s, 2), "max_speed_m_s": round(res.max_speed_m_s, 2),
                         "boost_s": round(res.boost_duration_s, 1), "propulsion_kg": round(res.propulsion_mass_kg, 2),
                         "cost_usd": round(res.cost["total_usd"])}, name="api-skate")
        return out

    @r.post("/hover/evaluate")
    def hover(req: HoverRequest):
        res = evaluate_hover(req.config, run=req.run, keep_trace=req.run)
        out = json.loads(res.model_dump_json())
        if req.save:
            kind = "coldgas_hoverboard" if req.config.propulsion == "coldgas" else "rocket_hoverboard"
            out["experiment_id"] = db.add_experiment(
                kind=kind, solver="levitate.propulsion.hover" + ("(6-DOF)" if req.run else "(sizing)"),
                evidence="simplified_numerical_simulation" if req.run else "analytical_estimate",
                config=json.loads(req.config.model_dump_json()), results={k: v for k, v in out.items() if k != "trace"},
                verdict=("MISSION_OK" if res.mission_completed else "FAILED" if res.failed else "ABORTED_RESERVE") if req.run else "SIZED",
                summary={"hover_s": round(res.hover_time_analytic_s, 2), "gross_kg": round(res.gross_mass_kg, 1),
                         "flight_s": round(res.flight_time_s, 2), "failed": res.failed}, name="api-hover")
        return out

    @r.get("/turbojet")
    def turbojet(thrust_n: float = 1800.0):
        return turbojet_comparator(thrust_n).model_dump()

    @r.get("/results")
    def results(kind: str | None = None, study_id: int | None = None, limit: int = 500):
        if kind and kind not in KINDS:
            raise HTTPException(400, f"kind must be one of {KINDS}")
        kinds = [kind] if kind else list(KINDS)
        out = []
        for k in kinds:
            out += db.list_experiments(kind=k, study_id=study_id, limit=min(limit, 5000))
        return out

    @r.get("/studies")
    def studies():
        return [s for s in db.list_studies() if s["kind"] in KINDS]

    def _run(sid, cfg: PropStudyConfig):
        db.update_study(sid, status="running", progress=0.0)
        try:
            res = run_propulsion_study(db, cfg, sid, lambda f: db.update_study(sid, progress=round(f, 4)))
            if cfg.kind != "coldgas_skateboard":
                res["practical"] = practical(db, cfg.kind, sid)
            db.update_study(sid, status="done", progress=1.0, result=res)
        except Exception as e:  # noqa: BLE001
            db.update_study(sid, status="failed", result={"error": str(e), "trace": traceback.format_exc()})

    @r.post("/studies")
    def create_study(req: PropStudyRequest):
        if req.kind not in KINDS:
            raise HTTPException(400, f"kind must be one of {KINDS}")
        cfg = PropStudyConfig(kind=req.kind, n_trials=req.n_trials)
        sid = db.create_study(req.name or f"{req.kind} {time.strftime('%Y-%m-%d %H:%M')}", req.kind, cfg.model_dump(),
                              "propulsion experiments")
        threading.Thread(target=_run, args=(sid, cfg), daemon=True).start()
        return {"study_id": sid, "config": cfg.model_dump()}

    @r.get("/compare")
    def compare() -> dict[str, Any]:
        from .rom import baselines
        summary = json.loads(SUMMARY.read_text(encoding="utf-8")) if SUMMARY.exists() else None
        return {"baselines": baselines(), "study_summary": summary}

    return r
