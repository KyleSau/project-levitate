import math

import numpy as np
import pytest

from levitate.ehd_board import EADDesign, evaluate_ead, wire_performance
from levitate.screening import ionic_wind
from levitate.solvers.ehd_bipolar import BipolarCoronaSolver, CoronaGeometry, coaxial_exact, peek_onset_field


def test_peek_field_magnitude():
    # 25 um wire: ~22 MV/m (well-known order for thin corona wires)
    assert 2.0e7 < peek_onset_field(25e-6) < 2.5e7


def test_laplace_wire_plane_matches_image_charge_solution():
    s = BipolarCoronaSolver(CoronaGeometry(r_wire=25e-6, gap=10e-3), 32, 64)
    phi = s.solve_poisson(np.zeros((s.N + 1, s.M)), 10e3)
    exact = 10e3 / (25e-6 * math.acosh(10e-3 / 25e-6))
    assert s.wire_field_mean(phi) == pytest.approx(exact, rel=1e-6)


def test_below_onset_no_corona():
    r = BipolarCoronaSolver(CoronaGeometry(r_wire=25e-6, gap=10e-3), 24, 48).solve(2e3)
    assert not r.corona_active and r.current_per_length == 0


@pytest.fixture(scope="module")
def coax_runs():
    g = CoronaGeometry(r_wire=50e-6, r_outer=10e-3, eccentricity=1e-5)
    exact, _ = coaxial_exact(12e3, 50e-6, 10e-3)
    return exact, [BipolarCoronaSolver(g, n, 2 * n).solve(12e3) for n in (24, 48)]


def test_coaxial_verification_converges_first_order(coax_runs):
    exact, (coarse, fine) = coax_runs
    e1 = abs(coarse.current_per_length / exact - 1)
    e2 = abs(fine.current_per_length / exact - 1)
    assert e2 < e1
    assert e1 / e2 == pytest.approx(2.0, rel=0.3)          # first-order upwind
    richardson = 2 * fine.current_per_length - coarse.current_per_length
    assert richardson == pytest.approx(exact, rel=0.02)


def test_current_conservation_and_kaptzov(coax_runs):
    _, runs = coax_runs
    for r in runs:
        assert r.current_conservation_error < 1e-5
        assert r.wire_field_mean == pytest.approx(r.onset_field, rel=1e-3)


def test_wire_plane_thrust_obeys_momentum_relation():
    r = BipolarCoronaSolver(CoronaGeometry(r_wire=25e-6, gap=10e-3), 48, 96).solve(12e3)
    kappa = r.thrust_per_length * 2.0e-4 / (r.current_per_length * 10e-3)
    assert 0.8 < kappa < 1.0               # T ~ I d / mu
    assert abs(r.force_per_length[1]) < 1e-6 * abs(r.force_per_length[0])   # symmetric: no lateral force
    # thrust/power in the published 1-10 N/kW band for wire emitters
    assert 1.0 < r.thrust_to_power * 1000 < 10.0


def test_surrogate_matches_heldout_solver():
    D, rw, V = 10e-3, 25e-6, 12e3
    w = wire_performance(V, D, rw, 2e-4, 1.5 * D)
    r = BipolarCoronaSolver(CoronaGeometry(r_wire=rw, gap=D), 48, 96).solve(V)
    assert w["T"] == pytest.approx(r.thrust_per_length, rel=0.05)
    assert w["I"] == pytest.approx(r.current_per_length, rel=0.05)


def test_ead_board_cannot_hover():
    rep = evaluate_ead(EADDesign(n_stages=3, gap_mm=10, voltage_kv=8))
    assert rep.verdict == "INFEASIBLE"
    assert rep.scenarios["optimistic"].thrust_to_weight < 0.5
    for sc in rep.scenarios.values():
        # numerical thrust never exceeds the analytical space-charge-limited upper bound
        assert sc.thrust_n <= sc.scl_upper_bound_thrust_n * 1.05


def test_analytical_bound_rules_out_single_stage():
    r = ionic_wind()
    assert r.numbers["field_needed_single_stage_v_m"] > 3.0e6     # above air breakdown
