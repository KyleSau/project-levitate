"""Additional API routes: solvers & fields, experiments, import/export, harness proxy, studies."""
from __future__ import annotations

import json

from fastapi import HTTPException
from fastapi.responses import Response

from . import store
from .api import J, app
from .sim import SimRequest, run
from .solvers.registry import REGISTRY
from .util import DATA
from .vehicle import default_vehicle


# ----------------------------------------------------------------------------- solvers & fields
@app.get("/api/solvers")
def solvers():
    return J([a.info() for a in REGISTRY.values()])


@app.post("/api/solvers/{name}/run")
def solver_run(name: str, params: dict | None = None):
    a = REGISTRY.get(name)
    if a is None:
        raise HTTPException(404, f"unknown solver {name}")
    ok, why = a.available()
    if not ok:
        raise HTTPException(409, f"{name} NOT CONNECTED: {why}")
    p = params or {}
    jid = store.submit(f"solver:{name}", p, lambda prog: a.run(p, prog))
    return J({"job": jid})


@app.get("/api/jobs")
def jobs():
    return J(store.list_jobs())


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = store.get_job(jid)
    if j is None:
        raise HTTPException(404, "no such job")
    return J(j)


@app.get("/api/rom/air")
def rom_air():
    p = DATA / "rom" / "air_properties.json"
    if not p.exists():
        raise HTTPException(404, "air ROM not built: run solver cantera_air")
    return Response(p.read_text(), media_type="application/json")


@app.get("/api/rom/added_mass")
def rom_added_mass():
    p = DATA / "rom" / "added_mass.json"
    if not p.exists():
        raise HTTPException(404, "added-mass ROM not built: run solver fem_added_mass")
    return Response(p.read_text(), media_type="application/json")


@app.get("/api/fields")
def fields_list():
    """Field overlays available from real solver runs (never synthesised)."""
    out = []
    p = DATA / "rom" / "added_mass_field.json"
    if p.exists():
        d = json.loads(p.read_text())
        for q, v in d["quantities"].items():
            out.append({"id": f"fem_added_mass:{q}", "title": d["title"], "quantity": q, "unit": v["unit"],
                        "source": d["source"], "valid": d["valid"], "plane": "yz", "attach": "board"})
    p = DATA / "rom" / "harness_ehd_latest.json"
    if p.exists():
        from .exchange import fields_from_doc
        d = json.loads(p.read_text())
        for f in fields_from_doc(d["document"]):
            out.append({"id": f"harness_ehd:{f['quantity']}", "title": f"Agent A corona solver {d['params']}",
                        "quantity": f["quantity"], "unit": f["unit"], "source": d["solver"], "valid": d["valid"],
                        "plane": "xz", "attach": "world"})
    return J(out)


@app.get("/api/fields/{fid}")
def field_get(fid: str):
    src, _, q = fid.partition(":")
    if src == "fem_added_mass":
        p = DATA / "rom" / "added_mass_field.json"
        if not p.exists():
            raise HTTPException(404, "not built")
        d = json.loads(p.read_text())
        return J({"title": d["title"], "source": d["source"], "quantity": q, "unit": d["quantities"][q]["unit"],
                  "u": d["grid"]["y"], "v": d["grid"]["z"], "values": d["quantities"][q]["values"], "plane": "yz",
                  "attach": "board", "valid": d["valid"]})
    if src == "harness_ehd":
        from .exchange import fields_from_doc
        p = DATA / "rom" / "harness_ehd_latest.json"
        if not p.exists():
            raise HTTPException(404, "not built")
        d = json.loads(p.read_text())
        f = [x for x in fields_from_doc(d["document"]) if x["quantity"] == q][0]
        # corona cross-section: lateral coordinate (u) along world x, height above collector (v) along world z
        return J({"title": "Agent A corona solver (wire-to-plane cross-section)", "source": d["solver"], "quantity": q,
                  "unit": f["unit"], "u": [x - (f["u"][0] + f["u"][-1]) / 2 for x in f["u"]], "v": f["v"],
                  "values": f["values"], "plane": "xz", "attach": "world", "valid": d["valid"], "frame": f["frame"],
                  "summary": d.get("summary")})
    raise HTTPException(404, fid)


# ----------------------------------------------------------------------------- experiments
@app.post("/api/experiments")
def exp_save(req: SimRequest):
    """Run a flight (synchronously) and save it."""
    res = run(req)
    eid = store.save_experiment(req.name, "flight_sim", res, req.model_dump(mode="json"))
    return J({"id": eid, "summary": res["summary"]})


@app.post("/api/experiments/save_result")
def exp_save_result(body: dict):
    res = body["result"]
    eid = store.save_experiment(body.get("name") or res.get("name", "flight"), body.get("kind", "flight_sim"), res)
    return J({"id": eid})


@app.get("/api/experiments")
def exp_list(limit: int = 200):
    return J(store.list_experiments(limit))


@app.get("/api/experiments/{eid}")
def exp_get(eid: int):
    r = store.load_experiment(eid)
    if r is None:
        raise HTTPException(404, "no such experiment")
    return J(r)


@app.delete("/api/experiments/{eid}")
def exp_delete(eid: int):
    return J({"deleted": store.delete_experiment(eid)})


@app.get("/api/experiments/{eid}/export")
def exp_export(eid: int, every: int = 1):
    from .exchange import export_flight
    r = store.load_experiment(eid)
    if r is None:
        raise HTTPException(404, "no such experiment")
    if "trajectory" not in r:
        raise HTTPException(409, "experiment is not a flight")
    return J(export_flight(r, experiment_id=eid, every=every))


@app.post("/api/export")
def export_result(body: dict):
    from .exchange import export_flight, validate_doc
    doc = export_flight(body["result"], experiment_id=body.get("experiment_id"), every=int(body.get("every", 1)))
    return J({"document": doc, "schema_errors": validate_doc(doc)})


def _import(doc: dict) -> dict:
    from .exchange import fields_from_doc, validate_doc, vehicle_from_doc
    out = {"schema_errors": validate_doc(doc), "evidence": doc.get("evidence"), "source": doc.get("source"),
           "kind": doc.get("kind"), "summary": doc.get("summary"), "experiment_id": doc.get("experiment_id"),
           "verdict": doc.get("verdict")}
    if doc.get("vehicle"):
        try:
            v, mc, notes = vehicle_from_doc(doc)
            out.update(vehicle=v.model_dump(mode="json"), mode=mc.model_dump(mode="json"), notes=notes)
        except ValueError as e:
            out["vehicle_error"] = str(e)
    out["fields"] = [{k: f[k] for k in ("quantity", "unit", "u_axis", "v_axis", "frame")} for f in fields_from_doc(doc)]
    return out


@app.post("/api/import")
def import_doc(doc: dict):
    """Import a levitate.experiment-result/v1 document (evidence passed through unchanged)."""
    return J(_import(doc))


# ----------------------------------------------------------------------------- harness proxy
def _need_harness():
    from . import harness
    if not harness.status()["connected"]:
        raise HTTPException(503, "Research harness: NOT CONNECTED")
    return harness


@app.get("/api/harness/experiments")
def harness_experiments(kind: str | None = None, verdict: str | None = None, limit: int = 50):
    h = _need_harness()
    rows = h.list_experiments(kind, limit=limit if not verdict else 1000)
    rows = rows if isinstance(rows, list) else rows.get("rows", [])
    if verdict:
        rows = [r for r in rows if r.get("verdict") == verdict][:limit]
    return J(rows)


def _harness_doc(exp_id: int) -> dict:
    import httpx
    h = _need_harness()
    try:
        return h.export_experiment(exp_id)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"harness GET /api/experiments/{exp_id}/export returned {e.response.status_code}")


@app.post("/api/harness/import/{exp_id}")
def harness_import(exp_id: int):
    return J(_import(_harness_doc(exp_id)))


@app.post("/api/simulate_imported/{exp_id}")
def simulate_imported(exp_id: int):
    """Import Agent A's design and fly the demo mission with its constraints (REALITY mode)."""
    from .exchange import vehicle_from_doc
    v, mc, _ = vehicle_from_doc(_harness_doc(exp_id))
    return J(run(SimRequest(vehicle=v, mode=mc, name=f"Agent A design #{exp_id} (demo mission)")))


# ----------------------------------------------------------------------------- studies
def _base_request(b: dict | None) -> dict:
    if b:
        return SimRequest(**b).model_dump(mode="json")
    from .modes import reality_preset
    return SimRequest(vehicle=default_vehicle(), mode=reality_preset("reality_baseline")).model_dump(mode="json")


@app.post("/api/sweep")
def sweep_ep(body: dict):
    """body: {base?: SimRequest dict, params?: [{path, values}], simulate?: bool} -> background job."""
    from .studies import default_frontier_request, sweep
    base = _base_request(body.get("base"))
    params = body.get("params")
    if not params:
        base, params = default_frontier_request(base)
    sim = bool(body.get("simulate"))
    jid = store.submit("sweep", {"params": params, "simulate": sim}, lambda prog: sweep(base, params, sim, True, prog))
    return J({"job": jid})


@app.post("/api/optimise")
def optimise_ep(body: dict | None = None):
    from .studies import optimise_endurance
    base = _base_request((body or {}).get("base"))
    return J({"job": store.submit("optimise_endurance", {}, lambda prog: optimise_endurance(base, prog))})


@app.post("/api/offline")
def offline_ep(req: SimRequest):
    """High-accuracy offline run (SciPy DOP853 per control interval) as a background job, saved as an experiment."""
    req = req.model_copy(deep=True)
    req.settings.integrator = "dop853"

    def work(prog):
        res = run(req, progress=prog)
        eid = store.save_experiment(req.name + " [DOP853]", "flight_sim", res, req.model_dump(mode="json"))
        return {"experiment_id": eid, "summary": res["summary"]}
    return J({"job": store.submit("offline_dop853", {"name": req.name}, work)})
