"""End-to-end hover feasibility evaluation of a conventional rotor/ducted-fan hoverboard.

Pipeline: design -> layout -> mass budget -> hover equilibrium (allocation) -> rotor power ->
battery operating point -> endurance -> control authority (LP) -> structure -> constraints,
repeated for pessimistic / nominal / optimistic assumption scenarios. Optional 6-DOF mission sim.
"""
from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel
from scipy.optimize import linprog

from .catalog import BATTERIES, MATERIALS, MOTORS, global_assumptions
from .constants import G0
from .design import Design, RotorLayout, allocation_matrix, rotor_layout
from .physics import battery as batt_model
from .physics import rotor as rotor_model
from .physics.dynamics import SimConfig, SimResult, VehicleParams, simulate
from .physics.mass import MassBudget, battery_dims_m, build_mass_budget
from .provenance import SCENARIOS, Evidence

SUSTAINED_HOVER_MIN_S = 120.0
MIN_THRUST_TO_WEIGHT = 1.5
MIN_ROLL_PITCH_ACCEL = 50.0     # rad/s^2 available while holding hover thrust
MIN_YAW_ACCEL = 5.0
MIN_BENDING_FREQ_HZ = 150.0


class Constraint(BaseModel):
    key: str
    passed: bool
    value: float | None = None
    limit: float | None = None
    message: str
    hard: bool = True


class ScenarioResult(BaseModel):
    scenario: str
    mass_g: float
    weight_n: float
    hover_thrust_per_rotor_n: list[float]
    max_thrust_per_rotor_n: float
    thrust_to_weight: float
    hover_shaft_power_w: float
    hover_electrical_power_w: float
    hover_current_a: float
    hover_c_rate: float
    battery_heat_w: float
    endurance_s: float
    power_loading_g_per_w: float
    disk_loading_n_m2: float
    tip_mach: float
    rpm_hover: float
    authority_rad_s2: dict[str, float]
    bending_freq_hz: float
    ground_effect_thrust_ratio: float
    constraints: list[Constraint]
    feasible: bool


class EvaluationReport(BaseModel):
    design: Design
    evidence: Evidence = Evidence.ANALYTICAL          # of the force/power/endurance model
    evidence_by_part: dict[str, Evidence] = {}
    layout: RotorLayout
    mass_budget: MassBudget
    scenarios: dict[str, ScenarioResult]
    verdict: str                    # FEASIBLE | MARGINAL | INFEASIBLE
    verdict_reason: str
    cost_usd: float
    assumptions_used: dict[str, dict[str, float]]
    geometry: dict
    sim: SimResult | None = None


def _authority(B: np.ndarray, weight: float, t_max: float) -> dict[str, float]:
    """Largest symmetric torque on each axis achievable while holding exactly `weight` of thrust
    and zero torque on the other two axes (linear program, rotor bounds [0, t_max])."""
    n = B.shape[1]
    out = {}
    for ax, name in ((1, "roll"), (2, "pitch"), (3, "yaw")):
        best = math.inf
        for sign in (1, -1):
            others = [i for i in (1, 2, 3) if i != ax]
            A_eq = np.vstack([B[0], B[others[0]], B[others[1]]])
            b_eq = np.array([weight, 0.0, 0.0])
            res = linprog(-sign * B[ax], A_eq=A_eq, b_eq=b_eq, bounds=[(0, t_max)] * n, method="highs")
            best = min(best, max(0.0, sign * float(B[ax] @ res.x)) if res.success else 0.0)
        out[name] = best
    return out


def _bending_frequency(d: Design, lay: RotorLayout, total_mass_kg: float) -> float:
    """Free-free first bending mode of the deck as an Euler-Bernoulli box beam, evaluated at the
    weakest section (through a duct centre). Evidence: analytical estimate."""
    mat = MATERIALS[d.deck_material]
    E = mat.youngs_modulus_gpa * 1e9
    H = d.board_height_mm / 1000
    W = d.width_mm / 1000
    tw = max(d.wall_mm, mat.min_wall_mm) / 1000
    ts = max(d.skin_mm, mat.min_wall_mm) / 1000
    net_skin_w = max(W - 2 * lay.duct_outer_radius_m, 2 * tw) if d.propulsion == "ducted_rotor" else W
    n_webs = 2 + (2 if d.propulsion == "ducted_rotor" else 0)
    # neutral axis approx at mid-height; top skin as flange, webs as rectangles
    I = net_skin_w * ts * (H / 2) ** 2 + n_webs * tw * H ** 3 / 12
    L = d.length_mm / 1000
    mu = total_mass_kg / L
    return (4.730 ** 2 / (2 * math.pi)) * math.sqrt(E * I / (mu * L ** 4))


def _scenario(d: Design, lay: RotorLayout, vals: dict[str, float], scenario: str) -> tuple[ScenarioResult, MassBudget]:
    motor = MOTORS[d.motor]
    batt = BATTERIES[d.battery]
    elec = d.electronics
    mb = build_mass_budget(d, lay, vals)
    m = mb.total_g / 1000
    W = m * G0
    n = len(lay.positions_m)
    D = d.rotor_diameter_mm / 1000
    ducted = d.propulsion == "ducted_rotor"
    kduct = rotor_model.duct_power_factor(ducted, vals["duct_effectiveness"])
    fm = vals["figure_of_merit"]
    eta = min(motor.efficiency * vals["motor_eff_scale"], 0.95)
    cons: list[Constraint] = []

    B = allocation_matrix(lay.positions_m, lay.spins, vals["rotor_torque_ratio"], cg=mb.cg_m)
    rank = int(np.linalg.matrix_rank(B, tol=1e-9))
    cons.append(Constraint(key="controllable", passed=rank == 4, value=rank, limit=4,
                           message="allocation matrix must have rank 4 (thrust + 3 torques)"))
    cons.append(Constraint(key="fits_envelope", passed=lay.fits, message="; ".join(lay.fit_issues) or "fits"))
    cons.append(Constraint(key="prop_size_vs_motor", passed=d.rotor_diameter_mm <= motor.max_prop_diameter_mm,
                           value=d.rotor_diameter_mm, limit=motor.max_prop_diameter_mm,
                           message="rotor diameter within motor's rated prop size"))

    u_hover = np.linalg.pinv(B) @ np.array([W, 0, 0, 0])
    k_ge = rotor_model.ground_effect_thrust_ratio(D / 2, d.hover_altitude_m)
    u_eff = np.maximum(u_hover, 0.0)
    p_shaft = sum(rotor_model.hover_shaft_power(t, D, fm, kduct, d.hover_altitude_m) for t in u_eff)
    p_elec = p_shaft / eta + elec.power_w
    op = batt_model.operating_point(p_elec, batt.cells, batt.internal_resistance_ohm, batt.capacity_mah)
    endurance = batt_model.endurance_s(p_elec, batt.cells, batt.internal_resistance_ohm, batt.capacity_mah,
                                       vals["battery_specific_energy_derate"])

    # max thrust: motor rating, shared battery limit
    p_batt_max = batt_model.max_deliverable_power(batt.cells, batt.internal_resistance_ohm, batt.capacity_mah,
                                                  batt.max_continuous_c)
    p_motor_max = min(motor.max_elec_power_w, max(p_batt_max - elec.power_w, 0) / n)
    t_max = rotor_model.max_thrust_from_shaft_power(p_motor_max * eta, D, fm, kduct)
    tw = n * t_max / W
    auth_torque = _authority(B, W, t_max) if rank == 4 and tw > 1 else {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
    J = np.asarray(mb.inertia_kgm2)
    auth = {"roll": auth_torque["roll"] / J[0, 0], "pitch": auth_torque["pitch"] / J[1, 1],
            "yaw": auth_torque["yaw"] / J[2, 2]}
    f_bend = _bending_frequency(d, lay, m)
    t_mean = float(np.mean(u_eff))
    mach = rotor_model.tip_mach(t_mean, D)
    rpm = rotor_model.rotor_speed_rev_s(t_mean, D) * 60

    cons += [
        Constraint(key="hover_thrust_in_range", passed=bool(np.all(u_hover >= 0) and np.all(u_hover <= t_max)),
                   value=float(u_hover.max()), limit=t_max, message="every rotor's hover thrust within [0, T_max]"),
        Constraint(key="thrust_to_weight", passed=tw >= MIN_THRUST_TO_WEIGHT, value=tw, limit=MIN_THRUST_TO_WEIGHT,
                   message="thrust-to-weight margin for control and climb"),
        Constraint(key="battery_hover_point", passed=op.feasible and op.c_rate <= batt.max_continuous_c,
                   value=op.c_rate, limit=batt.max_continuous_c,
                   message=op.reason or "hover current within derated continuous C"),
        Constraint(key="sustained_hover", passed=endurance >= SUSTAINED_HOVER_MIN_S, value=endurance,
                   limit=SUSTAINED_HOVER_MIN_S, message="hover endurance (s)"),
        Constraint(key="roll_pitch_authority", passed=min(auth["roll"], auth["pitch"]) >= MIN_ROLL_PITCH_ACCEL,
                   value=min(auth["roll"], auth["pitch"]), limit=MIN_ROLL_PITCH_ACCEL,
                   message="angular acceleration available at hover thrust (rad/s^2)"),
        Constraint(key="yaw_authority", passed=auth["yaw"] >= MIN_YAW_ACCEL, value=auth["yaw"], limit=MIN_YAW_ACCEL,
                   message="yaw angular acceleration at hover (rad/s^2)"),
        Constraint(key="tip_mach", passed=mach < 0.5, value=mach, limit=0.5, message="rotor tip Mach number"),
        Constraint(key="deck_bending_mode", passed=f_bend >= MIN_BENDING_FREQ_HZ, value=f_bend,
                   limit=MIN_BENDING_FREQ_HZ, message="first free-free bending mode (Hz) above control bandwidth"),
        Constraint(key="mass_target", passed=mb.total_g <= 50, value=mb.total_g, limit=50, hard=False,
                   message="project mass target 20-50 g"),
    ]
    area = math.pi * (D / 2) ** 2 * n
    res = ScenarioResult(
        scenario=scenario, mass_g=mb.total_g, weight_n=W, hover_thrust_per_rotor_n=u_hover.tolist(),
        max_thrust_per_rotor_n=t_max, thrust_to_weight=tw, hover_shaft_power_w=p_shaft,
        hover_electrical_power_w=p_elec, hover_current_a=op.current_a, hover_c_rate=op.c_rate,
        battery_heat_w=op.heat_w, endurance_s=endurance,
        power_loading_g_per_w=mb.total_g / p_elec if p_elec > 0 else 0.0,
        disk_loading_n_m2=W / area, tip_mach=mach, rpm_hover=rpm, authority_rad_s2=auth,
        bending_freq_hz=f_bend, ground_effect_thrust_ratio=k_ge, constraints=cons, feasible=all(c.passed for c in cons if c.hard),
    )
    return res, mb


def vehicle_params(d: Design, lay: RotorLayout, mb: MassBudget, sres: ScenarioResult, vals: dict[str, float]) -> VehicleParams:
    cg = np.array(mb.cg_m)
    return VehicleParams(
        mass_kg=mb.total_g / 1000, inertia=mb.inertia_kgm2,
        rotor_pos_cg=[tuple((np.array(p) - cg).tolist()) for p in lay.positions_m], spins=lay.spins,
        kappa=vals["rotor_torque_ratio"], t_max_n=sres.max_thrust_per_rotor_n,
        motor_tau_s=vals["motor_time_constant"], rotor_radius_m=d.rotor_diameter_mm / 2000,
        rotor_height_above_bottom_m=cg[2] + d.board_height_mm / 2000,
        drag_area_xy_m2=d.length_mm * d.board_height_mm * 1e-6, drag_area_z_m2=d.length_mm * d.width_mm * 1e-6)


def geometry_payload(d: Design, lay: RotorLayout, mb: MassBudget) -> dict:
    bl, bw, bt = battery_dims_m(BATTERIES[d.battery].capacity_mah)
    return {
        "length_m": d.length_mm / 1000, "width_m": d.width_mm / 1000, "height_m": d.board_height_mm / 1000,
        "skin_m": d.skin_mm / 1000, "wall_m": d.wall_mm / 1000,
        "rotors": [{"pos": p, "spin": s, "r_rotor": d.rotor_diameter_mm / 2000, "r_in": lay.duct_inner_radius_m,
                    "r_out": lay.duct_outer_radius_m} for p, s in zip(lay.positions_m, lay.spins)],
        "ducted": d.propulsion == "ducted_rotor",
        "battery": {"size": [bl, bw, bt], "pos": [0, 0, -d.board_height_mm / 2000 + bt / 2]},
        "avionics": {"size": [0.02, 0.02, 0.004], "pos": [0, 0, d.board_height_mm / 2000 - 0.002]},
        "cg": mb.cg_m,
    }


def evaluate(d: Design, overrides: dict[str, float] | None = None, run_sim: bool = False,
             sim_cfg: SimConfig | None = None) -> EvaluationReport:
    errs = d.validate_keys()
    if errs:
        raise ValueError("; ".join(errs))
    lay = rotor_layout(d)
    aset = global_assumptions()
    results, budgets, used = {}, {}, {}
    for sc in SCENARIOS:
        vals = aset.values(sc, overrides)
        used[sc] = vals
        results[sc], budgets[sc] = _scenario(d, lay, vals, sc)

    if results["pessimistic"].feasible:
        verdict, why = "FEASIBLE", "all hard constraints pass even with pessimistic assumptions"
    elif results["nominal"].feasible:
        failed = [c.key for c in results["pessimistic"].constraints if c.hard and not c.passed]
        verdict, why = "MARGINAL", f"passes at nominal assumptions; pessimistic fails: {', '.join(failed)}"
    else:
        failed = [c.key for c in results["nominal"].constraints if c.hard and not c.passed]
        verdict, why = "INFEASIBLE", f"nominal assumptions fail: {', '.join(failed)}"

    mb = budgets["nominal"]
    rep = EvaluationReport(design=d, layout=lay, mass_budget=mb, scenarios=results, verdict=verdict,
                           verdict_reason=why, cost_usd=mb.cost_usd, assumptions_used=used,
                           geometry=geometry_payload(d, lay, mb))
    if run_sim and results["nominal"].constraints[0].passed and results["nominal"].thrust_to_weight > 1.05:
        vp = vehicle_params(d, lay, mb, results["nominal"], used["nominal"])
        rep.sim = simulate(vp, sim_cfg or SimConfig())
    rep.evidence_by_part = {"mass_budget": Evidence.ANALYTICAL, "rotor_power": Evidence.ANALYTICAL,
                            "endurance": Evidence.ANALYTICAL, "control_authority": Evidence.ANALYTICAL,
                            "structure": Evidence.ANALYTICAL}
    if rep.sim:
        # numerical integration of the closed loop, but driven by the analytical force model
        rep.evidence_by_part["closed_loop_stability"] = Evidence.SIMPLIFIED_NUMERICAL
    return rep
