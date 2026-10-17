"""Working-gas properties for cold-gas propulsion: ideal gas and tabulated real gas (air, nitrogen).

Ideal gas: calorically perfect, R and gamma below (gamma = 1.40 for both air and N2 near room temperature).
Real gas: bilinear interpolation (in T and log rho) of tables generated from reference Helmholtz equations of state
(`gen_realgas.py`; Lemmon et al. 2000 for air, Span et al. 2000 for nitrogen). Table validity: T 135-400 K,
rho 0.02-650 kg/m^3 (p up to ~1000 bar at 300 K). Outside the grid the functions clamp and set `valid=False`.

Does real-gas behaviour matter? At 293 K the compressibility factor Z of air is 0.99 at 100 bar, 1.03 at 200 bar,
1.10 at 300 bar and 1.52 at 690 bar (10 000 psi). An ideal-gas model therefore overstates the stored mass by ~10 % at
300 bar and by ~50 % at 690 bar. Below ~150 bar the ideal-gas error is < 2 %. `tests/test_propulsion_coldgas.py`
checks these numbers. All tank models default to the real-gas table.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from pydantic import BaseModel

DATA = Path(__file__).resolve().parent / "data"
P_ATM = 101325.0


class Gas(BaseModel):
    key: str
    name: str
    R: float          # specific gas constant [J/(kg K)]
    gamma: float      # ideal-gas heat-capacity ratio near 293 K
    molar_mass: float

    @property
    def cp(self) -> float:
        return self.gamma * self.R / (self.gamma - 1)

    @property
    def cv(self) -> float:
        return self.R / (self.gamma - 1)


GASES = {
    "air": Gas(key="air", name="dry air", R=287.05, gamma=1.40, molar_mass=0.0289647),
    "n2": Gas(key="n2", name="nitrogen", R=296.80, gamma=1.40, molar_mass=0.0280134),
}


class RealGasTable:
    def __init__(self, key: str, rom: bool = False):
        name = f"rom_realgas_{key}.json" if rom else f"realgas_{key}.json"
        d = json.loads((DATA / name).read_text(encoding="utf-8"))
        self.key = key
        self.rom = rom
        self.R = d["R"]
        self.T = np.array(d["T"])
        self.rho = np.array(d["rho"])
        self.lrho = np.log(self.rho)
        self.tab = {k: np.array(d[k]) for k in ("p", "u", "h", "s", "Z")}

    # ------------------------------------------------------------------ interpolation helpers
    def _col(self, rho: float):
        lr = math.log(min(max(rho, self.rho[0]), self.rho[-1]))
        j = int(np.clip(np.searchsorted(self.lrho, lr) - 1, 0, len(self.rho) - 2))
        w = (lr - self.lrho[j]) / (self.lrho[j + 1] - self.lrho[j])
        return j, w

    def column(self, q: str, rho: float) -> np.ndarray:
        j, w = self._col(rho)
        a = self.tab[q]
        return a[:, j] * (1 - w) + a[:, j + 1] * w

    def prop(self, q: str, T: float, rho: float) -> float:
        return float(np.interp(T, self.T, self.column(q, rho)))

    def valid(self, T: float, rho: float) -> bool:
        return bool(self.T[0] <= T <= self.T[-1] and self.rho[0] <= rho <= self.rho[-1])

    # ------------------------------------------------------------------ inversions
    def T_from_u(self, rho: float, u: float) -> float:
        return float(np.interp(u, self.column("u", rho), self.T))

    def rho_from_pT(self, p: float, T: float) -> float:
        T = min(max(T, self.T[0]), self.T[-1])
        i = int(np.clip(np.searchsorted(self.T, T) - 1, 0, len(self.T) - 2))
        w = (T - self.T[i]) / (self.T[i + 1] - self.T[i])
        prow = self.tab["p"][i] * (1 - w) + self.tab["p"][i + 1] * w     # p is monotone in rho for T > Tc
        return float(math.exp(np.interp(math.log(p), np.log(prow), self.lrho)))

    def Z(self, p: float, T: float) -> float:
        return self.prop("Z", T, self.rho_from_pT(p, T))

    def T_from_rho_s(self, rho: float, s: float) -> float:
        return float(np.interp(s, self.column("s", rho), self.T))

    # ------------------------------------------------------------------ derived quantities
    def isentrope(self, p0: float, T0: float, rho_fracs: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """States along the isentrope through (p0, T0) at densities rho0 * rho_fracs: returns (p, T, valid)."""
        rho0 = self.rho_from_pT(p0, T0)
        s0 = self.prop("s", T0, rho0)
        ps, Ts, ok = [], [], []
        for f in rho_fracs:
            r = rho0 * f
            T = self.T_from_rho_s(r, s0)
            ps.append(self.prop("p", T, r)); Ts.append(T); ok.append(self.valid(T, r) and T > self.T[0] + 1e-9)
        return np.array(ps), np.array(Ts), np.array(ok)

    def flow_exergy(self, p: float, T: float, T_amb: float = 293.15, p_amb: float = P_ATM) -> float:
        """Specific flow exergy [J/kg] = (h - h_a) - T_a (s - s_a): minimum work to compress 1 kg from ambient."""
        r, ra = self.rho_from_pT(p, T), self.rho_from_pT(p_amb, T_amb)
        return (self.prop("h", T, r) - self.prop("h", T_amb, ra)) - T_amb * (self.prop("s", T, r) - self.prop("s", T_amb, ra))

    def closed_exergy(self, p: float, T: float, T_amb: float = 293.15, p_amb: float = P_ATM) -> float:
        """Specific non-flow exergy [J/kg] of gas held in a tank = (u-u_a) + p_a (v-v_a) - T_a (s-s_a).
        Upper bound on the work that 1 kg of stored gas can deliver to anything (thrust work + jet KE included)."""
        r, ra = self.rho_from_pT(p, T), self.rho_from_pT(p_amb, T_amb)
        return ((self.prop("u", T, r) - self.prop("u", T_amb, ra)) + p_amb * (1 / r - 1 / ra)
                - T_amb * (self.prop("s", T, r) - self.prop("s", T_amb, ra)))


@lru_cache(maxsize=None)
def real_gas(key: str, rom: bool = False) -> RealGasTable:
    """Full table (default) or the reduced ROM table shipped to the browser (every 2nd density point, 5 sig. figs)."""
    return RealGasTable(key, rom)


def write_rom_tables() -> dict[str, dict]:
    """Sub-sample the full tables onto the browser grid; values are exact EOS values at retained grid points."""
    out = {}
    for key in GASES:
        d = json.loads((DATA / f"realgas_{key}.json").read_text(encoding="utf-8"))
        keep = list(range(0, len(d["rho"]), 2))
        if keep[-1] != len(d["rho"]) - 1:
            keep.append(len(d["rho"]) - 1)
        r = {"fluid": d["fluid"], "eos": d["eos"], "R": d["R"], "T": d["T"],
             "rho": [float(f"{d['rho'][j]:.6g}") for j in keep]}
        for q in ("p", "u", "h", "s", "Z"):
            r[q] = [[float(f"{row[j]:.7g}") for j in keep] for row in d[q]]
        (DATA / f"rom_realgas_{key}.json").write_text(json.dumps(r, separators=(",", ":")), encoding="utf-8")
        out[key] = r
    real_gas.cache_clear()
    return out


def ideal_density(gas: Gas, p: float, T: float) -> float:
    return p / (gas.R * T)


def density(gas_key: str, p: float, T: float, real: bool = True) -> float:
    return real_gas(gas_key).rho_from_pT(p, T) if real else ideal_density(GASES[gas_key], p, T)


def ideal_closed_exergy(gas: Gas, p: float, T: float, T_amb: float = 293.15, p_amb: float = P_ATM) -> float:
    """Ideal-gas non-flow exergy per kg (same definition as RealGasTable.closed_exergy)."""
    v, va = gas.R * T / p, gas.R * T_amb / p_amb
    ds = gas.cp * math.log(T / T_amb) - gas.R * math.log(p / p_amb)
    return gas.cv * (T - T_amb) + p_amb * (v - va) - T_amb * ds
