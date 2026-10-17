"""Every non-law number used by the propulsion experiments, with source, status and a low/nominal/high band.

Status meanings follow `levitate.provenance.SourceStatus`:
  physical_law            exact theory (not stored here, it is in the code)
  peer_reviewed           published measurement / validated model (citation given)
  catalog_nominal         manufacturer/retailer/press figure, not verified by us
  engineering_judgment    plausible estimate that must be measured before any reliance

Engines and thrusters are BLACK BOXES: the parameters below describe external behaviour only (thrust, Isp, mass flow,
mass, throttle range, start/stop limits, exhaust state). No formulation, construction or operating details are modelled
or implied. Any physical validation must be professionally reviewed, unmanned and safely contained.
"""
from __future__ import annotations

from ..provenance import Assumption, AssumptionSet, SourceStatus

LIT, CAT, ENG = SourceStatus.PEER_REVIEWED, SourceStatus.CATALOG_NOMINAL, SourceStatus.ENGINEERING_JUDGMENT


def _a(s: AssumptionSet, key, desc, nom, lo, hi, unit, fav, status, src):
    s.add(Assumption(key=key, description=desc, nominal=nom, low=lo, high=hi, unit=unit, favourable=fav,
                     status=status, source=src))


def coldgas_assumptions() -> AssumptionSet:
    s = AssumptionSet()
    # pressure-vessel performance factor PV/m at SERVICE pressure (not burst), per tank class
    _a(s, "pvw_metal", "Steel/aluminium cylinder PV/m at service pressure", 18e3, 15e3, 22e3, "J/kg", "high", CAT,
       "AL80 SCUBA 11.1 L, 207 bar, ~14.2 kg -> 16 kJ/kg; 12 L 232 bar steel ~14.5 kg -> 19 kJ/kg (typical retail specs)")
    _a(s, "pvw_type3", "Carbon-wrapped aluminium-lined (Type 3) cylinder PV/m incl. valve", 44e3, 36e3, 52e3, "J/kg",
       "high", CAT, "6.8 L 300 bar SCBA cylinders listed at 6.8-7.1 kg filled (Scott/3M 1860, Draeger retail pages) "
                    "minus ~2.2 kg air -> ~4.6-4.9 kg -> 42-44 kJ/kg")
    _a(s, "pvw_type4", "Carbon/polymer-lined (Type 4) automotive tank PV/m (excl. valves)", 98e3, 80e3, 110e3, "J/kg",
       "high", CAT, "Toyota Mirai (2014): 122.4 L at 70 MPa, 87.5 kg for both tanks excl. valves -> 98 kJ/kg")
    _a(s, "nozzle_cd", "Nozzle throat discharge coefficient", 0.97, 0.94, 0.99, "-", "high", LIT,
       "Sutton & Biblarz, Rocket Propulsion Elements (9th ed.) ch. 3: 0.95-0.99 for well-made nozzles")
    _a(s, "nozzle_cf_eff", "Thrust-coefficient efficiency (divergence, friction, boundary layer)", 0.95, 0.90, 0.98, "-",
       "high", LIT, "Sutton & Biblarz ch. 3: 15 deg conical divergence factor 0.983; small nozzles lose more")
    _a(s, "reg_dropout_bar", "Pressure margin a regulator needs above its set point", 5.0, 2.0, 15.0, "bar", "low", ENG,
       "typical high-flow piston regulators; must be measured for any chosen part")
    _a(s, "wall_h", "Gas-to-wall heat-transfer coefficient during blowdown", 100.0, 30.0, 300.0, "W/(m^2 K)", "high", ENG,
       "fast fill/defuel studies of composite tanks report O(10^2) W/m^2K; strongly geometry dependent")
    _a(s, "wall_c", "Effective specific heat of the tank wall/liner", 900.0, 800.0, 1100.0, "J/(kg K)", "high", LIT,
       "aluminium 900, carbon/epoxy ~1000 J/kg K")
    _a(s, "compressor_iso_eff", "HP compressor isothermal efficiency (electrical in -> isothermal work)", 0.43, 0.30,
       0.60, "-", "high", CAT, "breathing-air compressor class ~100 L/min free air to 300 bar at ~2.2 kW electrical "
                                "-> ~1.1 MJ/kg vs 0.48 MJ/kg isothermal minimum")
    _a(s, "elec_price", "Electricity price", 0.20, 0.12, 0.35, "$/kWh", "low", ENG, "residential, 2026")
    _a(s, "cost_tank_metal", "Metal cylinder cost per litre water volume", 25.0, 15.0, 40.0, "$/L", "low", ENG,
       "retail SCUBA cylinders")
    _a(s, "cost_tank_type3", "Type 3 cylinder cost per litre", 95.0, 60.0, 150.0, "$/L", "low", ENG,
       "6.8 L 300 bar carbon cylinders retail ~$400-900")
    _a(s, "cost_tank_type4", "Type 4 tank cost per litre", 110.0, 60.0, 200.0, "$/L", "low", ENG, "estimate")
    _a(s, "cost_valves_base", "Regulator, valves, controller, plumbing (black box) per system", 900.0, 400.0, 2000.0,
       "$", "low", ENG, "estimate")
    _a(s, "cost_per_thruster", "Cold-gas nozzle + solenoid/proportional valve (black box) each", 150.0, 60.0, 400.0,
       "$", "low", ENG, "estimate")
    _a(s, "valves_kg_base", "Regulator, manifold, valves, controller mass per system", 1.5, 0.8, 3.0, "kg", "low", ENG,
       "estimate")
    _a(s, "kg_per_thruster", "Nozzle + valve mass each", 0.25, 0.12, 0.5, "kg", "low", ENG, "estimate")
    return s


def rocket_assumptions() -> AssumptionSet:
    """Black-box chemical rocket classes (external behaviour only)."""
    s = AssumptionSet()
    _a(s, "isp_mono", "Monopropellant-class black box, sea-level Isp", 140.0, 120.0, 160.0, "s", "high", LIT,
       "Bell Rocket Belt (1961, peroxide monopropellant): ~1.3 kN for ~21 s on ~20-25 kg -> ~110-140 s delivered; "
       "Sutton & Biblarz tables for monopropellants")
    _a(s, "isp_biprop", "Storable/cryogenic bipropellant-class black box, sea-level Isp (small engine)", 250.0, 220.0,
       280.0, "s", "high", LIT, "Sutton & Biblarz tables; small engines at low chamber pressure deliver the lower end")
    _a(s, "isp_solid", "Solid-motor-class black box, sea-level Isp", 200.0, 180.0, 230.0, "s", "high", LIT,
       "Sutton & Biblarz: composite solids 200-250 s sea level")
    _a(s, "texit_mono", "Monoprop-class exhaust exit temperature", 900.0, 750.0, 1050.0, "K", "low", LIT,
       "decomposition products of high-concentration peroxide ~1000 K adiabatic (published property data)")
    _a(s, "texit_biprop", "Biprop-class exhaust exit temperature", 1800.0, 1400.0, 2300.0, "K", "low", LIT,
       "chamber 2800-3500 K, exit after expansion 1300-2300 K (Sutton & Biblarz)")
    _a(s, "texit_solid", "Solid-class exhaust exit temperature", 1700.0, 1400.0, 2200.0, "K", "low", LIT, "as above")
    _a(s, "min_throttle_mono", "Minimum stable throttle, monoprop class", 0.30, 0.15, 0.50, "-", "low", ENG,
       "valve-throttled catalytic devices; demonstrated by valve-controlled rocket belts")
    _a(s, "min_throttle_biprop", "Minimum stable throttle, biprop class", 0.40, 0.30, 0.60, "-", "low", LIT,
       "deep throttling is rare; many throttleable engines 40-100 % (e.g. landing engines)")
    _a(s, "engine_tw", "Black-box engine thrust/weight (engine only)", 25.0, 15.0, 40.0, "-", "high", ENG,
       "small pressure-fed engines/thrusters")
    _a(s, "tankage_fraction", "Propellant tank + pressurant + feed mass per kg propellant", 0.25, 0.15, 0.40, "-",
       "low", ENG, "small pressure-fed systems carry heavy tanks")
    _a(s, "start_delay_s", "Start transient to full thrust (liquid classes)", 0.3, 0.1, 0.8, "s", "low", ENG, "estimate")
    _a(s, "biprop_restarts", "Allowed restarts, biprop class", 3.0, 1.0, 10.0, "-", "high", ENG, "estimate")
    _a(s, "cost_prop_per_kg", "Propellant cost (black box)", 15.0, 5.0, 50.0, "$/kg", "low", ENG, "estimate")
    _a(s, "cost_engine_per_n", "Engine cost per newton thrust (black box)", 6.0, 2.0, 15.0, "$/N", "low", ENG, "estimate")
    _a(s, "acoustic_eff", "Acoustic efficiency of a rocket/high-speed jet (sound power / jet mechanical power)", 0.005,
       0.002, 0.01, "-", "low", LIT, "NASA SP-8072 (Eldred 1971), Acoustic loads generated by the propulsion system")
    _a(s, "acoustic_eff_coldgas", "Acoustic efficiency of a cold supersonic gas jet", 0.003, 0.001, 0.008, "-", "low",
       ENG, "same correlation; cold jets radiate somewhat less")
    return s


def hazard_thresholds() -> dict[str, tuple[float, str]]:
    return {
        "jet_velocity_m_s": (15.0, "gale-force wind (Beaufort 8, 17-20 m/s) knocks people off balance; debris pick-up"),
        "jet_hot_excess_k": (40.0, "~60 C gas: skin burn within seconds (ISO 13732-1 contact thresholds as guide)"),
        "jet_cold_excess_k": (-50.0, "< -30 C gas jet: frost injury on exposed skin within seconds"),
        "overpressure_low_pa": (6.9e3, "1 psi: window breakage, people knocked down (Glasstone & Dolan / Kinney-Graham)"),
        "overpressure_ear_pa": (34.5e3, "~5 psi: eardrum rupture threshold"),
        "spl_impulse_db": (140.0, "NIOSH/OSHA peak limit for impulsive noise"),
        "spl_pain_db": (120.0, "threshold of pain"),
    }


def skateboard_assumptions() -> AssumptionSet:
    s = AssumptionSet()
    _a(s, "crr", "Rolling-resistance coefficient, urethane wheels", 0.015, 0.008, 0.030, "-", "low", ENG,
       "reported 0.005-0.02 on smooth concrete, up to ~0.03 on rough asphalt for 70-90 mm urethane wheels")
    _a(s, "cda_upright", "Rider + board CdA, upright stance", 0.60, 0.45, 0.75, "m^2", "low", LIT,
       "upright cyclist CdA 0.5-0.7 m^2 (Wilson, Bicycling Science, 3rd ed.)")
    _a(s, "cda_crouch", "Rider + board CdA, crouched", 0.35, 0.28, 0.45, "m^2", "low", LIT, "crouched cyclist ~0.3-0.4")
    _a(s, "mu", "Tyre-road friction, urethane on dry asphalt/concrete", 0.70, 0.50, 0.90, "-", "high", ENG,
       "urethane wheels slide at 0.5-0.9 g on dry surfaces (powerslide decelerations)")
    _a(s, "drive_eff", "Battery -> wheel efficiency, hub motor + controller", 0.85, 0.75, 0.90, "-", "high", CAT,
       "BLDC hub motors with FOC")
    _a(s, "regen_eff", "Wheel -> battery efficiency when regenerating", 0.65, 0.50, 0.80, "-", "high", ENG, "estimate")
    _a(s, "motor_peak_w", "Peak electrical power per hub motor", 1500.0, 1000.0, 2500.0, "W", "high", CAT,
       "consumer dual-hub electric skateboards: 2 x 1-2.5 kW peak")
    _a(s, "wheel_force_max_n", "Max drive force at the wheels (motor torque limit), both motors", 240.0, 160.0, 320.0,
       "N", "high", CAT, "~0.25 g for a 100 kg rider+board, typical of consumer boards")
    _a(s, "top_speed_m_s", "Electric top speed (back-EMF / firmware limit)", 11.0, 9.0, 13.0, "m/s", "high", CAT,
       "consumer boards 35-50 km/h")
    _a(s, "batt_wh", "Electric board pack energy", 400.0, 250.0, 700.0, "Wh", "high", CAT, "10-12S Li-ion packs")
    _a(s, "batt_wh_per_kg", "Pack specific energy", 150.0, 120.0, 180.0, "Wh/kg", "high", LIT, "18650/21700 packs")
    _a(s, "rider_heel_lever_m", "Effective centre-of-pressure + hip-strategy lever resisting a backward fall", 0.08,
       0.05, 0.12, "m", "high", LIT, "foot heel margin ~0.05 m behind ankle (Winter, Biomechanics of Human Movement); "
                                    "hip strategy extends it")
    _a(s, "rider_toe_lever_m", "Effective lever resisting a forward fall", 0.15, 0.10, 0.18, "m", "high", LIT,
       "toe margin ~0.15-0.18 m ahead of ankle")
    _a(s, "rider_lag_s", "Postural response lag (perceive acceleration -> correct lean)", 0.15, 0.10, 0.25, "s", "low",
       LIT, "postural reflex latencies 100-200 ms")
    _a(s, "cost_board", "Deck, trucks, wheels", 150.0, 80.0, 300.0, "$", "low", ENG, "retail")
    _a(s, "cost_edrive", "Hub motors, ESC, BMS, pack (400 Wh)", 700.0, 400.0, 1200.0, "$", "low", ENG, "retail parts")
    return s


def hover_assumptions() -> AssumptionSet:
    s = AssumptionSet()
    _a(s, "tw_margin", "Thrust/weight needed for attitude control authority + gust margin", 1.30, 1.20, 1.50, "-",
       "low", ENG, "same 1.3 x rule as levitate.human_scale")
    _a(s, "board_struct_kg", "Deck, landing feet, rider bindings, guards", 12.0, 8.0, 18.0, "kg", "low", ENG,
       "estimate for a 1.0 x 0.5 m composite deck")
    _a(s, "avionics_kg", "Flight controller, IMU, power, wiring", 3.0, 2.0, 5.0, "kg", "low", ENG, "estimate")
    _a(s, "avionics_cost", "Avionics cost", 1500.0, 800.0, 3000.0, "$", "low", ENG, "estimate")
    _a(s, "struct_cost", "Structure cost", 1200.0, 600.0, 2500.0, "$", "low", ENG, "estimate")
    return s


def all_assumption_sets() -> dict[str, AssumptionSet]:
    return {"coldgas": coldgas_assumptions(), "rocket": rocket_assumptions(), "skateboard": skateboard_assumptions(),
            "hover": hover_assumptions()}
