"""Ground contact behaviour and numerical convergence of the fixed-step integrator."""
import math

import numpy as np
import pytest
from conftest import air_state, make_plant

from vlab import quat
from vlab.offline import integrate_open_loop
from vlab.vehicle import scale_total_mass, default_vehicle


def _corner_min_z(p, x):
    return float((x[2] + (p.corners @ quat.to_rot(x[6:10]).T)[:, 2]).min())


@pytest.mark.parametrize("mass", [0.020, 0.120])
def test_drop_landing_no_penetration_no_bounce(mass):
    p = make_plant(vehicle=scale_total_mass(default_vehicle(), mass))
    h_cg = p.cg[2] + p.rm.vehicle.height_m / 2
    x = air_state(p, z=h_cg + 0.05)             # drop from 5 cm clearance
    v_impact = math.sqrt(2 * 9.80665 * 0.05)
    u = np.zeros(p.n)
    min_z, max_rebound, z_prev, after_contact = 0.0, 0.0, x[2], False
    for k in range(3000):                        # 3 s
        x = p.step(x, u, np.zeros(3), 1e-3)
        cz = _corner_min_z(p, x)
        min_z = min(min_z, cz)
        if cz < 0:
            after_contact = True
        elif after_contact:
            max_rebound = max(max_rebound, cz)
        assert abs(x[2] - z_prev) <= 1.5 * v_impact * 1e-3 + 1e-9, "no teleporting"
        z_prev = x[2]
    # compliant pads, k = 4 kN/m total at 20 g: peak compression ~1.2 mm after a 1 m/s (5 cm) drop
    assert min_z > -2.0e-3, f"penetration {min_z*1e3:.3f} mm"
    assert max_rebound < 2e-3, f"rebound {max_rebound*1e3:.3f} mm (restitution must be small)"
    sag = p.m * p.g / (4 * p.kc)
    assert _corner_min_z(p, x) == pytest.approx(-sag, rel=0.05), "rests at static contact equilibrium"
    assert np.linalg.norm(x[3:6]) < 1e-4
    wr = p.wrench(x, np.zeros(3))
    assert wr["contact_N"] == pytest.approx(p.m * p.g, rel=1e-3), "ground carries the weight at rest"


def test_resting_board_is_static():
    p = make_plant()
    x = p.rest_state()
    for _ in range(2000):
        x = p.step(x, np.zeros(p.n), np.zeros(3), 1e-3)
    assert np.abs(x[3:6]).max() < 1e-9
    assert abs(x[2] - p.rest_state()[2]) < 1e-9


def test_rk4_fourth_order_convergence_torque_free():
    from vlab.vehicle import set_cg
    p = make_plant(vehicle=set_cg(default_vehicle(), (0.004, 0.0015, 0.0002)), g=0.0)
    x0 = air_state(p, z=10.0, w=(6.0, -2.0, 4.0))
    T = 2.0
    ref = integrate_open_loop(p, x0, np.zeros(p.n), T, rtol=1e-13, atol=1e-15).y[:, -1]
    dts = [8e-3, 4e-3, 2e-3, 1e-3]
    errs = []
    for dt in dts:
        x = x0.copy()
        for _ in range(int(round(T / dt))):
            x = p.rk4_step(x, np.zeros(p.n), np.zeros(3), dt)
        errs.append(np.linalg.norm(x[6:13] - ref[6:13]))
    orders = [math.log2(errs[i] / errs[i + 1]) for i in range(len(errs) - 1)]
    assert all(3.5 < o < 4.6 for o in orders), (errs, orders)


def test_rk4_vs_dop853_with_drag_and_thrust():
    p = make_plant(drag=True)
    u = np.linalg.pinv(p.B[[2, 3, 4, 5]]) @ np.array([1.2 * p.m * p.g, 1e-6, -1e-6, 3e-7])  # moderate (non-chaotic) rotation
    x0 = air_state(p, z=1.0, v=(0.5, -0.2, 0.0))
    x0[13:13 + p.n] = u
    T = 1.0
    ref = integrate_open_loop(p, x0, u, T).y[:, -1]
    x = x0.copy()
    for _ in range(1000):
        x = p.step(x, u, np.zeros(3), 1e-3)
    assert np.linalg.norm(x[0:3] - ref[0:3]) < 1e-9
    assert np.linalg.norm(x[6:10] - ref[6:10]) < 1e-9


def test_landing_at_descent_rate_penetrates_less_than_0p3mm():
    p = make_plant()
    h_cg = p.cg[2] + p.rm.vehicle.height_m / 2
    x = air_state(p, z=h_cg + 0.0005, v=(0, 0, -0.12))
    min_z = 0.0
    for _ in range(500):
        x = p.step(x, np.zeros(p.n), np.zeros(3), 1e-3)
        min_z = min(min_z, _corner_min_z(p, x))
    assert min_z > -3e-4


@pytest.mark.parametrize("mass,cg", [(0.020, None), (0.120, None), (0.020, (0.008, 0.002, 0.0))])
def test_contact_modes_inside_rk4_stability_region(mass, cg):
    """Every eigenvalue of the linearised resting contact system, times the sub-step actually used,
    must have RK4 amplification |R(z)| <= 1 (no numerical energy injection / spurious bouncing)."""
    from vlab.vehicle import set_cg
    v = scale_total_mass(default_vehicle(), mass)
    if cg:
        v = set_cg(v, cg)
    p = make_plant(vehicle=v)
    x0 = p.rest_state()
    h = 1e-3 / p.substeps(x0, 1e-3)
    f0 = p.deriv(x0, np.zeros(p.n), np.zeros(3))[:13]
    Jac = np.zeros((13, 13))
    for i in range(13):
        x = x0.copy()
        x[i] += 1e-7
        Jac[:, i] = (p.deriv(x, np.zeros(p.n), np.zeros(3))[:13] - f0) / 1e-7
    z = np.linalg.eigvals(Jac) * h
    R = np.abs(1 + z + z**2 / 2 + z**3 / 6 + z**4 / 24)
    assert R.max() <= 1.0 + 1e-6
