"""Component catalog and global assumption library.

IMPORTANT: catalog masses/ratings are *nominal* retailer-class values for common
micro-FPV parts. They are flagged CATALOG_NOMINAL and must be replaced by values
measured on a scale / thrust stand before any result is promoted beyond
"analytical estimate". See docs/VALIDATION_PLAN.md.
"""
from __future__ import annotations

from pydantic import BaseModel

from .provenance import Assumption, AssumptionSet, SourceStatus

CAT = SourceStatus.CATALOG_NOMINAL
ENG = SourceStatus.ENGINEERING_JUDGMENT
LIT = SourceStatus.PEER_REVIEWED
LAW = SourceStatus.PHYSICAL_LAW


class Motor(BaseModel):
    key: str
    name: str
    kind: str                 # "brushless" | "coreless"
    mass_g: float
    max_elec_power_w: float   # sustained electrical input at full throttle on 1S
    efficiency: float         # nominal motor (+driver) electrical->shaft efficiency near hover
    max_prop_diameter_mm: float
    cost_usd: float
    status: SourceStatus = CAT
    note: str = ""


class Battery(BaseModel):
    key: str
    name: str
    cells: int
    capacity_mah: float
    mass_g: float
    max_continuous_c: float   # *derated* continuous C (marketing C ratings are not trusted)
    internal_resistance_ohm: float
    cost_usd: float
    status: SourceStatus = CAT


class Material(BaseModel):
    key: str
    name: str
    density_kg_m3: float
    youngs_modulus_gpa: float
    min_wall_mm: float        # practical minimum wall for this manufacturing route
    cost_usd_per_cm3: float
    status: SourceStatus = LIT


class Electronics(BaseModel):
    key: str
    name: str
    mass_g: float
    power_w: float
    supports: str             # "brushless" | "coreless"
    cost_usd: float
    status: SourceStatus = CAT


MOTORS: dict[str, Motor] = {m.key: m for m in [
    Motor(key="coreless_0615", name="Coreless 6x15 mm brushed", kind="coreless", mass_g=2.0,
          max_elec_power_w=5.5, efficiency=0.50, max_prop_diameter_mm=35, cost_usd=3,
          note="typical micro-whoop brushed motor"),
    Motor(key="coreless_0716", name="Coreless 7x16 mm brushed", kind="coreless", mass_g=2.7,
          max_elec_power_w=7.0, efficiency=0.52, max_prop_diameter_mm=46, cost_usd=4,
          note="Crazyflie-class motor"),
    Motor(key="coreless_0820", name="Coreless 8x20 mm brushed", kind="coreless", mass_g=4.3,
          max_elec_power_w=10.0, efficiency=0.55, max_prop_diameter_mm=55, cost_usd=5),
    Motor(key="bl_0702", name="Brushless 0702 (~25k KV)", kind="brushless", mass_g=1.9,
          max_elec_power_w=12.0, efficiency=0.65, max_prop_diameter_mm=35, cost_usd=12),
    Motor(key="bl_0802", name="Brushless 0802 (~19k KV)", kind="brushless", mass_g=2.6,
          max_elec_power_w=16.0, efficiency=0.68, max_prop_diameter_mm=40, cost_usd=13),
    Motor(key="bl_1103", name="Brushless 1103 (~11k KV)", kind="brushless", mass_g=3.8,
          max_elec_power_w=25.0, efficiency=0.72, max_prop_diameter_mm=65, cost_usd=14),
]}


def _lipo(cap: int, mass: float, c: float, ir: float, cost: float) -> Battery:
    return Battery(key=f"lipo_1s_{cap}", name=f"1S LiPo {cap} mAh", cells=1, capacity_mah=cap,
                   mass_g=mass, max_continuous_c=c, internal_resistance_ohm=ir, cost_usd=cost)


BATTERIES: dict[str, Battery] = {b.key: b for b in [
    _lipo(150, 4.3, 20, 0.30, 4),
    _lipo(200, 5.6, 20, 0.22, 4),
    _lipo(260, 7.0, 20, 0.17, 5),
    _lipo(300, 8.2, 20, 0.15, 5),
    _lipo(380, 10.0, 18, 0.12, 6),
    _lipo(450, 11.8, 18, 0.10, 6),
    _lipo(550, 14.0, 15, 0.09, 7),
    _lipo(660, 16.5, 15, 0.08, 8),
]}

MATERIALS: dict[str, Material] = {m.key: m for m in [
    Material(key="cfrp_plate", name="Carbon-fibre plate (CNC)", density_kg_m3=1550, youngs_modulus_gpa=70,
             min_wall_mm=0.8, cost_usd_per_cm3=0.60),
    Material(key="pla_fdm", name="PLA (FDM print)", density_kg_m3=1240, youngs_modulus_gpa=3.5,
             min_wall_mm=0.6, cost_usd_per_cm3=0.03),
    Material(key="pa12_sls", name="Nylon PA12 (SLS print)", density_kg_m3=1010, youngs_modulus_gpa=1.7,
             min_wall_mm=0.7, cost_usd_per_cm3=0.25),
    Material(key="resin_sla", name="Tough resin (SLA print)", density_kg_m3=1150, youngs_modulus_gpa=2.5,
             min_wall_mm=0.5, cost_usd_per_cm3=0.15),
    Material(key="eps_foam_cf", name="EPP foam core + CF skin", density_kg_m3=180, youngs_modulus_gpa=0.9,
             min_wall_mm=2.0, cost_usd_per_cm3=0.05, status=ENG),
]}

ELECTRONICS: dict[str, Electronics] = {e.key: e for e in [
    Electronics(key="aio_brushless_1s", name="1S AIO F4 FC + 4x5A ESC + RX", mass_g=3.0, power_w=0.45,
                supports="brushless", cost_usd=40),
    Electronics(key="aio_brushed_1s", name="1S brushed FC (MOSFET drivers) + RX", mass_g=2.0, power_w=0.35,
                supports="coreless", cost_usd=20),
]}


def global_assumptions() -> AssumptionSet:
    """Model parameters that are uncertain. Every one of these must eventually be measured."""
    s = AssumptionSet()
    add = s.add
    add(Assumption(key="figure_of_merit", description="Rotor hover figure of merit at Re~2e4-5e4",
                   nominal=0.42, low=0.32, high=0.52, unit="-", favourable="high", status=LIT,
                   source="Micro-rotor FM 0.3-0.55 (Bohorquez & Pines 2003; Ramasamy et al.); measure on stand"))
    add(Assumption(key="duct_effectiveness", description="Fraction of ideal ducted-rotor power saving realised "
                   "(tip-gap, inlet-lip and wall losses at mm scale)",
                   nominal=0.5, low=0.0, high=0.8, unit="-", favourable="high", status=ENG,
                   source="Ideal duct sigma=1 saves 29% power; small ducts with 0.3-0.5 mm tip gaps lose much of it"))
    add(Assumption(key="motor_eff_scale", description="Multiplier on catalog motor efficiency at hover point",
                   nominal=1.0, low=0.85, high=1.08, unit="-", favourable="high", status=ENG,
                   source="Catalog efficiencies are peak values; hover point is often off-peak"))
    add(Assumption(key="battery_specific_energy_derate", description="Fraction of nameplate Wh actually delivered "
                   "at hover C-rate before LVC (3.3 V/cell)",
                   nominal=0.80, low=0.70, high=0.88, unit="-", favourable="high", status=ENG,
                   source="Small LiPo cells typically deliver 75-90% of nameplate at 5-10C"))
    add(Assumption(key="mass_growth", description="Mass growth allowance for wiring, glue, fasteners, connectors",
                   nominal=1.06, low=1.03, high=1.12, unit="-", favourable="low", status=ENG,
                   source="Standard aerospace mass growth allowance for concept stage"))
    add(Assumption(key="rotor_torque_ratio", description="Rotor reaction torque / thrust (kappa)",
                   nominal=0.006, low=0.004, high=0.009, unit="m", favourable="high", status=ENG,
                   source="Crazyflie-class identification values ~0.005-0.008 m; measure on stand"))
    add(Assumption(key="motor_time_constant", description="First-order thrust response time constant",
                   nominal=0.03, low=0.015, high=0.05, unit="s", favourable="low", status=ENG,
                   source="Micro brushless/coreless rotors 15-50 ms"))
    add(Assumption(key="prop_mass_coeff", description="Propeller/fan mass at 31 mm diameter (scales ~D^2.5)",
                   nominal=0.30, low=0.20, high=0.45, unit="g", favourable="low", status=CAT,
                   source="31 mm whoop props ~0.2-0.4 g each"))
    return s
