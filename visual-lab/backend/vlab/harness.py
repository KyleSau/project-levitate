"""Client for Agent A's research harness API (http://127.0.0.1:8000), per docs/API_CONTRACT.md.

Everything degrades gracefully: when the harness is unreachable the lab reports
"Research harness: NOT CONNECTED" and keeps working stand-alone.
"""
from __future__ import annotations

import os
import time

import httpx

HARNESS_URL = os.environ.get("LEVITATE_HARNESS_URL", "http://127.0.0.1:8000")
_status_cache: dict = {"t": 0.0, "value": None}


def status(max_age_s: float = 5.0) -> dict:
    now = time.time()
    if _status_cache["value"] is not None and now - _status_cache["t"] < max_age_s:
        return _status_cache["value"]
    try:
        r = httpx.get(f"{HARNESS_URL}/api/health", timeout=1.5)
        r.raise_for_status()
        val = {"connected": True, "url": HARNESS_URL, "detail": "health ok", "health": r.json()}
    except Exception as e:  # noqa: BLE001 - any failure means not connected
        val = {"connected": False, "url": HARNESS_URL, "detail": f"NOT CONNECTED ({type(e).__name__}: {e})"[:300]}
    _status_cache.update(t=now, value=val)
    return val


def _get(path: str, timeout: float = 10.0, **params):
    r = httpx.get(f"{HARNESS_URL}{path}", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def list_experiments(kind: str | None = None, limit: int = 50) -> list[dict]:
    params = {"limit": limit}
    if kind:
        params["kind"] = kind
    return _get("/api/experiments", **params)


def export_experiment(exp_id) -> dict:
    """GET /api/experiments/{id}/export -> levitate.experiment-result/v1 (promised by Agent A).
    Raises httpx.HTTPStatusError (e.g. 404) if the endpoint does not exist yet."""
    return _get(f"/api/experiments/{exp_id}/export", timeout=20.0)


def solve_ehd_wire(voltage_kv: float, gap_mm: float, wire_radius_um: float) -> dict:
    r = httpx.post(f"{HARNESS_URL}/api/solve/ehd_wire",
                   json={"voltage_kv": voltage_kv, "gap_mm": gap_mm, "wire_radius_um": wire_radius_um}, timeout=300.0)
    r.raise_for_status()
    return r.json()


def solvers() -> list[dict]:
    return _get("/api/solvers")
