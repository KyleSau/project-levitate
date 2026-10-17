"""Concrete solver adapters and the registry."""
from __future__ import annotations

import importlib.util
import shutil

from ..design import Design
from ..ehd_board import EADDesign, evaluate_ead
from ..evaluate import evaluate
from ..physics.dynamics import SimConfig
from ..provenance import Evidence
from .base import SolverAdapter, SolverJob, SolverOutput, which_wsl
from .ehd_bipolar import BipolarCoronaSolver, CoronaGeometry


def rotor_summary(rep) -> dict:
    n = rep.scenarios["nominal"]
    s = {
        "verdict": rep.verdict, "mass_g": round(n.mass_g, 2), "hover_power_w": round(n.hover_electrical_power_w, 2),
        "endurance_s_pess": round(rep.scenarios["pessimistic"].endurance_s, 1),
        "endurance_s_nom": round(n.endurance_s, 1),
        "endurance_s_opt": round(rep.scenarios["optimistic"].endurance_s, 1),
        "thrust_to_weight": round(n.thrust_to_weight, 3), "roll_accel": round(n.authority_rad_s2["roll"], 1),
        "pitch_accel": round(n.authority_rad_s2["pitch"], 1), "yaw_accel": round(n.authority_rad_s2["yaw"], 1),
        "cost_usd": round(rep.cost_usd, 2), "n_rotors": rep.design.n_rotors,
        "rotor_diameter_mm": rep.design.rotor_diameter_mm, "motor": rep.design.motor, "battery": rep.design.battery,
        "layout": rep.design.layout, "footprint_mm2": rep.design.length_mm * rep.design.width_mm,
    }
    if rep.sim:
        s["sim_stable"] = rep.sim.metrics["stable"]
        s["sim_rms_err_m"] = round(float(rep.sim.metrics["rms_tracking_error_m"]), 4)
    return s


class RotorAnalyticAdapter(SolverAdapter):
    name = "levitate.rotor_momentum_6dof"
    handles = ("rotor_design",)
    evidence = Evidence.ANALYTICAL
    description = ("Momentum theory + mass budget + battery + LP control authority; optional RK4 6-DOF closed-loop "
                   "mission (simplified numerical, driven by the analytical force model).")

    def run(self, job: SolverJob) -> SolverOutput:
        cfg = dict(job.config)
        run_sim = bool(cfg.pop("run_sim", False))
        sim_cfg = SimConfig(**cfg.pop("sim", {})) if "sim" in cfg else None
        d = Design(**cfg)
        rep = evaluate(d, job.overrides, run_sim=run_sim, sim_cfg=sim_cfg)
        return SolverOutput(solver=self.name, evidence=rep.evidence, results=rep.model_dump(mode="json"),
                            summary=rotor_summary(rep), verdict=rep.verdict,
                            assumptions={k: v for k, v in rep.assumptions_used.items()})


def ead_summary(rep) -> dict:
    n = rep.scenarios["nominal"]
    return {"verdict": rep.verdict, "mass_g": round(n.mass_g, 2), "thrust_mn": round(n.thrust_n * 1000, 2),
            "thrust_to_weight": round(n.thrust_to_weight, 4),
            "thrust_to_weight_opt": round(rep.scenarios["optimistic"].thrust_to_weight, 4),
            "power_w": round(n.electrical_power_w, 2), "voltage_kv": rep.design.voltage_kv,
            "gap_mm": rep.design.gap_mm, "n_stages": rep.design.n_stages,
            "scl_bound_mn": round(n.scl_upper_bound_thrust_n * 1000, 2), "endurance_s_nom": round(n.endurance_s, 1)}


class EADSurrogateAdapter(SolverAdapter):
    name = "levitate.ead_board_surrogate"
    handles = ("ead_design",)
    evidence = Evidence.SIMPLIFIED_NUMERICAL
    description = "Board-level ionic-wind system model on a surrogate fitted to the coupled corona solver."

    def run(self, job: SolverJob) -> SolverOutput:
        rep = evaluate_ead(EADDesign(**job.config), job.overrides)
        return SolverOutput(solver=self.name, evidence=rep.evidence, results=rep.model_dump(mode="json"),
                            summary=ead_summary(rep), verdict=rep.verdict)


class CoronaFVAdapter(SolverAdapter):
    name = "levitate.corona_bipolar_fv"
    handles = ("ehd_wire",)
    evidence = Evidence.SIMPLIFIED_NUMERICAL
    description = ("Coupled Poisson + unipolar ion drift (Kaptzov/Peek), bipolar-coordinate FD/FV, with automatic "
                   "two-grid convergence check.")

    def run(self, job: SolverJob) -> SolverOutput:
        c = job.config
        geom = CoronaGeometry(r_wire=c.get("wire_radius_um", 25) * 1e-6, gap=c.get("gap_mm", 10) / 1000)
        V = c.get("voltage_kv", 10) * 1000
        mu = c.get("mobility", 2.0e-4)
        n = c.get("grid", [48, 96])
        D = geom.gap
        coarse = BipolarCoronaSolver(geom, n[0], n[1], mobility=mu).solve(V, strips=(D, 2 * D), sample_fields=True)
        notes, valid = [], True
        conv = None
        if c.get("convergence_check", True) and coarse.corona_active:
            fine = BipolarCoronaSolver(geom, 2 * n[0], 2 * n[1], mobility=mu).solve(V, strips=(D, 2 * D))
            conv = abs(fine.thrust_per_length / coarse.thrust_per_length - 1) if coarse.thrust_per_length else 0
            notes.append(f"grid convergence: thrust changes {conv:.1%} on 2x refinement")
            if conv > 0.10:
                valid = False
                notes.append("discretisation error > 10%: refine grid")
        if coarse.current_conservation_error > 1e-3:
            valid = False
            notes.append("current not conserved between electrodes")
        res = {k: v for k, v in coarse.__dict__.items()}
        res["grid_convergence_rel"] = conv
        summary = {"voltage_kv": V / 1000, "gap_mm": D * 1000, "wire_radius_um": geom.r_wire * 1e6,
                   "corona": coarse.corona_active, "current_ua_per_m": round(coarse.current_per_length * 1e6, 3),
                   "thrust_mn_per_m": round(coarse.thrust_per_length * 1000, 4),
                   "thrust_to_power_n_per_kw": round(coarse.thrust_to_power * 1000, 3),
                   "grid_convergence_rel": conv}
        return SolverOutput(solver=self.name, evidence=self.evidence, results=res, summary=summary,
                            verdict="VALID" if valid else "UNCONVERGED", valid=valid, validity_notes=notes)


# --------------------------------------------------------------------------- external engines
class _ExternalAdapter(SolverAdapter):
    binary = ""
    evidence = Evidence.HIGH_FIDELITY_NUMERICAL
    install_hint = ""

    def available(self):
        p = which_wsl(self.binary) if self.binary else None
        return (True, f"found {p}") if p else (False, f"not installed. {self.install_hint}")

    def run(self, job: SolverJob) -> SolverOutput:
        ok, why = self.available()
        raise RuntimeError(f"{self.name}: {why}" if not ok else
                           f"{self.name}: case generation for '{job.kind}' not implemented yet (see docs/SOLVERS.md)")


class ElmerAdapter(_ExternalAdapter):
    name, binary = "elmer", "ElmerSolver"
    handles = ("ehd_wire_3d", "structure_modal", "thermal")
    install_hint = "Windows installer from https://www.elmerfem.org or `apt install elmerfem-csc` in WSL Ubuntu."
    description = "Elmer FEM: electrostatics, structural modal, thermal for 3D geometries (Gmsh meshes)."


class OpenFOAMAdapter(_ExternalAdapter):
    name, binary = "openfoam", "simpleFoam"
    handles = ("duct_cfd", "ead_flow", "cyclorotor_cfd")
    install_hint = "Install Ubuntu in WSL2, then the openfoam.org apt repository."
    description = "OpenFOAM: ducted-fan inflow/ground-effect CFD, EHD body-force-driven flow, cyclorotor moving mesh."


class GetDPAdapter(_ExternalAdapter):
    name, binary = "getdp", "getdp"
    handles = ("magnetics", "eddy_current")
    install_hint = "Binaries from https://getdp.info"
    description = "GetDP: magnetodynamics / eddy-current FE (e.g. quantitative Hendo-over-ground check)."


class FEMMAdapter(_ExternalAdapter):
    name, binary = "femm", "femm"
    handles = ("magnetics_2d", "electrostatics_2d")
    install_hint = "Windows installer from https://www.femm.info (scriptable via pyfemm)."
    description = "FEMM: rapid 2D magnetics/electrostatics cross-checks."


class FEniCSxAdapter(SolverAdapter):
    name = "fenicsx"
    handles = ("custom_pde",)
    evidence = Evidence.HIGH_FIDELITY_NUMERICAL
    description = "FEniCSx (dolfinx) for custom coupled PDEs on unstructured meshes; conda-forge in WSL."

    def available(self):
        ok = importlib.util.find_spec("dolfinx") is not None
        return (ok, "dolfinx importable" if ok else "not installed (conda-forge fenics-dolfinx, Linux/WSL recommended)")

    def run(self, job):
        raise RuntimeError("fenicsx adapter: not installed / not implemented yet")


class COMSOLAdapter(SolverAdapter):
    """Optional. Uses the documented COMSOL LiveLink/`mph` Python interface if the user later has a licence.
    Nothing in the harness depends on it."""
    name = "comsol"
    handles = ("any_multiphysics",)
    evidence = Evidence.HIGH_FIDELITY_NUMERICAL
    description = "Optional COMSOL Multiphysics via the documented `mph` client (licensed installs only)."

    def available(self):
        has_mph = importlib.util.find_spec("mph") is not None
        has_bin = shutil.which("comsol") is not None
        if has_mph and has_bin:
            return True, "mph + comsol found"
        return False, "COMSOL unavailable (not required). Install COMSOL + `pip install mph` to enable."

    def run(self, job):
        raise RuntimeError("COMSOL adapter is a documented placeholder; see docs/SOLVERS.md")


REGISTRY: list[SolverAdapter] = [RotorAnalyticAdapter(), EADSurrogateAdapter(), CoronaFVAdapter(), ElmerAdapter(),
                                 OpenFOAMAdapter(), GetDPAdapter(), FEMMAdapter(), FEniCSxAdapter(), COMSOLAdapter()]


def select_adapter(kind: str, prefer_fidelity: bool = False) -> SolverAdapter:
    cands = [a for a in REGISTRY if kind in a.handles and a.available()[0]]
    if not cands:
        raise LookupError(f"no available solver handles '{kind}'")
    order = [Evidence.HIGH_FIDELITY_NUMERICAL, Evidence.SIMPLIFIED_NUMERICAL, Evidence.ANALYTICAL]
    cands.sort(key=lambda a: order.index(a.evidence) if prefer_fidelity else -order.index(a.evidence))
    return cands[0]
