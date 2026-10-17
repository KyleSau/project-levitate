"""Rotor / ducted-fan hover performance from actuator-disk momentum theory.

Equations
---------
Open rotor, ideal induced power:      P_i = T^1.5 / sqrt(2 rho A)
Ideal duct, exit area ratio sigma=1:  P_i = T^1.5 / sqrt(4 rho A)   (29.3 % less)
Real shaft power:                     P_s = P_i / FM
Ground effect (Cheeseman & Bennett 1955, constant power):
                                      T_IGE / T_OGE = 1 / (1 - (R / 4z)^2)
  -> at constant thrust the induced power scales by k^-1.5.

These are analytical estimates (Evidence.ANALYTICAL). FM and duct effectiveness are
uncertain assumptions; they dominate the endurance uncertainty and must be measured.
"""
from __future__ import annotations

import math

from ..constants import MU_AIR_SL, RHO_AIR_SL

CT_TYPICAL = 0.10     # thrust coefficient T = CT rho n^2 D^4 (n in rev/s), micro props 0.08-0.13
RE_REF = 3.0e4        # Reynolds number at which the FM assumption is anchored


def duct_power_factor(ducted: bool, effectiveness: float) -> float:
    """Multiplier on open-rotor ideal power. Ideal sigma=1 duct = 1/sqrt(2)."""
    if not ducted:
        return 1.0
    return 1.0 - effectiveness * (1.0 - 1.0 / math.sqrt(2.0))


def ground_effect_thrust_ratio(radius_m: float, height_m: float) -> float:
    """Cheeseman-Bennett; clamped at z/R = 0.5 where the model stops being credible."""
    z = max(height_m, 0.5 * radius_m)
    q = (radius_m / (4.0 * z)) ** 2
    return 1.0 / (1.0 - q)


def rotor_speed_rev_s(thrust_n: float, diameter_m: float, rho: float = RHO_AIR_SL, ct: float = CT_TYPICAL) -> float:
    return math.sqrt(max(thrust_n, 0.0) / (ct * rho * diameter_m ** 4))


def blade_reynolds(thrust_n: float, diameter_m: float, rho: float = RHO_AIR_SL) -> float:
    n = rotor_speed_rev_s(thrust_n, diameter_m, rho)
    v75 = 0.75 * math.pi * diameter_m * n
    chord = 0.15 * diameter_m
    return rho * v75 * chord / MU_AIR_SL


def fm_at_reynolds(fm_ref: float, re: float) -> float:
    """Weak Reynolds correction (FM rises with Re in the 1e4-1e5 range). Engineering judgment, exponent 0.1."""
    if re <= 0:
        return fm_ref
    return fm_ref * min(max((re / RE_REF) ** 0.1, 0.75), 1.12)


def hover_shaft_power(thrust_n: float, diameter_m: float, fm: float, duct_factor: float,
                      height_m: float = 10.0, rho: float = RHO_AIR_SL) -> float:
    """Shaft power [W] for one rotor producing `thrust_n` while hovering at `height_m`."""
    if thrust_n <= 0:
        return 0.0
    area = math.pi * (diameter_m / 2) ** 2
    p_ideal = thrust_n ** 1.5 / math.sqrt(2 * rho * area)
    k_ge = ground_effect_thrust_ratio(diameter_m / 2, height_m)
    fm_eff = fm_at_reynolds(fm, blade_reynolds(thrust_n, diameter_m, rho))
    return p_ideal * duct_factor / fm_eff * k_ge ** -1.5


def max_thrust_from_shaft_power(p_shaft_w: float, diameter_m: float, fm: float, duct_factor: float,
                                rho: float = RHO_AIR_SL) -> float:
    """Invert hover_shaft_power (out of ground effect) by fixed-point iteration on the Re correction."""
    area = math.pi * (diameter_m / 2) ** 2
    t = (p_shaft_w * fm / duct_factor * math.sqrt(2 * rho * area)) ** (2 / 3)
    for _ in range(20):
        fm_eff = fm_at_reynolds(fm, blade_reynolds(t, diameter_m, rho))
        t = (p_shaft_w * fm_eff / duct_factor * math.sqrt(2 * rho * area)) ** (2 / 3)
    return t


def tip_mach(thrust_n: float, diameter_m: float, rho: float = RHO_AIR_SL) -> float:
    return math.pi * diameter_m * rotor_speed_rev_s(thrust_n, diameter_m, rho) / 340.3
