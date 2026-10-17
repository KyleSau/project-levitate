"""Static hover feasibility of a resolved configuration (what the closed-loop simulation will then show).

Every metric carries a `basis`:
  * "calculated"      - follows from Newton's laws / geometry / mass distribution (no model uncertainty);
  * "estimate"        - from an uncertain engineering model (momentum-theory power, battery Thevenin model,
                        lumped thermal model); numbers are ESTIMATES;
  * "hypothetical"    - only meaningful under the IDEAL (hypothetical force input) assumption.
Each constraint names the REALITY toggle that produces it, so the UI can show exactly which constraints make
the vehicle infeasible.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import linprog

from .modes import ModeConfig, ResolvedModel, battery_max_power, cell_power, V_OC_PER_CELL


def _num(x):
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def authority(B4: np.ndarray, weight: float, lb, ub) -> dict[str, float]:
    """Largest symmetric torque on each axis while holding thrust = weight and zero other torques (LP)."""
    n = B4.shape[1]
    bounds = [(None if not math.isfinite(l) else l, None if not math.isfinite(u) else u) for l, u in zip(lb, ub)]
    out = {}
    for ax, name in ((1, "roll"), (2, "pitch"), (3, "yaw")):
        best = math.inf
        for sign in (1, -1):
            others = [i for i in (1, 2, 3) if i != ax]
            A_eq = np.vstack([B4[0], B4[others[0]], B4[others[1]]])
            res = linprog(-sign * B4[ax], A_eq=A_eq, b_eq=[weight, 0, 0], bounds=bounds, method="highs")
            if res.status == 3:          # unbounded
                val = math.inf
            else:
                val = max(0.0, sign * float(B4[ax] @ res.x)) if res.success else 0.0
            best = min(best, val)
        out[name] = best
    return out


def analyse(rm: ResolvedModel, mc: ModeConfig, plant) -> dict:
    m, g = plant.m, plant.g
    W = m * g
    n = plant.n
    ideal = rm.mode == "ideal"
    pw = rm.power
    f_max = np.array(rm.f_max, float)
    f_min = np.array(rm.f_min, float)
    B4 = plant.B[[2, 3, 4, 5]]
    u_h = np.linalg.pinv(B4) @ np.array([W, 0, 0, 0])
    t_force = float(np.sum(f_max))
    budget = rm.power_cap_w - pw.avionics_w if rm.power_cap_w < math.inf else math.inf
    t_power = n * pw.thrust_at_power(budget / n) if budget < math.inf else math.inf
    t_avail = min(t_force, t_power)
    p_load = float(np.sum(pw.actuator_power(u_h))) + pw.avionics_w
    p_cell = cell_power(p_load, rm.battery) if rm.battery else p_load
    endurance = rm.energy_j / p_cell if rm.energy_j < math.inf and p_cell > 0 else math.inf
    tw = t_avail / W
    a_up = (t_avail - W) / m
    tilt = math.degrees(math.acos(W / t_avail)) if t_avail > W else 0.0
    a_h = g * math.tan(math.radians(tilt)) if tilt < 89.9 else math.inf
    payload = t_avail / g - m
    payload_margin = t_avail / (1.3 * g) - m
    J = plant.J
    auth_t = authority(B4, W, f_min, f_max) if t_avail > W else {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
    auth = {k: auth_t[k] / J[i, i] for i, k in enumerate(("roll", "pitch", "yaw"))}
    metrics = []

    def met(key, label, value, unit, basis, note=""):
        metrics.append({"key": key, "label": label, "value": _num(value), "unit": unit, "basis": basis,
                        "unbounded": value is not None and not math.isfinite(float(value)), "note": note})

    met("mass", "total mass", m, "kg", "calculated", "from mass distribution")
    met("weight", "weight m g", W, "N", "calculated", f"g = {g} m/s^2")
    met("required_hover_force", "required hover force (sum)", W, "N", "calculated", "Newton: sum F_z = m g")
    for i, u in enumerate(u_h):
        met(f"hover_force_A{i}", f"hover force actuator A{i}", u, "N", "calculated", "allocation incl. CG offset")
    met("available_thrust", "available thrust (sum)", t_avail, "N", "hypothetical" if ideal else "estimate",
        "unlimited (ideal)" if ideal and not math.isfinite(t_avail) else
        ("force-limited" if t_force <= t_power else "power-limited"))
    met("thrust_to_weight", "thrust / weight", tw, "-", "hypothetical" if ideal else "estimate")
    met("max_vertical_accel", "max vertical acceleration", a_up, "m/s^2", "hypothetical" if ideal else "estimate")
    met("max_tilt_level", "max tilt holding altitude", tilt, "deg", "hypothetical" if ideal else "estimate")
    met("max_horizontal_accel", "max horizontal acceleration", a_h, "m/s^2", "hypothetical" if ideal else "estimate")
    met("max_payload", "max payload (T/W = 1)", payload, "kg", "hypothetical" if ideal else "estimate")
    met("max_payload_margin", "max payload (T/W = 1.3)", payload_margin, "kg", "hypothetical" if ideal else "estimate")
    met("hover_power", "hover electrical power", p_cell, "W", "estimate", pw.model)
    met("endurance", "hover endurance", endurance, "s", "hypothetical" if ideal else "estimate")
    for k, val in auth.items():
        met(f"authority_{k}", f"{k} angular accel at hover", val, "rad/s^2", "hypothetical" if ideal else "estimate",
            "LP over actuator bounds")
    cons = []

    def con(key, label, passed, value, limit, unit, toggle, hard=True, msg=""):
        cons.append({"key": key, "label": label, "passed": bool(passed), "value": _num(value), "limit": _num(limit),
                     "unit": unit, "toggle": toggle, "hard": hard, "message": msg})

    mp_ok = plant.mp.valid
    con("inertia_valid", "inertia tensor physically valid", mp_ok, None, None, "", "mass_distribution",
        msg="; ".join(plant.mp.issues) or "positive definite, triangle inequality holds")
    lim_toggles = [k for k, on in (("thrust_limit", mc.thrust_limit.enabled), ("power_limit", mc.power_limit.enabled),
                                   ("battery", mc.battery.enabled), ("efficiency", mc.efficiency.enabled),
                                   ("total_mass", mc.total_mass.enabled)) if on and not ideal]
    con("hover_thrust", "available thrust >= weight", t_avail >= W, t_avail, W, "N", ",".join(lim_toggles) or "-",
        msg="cannot hover: thrust below weight" if t_avail < W else "")
    in_b = bool(np.all(u_h >= f_min - 1e-12) and np.all(u_h <= f_max + 1e-12))
    con("hover_allocation", "every actuator's hover force within bounds", in_b, float(np.max(u_h)), float(np.min(f_max)),
        "N", "thrust_limit,mass_distribution", msg="CG offset may overload one actuator" if not in_b else "")
    con("thrust_margin", "thrust / weight >= 1.3 (control + climb margin)", tw >= 1.3, tw, 1.3, "-",
        ",".join(lim_toggles) or "-", hard=False)
    if not ideal and rm.battery is not None:
        pb = battery_max_power(rm.battery)
        con("battery_power", "hover power <= battery max deliverable", p_load <= pb, p_load, pb, "W", "battery",
            msg="battery cannot deliver hover power (C-rate / voltage sag)" if p_load > pb else "")
        voc = V_OC_PER_CELL * rm.battery.cells
        i_h = p_cell / voc
        con("battery_c_rate", "hover C-rate <= derated continuous C", i_h / (rm.battery.capacity_mah / 1000)
            <= rm.battery.max_continuous_c, i_h / (rm.battery.capacity_mah / 1000), rm.battery.max_continuous_c, "C",
            "battery")
        con("endurance_mission", "endurance >= 40 s (demo mission)", endurance >= 40, endurance, 40, "s", "battery")
        con("endurance_sustained", "endurance >= 120 s (Agent A sustained-hover criterion)", endurance >= 120,
            endurance, 120, "s", "battery", hard=False)
    if not ideal and mc.power_limit.enabled:
        cap = mc.power_limit.max_electrical_power_w
        con("power_cap", "hover power <= actuator/ESC power cap", p_load <= cap, p_load, cap, "W", "power_limit")
    con("roll_pitch_authority", "roll/pitch authority >= 20 rad/s^2 at hover", min(auth["roll"], auth["pitch"]) >= 20,
        min(auth["roll"], auth["pitch"]), 20, "rad/s^2", ",".join(lim_toggles) or "-")
    con("yaw_authority", "yaw authority >= 2 rad/s^2 at hover", auth["yaw"] >= 2, auth["yaw"], 2, "rad/s^2",
        ",".join(lim_toggles) or "-", hard=False)
    if rm.thermal is not None and pw.kind == "rotor":
        eta = mc.efficiency.motor_efficiency if mc.efficiency.enabled else 1.0
        q = float(np.max(pw.actuator_power(u_h))) * (1 - eta)
        t_ss = rm.thermal.ambient_c + q * rm.thermal.thermal_resistance_k_per_w
        tau_th = rm.thermal.thermal_resistance_k_per_w * rm.thermal.heat_capacity_j_per_k
        met("motor_temp_ss", "steady-state motor temperature at hover", t_ss, "C", "estimate",
            f"lumped R_th C_th, time constant {tau_th:.0f} s")
        con("thermal", "steady-state motor temperature <= limit", t_ss <= rm.thermal.max_temp_c, t_ss,
            rm.thermal.max_temp_c, "C", "thermal", hard=False, msg=f"derating after ~{tau_th:.0f} s time constant")
    if not ideal and mc.delays.enabled:
        wc = 22.0  # rate-loop crossover ~ rate_kp
        lag = math.degrees(math.atan(wc * mc.delays.actuator_time_constant_s) + wc * mc.delays.transport_delay_s)
        met("rate_loop_phase_lag", "actuator lag + delay phase at rate-loop crossover", lag, "deg", "estimate",
            "first-order lag + transport delay at 22 rad/s")
        con("delay_phase", "actuator phase lag <= 45 deg at rate-loop crossover", lag <= 45, lag, 45, "deg", "delays",
            hard=False)
    hard_fail = [c for c in cons if c["hard"] and not c["passed"]]
    soft_fail = [c for c in cons if not c["hard"] and not c["passed"]]
    if hard_fail:
        verdict = "INFEASIBLE"
    elif soft_fail:
        verdict = "MARGINAL"
    else:
        verdict = "FEASIBLE"
    if ideal:
        verdict += " (HYPOTHETICAL)"
    return {"verdict": verdict, "metrics": metrics, "constraints": cons,
            "failing": [c["key"] for c in hard_fail], "marginal": [c["key"] for c in soft_fail],
            "limiting_toggles": sorted({t for c in hard_fail for t in c["toggle"].split(",") if t and t != "-"}),
            "hover_forces_n": u_h.tolist(), "power_model": pw.model, "evidence": rm.evidence,
            "labels": rm.labels}
