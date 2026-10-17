"""Human-carrying hover vehicle sizing (rider 90.7 kg = 200 lb) with downwash / debris as a first-class output.

Physics (all analytical, Evidence.ANALYTICAL):
  * Lift must come from somewhere: in hover, the downward momentum flux of the propulsive jet equals the weight.
    For a jet of total exit area A_e:  T = rho * A_e * v_e^2  ->  v_e = sqrt(T / (rho A_e)).
    Ducted fan with exit-area ratio sigma:  A_e = sigma * A_fan.  Open rotor far wake:  v_w = sqrt(2T/(rho A)).
    So for a given weight, the ONLY lever on downwash velocity (debris) is the jet area. Same lever as power:
    P_ideal = T v_e / 2 for a duct.  Low debris and low power both require large area.
  * Ideal power: open P = T^1.5/sqrt(2 rho A); ducted P = T^1.5/sqrt(4 sigma rho A); real = ideal / FM / eta.
  * Redundancy: with N lift units, the vehicle must hold 1.3 x weight with any one unit failed (N-1 rule).
  * Mass closure: m = rider + avionics + motors + controllers + fans + energy + structure_fraction * m,
    iterated to a fixed point; if it does not converge below 2 t the concept "does not close".
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from .constants import G0, RHO_AIR_SL
from .provenance import SCENARIOS, Assumption, AssumptionSet, Evidence, SourceStatus

RIDER_KG = 90.72
LIT, ENG, CAT = SourceStatus.PEER_REVIEWED, SourceStatus.ENGINEERING_JUDGMENT, SourceStatus.CATALOG_NOMINAL

Concept = Literal["ducted_electric", "open_rotor_electric", "turbojet", "ducted_hybrid", "air_cushion"]


def human_assumptions() -> AssumptionSet:
    s = AssumptionSet()
    a = s.add
    a(Assumption(key="fm_ducted", description="Large ducted fan figure of merit (fan only)", nominal=0.75, low=0.65,
                 high=0.82, unit="-", favourable="high", status=LIT, source="Large ducted fans / lift fans 0.65-0.82"))
    a(Assumption(key="fm_open", description="Large open rotor/propeller hover FM", nominal=0.72, low=0.62, high=0.80,
                 unit="-", favourable="high", status=LIT, source="Multirotor/eVTOL propellers 0.6-0.8"))
    a(Assumption(key="duct_effectiveness", description="Fraction of ideal duct power saving realised", nominal=0.6,
                 low=0.3, high=0.85, unit="-", favourable="high", status=ENG, source="tight tip gaps at large scale"))
    a(Assumption(key="eta_drive", description="Motor + controller efficiency", nominal=0.90, low=0.85, high=0.94,
                 unit="-", favourable="high", status=LIT, source="PM outrunners + FOC controllers"))
    a(Assumption(key="motor_kw_per_kg", description="Motor continuous specific power incl. mount", nominal=5.0,
                 low=3.0, high=8.0, unit="kW/kg", favourable="high", status=CAT, source="EMRAX/T-Motor class"))
    a(Assumption(key="esc_kw_per_kg", description="Controller specific power", nominal=20.0, low=10.0, high=30.0,
                 unit="kW/kg", favourable="high", status=CAT, source="high-power FOC ESCs"))
    a(Assumption(key="batt_wh_per_kg", description="High-power Li-ion pack specific energy (pack level)",
                 nominal=170.0, low=140.0, high=200.0, unit="Wh/kg", favourable="high", status=LIT,
                 source="21700 high-power cells ~230-250 Wh/kg cell, ~70-80% at pack level"))
    a(Assumption(key="batt_kw_per_kg", description="Pack continuous specific power", nominal=1.8, low=1.0, high=3.0,
                 unit="kW/kg", favourable="high", status=LIT, source="high-power cells 2-3 kW/kg cell level"))
    a(Assumption(key="batt_usable", description="Usable fraction of pack energy", nominal=0.85, low=0.80, high=0.90,
                 unit="-", favourable="high", status=ENG, source="SoC window + reserve"))
    a(Assumption(key="fan_kg_per_m2_ducted", description="Ducted fan rotor + duct + mounts per fan area",
                 nominal=6.0, low=4.0, high=10.0, unit="kg/m^2", favourable="low", status=ENG, source="composite ducts"))
    a(Assumption(key="fan_kg_per_m2_open", description="Open rotor + arms + guards per disk area", nominal=3.0,
                 low=2.0, high=5.0, unit="kg/m^2", favourable="low", status=ENG, source="multirotor scaling"))
    a(Assumption(key="structure_fraction", description="Deck/frame/landing gear/rider restraint, fraction of gross",
                 nominal=0.15, low=0.10, high=0.22, unit="-", favourable="low", status=ENG, source="eVTOL/ultralight"))
    a(Assumption(key="avionics_kg", description="Redundant flight control, sensors, wiring, rider controls",
                 nominal=8.0, low=5.0, high=12.0, unit="kg", favourable="low", status=ENG, source="estimate"))
    a(Assumption(key="turbojet_tw", description="Micro turbojet thrust/weight incl. ECU, pump", nominal=11.0, low=8.0,
                 high=14.0, unit="-", favourable="high", status=CAT, source="JetCat P300/P400 class"))
    a(Assumption(key="turbojet_tsfc", description="Turbojet TSFC", nominal=0.16, low=0.13, high=0.20,
                 unit="kg/(N h)", favourable="low", status=CAT, source="P300: ~0.98 L/min at 300 N"))
    a(Assumption(key="turbojet_v_exhaust", description="Turbojet exhaust velocity", nominal=500.0, low=420.0,
                 high=600.0, unit="m/s", favourable="low", status=CAT, source="thrust / mass flow, P300 class"))
    a(Assumption(key="gen_kw_per_kg", description="Engine + generator specific power", nominal=1.2, low=0.8, high=2.0,
                 unit="kW/kg", favourable="high", status=ENG, source="small turboshaft/ICE gensets for UAVs"))
    a(Assumption(key="gen_kg_per_kwh", description="Fuel per electrical kWh (BSFC / generator efficiency)",
                 nominal=0.33, low=0.27, high=0.45, unit="kg/kWh", favourable="low", status=ENG,
                 source="ICE 0.25-0.35, small turboshaft 0.4-0.6 kg/kWh"))
    a(Assumption(key="cushion_fan_eff", description="Lift-fan total-to-static efficiency into the plenum",
                 nominal=0.55, low=0.40, high=0.70, unit="-", favourable="high", status=LIT,
                 source="hovercraft lift fans 0.5-0.75"))
    a(Assumption(key="skirt_kg_per_m", description="Flexible skirt (coated fabric) mass per metre of perimeter",
                 nominal=1.2, low=0.8, high=2.0, unit="kg/m", favourable="low", status=ENG, source="light hovercraft"))
    a(Assumption(key="cost_motor_per_kw", description="Motor + controller cost", nominal=60.0, low=30.0, high=150.0,
                 unit="$/kW", favourable="low", status=ENG, source="hobby to light-aviation grade"))
    a(Assumption(key="cost_batt_per_kwh", description="High-power pack with BMS", nominal=700.0, low=400.0,
                 high=1200.0, unit="$/kWh", favourable="low", status=ENG, source="estimate"))
    a(Assumption(key="cost_fan_per_m2", description="Fans, ducts, guards", nominal=4000.0, low=2000.0, high=8000.0,
                 unit="$/m^2", favourable="low", status=ENG, source="estimate"))
    a(Assumption(key="cost_turbojet_per_n", description="Micro turbojet price per newton", nominal=20.0, low=15.0,
                 high=30.0, unit="$/N", favourable="low", status=CAT, source="P300 ~$6k"))
    a(Assumption(key="cost_gen_per_kw", description="Genset cost", nominal=400.0, low=200.0, high=1000.0,
                 unit="$/kW", favourable="low", status=ENG, source="estimate"))
    return s


class HumanDesign(BaseModel):
    concept: Concept = "ducted_electric"
    lift_area_m2: float = Field(0.5, gt=0.01, le=60, description="total fan/rotor disk area (turbojet: ignored)")
    exit_area_ratio: float = Field(1.0, ge=1.0, le=1.6, description="duct exit/fan area (diffuser), ducted only")
    n_units: int = Field(6, ge=3, le=24)
    mission_min: float = Field(5.0, ge=0.5, le=120)
    payload_kg: float = Field(0.0, ge=0, le=100)
    packing: float = Field(0.6, ge=0.2, le=0.9, description="lift area / deck footprint")
    # air cushion only
    hover_gap_mm: float = Field(8.0, ge=1, le=100, description="skirt hem clearance above the surface")
    surface_roughness_mm: float = Field(3.0, ge=0, le=100, description="0.5 floor, 3 asphalt, 5 water chop, 30 grass")
    cushion_aspect: float = Field(2.5, ge=1, le=5, description="deck length / width")


def debris_class(v: float) -> str:
    """Engineering-judgment bands for jet velocity at the ground (outwash peaks are of the same order)."""
    if v < 12:
        return "low (like a strong breeze: dust and leaves stir)"
    if v < 25:
        return "moderate (leaves, sand, loose litter blown away)"
    if v < 50:
        return "high (grit and small gravel thrown; eye hazard)"
    return "severe (stones thrown, jet-blast; injury hazard)"


class HumanResult(BaseModel):
    scenario: str
    closes: bool
    gross_kg: float
    vehicle_kg: float
    hover_power_kw: float
    installed_power_kw: float
    jet_velocity_m_s: float
    debris: str
    footprint_m2: float
    footprint_side_m: float
    form: str
    endurance_min: float
    mass_breakdown_kg: dict[str, float]
    cost_usd: float
    energy_cost_per_flight_usd: float
    notes: list[str]


class HumanReport(BaseModel):
    design: HumanDesign
    evidence: Evidence = Evidence.ANALYTICAL
    scenarios: dict[str, HumanResult]
    verdict: str


def _size(d: HumanDesign, v: dict[str, float], scenario: str) -> HumanResult:
    N = d.n_units
    fixed = RIDER_KG + d.payload_kg + v["avionics_kg"]
    t_h = d.mission_min / 60
    notes: list[str] = []
    m = fixed / (1 - v["structure_fraction"]) * 1.5
    out: dict[str, float] = {}
    for _ in range(200):
        W = m * G0
        t_unit_max = 1.3 * W / (N - 1)
        if d.concept == "air_cushion":
            # plenum: p = W / A_c ; leakage under the skirt hem Q = Cd * perimeter * h_eff * sqrt(2p/rho)
            A_c = d.lift_area_m2
            width = math.sqrt(A_c / d.cushion_aspect)
            perim = 2 * (width + width * d.cushion_aspect)
            p_c = W / A_c
            h_eff = (d.hover_gap_mm + d.surface_roughness_mm) / 1000
            q = 0.6 * perim * h_eff * math.sqrt(2 * p_c / RHO_AIR_SL)
            p_lift = p_c * q / (v["cushion_fan_eff"] * v["eta_drive"]) / 1000
            p_hover = p_lift * 1.25                    # + thrust/steering fans for low-speed motion
            p_inst = p_hover * 1.4                     # N-1 lift fans + margin
            e_kwh = p_hover * t_h * 1.1 / v["batt_usable"]
            parts = {"motors": p_inst * v["eta_drive"] / v["motor_kw_per_kg"], "controllers": p_inst / v["esc_kw_per_kg"],
                     "fans_ducts": 1.5 * N, "skirt": v["skirt_kg_per_m"] * perim,
                     "battery": max(e_kwh / (v["batt_wh_per_kg"] / 1000), p_inst / v["batt_kw_per_kg"])}
            out["cushion"] = 1.0
        elif d.concept == "turbojet":
            eng = N * t_unit_max / (v["turbojet_tw"] * G0)
            fuel = v["turbojet_tsfc"] * W * t_h * 1.1
            parts = {"engines": eng, "fuel": fuel, "tanks_lines": 0.12 * fuel + 2.0}
            p_hover = W * v["turbojet_v_exhaust"] / 2 / 1000          # jet power (kW) for reference
            p_inst = N * t_unit_max * v["turbojet_v_exhaust"] / 2 / 1000
        else:
            ducted = d.concept != "open_rotor_electric"
            A = d.lift_area_m2
            a_u = A / N
            if ducted:
                k = 1 - v["duct_effectiveness"] * (1 - 1 / math.sqrt(2 * d.exit_area_ratio))
                fm = v["fm_ducted"]
            else:
                k, fm = 1.0, v["fm_open"]
            shaft = lambda T, area: T ** 1.5 * k / (fm * math.sqrt(2 * RHO_AIR_SL * area)) / 1000  # noqa: E731
            p_hover = shaft(W, A) / v["eta_drive"]
            p_unit = shaft(t_unit_max, a_u) / v["eta_drive"]
            p_inst = N * p_unit
            p_peak = (N - 1) * p_unit
            parts = {"motors": p_inst * v["eta_drive"] / v["motor_kw_per_kg"], "controllers": p_inst / v["esc_kw_per_kg"],
                     "fans_ducts": A * v["fan_kg_per_m2_ducted" if ducted else "fan_kg_per_m2_open"]}
            if d.concept == "ducted_hybrid":
                p_gen = p_hover * 1.1
                parts["genset"] = p_gen / v["gen_kw_per_kg"]
                parts["fuel"] = v["gen_kg_per_kwh"] * p_hover * t_h * 1.1
                buf_kw = max(p_peak - p_gen, 0.0)
                parts["buffer_battery"] = max(buf_kw / v["batt_kw_per_kg"], buf_kw * (30 / 3600) / (v["batt_wh_per_kg"] / 1000))
            else:
                e_kwh = p_hover * t_h * 1.1 / v["batt_usable"]
                parts["battery"] = max(e_kwh / (v["batt_wh_per_kg"] / 1000), p_peak / v["batt_kw_per_kg"])
                if p_peak / v["batt_kw_per_kg"] > e_kwh / (v["batt_wh_per_kg"] / 1000):
                    out["power_limited"] = 1.0
        m_new = (fixed + sum(parts.values())) / (1 - v["structure_fraction"])
        if abs(m_new - m) < 1e-4:
            m = m_new
            break
        m = 0.5 * m + 0.5 * m_new
        if m > 2000:
            break
    closes = m <= 2000
    W = m * G0
    parts["structure"] = v["structure_fraction"] * m
    parts["avionics"] = v["avionics_kg"]
    if d.concept == "air_cushion":
        vj = math.sqrt(2 * W / d.lift_area_m2 / RHO_AIR_SL)
        foot = d.lift_area_m2 / 0.9
        notes.append("Leakage jet is a thin horizontal sheet at the skirt hem, not a downward column: "
                     "it moves dust and water spray around the edge rather than blasting the ground below")
        notes.append(f"Hovers ~{d.hover_gap_mm:.0f} mm above the skirt hem; not free flight. "
                     "Works on smooth ground and water; grass/gravel raise leakage (set surface_roughness_mm)")
    elif d.concept == "turbojet":
        vj = v["turbojet_v_exhaust"]
        foot = 0.6
        notes.append("Exhaust ~600-700 C: burns, ignition of dry grass, kerosene fuel on board")
    else:
        A = d.lift_area_m2
        vj = math.sqrt(W / (RHO_AIR_SL * A * d.exit_area_ratio)) if d.concept != "open_rotor_electric" \
            else math.sqrt(2 * W / (RHO_AIR_SL * A))
        foot = A / d.packing
    side = math.sqrt(foot)
    form = "board (rider-sized deck)" if foot <= 0.8 else "platform (2-3 m)" if foot <= 6 else "large platform (>2.5 m)"
    # endurance: re-use the closed design and ask how long the stored energy lasts at hover
    if d.concept in ("ducted_electric", "open_rotor_electric", "air_cushion"):
        e_store = parts["battery"] * v["batt_wh_per_kg"] / 1000 * v["batt_usable"]
        endurance = e_store / p_hover * 60 if p_hover else 0.0
        energy_cost = p_hover * t_h * 0.20 / 0.9      # $0.20/kWh grid, 90 % charging
    else:
        endurance = d.mission_min
        energy_cost = parts.get("fuel", 0.0) / 0.8 * 1.5    # $1.50/L fuel, 0.8 kg/L
    if out.get("power_limited"):
        notes.append("battery sized by peak power, not energy (high-power cells dominate)")
    cost = v["avionics_kg"] * 600
    if d.concept == "turbojet":
        cost += d.n_units * (1.3 * W / (d.n_units - 1)) * v["cost_turbojet_per_n"]
    else:
        fan_cost = (400 * d.n_units + 60 * parts["skirt"]) if d.concept == "air_cushion" \
            else d.lift_area_m2 * v["cost_fan_per_m2"]
        cost += p_inst * v["cost_motor_per_kw"] + fan_cost
        if "battery" in parts:
            cost += parts["battery"] * v["batt_wh_per_kg"] / 1000 * v["cost_batt_per_kwh"]
        if "genset" in parts:
            cost += parts["genset"] * v["gen_kw_per_kg"] * v["cost_gen_per_kw"]
            cost += parts["buffer_battery"] * v["batt_wh_per_kg"] / 1000 * v["cost_batt_per_kwh"]
    cost += parts["structure"] * 80
    return HumanResult(scenario=scenario, closes=closes, gross_kg=m, vehicle_kg=m - RIDER_KG - d.payload_kg,
                       hover_power_kw=p_hover, installed_power_kw=p_inst, jet_velocity_m_s=vj, debris=debris_class(vj),
                       footprint_m2=foot, footprint_side_m=side, form=form, endurance_min=endurance,
                       mass_breakdown_kg={k: round(x, 2) for k, x in parts.items()}, cost_usd=cost,
                       energy_cost_per_flight_usd=energy_cost, notes=notes)


def evaluate_human(d: HumanDesign, overrides: dict[str, float] | None = None) -> HumanReport:
    aset = human_assumptions()
    res = {sc: _size(d, aset.values(sc, overrides), sc) for sc in SCENARIOS}
    n = res["nominal"]
    if not n.closes:
        verdict = "DOES_NOT_CLOSE"
    elif not res["pessimistic"].closes:
        verdict = "CLOSES_NOMINAL_ONLY"
    else:
        verdict = "CLOSES"
    return HumanReport(design=d, scenarios=res, verdict=verdict)


def min_area_for_jet_velocity(gross_kg: float, v_max: float, ducted: bool = True, sigma: float = 1.0) -> float:
    """Smallest lift area that keeps the jet below v_max for a given gross mass (pure momentum, no assumptions)."""
    W = gross_kg * G0
    return W / (RHO_AIR_SL * sigma * v_max ** 2) if ducted else 2 * W / (RHO_AIR_SL * v_max ** 2)
