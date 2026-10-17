"""Persistence (SQLite under visual-lab/data/) and asynchronous background jobs.

experiments: saved flights / sweeps / imports (summary + config in SQLite; full result gzipped on disk).
jobs: solver runs, offline integrations, sweeps, optimisations run in a thread pool; progress is polled.
"""
from __future__ import annotations

import gzip
import json
import sqlite3
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from .util import DATA, sanitize

DB_PATH = DATA / "visual_lab.sqlite"
RESULTS = DATA / "results"
_db_lock = threading.Lock()


def _conn():
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.execute("""CREATE TABLE IF NOT EXISTS experiments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, name TEXT, kind TEXT, mode TEXT, evidence TEXT,
        verdict TEXT, summary TEXT, config TEXT, result_file TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, created REAL, kind TEXT, status TEXT, progress REAL, params TEXT, result TEXT,
        error TEXT, finished REAL)""")
    return c


def save_experiment(name: str, kind: str, result: dict, config: dict | None = None) -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    s = result.get("summary", {})
    with _db_lock:
        c = _conn()
        cur = c.execute("INSERT INTO experiments (created, name, kind, mode, evidence, verdict, summary, config) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (time.time(), name, kind, s.get("mode"), s.get("evidence"),
                         (result.get("feasibility") or {}).get("verdict") or result.get("verdict"),
                         json.dumps(sanitize({k: v for k, v in s.items() if not isinstance(v, (list, dict))})),
                         json.dumps(sanitize(config or {}))))
        eid = cur.lastrowid
        f = RESULTS / f"{eid}.json.gz"
        with gzip.open(f, "wt", encoding="utf8") as fh:
            json.dump(sanitize(result), fh, separators=(",", ":"))
        c.execute("UPDATE experiments SET result_file=? WHERE id=?", (f.name, eid))
        c.commit()
        c.close()
    return int(eid)


def list_experiments(limit: int = 200) -> list[dict]:
    with _db_lock:
        c = _conn()
        rows = c.execute("SELECT id, created, name, kind, mode, evidence, verdict, summary FROM experiments "
                         "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        c.close()
    return [{"id": r[0], "created": r[1], "name": r[2], "kind": r[3], "mode": r[4], "evidence": r[5], "verdict": r[6],
             "summary": json.loads(r[7] or "{}")} for r in rows]


def load_experiment(eid: int) -> dict | None:
    with _db_lock:
        c = _conn()
        r = c.execute("SELECT result_file FROM experiments WHERE id=?", (eid,)).fetchone()
        c.close()
    if not r or not r[0]:
        return None
    with gzip.open(RESULTS / r[0], "rt", encoding="utf8") as fh:
        return json.load(fh)


def delete_experiment(eid: int) -> bool:
    with _db_lock:
        c = _conn()
        r = c.execute("SELECT result_file FROM experiments WHERE id=?", (eid,)).fetchone()
        c.execute("DELETE FROM experiments WHERE id=?", (eid,))
        c.commit()
        c.close()
    if r and r[0] and (RESULTS / r[0]).exists():
        (RESULTS / r[0]).unlink()
    return bool(r)


# ------------------------------------------------------------------------------------------- jobs
_pool = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, dict] = {}


def submit(kind: str, params: dict, fn) -> str:
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "created": time.time(), "kind": kind, "status": "queued", "progress": 0.0, "params": params,
           "result": None, "error": None, "finished": None}
    _jobs[jid] = job

    def prog(x):
        job["progress"] = float(min(1.0, max(0.0, x)))

    def work():
        job["status"] = "running"
        try:
            job["result"] = sanitize(fn(prog))
            job["status"] = "done"
            job["progress"] = 1.0
        except Exception as e:  # noqa: BLE001
            job["status"] = "failed"
            job["error"] = f"{type(e).__name__}: {e}"
            job["trace"] = traceback.format_exc()[-2000:]
        job["finished"] = time.time()
        with _db_lock:
            c = _conn()
            c.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
                      (jid, job["created"], kind, job["status"], job["progress"], json.dumps(sanitize(params)),
                       json.dumps(job["result"])[:2_000_000] if job["result"] is not None else None, job["error"],
                       job["finished"]))
            c.commit()
            c.close()

    _pool.submit(work)
    return jid


def get_job(jid: str) -> dict | None:
    j = _jobs.get(jid)
    if j is not None:
        return j
    with _db_lock:
        c = _conn()
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        c.close()
    if not r:
        return None
    return {"id": r[0], "created": r[1], "kind": r[2], "status": r[3], "progress": r[4], "params": json.loads(r[5]),
            "result": json.loads(r[6]) if r[6] else None, "error": r[7], "finished": r[8]}


def list_jobs() -> list[dict]:
    return sorted(({k: v for k, v in j.items() if k != "result"} for j in _jobs.values()), key=lambda j: -j["created"])
