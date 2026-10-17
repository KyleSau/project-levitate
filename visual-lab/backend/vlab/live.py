"""Live, real-time simulation over a WebSocket (/ws/live).

The server steps the same fixed-step RK4 Simulation as the offline runner, paced to wall-clock time x speed,
and streams every recorded 100 Hz frame. Client commands (goto / land / takeoff / gust push / pause / speed)
only change controller set-points or apply a declared external force; the motion is always the integrated
result. At the end the full recording is returned for replay, saving and v1 export.

Protocol (JSON):
  client -> {"type": "start", "request": SimRequest?, "speed": 1.0}
  server -> {"type": "header", ...static parts of a result...}
  server -> {"type": "frames", "channels": {name: [new values]}, "events": [...], "phases": [...]?, "t": sim time}
  client -> {"type": "cmd", "cmd": "goto", "rel": [dx, dy, dz], "yaw_deg": 90?}
            {"type": "cmd", "cmd": "land" | "takeoff"} ; {"type": "push", "force_n": [fx, fy, fz], "duration_s": 0.1}
            {"type": "pause"} | {"type": "resume"} | {"type": "speed", "value": 0.5} | {"type": "stop"}
  server -> {"type": "package", "result": full SimResult}   (after "stop" or when the session limit is reached)
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import WebSocket, WebSocketDisconnect

from .api import app
from .mission import Step
from .sim import SimRequest, Simulation, vehicle_payload
from .util import sanitize

LIVE_LIMIT_S = 180.0


def live_mission() -> list[Step]:
    return [Step(kind="idle", duration_s=0.5, segment="L", label="L  on ground"),
            Step(kind="arm", duration_s=0.5, segment="L", label="L  arm"),
            Step(kind="takeoff", duration_s=2.5, alt_m=0.25, segment="L", label="L  takeoff"),
            Step(kind="hold", duration_s=1e9, segment="L", label="L  live: hover, awaiting commands")]


def header(sim: Simulation) -> dict:
    rm, plant = sim.rm, sim.plant
    return {"type": "header", "name": "live session", "feasibility": sim.feas, "vehicle": vehicle_payload(rm, plant),
            "labels": rm.labels, "power_model": rm.power.model, "air": {"rho": rm.rho, "mu": rm.mu, "source": rm.air_source},
            "settings": sim.req.settings.model_dump(), "gains": sim.req.gains.model_dump(),
            "mode_config": sim.mc.model_dump(mode="json"),
            "integrator": f"RK4 fixed step (live, paced to wall clock), dt = {sim.dt*1000:.3g} ms",
            "summary": {"mode": rm.mode, "evidence": rm.evidence, "mass_kg": plant.m, "weight_n": plant.m * plant.g,
                        "failures": []},
            "phases": phases(sim), "events": []}


def phases(sim: Simulation) -> list[dict]:
    return [{"index": i, "segment": s.segment, "kind": s.kind, "label": s.label or s.kind} for i, s in enumerate(sim.ap.steps)]


@app.websocket("/ws/live")
async def live_ws(ws: WebSocket):
    await ws.accept()
    try:
        start = await ws.receive_json()
        req = SimRequest(**(start.get("request") or {}))
        req.settings.t_max_s = LIVE_LIMIT_S
        sim = Simulation(req, mission=live_mission(), demo_gust=False)
    except Exception as e:  # noqa: BLE001
        await ws.send_text(json.dumps({"type": "error", "message": f"{type(e).__name__}: {e}"}))
        await ws.close()
        return
    await ws.send_text(json.dumps(sanitize(header(sim))))
    speed = float(start.get("speed", 1.0))
    paused = False
    sent = 0
    ev_sent = 0
    n_phases = len(sim.ap.steps)
    last = time.perf_counter()
    target_t = 0.0
    try:
        while True:
            # handle all pending client messages (non-blocking, ~30 Hz loop)
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=0.03)
            except asyncio.TimeoutError:
                msg = None
            if msg:
                typ = msg.get("type")
                if typ == "stop":
                    break
                if typ == "pause":
                    paused = True
                elif typ == "resume":
                    paused = False
                    last = time.perf_counter()
                elif typ == "speed":
                    speed = max(0.05, min(4.0, float(msg.get("value", 1.0))))
                elif typ == "cmd":
                    why = sim.ap.command(sim.t, msg.get("cmd", ""), rel=msg.get("rel"), yaw_deg=msg.get("yaw_deg"),
                                         alt_m=msg.get("alt_m"))
                    if why:
                        await ws.send_text(json.dumps({"type": "notice", "message": why}))
                elif typ == "push":
                    f = msg.get("force_n", [0.0, 0.04, 0.0])
                    d = float(msg.get("duration_s", 0.1))
                    sim.extra_impulses.append((sim.t, d, f))
                    sim.ap.event(sim.t, "PUSH", f"external push {f} N for {d} s (world frame, at CG)")
            now = time.perf_counter()
            if not paused:
                target_t += (now - last) * speed
            last = now
            n_steps = min(int((target_t - sim.t) / sim.dt), 400)
            if n_steps > 0:
                def advance(k=n_steps):
                    for _ in range(k):
                        if not sim.step():
                            return False
                    return True
                alive = await asyncio.to_thread(advance)
                if not alive:
                    break
            ch = sim.rec.ch
            n = len(ch.get("t", []))
            out: dict = {"type": "frames", "t": sim.t, "paused": paused, "speed": speed}
            if n > sent:
                out["channels"] = {k: v[sent:n] for k, v in ch.items()}
                sent = n
            if len(sim.ap.events) > ev_sent:
                out["events"] = sim.ap.events[ev_sent:]
                ev_sent = len(sim.ap.events)
            if len(sim.ap.steps) != n_phases or "events" in out:
                out["phases"] = phases(sim)
                n_phases = len(sim.ap.steps)
            if "channels" in out or "events" in out or msg:
                await ws.send_text(json.dumps(sanitize(out), separators=(",", ":")))
        res = await asyncio.to_thread(sim.package)
        res["name"] = "live session recording"
        await ws.send_text(json.dumps(sanitize({"type": "package", "result": res}), separators=(",", ":")))
        await ws.close()
    except WebSocketDisconnect:
        return
