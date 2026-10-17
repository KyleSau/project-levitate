"""Closed-loop simulation runner and state recorder.

Real-time integrator: classical 4th-order Runge-Kutta, fixed step dt (default 1 ms), quaternion
re-normalised after every step; controller runs at a fixed rate (default 500 Hz, zero-order hold),
deterministic for a given seed. Offline high-accuracy mode integrates every control interval with
SciPy solve_ivp (DOP853, rtol 1e-9) instead of RK4 (see offline.py) - same plant, same controller.

Step-size choice: the stiffest modes are the ground-contact modes. At construction the plant linearises
the resting contact system (finite-difference Jacobian) and, whenever the board is within 5 mm of the
ground, sub-steps RK4 so that |lambda_max h| <= 2.0 (RK4 real-axis stability limit 2.785); in free flight
the full step is used (free-flight modes are < 100 rad/s). tests/test_contact_convergence.py verifies
4th-order convergence, contact stability and step-size independence.
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from . import quat
from .controller import Controller, Gains
from .feasibility import analyse
from .mission import Autopilot, Step, demo_mission
from .modes import ModeConfig, resolve
from .plant import Plant
from .vehicle import VehicleConfig, default_vehicle, mass_properties


class SimSettings(BaseModel):
    dt: float = Field(0.001, gt=0, le=0.005)
    record_hz: float = 100.0
    t_max_s: float = 60.0
    integrator: Literal["rk4", "dop853"] = "rk4"
    seed: int = 0


class SimRequest(BaseModel):
    vehicle: VehicleConfig | None = None
    total_mass_kg: float | None = None          # convenience: rebuild default vehicle with this mass
    cg_m: tuple[float, float, float] | None = None
    mode: ModeConfig = Field(default_factory=ModeConfig)
    gains: Gains = Field(default_factory=Gains)
    mission: list[Step] | None = None
    settings: SimSettings = Field(default_factory=SimSettings)
    name: str = "demo mission"


def build_vehicle(req: SimRequest) -> VehicleConfig:
    from .vehicle import scale_total_mass, set_cg
    v = req.vehicle or default_vehicle()
    if req.total_mass_kg is not None:
        v = scale_total_mass(v, req.total_mass_kg)
    if req.cg_m is not None:
        v = set_cg(v, req.cg_m)
    return v


def _r(a, nd=7):
    """Round for transport; keeps ~7 significant digits for typical magnitudes."""
    if isinstance(a, (list, tuple, np.ndarray)):
        return [_r(z, nd) for z in a]
    a = float(a)
    if not math.isfinite(a):
        return None
    if a == 0.0:
        return 0.0
    return round(a, max(0, nd - int(math.floor(math.log10(abs(a))))))


class Recorder:
    def __init__(self):
        self.ch: dict[str, list] = {}

    def add(self, **kw):
        for k, v in kw.items():
            self.ch.setdefault(k, []).append(v)


def impulse_force(mc: ModeConfig, t: float) -> np.ndarray:
    F = np.zeros(3)
    for imp in mc.disturbances.impulses:
        if imp.t_s <= t < imp.t_s + imp.duration_s:
            F += np.array(imp.force_n)
    return F


def run(req: SimRequest, progress=None) -> dict:
    t_wall = time.perf_counter()
    mc = req.mode
    st = req.settings
    v0 = build_vehicle(req)
    rm = resolve(v0, mc)
    plant = Plant(rm, mc.environment)
    feas = analyse(rm, mc, plant)
    rng = np.random.default_rng(st.seed)
    mission = req.mission or demo_mission()
    if req.mission is None and not mc.disturbances.impulses:
        # demo: lateral gust impulse during the hover segment B (t ~ 5 s) to show disturbance rejection
        from .modes import Impulse
        mc = mc.model_copy(deep=True)
        mc.disturbances.impulses = [Impulse(t_s=5.0, duration_s=0.10, force_n=(0.0, 0.04, 0.0))]
    m_model = plant.m * (1 + mc.disturbances.controller_mass_error)
    ctrl = Controller(plant, req.gains, rm.f_min, rm.f_max, mass_model=m_model, torque_limit=rm.torque_limit,
                      power_cap_w=rm.power_cap_w)
    x = plant.rest_state()
    h_cg = plant.cg[2] + rm.vehicle.height_m / 2
    ap = Autopilot(mission, plant.m * plant.g, h_cg, x)
    dt = st.dt
    ctrl_every = max(1, int(round(1.0 / (req.gains.control_hz * dt))))
    dtc = ctrl_every * dt
    rec_every = max(1, int(round(1.0 / (st.record_hz * dt))))
    n = plant.n
    delay_n = int(round(rm.transport_delay_s / dtc))
    fifo: deque = deque([np.zeros(n)] * delay_n, maxlen=max(delay_n, 1)) if delay_n > 0 else None
    u_app = np.zeros(n)
    u_cmd = np.zeros(n)
    diag: dict = {}
    temps = np.full(n, rm.thermal.ambient_c if rm.thermal else 25.0)
    derate = np.ones(n)
    gust = np.zeros(3)
    rec = Recorder()
    flags = dict(battery_depleted=False, thermal_derate=False, loss_of_control=False, diverged=False,
                 thrust_deficit_s=0.0, power_limited_s=0.0, saturated_s=0.0)
    failed_act = mc.disturbances.actuator_failure_index
    inst = ~plant.lag
    t = 0.0
    k = 0
    n_max = int(st.t_max_s / dt)
    use_dop = st.integrator == "dop853"
    if use_dop:
        from .offline import dop853_interval
    ref = None
    last_ref_phase = None
    max_pen = 0.0
    while k < n_max:
        t = k * dt
        if k % ctrl_every == 0:
            meas = x.copy()
            if mc.disturbances.sensor_noise_pos_m:
                meas[0:3] += rng.normal(0, mc.disturbances.sensor_noise_pos_m, 3)
            if mc.disturbances.sensor_noise_att_rad:
                dth = rng.normal(0, mc.disturbances.sensor_noise_att_rad, 3)
                meas[6:10] = quat.normalize(quat.mul(x[6:10], np.array([1.0, *(dth / 2)])))
            c = plant.contact(x[0:3], x[3:6], quat.to_rot(x[6:10]), x[10:13])
            contact_n = c[2] if c else 0.0
            ref = ap.update(t, meas, contact_n, dtc)
            if ap.done:
                break
            f_min = np.array(rm.f_min, float)
            f_max = np.array(rm.f_max, float) * derate
            if failed_act is not None and t >= mc.disturbances.actuator_failure_t_s:
                f_min[failed_act] = f_max[failed_act] = 0.0
                if not any(e["kind"] == "ACTUATOR_FAILURE" for e in ap.events):
                    ap.event(t, "ACTUATOR_FAILURE", f"actuator A{failed_act} failed (force forced to 0)")
            if rm.energy_j < math.inf and x[-1] >= rm.energy_j:
                f_min[:] = 0.0
                f_max[:] = 0.0
                if not flags["battery_depleted"]:
                    flags["battery_depleted"] = True
                    ap.event(t, "BATTERY_DEPLETED", f"usable battery energy {rm.energy_j:.0f} J exhausted")
            if flags["loss_of_control"]:
                ref.armed = False
            u_cmd, diag = ctrl.update(meas, ref, f_min, f_max)
            u_cmd = np.clip(u_cmd, f_min, f_max)
            airborne = contact_n == 0.0
            if diag.get("thrust_deficit") and ref.armed:
                flags["thrust_deficit_s"] += dtc
                if flags["thrust_deficit_s"] >= 0.5 and not any(e["kind"] == "THRUST_DEFICIT" for e in ap.events):
                    ap.event(t, "THRUST_DEFICIT", "commanded vertical force exceeds available thrust: cannot hold altitude")
            if diag.get("power_limited"):
                flags["power_limited_s"] += dtc
                if not any(e["kind"] == "POWER_LIMIT" for e in ap.events):
                    ap.event(t, "POWER_LIMIT", "electrical power cap reached: thrust scaled down")
            if diag.get("saturated") and airborne:
                flags["saturated_s"] += dtc
            if fifo is not None:
                fifo.append(u_cmd.copy())
                u_app = fifo[0]
            else:
                u_app = u_cmd
            x[13:13 + n][inst] = u_app[inst]
            # thermal model (lumped, explicit Euler at control rate; time constant R C ~ 40 s >> dtc)
            if rm.thermal is not None and rm.power.kind == "rotor":
                th = rm.thermal
                eta = mc.efficiency.motor_efficiency if mc.efficiency.enabled else 1.0
                q_heat = rm.power.actuator_power(x[13:13 + n]) * (1 - eta)
                temps += dtc * (q_heat - (temps - th.ambient_c) / th.thermal_resistance_k_per_w) / th.heat_capacity_j_per_k
                derate = np.clip(1.0 - (temps - th.max_temp_c) / 10.0, 0.0, 1.0)
                if np.any(derate < 1) and not flags["thermal_derate"]:
                    flags["thermal_derate"] = True
                    ap.event(t, "THERMAL_DERATE", f"actuator temperature above {th.max_temp_c} C: force derated")
            # loss of control
            tilt = math.degrees(math.acos(max(-1.0, min(1.0, quat.to_rot(x[6:10])[2, 2]))))
            if tilt > 75 and not flags["loss_of_control"] and x[2] > h_cg + 0.005:
                flags["loss_of_control"] = True
                ap.event(t, "LOSS_OF_CONTROL", f"tilt {tilt:.0f} deg > 75 deg: motors disarmed")
        f_ext = impulse_force(mc, t)
        if mc.disturbances.gust_std_n:
            a_ou = dt / mc.disturbances.gust_tau_s
            gust = gust * (1 - a_ou) + mc.disturbances.gust_std_n * math.sqrt(2 * a_ou) * rng.normal(0, 1, 3)
            f_ext = f_ext + gust
        if k % rec_every == 0:
            _record(rec, plant, x, u_app, u_cmd, f_ext, ref, ap, diag, temps, t)
            cz = (x[0:3][2] + (plant.corners @ quat.to_rot(x[6:10]).T)[:, 2]).min()
            max_pen = max(max_pen, -cz)
        if use_dop:
            x = dop853_interval(plant, x, u_app, f_ext, dt)
        else:
            x = plant.step(x, u_app, f_ext, dt)
        if not np.all(np.isfinite(x)) or abs(x[2]) > 1e3:
            flags["diverged"] = True
            ap.event(t, "DIVERGED", "state not finite")
            break
        k += 1
        if progress and k % 2000 == 0:
            progress(k / n_max)
    _record(rec, plant, x, u_app, u_cmd, impulse_force(mc, t), ref, ap, diag, temps, t + dt)
    wall = time.perf_counter() - t_wall
    return _package(req, mc, rm, plant, feas, rec, ap, flags, wall, max_pen, k * dt)


def _record(rec: Recorder, plant: Plant, x, u_app, u_cmd, f_ext, ref, ap: Autopilot, diag, temps, t):
    wr = plant.wrench(x, f_ext)
    R = wr["R"]
    a = plant.accel(R, wr["F_net_w"])
    roll, pitch, yaw = quat.to_euler_zyx(x[6:10])
    w = x[10:13]
    wdot = plant.Jinv @ (wr["tau_net_b"] - quat.cross(w, plant.J @ w))
    ke, pe = plant.energy(x)
    phase_i, seg, label = ap.phase_label()
    f_act = wr["f_actual"]
    p_el = plant.electrical_power(x[13:13 + plant.n])
    pr = ref.p if ref else tuple(x[0:3])
    vr = ref.v if ref else (0.0, 0.0, 0.0)
    rec.add(t=_r(t), pos=_r(x[0:3]), vel=_r(x[3:6]), acc=_r(a), quat=_r(x[6:10]),
            euler_deg=_r(np.degrees([roll, pitch, yaw])), omega=_r(w), omega_dot=_r(wdot),
            f_act=_r(f_act), f_cmd=_r(u_cmd), F_grav=_r(wr["F_grav_w"]), F_act=_r(wr["F_act_w"]),
            F_drag=_r(wr["F_drag_w"]), F_contact=_r(wr["F_contact_w"]), F_ext=_r(wr["F_ext_w"]),
            F_net=_r(wr["F_net_w"]), tau_act=_r(wr["tau_act_b"]), tau_drag=_r(wr["tau_drag_b"]),
            tau_contact=_r(wr["tau_contact_b"]), tau_net=_r(wr["tau_net_b"]), contact_n=_r(wr["contact_N"]),
            contact_pts=wr["contact_pts"], ref_pos=_r(pr), ref_vel=_r(vr),
            ref_yaw_deg=_r(math.degrees(ref.yaw) if ref else 0.0),
            err_pos=_r(np.array(pr) - x[0:3]), power_w=_r(p_el), energy_j=_r(x[-1]), temp_c=_r(temps),
            ke_j=_r(ke), pe_j=_r(pe), L_world=_r(plant.angular_momentum_world(x)), phase=phase_i,
            tilt_cmd_deg=_r(diag.get("tilt_cmd", 0.0)), saturated=bool(diag.get("saturated", False)),
            armed=bool(ref.armed) if ref else False, kge=_r(wr["kge"]))


def _package(req, mc, rm, plant, feas, rec, ap, flags, wall, max_pen, t_end) -> dict:
    ch = rec.ch
    mp = plant.mp
    pos = np.array(ch["pos"])
    phases = [{"index": i, "segment": s.segment, "kind": s.kind, "label": s.label or s.kind}
              for i, s in enumerate(ap.steps)]  # may be truncated by a mission abort
    # hover check: segment B mean upward actuator force vs weight
    ph = np.array(ch["phase"])
    hov = [i for i, s in enumerate(ap.steps) if s.segment == "B"]
    F_act = np.array(ch["F_act"])
    sel = np.isin(ph, hov)
    hover_force = float(F_act[sel, 2].mean()) if sel.any() else None
    alt = pos[:, 2] - (plant.cg[2] + rm.vehicle.height_m / 2)
    kinds = [e["kind"] for e in ap.events]
    err = np.array(ch["err_pos"])
    airborne = np.array(ch["contact_n"]) == 0
    summary = {
        "mode": rm.mode, "evidence": rm.evidence, "mass_kg": mp.mass_kg, "weight_n": mp.weight_n,
        "sim_time_s": t_end, "wall_time_s": round(wall, 3), "frames": len(ch["t"]),
        "max_ground_clearance_m": float(alt.max()), "takeoffs": ap.takeoff_count, "landings": ap.landing_count,
        "hover_mean_actuator_force_n": hover_force,
        "hover_force_over_weight": hover_force / mp.weight_n if hover_force else None,
        "rms_pos_error_airborne_m": float(np.sqrt((err[airborne] ** 2).sum(axis=1).mean())) if airborne.any() else None,
        "max_tilt_deg": float(np.max(np.abs(np.array(ch["euler_deg"])[:, 0:2]))) if ch["euler_deg"] else 0.0,
        "energy_j": float(ch["energy_j"][-1]), "max_ground_penetration_m": float(max_pen),
        "completed_mission": ap.done or ap.i >= len(ap.steps) - 1,
        "failures": [k for k in kinds if k in ("TAKEOFF_FAILED", "MISSION_ABORT", "THRUST_DEFICIT", "BATTERY_DEPLETED",
                                               "LOSS_OF_CONTROL", "DIVERGED", "ACTUATOR_FAILURE", "THERMAL_DERATE")],
        **{k: v for k, v in flags.items()},
    }
    return {
        "name": req.name, "summary": {k: (_r(v) if isinstance(v, float) else v) for k, v in summary.items()},
        "events": ap.events, "phases": phases, "feasibility": feas,
        "vehicle": vehicle_payload(rm, plant), "labels": rm.labels, "power_model": rm.power.model,
        "air": {"rho": rm.rho, "mu": rm.mu, "source": rm.air_source},
        "settings": req.settings.model_dump(), "gains": req.gains.model_dump(),
        "mode_config": mc.model_dump(mode="json"),
        "integrator": ("RK4 fixed step" if req.settings.integrator == "rk4" else "SciPy solve_ivp DOP853 per control interval")
                      + f", dt = {req.settings.dt*1000:.3g} ms, controller {req.gains.control_hz:.0f} Hz ZOH",
        "trajectory": ch,
    }


def vehicle_payload(rm, plant: Plant) -> dict:
    v = rm.vehicle
    mp = plant.mp
    return {
        "name": v.name, "length_m": v.length_m, "width_m": v.width_m, "height_m": v.height_m,
        "mass_kg": mp.mass_kg, "cg_m": list(mp.cg_m), "inertia_kgm2": mp.inertia_kgm2,
        "principal_moments_kgm2": list(mp.principal_moments_kgm2), "inertia_valid": mp.valid,
        "components": [c.model_dump() for c in v.components],
        "actuators": [{**a.model_dump(), "max_force_n": _r(fm), "min_force_n": _r(fn)}
                      for a, fm, fn in zip(v.actuators, rm.f_max, rm.f_min)],
        "added_mass_kg": list(v.added_mass_kg), "drag": v.drag.model_dump(), "contact": v.contact.model_dump(),
        "B": plant.B.tolist(), "hypothetical": rm.hypothetical,
    }
