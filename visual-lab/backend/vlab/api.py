"""FastAPI backend of the Visual Flight Physics Lab (port 8100)."""
from __future__ import annotations

import json
import threading

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response

from . import __version__
from .modes import PRESETS, reality_preset
from .sim import SimRequest, run
from .util import sanitize, versions

app = FastAPI(title="Project Levitate - Visual Flight Physics Lab", version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=2000)

_cache: dict[str, dict] = {}
_lock = threading.Lock()


def J(obj, status: int = 200) -> Response:
    return Response(json.dumps(sanitize(obj), separators=(",", ":")), status_code=status, media_type="application/json")


@app.get("/api/health")
def health():
    return J({"status": "ok", "service": "visual_lab", "versions": versions()})


@app.get("/api/presets")
def presets():
    return J({"presets": PRESETS, "configs": {p: reality_preset(p).model_dump(mode="json") for p in PRESETS}})


@app.get("/api/demo")
def demo(preset: str = "ideal"):
    """Automated demo mission A-G for a named preset (cached; deterministic)."""
    if preset not in PRESETS:
        raise HTTPException(404, f"unknown preset {preset}")
    with _lock:
        if preset in _cache:
            return J(_cache[preset])
    res = run(SimRequest(mode=reality_preset(preset), name=f"demo mission ({preset})"))
    with _lock:
        _cache[preset] = res
    return J(res)


@app.post("/api/simulate")
def simulate(req: SimRequest):
    try:
        return J(run(req))
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/harness/status")
def harness_status():
    from . import harness
    return J(harness.status())
