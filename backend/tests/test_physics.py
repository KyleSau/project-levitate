import math

import numpy as np
import pytest

from levitate.constants import G0, RHO_AIR_SL
from levitate.design import Design, allocation_matrix, rotor_layout
from levitate.physics import battery, rotor
from levitate.physics.mass import build_mass_budget
from levitate.catalog import global_assumptions


def test_ideal_induced_power_matches_momentum_theory():
    T, D = 0.3, 0.05
    A = math.pi * (D / 2) ** 2
    expected = T ** 1.5 / math.sqrt(2 * RHO_AIR_SL * A)
    # FM=1, no duct, out of ground effect, Re correction neutralised by inverting with same FM
    p = rotor.hover_shaft_power(T, D, fm=1.0, duct_factor=1.0, height_m=100.0)
    fm_eff = rotor.fm_at_reynolds(1.0, rotor.blade_reynolds(T, D))
    assert p == pytest.approx(expected / fm_eff, rel=1e-6)   # ground effect at 100 m is 1 + O(1e-8)


def test_ideal_duct_saves_29_percent():
    assert rotor.duct_power_factor(True, 1.0) == pytest.approx(1 / math.sqrt(2))
    assert rotor.duct_power_factor(False, 1.0) == 1.0


def test_ground_effect_limits():
    assert rotor.ground_effect_thrust_ratio(0.01, 10.0) == pytest.approx(1.0, abs=1e-6)
    # Cheeseman-Bennett at z = R: 1/(1-1/16)
    assert rotor.ground_effect_thrust_ratio(0.01, 0.01) == pytest.approx(16 / 15)


def test_max_thrust_inverts_power():
    D, fm, kd = 0.022, 0.42, 0.85
    for T in (0.05, 0.1, 0.3):
        p = rotor.hover_shaft_power(T, D, fm, kd, height_m=100)
        assert rotor.max_thrust_from_shaft_power(p, D, fm, kd) == pytest.approx(T, rel=1e-4)


def test_battery_operating_point_power_balance():
    op = battery.operating_point(7.0, 1, 0.15, 300)
    assert op.feasible
    assert op.terminal_v * op.current_a == pytest.approx(7.0, rel=1e-9)
    assert op.heat_w == pytest.approx(op.current_a ** 2 * 0.15)
    assert not battery.operating_point(1000.0, 1, 0.15, 300).feasible


def test_mass_budget_consistency():
    d = Design()
    lay = rotor_layout(d)
    mb = build_mass_budget(d, lay, global_assumptions().values())
    assert mb.total_g == pytest.approx(sum(i.mass_g for i in mb.items))
    assert mb.total_g == pytest.approx(sum(mb.by_group_g.values()))
    J = np.array(mb.inertia_kgm2)
    assert np.allclose(J, J.T)
    ev = np.linalg.eigvalsh(J)
    assert np.all(ev > 0)
    # triangle inequality for principal moments of a physical body
    assert ev[0] + ev[1] >= ev[2] * (1 - 1e-9)
    # a long thin board: yaw >= pitch >> roll
    assert J[2, 2] > J[0, 0] and J[1, 1] > J[0, 0]


def test_inline_layout_is_uncontrollable_in_roll():
    d = Design(layout="inline", rotor_diameter_mm=20)
    lay = rotor_layout(d)
    B = allocation_matrix(lay.positions_m, lay.spins, 0.006)
    assert np.linalg.matrix_rank(B) < 4


def test_staggered_layout_spin_pattern_full_rank_and_balanced():
    d = Design(rotor_diameter_mm=20, lateral_offset_mm=3.5)
    lay = rotor_layout(d)
    assert lay.fits, lay.fit_issues
    assert sum(lay.spins) == 0
    assert np.linalg.matrix_rank(allocation_matrix(lay.positions_m, lay.spins, 0.006)) == 4


def test_geometry_rejects_oversize_rotor():
    lay = rotor_layout(Design(rotor_diameter_mm=40, width_mm=32))
    assert not lay.fits


def test_weight_of_20g():
    assert 0.020 * G0 == pytest.approx(0.196, abs=5e-4)
