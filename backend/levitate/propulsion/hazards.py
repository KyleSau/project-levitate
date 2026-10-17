"""Hazard-zone estimates for propulsive jets (cold gas, rocket black boxes, turbojet) - analytical, order-of-magnitude.

Free round jet far field (x > ~6-10 exit diameters):
    momentum-equivalent diameter  d_eq = sqrt(4 F / (pi rho_a ue^2))      (Thring & Newby 1953 equivalent diameter)
    centreline velocity           u_c(x)  = B_u ue d_eq / x,  B_u = 5.8     (Pope, Turbulent Flows, 2000, round jet)
                                   -> u_c depends only on the thrust: u_c = 6.5 sqrt(F / rho_a) / x
    centreline temperature excess dT_c(x) = B_T dT_e d_eq / x,  B_T = 5.0  (Chen & Rodi 1980 scalar decay)
Impinging jet (hover) radial wall jet:  u_w(r) ~ 1.03 sqrt(F / rho_a) / r  (Poreh, Tsuei & Cermak 1967, r >> h)
Noise (NASA SP-8072, Eldred 1971):  W_ac = eta_ac * 0.5 mdot ue^2,  L_W = 10 log10(W_ac / 1e-12),
    SPL(r) = L_W - 20 log10(r) - 8  (hemispherical spreading over hard ground; no directivity, overall level)
These ignore supersonic shock-cell structure, potential-core length, crossflow, and directivity: treat as +/- 50 %
on distances. Thresholds: assumptions.hazard_thresholds().
"""
from __future__ import annotations

import math

from pydantic import BaseModel

from ..constants import RHO_AIR_SL
from .assumptions import hazard_thresholds

B_U, B_T = 5.8, 5.0


class JetHazard(BaseModel):
    thrust_n: float
    exit_velocity_m_s: float
    exit_temp_k: float
    d_eq_m: float
    velocity_zone_m: float          # distance along the jet axis to fall below the velocity threshold
    temperature_zone_m: float       # distance to fall within the hot/cold threshold
    ground_outwash_zone_m: float    # radius on the ground (hover) to fall below the velocity threshold
    sound_power_w: float
    spl_at_1m_db: float
    spl_at_10m_db: float
    spl_rider_db: float
    distance_140db_m: float
    distance_120db_m: float
    notes: list[str]


def jet_hazard(thrust_n: float, ue: float, exit_temp_k: float, mdot: float, acoustic_eff: float,
               t_amb: float = 293.15, rider_distance_m: float = 1.2) -> JetHazard:
    thr = hazard_thresholds()
    if thrust_n <= 0 or ue <= 0:
        return JetHazard(thrust_n=0, exit_velocity_m_s=0, exit_temp_k=t_amb, d_eq_m=0, velocity_zone_m=0,
                         temperature_zone_m=0, ground_outwash_zone_m=0, sound_power_w=0, spl_at_1m_db=0,
                         spl_at_10m_db=0, spl_rider_db=0, distance_140db_m=0, distance_120db_m=0, notes=[])
    d_eq = math.sqrt(4 * thrust_n / (math.pi * RHO_AIR_SL * ue * ue))
    u_lim = thr["jet_velocity_m_s"][0]
    x_u = max(B_U * ue * d_eq / u_lim, 0.0)
    dTe = exit_temp_k - t_amb
    lim = thr["jet_hot_excess_k"][0] if dTe > 0 else thr["jet_cold_excess_k"][0]
    x_T = B_T * d_eq * dTe / lim if dTe / lim > 1 else 0.0
    r_w = 1.03 * math.sqrt(thrust_n / RHO_AIR_SL) / u_lim
    W = acoustic_eff * 0.5 * mdot * ue * ue
    Lw = 10 * math.log10(max(W, 1e-12) / 1e-12)
    spl = lambda r: Lw - 20 * math.log10(r) - 8  # noqa: E731
    dist = lambda L: 10 ** ((Lw - 8 - L) / 20)   # noqa: E731
    notes = [f"jet stays above {u_lim:.0f} m/s for ~{x_u:.1f} m along its axis"]
    if dTe > 0 and x_T > 0:
        notes.append(f"hot exhaust ({exit_temp_k - 273.15:.0f} C at exit) above ~{t_amb - 273.15 + lim:.0f} C for ~{x_T:.1f} m")
    if dTe < 0 and x_T > 0:
        notes.append(f"cold exhaust ({exit_temp_k - 273.15:.0f} C at exit): frost/condensation, below "
                     f"{t_amb - 273.15 + lim:.0f} C for ~{x_T:.1f} m")
    return JetHazard(thrust_n=thrust_n, exit_velocity_m_s=ue, exit_temp_k=exit_temp_k, d_eq_m=d_eq, velocity_zone_m=x_u,
                     temperature_zone_m=x_T, ground_outwash_zone_m=r_w, sound_power_w=W, spl_at_1m_db=spl(1.0),
                     spl_at_10m_db=spl(10.0), spl_rider_db=spl(rider_distance_m), distance_140db_m=dist(140.0),
                     distance_120db_m=dist(120.0), notes=notes)


def combine_spl(levels_db: list[float]) -> float:
    s = sum(10 ** (L / 10) for L in levels_db if L > 0)
    return 10 * math.log10(s) if s > 0 else 0.0
