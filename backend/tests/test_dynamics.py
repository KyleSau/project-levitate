import math

import numpy as np
import pytest

from levitate.design import Design
from levitate.evaluate import evaluate, vehicle_params
from levitate.physics.dynamics import SimConfig, Waypoint, quat_mul, quat_to_rot, simulate

GOOD = Design(rotor_diameter_mm=22.2, lateral_offset_mm=3.4, board_height_mm=6.0, deck_material="eps_foam_cf",
              motor="bl_0702", battery="lipo_1s_550")


def _vp(design, overrides=None):
    rep = evaluate(design, overrides)
    vals = rep.assumptions_used["nominal"]
    return vehicle_params(design, rep.layout, rep.mass_budget, rep.scenarios["nominal"], vals), rep


def test_quaternion_rotation_is_orthonormal():
    q = np.array([0.9, 0.1, -0.3, 0.2])
    q /= np.linalg.norm(q)
    R = quat_to_rot(q)
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-12)
    assert np.linalg.det(R) == pytest.approx(1.0)
    # composition matches matrix product
    p = np.array([0.7, 0.0, 0.7, 0.1])
    p /= np.linalg.norm(p)
    assert np.allclose(quat_to_rot(quat_mul(q, p)), R @ quat_to_rot(p), atol=1e-12)


def test_full_mission_is_stable_and_lands():
    vp, rep = _vp(GOOD)
    assert rep.scenarios["nominal"].thrust_to_weight > 1.3
    res = simulate(vp, SimConfig())
    m = res.metrics
    assert m["stable"] and not m["crashed"]
    assert m["rms_tracking_error_m"] < 0.05
    assert m["landed"] and m["landing_error_m"] < 0.05
    # never meaningfully below the ground plane
    assert min(p[2] for p in res.pos) > -0.005


def test_hover_equilibrium_thrust_equals_weight():
    vp, _ = _vp(GOOD)
    cfg = SimConfig(duration_s=6.0, mission=[Waypoint(t=0, pos=(0, 0, 0)), Waypoint(t=0.5, pos=(0, 0, 0.3))])
    res = simulate(vp, cfg)
    tail = np.array(res.thrusts[-20:]).sum(axis=1)
    # at 0.3 m the Cheeseman-Bennett correction is < 0.1 %, so total thrust ~ weight
    assert tail.mean() == pytest.approx(vp.mass_kg * 9.80665, rel=0.01)
    assert res.pos[-1][2] == pytest.approx(0.3, abs=0.005)


def test_underpowered_vehicle_cannot_climb():
    vp, _ = _vp(GOOD)
    vp = vp.model_copy(update={"t_max_n": 0.9 * vp.mass_kg * 9.80665 / 4})   # T/W = 0.9
    res = simulate(vp, SimConfig(duration_s=4.0))
    # Ground effect (up to +33 % thrust at z/R = 0.5) lets it skim ~1 rotor radius above the surface,
    # exactly as underpowered multirotors do, but it cannot climb out of ground effect to the 0.3 m target.
    assert max(p[2] for p in res.pos) < 2 * vp.rotor_radius_m
    assert not res.metrics["stable"]


def test_gust_rejection():
    vp, _ = _vp(GOOD)
    res = simulate(vp, SimConfig(gust_std_n=0.02, sensor_noise_pos_m=0.002, sensor_noise_att_rad=0.005, seed=3))
    assert res.metrics["stable"]


def test_mass_mismatch_robustness():
    vp, _ = _vp(GOOD)
    res = simulate(vp, SimConfig(plant_mass_scale=1.1))
    assert res.metrics["stable"]
