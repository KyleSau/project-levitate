"""Board-level electroaerodynamic (ionic wind) hoverboard model.

Per-wire physics comes from the coupled corona solver (solvers/ehd_bipolar.py) through a cached
reduced-order surrogate:  I'(V) = C V (V - V0)   (Townsend form, fitted)  and
T' = kappa * I' * D / mu  (kappa fitted; ~0.9-0.95 from the solver).  Because the drift-only model
is linear in mobility, rho and phi are independent of mu: thrust at a given voltage is mu-independent
and current/power scale with mu. The surrogate is rebuilt automatically when solver code changes.

System model: n_stages stacked wire-to-collector stages across the board footprint, a DC-DC
high-voltage converter, a LiPo cell, avionics, collectors (mesh), frames. Every uncertain parameter
is an Assumption. An independent analytical upper bound (space-charge-limited thrust density
9/8 eps0 E^2 per stage) is reported alongside.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field

from .catalog import BATTERIES
from .constants import EPS0, G0
from .physics import battery as batt_model
from .provenance import SCENARIOS, Assumption, AssumptionSet, Evidence, SourceStatus, code_fingerprint
from .solvers.ehd_bipolar import BipolarCoronaSolver, CoronaGeometry

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SURROGATE_PATH = DATA_DIR / "ehd_surrogate.json"
MU_REF = 2.0e-4

SURR_GAPS_MM = (3, 5, 8, 12, 20, 30)
SURR_RADII_UM = (12.5, 25, 50)
SURR_V_OVER_V0 = (1.4, 2.0, 3.0, 4.5)
SURR_GRID = (48, 96)
GRID_UNCERTAINTY = 0.04   # measured coarse-vs-fine thrust difference at this grid (see research log)


def ehd_assumptions() -> AssumptionSet:
    s = AssumptionSet()
    LIT, ENG = SourceStatus.PEER_REVIEWED, SourceStatus.ENGINEERING_JUDGMENT
    s.add(Assumption(key="ion_mobility", description="Positive ion mobility in air", nominal=2.0e-4, low=1.8e-4,
                     high=2.2e-4, unit="m^2/(V s)", favourable="low", status=LIT,
                     source="Positive air ions 1.4-2.2e-4 (humidity dependent); Moreau 2007, Masuyama 2013"))
    s.add(Assumption(key="spark_mean_field", description="Max mean gap field V/D before sparkover (wire-plane, +DC)",
                     nominal=0.8e6, low=0.5e6, high=1.2e6, unit="V/m", favourable="high", status=ENG,
                     source="Positive wire-plane sparkover ~0.5-1.2 MV/m at cm gaps; humidity, dust, edges reduce it"))
    s.add(Assumption(key="hv_specific_power", description="HV DC-DC converter output power per mass",
                     nominal=400.0, low=150.0, high=1200.0, unit="W/kg", favourable="high", status=LIT,
                     source="Xu et al., Nature 563 (2018): 1.2 kW/kg bespoke 40 kV converter; COTS modules ~0.1-0.3 kW/kg"))
    s.add(Assumption(key="hv_efficiency", description="HV converter efficiency", nominal=0.80, low=0.60, high=0.85,
                     unit="-", favourable="high", status=LIT, source="Xu et al. 2018 reported ~85%"))
    s.add(Assumption(key="thrust_after_drag", description="Fraction of electrostatic thrust left after electrode/"
                     "collector aerodynamic drag in the induced jet", nominal=0.75, low=0.5, high=0.9, unit="-",
                     favourable="high", status=ENG, source="Masuyama & Barrett 2013 found significant collector drag"))
    s.add(Assumption(key="array_interaction", description="Thrust retained when wires form an array "
                     "(mutual shielding of neighbouring emitters, not captured by single-wire solve)",
                     nominal=0.85, low=0.6, high=1.0, unit="-", favourable="high", status=ENG,
                     source="Neighbouring corona wires lower each other's surface field; to be replaced by a "
                     "periodic-array solve"))
    s.add(Assumption(key="collector_areal_density", description="Collector mesh/foil areal density",
                     nominal=40.0, low=20.0, high=100.0, unit="g/m^2", favourable="low", status=ENG,
                     source="Fine metal mesh 50-150 g/m^2; metallised polymer mesh 15-40 g/m^2"))
    s.add(Assumption(key="stage_frame_mass", description="Insulating frame + standoffs per stage",
                     nominal=0.8, low=0.4, high=1.5, unit="g", favourable="low", status=ENG, source="estimate"))
    s.add(Assumption(key="mass_growth", description="Mass growth allowance", nominal=1.06, low=1.03, high=1.12,
                     unit="-", favourable="low", status=ENG, source="concept-stage allowance"))
    s.add(Assumption(key="battery_specific_energy_derate", description="Usable fraction of nameplate energy",
                     nominal=0.80, low=0.70, high=0.88, unit="-", favourable="high", status=ENG, source="as rotor model"))
    return s


# ------------------------------------------------------------------------------------ surrogate
def _onset_voltage(r_w: float, D: float) -> float:
    from .solvers.ehd_bipolar import peek_onset_field
    return peek_onset_field(r_w) * r_w * math.acosh(D / r_w)


def build_surrogate(progress=None) -> dict:
    entries = []
    total = len(SURR_GAPS_MM) * len(SURR_RADII_UM)
    for gi, D_mm in enumerate(SURR_GAPS_MM):
        for ri, r_um in enumerate(SURR_RADII_UM):
            D, r = D_mm / 1000, r_um * 1e-6
            V0 = _onset_voltage(r, D)
            solver = BipolarCoronaSolver(CoronaGeometry(r_wire=r, gap=D), *SURR_GRID, mobility=MU_REF)
            pts = []
            for k in SURR_V_OVER_V0:
                res = solver.solve(k * V0, strips=(D, 1.5 * D, 2 * D, 3 * D))
                pts.append({"V": res.voltage, "I": res.current_per_length, "T": res.thrust_per_length,
                            "strip": res.strip_force_fraction, "cons_err": res.current_conservation_error})
            V = np.array([p["V"] for p in pts])
            I = np.array([p["I"] for p in pts])
            T = np.array([p["T"] for p in pts])
            # least squares fit I = C V (V - V0f) -> I = C V^2 - C V0f V
            A = np.column_stack([V ** 2, -V])
            c1, c2 = np.linalg.lstsq(A, I, rcond=None)[0]
            C, V0f = float(c1), float(c2 / c1)
            kappa = T * MU_REF / (I * D)
            kfit = np.polyfit(V / V0, kappa, 1)
            pred = C * V * (V - V0f)
            entries.append({"gap_mm": D_mm, "r_um": r_um, "V0_peek": V0, "C": C, "V0_fit": V0f,
                            "kappa_fit": kfit.tolist(), "fit_rel_err_max": float(np.max(np.abs(pred / I - 1))),
                            "points": pts})
            if progress:
                progress((gi * len(SURR_RADII_UM) + ri + 1) / total)
    out = {"code_sha": code_fingerprint(), "grid": SURR_GRID, "mu_ref": MU_REF, "grid_uncertainty": GRID_UNCERTAINTY,
           "evidence": Evidence.SIMPLIFIED_NUMERICAL.value, "entries": entries}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SURROGATE_PATH.write_text(json.dumps(out, indent=1))
    return out


_SURR_CACHE: dict | None = None


def load_surrogate(rebuild_if_stale: bool = False) -> dict:
    global _SURR_CACHE
    if _SURR_CACHE is not None:
        return _SURR_CACHE
    if SURROGATE_PATH.exists():
        s = json.loads(SURROGATE_PATH.read_text())
        if not rebuild_if_stale or s.get("code_sha") == code_fingerprint():
            _SURR_CACHE = s
            return s
    _SURR_CACHE = build_surrogate()
    return _SURR_CACHE


def wire_performance(V: float, D: float, r_w: float, mobility: float, pitch: float) -> dict:
    """Interpolated per-length current, thrust and in-strip force fraction for one wire (bilinear in
    log D, log r over the surrogate table; Townsend form in V)."""
    s = load_surrogate()
    ent = s["entries"]
    gaps = np.array(sorted({e["gap_mm"] for e in ent}), float)
    radii = np.array(sorted({e["r_um"] for e in ent}), float)
    D_mm, r_um = D * 1000, r_w * 1e6
    lg = np.clip(np.log(D_mm), np.log(gaps[0]), np.log(gaps[-1]))
    lr = np.clip(np.log(r_um), np.log(radii[0]), np.log(radii[-1]))
    gi = int(np.clip(np.searchsorted(np.log(gaps), lg) - 1, 0, len(gaps) - 2))
    ri = int(np.clip(np.searchsorted(np.log(radii), lr) - 1, 0, len(radii) - 2))
    tg = (lg - np.log(gaps[gi])) / (np.log(gaps[gi + 1]) - np.log(gaps[gi]))
    tr = (lr - np.log(radii[ri])) / (np.log(radii[ri + 1]) - np.log(radii[ri]))
    V0 = _onset_voltage(r_w, D)
    acc = {"I": 0.0, "T": 0.0, "strip": 0.0}
    for (a, b, w) in ((gi, ri, (1 - tg) * (1 - tr)), (gi + 1, ri, tg * (1 - tr)),
                      (gi, ri + 1, (1 - tg) * tr), (gi + 1, ri + 1, tg * tr)):
        e = next(x for x in ent if x["gap_mm"] == gaps[a] and x["r_um"] == radii[b])
        # evaluate at the same V/V0 ratio by interpolating the solver points (I/V^2 and T/V^2 vs V/V0,
        # exact at the nodes), then rescale with the Townsend dependence I ~ V^2 / D^2
        k = V / V0
        Ve = k * e["V0_peek"]
        ks = np.array(SURR_V_OVER_V0)
        iv = np.array([p["I"] / p["V"] ** 2 for p in e["points"]])
        tv = np.array([p["T"] / p["V"] ** 2 for p in e["points"]])
        if k <= 1.0:
            Ie = Te = 0.0
        elif k < ks[0]:
            # between onset and first point: Townsend shape I ~ V (V - V0) anchored at the first point
            f = (1 - 1 / k) / (1 - 1 / ks[0])
            Ie, Te = iv[0] * f * Ve ** 2, tv[0] * f * Ve ** 2
        else:
            Ie = float(np.interp(k, ks, iv)) * Ve ** 2     # flat extrapolation beyond the last point
            Te = float(np.interp(k, ks, tv)) * Ve ** 2
        # scale current: I ~ V^2 / D^2-ish; use the exact ratio of Townsend scaling C ~ 1/D^2
        scale_I = (V / Ve) ** 2 * ((e["gap_mm"] / 1000) / D) ** 2
        scale_T = scale_I * D / (e["gap_mm"] / 1000)
        # in-strip fraction for this pitch (interpolate over pitch/D)
        sf = e["points"][min(range(len(SURR_V_OVER_V0)), key=lambda i: abs(SURR_V_OVER_V0[i] - k))]["strip"]
        ratios = np.array([1.0, 1.5, 2.0, 3.0])
        fr = np.array(list(sf.values()))
        strip = float(np.interp(pitch / D, ratios, fr))
        acc["I"] += w * Ie * scale_I
        acc["T"] += w * Te * scale_T
        acc["strip"] += w * strip
    acc["I"] *= mobility / MU_REF
    acc["V0"] = V0
    acc["corona"] = V > V0
    return acc


# ------------------------------------------------------------------------------------ system model
class EADDesign(BaseModel):
    name: str = "ead_baseline"
    length_mm: float = Field(100.0, ge=40, le=200)
    width_mm: float = Field(32.0, ge=15, le=80)
    voltage_kv: float = Field(8.0, ge=1, le=60)
    gap_mm: float = Field(8.0, ge=3, le=30)
    wire_radius_um: float = Field(25.0, ge=12.5, le=50)
    pitch_over_gap: float = Field(1.5, ge=1.0, le=3.0)
    n_stages: int = Field(1, ge=1, le=8)
    battery: str = "lipo_1s_300"
    avionics_g: float = Field(2.5, ge=0.5, le=10)
    max_stack_height_mm: float = Field(40.0, ge=5, le=300, description="board thickness budget for all stages")

    @property
    def stack_height_mm(self) -> float:
        return self.n_stages * (self.gap_mm + 3.0)    # gap + collector/frame depth per stage


class EADScenario(BaseModel):
    scenario: str
    corona: bool
    spark_limited: bool
    n_wires_per_stage: int
    thrust_n: float
    weight_n: float
    thrust_to_weight: float
    electrical_power_w: float
    thrust_to_power_n_per_kw: float
    mass_g: float
    mass_breakdown_g: dict[str, float]
    battery_can_supply: bool
    endurance_s: float
    scl_upper_bound_thrust_n: float
    stack_height_mm: float
    feasible: bool
    reasons: list[str]


class EADReport(BaseModel):
    design: EADDesign
    evidence: Evidence = Evidence.SIMPLIFIED_NUMERICAL
    scenarios: dict[str, EADScenario]
    verdict: str
    verdict_reason: str
    per_wire: dict
    notes: list[str]


def evaluate_ead(d: EADDesign, overrides: dict[str, float] | None = None) -> EADReport:
    aset = ehd_assumptions()
    batt = BATTERIES[d.battery]
    L, W = d.length_mm / 1000, d.width_mm / 1000
    D, r = d.gap_mm / 1000, d.wire_radius_um * 1e-6
    V = d.voltage_kv * 1000
    pitch = d.pitch_over_gap * D
    n_w = max(int(W // pitch), 1)
    wire_len = L - 0.004
    out = {}
    per_wire_nominal = {}
    for sc in SCENARIOS:
        v = aset.values(sc, overrides)
        reasons = []
        spark = V / D > v["spark_mean_field"]
        if spark:
            reasons.append(f"mean field {V / D / 1e6:.2f} MV/m exceeds sparkover {v['spark_mean_field'] / 1e6:.2f} MV/m")
        wp = wire_performance(V, D, r, v["ion_mobility"], pitch)
        if sc == "nominal":
            per_wire_nominal = wp
        if not wp["corona"]:
            reasons.append(f"below corona onset ({wp['V0'] / 1000:.1f} kV)")
        T_e = d.n_stages * n_w * wire_len * wp["T"] * min(wp["strip"], 1.0)
        thrust = T_e * v["thrust_after_drag"] * v["array_interaction"] if (wp["corona"] and not spark) else 0.0
        p_out = d.n_stages * n_w * wire_len * wp["I"] * V if wp["corona"] else 0.0
        p_in = p_out / v["hv_efficiency"] + 0.3      # +0.3 W avionics
        m_hv = p_out / v["hv_specific_power"] * 1000 + 1.0   # +1 g packaging/potting floor
        m_coll = d.n_stages * L * W * v["collector_areal_density"]
        m_frame = d.n_stages * v["stage_frame_mass"]
        m_wire = d.n_stages * n_w * wire_len * math.pi * r ** 2 * 19300 * 1000
        breakdown = {"hv_converter": m_hv, "collectors": m_coll, "frames": m_frame, "emitter_wires": m_wire,
                     "battery": batt.mass_g, "avionics": d.avionics_g}
        base = sum(val for k, val in breakdown.items() if k != "battery")
        breakdown["allowance"] = base * (v["mass_growth"] - 1)
        mass_g = sum(breakdown.values())
        weight = mass_g / 1000 * G0
        p_max = batt_model.max_deliverable_power(batt.cells, batt.internal_resistance_ohm, batt.capacity_mah,
                                                 batt.max_continuous_c)
        can_supply = p_in <= p_max
        if not can_supply:
            # corona current (and thrust, ~I at fixed geometry) must be throttled to what the cell delivers
            scale = max(p_max - 0.3, 0.0) / max(p_in - 0.3, 1e-9)
            reasons.append(f"battery-power-limited: needs {p_in:.1f} W, cell delivers {p_max:.1f} W "
                           f"(thrust throttled to {scale:.0%})")
            thrust *= scale
            p_in = p_max
        endurance = batt_model.endurance_s(p_in, batt.cells, batt.internal_resistance_ohm, batt.capacity_mah,
                                           v["battery_specific_energy_derate"])
        e_mean = min(V / D, v["spark_mean_field"])
        scl = d.n_stages * L * W * 9 / 8 * EPS0 * e_mean ** 2
        tw = thrust / weight
        if tw < 1.0:
            reasons.append(f"thrust-to-weight {tw:.3f} < 1")
        too_tall = d.stack_height_mm > d.max_stack_height_mm
        if too_tall:
            reasons.append(f"stack {d.stack_height_mm:.0f} mm exceeds thickness budget {d.max_stack_height_mm:.0f} mm")
        feasible = tw >= 1.3 and not spark and wp["corona"] and endurance >= 60 and not too_tall
        out[sc] = EADScenario(scenario=sc, corona=bool(wp["corona"]), spark_limited=bool(spark),
                              n_wires_per_stage=n_w, thrust_n=thrust, weight_n=weight, thrust_to_weight=tw,
                              electrical_power_w=p_in,
                              thrust_to_power_n_per_kw=thrust / p_in * 1000 if p_in else 0.0, mass_g=mass_g,
                              mass_breakdown_g=breakdown, battery_can_supply=can_supply, endurance_s=endurance,
                              scl_upper_bound_thrust_n=scl, stack_height_mm=d.stack_height_mm, feasible=feasible,
                              reasons=reasons)
    if out["pessimistic"].feasible:
        verdict, why = "FEASIBLE", "lifts with margin under pessimistic assumptions"
    elif out["nominal"].feasible:
        verdict, why = "MARGINAL", "; ".join(out["pessimistic"].reasons)
    else:
        verdict, why = "INFEASIBLE", "; ".join(out["nominal"].reasons) or "insufficient margin"
    notes = [
        f"Per-wire physics: coupled Poisson + ion-drift solver surrogate ({SURR_GRID[0]}x{SURR_GRID[1]} grid, "
        f"~{GRID_UNCERTAINTY:.0%} discretisation uncertainty).",
        "Electrostatic thrust is the Coulomb body force on the air; electrode drag and array shielding are "
        "applied as uncertain multipliers, not solved (needs OpenFOAM/Elmer coupled run).",
        "Space-charge-limited bound uses 9/8 eps0 E^2 per stage, an upper limit on any single-stage DC "
        "ionic thruster at that mean field.",
    ]
    return EADReport(design=d, scenarios=out, verdict=verdict, verdict_reason=why,
                     per_wire={k: float(v) if not isinstance(v, bool) else v for k, v in per_wire_nominal.items()},
                     notes=notes)
