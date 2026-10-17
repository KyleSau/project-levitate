# Solver integration

All physics engines sit behind `levitate.solvers.base.SolverAdapter` (`name`, `handles`, `evidence`, `available()`, `run(job)`), registered in `levitate/solvers/adapters.py`. The harness selects an adapter by job kind and records the adapter name and evidence category with every experiment. `GET /api/solvers` shows connection status.

| Adapter | Status | Evidence | Use |
|---|---|---|---|
| `levitate.rotor_momentum_6dof` | built-in | analytical (+ simplified numerical when the 6-DOF mission is run) | momentum theory, mass/inertia, battery, LP control authority, RK4 6-DOF |
| `levitate.corona_bipolar_fv` | built-in | simplified numerical | coupled Poisson + ion drift (Kaptzov/Peek), bipolar coordinates, automatic 2× grid check |
| `levitate.ead_board_surrogate` | built-in | simplified numerical | board-level EAD system on a surrogate of the corona solver (`data/ehd_surrogate.json`, 72 solves, rebuild with `build_surrogate()`) |
| `elmer` | NOT CONNECTED | high-fidelity | 3D electrostatics, deck modal / thermal |
| `openfoam` | NOT CONNECTED | high-fidelity | duct inflow, ground effect, EHD body-force flow, cyclorotor |
| `getdp`, `femm` | NOT CONNECTED | high-fidelity | eddy-current / magnetostatic cross-checks |
| `fenicsx` | NOT CONNECTED | high-fidelity | custom PDEs (conda-forge, Linux/WSL) |
| `comsol` | optional placeholder | high-fidelity | documented below; nothing depends on it |

## Adding an engine
1. Subclass `SolverAdapter`; implement `available()` (binary on PATH or in WSL via `which_wsl`) and `run(job)`.
2. In `run`, write the case (Gmsh mesh + solver input) into a per-experiment directory, execute, parse outputs into SI scalars + optional regular-grid fields, and perform a convergence/validity check (two meshes or residual history). Return `SolverOutput(valid=..., validity_notes=[...])`.
3. Register it in `REGISTRY`. Results then flow into the DB, `/api/experiments/{id}/export` and the UI automatically.

## Optional COMSOL integration (future, licensed installs only)
`COMSOLAdapter` checks for the `comsol` launcher and the open-source `mph` Python client (which drives COMSOL through its documented Java API / LiveLink). To enable: install COMSOL with a valid licence, `pip install mph`, then implement `run()` by loading a parametrised `.mph` model, setting parameters from `job.config`, solving, and exporting the same `SolverOutput` structure. No COMSOL internals are reverse-engineered or reproduced.

## Installing the open-source engines (recommended next step)
```powershell
wsl --install -d Ubuntu-24.04
# inside Ubuntu:
sudo apt install gmsh elmerfem-csc    # Elmer from the elmerfem PPA if not in the distro
# OpenFOAM (openfoam.org): add the dl.openfoam.org apt repository, then apt install openfoam12
```
