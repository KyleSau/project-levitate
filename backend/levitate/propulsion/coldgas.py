"""Cold-gas (compressed air / nitrogen) tank + thruster model.  Computational model only - black-box hardware.

Tank (fixed volume V, lumped gas state, uniform):
    dm/dt = -mdot
    dU/dt = -mdot * h(T, rho) + Q,      Q = h_w A_w (T_w - T)           (energy balance of an open control volume)
    m_w c_w dT_w/dt = -Q + h_ext A_w (T_amb - T_w)
  thermal modes: "adiabatic" (Q = 0: remaining gas follows an isentrope, rate independent), "isothermal" (T = T0),
  "heat_transfer" (lumped wall, above), "polytropic" (ideal gas only, p ~ rho^n; analytic comparison case).
  Properties: real-gas tables (gas.py) by default; ideal gas optional (used for the closed-form validation cases).

Nozzle (quasi-steady, isentropic ideal-gas expansion from the stagnation state p0, T0):
    choked (p0/pa > ((g+1)/2)^(g/(g-1)) ~ 1.89):
        mdot = Cd A* p0 sqrt(g / (Z R T0)) (2/(g+1))^((g+1)/(2(g-1)))      Z = real-gas compressibility at (p0, T0)
        pe from the area ratio, ue = sqrt(2 g/(g-1) R T0 (1 - (pe/p0)^((g-1)/g)))
        F = eta_cf (mdot ue + (pe - pa) Ae)                                 Isp = F / (mdot g0)
    unchoked: isentropic orifice flow to pa (no pressure thrust).
  Real-gas effects are carried in the mass flow (Z) and in the tank; the expansion itself is ideal-gas, which is
  accurate when the nozzle is fed from a regulator (p0 <= ~50 bar, Z within 1 % of 1). Unregulated 300 bar feed
  carries an additional few-% uncertainty on ue.
Regulator: p0 = min(throttle * p_reg, p_tank - dropout) (isenthalpic: T0 = T_tank; Joule-Thomson cooling neglected).
"""
from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

from ..constants import G0
from .assumptions import coldgas_assumptions
from .gas import GASES, P_ATM, Gas, ideal_closed_exergy, real_gas

TankClass = Literal["metal", "type3", "type4"]
Thermal = Literal["adiabatic", "isothermal", "heat_transfer", "polytropic"]
T_AMB = 293.15


class TankConfig(BaseModel):
    volume_l: float = Field(6.8, gt=0.05, le=2000, description="water volume per tank")
    n_tanks: int = Field(1, ge=1, le=20)
    pressure_bar: float = Field(300.0, gt=1.5, le=900, description="fill (= service) pressure")
    temperature_k: float = Field(T_AMB, ge=200, le=350)
    gas: Literal["air", "n2"] = "air"
    tank_class: TankClass = "type3"
    real_gas: bool = True
    rom_table: bool = False      # use the reduced browser table (for Python <-> JS parity checks)
    thermal: Thermal = "heat_transfer"
    polytropic_n: float = Field(1.25, ge=1.0, le=1.4)

    @property
    def volume_m3(self) -> float:
        return self.volume_l * self.n_tanks / 1000


class ThrusterConfig(BaseModel):
    n_thrusters: int = Field(1, ge=1, le=16)
    throat_diameter_mm: float = Field(6.0, gt=0.2, le=60, description="per thruster")
    expansion_ratio: float = Field(2.0, ge=1.0, le=50, description="exit/throat area")
    regulated: bool = True
    reg_pressure_bar: float = Field(30.0, ge=2.0, le=300)
    ambient_pa: float = Field(P_ATM, ge=0.0, le=2e5)

    @property
    def throat_area(self) -> float:
        return math.pi * (self.throat_diameter_mm / 2000) ** 2


# --------------------------------------------------------------------------------------------- nozzle relations
def gamma_flow(g: float) -> float:
    return math.sqrt(g) * (2 / (g + 1)) ** ((g + 1) / (2 * (g - 1)))


def critical_ratio(g: float) -> float:
    """p0/pa above which the throat chokes."""
    return ((g + 1) / 2) ** (g / (g - 1))


def area_ratio_from_mach(M: float, g: float) -> float:
    return (1 / M) * ((2 / (g + 1)) * (1 + (g - 1) / 2 * M * M)) ** ((g + 1) / (2 * (g - 1)))


def exit_mach(eps: float, g: float) -> float:
    if eps <= 1.0 + 1e-9:
        return 1.0
    return brentq(lambda M: area_ratio_from_mach(M, g) - eps, 1.0 + 1e-9, 50.0)


def exit_pressure_ratio(eps: float, g: float) -> float:
    M = exit_mach(eps, g)
    return (1 + (g - 1) / 2 * M * M) ** (-g / (g - 1))


class NozzleState(BaseModel):
    mdot: float
    thrust: float
    ue: float
    pe: float
    Te: float
    choked: bool
    separated: bool

    @property
    def isp(self) -> float:
        return self.thrust / (self.mdot * G0) if self.mdot > 0 else 0.0


def nozzle(p0: float, T0: float, gas: Gas, At: float, eps: float, pa: float, cd: float, eta_cf: float,
           Z: float = 1.0, pe_ratio: float | None = None) -> NozzleState:
    g, R = gas.gamma, gas.R
    if p0 <= pa * 1.0001 or At <= 0:
        return NozzleState(mdot=0.0, thrust=0.0, ue=0.0, pe=pa, Te=T0, choked=False, separated=False)
    k = (g - 1) / g
    if p0 / max(pa, 1e-9) >= critical_ratio(g):
        mdot = cd * At * p0 * gamma_flow(g) / math.sqrt(Z * R * T0)
        r = exit_pressure_ratio(eps, g) if pe_ratio is None else pe_ratio
        pe = r * p0
        ue = math.sqrt(2 * g / (g - 1) * R * T0 * (1 - r ** k))
        F = eta_cf * (mdot * ue + (pe - pa) * eps * At)
        return NozzleState(mdot=mdot, thrust=max(F, 0.0), ue=ue, pe=pe, Te=T0 * r ** k, choked=True,
                           separated=pe < 0.4 * pa)
    r = pa / p0
    mdot = cd * At * p0 * math.sqrt(2 * g / ((g - 1) * Z * R * T0) * (r ** (2 / g) - r ** ((g + 1) / g)))
    ue = math.sqrt(2 * g / (g - 1) * R * T0 * (1 - r ** k))
    return NozzleState(mdot=mdot, thrust=eta_cf * mdot * ue, ue=ue, pe=pa, Te=T0 * r ** k, choked=False,
                       separated=False)


# --------------------------------------------------------------------------------------------- tank properties
def tank_geometry(volume_m3_each: float, aspect: float = 3.5) -> tuple[float, float, float]:
    """Cylinder with hemispherical-ish ends approximated as a cylinder of L/D = aspect: (D, L, wetted area)."""
    D = (4 * volume_m3_each / (math.pi * aspect)) ** (1 / 3)
    L = aspect * D
    return D, L, math.pi * D * L + math.pi * D * D / 2


def pvw(tank_class: TankClass, vals: dict[str, float]) -> float:
    return vals[f"pvw_{tank_class}"]


def tank_mass(cfg: TankConfig, vals: dict[str, float]) -> float:
    """Empty tank mass from the pressure-vessel performance factor PV/m at service pressure."""
    return cfg.pressure_bar * 1e5 * cfg.volume_m3 / pvw(cfg.tank_class, vals)


def gas_mass(cfg: TankConfig, p: float | None = None, T: float | None = None) -> float:
    p = cfg.pressure_bar * 1e5 if p is None else p
    T = cfg.temperature_k if T is None else T
    rho = real_gas(cfg.gas, cfg.rom_table).rho_from_pT(p, T) if cfg.real_gas else p / (GASES[cfg.gas].R * T)
    return rho * cfg.volume_m3


def tank_cost(cfg: TankConfig, vals: dict[str, float]) -> float:
    return vals[f"cost_tank_{cfg.tank_class}"] * cfg.volume_l * cfg.n_tanks * max(1.0, cfg.pressure_bar / 300) ** 0.5


class EnergyReport(BaseModel):
    gas_mass_kg: float
    gas_mass_ideal_kg: float
    real_gas_mass_error_pct: float
    Z_fill: float
    stored_exergy_kj: float                 # max useful work obtainable from the stored gas
    burst_energy_kj: float                  # isentropic expansion energy released by a sudden vessel failure
    tnt_equiv_kg: float
    blast_radius_1psi_m: float
    blast_radius_5psi_m: float
    refill_min_work_kj: float               # thermodynamic minimum (isothermal, reversible)
    refill_adiabatic_1stage_kj: float       # single-stage adiabatic compression (reference upper case)
    refill_electric_kwh: float              # at the assumed compressor isothermal efficiency
    refill_cost_usd: float
    notes: list[str]


def kinney_graham_overpressure(Z: float) -> float:
    """Peak side-on overpressure ratio ps/pa vs scaled distance Z = R / W_TNT^(1/3) [m/kg^(1/3)] (Kinney & Graham 1985)."""
    return 808 * (1 + (Z / 4.5) ** 2) / math.sqrt((1 + (Z / 0.048) ** 2) * (1 + (Z / 0.32) ** 2) * (1 + (Z / 1.35) ** 2))


def blast_radius(tnt_kg: float, overpressure_pa: float, pa: float = P_ATM) -> float:
    if tnt_kg <= 0:
        return 0.0
    Zs = brentq(lambda z: kinney_graham_overpressure(z) * pa - overpressure_pa, 1e-3, 500.0)
    return Zs * tnt_kg ** (1 / 3)


def energy_report(cfg: TankConfig, residual_bar: float = 1.0, vals: dict[str, float] | None = None) -> EnergyReport:
    vals = vals or coldgas_assumptions().values()
    gas = GASES[cfg.gas]
    p, T = cfg.pressure_bar * 1e5, cfg.temperature_k
    m = gas_mass(cfg)
    m_ideal = p * cfg.volume_m3 / (gas.R * T)
    tab = real_gas(cfg.gas, cfg.rom_table)
    Z = tab.Z(p, T) if cfg.real_gas else 1.0
    psi = tab.closed_exergy(p, T) if cfg.real_gas else ideal_closed_exergy(gas, p, T)
    k = (gas.gamma - 1) / gas.gamma
    e_burst = m * gas.cv * T * (1 - (P_ATM / p) ** k)          # isentropic expansion work of the released gas
    tnt = 2 * e_burst / 4.184e6                                # x2: surface burst (ground reflection), conservative
    # refill along an isothermal fill from residual_bar to the fill pressure, compressor work ~ flow exergy / eta
    p_res = max(residual_bar * 1e5, P_ATM)
    ps = np.geomspace(p_res, p, 60)
    ms = np.array([gas_mass(cfg, pp, T_AMB) for pp in ps])
    ef = np.array([tab.flow_exergy(pp, T_AMB) if cfg.real_gas else gas.R * T_AMB * math.log(pp / P_ATM) for pp in ps])
    w_flow = float(np.trapezoid(ef, ms))
    m_fill = ms[-1] - ms[0]
    w_min = (ms[-1] * (tab.closed_exergy(p, T_AMB) if cfg.real_gas else ideal_closed_exergy(gas, p, T_AMB))
                          - ms[0] * (tab.closed_exergy(p_res, T_AMB) if cfg.real_gas else ideal_closed_exergy(gas, p_res, T_AMB)))
    w_ad1 = m_fill * gas.cp * T_AMB * ((p / P_ATM) ** k - 1)
    e_el = w_flow / vals["compressor_iso_eff"] / 3.6e6
    notes = []
    if cfg.real_gas and abs(Z - 1) > 0.02:
        notes.append(f"real-gas Z = {Z:.3f} at fill: ideal-gas model would mis-state stored mass by {100 * (m_ideal / m - 1):+.1f} %")
    notes.append("burst energy uses the ideal-gas isentropic expansion of the real stored mass, doubled for a surface "
                 "burst; fragments (the dominant hazard of a vessel failure) are not modelled")
    return EnergyReport(gas_mass_kg=m, gas_mass_ideal_kg=m_ideal, real_gas_mass_error_pct=100 * (m_ideal / m - 1),
                        Z_fill=Z, stored_exergy_kj=m * psi / 1e3, burst_energy_kj=e_burst / 1e3, tnt_equiv_kg=tnt,
                        blast_radius_1psi_m=blast_radius(tnt, 6.9e3), blast_radius_5psi_m=blast_radius(tnt, 34.5e3),
                        refill_min_work_kj=w_min / 1e3, refill_adiabatic_1stage_kj=w_ad1 / 1e3,
                        refill_electric_kwh=e_el, refill_cost_usd=e_el * vals["elec_price"], notes=notes)


# --------------------------------------------------------------------------------------------- tank + thruster system
class ColdGasSystem:
    """Tank + regulator + N identical thrusters. Used by the blowdown, skateboard and hover models.

    State: m (gas mass), U (gas internal energy, real-gas reference), Tw (wall temperature).
    `step(dt, throttle)` advances with semi-implicit Euler (this is what the browser model does);
    `blowdown_ivp()` integrates the same equations with SciPy for reference.
    """

    def __init__(self, tank: TankConfig, thr: ThrusterConfig, vals: dict[str, float] | None = None):
        self.tank, self.thr = tank, thr
        self.vals = vals or coldgas_assumptions().values()
        self.gas = GASES[tank.gas]
        self.tab = real_gas(tank.gas, tank.rom_table) if tank.real_gas else None
        self.V = tank.volume_m3
        _, _, a_each = tank_geometry(self.V / tank.n_tanks)
        self.A_wall = a_each * tank.n_tanks
        self.m_wall = tank_mass(tank, self.vals)
        self.dry_mass = self.m_wall + self.vals["valves_kg_base"] + thr.n_thrusters * self.vals["kg_per_thruster"]
        self.pe_ratio = exit_pressure_ratio(thr.expansion_ratio, self.gas.gamma)
        self.reset()

    # ---- thermodynamic state
    def reset(self):
        self.m0 = gas_mass(self.tank)
        self.rho0 = self.m0 / self.V
        self.T0 = self.tank.temperature_k
        self.m = self.m0
        self.U = self.m * self.u(self.T0, self.rho0)
        self.Tw = self.T0
        self.valid = True

    def u(self, T, rho):
        return self.tab.prop("u", T, rho) if self.tab else self.gas.cv * T

    def h(self, T, rho):
        return self.tab.prop("h", T, rho) if self.tab else self.gas.cp * T

    def state(self, m=None, U=None):
        m = self.m if m is None else m
        U = self.U if U is None else U
        rho = max(m, 1e-12) / self.V
        mode = self.tank.thermal
        if mode == "isothermal":
            T = self.T0
        elif mode == "polytropic":
            T = self.T0 * (rho / self.rho0) ** (self.tank.polytropic_n - 1)
        else:
            T = self.tab.T_from_u(rho, U / max(m, 1e-12)) if self.tab else (U / max(m, 1e-12)) / self.gas.cv
        if mode == "polytropic":
            p = self.tank.pressure_bar * 1e5 * (rho / self.rho0) ** self.tank.polytropic_n
        else:
            p = self.tab.prop("p", T, rho) if self.tab else rho * self.gas.R * T
        ok = bool(self.tab.valid(T, rho) and T > self.tab.T[0] + 0.5) if self.tab else True
        return p, T, rho, ok

    def feed(self, p_tank: float, throttle: float) -> float:
        """Stagnation pressure delivered to each nozzle."""
        th = min(max(throttle, 0.0), 1.0)
        if self.thr.regulated:
            return min(th * self.thr.reg_pressure_bar * 1e5, max(p_tank - self.vals["reg_dropout_bar"] * 1e5, 0.0))
        return th * p_tank

    def thrust_state(self, throttle: float, m=None, U=None):
        p, T, rho, ok = self.state(m, U)
        p0 = self.feed(p, throttle)
        Z = self.tab.prop("Z", T, self.tab.rho_from_pT(max(p0, 2e4), T)) if (self.tab and p0 > 2e5) else 1.0
        nz = nozzle(p0, T, self.gas, self.thr.throat_area, self.thr.expansion_ratio, self.thr.ambient_pa,
                    self.vals["nozzle_cd"], self.vals["nozzle_cf_eff"], Z, self.pe_ratio)
        n = self.thr.n_thrusters
        return {"p_tank": p, "T_tank": T, "p0": p0, "mdot": nz.mdot * n, "thrust": nz.thrust * n, "ue": nz.ue,
                "isp": nz.isp, "Te": nz.Te, "choked": nz.choked, "separated": nz.separated, "valid": ok, "rho": rho,
                "per_thruster": nz.thrust}

    def max_thrust(self) -> float:
        return self.thrust_state(1.0)["thrust"]

    def rhs(self, m, U, Tw, mdot):
        p, T, rho, _ = self.state(m, U)
        mode = self.tank.thermal
        Q = self.vals["wall_h"] * self.A_wall * (Tw - T) if mode == "heat_transfer" else 0.0
        dU = -mdot * self.h(T, rho) + Q
        dTw = (-Q + 10.0 * self.A_wall * (T_AMB - Tw)) / (self.m_wall * self.vals["wall_c"]) if mode == "heat_transfer" else 0.0
        if mode in ("isothermal", "polytropic"):
            dU = 0.0          # U is not used by these modes
        return -mdot, dU, dTw

    def step(self, dt: float, throttle: float) -> dict:
        """Advance dt with the throttle held; returns the thrust state at the start of the step."""
        st = self.thrust_state(throttle)
        if self.m <= 1e-9 or not st["valid"]:
            st.update(mdot=0.0, thrust=0.0)
        mdot = min(st["mdot"], self.m / dt)
        dm, dU, dTw = self.rhs(self.m, self.U, self.Tw, mdot)
        self.m += dm * dt
        self.U += dU * dt
        self.Tw += dTw * dt
        if self.tank.thermal == "isothermal":
            self.U = self.m * self.u(self.T0, self.m / self.V)
        st["mdot_used"] = mdot
        return st

    # ---- reference integration
    def blowdown_ivp(self, throttle: float = 1.0, t_end: float = 600.0, thrust_cutoff_frac: float = 0.02,
                     rtol: float = 1e-8, n_out: int = 400):
        F_start = self.thrust_state(throttle)["thrust"]

        def f(t, y):
            m, U, Tw = y
            st = self.thrust_state(throttle, m, U)
            mdot = st["mdot"] if st["valid"] else 0.0
            return self.rhs(m, U, Tw, mdot)

        def ev_low(t, y):
            st = self.thrust_state(throttle, y[0], y[1])
            return st["thrust"] - thrust_cutoff_frac * F_start if st["valid"] else -1.0
        ev_low.terminal = True
        y0 = [self.m, self.U, self.Tw]
        sol = solve_ivp(f, (0, t_end), y0, method="LSODA", rtol=rtol, atol=[1e-9 * max(self.m, 1), 1e-6 * abs(self.U) + 1, 1e-6],
                        events=ev_low, dense_output=True)
        t_stop = sol.t[-1]
        ts = np.linspace(0, t_stop, n_out)
        Y = sol.sol(ts)
        rows = [self.thrust_state(throttle, Y[0, i], Y[1, i]) for i in range(n_out)]
        impulse = float(np.trapezoid([r["thrust"] for r in rows], ts))
        return {"t": ts.tolist(), "m": Y[0].tolist(), "U": Y[1].tolist(), "Tw": Y[2].tolist(),
                "p_tank": [r["p_tank"] for r in rows], "T_tank": [r["T_tank"] for r in rows],
                "thrust": [r["thrust"] for r in rows], "mdot": [r["mdot"] for r in rows],
                "isp": [r["isp"] for r in rows], "Te": [r["Te"] for r in rows], "valid": [r["valid"] for r in rows],
                "t_stop": float(t_stop), "impulse": impulse, "mass_used": float(self.m - Y[0, -1]),
                "stopped_by": "thrust_cutoff_or_model_limit" if sol.status == 1 else "t_end"}


# --------------------------------------------------------------------------------------------- closed forms
def tau0(V: float, At: float, gas: Gas, T0: float, cd: float = 1.0) -> float:
    return V / (cd * At * gamma_flow(gas.gamma) * math.sqrt(gas.R * T0))


def analytic_isothermal_p(t, p0, V, At, gas, T0, cd=1.0):
    return p0 * np.exp(-np.asarray(t) / tau0(V, At, gas, T0, cd))


def analytic_adiabatic_p(t, p0, V, At, gas, T0, cd=1.0):
    g = gas.gamma
    return p0 * (1 + (g - 1) / 2 * np.asarray(t) / tau0(V, At, gas, T0, cd)) ** (-2 * g / (g - 1))


def ideal_isp(gas: Gas, T0: float, pe_over_p0: float, pa_over_p0: float = 0.0, eps: float | None = None) -> float:
    """Ideal Isp of a nozzle (eta = 1); vacuum and perfectly expanded cases follow from pe/pa choices."""
    g, R = gas.gamma, gas.R
    ue = math.sqrt(2 * g / (g - 1) * R * T0 * (1 - pe_over_p0 ** ((g - 1) / g)))
    if eps is None:
        return ue / G0
    cstar = math.sqrt(R * T0) / gamma_flow(g)
    return (ue + (pe_over_p0 - pa_over_p0) * eps * cstar) / G0
