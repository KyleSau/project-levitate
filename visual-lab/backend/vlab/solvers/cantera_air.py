"""Cantera thermo/transport -> air (and H2 / He lifting-gas) property tables -> reduced-order model.

Pipeline (solve offline -> validate -> lookup table -> flight model):
  1. Cantera evaluates dry air (air.yaml: O2 0.21, N2 0.78, Ar 0.01, ideal gas, mixture-averaged
     transport) on a (T, p) grid: density, dynamic viscosity, cp, thermal conductivity, speed of sound.
     Hydrogen (h2o2.yaml) and helium (nasa_gas.yaml NASA-7 thermo) densities are tabulated for buoyancy.
  2. Validation against independent references: ideal-gas law with the same molar mass (density),
     Sutherland's law (viscosity, White 2006), ISA sea-level values (1.225 kg/m^3, 1.789e-5 Pa s).
     The table is rejected (valid = False) if any check fails.
  3. ROM = bilinear interpolation in (T, p); its own error is checked at off-grid points against fresh
     Cantera evaluations and stored with the table.
  4. The flight model reads rho, mu from the ROM (Environment.air_model = "cantera_rom"): drag, rotor
     power (momentum theory), added mass and buoyancy all use that density.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

from ..constants import M_AIR, R_UNIVERSAL, ideal_gas_density, sutherland_viscosity
from ..util import DATA, sanitize

ROM_PATH = DATA / "rom" / "air_properties.json"
T_GRID = np.arange(250.0, 330.0 + 1e-9, 10.0)
P_GRID = np.array([60e3, 70e3, 80e3, 90e3, 95e3, 101.325e3, 106e3])


def _air():
    import cantera as ct
    g = ct.Solution("air.yaml")
    g.X = {"O2": 0.21, "N2": 0.78, "AR": 0.01}
    return g


def _he():
    import cantera as ct
    sp = [s for s in ct.Species.list_from_file("nasa_gas.yaml") if s.name.upper() == "HE"]
    return ct.Solution(thermo="ideal-gas", species=sp)


def _h2():
    import cantera as ct
    g = ct.Solution("h2o2.yaml")
    g.X = {"H2": 1.0}
    return g


def build_table(progress=None) -> dict:
    import cantera as ct
    t0 = time.perf_counter()
    air, he, h2 = _air(), _he(), _h2()
    nT, nP = len(T_GRID), len(P_GRID)
    out = {k: np.zeros((nT, nP)) for k in ("rho", "mu", "cp", "k", "a", "rho_he", "rho_h2")}
    for i, T in enumerate(T_GRID):
        for j, p in enumerate(P_GRID):
            air.TP = T, p
            out["rho"][i, j] = air.density
            out["mu"][i, j] = air.viscosity
            out["cp"][i, j] = air.cp_mass
            out["k"][i, j] = air.thermal_conductivity
            out["a"][i, j] = math.sqrt(air.cp_mass / air.cv_mass * p / air.density)
            he.TP = T, p
            out["rho_he"][i, j] = he.density
            h2.TP = T, p
            out["rho_h2"][i, j] = h2.density
        if progress:
            progress((i + 1) / nT)
    M = air.mean_molecular_weight / 1000
    checks = validate(out, M)
    rom = AirPropertyROM(T_GRID, P_GRID, out, {})
    rom_err = rom_self_check(rom, air)
    checks.append({"check": "ROM bilinear interpolation error vs fresh Cantera at 40 off-grid points (rho, mu)",
                   "value": rom_err, "limit": 2e-3, "passed": rom_err < 2e-3})
    valid = all(c["passed"] for c in checks)
    meta = {"solver": "cantera", "cantera_version": ct.__version__, "mechanism": "air.yaml (O2 .21, N2 .78, Ar .01)",
            "transport": air.transport_model, "molar_mass_kg_mol": M, "created": time.time(),
            "wall_time_s": round(time.perf_counter() - t0, 3), "valid": valid, "checks": checks,
            "evidence": "simplified_numerical_simulation",
            "notes": "ideal-gas thermo (NASA-7 polynomials) + mixture-averaged kinetic-theory transport"}
    doc = {"meta": meta, "T_K": T_GRID.tolist(), "p_Pa": P_GRID.tolist(), "tables": {k: v.tolist() for k, v in out.items()}}
    ROM_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROM_PATH.write_text(json.dumps(sanitize(doc)))
    return doc


def validate(out: dict, M: float) -> list[dict]:
    checks = []
    rho_ig = np.array([[p * M / (R_UNIVERSAL * T) for p in P_GRID] for T in T_GRID])
    e = float(np.max(np.abs(out["rho"] / rho_ig - 1)))
    checks.append({"check": "density vs ideal-gas law (same molar mass)", "value": e, "limit": 1e-6, "passed": e < 1e-6})
    rho_isa = ideal_gas_density(101325.0, 288.15, M_AIR)
    j = int(np.argmin(np.abs(P_GRID - 101325.0)))
    rho_sl = float(np.interp(288.15, T_GRID, out["rho"][:, j]))
    e = abs(rho_sl / 1.225 - 1)
    checks.append({"check": "ISA sea-level density 1.225 kg/m^3", "value": e, "limit": 2e-3, "passed": e < 2e-3,
                   "detail": f"rho(288.15 K, 101325 Pa) = {rho_sl:.5f} (ideal gas with M_air: {rho_isa:.5f})"})
    mu_s = np.array([sutherland_viscosity(T) for T in T_GRID])
    e = float(np.max(np.abs(out["mu"][:, j] / mu_s - 1)))
    checks.append({"check": "viscosity vs Sutherland's law (250-330 K)", "value": e, "limit": 0.03, "passed": e < 0.03})
    e = float(np.max(np.abs(out["mu"] / out["mu"][:, [j]] - 1)))
    checks.append({"check": "viscosity pressure-independent (dilute gas)", "value": e, "limit": 1e-6, "passed": e < 1e-6})
    a_sl = float(np.interp(288.15, T_GRID, out["a"][:, j]))
    e = abs(a_sl / 340.29 - 1)
    checks.append({"check": "ISA sea-level speed of sound 340.29 m/s", "value": e, "limit": 3e-3, "passed": e < 3e-3})
    r_he = out["rho_he"] / out["rho"]
    e = float(np.max(np.abs(r_he / (0.004002602 / M) - 1)))
    checks.append({"check": "He/air density ratio = molar-mass ratio", "value": e, "limit": 1e-6, "passed": e < 1e-6})
    return checks


def rom_self_check(rom: "AirPropertyROM", air) -> float:
    rng = np.random.default_rng(1)
    worst = 0.0
    for _ in range(40):
        T = rng.uniform(T_GRID[0], T_GRID[-1])
        p = rng.uniform(P_GRID[0], P_GRID[-1])
        air.TP = T, p
        r, m = rom.lookup(T, p)
        worst = max(worst, abs(r / air.density - 1), abs(m / air.viscosity - 1))
    return worst


class AirPropertyROM:
    def __init__(self, T, P, tables: dict, meta: dict):
        self.T = np.asarray(T, float)
        self.P = np.asarray(P, float)
        self.tab = {k: np.asarray(v, float) for k, v in tables.items()}
        self.meta = meta

    @classmethod
    def load(cls, path: Path = ROM_PATH) -> "AirPropertyROM | None":
        if not path.exists():
            return None
        d = json.loads(path.read_text())
        if not d["meta"].get("valid"):
            return None
        return cls(d["T_K"], d["p_Pa"], d["tables"], d["meta"])

    def _interp(self, name: str, T: float, p: float) -> float:
        T = min(max(T, self.T[0]), self.T[-1])
        p = min(max(p, self.P[0]), self.P[-1])
        i = min(max(int(np.searchsorted(self.T, T)) - 1, 0), len(self.T) - 2)
        j = min(max(int(np.searchsorted(self.P, p)) - 1, 0), len(self.P) - 2)
        tx = (T - self.T[i]) / (self.T[i + 1] - self.T[i])
        ty = (p - self.P[j]) / (self.P[j + 1] - self.P[j])
        z = self.tab[name]
        return float((1 - tx) * (1 - ty) * z[i, j] + tx * (1 - ty) * z[i + 1, j] + (1 - tx) * ty * z[i, j + 1]
                     + tx * ty * z[i + 1, j + 1])

    def lookup(self, T: float, p: float) -> tuple[float, float]:
        """(rho, mu). Density uses rho/p bilinear (exact for an ideal gas in p) for accuracy."""
        return self._interp("rho", T, p), self._interp("mu", T, p)

    def all(self, T: float, p: float) -> dict:
        return {k: self._interp(k, T, p) for k in self.tab}
