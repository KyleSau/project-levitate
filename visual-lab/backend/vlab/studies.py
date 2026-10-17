"""Parameter sweeps, feasibility frontier (Pareto) and optimisation jobs.

Every point is evaluated with the same static analysis as the UI (feasibility.analyse) and, optionally,
verified by a short closed-loop simulation (arm, takeoff to 0.25 m, 3 s hover): the simulation decides
`hover_achieved`, never the static model alone.

Battery coupling (when sweeping capacity): m_batt = 0.70 g + 0.0239 g/mAh * C and R_int = 45 Ohm mAh / C,
fits to Agent A's 1S LiPo catalog (backend/levitate/catalog.py, 150-660 mAh: 4.3-16.5 g, 0.30-0.08 Ohm). Cost: catalog-nominal
prices from the same catalog (motor 0702 $12 each, AIO FC/ESC $40, battery $4 + $0.006/mAh, structure $5);
cost is an ESTIMATE.
"""
from __future__ import annotations

import copy
import itertools
import math

import numpy as np

from .mission import Step
from .sim import SimRequest, SimSettings, analyse_request, run

BATT_MASS_G0, BATT_MASS_G_PER_MAH = 0.70, 0.0239
BATT_IR_OHM_MAH = 45.0          # R_int ~ 45 Ohm mAh / C: fit to Agent A catalog (0.30 @150, 0.15 @300, 0.08 @660)


def couple_battery(req: dict, cap_mah: float, mass: bool = True):
    if mass:
        set_path(req, "mode.battery.mass_kg", (BATT_MASS_G0 + BATT_MASS_G_PER_MAH * cap_mah) / 1000)
    set_path(req, "mode.battery.internal_resistance_ohm", BATT_IR_OHM_MAH / cap_mah)


def set_path(d: dict, path: str, value):
    if path == "rotor_radius_m":
        for a in d["vehicle"]["actuators"]:
            a["radius_m"] = value
        return
    keys = path.split(".")
    o = d
    for k in keys[:-1]:
        o = o.setdefault(k, {})
    o[keys[-1]] = value


def cost_estimate(req: dict, mass_props: dict) -> float:
    n = len(req["vehicle"]["actuators"])
    mode = req["mode"]
    c = 5.0 + 40.0 + 12.0 * n
    if mode.get("mode") == "reality" and mode.get("battery", {}).get("enabled"):
        c += 4.0 + 0.006 * mode["battery"]["capacity_mah"]
    return c


def short_mission(alt=0.25):
    return [Step(kind="arm", duration_s=0.4), Step(kind="takeoff", duration_s=2.0, alt_m=alt),
            Step(kind="hold", duration_s=3.0)]


def evaluate_point(req: dict, simulate: bool) -> dict:
    sr = SimRequest(**req)
    try:
        a = analyse_request(sr)
    except ValueError as e:
        return {"error": str(e)}
    f = a["feasibility"]
    m = {x["key"]: x["value"] for x in f["metrics"]}
    out = {"verdict": f["verdict"], "failing": f["failing"], "limiting": f["limiting_toggles"],
           "mass_kg": a["vehicle"]["mass_kg"], "thrust_to_weight": m.get("thrust_to_weight"),
           "hover_power_w": m.get("hover_power"), "endurance_s": m.get("endurance"),
           "max_payload_kg": m.get("max_payload"), "max_vertical_accel": m.get("max_vertical_accel"),
           "max_horizontal_accel": m.get("max_horizontal_accel"), "roll_authority": m.get("authority_roll"),
           "cost_usd_estimate": cost_estimate(req, a["vehicle"]), "evidence": a["evidence"]}
    if simulate:
        sr2 = sr.model_copy(deep=True)
        sr2.mission = short_mission()
        sr2.settings = SimSettings(t_max_s=8.0)
        r = run(sr2)
        pos = np.array(r["trajectory"]["pos"])
        h0 = r["vehicle"]["cg_m"][2] + r["vehicle"]["height_m"] / 2
        clr = pos[:, 2] - h0
        out["sim_final_clearance_m"] = float(clr[-1])
        out["hover_achieved"] = bool(clr[-1] > 0.2 and abs(clr[-1] - 0.25) < 0.05)
        out["sim_failures"] = r["summary"]["failures"]
    return out


def sweep(base: dict, params: list[dict], simulate: bool = False, couple_battery_mass: bool = True, progress=None) -> dict:
    """params: [{path, values}] -> full-factorial grid."""
    grids = [p["values"] for p in params]
    n = int(np.prod([len(g) for g in grids]))
    limit = 60 if simulate else 2500
    if n > limit:
        raise ValueError(f"{n} points exceeds limit {limit} ({'with' if simulate else 'without'} simulation)")
    rows = []
    for i, combo in enumerate(itertools.product(*grids)):
        req = copy.deepcopy(base)
        for p, v in zip(params, combo):
            set_path(req, p["path"], v)
            if couple_battery_mass and p["path"] == "mode.battery.capacity_mah":
                couple_battery(req, v, mass=not any(q["path"] == "mode.battery.mass_kg" for q in params))
        row = {p["path"]: v for p, v in zip(params, combo)}
        row.update(evaluate_point(req, simulate))
        rows.append(row)
        if progress:
            progress((i + 1) / n)
    return {"params": params, "rows": rows, "pareto": pareto(rows), "simulated": simulate,
            "basis": {"mass_kg": "calculated", "thrust_to_weight": "estimate", "hover_power_w": "estimate",
                      "endurance_s": "estimate", "cost_usd_estimate": "estimate", "hover_achieved": "simulation"}}


def pareto(rows: list[dict], objectives=(("endurance_s", "max"), ("mass_kg", "min"), ("cost_usd_estimate", "min"))) -> list[int]:
    """Indices of hover-feasible rows that are non-dominated in the given objectives."""
    def val(r, k, sense):
        v = r.get(k)
        if v is None:
            v = math.inf if sense == "max" else -math.inf    # unbounded endurance (ideal) dominates
        return v if sense == "max" else -v
    cand = [i for i, r in enumerate(rows) if "error" not in r and not r.get("failing")]
    front = []
    for i in cand:
        vi = [val(rows[i], k, s) for k, s in objectives]
        dominated = False
        for j in cand:
            if j == i:
                continue
            vj = [val(rows[j], k, s) for k, s in objectives]
            if all(b >= a for a, b in zip(vi, vj)) and any(b > a for a, b in zip(vi, vj)):
                dominated = True
                break
        if not dominated:
            front.append(i)
    return front


def default_frontier_request(base: dict) -> tuple[dict, list[dict]]:
    params = [{"path": "mode.battery.capacity_mah", "values": [100, 150, 200, 260, 300, 380, 450, 550, 660, 800, 1000]},
              {"path": "total_mass_kg", "values": [0.010, 0.015, 0.020, 0.025, 0.030, 0.040]}]
    return base, params


def optimise_endurance(base: dict, progress=None, simulate_best: bool = True) -> dict:
    """Maximise hover endurance over (battery capacity, rotor radius) s.t. hover-feasible and T/W >= 1.3.
    SciPy differential evolution on the static model; the optimum is then verified by simulation."""
    from scipy.optimize import differential_evolution
    evals = {"n": 0}

    def make(x):
        req = copy.deepcopy(base)
        set_path(req, "mode.battery.capacity_mah", float(x[0]))
        couple_battery(req, float(x[0]))
        set_path(req, "rotor_radius_m", float(x[1]))
        return req

    def obj(x):
        evals["n"] += 1
        if progress:
            progress(min(0.9, evals["n"] / 400))
        r = evaluate_point(make(x), False)
        if "error" in r or r["failing"] or (r["thrust_to_weight"] or 0) < 1.3:
            return 1e6 - (r.get("thrust_to_weight") or 0) * 1e3
        return -(r["endurance_s"] or 0.0)

    res = differential_evolution(obj, bounds=[(100, 1000), (0.006, 0.0135)], seed=1, maxiter=25, popsize=10, tol=1e-6,
                                 polish=False)
    best = make(res.x)
    out = {"x": {"battery_capacity_mah": float(res.x[0]), "rotor_radius_m": float(res.x[1])},
           "objective_endurance_s": float(-res.fun) if res.fun < 0 else None, "evaluations": evals["n"],
           "static": evaluate_point(best, False), "bounds": {"capacity_mah": [100, 1000], "rotor_radius_m": [0.006, 0.0135]},
           "note": "rotor radius upper bound 13.5 mm keeps 4 ducts inside the 32 mm-wide deck footprint (Agent A layout)"}
    if simulate_best:
        out["verified"] = evaluate_point(best, True)
    if progress:
        progress(1.0)
    return out
