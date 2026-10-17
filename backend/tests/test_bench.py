"""Bench analysis must recover known parameters from SYNTHETIC logs (code verification, not measurements)."""
import math

import numpy as np
import pytest

from levitate import bench
from levitate.constants import G0, RHO_AIR_SL

D = 0.022
A = math.pi * (D / 2) ** 2


def _write(path, header, rows):
    with open(path, "w") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            fh.write(",".join("" if v is None else f"{v:.6g}" for v in r) + "\n")


def _sweep(path, fm, eta, k_duct, with_shaft, rng):
    rows, t = [], 0.0
    for thr in range(1100, 2001, 100):
        T = 0.02 + (thr - 1100) / 900 * 0.10                     # N
        p_shaft = T ** 1.5 * k_duct / (fm * math.sqrt(2 * RHO_AIR_SL * A))
        p_e = p_shaft / eta
        v = 3.9 - 0.02 * p_e
        rpm = math.sqrt(T / (0.1 * RHO_AIR_SL * D ** 4)) * 60
        q = p_shaft / (rpm * 2 * math.pi / 60) * 1000            # N*mm
        for _ in range(160):                                       # 4 s at 40 Hz
            rows.append([t, thr, T / G0 * 1000 * (1 + rng.normal(0, 0.003)), v, p_e / v * (1 + rng.normal(0, 0.003)),
                         rpm if with_shaft else None, q if with_shaft else None])
            t += 0.025
    _write(path, ["t_s", "throttle_us", "thrust_g", "voltage_v", "current_a", "rpm", "torque_nmm"], rows)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "MEAS_DIR", tmp_path / "m")
    monkeypatch.setattr(bench, "MEAS_FILE", tmp_path / "m" / "assumptions_measured.json")


def test_recovers_fm_eta_and_duct(tmp_path):
    rng = np.random.default_rng(0)
    _sweep(tmp_path / "open.csv", fm=0.45, eta=0.62, k_duct=1.0, with_shaft=True, rng=rng)
    k = 1 - 0.5 * (1 - 1 / math.sqrt(2))                            # duct effectiveness 0.5
    _sweep(tmp_path / "duct.csv", fm=0.45, eta=0.62, k_duct=k, with_shaft=True, rng=rng)
    rep = bench.analyse_session(str(tmp_path / "open.csv"), D, str(tmp_path / "duct.csv"), catalog_motor_eff=0.62)
    assert rep["open"]["figure_of_merit"]["mean"] == pytest.approx(0.45, rel=0.02)
    assert rep["open"]["motor_efficiency"]["mean"] == pytest.approx(0.62, rel=0.02)
    assert rep["duct"]["mean"] == pytest.approx(0.5, abs=0.05)
    e = rep["entries"]
    assert e["figure_of_merit"]["low"] < 0.45 < e["figure_of_merit"]["high"]
    assert bench.MEAS_FILE.exists()


def test_combined_only_when_no_shaft_data(tmp_path):
    _sweep(tmp_path / "open.csv", fm=0.40, eta=0.60, k_duct=1.0, with_shaft=False, rng=np.random.default_rng(1))
    rep = bench.analyse_session(str(tmp_path / "open.csv"), D, catalog_motor_eff=0.60)
    assert "note" in rep
    assert rep["entries"]["figure_of_merit"]["nominal"] == pytest.approx(0.40, rel=0.02)


def test_battery_fit(tmp_path):
    rows, t, soc = [], 0.0, 1.0
    cap_ah, R = 0.3, 0.15
    while True:
        i = 1.8 if int(t // 20) % 2 == 0 else 2.6
        voc = 3.3 + 0.9 * soc
        v = voc - i * R
        rows.append([t, v, i])
        soc -= i * 0.5 / 3600 / cap_ah
        t += 0.5
        if v < 3.25:
            break
    _write(tmp_path / "dis.csv", ["t_s", "voltage_v", "current_a"], rows)
    b = bench.fit_battery(bench.read_csv(tmp_path / "dis.csv"), 300)
    assert b["internal_resistance_ohm"] == pytest.approx(R, rel=0.05)
    # independent reference: rectangle rule up to the first sample below the 3.3 V cutoff
    end = next(k for k, r in enumerate(rows) if r[1] < 3.3)
    ref = sum(v * i * 0.5 for _, v, i in rows[:end]) / 3600 / (0.3 * 3.7)
    assert b["usable_fraction"] == pytest.approx(ref, rel=0.01)


def test_time_constant(tmp_path):
    rows, tau = [], 0.03
    for k in range(400):
        t = k * 0.005
        thr = 1200 if t < 0.5 else 1600
        T = 20 if t < 0.5 else 20 + 40 * (1 - math.exp(-(t - 0.5) / tau))
        rows.append([t, thr, T])
    _write(tmp_path / "step.csv", ["t_s", "throttle_us", "thrust_g"], rows)
    assert bench.fit_time_constant(bench.read_csv(tmp_path / "step.csv")) == pytest.approx(tau, abs=0.006)
