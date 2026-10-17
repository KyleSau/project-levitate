"""Small helpers: JSON sanitising (non-finite floats -> null) and version stamps."""
from __future__ import annotations

import math
import platform
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]          # visual-lab/
DATA = ROOT / "data"


def sanitize(o):
    if isinstance(o, dict):
        return {str(k): sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize(v) for v in o]
    if isinstance(o, np.ndarray):
        return sanitize(o.tolist())
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def code_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except Exception:
        return None


def versions() -> dict:
    import scipy
    from . import __version__
    out = {"visual_lab": __version__, "python": platform.python_version(), "numpy": np.__version__,
           "scipy": scipy.__version__, "code_sha": code_sha()}
    for mod in ("cantera", "skfem", "gmsh"):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, "__version__", "?")
        except Exception:
            out[mod] = None
    return out
