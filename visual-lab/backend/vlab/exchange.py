"""levitate.experiment-result/v1 import / export (schema/experiment_result.v1.schema.json).

Import: a research-harness (or any v1) document's `vehicle` block becomes a VehicleConfig whose inertia,
CG and mass are taken verbatim (inertia_override), plus a suggested REALITY ModeConfig built from its
`power_model`; `fields` become overlay grids. Evidence categories are passed through unchanged.
Export: a recorded flight becomes a v1 document with source = "visual_lab", kind = "flight_sim" and
evidence "hypothetical_ideal" (IDEAL mode) or "simplified_numerical_simulation" (REALITY mode).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

from .modes import BatteryConstraint, ModeConfig, PropulsionEfficiency, V_OC_PER_CELL, reality_preset
from .util import ROOT, sanitize, versions
from .vehicle import Actuator, DragModel, MassComponent, PowerModel, VehicleConfig, check_inertia

SCHEMA_PATH = ROOT.parent / "schema" / "experiment_result.v1.schema.json"
SCHEMA_ID = "levitate.experiment-result/v1"


def load_schema() -> dict:
    return json.loads(Path(SCHEMA_PATH).read_text())


def validate_doc(doc: dict) -> list[str]:
    import jsonschema
    v = jsonschema.Draft202012Validator(load_schema())
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in v.iter_errors(doc)]


# ------------------------------------------------------------------------------------------ import
def vehicle_from_doc(doc: dict) -> tuple[VehicleConfig, ModeConfig, list[str]]:
    vb = doc.get("vehicle")
    if not vb:
        raise ValueError("document has no vehicle block")
    notes = []
    J = np.array(vb["inertia_kgm2"], float)
    issues = check_inertia(J)
    if issues:
        raise ValueError("imported inertia invalid: " + "; ".join(issues))
    dims = vb.get("dimensions_m") or [0.1, 0.032, 0.009]
    m = float(vb["mass_kg"])
    cg = tuple(float(c) for c in vb["cg_m"])
    acts = []
    for i, a in enumerate(vb["actuators"]):
        acts.append(Actuator(name=f"A{i}", pos_m=tuple(a["pos_m"]), axis=tuple(a["axis"]), max_force_n=a["max_force_n"],
                             spin=int(a.get("spin", 0)), torque_ratio_m=float(a.get("torque_ratio_m", 0.0)),
                             time_constant_s=float(a.get("time_constant_s", 0.0)), mechanism=a.get("mechanism", "unspecified"),
                             radius_m=float(a.get("radius_m", 0.011))))
    drag = DragModel()
    if vb.get("drag"):
        cd = float(vb["drag"].get("cd", 1.1))
        drag = DragModel(cd_x=cd, cd_y=cd, cd_z=cd)
        notes.append(f"drag: cd = {cd} on all body axes (source areas recomputed from dimensions)")
    pm = vb.get("power_model") or {}
    power = PowerModel(figure_of_merit=pm.get("figure_of_merit", 0.42), duct_factor=pm.get("duct_factor", 1.0),
                       motor_efficiency=pm.get("motor_efficiency", 0.65), avionics_w=pm.get("avionics_w", 0.45))
    v = VehicleConfig(name=f"imported {doc.get('source')}#{doc.get('experiment_id')}", length_m=dims[0], width_m=dims[1],
                      height_m=dims[2],
                      components=[MassComponent(name="imported rigid body (mass, CG, inertia from source)", mass_kg=m,
                                                pos_m=cg, group="imported")],
                      actuators=acts, inertia_override_kgm2=J.tolist(), cg_override_m=cg, drag=drag, power=power,
                      source=f"{doc.get('source')}:{doc.get('experiment_id')} ({doc.get('evidence')})")
    mc = reality_preset("reality_baseline")
    mc.efficiency = PropulsionEfficiency(enabled=True, figure_of_merit=power.figure_of_merit,
                                         motor_efficiency=power.motor_efficiency, duct_factor=power.duct_factor)
    mc.conversion_losses.enabled = False         # harness motor efficiency already includes the driver
    mc.power_limit.enabled = False
    if pm.get("battery_energy_j"):
        e = float(pm["battery_energy_j"])
        b = BatteryConstraint(enabled=True, include_mass=False, usable_fraction=0.8,
                              capacity_mah=e / (V_OC_PER_CELL * 3600 * 0.8) * 1000)
        if pm.get("battery_max_power_w"):
            b.max_power_override_w = float(pm["battery_max_power_w"])
        mc.battery = b
        notes.append(f"battery: {e:.0f} J usable, max {pm.get('battery_max_power_w')} W (mass already in vehicle)")
    else:
        mc.battery.enabled = False
    taus = {a.time_constant_s for a in acts}
    mc.delays.enabled = any(t > 0 for t in taus)
    if mc.delays.enabled:
        mc.delays.actuator_time_constant_s = max(taus)
    if "ducted" in (acts[0].mechanism if acts else ""):
        mc.propulsion = "ducted_rotor"
    elif "rotor" in (acts[0].mechanism if acts else ""):
        mc.propulsion = "open_rotor"
    notes.append("actuator max force taken per actuator from source; inertia/CG used verbatim")
    return v, mc, notes


def fields_from_doc(doc: dict) -> list[dict]:
    """Convert v1 `fields` into overlay grids {u, v, values[iv][iu]} without altering any value."""
    f = doc.get("fields")
    if not f or not f.get("quantities"):
        return []
    g = f.get("grid", {})
    axes = [k for k in ("x", "y", "z") if g.get(k)]
    if len(axes) < 2:
        return []
    a0, a1 = axes[0], axes[1]
    c0, c1 = g[a0], g[a1]
    out = []
    for name, q in f["quantities"].items():
        vals = q["values"]
        # orientation: values indexed [i0][i1] (len c0 x len c1) or [i1][i0]
        if len(vals) == len(c0) and len(vals[0]) == len(c1):
            # overlay wants values[iv][iu] with u = second axis (lateral), v = first axis
            out.append({"quantity": name, "unit": q.get("unit", ""), "u": c1, "v": c0, "values": vals,
                        "u_axis": a1, "v_axis": a0})
        elif len(vals) == len(c1) and len(vals[0]) == len(c0):
            out.append({"quantity": name, "unit": q.get("unit", ""), "u": c0, "v": c1, "values": vals,
                        "u_axis": a0, "v_axis": a1})
    for o in out:
        o.update(frame=f.get("frame", ""), source=doc.get("solver"), evidence=doc.get("evidence"),
                 experiment_id=doc.get("experiment_id"))
    return out


# ------------------------------------------------------------------------------------------ export
def flatten_summary(s: dict) -> dict:
    return {k: v for k, v in s.items() if isinstance(v, (int, float, str, bool)) or v is None}


def export_flight(res: dict, experiment_id=None, every: int = 1) -> dict:
    tr = res["trajectory"]
    veh = res["vehicle"]
    mc = res.get("mode_config", {})
    ideal = res["summary"]["mode"] == "ideal"
    pm = res.get("power_model", "")
    sl = slice(None, None, every)
    traj = {"t": tr["t"][sl], "pos": tr["pos"][sl], "quat": tr["quat"][sl], "vel": tr["vel"][sl],
            "omega": tr["omega"][sl], "forces": {k: tr[k][sl] for k in ("F_act", "F_grav", "F_drag", "F_contact", "F_ext", "F_net")},
            "torques": {k: tr[k][sl] for k in ("tau_act", "tau_drag", "tau_contact", "tau_net")},
            "actuator_force_n": tr["f_act"][sl], "electrical_power_w_estimate": tr["power_w"][sl],
            "energy_j_estimate": tr["energy_j"][sl], "phase": tr["phase"][sl],
            "frames": {"world": "x fwd, y left, z up; pos = CG", "quat": "w,x,y,z body->world", "omega": "body",
                       "forces": "world, N", "torques": "body about CG, N m"}}
    acts = []
    for a in veh["actuators"]:
        acts.append({"pos_m": list(a["pos_m"]), "axis": list(a["axis"]),
                     "max_force_n": a["max_force_n"] if a["max_force_n"] is not None else 1e9,
                     "spin": int(a["spin"]), "torque_ratio_m": a["torque_ratio_m"], "time_constant_s": a["time_constant_s"],
                     "mechanism": "hypothetical" if ideal else a["mechanism"], "radius_m": a["radius_m"]})
    doc = {
        "schema_version": SCHEMA_ID, "source": "visual_lab", "experiment_id": experiment_id, "kind": "flight_sim",
        "evidence": "hypothetical_ideal" if ideal else "simplified_numerical_simulation",
        "solver": "visual_lab.6dof_" + ("dop853" if "DOP853" in res.get("integrator", "") else "rk4"),
        "created": time.time(),
        "config": {"name": res.get("name"), "mode_config": mc, "gains": res.get("gains"), "settings": res.get("settings"),
                   "phases": res.get("phases"), "integrator": res.get("integrator")},
        "summary": flatten_summary(res["summary"]),
        "verdict": res["feasibility"]["verdict"],
        "assumptions": {"labels": res.get("labels"), "power_model": pm, "air": res.get("air"),
                        "constraints": res["feasibility"]["constraints"], "events": res.get("events")},
        "versions": versions(),
        "vehicle": {"mass_kg": veh["mass_kg"], "inertia_kgm2": veh["inertia_kgm2"],
                    "cg_m": [veh["cg_m"][i] for i in range(3)],
                    "dimensions_m": [veh["length_m"], veh["width_m"], veh["height_m"]], "actuators": acts,
                    "power_model": None if ideal else {"type": "momentum_theory" if "momentum" in pm else "other",
                                                       "figure_of_merit": mc.get("efficiency", {}).get("figure_of_merit"),
                                                       "duct_factor": mc.get("efficiency", {}).get("duct_factor"),
                                                       "motor_efficiency": mc.get("efficiency", {}).get("motor_efficiency")},
                    "drag": {"cd": veh["drag"]["cd_z"], "area_xy_m2": veh["length_m"] * veh["height_m"],
                             "area_z_m2": veh["length_m"] * veh["width_m"]}},
        "fields": None,
        "trajectory": traj,
    }
    if doc["vehicle"]["power_model"]:
        doc["vehicle"]["power_model"] = {k: v for k, v in doc["vehicle"]["power_model"].items() if v is not None}
    return sanitize(doc)


def export_rom_field(field_doc: dict, meta: dict) -> dict:
    return sanitize({
        "schema_version": SCHEMA_ID, "source": "visual_lab", "experiment_id": None, "kind": "solver_field",
        "evidence": meta.get("evidence", "simplified_numerical_simulation"), "solver": meta.get("solver"),
        "created": meta.get("created", time.time()), "config": {"title": field_doc.get("title"), "plane": field_doc.get("plane")},
        "summary": {"valid": meta.get("valid"), **{k: v for k, v in meta.get("deck_section", {}).items()}},
        "verdict": "VALID" if meta.get("valid") else "INVALID", "assumptions": {"limitations": meta.get("limitations")},
        "versions": versions(), "vehicle": None,
        "fields": {"grid": field_doc["grid"], "quantities": field_doc["quantities"]}, "trajectory": None})


def _finite(x):
    return x if (isinstance(x, (int, float)) and math.isfinite(x)) else None
