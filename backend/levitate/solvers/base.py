"""Solver adapter interface and registry.

The harness never calls a physics engine directly: it asks the registry for an adapter that can handle
a job kind, checks `available()`, and runs it. Each adapter declares the evidence category its results
carry. External engines (Elmer, OpenFOAM, GetDP, FEniCSx, COMSOL) plug in through the same interface.
"""
from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from ..provenance import Evidence


class SolverJob(BaseModel):
    kind: str                 # "rotor_design" | "ead_design" | "ehd_wire" | "flight_sim" | ...
    config: dict[str, Any]
    overrides: dict[str, float] | None = None


class SolverOutput(BaseModel):
    solver: str
    evidence: Evidence
    results: dict[str, Any]
    summary: dict[str, Any]
    verdict: str | None = None
    assumptions: dict[str, Any] | None = None
    valid: bool = True
    validity_notes: list[str] = []


class SolverAdapter(ABC):
    name: str = "abstract"
    handles: tuple[str, ...] = ()
    evidence: Evidence = Evidence.ANALYTICAL
    description: str = ""

    def available(self) -> tuple[bool, str]:
        return True, "built-in"

    @abstractmethod
    def run(self, job: SolverJob) -> SolverOutput: ...

    def info(self) -> dict[str, Any]:
        ok, why = self.available()
        return {"name": self.name, "handles": list(self.handles), "evidence": self.evidence.value,
                "available": ok, "status": why, "description": self.description}


def which_wsl(binary: str) -> str | None:
    """Look for a binary on Windows PATH, then inside the default WSL distro."""
    p = shutil.which(binary)
    if p:
        return p
    wsl = shutil.which("wsl")
    if not wsl:
        return None
    try:
        out = subprocess.run([wsl, "-e", "sh", "-lc", f"command -v {binary}"], capture_output=True, text=True,
                             timeout=8)
        path = out.stdout.strip()
        return f"wsl:{path}" if out.returncode == 0 and path else None
    except (subprocess.TimeoutExpired, OSError):
        return None
