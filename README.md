# Project Levitate — research harness & lab

Experiment harness and web lab for a ~100 × 32 mm free-flying hoverboard.

## Run
```powershell
.\start.ps1          # API + built UI at http://127.0.0.1:8000
.\start.ps1 -Dev     # API on :8000 + Vite dev UI on http://127.0.0.1:5173
```
Tests: `cd backend; ..\.venv\Scripts\python.exe -m pytest -q` (31 tests, ~20 s).

## Layout
| Path | Contents |
|---|---|
| `backend/levitate/design.py` | parametric design schema, rotor layout, spin-pattern selection, allocation matrix |
| `backend/levitate/physics/` | rotor momentum theory + ground effect, battery, mass/CG/inertia, RK4 6-DOF + geometric controller |
| `backend/levitate/evaluate.py` | end-to-end hover feasibility at pessimistic/nominal/optimistic assumptions |
| `backend/levitate/solvers/ehd_bipolar.py` | coupled corona (ionic wind) solver + exact coaxial reference |
| `backend/levitate/ehd_board.py` | board-level ionic-wind system model on the solver surrogate |
| `backend/levitate/screening.py` | first-principles screening of 16 lift mechanisms |
| `backend/levitate/optimize.py` | Optuna NSGA-II/TPE studies, sensitivity, sweeps, goal planner |
| `backend/levitate/db.py`, `api.py` | SQLite experiment store, FastAPI |
| `frontend/` | React + TS + Vite + React Three Fiber lab |
| `schema/`, `docs/API_CONTRACT.md` | shared result schema with the visual flight lab workstream |
| `docs/RESEARCH_LOG.md` | findings, uncertainties, next steps |
| `docs/VALIDATION_PLAN.md`, `docs/SOLVERS.md` | physical test plan, solver adapters |

Parallel workstream: the visual flight-physics lab lives on branch `feature/levitate-visual-physics` (worktree `..\levitation-visual-lab`, ports 8100/5174).

Every result carries an evidence category; nothing here is a measured result yet.
