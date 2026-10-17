"""Modular solver-integration layer.

Each adapter: name, description, evidence, availability check, run(params, progress) -> result dict with
`valid` and `checks`. Heavy solvers never run per animation frame: solve offline -> validate ->
lookup table / reduced-order model -> flight dynamics -> visualisation.
Engines that are not installed are reported as NOT CONNECTED and are never faked.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import time

from ..util import DATA, sanitize


class Adapter:
    name = ""
    description = ""
    evidence = "simplified_numerical_simulation"
    produces = ""
    params: dict = {}

    def available(self) -> tuple[bool, str]:
        return True, "built-in"

    def status(self) -> dict:
        return {}

    def run(self, params: dict, progress=None) -> dict:
        raise NotImplementedError

    def info(self) -> dict:
        ok, why = self.available()
        return {"name": self.name, "description": self.description, "evidence": self.evidence, "available": ok,
                "status": "CONNECTED" if ok else "NOT CONNECTED", "detail": why, "produces": self.produces,
                "params": self.params, **self.status()}


class CanteraAir(Adapter):
    name = "cantera_air"
    description = ("Cantera ideal-gas thermo + mixture-averaged transport for air (and He/H2 density): "
                   "rho, mu, cp, k, a on a (T, p) grid -> bilinear ROM used by drag, rotor power, added mass.")
    produces = "data/rom/air_properties.json (ROM consumed when environment.air_model = cantera_rom)"

    def available(self):
        ok = importlib.util.find_spec("cantera") is not None
        return ok, "cantera importable" if ok else "cantera not installed"

    def status(self):
        from .cantera_air import ROM_PATH
        if not ROM_PATH.exists():
            return {"rom": None}
        m = json.loads(ROM_PATH.read_text())["meta"]
        return {"rom": {"valid": m["valid"], "created": m["created"], "checks": m["checks"], "version": m["cantera_version"]}}

    def run(self, params, progress=None):
        from .cantera_air import build_table
        d = build_table(progress)
        return {"valid": d["meta"]["valid"], "checks": d["meta"]["checks"], "meta": d["meta"]}


class FemAddedMass(Adapter):
    name = "fem_added_mass"
    description = ("Gmsh (OpenCASCADE) mesh + scikit-fem P2 finite elements: 2-D potential flow around the deck "
                   "cross-section -> added-mass coefficient table C_A(aspect) + exported phi / |u| field.")
    produces = "data/rom/added_mass.json (ROM, used when added_mass toggle is on) + added_mass_field.json (overlay)"

    def available(self):
        ok = importlib.util.find_spec("skfem") is not None and importlib.util.find_spec("gmsh") is not None
        return ok, "gmsh + scikit-fem importable" if ok else "gmsh or scikit-fem missing"

    def status(self):
        from .fem_added_mass import ROM_PATH
        if not ROM_PATH.exists():
            return {"rom": None}
        m = json.loads(ROM_PATH.read_text())["meta"]
        return {"rom": {"valid": m["valid"], "created": m["created"], "checks": m["checks"],
                        "deck_section": m.get("deck_section"), "limitations": m.get("limitations")}}

    def run(self, params, progress=None):
        from .fem_added_mass import build_rom
        d = build_rom(progress, W=params.get("width_m", 0.032), H=params.get("height_m", 0.009))
        return {"valid": d["meta"]["valid"], "checks": d["meta"]["checks"], "meta": d["meta"]}


class HarnessEHD(Adapter):
    name = "harness_ehd_wire"
    description = ("Agent A's coupled corona (ionic-wind) solver over its API (/api/solve/ehd_wire): Poisson + ion "
                   "drift with two-grid convergence check -> phi/rho fields + thrust-to-power for ionic propulsion.")
    produces = "data/rom/harness_ehd_latest.json (fields overlay; thrust_per_power for propulsion = ionic_wind)"
    params = {"voltage_kv": 9.0, "gap_mm": 8.0, "wire_radius_um": 25.0}

    def available(self):
        from ..harness import status
        s = status()
        return s["connected"], s["detail"]

    def status(self):
        p = DATA / "rom" / "harness_ehd_latest.json"
        if not p.exists():
            return {"rom": None}
        d = json.loads(p.read_text())
        return {"rom": {"valid": d.get("valid"), "created": d.get("created"), "summary": d.get("summary")}}

    def run(self, params, progress=None):
        from .. import harness
        p = {**self.params, **params}
        if progress:
            progress(0.05)
        res = harness.solve_ehd_wire(p["voltage_kv"], p["gap_mm"], p["wire_radius_um"])
        if progress:
            progress(0.8)
        doc = res
        if not res.get("schema_version") and res.get("experiment_id") is not None:
            # contract: the v1 document (with regular-grid fields) comes from /api/experiments/{id}/export
            try:
                doc = harness.export_experiment(res["experiment_id"])
            except Exception:  # noqa: BLE001 - export endpoint missing: no fields, reported below
                doc = res
        summary = doc.get("summary") or res.get("summary") or {}
        fields = doc.get("fields")
        verdict = doc.get("verdict") or res.get("verdict")
        cons = (res.get("results") or {}).get("current_conservation_error")
        checks = [{"check": "harness verdict VALID", "value": verdict, "passed": verdict == "VALID"},
                  {"check": "v1 fields present (via /api/experiments/{id}/export)", "value": bool(fields),
                   "passed": bool(fields)}]
        if cons is not None:
            checks.append({"check": "current conservation error between electrodes < 1e-3", "value": cons,
                           "limit": 1e-3, "passed": cons < 1e-3})
        conv = summary.get("grid_convergence_rel")
        if conv is not None:
            checks.append({"check": "grid convergence (2x refinement) < 10 %", "value": conv, "limit": 0.1,
                           "passed": conv < 0.1})
        valid = all(c["passed"] for c in checks)
        out = {"valid": valid, "checks": checks, "summary": summary, "created": time.time(), "params": p,
               "evidence": doc.get("evidence", "simplified_numerical_simulation"),
               "solver": doc.get("solver", "levitate.corona_bipolar_fv"),
               "document": {"schema_version": doc.get("schema_version"), "source": doc.get("source", "research_harness"),
                            "experiment_id": doc.get("experiment_id"), "kind": doc.get("kind", "ehd_wire"),
                            "evidence": doc.get("evidence"), "solver": doc.get("solver"), "summary": summary,
                            "fields": fields}}
        (DATA / "rom").mkdir(parents=True, exist_ok=True)
        (DATA / "rom" / "harness_ehd_latest.json").write_text(json.dumps(sanitize(out)))
        return {k: v for k, v in out.items() if k != "document"}


class External(Adapter):
    binaries: tuple = ()
    module = ""
    evidence = "high_fidelity_numerical_simulation"

    def available(self):
        for b in self.binaries:
            p = shutil.which(b)
            if p:
                return False, f"binary found at {p}, but no case-generation adapter is implemented yet"
        if self.module and importlib.util.find_spec(self.module):
            return False, f"python module {self.module} found, but no adapter is implemented yet"
        return False, f"not installed ({', '.join(self.binaries) or self.module} not found)"

    def run(self, params, progress=None):
        raise RuntimeError(f"{self.name} is NOT CONNECTED: {self.available()[1]}")


class Elmer(External):
    name, binaries = "elmer", ("ElmerSolver",)
    description = "Elmer FEM (3-D electrostatics / structure / thermal)"


class OpenFOAM(External):
    name, binaries = "openfoam", ("simpleFoam", "pimpleFoam")
    description = "OpenFOAM CFD (rotor/duct inflow, ground effect)"


class Moose(External):
    name, binaries = "moose", ("moose-opt", "combined-opt")
    description = "MOOSE multiphysics framework"


class FEniCSx(External):
    name, module = "fenicsx", "dolfinx"
    description = "FEniCSx / dolfinx custom PDEs"


class GetDP(External):
    name, binaries = "getdp", ("getdp",)
    description = "GetDP finite-element (magnetics / eddy currents)"


REGISTRY: dict[str, Adapter] = {a.name: a for a in (CanteraAir(), FemAddedMass(), HarnessEHD(), Elmer(), OpenFOAM(),
                                                     Moose(), FEniCSx(), GetDP())}
