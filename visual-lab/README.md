# Project Levitate — Visual Flight Physics Lab (workstream B)

Interactive, physics-first 6-DOF simulation of a Tech-Deck-sized hoverboard (100 × 32 × 9 mm, 20 g).
Motion is produced only by integrated forces and torques (RK4, 1 ms; optional SciPy DOP853 offline);
the browser replays the recorded physical state — no animation paths, no easing. A live mode streams
the same integrator in real time over a WebSocket and accepts commands while flying.

## Launch (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File visual-lab\start.ps1       # first run creates .venv and node_modules
#   UI   http://127.0.0.1:5174
#   API  http://127.0.0.1:8100/docs
powershell -ExecutionPolicy Bypass -File visual-lab\stop.ps1
```
`start.ps1 -Preview` serves the production build instead of the Vite dev server.

Manual:
```powershell
cd visual-lab\backend ; ..\.venv\Scripts\python -m uvicorn vlab.api:app --port 8100
cd visual-lab\frontend; npm run dev        # 5174, proxies /api -> 8100
```
Optional: Agent A's research harness on http://127.0.0.1:8000 (`LEVITATE_HARNESS_URL` overrides). When it is
down the lab shows "Research harness: NOT CONNECTED" and works stand-alone.

## Tests
```powershell
cd visual-lab\backend ; ..\.venv\Scripts\python -m pytest -q
cd visual-lab\frontend; npx tsc --noEmit; npm run build
```

## UI
* **3D flight lab** — true-scale board, ground grid (1 cm / 10 cm), XYZ axes, altitude ruler; per-actuator force
  arrows (violet = HYPOTHETICAL in ideal mode), gravity, net force, contact, drag, disturbance, velocity, torque ring,
  CG marker, trail, controller set-point; attitude indicator; live dashboard (every value from the recorded frame,
  power/energy tagged ESTIMATE); timeline with segments A–G and events, play / pause / restart / 0.05–4× / frame
  step (← → keys) / scrubbing; charts with hover and click-to-seek; camera orbit + follow.
* **Parameters** — IDEAL vs REALITY, every constraint toggle, mass / CG (inertia recomputed from the mass
  distribution), actuator positions, environment (gravity, T, p, Cantera ROM air), disturbances & failures,
  controller gains; live feasibility analysis; "Run" restarts the mission from rest.
* **Feasibility frontier** — required vs available lift, T/W, power, endurance, payload, accelerations, authority,
  constraints with the binding toggle; per-manoeuvre required force/torque; sweeps (optionally simulation-verified)
  with Pareto front; endurance optimisation.
* **Solvers & fields** — registry (Cantera, Gmsh + scikit-fem, Agent A corona solver; Elmer / OpenFOAM / MOOSE /
  FEniCSx / GetDP shown NOT CONNECTED), background runs with validation tables, ROM plots, field heatmaps and 3D
  overlay.
* **Experiments** — save / replay / delete (SQLite), export `levitate.experiment-result/v1`, import v1 files, fly
  Agent A designs, queue offline DOP853 runs.

## API (port 8100)
| Method | Path | |
|---|---|---|
| GET | /api/health, /api/presets, /api/defaults | |
| GET | /api/demo?preset= | demo mission A–G (cached) |
| POST | /api/simulate, /api/analyse | SimRequest → flight / static feasibility |
| POST | /api/offline | DOP853 run as background job |
| GET/POST | /api/solvers, /api/solvers/{name}/run, /api/jobs/{id} | solver layer + jobs |
| GET | /api/rom/air, /api/rom/added_mass, /api/fields, /api/fields/{id} | ROMs and real field data |
| POST/GET/DELETE | /api/experiments[/{id}], /api/experiments/{id}/export | store + v1 export |
| POST | /api/import, /api/export | v1 import / export |
| WS | /ws/live | real-time interactive session (start, cmd goto/land/takeoff, push, pause, speed, stop → recording) |
| GET/POST | /api/harness/status, /api/harness/experiments, /api/harness/import/{id}, /api/simulate_imported/{id} | Agent A |
| POST | /api/sweep, /api/optimise | studies (background jobs) |

## Docs
`docs/PHYSICS.md` (equations, integrators, controller, modes), `docs/VALIDATION.md` (what every test checks),
`docs/ASSUMPTIONS.md` (parameters, sources, limitations).
