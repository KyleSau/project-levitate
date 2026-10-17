# Project Levitate research log

Evidence tags: **[A]** analytical estimate · **[SN]** simplified numerical simulation · **[HF]** high-fidelity numerical · **[M]** physically measured.
No result in this log is **[M]** yet. Every endurance/thrust figure depends on assumptions listed in `/api/catalog` and must be measured (see VALIDATION_PLAN.md).

---

## 2026-10-16 — Session 1: platform, conventional baseline, ionic-wind study

### Environment / tooling
* Windows 11, Python 3.13 venv, Node 22. WSL has only `docker-desktop` (no Ubuntu) → Elmer, OpenFOAM, MOOSE, FEniCSx, GetDP, FEMM are **not installed**; adapters report NOT CONNECTED. COMSOL adapter is a documented optional placeholder.
* REA 6.4.0 (`rea` npm CLI) inspected: it is an app/binary reverse-engineering toolkit (decompile, web-bundle analysis, Android/Electron capture, evidence bundles). All solvers relevant to this project are open source with documented APIs, so REA was not needed; no binaries were analysed.
* Cantera not installed: gas properties needed so far (air, H2, He densities) follow from the ideal-gas law; no kinetics are involved yet.

### Verification of numerical code
| Check | Result |
|---|---|
| Corona solver, Laplace field at wire vs image-charge exact solution | agrees to 5 significant digits [SN] |
| Corona solver vs exact coaxial Kaptzov solution (12 kV, 50 µm wire, 10 mm cylinder) | error 7.5 % → 3.6 % on 2× refinement (first order, as expected for upwind); Richardson-extrapolated error 0.3 % |
| Charge conservation emitter→collector | ≤ 1e-7 relative |
| Wire-to-plane: T·μ/(I·d) | 0.86–0.95 (momentum relation T ≈ I d/μ holds) |
| Wire-to-plane thrust/power | 2.2–7.9 N/kW over 6–20 kV, 10 mm gap — same band as published wire-emitter data (Masuyama & Barrett 2013) |
| Coarse (48×96) vs fine (96×192) grid, thrust | 3–4 % difference → carried as 4 % discretisation uncertainty |
| EHD surrogate vs held-out solver runs (4 points off the training grid) | −1.6 % … −3.3 % |
| 6-DOF: hover thrust = weight at 0.3 m; full mission tracking | thrust within 1 %; RMS position error ≈ 6.5 mm |
| Automated tests | 31 passed (`backend/tests`) |

### Conventional micro-electric baseline (ducted fans in the deck)
* **Calibration against a known vehicle**: a Crazyflie-2.1-class configuration (4 × 7×16 mm coreless, 45 mm props, 250 mAh) evaluates to 28.2 g, 5.96 W, **7.2 min** nominal [A]; Bitcraze publishes 27 g and ~7 min. Hover power/endurance are consistent. The model gives T/W 1.32 where the real vehicle has ~2: **the peak-thrust model (derated battery C, catalog motor power) is conservative.**
* **Optimisation** (study #1, NSGA-II, 2000 candidates, objectives endurance/mass/stability/cost): 452 candidates satisfy all hard constraints at nominal assumptions. Pareto front dominated by:
  4 staggered 22 mm ducted fans (±3.4 mm lateral stagger), brushless 0702, 1S 550–660 mAh, EPP-foam/CF-skin deck 5–6 mm thick, 100 × 33–34 mm.
  Best: **30.3 g, 8.1 W hover, endurance 5.5 / 12.5 / 20.9 min (pessimistic / nominal / optimistic), T/W 1.68 nominal** [A]. All 5 leading designs fly the full take-off → translate → yaw → land mission stably in closed-loop 6-DOF (RMS error 6.5 mm) [SN, with analytical forces].
* **Verdict: MARGINAL.** Under pessimistic assumptions (FM 0.32, no duct benefit, motor efficiency −15 %) T/W falls to 1.08 and roll authority to 34 rad/s². Robust study #2 (1500 candidates, pessimistic) found **no design** meeting all constraints. Given the calibration point above, this is likely over-pessimistic on peak thrust, but it is unresolved until measured.
* Staggered layout insight: inline rotors along the 32 mm width cannot generate roll torque (rank-3 allocation). A ±3–4 mm stagger plus spin pattern (+,−,−,+) chosen by maximising the smallest singular value of the allocation matrix restores full rank; the narrow board's tiny roll inertia (~3e-6 kg m²) makes even a 3.4 mm moment arm give >100 rad/s².
* Underpowered vehicles (T/W 0.9) skim in ground effect at ~1 rotor radius but cannot climb (Cheeseman–Bennett gives up to +33 % thrust at z/R = 0.5). This is physical, not a bug.

### Ionic wind (EAD) — first alternative propulsion model
* Analytical bound [A]: space-charge-limited thrust density T/A ≤ 9/8 ε0 E², with T/P = 1/(μE). Over the 100 × 32 mm footprint a single stage would need a mean field of 3.1 MV/m (above air breakdown) to lift 30 g; at a realistic 0.8 MV/m sparkover limit the single-stage ideal is 20 mN vs 294 mN weight.
* Coupled corona solver + surrogate + full system mass model (HV converter, collectors, frames, battery) [SN]:
  * study #3, optimistic assumptions, ≤ 40 mm thickness: **best T/W = 0.157** (3 stages, 10 mm gaps, ~10 kV, 55 g).
  * study #4, nominal assumptions: **best T/W = 0.066**.
  * Even with an unrealistic 300 mm stack and optimistic assumptions: T/W 0.275.
* **Verdict: ionic wind cannot lift this board, by a factor of 6–15.** The HV converter specific power (0.15–1.2 kW/kg) and the E² thrust-density ceiling are the binding physics. Not dependent on any single uncertain assumption (sensitivity: all assumptions at their best give 0.16).

### Concept screening [A] (`/api/screening`)
Viable: ducted fans (baseline), open micro-props. Conditional: cyclorotor (uses full rectangular footprint as disk area — next numerical study), air-cushion / ground-effect mode (~2 W over concrete at 1 mm gap vs ~9 W hover; useless over grass), hybrid cushion + rotor. Not viable: ionic wind / EHD, electrostatic (attractive only), magnetic & Hendo-style eddy levitation (needs conductive track; lift fraction 1e-11 over sea water), H2 buoyancy (26 L needed), H2 fuel cell (~70 g for 7 W), flapping wings and piezo inside the outline, cold gas (24 s), acoustic levitation.

### Numerical uncertainties carried
* Rotor: figure of merit (0.32–0.52), duct effectiveness (0–0.8), motor efficiency (±15 %), battery usable energy (70–88 %): endurance spread ≈ 4× between pessimistic and optimistic.
* Corona: 4 % discretisation; electrode drag (0.5–0.9) and array shielding (0.6–1.0) are multipliers, not solved.
* 6-DOF: drag coefficient 1.1 assumed; rotor inflow/H-force not modelled; ground effect from Cheeseman–Bennett (open-rotor formula applied to ducts).

### Next steps
1. **Measure** (VALIDATION_PLAN.md): component masses; static thrust vs electrical power for 0702 + 22 mm fan open and in a printed duct → FM and duct effectiveness; battery discharge at 2–20 C → usable energy and max power. These collapse most of the 4× endurance uncertainty and settle the robust T/W question.
2. Add 2S cells / higher-C cells to the catalog and re-run the robust study.
3. Cyclorotor model (analytical, then OpenFOAM moving mesh once WSL Ubuntu is installed).
4. Air-cushion hybrid: fan pressure–flow map, skirt leakage model, mission-energy optimiser.
5. Corona: periodic multi-wire array solve (remove the array-interaction multiplier); couple body force into a flow solve for electrode drag.
6. Install WSL Ubuntu + OpenFOAM (duct inflow / ground-effect CFD) and Elmer (deck modal analysis) and wire them through the existing adapter interface.
