"""Validation of the cold-gas tank / nozzle model against closed-form solutions and reference data."""
import math

import numpy as np
import pytest

from levitate.constants import G0
from levitate.propulsion.assumptions import coldgas_assumptions
from levitate.propulsion.coldgas import (ColdGasSystem, TankConfig, ThrusterConfig, analytic_adiabatic_p,
                                         analytic_isothermal_p, blast_radius, energy_report, ideal_isp, tank_mass,
                                         tau0)
from levitate.propulsion.gas import GASES, real_gas

VALS = coldgas_assumptions().values() | {"nozzle_cd": 1.0}


def test_real_gas_table_matches_reference_eos():
    # Values from CoolProp 8 (Lemmon 2000 air EOS) at 300 K, independent of the table grid points
    t = real_gas("air")
    for p_bar, z_ref in [(100, 0.99308), (200, 1.03207), (300, 1.10838), (450, 1.26028), (690, 1.53498)]:
        assert t.Z(p_bar * 1e5, 300.0) == pytest.approx(z_ref, rel=3e-3)   # table interpolation
    assert real_gas("n2").Z(300e5, 300.0) == pytest.approx(1.14296, rel=2e-3)


def test_real_gas_matters_above_150_bar():
    t = real_gas("air")
    assert abs(t.Z(100e5, 293.15) - 1) < 0.02            # ideal gas fine at 100 bar
    assert t.Z(300e5, 293.15) > 1.09                      # ~10 % less mass than ideal at 300 bar
    assert t.Z(690e5, 293.15) > 1.5                       # ~50 % at 10 000 psi


def _ideal_sys(thermal, regulated=False, pa=0.0):
    tk = TankConfig(volume_l=10, pressure_bar=200, real_gas=False, thermal=thermal)
    th = ThrusterConfig(throat_diameter_mm=3.0, regulated=regulated, ambient_pa=pa, expansion_ratio=4.0)
    return ColdGasSystem(tk, th, VALS), tk, th


@pytest.mark.parametrize("thermal,analytic", [("isothermal", analytic_isothermal_p), ("adiabatic", analytic_adiabatic_p)])
def test_blowdown_matches_closed_form(thermal, analytic):
    s, tk, th = _ideal_sys(thermal)
    r = s.blowdown_ivp(t_end=3.0, thrust_cutoff_frac=1e-4)
    t = np.array(r["t"])
    p_ref = analytic(t, 200e5, tk.volume_m3, th.throat_area, GASES["air"], 293.15)
    assert np.max(np.abs(np.array(r["p_tank"]) - p_ref) / p_ref) < 1e-4
    # the fixed-step integrator used in the browser converges to the same answer
    s.reset()
    dt, tt, err = 1e-4, 0.0, 0.0
    for i in range(10000):
        s.step(dt, 1.0)
        tt += dt
        if i % 500 == 499:
            p = s.state()[0]
            pr = float(analytic(tt, 200e5, tk.volume_m3, th.throat_area, GASES["air"], 293.15))
            err = max(err, abs(p - pr) / pr)
    assert err < 3e-3


def test_impulse_equals_mass_times_exhaust_velocity_isothermal_vacuum():
    s, tk, th = _ideal_sys("isothermal")
    r = s.blowdown_ivp(t_end=5.0, thrust_cutoff_frac=1e-3)
    isp = r["isp"][0]
    assert np.allclose(r["isp"], isp, rtol=1e-9)              # constant Isp in vacuum at constant T0
    assert r["impulse"] == pytest.approx(r["mass_used"] * isp * G0, rel=2e-3)
    # and Isp equals the ideal formula (eta_cf applied)
    from levitate.propulsion.coldgas import exit_pressure_ratio
    pe = exit_pressure_ratio(4.0, 1.4)
    assert isp == pytest.approx(VALS["nozzle_cf_eff"] * ideal_isp(GASES["air"], 293.15, pe, 0.0, 4.0), rel=1e-9)


def test_ideal_isp_of_air_in_known_range():
    # infinite expansion: sqrt(2 cp T0)/g0 = 78 s; sea level from 30 bar, matched nozzle: 61.7 s
    g = GASES["air"]
    assert math.sqrt(2 * g.cp * 293.15) / G0 == pytest.approx(78.2, abs=0.3)
    assert ideal_isp(g, 293.15, 1 / 30) == pytest.approx(61.7, abs=0.1)


def test_adiabatic_real_gas_follows_isentrope_and_heat_transfer_lies_between():
    tk = TankConfig(thermal="adiabatic")
    s = ColdGasSystem(tk, ThrusterConfig())
    r = s.blowdown_ivp(n_out=50)
    t = real_gas("air")
    rho0 = s.m0 / s.V
    fr = np.array(r["m"]) / s.m0
    ok = np.array(r["valid"])
    p_is, T_is, _ = t.isentrope(300e5, 293.15, fr[ok])
    assert np.max(np.abs(np.array(r["T_tank"])[ok] - T_is)) < 1.5      # path independent: remaining gas is isentropic
    del rho0
    # heat-transfer case keeps the gas warmer than adiabatic, colder than isothermal, at equal remaining mass
    sh = ColdGasSystem(TankConfig(thermal="heat_transfer"), ThrusterConfig())
    rh = sh.blowdown_ivp(n_out=200)
    m_mid = 0.5 * s.m0
    T_ad = np.interp(m_mid, r["m"][::-1], r["T_tank"][::-1])
    T_ht = np.interp(m_mid, rh["m"][::-1], rh["T_tank"][::-1])
    assert T_ad < T_ht < 293.15


def test_regulated_thrust_constant_until_tank_reaches_set_point():
    s = ColdGasSystem(TankConfig(thermal="isothermal"), ThrusterConfig(reg_pressure_bar=30))
    r = s.blowdown_ivp(n_out=300)
    F = np.array(r["thrust"])
    p = np.array(r["p_tank"])
    hi = p > 40e5
    assert np.ptp(F[hi]) / F[hi].mean() < 1e-6
    assert F[p < 25e5].max() < F[hi].mean() * 0.99


def test_tank_mass_from_performance_factor_matches_published_tanks():
    v = coldgas_assumptions().values()
    mirai = TankConfig(volume_l=61.2, n_tanks=2, pressure_bar=700, tank_class="type4")
    assert tank_mass(mirai, v) == pytest.approx(87.5, rel=0.01)
    scba = TankConfig(volume_l=6.8, pressure_bar=300, tank_class="type3")
    assert 4.0 < tank_mass(scba, v) < 5.2


def test_energy_report_burst_and_refill():
    tk = TankConfig()
    er = energy_report(tk)
    g = GASES["air"]
    assert er.burst_energy_kj * 1e3 == pytest.approx(er.gas_mass_kg * g.cv * 293.15 * (1 - (101325 / 300e5) ** (0.4 / 1.4)), rel=1e-9)
    assert er.stored_exergy_kj > er.burst_energy_kj       # exergy (reversible work) exceeds the adiabatic expansion work
    # minimum work to fill = closed exergy; ideal-gas isothermal limit m R T (ln r - 1 + 1/r) (atmosphere does pa dV)
    r = 300e5 / 101325
    w_iso = er.gas_mass_kg * g.R * 293.15 * (math.log(r) - 1 + 1 / r)
    assert er.refill_min_work_kj * 1e3 == pytest.approx(w_iso, rel=0.05)
    # calibration: ~1.1 MJ/kg electrical when delivering at 300 bar; filling from empty averages lower pressures
    assert 0.7e6 < er.refill_electric_kwh * 3.6e6 / er.gas_mass_kg < 1.1e6
    assert blast_radius(1.0, 6.9e3) == pytest.approx(16.0, rel=0.25)   # 1 kg TNT reaches 1 psi at ~15-18 m


def test_rom_table_close_to_full_table():
    a = ColdGasSystem(TankConfig(), ThrusterConfig()).blowdown_ivp()
    b = ColdGasSystem(TankConfig(rom_table=True), ThrusterConfig()).blowdown_ivp()
    assert b["impulse"] == pytest.approx(a["impulse"], rel=0.01)
    assert b["mass_used"] == pytest.approx(a["mass_used"], rel=0.01)


def test_tau_definition():
    g = GASES["air"]
    assert tau0(0.01, 1e-5, g, 293.15) == pytest.approx(0.01 / (1e-5 * 0.6847 * math.sqrt(g.R * 293.15)), rel=1e-3)
