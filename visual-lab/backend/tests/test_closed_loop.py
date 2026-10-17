"""Closed-loop flight: demo mission, ideal vs reality, failure-to-hover, disturbance rejection."""
import numpy as np
import pytest

from vlab.mission import Step
from vlab.modes import BatteryConstraint, Impulse, ModeConfig, reality_preset
from vlab.sim import SimRequest, SimSettings, run


@pytest.fixture(scope="module")
def ideal_demo():
    return run(SimRequest(mode=reality_preset("ideal")))


def _clearance(res):
    pos = np.array(res["trajectory"]["pos"])
    v = res["vehicle"]
    return pos[:, 2] - (v["cg_m"][2] + v["height_m"] / 2)


def test_demo_mission_ideal_completes_all_segments(ideal_demo):
    s = ideal_demo["summary"]
    assert s["completed_mission"]
    assert s["takeoffs"] == 2 and s["landings"] == 1
    assert s["failures"] == []
    kinds = [e["kind"] for e in ideal_demo["events"]]
    for k in ("LIFTOFF", "COMMAND_REMOVED", "BRAKE", "TOUCHDOWN", "LANDED"):
        assert k in kinds
    assert abs(s["hover_force_over_weight"] - 1.0) < 2e-3, "hover: actuator force balances weight"
    assert s["max_ground_penetration_m"] < 2e-4
    assert ideal_demo["summary"]["evidence"] == "hypothetical_ideal"


def test_quaternions_normalised_in_record(ideal_demo):
    q = np.array(ideal_demo["trajectory"]["quat"])
    assert np.abs(np.linalg.norm(q, axis=1) - 1).max() < 1e-5   # transport rounding to 7 digits


def test_forward_momentum_persists_when_command_removed(ideal_demo):
    tr = ideal_demo["trajectory"]
    ph = np.array(tr["phase"])
    coast = [p["index"] for p in ideal_demo["phases"] if p["kind"] == "coast"][0]
    v = np.array(tr["vel"])[ph == coast]
    att = np.array(tr["euler_deg"])[ph == coast]
    assert v[0, 0] > 0.7
    # level attitude -> only drag decelerates; velocity retained > 95 % over 1.2 s
    assert v[-1, 0] / v[0, 0] > 0.95
    assert np.abs(att[20:, 1]).max() < 1.0
    # acceleration during coast equals drag/m (no thrust in x)
    F_net = np.array(tr["F_net"])[ph == coast]
    F_drag = np.array(tr["F_drag"])[ph == coast]
    assert np.abs(F_net[20:, 0] - F_drag[20:, 0]).max() < 2e-4


def test_vehicle_lands_and_takes_off_again(ideal_demo):
    clr = _clearance(ideal_demo)
    tr = ideal_demo["trajectory"]
    t = np.array(tr["t"])
    ev = {e["kind"]: e["t"] for e in ideal_demo["events"]}
    landed_t = ev["LANDED"]
    i = np.searchsorted(t, landed_t + 0.5)
    assert abs(clr[i]) < 2e-4 and tr["contact_n"][i] > 0.9 * ideal_demo["summary"]["weight_n"]
    assert clr[-1] > 0.2, "second takeoff reached hover altitude"
    assert clr.min() > -2e-4


def test_pitch_forward_for_forward_flight(ideal_demo):
    tr = ideal_demo["trajectory"]
    ph = np.array(tr["phase"])
    acc = [p["index"] for p in ideal_demo["phases"] if p["kind"] == "accelerate"][0]
    pitch = np.array(tr["euler_deg"])[ph == acc][:, 1]
    assert pitch.max() > 3.0, "quad-type actuators must pitch nose-down (positive pitch about +y) to accelerate +x"


def test_disturbance_rejection_in_hover(ideal_demo):
    tr = ideal_demo["trajectory"]
    t = np.array(tr["t"])
    err = np.linalg.norm(np.array(tr["err_pos"]), axis=1)
    i_hit = np.searchsorted(t, 5.0)
    i_peak = i_hit + np.argmax(err[i_hit:i_hit + 150])
    assert err[i_peak] > 2e-3, "impulse must visibly disturb"
    i_after = np.searchsorted(t, 6.7)
    assert err[i_after] < 0.35 * err[i_peak]


def test_reality_baseline_flies():
    r = run(SimRequest(mode=reality_preset("reality_baseline")))
    assert r["summary"]["completed_mission"] and r["summary"]["landings"] == 1
    assert r["summary"]["mass_kg"] == pytest.approx(0.0282, abs=1e-9), "battery mass is added"
    assert r["summary"]["energy_j"] > 50
    assert r["feasibility"]["verdict"] in ("FEASIBLE", "MARGINAL")


@pytest.mark.parametrize("preset,expect", [("underpowered", "power_cap"), ("too_heavy", "battery_power"),
                                           ("thrust_capped", "hover_thrust")])
def test_infeasible_configs_fail_to_hover(preset, expect):
    r = run(SimRequest(mode=reality_preset(preset)))
    f = r["feasibility"]
    assert f["verdict"] == "INFEASIBLE"
    assert expect in f["failing"]
    assert _clearance(r).max() < 0.01, "must not fly"
    assert "TAKEOFF_FAILED" in r["summary"]["failures"]


def test_battery_depletion_mid_flight_falls_and_stops_on_ground():
    mc = reality_preset("reality_baseline")
    mc.battery = BatteryConstraint(enabled=True, usable_fraction=0.006)   # ~19 J: a few seconds of hover
    mission = [Step(kind="arm", duration_s=0.3), Step(kind="takeoff", duration_s=1.5, alt_m=0.2),
               Step(kind="hold", duration_s=20.0)]
    r = run(SimRequest(mode=mc, mission=mission, settings=SimSettings(t_max_s=12)))
    kinds = [e["kind"] for e in r["events"]]
    assert "BATTERY_DEPLETED" in kinds
    clr = _clearance(r)
    assert clr.max() > 0.1 and abs(clr[-1]) < 1e-3, "falls back to the ground after energy is exhausted"
    assert clr.min() > -1.5e-3


def test_step_size_independence_short_mission():
    mission = [Step(kind="arm", duration_s=0.4), Step(kind="takeoff", duration_s=1.5, alt_m=0.2),
               Step(kind="accelerate", duration_s=1.0, vel=(0.5, 0, 0)), Step(kind="hold", duration_s=0.5)]
    mc = ModeConfig(mode="ideal")
    mc.disturbances.impulses = [Impulse(t_s=99, force_n=(0, 0, 0))]
    a = run(SimRequest(mode=mc, mission=mission, settings=SimSettings(dt=1e-3)))
    b = run(SimRequest(mode=mc, mission=mission, settings=SimSettings(dt=5e-4)))
    pa, pb = np.array(a["trajectory"]["pos"]), np.array(b["trajectory"]["pos"])
    n = min(len(pa), len(pb))
    assert np.abs(pa[:n] - pb[:n]).max() < 2e-3


def test_offline_dop853_runner_matches_rk4():
    mission = [Step(kind="arm", duration_s=0.3), Step(kind="takeoff", duration_s=1.0, alt_m=0.15),
               Step(kind="hold", duration_s=0.3)]
    mc = ModeConfig(mode="ideal")
    mc.disturbances.impulses = [Impulse(t_s=99, force_n=(0, 0, 0))]
    a = run(SimRequest(mode=mc, mission=mission, settings=SimSettings(integrator="rk4")))
    b = run(SimRequest(mode=mc, mission=mission, settings=SimSettings(integrator="dop853")))
    pa, pb = np.array(a["trajectory"]["pos"]), np.array(b["trajectory"]["pos"])
    n = min(len(pa), len(pb))
    assert np.abs(pa[:n] - pb[:n]).max() < 1e-4


def test_actuator_failure_is_reported():
    mc = ModeConfig(mode="ideal")
    mc.disturbances.actuator_failure_index = 0
    mc.disturbances.actuator_failure_t_s = 2.5
    mission = [Step(kind="arm", duration_s=0.3), Step(kind="takeoff", duration_s=1.5, alt_m=0.2),
               Step(kind="hold", duration_s=3.0)]
    r = run(SimRequest(mode=mc, mission=mission, settings=SimSettings(t_max_s=6)))
    assert "ACTUATOR_FAILURE" in [e["kind"] for e in r["events"]]
    fa = np.array(r["trajectory"]["f_act"])
    t = np.array(r["trajectory"]["t"])
    assert np.abs(fa[t > 2.6, 0]).max() == 0.0
