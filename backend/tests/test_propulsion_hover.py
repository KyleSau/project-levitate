"""Validation of the 6-DOF thrust-borne hoverboard model (cold gas and black-box rocket)."""
import math

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from levitate.constants import G0, RHO_AIR_SL
from levitate.propulsion.coldgas import TankConfig
from levitate.propulsion.hover import HoverConfig, HoverSim, MissionConfig, evaluate_hover
from levitate.propulsion.rocket import RocketEngineConfig


def test_free_fall_with_drag_matches_solve_ivp():
    cfg = HoverConfig(propulsion="rocket", start_height_m=60.0)
    sim = HoverSim(cfg)
    sim.reset()
    sim.phase = "done"
    m = sim.mass_props()[0]
    k = 0.5 * RHO_AIR_SL * sim.cda / m
    z0 = sim.pos[2]
    for _ in range(2500):
        sim.step(cfg.dt)
    ref = solve_ivp(lambda t, y: [y[1], -G0 - k * y[1] * abs(y[1])], (0, 2.5), [z0, 0.0], rtol=1e-10, atol=1e-10)
    assert sim.pos[2] == pytest.approx(ref.y[0, -1], abs=0.03)          # first-order Euler, dt = 1 ms
    assert sim.tel["vel"][2] == pytest.approx(ref.y[1, -1], rel=2e-3)


def test_variable_mass_rocket_equation_6dof():
    cfg = HoverConfig(propulsion="rocket", gravity=0.0, drag=False, cant_deg=0.0, start_height_m=5.0, reserve_s=0.0,
                      tank_x_m=0.0)
    sim = HoverSim(cfg)
    sim.reset()
    sim._control = lambda *a: ([1.0] * 4, True)
    m0 = sim.mass_props()[0]
    dv = 0.0
    for _ in range(3000):
        m = sim.mass_props()[0]
        sim.step(cfg.dt)
        dv += sum(sim.tel["F"]) / m * cfg.dt
    m1 = sim.mass_props()[0]
    ex = sim.rules.isp_s * G0 * math.log(m0 / m1)
    assert dv == pytest.approx(ex, rel=1e-3)
    assert ex * 0.95 < np.linalg.norm(sim.tel["vel"]) <= ex * 1.0001
    # impulse = propellant used x effective exhaust velocity
    assert sim.impulse == pytest.approx(sim.used * sim.rules.isp_s * G0, rel=1e-9)


def test_hover_time_matches_constant_tw_analytic():
    """Hold a hover until the propellant is gone: t = Isp cos(cant) ln(m0/m1) for T = W / cos(cant)."""
    cfg = HoverConfig(propulsion="rocket", reserve_s=0.0, tank_x_m=0.0,
                      mission=MissionConfig(hold_s=600.0, hover_height_m=0.5), engine=RocketEngineConfig(propellant_kg=6.0))
    sim = HoverSim(cfg)
    m0 = sim.mass_props()[0]
    sim.run(t_end=120.0)
    assert sim.ran_dry and sim.t_liftoff is not None
    m1 = m0 - 6.0
    t_an = sim.rules.isp_s * math.cos(math.radians(cfg.cant_deg)) * math.log(m0 / m1)
    # engines start at t = 0.5 s and run below hover thrust until lift-off, so the analytic hover time must lie
    # between (burn-out - lift-off) and (burn-out - engine start)
    assert sim.t_burnout - sim.t_liftoff < t_an < sim.t_burnout - 0.5
    assert sim.t_burnout - 0.5 == pytest.approx(t_an, rel=0.03)


def test_cg_shift_with_propellant_use():
    cfg = HoverConfig(propulsion="rocket")
    sim = HoverSim(cfg)
    m0, cg0, _ = sim.mass_props()
    sim.prop -= 10.0
    m1, cg1, _ = sim.mass_props()
    tpos = np.array([cfg.tank_x_m, 0.0, cfg.tank_z_m])
    expect = (m0 * np.array(cg0) - 10.0 * tpos) / (m0 - 10.0)
    assert np.allclose(cg1, expect, atol=1e-12)
    assert cg1[0] < cg0[0] and cg1[2] > cg0[2]        # tank is forward and below the CG


def test_rocket_mission_completes():
    r = evaluate_hover(HoverConfig(propulsion="rocket"))
    assert r.mission_completed and r.failed is None
    assert r.max_tilt_deg < 20
    assert [e for _, e in r.events][-1] == "done"


def test_coldgas_board_aborts_on_reserve_and_lands():
    r = evaluate_hover(HoverConfig())
    assert r.aborted and r.failed is None
    assert r.flight_time_s < r.hover_time_analytic_s
    assert r.hover_time_analytic_s < r.hover_time_upper_bound_s


def test_coldgas_without_reserve_runs_dry_and_falls():
    r = evaluate_hover(HoverConfig(reserve_s=0.0, mission=MissionConfig(hover_height_m=1.5, hold_s=30)))
    assert r.failed and "dry" in r.failed
    assert r.impact_speed_m_s > 1.0


def test_insufficient_thrust_cannot_lift_off():
    r = evaluate_hover(HoverConfig(tw_design=0.9))
    assert r.failed and "lift off" in r.failed


def test_solid_motor_cannot_hover():
    r = evaluate_hover(HoverConfig(propulsion="rocket", engine=RocketEngineConfig(engine_class="solid", propellant_kg=10)))
    assert not r.mission_completed
    assert any("solid" in w for w in r.warnings)


def test_min_throttle_above_hover_point_prevents_hover():
    r = evaluate_hover(HoverConfig(propulsion="rocket", engine=RocketEngineConfig(engine_class="biprop", propellant_kg=20,
                                                                                  min_throttle_override=0.95)))
    assert not r.mission_completed


def test_coldgas_upper_bound_is_independent_of_size():
    """With tank mass proportional to gas mass (k = tank kg per gas kg), hover time can never exceed
    Isp cos(cant) ln((1+k)/k), however large the tanks."""
    a = evaluate_hover(HoverConfig(tank=TankConfig(volume_l=9, n_tanks=4)), run=False)
    b = evaluate_hover(HoverConfig(tank=TankConfig(volume_l=50, n_tanks=4)), run=False)
    assert a.hover_time_upper_bound_s == pytest.approx(b.hover_time_upper_bound_s, rel=0.03)
    assert b.hover_time_analytic_s < b.hover_time_upper_bound_s
