"""SQLite experiment store. Every row records config, assumptions, solver, versions and code hash."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .provenance import config_hash, environment_versions

DEFAULT_DB = Path(os.environ.get("LEVITATE_DB", Path(__file__).resolve().parents[2] / "data" / "experiments.sqlite"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL,
    kind TEXT NOT NULL,              -- rotor_design | ead_design | ehd_wire | screening | ...
    name TEXT,
    study_id INTEGER,
    solver TEXT NOT NULL,
    evidence TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    assumptions_json TEXT,
    results_json TEXT NOT NULL,
    summary_json TEXT NOT NULL,      -- small flat dict for listing/comparison
    verdict TEXT,
    versions_json TEXT NOT NULL,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS ix_exp_kind ON experiments(kind);
CREATE INDEX IF NOT EXISTS ix_exp_study ON experiments(study_id);
CREATE TABLE IF NOT EXISTS studies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL,
    name TEXT NOT NULL,
    goal TEXT,
    kind TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL DEFAULT 0,
    result_json TEXT
);
"""


class ExperimentDB:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._versions = environment_versions()

    def add_experiment(self, *, kind: str, solver: str, evidence: str, config: dict, results: dict,
                       summary: dict, verdict: str | None = None, assumptions: dict | None = None,
                       name: str | None = None, study_id: int | None = None, notes: str | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO experiments (created, kind, name, study_id, solver, evidence, config_hash, config_json,"
                " assumptions_json, results_json, summary_json, verdict, versions_json, notes)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), kind, name, study_id, solver, evidence, config_hash(config), json.dumps(config),
                 json.dumps(assumptions) if assumptions else None, json.dumps(results, default=str),
                 json.dumps(summary, default=str), verdict, json.dumps(self._versions), notes))
            self._conn.commit()
            return int(cur.lastrowid)

    def list_experiments(self, kind: str | None = None, study_id: int | None = None, verdict: str | None = None,
                         limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        q = "SELECT id, created, kind, name, study_id, solver, evidence, config_hash, summary_json, verdict FROM experiments"
        cond, args = [], []
        for col, val in (("kind", kind), ("study_id", study_id), ("verdict", verdict)):
            if val is not None:
                cond.append(f"{col} = ?")
                args.append(val)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY id DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["summary"] = json.loads(d.pop("summary_json"))
            out.append(d)
        return out

    def get_experiment(self, exp_id: int) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        for k in ("config_json", "assumptions_json", "results_json", "summary_json", "versions_json"):
            if d.get(k):
                d[k.removesuffix("_json")] = json.loads(d.pop(k))
            else:
                d.pop(k, None)
        return d

    def count(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT kind, verdict, COUNT(*) c FROM experiments GROUP BY kind, verdict").fetchall()
        return {f"{r['kind']}:{r['verdict']}": r["c"] for r in rows}

    # ---------------------------------------------------------------- studies
    def create_study(self, name: str, kind: str, config: dict, goal: str | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO studies (created, name, goal, kind, config_json, status) VALUES (?,?,?,?,?,?)",
                (time.time(), name, goal, kind, json.dumps(config), "queued"))
            self._conn.commit()
            return int(cur.lastrowid)

    def update_study(self, study_id: int, status: str | None = None, progress: float | None = None,
                     result: dict | None = None) -> None:
        sets, args = [], []
        if status is not None:
            sets.append("status = ?"); args.append(status)
        if progress is not None:
            sets.append("progress = ?"); args.append(progress)
        if result is not None:
            sets.append("result_json = ?"); args.append(json.dumps(result, default=str))
        if not sets:
            return
        with self._lock:
            self._conn.execute(f"UPDATE studies SET {', '.join(sets)} WHERE id = ?", (*args, study_id))
            self._conn.commit()

    def list_studies(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM studies ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["config"] = json.loads(d.pop("config_json"))
            res = d.pop("result_json")
            d["result"] = json.loads(res) if res else None
            out.append(d)
        return out

    def get_study(self, study_id: int) -> dict[str, Any] | None:
        for s in self.list_studies():
            if s["id"] == study_id:
                return s
        return None
