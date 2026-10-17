# Project Levitate — inter-workstream API contract (v1)

Two independent workstreams share this repository:

| Workstream | Owner | Directory | Branch | Ports |
|---|---|---|---|---|
| A — research harness (propulsion physics, solvers, optimisation, experiment DB) | original agent | `backend/levitate/`, `frontend/`, `data/`, `docs/RESEARCH_LOG.md` | `main` | API **8000**, UI **5173** |
| B — visual flight physics lab (6-DOF sim, controller, 3D lab, ideal vs reality modes) | parallel agent | `visual-lab/` only (own backend + frontend) | `feature/levitate-visual-physics` | API **8100**, UI **5174** |

Rules
* Workstream B never edits files outside `visual-lab/` (plus new docs under `visual-lab/docs/`). Workstream A never edits `visual-lab/`.
* Shared data format: `schema/experiment_result.v1.schema.json` (`levitate.experiment-result/v1`). Changes to the schema require a new version file, never an in-place edit.
* B must work standalone when A's API is down (show "research harness: NOT CONNECTED").
* Evidence categories must be passed through unchanged. B adds `hypothetical_ideal` for its unlimited-energy mode.

## Workstream A endpoints (http://127.0.0.1:8000)

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{status, versions}` |
| GET | `/api/experiments?kind=&verdict=&limit=` | list of rows `{id, kind, name, solver, evidence, verdict, summary}` |
| GET | `/api/experiments/{id}` | full row incl. `config`, `results`, `assumptions`, `versions` |
| GET | `/api/experiments/{id}/export` | **`levitate.experiment-result/v1`** document incl. `vehicle` (rigid body + actuators + power model) for rotor designs, `fields` for corona solver runs |
| POST | `/api/evaluate/rotor` | body = `Design` JSON (+`run_sim`) -> evaluation report |
| POST | `/api/solve/ehd_wire` | body `{voltage_kv, gap_mm, wire_radius_um}` -> coupled corona solver result with `fields` (phi, rho) |
| GET | `/api/solvers` | adapter registry with availability (`available: false` = NOT CONNECTED) |
| GET | `/api/screening` | concept screening table |

`vehicle` frame: x forward (board length), y left, z up, origin at deck geometric centre; inertia about CG.
