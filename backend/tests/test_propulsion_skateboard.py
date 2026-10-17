"""Validation of the boosted-skateboard model: closed forms, variable-mass Newton, energy closure, no free energy."""
import math

import pytest

from levitate.constants import G0, RHO_AIR_SL
from levitate.propulsion.coldgas import TankConfig, ThrusterConfig
from levitate.propulsion.skateboard import Controls, SkateConfig, SkateSim, default_scenario, evaluate_skateboard


def _coast(sim, v0, t_end):
    sim.reset()
    sim.v = v0
    sim.ctl = Controls()
    t = 0.0
    while t < t_end and sim.v > 0:
        sim.step(sim.cfg.dt)
        t += sim.cfg.dt
    return t


def test_rolling_resistance_coast_down_closed_form():
    sim = SkateSim(SkateConfig(coldgas=False, electric=False, overrides={"cda_upright": 0.0}))
    t = _coast(sim, 8.0, 200.0)
    assert t == pytest.approx(8.0 / (sim.v_sk["crr"] * G0), rel=1e-3)


def test_drag_decay_closed_form():
    sim = SkateSim(SkateConfig(coldgas=False, electric=False, overrides={"crr": 0.0}))
    m = sim.mass_props()[0]
    _coast(sim, 10.0, 10.0)
    k = RHO_AIR_SL * sim.v_sk["cda_upright"] / (2 * m)
    assert sim.v == pytest.approx(10.0 / (1 + k * 10.0 * 10.0), rel=1e-3)


def test_rocket_equation_variable_mass():
    """Frictionless, drag-free board pushed by an isothermal ideal-gas thruster in vacuum-like constant-Isp mode:
    delta-v must equal ue ln(m0/m1) (Tsiolkovsky) for the integrated variable-mass Newton's law."""
    cfg = SkateConfig(electric=False, overrides={"crr": 0.0, "cda_upright": 0.0, "rider_heel_lever_m": 5.0},
                      tank=TankConfig(real_gas=False, thermal="isothermal", volume_l=20, pressure_bar=200),
                      thruster=ThrusterConfig(regulated=False, ambient_pa=0.0, throat_diameter_mm=4.0),
                      thrust_height_m=0.9, tank_h_m=0.9, boost_ramp_s=0.0, dt=0.0005)
    sim = SkateSim(cfg)
    sim.reset()
    m0 = sim.mass_props()[0]
    sim.ctl = Controls(boost=True)
    ue = None
    for _ in range(int(4.0 / cfg.dt)):
        tel = sim.step(cfg.dt)
        if ue is None and tel["mdot"] > 0:
            ue = tel["thrust"] / tel["mdot"]
    m1 = sim.mass_props()[0]
    assert sim.v == pytest.approx(ue * math.log(m0 / m1), rel=2e-3)


def test_energy_ledger_closes_default_scenario():
    r = evaluate_skateboard(SkateConfig())
    L = r.energy_ledger
    assert abs(L["rel_residual"]) < 1e-4
    assert abs(r.no_boost_ledger["rel_residual"]) < 1e-4


def test_boost_creates_no_energy():
    cfg = SkateConfig(electric=False)
    sim = SkateSim(cfg)
    rec = sim.run([(0.0, Controls(boost=True))], 15.0)
    L = rec["ledger"]
    assert L["jet_ke"] > 0
    assert L["jet_ke"] <= L["exergy_used"]                 # jet energy bounded by the exergy drawn from the tank
    useful = L["ke1"] + L["drag"] + L["roll"]
    assert useful <= L["jet_ke"]                           # vehicle gets less than the jet carries
    assert abs(L["rel_residual"]) < 1e-4
    # propulsive efficiency at skateboard speeds is tiny: thrust work / jet KE ~ 2 v / ue
    assert L["thrust_work"] / L["jet_ke"] < 0.1


def test_speed_gain_bounded_by_stored_energy():
    r = evaluate_skateboard(SkateConfig())
    m = r.total_mass_kg
    e_max = r.hazards["tank"]["stored_exergy_kj"] * 1e3
    v_bound = math.sqrt(r.max_speed_no_boost_m_s ** 2 + 2 * e_max / m)
    assert 0 < r.speed_gain_m_s and r.max_speed_m_s < v_bound


def test_cg_shift_as_gas_depletes():
    cfg = SkateConfig(electric=False)
    sim = SkateSim(cfg)
    sim.reset()
    m0, x0, _, parts = sim.mass_props()
    mg0 = sim.gas_sys.m
    sim.ctl = Controls(boost=True)
    for _ in range(3000):
        sim.step(cfg.dt)
    m1, x1, _, _ = sim.mass_props()
    dm = mg0 - sim.gas_sys.m
    # removing dm at the tank position moves the CG away from the tank: x1 = (m0 x0 - dm x_tank) / (m0 - dm)
    expect = (m0 * x0 - dm * cfg.tank_x_m) / (m0 - dm)
    # rider lean changes during the boost too; compare with the rider lean contribution removed
    lean_shift = cfg.rider_kg * sim.l * math.sin(sim.theta) / m1
    assert x1 - lean_shift == pytest.approx(expect, abs=2e-4)
    assert x1 - lean_shift > x0


def test_surprised_rider_falls_anticipating_rider_does_not():
    sc = [(0.0, Controls(throttle=1.0)), (3.0, Controls(throttle=1.0, boost=True))]
    ok = evaluate_skateboard(SkateConfig(), sc, t_end=8.0)
    surprised = evaluate_skateboard(SkateConfig(rider_anticipates=False, boost_ramp_s=0.0), sc, t_end=8.0)
    assert not ok.flags["rider_fell"]
    assert surprised.flags["rider_fell"]


def test_thrust_line_height_controls_pitch_load_transfer():
    def nf(h):
        cfg = SkateConfig(electric=False, thrust_height_m=h)
        sim = SkateSim(cfg)
        sim.reset()
        sim.ctl = Controls(boost=True)
        for _ in range(1500):
            tel = sim.step(cfg.dt)
        return tel["Nf"], tel
    lo, _ = nf(0.05)
    hi, tel = nf(1.5)
    assert hi > lo                       # thrust above the CG loads the nose, below it unloads it
    Tx = tel["Tx"]
    # difference in front load equals Tx (h_hi - h_lo) / L (other terms are identical)
    assert hi - lo == pytest.approx(Tx * (1.5 - 0.05) / 0.6, rel=0.05)


def test_default_boost_feasible_and_reported():
    r = evaluate_skateboard(SkateConfig())
    assert r.feasible
    assert r.boost_duration_s > 5
    assert 40 < r.mean_isp_s < 62
    assert r.speed_gain_m_s > 1.0
    assert any("burst" in w for w in r.warnings)


def test_harder_braking_noses_over():
    sc = default_scenario(True)
    sc[-1] = (17.0, Controls(brake=0.6))
    r = evaluate_skateboard(SkateConfig(), sc)
    assert r.flags["noseover"] or r.flags["rider_fell"]
