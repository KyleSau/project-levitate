# Project Levitate research log

## 2026-10-17 — Session 2: bench-test kit, human-scale study with debris limits

### Bench test (motor, fan, battery)
Not performed: it needs physical hardware. Prepared instead (docs/BENCH_TEST.md): parts list (~$60–90 stand), Arduino firmware
(HX711 thrust cell, INA226 power, optional tach and torque cell, current/voltage kill limits), PC logger (sweep, step, discharge
modes) and `levitate.bench` analysis. The analysis fits FM, motor efficiency, duct effectiveness, battery usable energy and internal
resistance, and motor time constant, then writes `data/measurements/assumptions_measured.json`, which the harness overlays as
MEASURED assumptions. The fitting code recovers known parameters from synthetic logs to within 2 % (tests; synthetic data is code
verification only, not a measurement). **No measured data exists yet.**

### Human-scale study (rider 90.7 kg = 200 lb), asphalt surface [A]
Model: `levitate.human_scale`, five concepts, mass closure, hold 1.3 × weight with any one lift unit failed, downwash/edge-jet
velocity as the debris metric. Three NSGA-II studies of 2000 designs each (#5 nominal, #6 must close at pessimistic assumptions,
#7 free flight only).

Physics finding (exact, no assumptions): in hover the jet's momentum flux equals the weight, so jet speed is fixed by jet area:
v = sqrt(W / (ρ A_exit)). For ~200 kg, keeping the jet below 12 m/s needs ≥ 8.5 m² of duct exit area; below 25 m/s needs ≥ 2 m².
Low debris and a rider-sized board are incompatible for any free-flying air-breathing vehicle.

| Concept | Board-sized (≤ 0.8 m²)? | Smallest closing design (nominal) | Robust (pessimistic)? |
|---|---|---|---|
| Battery-electric ducted fans | does not close (jet 180–260 m/s, >1 MW runaway) | 1.8 m², 282 kg, 107 kW, 45 m/s jet, 7.5 min | only at ~48 m² ($130k) |
| Battery-electric open rotors | does not close | 2.7 m², 132 kW, 56 m/s | only at ~41 m² |
| Ducted fans + engine-generator | does not close | 2.5 m², 94 kW, 33 m/s, 14 min | none closed |
| Micro turbojets | **closes**: 0.6 m², ~162 kg, 3 min | — | yes, but 500 m/s, ~650 °C exhaust |
| **Air cushion (skirted plenum)** | closes at 0.34 m² but 94 m/s edge jet and a tiny stance | **~1.0 m² deck (≈1.6 × 0.64 m): 138 kg, 3 kW, 49 m/s edge sheet, ~19 min, ~$9k** | **yes** |

* The air-cushion board is the only concept that is board-sized, closes under pessimistic assumptions, needs single-digit kW and
  keeps debris to a thin horizontal sheet at the skirt hem. It does not fly: it rides millimetres to centimetres above the surface.
  Larger decks cut the edge jet (25 m/s at ~4 m², 12 m/s at ~19 m²) and power (≤ 1 kW).
* Short grass (30 mm roughness) multiplies cushion power ×4–7 with this hem-gap model; real hovercraft use deep finger skirts that
  ride on the grass, which this model does not capture. Needs a skirt-leakage experiment.
* Electric free flight works only as a platform (≥ ~2 m² of fans) and is not robust: pessimistic battery specific power (1 kW/kg)
  and fan efficiency make the mass closure run away. Battery-pack power density is the measurement that matters most here.
* Economics (nominal, parts only): air-cushion board ~$9–15k, about $0.10–0.30 of electricity per 20 min ride; electric free-flight
  platform $25–130k for 7–8 min; turbojet board ~$50k plus ~$40 of fuel per 3 min flight.

### Next steps
1. Bench test (kit ready) for the mini board.
2. Air-cushion line: scale model (1:4, ~2 kg) of a skirted plenum board to measure leakage Cd, skirt behaviour on asphalt/grass/water,
   and edge-jet velocity with a pitot/hot-wire. This validates the one human-scale concept that closes robustly.
3. Rider stability on a cushion board (roll/pitch stiffness from plenum geometry, compartmented skirts) — add to the 6-DOF model.
4. Free-flight platform: battery cell discharge-power test; ground-effect benefit of hovering low over the platform's own footprint.


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
