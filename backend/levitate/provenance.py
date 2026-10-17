"""Evidence categories, assumptions with uncertainty, and reproducibility metadata.

Every number that enters a model is either a physical constant, a design variable,
or an `Assumption`. Assumptions carry a source, a verification status and a
low/nominal/high band so results can be reported as ranges rather than as facts.
"""
from __future__ import annotations

import hashlib
import json
import platform
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Evidence(str, Enum):
    ANALYTICAL = "analytical_estimate"
    SIMPLIFIED_NUMERICAL = "simplified_numerical_simulation"
    HIGH_FIDELITY_NUMERICAL = "high_fidelity_numerical_simulation"
    MEASURED = "physically_measured"


class SourceStatus(str, Enum):
    PHYSICAL_LAW = "physical_law"            # follows from conservation laws / exact theory
    PEER_REVIEWED = "peer_reviewed"          # published measurement or validated model
    CATALOG_NOMINAL = "catalog_nominal"      # manufacturer/retailer spec, not verified by us
    ENGINEERING_JUDGMENT = "engineering_judgment"  # plausible estimate, must be measured
    MEASURED = "measured"                    # measured in our lab


class Assumption(BaseModel):
    key: str
    description: str
    nominal: float
    low: float
    high: float
    unit: str
    # which end of the band is favourable to the design ("high" = larger value helps)
    favourable: Literal["high", "low"]
    status: SourceStatus
    source: str

    def pick(self, scenario: str) -> float:
        if scenario == "nominal":
            return self.nominal
        good = self.high if self.favourable == "high" else self.low
        bad = self.low if self.favourable == "high" else self.high
        if scenario == "optimistic":
            return good
        if scenario == "pessimistic":
            return bad
        raise ValueError(f"unknown scenario {scenario}")


SCENARIOS = ("pessimistic", "nominal", "optimistic")


class AssumptionSet(BaseModel):
    items: dict[str, Assumption] = Field(default_factory=dict)

    def add(self, a: Assumption) -> None:
        self.items[a.key] = a

    def values(self, scenario: str = "nominal", overrides: dict[str, float] | None = None) -> dict[str, float]:
        vals = {k: a.pick(scenario) for k, a in self.items.items()}
        if overrides:
            for k, v in overrides.items():
                if k not in vals:
                    raise KeyError(f"override for unknown assumption '{k}'")
                vals[k] = v
        return vals


def code_fingerprint() -> str:
    """SHA-256 over all package source files: pins results to the exact model code."""
    root = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.py")):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def environment_versions() -> dict[str, str]:
    import numpy
    import scipy

    from . import __version__

    out = {
        "levitate": __version__,
        "code_sha": code_fingerprint(),
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "platform": platform.platform(),
    }
    try:
        import optuna

        out["optuna"] = optuna.__version__
    except ImportError:
        pass
    return out


def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:16]
