"""Validation of the 6-DOF plant against closed-form solutions (no controller involved)."""
import math

import numpy as np
import pytest
from conftest import air_state, make_plant

from vlab import quat
from vlab.constants import G0
from vlab.offline import integrate_open_loop, rk4_open_loop
from vlab.vehicle import default_vehicle, set_cg


def hover_u(p, scale=1.0):
    return np.linalg.pinv(p.B[[2, 3, 4, 5]]) @ np.array([p.m * p.g * scale, 0, 0, 0])


def test_weight_of_20g_board():
    p = make_plant()
    assert p.m == pytest.approx(0.020, abs=1e-15)
    assert p.m * p.g == pytest.approx(0.1961330, abs=1e-7)
    assert G0 == 9.80665


def test_free_fall_rk4_and_dop853():
    p = make_plant()
    x0 = air_state(p, z=20.0)
    u = np.zeros(p.n)
    T = 1.5
    z_exact = 20.0 - 0.5 * G0 * T ** 2
    x = rk4_open_loop(p, x0, u, T, 1e-3)
    assert x[2] == pytest.approx(z_exact, abs=1e-10)
    assert x[5] == pytest.approx(-G0 * T, abs=1e-10)
    sol = integrate_open_loop(p, x0, u, T)
    assert sol.y[2, -1] == pytest.approx(z_exact, abs=1e-9)


def test_constant_acceleration_from_upward_force():
    p = make_plant()
    a = 1.7
    u = hover_u(p) * (1 + a / G0)
    x0 = air_state(p, z=1.0)
    x0[13:13 + p.n] = u
    T = 2.0
    x = rk4_open_loop(p, x0, u, T, 1e-3)
    assert x[2] == pytest.approx(1.0 + 0.5 * a * T * T, rel=1e-10)
    assert x[5] == pytest.approx(a * T, rel=1e-10)
    assert np.abs(x[10:13]).max() < 1e-9, "balanced allocation must create no torque"


def test_exactly_balancing_force_gives_hover_equilibrium():
    p = make_plant()
    u = hover_u(p)
    x0 = air_state(p, z=0.3)
    x0[13:13 + p.n] = u
    wr = p.wrench(x0, np.zeros(3))
    assert np.abs(wr["F_net_w"]).max() < 1e-15
    assert np.abs(wr["tau_net_b"]).max() < 1e-16          # machine precision (torques ~1e-3 N m)
    assert wr["F_act_w"][2] == pytest.approx(0.196133, abs=1e-6)
    x = rk4_open_loop(p, x0, u, 5.0, 1e-3)
    # residual drift is floating-point round-off (torque ~4e-18 N m) only
    assert np.abs(x[0:3] - x0[0:3]).max() < 1e-8
    assert np.abs(x[3:6]).max() < 1e-8


def test_insufficient_thrust_loses_altitude():
    p = make_plant()
    u = hover_u(p, 0.95)
    x0 = air_state(p, z=1.0)
    x0[13:13 + p.n] = u
    x = rk4_open_loop(p, x0, u, 1.0, 1e-3)
    a = -0.05 * G0
    assert x[2] == pytest.approx(1.0 + 0.5 * a, rel=1e-9)
    assert x[2] < 1.0


def test_forward_acceleration_equals_F_over_m():
    p = make_plant()
    F = 0.01
    x0 = air_state(p, z=1.0)
    u = hover_u(p)
    x0[13:13 + p.n] = u
    x = rk4_open_loop(p, x0, u, 1.0, 1e-3, f_ext=(F, 0, 0))
    assert x[3] == pytest.approx(F / p.m * 1.0, rel=1e-10)
    assert x[0] == pytest.approx(0.5 * F / p.m, rel=1e-10)


def test_tilted_thrust_gives_g_tan_theta():
    p = make_plant()
    th = math.radians(10)
    q = quat.from_axis_angle((0, 1, 0), th)       # pitch nose-down about +y -> thrust tilts toward +x
    u = hover_u(p) / math.cos(th)
    x0 = air_state(p, z=1.0, q=q)
    x0[13:13 + p.n] = u
    d = p.deriv(x0, u, np.zeros(3))
    assert d[3] == pytest.approx(G0 * math.tan(th), rel=1e-12)
    assert d[5] == pytest.approx(0.0, abs=1e-12)


def test_removing_forward_thrust_keeps_velocity_no_drag():
    p = make_plant(drag=False)
    u = hover_u(p)
    x = air_state(p, z=1.0)
    x[13:13 + p.n] = u
    for _ in range(500):
        x = p.rk4_step(x, u, np.array([0.01, 0, 0]), 1e-3)
    v_after = x[3]
    assert v_after == pytest.approx(0.25, rel=1e-9)
    for _ in range(2000):
        x = p.rk4_step(x, u, np.zeros(3), 1e-3)
    assert x[3] == pytest.approx(v_after, rel=1e-9), "momentum must persist when the command is removed"


def test_quadratic_drag_decay_matches_analytic():
    """m dv/dt = -k v|v|  ->  v(t) = v0 / (1 + k v0 t / m)."""
    p = make_plant(drag=True)
    u = hover_u(p)
    v0 = 2.0
    x = air_state(p, z=5.0, v=(v0, 0, 0))
    x[13:13 + p.n] = u
    T = 3.0
    x = rk4_open_loop(p, x, u, T, 1e-3)
    k = p.kd[0]
    assert x[3] == pytest.approx(v0 / (1 + k * v0 * T / p.m), rel=1e-9)
    assert 0 < x[3] < v0


def _asymmetric_plant():
    v = set_cg(default_vehicle(), (0.004, 0.0015, 0.0002))
    p = make_plant(vehicle=v, g=0.0)
    J = p.J
    assert abs(J[0, 1]) > 0 and abs(J[0, 2]) > 0, "CG offset must create products of inertia"
    return p


def test_torque_free_conserves_angular_momentum_and_energy():
    p = _asymmetric_plant()
    w0 = np.array([3.0, -1.0, 2.0])
    x0 = air_state(p, z=10.0, w=w0)
    L0 = p.angular_momentum_world(x0)
    E0 = p.energy(x0)[0]
    u = np.zeros(p.n)
    x = x0.copy()
    for _ in range(5000):
        x = p.rk4_step(x, u, np.zeros(3), 1e-3)
    L = p.angular_momentum_world(x)
    assert np.linalg.norm(L - L0) / np.linalg.norm(L0) < 1e-8
    assert abs(p.energy(x)[0] - E0) / E0 < 1e-8
    assert np.linalg.norm(x[10:13] - w0) > 0.1, "asymmetric body must precess (omega changes in body frame)"
    sol = integrate_open_loop(p, x0, u, 5.0, rtol=1e-11, atol=1e-13)
    xs = sol.y[:, -1]
    assert np.linalg.norm(p.angular_momentum_world(xs) - L0) / np.linalg.norm(L0) < 1e-8


def test_constant_torque_about_principal_axis():
    """Torque along a principal axis e (eigenvector of J): omega = tau/I_e t e, angle = tau t^2 / (2 I_e)."""
    p = make_plant(g=0.0)
    J = p.J
    assert abs(J[0, 1]) > 0, "staggered actuator layout gives a real product of inertia J_xy"
    ev, V = np.linalg.eigh(J)
    for k in range(3):
        e = V[:, k]
        tau = 2e-6
        p.tau_ext_b = tau * e
        x = air_state(p, z=10.0)
        T = 1.0
        x = rk4_open_loop(p, x, np.zeros(p.n), T, 1e-3)
        np.testing.assert_allclose(x[10:13], tau / ev[k] * T * e, rtol=1e-9, atol=1e-12)
        qv = x[6:10]
        angle = 2 * math.atan2(np.linalg.norm(qv[1:]), qv[0])
        assert angle == pytest.approx(0.5 * tau / ev[k] * T * T, rel=1e-8)
        np.testing.assert_allclose(qv[1:] / np.linalg.norm(qv[1:]), e * np.sign(qv[1:] @ e), atol=1e-9)


def test_rotation_responds_to_inertia_tensor():
    p1 = make_plant(g=0.0)
    p2 = make_plant(vehicle=set_cg(default_vehicle(), (0.005, 0.002, 0.0)), g=0.0)
    tau = np.array([1e-6, 0.0, 0.0])
    for p in (p1, p2):
        p.tau_ext_b = tau
        x = air_state(p, z=10.0)
        d = p.deriv(x, np.zeros(p.n), np.zeros(3))
        np.testing.assert_allclose(d[10:13], np.linalg.solve(p.J, tau), rtol=1e-12, atol=1e-18)
    a1 = make_plant(g=0.0)
    a1.tau_ext_b = tau
    d1 = a1.deriv(air_state(a1, z=10.0), np.zeros(a1.n), np.zeros(3))
    # doubling the mass (same distribution) doubles inertia and halves angular acceleration
    from vlab.vehicle import scale_total_mass
    a2 = make_plant(vehicle=scale_total_mass(default_vehicle(), 0.040), g=0.0)
    a2.tau_ext_b = tau
    d2 = a2.deriv(air_state(a2, z=10.0), np.zeros(a2.n), np.zeros(3))
    assert d2[10] == pytest.approx(d1[10] / 2, rel=1e-12)
    # off-diagonal inertia couples axes: roll torque on the offset-CG body produces some yaw/pitch acceleration
    p2.tau_ext_b = tau
    d = p2.deriv(air_state(p2, z=10.0), np.zeros(p2.n), np.zeros(3))
    assert abs(d[11]) + abs(d[12]) > 0


def test_actuator_differential_force_rolls_vehicle():
    """Torque from actuator geometry: tau = r x F about the CG produces roll acceleration J^-1 tau."""
    p = make_plant(g=0.0)
    u = np.zeros(p.n)
    u[0] = 0.01                                   # A0 at +y: positive roll torque y*F
    x = air_state(p, z=10.0)
    x[13:13 + p.n] = u                            # instantaneous actuators: force state = command
    d = p.deriv(x, u, np.zeros(3))
    tau = p.B[3:6] @ u
    assert tau[0] == pytest.approx(p.r_act[0][1] * 0.01, rel=1e-12)
    np.testing.assert_allclose(d[10:13], np.linalg.solve(p.J, tau - np.zeros(3)), rtol=1e-12)


def test_quaternion_stays_normalised():
    p = _asymmetric_plant()
    x = air_state(p, z=10.0, w=(20.0, -7.0, 11.0))
    for _ in range(3000):
        x = p.rk4_step(x, np.zeros(p.n), np.zeros(3), 2e-3)
        assert abs(np.linalg.norm(x[6:10]) - 1) < 1e-14
