"""Optimisation studies for the propulsion experiments (Optuna NSGA-II), stored in the experiment database.

kinds written to `experiments.kind`:
  coldgas_skateboard   one row per evaluated boosted-skateboard design (fixed-step simulation of a track run)
  coldgas_hoverboard   one row per cold-gas hoverboard design (analytic hover time + mass closure; 6-DOF
                       mission simulation for the Pareto designs)
  rocket_hoverboard    same for the black-box rocket board
Infeasible designs are kept with their constraint values (Optuna constraints > 0 = violated).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Literal

import optuna
from pydantic import BaseModel, Field

from ..constants import G0
from ..db import ExperimentDB
from .coldgas import TankConfig, ThrusterConfig, energy_report, tank_cost
from .hover import HoverConfig, evaluate_hover
from .rocket import RocketEngineConfig
from .skateboard import Controls, SkateConfig, SkateSim

optuna.logging.set_verbosity(optuna.logging.WARNING)
SUMMARY = Path(__file__).resolve().parent / "data" / "study_summary.json"
SOLVER = "levitate.propulsion"


class PropStudyConfig(BaseModel):
    kind: Literal["coldgas_skateboard", "coldgas_hoverboard", "rocket_hoverboard"]
    n_trials: int = Field(200, ge=4, le=5000)
    seed: int = 7
    rider_kg: float = 90.72
    simulate_top_k: int = Field(5, ge=0, le=30)
    max_boost_accel_g: float = 0.20        # skateboard: a prepared rider can hold ~0.2 g sustained push
    max_speed_m_s: float = 13.0            # skateboard: speed-wobble onset for urethane-wheel boards


def skate_study_scenario() -> list:
    """Wheels 0-3 s, wheels + boost until the tank is empty (up to 33 s), coast, gentle brake."""
    return [(0.0, Controls(throttle=1.0)), (3.0, Controls(throttle=1.0, boost=True)), (33.0, Controls()),
            (36.0, Controls(brake=0.2))]


_BASE: dict[float, tuple[float, float]] = {}


def _t_to(rec, v_target):
    return next((t for t, v in zip(rec["t"], rec["v"]) if v >= v_target), float("nan"))


def _baseline(rider_kg: float) -> tuple[float, float]:
    """(top speed, time to 10 m/s) of the plain electric board on the same track scenario."""
    if rider_kg not in _BASE:
        sim = SkateSim(SkateConfig(coldgas=False, rider_kg=rider_kg, dt=0.002))
        rec = sim.run([(t, Controls(throttle=c.throttle, brake=c.brake)) for t, c in skate_study_scenario()], 60.0, 5)
        _BASE[rider_kg] = (max(rec["v"]), _t_to(rec, 10.0))
    return _BASE[rider_kg]


def evaluate_skate_design(cfg: SkateConfig, max_accel_g: float, vmax_safe: float) -> dict:
    sim = SkateSim(cfg)
    rec = sim.run(skate_study_scenario(), 60.0, 5)
    v0, t10_0 = _baseline(cfg.rider_kg)
    gs = sim.gas_sys
    gs.reset()
    T0 = gs.max_thrust()
    m_tot = rec["m"][0]
    th = rec["thrust"]
    on = [t for t, f in zip(rec["t"], th) if f > 1.0]
    dur = on[-1] - on[0] if len(on) > 1 else 0.0
    er = energy_report(cfg.tank, vals=sim.v_cg)
    prop_kg = gs.dry_mass + gs.m0
    vmax = max(rec["v"])
    cost = (sim.v_sk["cost_board"] + sim.v_sk["cost_edrive"] + tank_cost(cfg.tank, sim.v_cg)
            + sim.v_cg["cost_valves_base"] + cfg.thruster.n_thrusters * sim.v_cg["cost_per_thruster"])
    L = rec["ledger"]
    out = {
        "speed_gain_m_s": vmax - v0, "max_speed_m_s": vmax, "boost_s": dur, "thrust_n": T0,
        "boost_accel_g": T0 / (m_tot * G0), "propulsion_kg": prop_kg, "gas_kg": gs.m0, "tank_kg": gs.m_wall,
        "gain_per_kg": (vmax - v0) / prop_kg, "cost_usd": cost, "refill_usd": er.refill_cost_usd,
        "burst_kj": er.burst_energy_kj, "blast_1psi_m": er.blast_radius_1psi_m, "rider_fell": sim.flags["rider_fell"],
        "noseover": sim.flags["noseover"], "wheelie": sim.flags["wheelie"], "ledger_residual": L["rel_residual"],
        "jet_over_exergy": L["jet_over_exergy"], "propulsive_eff": L["thrust_work"] / L["jet_ke"] if L["jet_ke"] else 0.0,
        "distance_m": rec["x"][-1], "events": [e for _, e in rec["events"]],
        "t_to_10_m_s": _t_to(rec, 10.0), "t_to_10_m_s_ebike": t10_0, "ebike_vmax": v0,
    }
    # hard limits: the rider must stay on and the boost must be holdable; speed above the wobble onset is reported
    viol = [float(out["rider_fell"] or out["noseover"]), max(0.0, out["boost_accel_g"] - max_accel_g)]
    return out | {"constraints": viol, "feasible": all(v <= 0 for v in viol), "over_wobble_speed": vmax > vmax_safe}


def run_propulsion_study(db: ExperimentDB, cfg: PropStudyConfig, study_id: int | None = None,
                         progress: Callable[[float], None] | None = None) -> dict:
    if cfg.kind == "coldgas_skateboard":
        return _skate_study(db, cfg, study_id, progress)
    return _hover_study(db, cfg, study_id, progress)


def _skate_study(db, cfg, study_id, progress):
    study = optuna.create_study(directions=["maximize", "minimize", "minimize"],
                                sampler=optuna.samplers.NSGAIISampler(seed=cfg.seed, population_size=40))
    ids = {}

    def objective(trial):
        tank = TankConfig(volume_l=trial.suggest_float("volume_l", 1.0, 12.0),
                          n_tanks=trial.suggest_int("n_tanks", 1, 2),
                          pressure_bar=trial.suggest_float("pressure_bar", 150.0, 450.0),
                          tank_class=trial.suggest_categorical("tank_class", ["metal", "type3", "type4"]))
        thr = ThrusterConfig(throat_diameter_mm=trial.suggest_float("throat_mm", 3.0, 10.0),
                             reg_pressure_bar=trial.suggest_float("reg_bar", 10.0, 60.0))
        sc = SkateConfig(rider_kg=cfg.rider_kg, tank=tank, thruster=thr,
                         thrust_height_m=trial.suggest_float("thrust_height_m", 0.08, 0.6), dt=0.002)
        r = evaluate_skate_design(sc, cfg.max_boost_accel_g, cfg.max_speed_m_s)
        for i, v in enumerate(r["constraints"]):
            trial.set_constraint(f"c{i}", v)
        trial.set_user_attr("constraints", r["constraints"])
        trial.set_user_attr("r", {k: v for k, v in r.items() if k != "events"})
        summ = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()
                if k in ("speed_gain_m_s", "max_speed_m_s", "boost_s", "thrust_n", "boost_accel_g", "propulsion_kg",
                         "gain_per_kg", "cost_usd", "burst_kj", "feasible")}
        ids[trial.number] = db.add_experiment(
            kind="coldgas_skateboard", solver=SOLVER + ".skateboard(fixed-step 2 ms)", evidence="simplified_numerical_simulation",
            config=json.loads(sc.model_dump_json()), results=r, summary=summ, verdict="FEASIBLE" if r["feasible"] else "INFEASIBLE",
            name=f"skate-{trial.number}", study_id=study_id)
        if progress:
            progress((trial.number + 1) / cfg.n_trials)
        return r["speed_gain_m_s"], r["propulsion_kg"], r["cost_usd"]

    study.optimize(objective, n_trials=cfg.n_trials)
    rows = [t.user_attrs["r"] | {"experiment_id": ids[t.number], "params": t.params} for t in study.trials]
    feas = [r for r in rows if r["feasible"]]
    front = _pareto(feas, [("speed_gain_m_s", 1), ("propulsion_kg", -1), ("cost_usd", -1)])
    best = max(feas, key=lambda r: r["speed_gain_m_s"], default=None)
    best_eff = max(feas, key=lambda r: r["gain_per_kg"], default=None)
    safe = [r for r in feas if not r["over_wobble_speed"]]
    best_safe = max(safe, key=lambda r: r["speed_gain_m_s"], default=None)
    fastest_t10 = min(feas, key=lambda r: r["t_to_10_m_s"] if r["t_to_10_m_s"] == r["t_to_10_m_s"] else 1e9, default=None)
    light = [r for r in feas if r["propulsion_kg"] <= 8.0]
    best_light = max(light, key=lambda r: r["speed_gain_m_s"], default=None)
    return {"kind": cfg.kind, "n_trials": cfg.n_trials, "n_feasible": len(feas), "n_safe_speed": len(safe),
            "infeasible_reasons": _reasons(rows), "pareto": front[:25], "best_gain": best, "best_gain_per_kg": best_eff,
            "best_gain_under_13m_s": best_safe, "fastest_to_10m_s": fastest_t10, "best_under_8kg": best_light}


def _hover_study(db, cfg, study_id, progress):
    gas = cfg.kind == "coldgas_hoverboard"
    study = optuna.create_study(directions=["maximize", "minimize", "minimize"],
                                sampler=optuna.samplers.NSGAIISampler(seed=cfg.seed, population_size=50))
    ids, cfgs = {}, {}

    def objective(trial):
        tw = trial.suggest_float("tw_design", 1.15, 1.6)
        if gas:
            hc = HoverConfig(rider_kg=cfg.rider_kg, tw_design=tw,
                             tank=TankConfig(volume_l=trial.suggest_float("volume_l", 2.0, 60.0, log=True),
                                             n_tanks=trial.suggest_int("n_tanks", 1, 8),
                                             pressure_bar=trial.suggest_float("pressure_bar", 150.0, 700.0),
                                             tank_class=trial.suggest_categorical("tank_class", ["metal", "type3", "type4"])),
                             reg_pressure_bar=trial.suggest_float("reg_bar", 15.0, 80.0))
        else:
            hc = HoverConfig(propulsion="rocket", rider_kg=cfg.rider_kg, tw_design=tw,
                             engine=RocketEngineConfig(engine_class=trial.suggest_categorical("engine_class", ["monoprop", "biprop"]),
                                                       propellant_kg=trial.suggest_float("propellant_kg", 3.0, 150.0, log=True)))
        r = evaluate_hover(hc, run=False)
        summ = {"hover_s": round(r.hover_time_analytic_s, 2), "ceiling_s": round(r.hover_time_upper_bound_s, 1),
                "gross_kg": round(r.gross_mass_kg, 1), "propellant_kg": round(r.propellant_kg, 2),
                "thrust_n": round(r.installed_thrust_n), "isp_s": round(r.isp_s, 1), "cost_usd": round(r.cost["total_hardware_usd"]),
                "jet_power_kw": round(0.5 * r.hover_thrust_n * r.isp_s * G0 / 1000, 1)}
        if gas:
            summ |= {"burst_mj": round(r.hazards["tank"]["burst_energy_kj"] / 1000, 2),
                     "blast_1psi_m": round(r.hazards["tank"]["blast_radius_1psi_m"], 1)}
        else:
            summ |= {"temp_zone_m": round(r.hazards["jet"]["temperature_zone_m"], 2),
                     "spl_rider_db": round(r.hazards["spl_4_jets_rider_db"], 1)}
        ids[trial.number] = db.add_experiment(
            kind=cfg.kind, solver=SOLVER + ".hover(analytic sizing)", evidence="analytical_estimate",
            config=json.loads(hc.model_dump_json()), results=json.loads(r.model_dump_json(exclude={"config"})),
            summary=summ, verdict="SIZED", name=f"{cfg.kind}-{trial.number}", study_id=study_id)
        cfgs[trial.number] = hc
        trial.set_user_attr("r", summ)
        if progress:
            progress(0.8 * (trial.number + 1) / cfg.n_trials)
        return r.hover_time_analytic_s, r.gross_mass_kg, r.cost["total_hardware_usd"]

    study.optimize(objective, n_trials=cfg.n_trials)
    rows = [t.user_attrs["r"] | {"experiment_id": ids[t.number], "trial": t.number, "params": t.params} for t in study.trials]
    front = _pareto(rows, [("hover_s", 1), ("gross_kg", -1), ("cost_usd", -1)])
    best = max(rows, key=lambda r: r["hover_s"])
    # 6-DOF mission simulation of the best designs (and the longest-hover one)
    sims = []
    pick = sorted(front, key=lambda r: -r["hover_s"])[: cfg.simulate_top_k]
    if best not in pick:
        pick.append(best)
    for i, r in enumerate(pick):
        hc = cfgs[r["trial"]]
        res = evaluate_hover(hc, run=True)
        eid = db.add_experiment(
            kind=cfg.kind, solver=SOLVER + ".hover(6-DOF fixed-step 1 ms)", evidence="simplified_numerical_simulation",
            config=json.loads(hc.model_dump_json()), results=json.loads(res.model_dump_json(exclude={"config"})),
            summary={"hover_s": round(res.hover_time_analytic_s, 2), "flight_s": round(res.flight_time_s, 2),
                     "mission_completed": res.mission_completed, "aborted": res.aborted, "failed": res.failed,
                     "max_tilt_deg": round(res.max_tilt_deg, 1), "gross_kg": round(res.gross_mass_kg, 1)},
            verdict="MISSION_OK" if res.mission_completed else ("FAILED" if res.failed else "ABORTED_RESERVE"),
            name=f"{cfg.kind}-mission-{r['trial']}", study_id=study_id)
        sims.append({"experiment_id": eid, "from_trial": r["trial"], "hover_s": res.hover_time_analytic_s,
                     "flight_s": res.flight_time_s, "mission_completed": res.mission_completed, "aborted": res.aborted,
                     "failed": res.failed, "gross_kg": res.gross_mass_kg, "events": [e for _, e in res.events]})
        if progress:
            progress(0.8 + 0.2 * (i + 1) / len(pick))
    # scalability: hover time vs rider mass for the best design
    scal = []
    for mr in (0.0, 45.0, 68.0, 90.72, 113.0, 136.0):
        hc = cfgs[best["trial"]].model_copy(update={"rider_kg": mr})
        rr = evaluate_hover(hc, run=False)
        scal.append({"rider_kg": mr, "hover_s": round(rr.hover_time_analytic_s, 2), "gross_kg": round(rr.gross_mass_kg, 1),
                     "thrust_n": round(rr.installed_thrust_n)})
    return {"kind": cfg.kind, "n_trials": cfg.n_trials, "pareto": front[:25], "best_hover": best,
            "missions": sims, "scalability": scal}


def _pareto(rows, keys):
    out = []
    for r in rows:
        dom = False
        for o in rows:
            if o is r:
                continue
            ge = all((o[k] - r[k]) * s >= 0 for k, s in keys)
            gt = any((o[k] - r[k]) * s > 0 for k, s in keys)
            if ge and gt:
                dom = True
                break
        if not dom:
            out.append(r)
    return sorted(out, key=lambda r: -r[keys[0][0]] * keys[0][1])


def _reasons(rows):
    c = {"rider_fell_or_noseover": 0, "boost_accel_too_high": 0, "feasible_but_over_13m_s": 0}
    for r in rows:
        v = r["constraints"]
        c["rider_fell_or_noseover"] += v[0] > 0
        c["boost_accel_too_high"] += v[1] > 0
        c["feasible_but_over_13m_s"] += bool(r["feasible"] and r["over_wobble_speed"])
    return c


def practical(db: ExperimentDB, kind: str, study_id: int, limits=(150.0, 200.0, 250.0)) -> dict:
    """Longest-hovering sized design under each gross-mass limit (from all stored trials of the study)."""
    rows = [e for e in db.list_experiments(kind=kind, study_id=study_id, limit=5000) if e["verdict"] == "SIZED"]
    out = {}
    for lim in limits:
        ok = [e for e in rows if e["summary"]["gross_kg"] <= lim]
        b = max(ok, key=lambda e: e["summary"]["hover_s"], default=None)
        out[str(int(lim))] = (b["summary"] | {"experiment_id": b["id"]}) if b else None
    return out


def write_summary(results: dict[str, dict]) -> dict:
    """Compact summary for the static page (rom_data.js) and the report."""
    lines = []
    s = results.get("coldgas_skateboard")
    if s and s.get("best_gain"):
        b, e = s["best_gain"], s["best_gain_per_kg"]
        sf, ft = s["best_gain_under_13m_s"], s["fastest_to_10m_s"]
        lines.append(f"Boosted skateboard ({s['n_trials']} designs, {s['n_feasible']} keep the rider on and the push "
                     f"<= 0.2 g): largest top-speed gain +{b['speed_gain_m_s']:.1f} m/s over the e-board ({b['max_speed_m_s']:.1f} m/s, "
                     f"above the ~13 m/s speed-wobble onset) with {b['propulsion_kg']:.1f} kg of tank+air, {b['boost_s']:.0f} s "
                     f"boost, ${b['cost_usd']:.0f}; best per kg +{e['gain_per_kg']:.2f} m/s/kg.")
        if sf:
            lines.append(f"Staying below 13 m/s the boost adds at most +{sf['speed_gain_m_s']:.1f} m/s "
                         f"({sf['propulsion_kg']:.1f} kg); its real effect is acceleration: 0-10 m/s in "
                         f"{ft['t_to_10_m_s']:.1f} s vs {ft['t_to_10_m_s_ebike']:.1f} s on wheels alone.")
    for k, label in (("coldgas_hoverboard", "Cold-gas hoverboard"), ("rocket_hoverboard", "Rocket hoverboard")):
        h = results.get(k)
        if not h:
            continue
        b = h["best_hover"]
        ok = sum(1 for m in h["missions"] if m["mission_completed"])
        lines.append(f"{label} ({h['n_trials']} designs): longest hover {b['hover_s']:.1f} s at {b['gross_kg']:.0f} kg gross "
                     f"({b['propellant_kg']:.0f} kg propellant, ${b['cost_usd']:.0f}); 6-DOF mission (lift-off, hover, 2 m "
                     f"translate, 90 deg turn, land) completed by {ok} of {len(h['missions'])} simulated Pareto designs.")
        pr = h.get("practical") or {}
        bits = [f"<= {k} kg: {v['hover_s']:.1f} s" for k, v in pr.items() if v]
        if bits:
            lines.append(f"{label}, best hover by gross-mass limit (rider 90.7 kg included): " + "; ".join(bits) + ".")
    doc = {"lines": lines, "results": results}
    SUMMARY.write_text(json.dumps(doc, default=float, indent=1), encoding="utf-8")
    return doc


def main(n_skate: int = 160, n_hover: int = 400):
    db = ExperimentDB()
    out = {}
    for kind, n in (("coldgas_skateboard", n_skate), ("coldgas_hoverboard", n_hover), ("rocket_hoverboard", n_hover)):
        cfg = PropStudyConfig(kind=kind, n_trials=n)
        sid = db.create_study(f"{kind} study", kind, cfg.model_dump(), goal="propulsion experiments (Agent C)")
        db.update_study(sid, status="running")
        res = run_propulsion_study(db, cfg, sid, lambda f: None)
        if kind != "coldgas_skateboard":
            res["practical"] = practical(db, kind, sid)
        db.update_study(sid, status="done", progress=1.0, result=res)
        out[kind] = res | {"study_id": sid}
        print(kind, "study", sid, "done")
    return write_summary(out)


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    d = main(*(int(x) for x in a))
    print("\n".join(d["lines"]))
