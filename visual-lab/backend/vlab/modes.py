"""IDEAL PHYSICS (unlimited energy) vs REALITY CONSTRAINTS configuration and its resolution into a plant.

IDEAL PHYSICS - UNLIMITED ENERGY
  * energy storage has zero mass and never depletes; power never limits force;
  * actuator force limits are relaxable (default: none), actuators may be instantaneous;
  * actuators are HYPOTHETICAL force inputs: no momentum-exchange mechanism is claimed. The simulation
    answers "what force/torque history is *required* for this manoeuvre", not "this propulsion exists";
  * gravity, Newton's laws, momentum, inertia, CG, drag and ground contact are always preserved.
REALITY CONSTRAINTS
  * every constraint below is individually toggleable; with a constraint enabled the plant enforces it
    physically (force saturation, power-limited thrust, battery depletion, thermal derating, lag/delay...).
    A vehicle that cannot produce its weight in thrust therefore cannot hover in the simulation.
"""
from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from .constants import G0, P_SL, T_SL
from .vehicle import MassComponent, PropulsionKind, Vec3, VehicleConfig

V_OC_PER_CELL = 3.75     # Agent A battery.py: mean open-circuit voltage over 4.2 -> 3.3 V discharge
V_MIN_PER_CELL = 3.3     # Agent A battery.py: low-voltage cutoff under load


class Toggle(BaseModel):
    enabled: bool = False


class ThrustLimit(Toggle):
    max_force_per_actuator_n: float = 0.12


class TorqueLimit(Toggle):
    max_torque_nm: Vec3 = (2.0e-3, 4.0e-3, 1.0e-3)


class PropulsionEfficiency(Toggle):
    figure_of_merit: float = 0.42          # Agent A nominal (range 0.32-0.52)
    motor_efficiency: float = 0.65         # Agent A catalog bl_0702
    duct_factor: float = 0.8536            # Agent A: duct effectiveness 0.5


class PowerLimit(Toggle):
    max_electrical_power_w: float = 48.0   # total for all actuators (4 x 12 W bl_0702 rating, Agent A catalog)


class BatteryConstraint(Toggle):
    cells: int = 1
    capacity_mah: float = 300.0            # Agent A catalog lipo_1s_300
    mass_kg: float = 0.0082
    internal_resistance_ohm: float = 0.15
    max_continuous_c: float = 20.0
    usable_fraction: float = 0.80
    include_mass: bool = True
    max_power_override_w: float | None = None   # e.g. imported from Agent A's power_model


class ConversionLosses(Toggle):
    esc_efficiency: float = 0.92           # ESC / driver; HV converter for ionic wind


class TotalMass(Toggle):
    total_mass_kg: float = 0.020           # total incl. battery when enabled


class Dimensions(Toggle):
    length_m: float = 0.100
    width_m: float = 0.032
    height_m: float = 0.009


class ThermalLimit(Toggle):
    thermal_resistance_k_per_w: float = 40.0
    heat_capacity_j_per_k: float = 1.0
    max_temp_c: float = 100.0
    ambient_c: float = 25.0


class Delays(Toggle):
    actuator_time_constant_s: float = 0.03   # Agent A nominal motor time constant
    transport_delay_s: float = 0.004


class AddedMass(Toggle):
    pass


class Environment(BaseModel):
    g: float = G0
    temperature_k: float = T_SL
    pressure_pa: float = P_SL
    air_model: Literal["isa_ideal_gas", "cantera_rom"] = "isa_ideal_gas"
    wind_m_s: Vec3 = (0.0, 0.0, 0.0)
    buoyancy: bool = False                 # rho V g on the deck volume (0.18 % of weight at 20 g)


class Impulse(BaseModel):
    t_s: float
    duration_s: float = 0.1
    force_n: Vec3 = (0.0, 0.02, 0.0)       # world frame, applied at CG


class Disturbances(BaseModel):
    gust_std_n: float = 0.0
    gust_tau_s: float = 0.5
    impulses: list[Impulse] = Field(default_factory=list)
    sensor_noise_pos_m: float = 0.0
    sensor_noise_att_rad: float = 0.0
    actuator_failure_index: int | None = None
    actuator_failure_t_s: float = 1e9
    controller_mass_error: float = 0.0     # controller believes m (1 + err)


class ModeConfig(BaseModel):
    mode: Literal["ideal", "reality"] = "ideal"
    propulsion: PropulsionKind = "ducted_rotor"
    ideal_force_limit_n: float | None = None   # None = unlimited (relaxed)
    ideal_bidirectional: bool = False
    thrust_limit: ThrustLimit = Field(default_factory=ThrustLimit)
    torque_limit: TorqueLimit = Field(default_factory=TorqueLimit)
    efficiency: PropulsionEfficiency = Field(default_factory=PropulsionEfficiency)
    power_limit: PowerLimit = Field(default_factory=PowerLimit)
    battery: BatteryConstraint = Field(default_factory=BatteryConstraint)
    conversion_losses: ConversionLosses = Field(default_factory=ConversionLosses)
    total_mass: TotalMass = Field(default_factory=TotalMass)
    dimensions: Dimensions = Field(default_factory=Dimensions)
    drag: Toggle = Field(default_factory=lambda: Toggle(enabled=True))
    ground_effect: Toggle = Field(default_factory=Toggle)
    thermal: ThermalLimit = Field(default_factory=ThermalLimit)
    delays: Delays = Field(default_factory=Delays)
    added_mass: AddedMass = Field(default_factory=AddedMass)
    environment: Environment = Field(default_factory=Environment)
    disturbances: Disturbances = Field(default_factory=Disturbances)


def reality_preset(name: str) -> ModeConfig:
    """Named configurations used by the UI and tests."""
    if name == "ideal":
        return ModeConfig(mode="ideal")
    on = dict(enabled=True)
    base = ModeConfig(mode="reality", propulsion="ducted_rotor",
                      efficiency=PropulsionEfficiency(**on), power_limit=PowerLimit(**on),
                      battery=BatteryConstraint(**on), conversion_losses=ConversionLosses(enabled=True, esc_efficiency=0.95),
                      ground_effect=Toggle(enabled=True), thermal=ThermalLimit(**on), delays=Delays(**on))
    if name == "reality_baseline":
        return base
    if name == "underpowered":         # motors/ESC rated for only 2.5 W total: cannot lift 28 g
        base.power_limit.max_electrical_power_w = 2.5
        return base
    if name == "too_heavy":            # 120 g total on the same propulsion -> battery cannot deliver hover power
        base.total_mass = TotalMass(enabled=True, total_mass_kg=0.120)
        return base
    if name == "thrust_capped":        # actuator max force 0.05 N each -> T/W < 1
        base.thrust_limit = ThrustLimit(enabled=True, max_force_per_actuator_n=0.05)
        return base
    raise KeyError(name)


PRESETS = ["ideal", "reality_baseline", "underpowered", "too_heavy", "thrust_capped"]


# --------------------------------------------------------------------------------- power models
class PowerFn(BaseModel):
    """Electrical power drawn by one actuator producing OGE-equivalent force f [N]:
       rotor : P = c_rotor |f|^1.5,  c_rotor = k_duct / (FM eta_motor eta_esc sqrt(2 rho A))
       ionic : P = |f| / (thrust_per_power eta_conv)
       ideal : no physical power; we report the ideal actuator-disk lower bound c = 1/sqrt(2 rho A)
               as an ESTIMATE only (FM = 1, eta = 1)."""
    kind: Literal["rotor", "ionic", "ideal_estimate"]
    c: float
    avionics_w: float
    model: str

    def actuator_power(self, f: np.ndarray | float):
        f = np.abs(f)
        return self.c * f ** 1.5 if self.kind in ("rotor", "ideal_estimate") else self.c * f

    def thrust_at_power(self, p: float) -> float:
        if p <= 0:
            return 0.0
        return (p / self.c) ** (2 / 3) if self.kind in ("rotor", "ideal_estimate") else p / self.c


def air_density(env: Environment) -> tuple[float, float, str]:
    """(rho, mu, source). cantera_rom uses the Cantera-generated lookup table (solvers/cantera_air.py)."""
    from .constants import ideal_gas_density, sutherland_viscosity
    if env.air_model == "cantera_rom":
        from .solvers.cantera_air import AirPropertyROM
        rom = AirPropertyROM.load()
        if rom is not None:
            rho, mu = rom.lookup(env.temperature_k, env.pressure_pa)
            return rho, mu, f"Cantera ROM ({rom.meta.get('mechanism')}, Cantera {rom.meta.get('cantera_version')})"
    return (ideal_gas_density(env.pressure_pa, env.temperature_k), sutherland_viscosity(env.temperature_k),
            "ideal gas + Sutherland")


def power_fn(mc: ModeConfig, v: VehicleConfig, rho: float) -> PowerFn:
    r = v.actuators[0].radius_m if v.actuators else 0.011
    area = math.pi * r * r
    if mc.mode == "ideal":
        return PowerFn(kind="ideal_estimate", c=1 / math.sqrt(2 * rho * area), avionics_w=0.0,
                       model=f"ESTIMATE: ideal actuator-disk induced power T^1.5/sqrt(2 rho A), A = {area*1e6:.0f} mm^2 "
                             "per actuator (FM = 1, lossless). Hypothetical forces have no defined power.")
    eff = mc.efficiency
    fm, eta, kd = (eff.figure_of_merit, eff.motor_efficiency, eff.duct_factor) if eff.enabled else (1.0, 1.0, 1.0)
    if mc.propulsion == "open_rotor":
        kd = 1.0
    esc = mc.conversion_losses.esc_efficiency if mc.conversion_losses.enabled else 1.0
    av = v.power.avionics_w
    if mc.propulsion == "ionic_wind":
        tpp = v.power.ionic_thrust_per_power_n_per_w
        src = "assumption"
        import json
        from .util import DATA
        p = DATA / "rom" / "harness_ehd_latest.json"
        if p.exists():
            d = json.loads(p.read_text())
            if d.get("valid") and d.get("summary", {}).get("thrust_to_power_n_per_kw"):
                tpp = d["summary"]["thrust_to_power_n_per_kw"] / 1000
                src = (f"Agent A corona solver ({d['params']['voltage_kv']} kV, gap {d['params']['gap_mm']} mm; "
                       "single wire 2-D, excludes collector drag / array shielding)")
        return PowerFn(kind="ionic", c=1 / (tpp * esc), avionics_w=av,
                       model=f"ESTIMATE: EAD P = T/(thrust_per_power {tpp*1000:.2f} N/kW [{src}] x eta_conv {esc:.2f})")
    return PowerFn(kind="rotor", c=kd / (fm * eta * esc * math.sqrt(2 * rho * area)), avionics_w=av,
                   model=f"ESTIMATE: momentum theory P = T^1.5 k_duct/(FM eta_m eta_esc sqrt(2 rho A)); FM={fm}, "
                         f"eta_m={eta}, eta_esc={esc}, k_duct={kd:.3f}, A={area*1e6:.0f} mm^2, rho={rho:.4f}")


def battery_max_power(b: BatteryConstraint) -> float:
    """Agent A battery.py max_deliverable_power: lower of C-rate and voltage-cutoff current limits."""
    if b.max_power_override_w is not None:
        return b.max_power_override_w
    voc = V_OC_PER_CELL * b.cells
    i_c = b.max_continuous_c * b.capacity_mah / 1000
    i_v = (voc - V_MIN_PER_CELL * b.cells) / b.internal_resistance_ohm if b.internal_resistance_ohm > 0 else math.inf
    i = min(i_c, i_v)
    return (voc - i * b.internal_resistance_ohm) * i


def battery_usable_energy_j(b: BatteryConstraint) -> float:
    return b.capacity_mah / 1000 * V_OC_PER_CELL * b.cells * 3600 * b.usable_fraction


def cell_power(load_w: float, b: BatteryConstraint) -> float:
    """Power drawn from the cell chemistry incl. I^2 R loss (Thevenin source)."""
    voc = V_OC_PER_CELL * b.cells
    r = b.internal_resistance_ohm
    if r <= 0:
        return load_w
    disc = voc * voc - 4 * r * load_w
    if disc < 0:
        return voc * voc / (2 * r)
    i = (voc - math.sqrt(disc)) / (2 * r)
    return voc * i


# ------------------------------------------------------------------------------------- resolution
class ResolvedModel(BaseModel):
    """Everything the plant/controller need, after constraints have been applied."""
    mode: str
    evidence: str
    vehicle: VehicleConfig
    rho: float
    mu: float
    air_source: str
    f_min: list[float]
    f_max: list[float]
    tau_s: list[float]
    transport_delay_s: float
    power: PowerFn
    power_cap_w: float                 # total electrical cap (inf in ideal)
    energy_j: float                    # usable energy (inf in ideal)
    battery: BatteryConstraint | None
    ground_effect: bool
    thermal: ThermalLimit | None
    torque_limit: Vec3 | None
    labels: list[str]
    hypothetical: bool


def apply_dimensions(v: VehicleConfig, d: Dimensions) -> VehicleConfig:
    sx, sy, sz = d.length_m / v.length_m, d.width_m / v.width_m, d.height_m / v.height_m
    out = v.model_copy(deep=True)
    out.length_m, out.width_m, out.height_m = d.length_m, d.width_m, d.height_m
    for c in out.components:
        c.pos_m = (c.pos_m[0] * sx, c.pos_m[1] * sy, c.pos_m[2] * sz)
        c.size_m = (c.size_m[0] * sx, c.size_m[1] * sy, c.size_m[2] * sz)
    for a in out.actuators:
        a.pos_m = (a.pos_m[0] * sx, a.pos_m[1] * sy, a.pos_m[2] * sz)
    return out


def resolve(vehicle: VehicleConfig, mc: ModeConfig) -> ResolvedModel:
    from .vehicle import scale_total_mass
    v = vehicle.model_copy(deep=True)
    labels: list[str] = []
    rho, mu, air_src = air_density(mc.environment)
    ideal = mc.mode == "ideal"
    n = len(v.actuators)
    if not ideal and mc.dimensions.enabled:
        v = apply_dimensions(v, mc.dimensions)
    batt = mc.battery if (not ideal and mc.battery.enabled) else None
    if batt is not None and batt.include_mass and batt.mass_kg > 0:
        v.components.append(MassComponent(name=f"battery {batt.cells}S {batt.capacity_mah:.0f} mAh", mass_kg=batt.mass_kg,
                                          pos_m=(0.0, 0.0, -v.height_m / 2 + 0.003), size_m=(0.035, 0.012, 0.006),
                                          group="energy"))
    if not ideal and mc.total_mass.enabled:
        v = scale_total_mass(v, mc.total_mass.total_mass_kg)
    if mc.added_mass.enabled:
        from .solvers.fem_added_mass import AddedMassROM
        rom = AddedMassROM.load()
        if rom is None:
            labels.append("added mass requested but FEM ROM not built (run solver job 'fem_added_mass')")
        else:
            v.added_mass_kg = rom.added_mass_kg(v.length_m, v.width_m, v.height_m, rho)
            labels.append(f"added mass from FEM ROM: {np.round(np.array(v.added_mass_kg) * 1e6, 1).tolist()} mg")
    v.drag.enabled = mc.drag.enabled
    pf = power_fn(mc, v, rho)

    if ideal:
        lim = mc.ideal_force_limit_n if mc.ideal_force_limit_n is not None else math.inf
        f_max = [lim] * n
        f_min = [-lim if mc.ideal_bidirectional else 0.0] * n
        for a in v.actuators:
            a.mechanism = "hypothetical"
        tau = [0.0] * n
        labels.append("HYPOTHETICAL force inputs - no propulsion mechanism claimed")
        labels.append("unlimited energy, zero-mass storage" + ("; unlimited force" if lim == math.inf else f"; |F| <= {lim} N"))
        return ResolvedModel(mode="ideal", evidence="hypothetical_ideal", vehicle=v, rho=rho, mu=mu, air_source=air_src,
                             f_min=f_min, f_max=f_max, tau_s=tau, transport_delay_s=0.0, power=pf,
                             power_cap_w=math.inf, energy_j=math.inf, battery=None, ground_effect=False,
                             thermal=None, torque_limit=None, labels=labels, hypothetical=True)

    f_max = [a.max_force_n for a in v.actuators]          # per-actuator rating (inf for the default board)
    if mc.thrust_limit.enabled:
        f_max = [min(f, mc.thrust_limit.max_force_per_actuator_n) for f in f_max]
    cap = math.inf
    if mc.power_limit.enabled:
        cap = min(cap, mc.power_limit.max_electrical_power_w)
        labels.append(f"actuator/ESC power cap {mc.power_limit.max_electrical_power_w:.2f} W total")
    energy = math.inf
    if batt is not None:
        pb = battery_max_power(batt)
        cap = min(cap, pb)
        energy = battery_usable_energy_j(batt)
        labels.append(f"battery max deliverable {pb:.2f} W, usable {energy:.0f} J")
    if cap < math.inf:
        # a single actuator can at most take the whole budget (after avionics)
        t_cap = pf.thrust_at_power(max(cap - pf.avionics_w, 0.0))
        f_max = [min(f, t_cap) for f in f_max]
    tau = [mc.delays.actuator_time_constant_s if mc.delays.enabled else 0.0] * n
    for a, t in zip(v.actuators, tau):
        a.time_constant_s = t
        a.mechanism = {"ducted_rotor": "ducted rotor (air momentum)", "open_rotor": "open rotor (air momentum)",
                       "ionic_wind": "EAD ionic wind (air momentum)", "hypothetical_ideal": "hypothetical"}[mc.propulsion]
    ge = mc.ground_effect.enabled and mc.propulsion in ("ducted_rotor", "open_rotor")
    return ResolvedModel(mode="reality", evidence="simplified_numerical_simulation", vehicle=v, rho=rho, mu=mu,
                         air_source=air_src, f_min=[0.0] * n, f_max=f_max, tau_s=tau,
                         transport_delay_s=mc.delays.transport_delay_s if mc.delays.enabled else 0.0,
                         power=pf, power_cap_w=cap, energy_j=energy, battery=batt, ground_effect=ge,
                         thermal=mc.thermal if mc.thermal.enabled else None,
                         torque_limit=mc.torque_limit.max_torque_nm if mc.torque_limit.enabled else None,
                         labels=labels, hypothetical=mc.propulsion == "hypothetical_ideal")
