"""Bench-test analysis: turn thrust-stand and battery-discharge logs into MEASURED assumptions.

Inputs are CSV files written by bench/logger.py (see docs/BENCH_TEST.md):
  thrust sweep : t_s, throttle_us, thrust_g, voltage_v, current_a[, rpm][, torque_nmm]
  discharge    : t_s, voltage_v, current_a
  step response: t_s, throttle_us, thrust_g

Outputs data/measurements/assumptions_measured.json, which catalog.global_assumptions() overlays on the
engineering-judgment values with status MEASURED. Nothing here generates data; it only fits what was logged.

Fits (momentum theory, same equations as physics/rotor.py):
  combined   M = FM * eta / k_duct = T^1.5 / (P_elec * sqrt(2 rho A))      (thrust + electrical power only)
  separated  FM = T^1.5 / (P_shaft sqrt(2 rho A)), eta = P_shaft / P_elec   (needs rpm and torque)
  duct       k_duct = M_open / M_ducted  ->  effectiveness = (1 - k_duct) / (1 - 1/sqrt 2)
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

from .constants import G0, RHO_AIR_SL

MEAS_DIR = Path(__file__).resolve().parents[2] / "data" / "measurements"
MEAS_FILE = MEAS_DIR / "assumptions_measured.json"
CAL_UNCERTAINTY = 0.02      # load-cell + power-sensor calibration, relative (1 sigma); update after calibration


def read_csv(path: str | Path) -> dict[str, np.ndarray]:
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path}: no data rows")
    return {k: np.array([float(r[k]) for r in rows if r.get(k) not in (None, "")]) for k in rows[0]}


def steady_points(d: dict[str, np.ndarray], settle_s: float = 1.0) -> list[dict[str, float]]:
    """Average each constant-throttle plateau, discarding the first `settle_s` seconds after a change."""
    thr, t = d["throttle_us"], d["t_s"]
    pts = []
    edges = [0] + [i for i in range(1, len(thr)) if thr[i] != thr[i - 1]] + [len(thr)]
    for a, b in zip(edges[:-1], edges[1:]):
        sel = np.arange(a, b)
        sel = sel[t[sel] >= t[a] + settle_s]
        if len(sel) < 5 or thr[a] <= 1000:
            continue
        p = {"throttle_us": float(thr[a]), "n": int(len(sel))}
        for k in ("thrust_g", "voltage_v", "current_a", "rpm", "torque_nmm"):
            if k in d and len(d[k]) == len(thr):
                p[k] = float(np.mean(d[k][sel]))
                p[k + "_sd"] = float(np.std(d[k][sel]))
        pts.append(p)
    return pts


def fit_rotor(points: list[dict[str, float]], diameter_m: float, rho: float = RHO_AIR_SL,
              min_fraction_of_max: float = 0.3) -> dict:
    """Return combined M (and FM, eta when rpm & torque were logged), each with mean and 2-sigma band."""
    if not points:
        raise ValueError("no steady thrust points")
    A = math.pi * (diameter_m / 2) ** 2
    tmax = max(p["thrust_g"] for p in points)
    use = [p for p in points if p["thrust_g"] >= min_fraction_of_max * tmax]
    T = np.array([p["thrust_g"] for p in use]) / 1000 * G0
    Pe = np.array([p["voltage_v"] * p["current_a"] for p in use])
    M = T ** 1.5 / (Pe * math.sqrt(2 * rho * A))
    out = {"n_points": len(use), "thrust_max_n": tmax / 1000 * G0,
           "elec_power_max_w": float(max(p["voltage_v"] * p["current_a"] for p in points)),
           "combined_M": _band(M)}
    if all("rpm" in p and "torque_nmm" in p for p in use):
        Ps = np.array([p["torque_nmm"] / 1000 * p["rpm"] * 2 * math.pi / 60 for p in use])
        out["figure_of_merit"] = _band(T ** 1.5 / (Ps * math.sqrt(2 * rho * A)))
        out["motor_efficiency"] = _band(Ps / Pe)
        out["torque_ratio_m"] = _band(np.array([p["torque_nmm"] / 1000 for p in use]) / T)
    return out


def _band(x: np.ndarray) -> dict:
    m = float(np.mean(x))
    sd = float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
    sd = math.hypot(sd, CAL_UNCERTAINTY * 1.5 * m)        # T^1.5 amplifies thrust calibration error
    return {"mean": m, "low": m - 2 * sd, "high": m + 2 * sd, "sd": sd, "n": int(len(x))}


def duct_effectiveness(open_fit: dict, ducted_fit: dict) -> dict:
    """Same motor/fan measured open and inside the printed duct coupon."""
    mo, md = open_fit["combined_M"], ducted_fit["combined_M"]
    k = mo["mean"] / md["mean"]
    rel = math.hypot(mo["sd"] / mo["mean"], md["sd"] / md["mean"])
    e = (1 - k) / (1 - 1 / math.sqrt(2))
    de = rel * k / (1 - 1 / math.sqrt(2))
    return {"k_duct": k, "mean": e, "low": e - 2 * de, "high": e + 2 * de}


def fit_battery(d: dict[str, np.ndarray], capacity_mah: float, cells: int = 1, v_cut: float = 3.3) -> dict:
    """Usable energy fraction to cutoff and internal resistance from load steps."""
    t, v, i = d["t_s"], d["voltage_v"], d["current_a"]
    end = int(np.argmax(v < v_cut * cells)) if np.any(v < v_cut * cells) else len(v)
    e_wh = float(np.trapezoid(v[:end] * i[:end], t[:end]) / 3600)
    nameplate = capacity_mah / 1000 * 3.7 * cells
    # internal resistance: dV/dI across current steps > 0.3 A
    di, dv = np.diff(i), np.diff(v)
    steps = np.abs(di) > 0.3
    r = -dv[steps] / di[steps]
    return {"energy_wh": e_wh, "usable_fraction": e_wh / nameplate,
            "internal_resistance_ohm": float(np.median(r)) if steps.any() else None,
            "peak_power_w": float(np.max(v * i)), "n_steps": int(steps.sum())}


def fit_time_constant(d: dict[str, np.ndarray]) -> float:
    """First-order time constant from the first throttle step-up: time to reach 63.2 % of the rise."""
    thr, t, T = d["throttle_us"], d["t_s"], d["thrust_g"]
    k = int(np.argmax(np.diff(thr) > 0)) + 1
    t0, T0 = t[k], float(np.mean(T[max(0, k - 20):k]))
    nxt = np.argmax(np.diff(thr[k:]) != 0) + k if np.any(np.diff(thr[k:]) != 0) else len(thr) - 1
    T1 = float(np.mean(T[max(k, nxt - 20):nxt]))
    target = T0 + 0.632 * (T1 - T0)
    j = k + int(np.argmax(T[k:nxt] >= target))
    return float(t[j] - t0)


def write_measured(entries: dict[str, dict], provenance: str) -> Path:
    """entries: assumption key -> {nominal, low, high}. Merged with any previous measurements."""
    MEAS_DIR.mkdir(parents=True, exist_ok=True)
    cur = json.loads(MEAS_FILE.read_text()) if MEAS_FILE.exists() else {}
    for k, v in entries.items():
        lo, hi = sorted((v["low"], v["high"]))
        cur[k] = {"nominal": v["nominal"], "low": lo, "high": hi, "source": provenance}
    MEAS_FILE.write_text(json.dumps(cur, indent=1))
    return MEAS_FILE


def analyse_session(open_csv: str, diameter_m: float, ducted_csv: str | None = None,
                    discharge_csv: str | None = None, capacity_mah: float | None = None,
                    step_csv: str | None = None, catalog_motor_eff: float = 0.65, label: str = "bench") -> dict:
    """End-to-end: fit everything that was logged and write the measured-assumption overlay."""
    rep: dict = {}
    entries: dict[str, dict] = {}
    of = fit_rotor(steady_points(read_csv(open_csv)), diameter_m)
    rep["open"] = of
    if "figure_of_merit" in of:
        fm, eta = of["figure_of_merit"], of["motor_efficiency"]
        entries["figure_of_merit"] = {"nominal": fm["mean"], "low": fm["low"], "high": fm["high"]}
        s = eta["mean"] / catalog_motor_eff
        entries["motor_eff_scale"] = {"nominal": s, "low": eta["low"] / catalog_motor_eff, "high": eta["high"] / catalog_motor_eff}
        tr = of["torque_ratio_m"]
        entries["rotor_torque_ratio"] = {"nominal": tr["mean"], "low": tr["low"], "high": tr["high"]}
    else:
        # only the product FM*eta is identifiable: attribute it to FM at the catalog efficiency, and say so
        m = of["combined_M"]
        entries["figure_of_merit"] = {k: m[src] / catalog_motor_eff for k, src in (("nominal", "mean"), ("low", "low"), ("high", "high"))}
        rep["note"] = "rpm/torque not logged: FM inferred from FM*eta at catalog motor efficiency"
    if ducted_csv:
        df = fit_rotor(steady_points(read_csv(ducted_csv)), diameter_m)
        rep["ducted"] = df
        de = duct_effectiveness(of, df)
        rep["duct"] = de
        entries["duct_effectiveness"] = {"nominal": de["mean"], "low": de["low"], "high": de["high"]}
    if discharge_csv and capacity_mah:
        b = fit_battery(read_csv(discharge_csv), capacity_mah)
        rep["battery"] = b
        u = b["usable_fraction"]
        entries["battery_specific_energy_derate"] = {"nominal": u, "low": u * 0.97, "high": min(u * 1.03, 1.0)}
    if step_csv:
        tau = fit_time_constant(read_csv(step_csv))
        rep["time_constant_s"] = tau
        entries["motor_time_constant"] = {"nominal": tau, "low": tau * 0.8, "high": tau * 1.2}
    rep["written_to"] = str(write_measured(entries, f"MEASURED: {label}"))
    rep["entries"] = entries
    return rep
