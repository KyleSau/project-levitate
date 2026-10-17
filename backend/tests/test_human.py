import math

import pytest

from levitate.constants import G0, RHO_AIR_SL
from levitate.db import ExperimentDB
from levitate.human_scale import HumanDesign, evaluate_human, min_area_for_jet_velocity
from levitate.optimize import HumanStudyConfig, run_human_study


def test_jet_velocity_is_momentum_flux_identity():
    d = HumanDesign(concept="ducted_electric", lift_area_m2=4.0, exit_area_ratio=1.2)
    n = evaluate_human(d).scenarios["nominal"]
    W = n.gross_kg * G0
    assert n.jet_velocity_m_s == pytest.approx(math.sqrt(W / (RHO_AIR_SL * 4.0 * 1.2)))
    # inverse: the area that gives this velocity is the area we used
    assert min_area_for_jet_velocity(n.gross_kg, n.jet_velocity_m_s, True, 1.2) == pytest.approx(4.0)


def test_board_sized_battery_electric_does_not_close():
    for c in ("ducted_electric", "open_rotor_electric"):
        assert evaluate_human(HumanDesign(concept=c, lift_area_m2=0.4)).verdict == "DOES_NOT_CLOSE"


def test_large_area_electric_closes_with_lower_downwash():
    small = evaluate_human(HumanDesign(concept="ducted_electric", lift_area_m2=2.0)).scenarios["nominal"]
    big = evaluate_human(HumanDesign(concept="ducted_electric", lift_area_m2=8.0)).scenarios["nominal"]
    assert small.closes and big.closes
    assert big.jet_velocity_m_s < small.jet_velocity_m_s
    assert big.hover_power_kw / big.gross_kg < small.hover_power_kw / small.gross_kg


def test_turbojet_closes_at_board_size_with_jet_blast():
    n = evaluate_human(HumanDesign(concept="turbojet", n_units=6)).scenarios["nominal"]
    assert n.closes and 120 < n.gross_kg < 300           # Flyboard-Air-class vehicle
    assert n.debris.startswith("severe")


def test_air_cushion_board_closes_on_asphalt_and_needs_little_power():
    r = evaluate_human(HumanDesign(concept="air_cushion", lift_area_m2=1.2, surface_roughness_mm=3, mission_min=20))
    assert r.verdict == "CLOSES"
    n = r.scenarios["nominal"]
    assert n.hover_power_kw < 10 and n.form.startswith("platform") is False or n.footprint_m2 < 1.5
    rough = evaluate_human(HumanDesign(concept="air_cushion", lift_area_m2=1.2, surface_roughness_mm=30, mission_min=20))
    assert rough.scenarios["nominal"].hover_power_kw > 3 * n.hover_power_kw     # leakage grows with gap


def test_leaf_blower_hovercraft_order_of_magnitude():
    # classic demo: ~1.13 m^2 disc, ~95 kg with rider, plastic skirt ~2 mm on a smooth floor; leaf blowers deliver
    # a few hundred watts of air power. Model air power p*Q must be of that order.
    W, A, perim, h = 95 * G0, 1.13, 3.77, 0.002
    p = W / A
    q = 0.6 * perim * h * math.sqrt(2 * p / RHO_AIR_SL)
    assert 50 < p * q < 500


def test_human_study_runs(tmp_path):
    r = run_human_study(ExperimentDB(tmp_path / "h.sqlite"), HumanStudyConfig(n_trials=80))
    assert r["n_trials"] == 80 and r["n_closed"] > 0
    assert all(p["jet_m_s"] > 0 for p in r["pareto"])
