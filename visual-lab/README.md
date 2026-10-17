# Project Levitate — Visual Flight Physics Lab (workstream B)

Interactive, physics-first 6-DOF simulation of a Tech-Deck-sized hoverboard (100 x 32 mm, 20 g).
Motion is produced only by integrated forces and torques; the browser replays the recorded state.

## Launch (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File visual-lab\start.ps1     # creates venv / node_modules on first run
# UI   http://127.0.0.1:5174
# API  http://127.0.0.1:8100/docs
powershell -ExecutionPolicy Bypass -File visual-lab\stop.ps1
```

Manual:
```powershell
cd visual-lab\backend;  ..\.venv\Scripts\python -m uvicorn vlab.api:app --port 8100
cd visual-lab\frontend; npm run dev        # port 5174, proxies /api -> 8100
```

## Tests
```powershell
cd visual-lab\backend; ..\.venv\Scripts\python -m pytest -q
cd visual-lab\frontend; npx tsc --noEmit; npm run build
```

See `docs/` for physics, validation and assumptions.
