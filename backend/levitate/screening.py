"""First-principles screening of candidate lift mechanisms for a ~100 x 32 mm, 20-50 g free-flying board.

Every function returns a ScreeningResult with the governing equation, the numbers, and a verdict.
These are analytical estimates: they *eliminate* concepts that violate scale or conservation limits;
they do not prove that surviving concepts work.
"""
from __future__ import annotations

import math

from pydantic import BaseModel

from .constants import EPS0, G0, M_H2, M_HE, MU0, RHO_AIR_SL, gas_density
from .provenance import Evidence

L_REF, W_REF = 0.100, 0.032
A_REF = L_REF * W_REF
M_REF = 0.030           # reference all-up mass for screening [kg]
WEIGHT = M_REF * G0


class ScreeningResult(BaseModel):
    key: str
    mechanism: str
    lift_principle: str
    free_flight: str                 # "yes" | "no" | "conditional"
    verdict: str                     # VIABLE | CONDITIONAL | NOT_VIABLE | BASELINE
    headline: str
    numbers: dict[str, float]
    equations: list[str]
    reasons: list[str]
    safety: str
    scaling: str
    evidence: Evidence = Evidence.ANALYTICAL


def _rotor_reference(area_fraction=0.45, fm=0.42, eta=0.65, duct=0.85, avionics_w=0.45):
    A = area_fraction * A_REF
    p_ideal = WEIGHT ** 1.5 / math.sqrt(2 * RHO_AIR_SL * A)
    p_elec = p_ideal * duct / fm / eta + avionics_w
    return A, p_ideal, p_elec


def ducted_fans() -> ScreeningResult:
    A, pi, pe = _rotor_reference()
    batt_wh = 0.30 * 3.7 * 0.8
    return ScreeningResult(
        key="edf", mechanism="Electric ducted fans (concealed in deck)", lift_principle="Momentum flux of a ducted air jet",
        free_flight="yes", verdict="BASELINE",
        headline=f"~{pe:.1f} W hover for 30 g with fans covering 45% of the deck; ~{batt_wh / pe * 60:.0f} min on a 300 mAh 1S cell",
        numbers={"disk_area_m2": A, "ideal_power_w": pi, "electrical_power_w": pe, "disk_loading_n_m2": WEIGHT / A},
        equations=["P_ideal = T^1.5 / sqrt(2 rho A)", "P_elec = P_ideal * k_duct / (FM * eta_motor)"],
        reasons=["Mature components (micro brushless motors, 1S LiPo, AIO flight controllers)",
                 "Disk area is capped by the 100 x 32 mm footprint -> high disk loading -> poor power loading"],
        safety="Low voltage (3.7 V); spinning blades shrouded by ducts.",
        scaling="Power ~ m^1.5 / sqrt(A): footprint-limited. Larger board or lower mass gives quadratic endurance gains.")


def open_micro_propellers() -> ScreeningResult:
    A, pi, pe = _rotor_reference(area_fraction=1.2, duct=1.0)
    return ScreeningResult(
        key="micro_props", mechanism="Open micro-propellers (outrigger rotors)", lift_principle="Momentum theory (open rotor)",
        free_flight="yes", verdict="VIABLE",
        headline=f"~{pe:.1f} W if rotors may overhang the deck (disk area 1.2x footprint)",
        numbers={"disk_area_m2": A, "electrical_power_w": pe},
        equations=["P_ideal = T^1.5 / sqrt(2 rho A)"],
        reasons=["Lower power than concealed ducts, but rotors outside the outline: no longer looks like a hoverboard",
                 "Exposed blades"],
        safety="Exposed blades at ~60k rpm: eye protection.", scaling="Same momentum-theory scaling as EDF.")


def ionic_wind(n_stages: int = 1, e_mean: float = 0.8e6, mobility: float = 2.0e-4) -> ScreeningResult:
    # space-charge-limited thrust density (Mott-Gurney with drift): T/A <= 9/8 eps0 E^2 ; T/P = 1/(mu E)
    t_density = 9 / 8 * EPS0 * e_mean ** 2
    t_max = n_stages * A_REF * t_density
    e_req = math.sqrt(8 * WEIGHT / (n_stages * A_REF) / (9 * EPS0))
    p_min = WEIGHT * mobility * e_req
    t_over_p = 1 / (mobility * e_mean)
    stages_needed = WEIGHT / (A_REF * t_density)
    return ScreeningResult(
        key="ionic_wind", mechanism="Ionic wind / electroaerodynamic (EAD) thrusters",
        lift_principle="Coulomb force on corona-generated ions, momentum transferred to neutral air by collisions",
        free_flight="no", verdict="NOT_VIABLE",
        headline=(f"Ideal single-stage limit {t_max * 1000:.1f} mN over the deck at {e_mean / 1e6:.1f} MV/m vs "
                  f"{WEIGHT * 1000:.0f} mN weight; needs ~{stages_needed:.0f} stages and >= {WEIGHT * mobility * math.sqrt(8 * WEIGHT / (stages_needed * A_REF) / (9 * EPS0)):.0f} W before converter losses"),
        numbers={"scl_thrust_density_n_m2": t_density, "single_stage_max_thrust_n": t_max,
                 "field_needed_single_stage_v_m": e_req, "min_power_single_stage_w": p_min,
                 "thrust_to_power_n_per_kw_at_e": 1000 * t_over_p, "stages_needed_at_e": stages_needed},
        equations=["j <= 9/8 eps0 mu V^2 / d^3 (space-charge limit)", "T/A <= 9/8 eps0 E^2,  T/P = d/(mu V) = 1/(mu E)",
                   "=> P_min = T mu sqrt(8 (T/A) / (9 eps0))"],
        reasons=["Thrust density is capped by space charge at fields below sparkover (~0.5-1.2 MV/m)",
                 "Single stage over the footprint would need a mean field above air breakdown (3 MV/m)",
                 "Stacking stages multiplies collector/frame mass and still needs tens of watts; HV converters "
                 "deliver only ~0.15-1.2 kW/kg", "See coupled corona solver results (EHD lab) for the full numerical case"],
        safety="5-30 kV; ozone and NOx generation; spark/fire risk. Specialist review required before any build.",
        scaling="T/A ~ E^2 is scale-free, T/P ~ 1/E: favourable only at large area & low disk loading (aircraft, "
                "not 30 g boards). Works for mg-scale ionocraft tethered to external HV supply.")


def ehd_general() -> ScreeningResult:
    r = ionic_wind()
    r.key, r.mechanism = "ehd", "Electrohydrodynamic propulsion (general, in air)"
    r.lift_principle = "Body force rho_e E on a charged fluid; in air this *is* ionic wind"
    r.reasons = ["In atmospheric air EHD reduces to the corona-driven ionic wind case above",
                 "Dielectric-liquid EHD pumps cannot provide thrust in air"] + r.reasons[:2]
    return r


def electrostatic_ground() -> ScreeningResult:
    p_max = 0.5 * EPS0 * (3.0e6) ** 2
    f_max = p_max * A_REF
    return ScreeningResult(
        key="electrostatic", mechanism="Electrostatic levitation against the ground",
        lift_principle="Maxwell stress between charged board and ground",
        free_flight="no", verdict="NOT_VIABLE",
        headline=f"Max Maxwell pressure {p_max:.0f} Pa at breakdown -> {f_max * 1000:.0f} mN, but always ATTRACTIVE toward an uncharged ground",
        numbers={"max_pressure_pa": p_max, "max_force_n": f_max},
        equations=["p = eps0 E^2 / 2,  E < 3 MV/m (air breakdown)", "image charge in a grounded/induced surface -> attraction"],
        reasons=["A charged body is attracted to the induced image charge in any ground surface (sign is wrong)",
                 "Repulsion would require charging the ground with the same polarity (external infrastructure)",
                 "Asphalt, grass, wood are poor/variable conductors; water is attractive too"],
        safety="kV-level charging; ESD hazards.", scaling="Pressure capped at ~40 Pa by breakdown irrespective of size.")


def magnetic_levitation() -> ScreeningResult:
    chi_pg, rho_pg = -4.5e-4, 2200.0
    bgrad = MU0 * rho_pg * G0 / abs(chi_pg)
    return ScreeningResult(
        key="maglev", mechanism="Magnetic levitation (static magnets, diamagnetic, superconducting)",
        lift_principle="Magnetic pressure B^2/(2 mu0) against a magnetised or diamagnetic counterpart",
        free_flight="no", verdict="NOT_VIABLE",
        headline="Ordinary ground (asphalt, soil, wood, water) is essentially non-magnetic: zero lift without a track",
        numbers={"diamagnetic_B_dBdz_required_T2_m": bgrad, "earth_field_T": 5e-5},
        equations=["F = (chi V / mu0) B dB/dz", "Earnshaw: no stable static levitation with permanent magnets alone"],
        reasons=["Needs magnetic track / superconductor (external infrastructure: excluded by the brief)",
                 f"Diamagnetic levitation of pyrolytic graphite needs B dB/dz ~ {bgrad:.0f} T^2/m generated BELOW the board",
                 "Earth's field (~50 uT) gives forces ~10^-9 of weight for any feasible onboard moment"],
        safety="Strong magnets: pinch hazard.",
        scaling="Externally supported levitation only; NOT free flight.")


def hendo_eddy_current(freq_hz: float = 1000.0, L: float = 0.01) -> ScreeningResult:
    sigmas = {"copper_sheet": 5.8e7, "aluminium_sheet": 3.5e7, "sea_water": 5.0, "wet_soil": 0.05,
              "fresh_water": 0.01, "concrete_dry": 1e-4, "asphalt": 1e-6, "dry_wood": 1e-9}
    nums = {}
    for k, s in sigmas.items():
        rm = MU0 * s * 2 * math.pi * freq_hz * L ** 2
        nums[f"lift_fraction_{k}"] = rm ** 2 / (1 + rm ** 2)
    return ScreeningResult(
        key="hendo", mechanism="Hendo-style rotating-magnet eddy-current levitation",
        lift_principle="Time-varying field induces eddy currents in a conductor -> repulsion (Lenz)",
        free_flight="no", verdict="NOT_VIABLE",
        headline=(f"Lift fraction vs perfect conductor: copper {nums['lift_fraction_copper_sheet']:.2f}, "
                  f"sea water {nums['lift_fraction_sea_water']:.1e}, asphalt {nums['lift_fraction_asphalt']:.0e}"),
        numbers=nums,
        equations=["R_m = mu0 sigma omega L^2", "F / F_perfect ~ R_m^2 / (1 + R_m^2) (single-loop circuit model)"],
        reasons=["Works only over thick copper/aluminium (the Hendo board rides on a copper half-pipe)",
                 "Ordinary ground conductivity is 10^7-10^16 times lower than copper",
                 "Also extremely power hungry even over copper (Hendo: ~kW for ~100 kg)"],
        safety="Strong rotating magnets.", scaling="Externally supported levitation only; NOT free flight.")


def hydrogen_buoyancy() -> ScreeningResult:
    rho_h2, rho_he = gas_density(M_H2), gas_density(M_HE)
    lift_per_m3 = (RHO_AIR_SL - rho_h2) * G0
    v_req = WEIGHT / lift_per_m3
    board_vol = L_REF * W_REF * 0.010
    return ScreeningResult(
        key="h2_buoyancy", mechanism="Hydrogen (or helium) buoyancy", lift_principle="Archimedes: displaced air mass",
        free_flight="conditional", verdict="NOT_VIABLE",
        headline=(f"30 g needs {v_req * 1000:.0f} L of H2 (a {2 * (3 * v_req / (4 * math.pi)) ** (1 / 3) * 100:.0f} cm sphere); "
                  f"a 10 mm deck holds {board_vol * 1e6:.0f} mL -> {board_vol * lift_per_m3 / G0 * 1000:.3f} g of lift"),
        numbers={"lift_g_per_litre_h2": lift_per_m3 / G0, "lift_g_per_litre_he": (RHO_AIR_SL - rho_he),
                 "volume_required_l": v_req * 1000, "deck_volume_lift_g": board_vol * lift_per_m3 / G0},
        equations=["L = (rho_air - rho_gas) g V"],
        reasons=["Lift per volume is fixed by gas densities (~1.1 g/L): impossible in a 32 mL envelope",
                 "An external balloon is explicitly excluded by the brief"],
        safety="H2 flammability 4-75% in air.", scaling="Volume ~ mass: requires ~1 L per gram.")


def hydrogen_fuel_cell(p_w: float = 7.0) -> ScreeningResult:
    sp_stack_w_kg = 100.0      # small PEM incl. BOP, sub-10 W class (optimistic)
    m_fc = p_w / sp_stack_w_kg
    t_10min_h2_g = p_w * 600 / (0.5 * 119.96e6) * 1000     # 50 % LHV efficiency
    hydride_wt = 0.015
    m_store = t_10min_h2_g / hydride_wt
    lipo = p_w * 600 / 3600 / 0.135
    return ScreeningResult(
        key="h2_fuel_cell", mechanism="Hydrogen PEM fuel cell power", lift_principle="(power source, not lift)",
        free_flight="yes", verdict="NOT_VIABLE",
        headline=f"{p_w:.0f} W fuel-cell system ~{m_fc * 1000:.0f} g + {m_store:.0f} g hydride for 10 min vs ~{lipo:.0f} g of LiPo",
        numbers={"fc_system_mass_g": m_fc * 1000, "h2_mass_10min_g": t_10min_h2_g, "storage_mass_g": m_store,
                 "lipo_equivalent_g": lipo},
        equations=["m_FC = P / (W/kg)", "m_H2 = P t / (eta LHV)"],
        reasons=["Sub-10 W fuel cells (stack + BOP) reach ~0.05-0.1 kW/kg, an order below LiPo specific power needs",
                 "Storage (hydride ~1.5 wt%, or pressure vessel) dominates for short missions",
                 "Fuel cells win only for long endurance at >1 kg scale"],
        safety="Pressurised/flammable H2; specialist review.", scaling="Advantage grows with endurance and scale; not at 30 g.")


def flapping_wing() -> ScreeningResult:
    return ScreeningResult(
        key="flapping", mechanism="Flapping-wing propulsion", lift_principle="Unsteady vortex lift from oscillating wings",
        free_flight="yes", verdict="NOT_VIABLE",
        headline="29 g flapping MAVs (e.g. DelFly Nimble) need ~33 cm span; inside a 100 x 32 mm outline the swept area is smaller than ducted fans'",
        numbers={"reference_mav_mass_g": 29, "reference_span_m": 0.33},
        equations=["P_induced >= T^1.5 / sqrt(2 rho A_swept)"],
        reasons=["Same momentum bound with smaller swept area if wings must stay inside the outline",
                 "Mechanism mass and fatigue; poor fit to a rigid deck shape"],
        safety="Low.", scaling="Competitive only with large wings relative to body.")


def piezo_actuation() -> ScreeningResult:
    return ScreeningResult(
        key="piezo", mechanism="Piezoelectric actuation (flapping or vibrating surfaces)",
        lift_principle="Piezo bimorph drives a flapping wing or acoustic/synthetic jet",
        free_flight="conditional", verdict="NOT_VIABLE",
        headline="Proven at 0.1-1 g scale (RoboBee-class) with 200-300 V drives; actuator & drive mass do not scale favourably to 30 g",
        numbers={"robobee_mass_mg": 80, "drive_voltage_v": 250},
        equations=["Actuator energy density ~ 1/2 d31^2 Y E^2 per cycle"],
        reasons=["Specific power of piezo stacks + HV drive electronics is below brushless motors at gram-to-tens-of-gram scale",
                 "Still bounded by the same momentum theory within the footprint",
                 "Synthetic jets give mN-level thrust only"],
        safety="200-300 V drive.", scaling="Advantageous below ~1 g where electromagnetic motors lose efficiency.")


def cyclorotor() -> ScreeningResult:
    A_proj = 0.100 * 0.028
    pi = WEIGHT ** 1.5 / math.sqrt(2 * RHO_AIR_SL * A_proj)
    return ScreeningResult(
        key="cyclorotor", mechanism="Cyclorotors (cycloidal rotors along the deck length)",
        lift_principle="Blades on a horizontal drum with cyclic pitch; thrust vector rotates with phase",
        free_flight="yes", verdict="CONDITIONAL",
        headline=f"A 28 mm x 100 mm drum fills the whole deck footprint as 'disk area' (ideal {pi:.1f} W); "
                 "tens-of-gram cyclocopters have been reported (Benedict group, Texas A&M; citation to verify)",
        numbers={"projected_area_m2": A_proj, "ideal_power_w": pi},
        equations=["P_ideal ~ T^1.5 / sqrt(2 rho A_proj), A_proj = span x diameter"],
        reasons=["Uses the full rectangular footprint (better than circular ducts)",
                 "Thrust vectoring by phase-shifting cyclic pitch gives control authority",
                 "Mechanism complexity/mass (pitch links, bearings) and lower TRL; needs a second rotor or tail for roll/yaw",
                 "Candidate for the next numerical study (OpenFOAM moving-mesh)"],
        safety="Internal rotating drum; enclosed.", scaling="Gains from rectangular footprint; mechanism mass penalty at small scale.")


def air_cushion(surface_roughness_mm: float = 1.0, hover_gap_mm: float = 1.0, cd: float = 0.6,
                fan_eff: float = 0.40, motor_eff: float = 0.65) -> dict[str, float]:
    a_c = 0.9 * A_REF
    perim = 2 * (L_REF + W_REF)
    p = WEIGHT / a_c
    h = (hover_gap_mm + surface_roughness_mm) / 1000
    q = cd * perim * h * math.sqrt(2 * p / RHO_AIR_SL)
    p_air = p * q
    return {"cushion_pressure_pa": p, "flow_m3_s": q, "air_power_w": p_air,
            "electrical_power_w": p_air / (fan_eff * motor_eff) + 0.45}


def ground_effect_cushion() -> ScreeningResult:
    surfaces = {"glass_or_wood": 0.2, "concrete": 1.0, "asphalt": 3.0, "short_grass": 20.0, "water_calm": 0.5}
    nums = {}
    for s, rough in surfaces.items():
        nums[f"power_w_{s}"] = air_cushion(rough)["electrical_power_w"]
    _, _, p_hover = _rotor_reference()
    nums["free_hover_power_w"] = p_hover
    return ScreeningResult(
        key="ground_effect", mechanism="Ground-effect / air-cushion (hovercraft) mode",
        lift_principle="Plenum pressure under the deck, power set by leakage flow under the skirt",
        free_flight="no", verdict="CONDITIONAL",
        headline=(f"Over concrete at 1 mm gap ~{nums['power_w_concrete']:.1f} W vs ~{p_hover:.1f} W free hover; "
                  f"over grass ~{nums['power_w_short_grass']:.1f} W (no advantage)"),
        numbers=nums,
        equations=["p = W / A_cushion", "Q = Cd * perimeter * h_eff * sqrt(2 p / rho)", "P = p Q / (eta_fan eta_motor)"],
        reasons=["Real levitation above the surface at mm heights for ~5-10x less power than hovering",
                 "Works over smooth ground and water; collapses over grass/gravel (h_eff dominated by roughness)",
                 "Not free flight: altitude ~ skirt gap; Cheeseman-Bennett rotor ground effect is only ~1-15% at 10-50 mm"],
        safety="Low voltage.", scaling="Power ~ perimeter x gap x p^1.5: small boards are favourable (low cushion pressure).")


def hybrid_cushion_rotor() -> ScreeningResult:
    r = ground_effect_cushion()
    return ScreeningResult(
        key="hybrid", mechanism="Hybrid: ducted fans with switchable plenum (cushion cruise + free flight)",
        lift_principle="Same fans feed a skirted plenum near the ground, exhaust freely in flight",
        free_flight="yes", verdict="CONDITIONAL",
        headline="Combines baseline free flight with low-power cushion cruising over smooth ground or water",
        numbers={"cushion_power_concrete_w": r.numbers["power_w_concrete"], "free_hover_power_w": r.numbers["free_hover_power_w"]},
        equations=["mission energy = P_hover t_flight + P_cushion t_cruise"],
        reasons=["Physically consistent (energy accounting per mode)", "Needs skirt or peripheral-jet geometry and a "
                 "mode valve: added mass ~1-3 g", "Fans must produce ~100 Pa static pressure at low flow (fan map needed)"],
        safety="Low voltage.", scaling="Benefit proportional to fraction of mission spent near smooth ground.")


def cold_gas_or_rocket() -> ScreeningResult:
    isp = 60.0
    mdot = WEIGHT / (isp * G0)
    return ScreeningResult(
        key="cold_gas", mechanism="Cold-gas / micro-rocket thrust (additional candidate)",
        lift_principle="Momentum of expelled propellant", free_flight="yes", verdict="NOT_VIABLE",
        headline=f"CO2 cold gas (Isp~{isp:.0f} s) burns {mdot * 1000:.2f} g/s: a 12 g cartridge hovers ~{12 / (mdot * 1000):.0f} s",
        numbers={"mass_flow_g_s": mdot * 1000, "hover_time_12g_s": 12 / (mdot * 1000)},
        equations=["mdot = T / (Isp g0)"], reasons=["Seconds of hover, not sustained flight"],
        safety="Pressure vessels / pyrotechnics.", scaling="Only for brief boosts.")


def acoustic_levitation() -> ScreeningResult:
    return ScreeningResult(
        key="acoustic", mechanism="Acoustic / squeeze-film levitation (additional candidate)",
        lift_principle="Time-averaged radiation pressure or squeeze-film pressure against a reflector",
        free_flight="no", verdict="NOT_VIABLE",
        headline="Needs a flat reflector within tens of micrometres to millimetres; ordinary ground is not one",
        numbers={}, equations=["p_rad ~ <E_acoustic> (near-field squeeze film: gap << wavelength)"],
        reasons=["Squeeze-film lift exists only at ~10-100 um gaps over flat surfaces", "High ultrasonic power"],
        safety="High-intensity ultrasound.", scaling="Micro-gap only.")


ALL_SCREENS = [ducted_fans, open_micro_propellers, ionic_wind, ehd_general, electrostatic_ground,
               magnetic_levitation, hendo_eddy_current, hydrogen_buoyancy, hydrogen_fuel_cell, flapping_wing,
               piezo_actuation, cyclorotor, ground_effect_cushion, hybrid_cushion_rotor, cold_gas_or_rocket,
               acoustic_levitation]


def screen_all() -> list[ScreeningResult]:
    return [f() for f in ALL_SCREENS]
