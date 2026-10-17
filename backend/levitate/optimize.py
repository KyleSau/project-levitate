"""Optimisation studies: multi-objective rotor search (NSGA-II), EAD search, sweeps, sensitivity analysis,
and a rule-based research-goal planner.

Constraint handling: hard-constraint violations become Optuna constraint values (> 0 = violated), so
infeasible candidates are kept and inspectable as rejected designs rather than silently discarded.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Callable

import optuna
from pydantic import BaseModel, Field

from .catalog import BATTERIES, MATERIALS, MOTORS, global_assumptions
from .db import ExperimentDB
from .design import Design
from .ehd_board import EADDesign, _onset_voltage, ehd_assumptions, evaluate_ead
from .evaluate import evaluate
from .solvers.adapters import ead_summary, rotor_summary

optuna.logging.set_verbosity(optuna.logging.WARNING)
log = logging.getLogger("levitate.optimize")


class RotorStudyConfig(BaseModel):
    n_trials: int = Field(300, ge=1, le=20000)
    seed: int = 42
    objectives: list[str] = ["endurance", "mass", "stability", "cost"]
    max_mass_g: float | None = None
    min_endurance_s: float | None = None
    robust: bool = False                       # optimise pessimistic-scenario endurance
    fixed: dict[str, Any] = Field(default_factory=dict)
    width_range_mm: tuple[float, float] = (30.0, 35.0)
    length_range_mm: tuple[float, float] = (95.0, 105.0)
    simulate_top_k: int = 5


OBJ_DIRECTIONS = {"endurance": "maximize", "mass": "minimize", "stability": "maximize", "cost": "minimize",
                  "power": "minimize", "footprint": "minimize"}


def _suggest_design(trial: optuna.Trial, cfg: RotorStudyConfig) -> Design:
    f = cfg.fixed

    def pick(name, fn):
        return f[name] if name in f else fn()

    return Design(
        name=f"trial-{trial.number}",
        length_mm=pick("length_mm", lambda: trial.suggest_float("length_mm", *cfg.length_range_mm)),
        width_mm=pick("width_mm", lambda: trial.suggest_float("width_mm", *cfg.width_range_mm)),
        board_height_mm=pick("board_height_mm", lambda: trial.suggest_float("board_height_mm", 5.0, 14.0)),
        skin_mm=pick("skin_mm", lambda: trial.suggest_float("skin_mm", 0.5, 1.5)),
        wall_mm=pick("wall_mm", lambda: trial.suggest_float("wall_mm", 0.5, 1.2)),
        deck_material=pick("deck_material", lambda: trial.suggest_categorical("deck_material", list(MATERIALS))),
        propulsion=pick("propulsion", lambda: "ducted_rotor"),
        layout=pick("layout", lambda: trial.suggest_categorical("layout", ["staggered", "grid"])),
        n_rotors=pick("n_rotors", lambda: trial.suggest_int("n_rotors", 3, 6)),
        rotor_diameter_mm=pick("rotor_diameter_mm", lambda: trial.suggest_float("rotor_diameter_mm", 12.0, 31.0)),
        lateral_offset_mm=pick("lateral_offset_mm", lambda: trial.suggest_float("lateral_offset_mm", 0.0, 10.0)),
        tip_gap_mm=pick("tip_gap_mm", lambda: trial.suggest_float("tip_gap_mm", 0.2, 0.6)),
        motor=pick("motor", lambda: trial.suggest_categorical("motor", list(MOTORS))),
        battery=pick("battery", lambda: trial.suggest_categorical("battery", list(BATTERIES))),
        extra_payload_g=f.get("extra_payload_g", 0.0),
        hover_altitude_m=f.get("hover_altitude_m", 0.3),
    )


def _objective_values(rep, cfg: RotorStudyConfig) -> list[float]:
    sc = rep.scenarios["pessimistic" if cfg.robust else "nominal"]
    vals = []
    for o in cfg.objectives:
        if o == "endurance":
            vals.append(sc.endurance_s)
        elif o == "mass":
            vals.append(sc.mass_g)
        elif o == "stability":
            vals.append(min(sc.authority_rad_s2["roll"], sc.authority_rad_s2["pitch"]) * min(sc.thrust_to_weight, 3))
        elif o == "cost":
            vals.append(rep.cost_usd)
        elif o == "power":
            vals.append(sc.hover_electrical_power_w)
        elif o == "footprint":
            vals.append(rep.design.length_mm * rep.design.width_mm)
    return vals


def _violations(rep, cfg: RotorStudyConfig) -> list[float]:
    sc = rep.scenarios["pessimistic" if cfg.robust else "nominal"]
    out = []
    for c in sc.constraints:
        if not c.hard:
            continue
        if c.passed:
            out.append(0.0)
        elif c.value is not None and c.limit is not None and c.limit != 0 and math.isfinite(c.value):
            out.append(abs(c.value - c.limit) / abs(c.limit) + 1e-3)
        else:
            out.append(1.0)
    if cfg.max_mass_g is not None:
        out.append(max(0.0, sc.mass_g - cfg.max_mass_g))
    if cfg.min_endurance_s is not None:
        out.append(max(0.0, cfg.min_endurance_s - sc.endurance_s))
    return out


def run_rotor_study(db: ExperimentDB, cfg: RotorStudyConfig, study_id: int | None = None,
                    progress: Callable[[float], None] | None = None) -> dict:
    sampler = optuna.samplers.NSGAIISampler(seed=cfg.seed, population_size=min(60, max(10, cfg.n_trials // 5)))
    study = optuna.create_study(directions=[OBJ_DIRECTIONS[o] for o in cfg.objectives], sampler=sampler)
    exp_ids: dict[int, int] = {}

    def objective(trial: optuna.Trial):
        d = _suggest_design(trial, cfg)
        rep = evaluate(d)
        cons = _violations(rep, cfg)
        trial.set_user_attr("constraints", cons)
        for i, v in enumerate(cons):
            trial.set_constraint(f"c{i}", v)
        summ = rotor_summary(rep)
        summ["trial"] = trial.number
        exp_ids[trial.number] = db.add_experiment(
            kind="rotor_design", solver="levitate.rotor_momentum_6dof", evidence=rep.evidence.value,
            config=d.model_dump(), results=rep.model_dump(mode="json", exclude={"sim"}), summary=summ,
            verdict=rep.verdict, name=d.name, study_id=study_id)
        if progress:
            progress((trial.number + 1) / cfg.n_trials * 0.9)
        return _objective_values(rep, cfg)

    study.optimize(objective, n_trials=cfg.n_trials)

    feasible = [t for t in study.best_trials if all(v <= 0 for v in t.user_attrs["constraints"])]
    feasible.sort(key=lambda t: -t.values[0] if OBJ_DIRECTIONS[cfg.objectives[0]] == "maximize" else t.values[0])
    pareto, seen = [], set()
    for t in feasible:
        key = tuple(sorted((k, round(v, 2) if isinstance(v, float) else v) for k, v in t.params.items()))
        if key in seen:
            continue
        seen.add(key)
        pareto.append({"trial": t.number, "experiment_id": exp_ids[t.number],
                       "values": dict(zip(cfg.objectives, t.values)), "params": t.params})

    # verify the leading Pareto designs in closed-loop 6-DOF simulation
    verified = []
    for p in pareto[: cfg.simulate_top_k]:
        exp = db.get_experiment(p["experiment_id"])
        d = Design(**exp["config"])
        rep = evaluate(d, run_sim=True)
        summ = rotor_summary(rep)
        eid = db.add_experiment(kind="rotor_design", solver="levitate.rotor_momentum_6dof+rk4_6dof",
                                evidence=rep.evidence.value, config={**d.model_dump(), "run_sim": True},
                                results=rep.model_dump(mode="json"), summary=summ, verdict=rep.verdict,
                                name=f"{d.name}-sim", study_id=study_id,
                                notes="Pareto design verified in closed-loop 6-DOF mission")
        verified.append({"experiment_id": eid, "trial": p["trial"], **summ})
    if progress:
        progress(1.0)
    n_feasible = sum(1 for t in study.trials if all(v <= 0 for v in t.user_attrs.get("constraints", [1])))
    return {"n_trials": len(study.trials), "n_feasible": n_feasible, "objectives": cfg.objectives,
            "pareto": pareto, "verified": verified}


class EADStudyConfig(BaseModel):
    n_trials: int = Field(400, ge=1, le=20000)
    seed: int = 7
    scenario: str = "optimistic"       # search the most favourable assumptions: a best case
    width_range_mm: tuple[float, float] = (30.0, 35.0)
    max_stack_height_mm: float = 40.0


def run_ead_study(db: ExperimentDB, cfg: EADStudyConfig, study_id: int | None = None,
                  progress: Callable[[float], None] | None = None) -> dict:
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=cfg.seed))
    best_ids = {}

    spark = ehd_assumptions().values(cfg.scenario)["spark_mean_field"]

    def objective(trial):
        gap = trial.suggest_float("gap_mm", 3.0, 30.0)
        r_um = trial.suggest_float("wire_radius_um", 12.5, 50.0)
        # voltage searched inside the physical operating window [corona onset, sparkover]
        v0 = _onset_voltage(r_um * 1e-6, gap / 1000)
        v_spark = spark * gap / 1000
        frac = trial.suggest_float("window_fraction", 0.02, 1.0)
        volt = v0 + frac * max(v_spark - v0, 0.0)
        d = EADDesign(
            name=f"ead-{trial.number}",
            width_mm=trial.suggest_float("width_mm", *cfg.width_range_mm),
            voltage_kv=max(volt / 1000, 1.0),
            gap_mm=gap,
            wire_radius_um=r_um,
            pitch_over_gap=trial.suggest_float("pitch_over_gap", 1.0, 3.0),
            n_stages=trial.suggest_int("n_stages", 1, 8),
            battery=trial.suggest_categorical("battery", list(BATTERIES)),
            avionics_g=2.5, max_stack_height_mm=cfg.max_stack_height_mm)
        rep = evaluate_ead(d)
        sc = rep.scenarios[cfg.scenario]
        best_ids[trial.number] = db.add_experiment(
            kind="ead_design", solver="levitate.ead_board_surrogate", evidence=rep.evidence.value,
            config=d.model_dump(), results=rep.model_dump(mode="json"), summary=ead_summary(rep),
            verdict=rep.verdict, name=d.name, study_id=study_id)
        if progress:
            progress((trial.number + 1) / cfg.n_trials)
        excess = d.stack_height_mm - d.max_stack_height_mm
        return sc.thrust_to_weight if excess <= 0 else -excess / 100   # geometric violation ranks below any fit

    study.optimize(objective, n_trials=cfg.n_trials)
    bt = study.best_trial
    best = db.get_experiment(best_ids[bt.number])
    return {"n_trials": len(study.trials), "best_thrust_to_weight": bt.value, "scenario": cfg.scenario,
            "best_params": bt.params, "best_experiment_id": best_ids[bt.number], "best_summary": best["summary"]}


# ------------------------------------------------------------------------------------ sensitivity
def sensitivity(d: Design) -> list[dict]:
    """One-at-a-time tornado: each assumption to its low and high value, others nominal."""
    base = evaluate(d).scenarios["nominal"]
    rows = []
    for k, a in global_assumptions().items.items():
        lo = evaluate(d, {k: a.low}).scenarios["nominal"]
        hi = evaluate(d, {k: a.high}).scenarios["nominal"]
        rows.append({"assumption": k, "description": a.description, "low": a.low, "high": a.high, "unit": a.unit,
                     "status": a.status.value, "endurance_low_s": lo.endurance_s, "endurance_high_s": hi.endurance_s,
                     "tw_low": lo.thrust_to_weight, "tw_high": hi.thrust_to_weight,
                     "swing_s": abs(hi.endurance_s - lo.endurance_s)})
    rows.sort(key=lambda r: -r["swing_s"])
    return [{"base_endurance_s": base.endurance_s, "base_tw": base.thrust_to_weight}] + rows


def sweep(d: Design, param: str, values: list[float | str]) -> list[dict]:
    out = []
    for v in values:
        dd = d.model_copy(update={param: v})
        try:
            rep = evaluate(dd)
            out.append({"value": v, **rotor_summary(rep)})
        except Exception as e:  # noqa: BLE001 - report the failure as a result
            out.append({"value": v, "error": str(e)})
    return out


# ------------------------------------------------------------------------------------ goal planner
class ResearchPlan(BaseModel):
    goal: str
    kind: str
    config: dict
    rationale: list[str]
    planner: str = "rule-based keyword planner (deterministic; no LLM)"


def plan_from_goal(goal: str) -> ResearchPlan:
    g = goal.lower()
    why: list[str] = []
    if any(w in g for w in ("ion", "ead", "ehd", "electroaero", "corona")):
        n = _int_after(g, ("trials", "experiments"), 400)
        why.append("goal mentions ionic wind -> EAD board search on the corona-solver surrogate")
        why.append("searching optimistic assumptions: if the best case cannot lift, the concept is eliminated")
        return ResearchPlan(goal=goal, kind="ead_study", config=EADStudyConfig(n_trials=n).model_dump(), rationale=why)
    cfg = RotorStudyConfig()
    cfg.n_trials = _int_after(g, ("trials", "experiments", "designs", "candidates"), 300)
    objs = []
    if any(w in g for w in ("endurance", "flight time", "longest", "duration")):
        objs.append("endurance")
    if any(w in g for w in ("light", "mass", "weight")):
        objs.append("mass")
    if any(w in g for w in ("stab", "agile", "control")):
        objs.append("stability")
    if any(w in g for w in ("cheap", "cost", "budget")):
        objs.append("cost")
    if "power" in g:
        objs.append("power")
    if objs:
        cfg.objectives = objs
        why.append(f"objectives parsed from goal: {objs}")
    else:
        why.append("no objective keywords: default objectives endurance/mass/stability/cost")
    m = re.search(r"(under|below|<|max(?:imum)?)\s*(\d+(?:\.\d+)?)\s*g\b", g)
    if m:
        cfg.max_mass_g = float(m.group(2))
        why.append(f"mass cap {cfg.max_mass_g} g")
    m = re.search(r"(at least|>=|over|minimum)\s*(\d+(?:\.\d+)?)\s*(min|minutes|s|sec)", g)
    if m:
        v = float(m.group(2))
        cfg.min_endurance_s = v * 60 if m.group(3).startswith("min") else v
        why.append(f"endurance floor {cfg.min_endurance_s:.0f} s")
    if "robust" in g or "pessimistic" in g or "worst" in g:
        cfg.robust = True
        why.append("robust: objectives and constraints evaluated at pessimistic assumptions")
    if "coreless" in g or "brushed" in g:
        cfg.fixed["motor"] = "coreless_0716"
        why.append("motor fixed to coreless class")
    for mat in MATERIALS:
        if mat.split("_")[0] in g:
            cfg.fixed["deck_material"] = mat
            why.append(f"deck material fixed to {mat}")
    return ResearchPlan(goal=goal, kind="rotor_study", config=cfg.model_dump(), rationale=why)


def _int_after(g: str, words: tuple[str, ...], default: int) -> int:
    for w in words:
        m = re.search(r"(\d+)\s*" + w, g)
        if m:
            return max(1, min(int(m.group(1)), 5000))
    return default


def ead_sensitivity(d: EADDesign) -> list[dict]:
    rows = []
    for k, a in ehd_assumptions().items.items():
        lo = evaluate_ead(d, {k: a.low}).scenarios["nominal"]
        hi = evaluate_ead(d, {k: a.high}).scenarios["nominal"]
        rows.append({"assumption": k, "low": a.low, "high": a.high, "tw_low": lo.thrust_to_weight,
                     "tw_high": hi.thrust_to_weight})
    return rows
