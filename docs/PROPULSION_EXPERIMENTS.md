# Propulsion experiments: cold-gas skateboard, cold-gas hoverboard, chemical-rocket hoverboard

Project Levitate, workstream C, 2026-10-17. Rider 90.7 kg (200 lb) unless stated.

> **Computational simulation only.** Nothing in this document or in the code is a design, build, fuelling or operating
> guide. Thrusters and engines are modelled as black boxes with published or explicitly assumed external parameters.
> Compressed gas at hundreds of bar and chemical rocket propulsion can kill; any physical validation of these ideas must
> be **professionally reviewed, unmanned and safely contained** (remote operation, blast/fragment containment).

Evidence tags as in `RESEARCH_LOG.md`: **[A]** analytical · **[SN]** simplified numerical simulation · **[M]** measured.
Nothing here is [M].

---

## 1. Summary

| Concept | Best result found (nominal assumptions) | Verdict |
|---|---|---|
| **Cold-gas boosted skateboard** | One 6.8 L / 300 bar carbon cylinder (8.6 kg incl. air and valves) gives ~110 N for ~10 s: **+2.2 m/s** top speed over the electric board (12.9 vs 10.7 m/s) [SN]. Study best: +7.3 m/s with 13.7 kg, but that is 18 m/s, far above the ~13 m/s speed-wobble onset. Below 13 m/s the gain is ≤ +2.2 m/s; the useful effect is acceleration (0–10 m/s in 4.5 s vs 5.2 s). | Works physically, poor value: **~0.5 % of the compressor electricity becomes thrust work on the board**; adds a vessel-burst hazard (0.18 kg TNT eq. per 6.8 L bottle). |
| **Cold-gas hoverboard** | Default (4 × 9 L, 300 bar, 144 kg gross, 1.87 kN installed): **4.1 s** hover [A], 3.1 s flight in the 6-DOF mission before the reserve abort [SN]. Best ≤ 200 kg gross: **13 s**; longest found: 23.5 s at 597 kg. Hard ceiling for any tank size: **~23 s (Type 3) to ~43 s (Type 4)**. | **Not viable** for a ridden vehicle. Tens of MJ of stored gas under the rider, ~0.4–0.8 MW of jet power, cryogenic exhaust. |
| **Chemical-rocket hoverboard (theoretical, black box)** | Monoprop-class, 30 kg propellant, 151 kg gross: **30 s** hover [A]; 6-DOF mission completed [SN]. Biprop-class best ≤ 200 kg: 96 s; longest 152 s at 289 kg. | Physically flies, but **~149 dB at the rider's ears, 600–1500 °C jets, 1–3 MW of jet power** and fire/toxic hazards not even modelled. Not a candidate. |
| Comparison | Air-cushion board LV-H1: 7.5 kW, ~40 min on 5.4 kWh; electric ducted-fan platform 107 kW, 7.5 min; micro-turbojet board 3 min with ~650 °C exhaust (existing results). | Air cushion remains the only human-scale hover concept with a usable ride time and safe power level. |

Key physics behind the verdicts (exact, no tuning):
1. **Hover time with propellant-proportional tank mass is capped**: with `k` kg of tank per kg of gas, hover time
   `t ≤ Isp·cos(cant)·ln((1+k)/k)` however large the tanks. Air, `Isp` ≈ 55–60 s, Type 3 cylinders `k` ≈ 1.7 → **≤ 23 s**.
2. **A thin fast jet is an inefficient way to hold weight**: hover jet power = ½·T·uₑ. Cold gas (uₑ ≈ 550 m/s) needs
   ~420 kW for a 144 kg board; a rocket (uₑ 1.4–2.5 km/s) 1–2 MW; the air cushion 7.5 kW.
3. **Propulsive efficiency at skateboard speed is tiny**: thrust work / jet kinetic energy ≈ 2v/(v+uₑ) ≈ 2–5 %.
   The boost cannot create energy; the ledger closes to 1e-8 and jet KE ≤ stored exergy in every run.

---

## 2. Tesla Roadster cold-gas demonstration (October 2026): what is public

Searched 2026-10-17. Tesla's next-generation Roadster was unveiled on **15 Oct 2026** at a SpaceX facility near
Waco / McGregor, Texas, with "cold-gas thrusters developed in collaboration with SpaceX". Everything below is **press
reporting of verbal/marketing claims**; no Tesla or SpaceX technical document was found.

| Item | Reported | Source |
|---|---|---|
| Date, place | 15 Oct 2026 (Thursday evening), SpaceX facility, Waco / McGregor TX | Fox Business; Yahoo Finance |
| Demo | ramp with fan "suction", inverted section, airborne flip/barrel roll, hop over parked cars | Fox Business; Electrek; Aviation Week ("a short hop … an axial roll") |
| Storage | 200 L on the "Thrust" trim; an additional 400 L on the "Rocket" trim (replacing the second seat) | Electrek (as reported) |
| Pressure | 10,000 psi (690 bar) | Electrek (stated, source unclear) |
| Thrust | "80 kN" rear thrusters (Electrek); "4–5× the force the tires can" (Tesla on X) | Electrek; Teslarati; Fox Business |
| Thruster layout | four rear ports; Rocket trim adds four downward corner thrusters + two front yaw thrusters | Electrek |
| Refill | "six or seven hours" now, 30 min target | Electrek |
| 0–60 mph | 0.81 s (live, timer issues), 1.0 s recorded, "<0.9 s" Thrust trim, "<0.59 s" Rocket trim | Electrek; Teslarati; InsideEVs (via search) |
| Duration | "a few seconds" at full power (Electrek author's inference) | Electrek |
| Conflicting | some coverage says 10 thrusters fed by 600 L; unconfirmed (one search summary only) | — |

**Not published:** thruster Isp, nozzle/valve data, vessel mass/type, gas temperature, mass flow, burn time, test data.
**Not verified by us:** any of the numbers above.

Plausibility check with our model (our estimate, not Tesla data): 200 L at 690 bar and 293 K holds **106 kg of air**
(real gas, Z = 1.55; an ideal-gas estimate would wrongly give 164 kg). At Isp 50–70 s that is 52–73 kN·s of impulse,
i.e. **0.65–0.9 s at 80 kN** — consistent with sub-second 0–60 claims and "a few seconds" of use. At a Type-4-class
PV/m of 98 kJ/kg the vessel would weigh ~140 kg; the stored expansion energy is ~19 MJ (≈ 9 kg TNT equivalent, 1 psi
radius ~28 m). Nothing in our models uses Tesla numbers as inputs; the cold-gas models are generic physics
("Tesla-inspired").

Sources:
[Electrek, 15 Oct 2026](https://electrek.co/2026/10/15/an-updated-technical-look-at-teslas-kick-flipping-0-60-in-1s-next-gen-roadster/) ·
[Aviation Week](https://aviationweek.com/aerospace/emerging-technologies/tesla-demos-flying-roadster-powered-spacex-cold-gas-thrusters) ·
[Fox Business](https://www.foxbusiness.com/technology/teslas-new-roadster-makes-flying-debut-hitting-60-mph-under-second) ·
[Teslarati](https://www.teslarati.com/tesla-roadster-downforce-fan-system/) ·
[Yahoo Finance](https://finance.yahoo.com/markets/stocks/article/something-extraordinary-tesla-roadster-wows-with-compressed-air-thrusters-for-limited-flight-153039576.html) ·
[InsideEVs](https://insideevs.com/news/812151/2027-tesla-roadster-price-specs-release-date/) (fetch failed; figures via search summary) ·
[The Drive, 2018 background](https://www.thedrive.com/news/25884/elon-musk-says-next-gen-roadster-will-hover-in-the-air-using-spacex-tech).

---

## 3. Models (all in `backend/levitate/propulsion/`, SI units)

### 3.1 Gas and tank — `gas.py`, `coldgas.py`
* **Real gas matters above ~150 bar.** Air at 293 K: Z = 0.99 (100 bar), 1.03 (200), 1.10 (300), 1.55 (690).
  An ideal-gas model over-states stored mass by 10.5 % at 300 bar and 55 % at 690 bar. Tables of p, u, h, s, Z on a
  (T, ρ) grid (135–400 K, 0.02–650 kg/m³) were generated with CoolProp 8 from the reference Helmholtz EOS (Lemmon et al.
  2000 for air, Span et al. 2000 for N₂) in a worktree-only venv (`gen_realgas.py`); interpolation error vs CoolProp
  < 0.3 % (tested). The browser uses every second density point (impulse within 1 % of the full table, tested).
* **Tank**: lumped gas, `dm/dt = −ṁ`, `dU/dt = −ṁh + Q`, wall `m_w c_w dT_w/dt = −Q + h_ext A (T_amb − T_w)`.
  Modes: adiabatic (remaining gas is isentropic, rate-independent), isothermal, heat-transfer (default, `h` = 100
  W/m²K), polytropic (ideal gas, analytic comparison). Real-gas adiabatic blowdown cools much faster than ideal
  (199 K vs 222 K at half mass from 300 bar) and reaches the edge of the table (135 K, near the air critical point)
  after ~75 % of the mass; the model then stops the thruster and flags it.
* **Regulator**: feed pressure `min(throttle·p_reg, p_tank − dropout)`; constant thrust until the tank falls to
  `p_reg + dropout`, then decay. Joule–Thomson cooling across the regulator neglected.
* **Nozzle**: choked `ṁ = C_d A* p₀ √(γ/(Z R T₀)) (2/(γ+1))^((γ+1)/(2(γ−1)))`, isentropic expansion to the exit area
  ratio, `F = η_CF (ṁ uₑ + (pₑ − pₐ) Aₑ)`, unchoked orifice flow below the critical ratio, separation flag at
  pₑ < 0.4 pₐ. Ideal Isp of air: 78 s (vacuum, infinite expansion), 61.7 s (sea level, 30 bar, matched nozzle); the
  model delivers 57–60 s at the regulator and 47–55 s averaged over a real blowdown.
* **Tank mass** from the pressure-vessel performance factor PV/m at service pressure (§5).
* **Energies**: stored exergy (max work any device can extract), burst energy (isentropic expansion of the stored
  mass, ×2 for a surface burst → TNT equivalent → Kinney–Graham overpressure radii for 1 psi and 5 psi), refill work
  (thermodynamic minimum = closed exergy; compressor electricity = ∫ flow exergy dm / isothermal efficiency 0.43,
  calibrated to a breathing-air compressor class: ~0.9–1.1 MJ_e per kg of air).

### 3.2 Rocket black box and comparator — `rocket.py`, `hazards.py`
* Engine = {F, Isp, throttle range, can stop?, max starts, start delay, exit temperature, T/W, tankage fraction};
  ṁ = F/(Isp·g₀). Classes: monoprop-class (Isp 140 s, 30–100 %, unlimited restarts), biprop-class (250 s,
  40–100 %, 3 restarts), solid-class (200 s, fixed thrust, cannot stop). Nothing about propellants or hardware.
* Jet hazards: momentum-equivalent diameter, round-jet decay (B_u = 5.8, B_T = 5.0), impinging wall-jet outwash,
  noise from NASA SP-8072 (acoustic efficiency 0.5 % rocket, 0.3 % cold gas, hemispherical spreading).
* Air-breathing micro-turbojet (from `human_scale.py`): TSFC 0.16 kg/(N·h) ⇒ fuel-only equivalent Isp ≈ 2300 s,
  i.e. 9–16× the rockets, because the reaction mass (air) is not carried.

### 3.3 Skateboard — `skateboard.py`
Planar: variable mass, rolling resistance `Crr·N`, drag `½ρC_dA v|v|`, dual hub motors (torque 240 N at the wheels,
2 × 1.5 kW peak, 11 m/s top, 85 % efficient, regen 65 %), braking limited by μ·N, traction limit on the driven rear
axle, thrust line height/angle, quasi-static pitch load transfer with wheelie and nose-over modes (rotation about the
contact), rider as an inverted pendulum whose ankle/hip torque is limited by the centre-of-pressure levers (heel
0.08 m, toe 0.15 m) with 0.15 s perception lag and optional anticipation (leaning into self-commanded accelerations),
dead-man cut-off, ground-frame energy ledger.

### 3.4 Hoverboards — `hover.py`
6-DOF rigid body with mass, CG and inertia recomputed every step from the parts list (gas/propellant at the tank
position, so the CG moves as it is used), 4 corner thrusters canted 10° for yaw authority, gravity, drag, rotational
damping, penalty-spring ground contact with friction, cascaded autopilot (position PID → thrust vector → quaternion
attitude PD → 4×4 allocation with attitude priority and saturation) flying lift-off → hover → 2 m translate → stop →
90° yaw → land, abort to landing on a propellant reserve, and failure detection (cannot lift off, ran dry in flight
with impact speed, lost control). Thrust is auto-sized to T/W = 1.3 at the start mass.

### 3.5 Browser model
`sim/propulsion/site/propulsion.js` is a line-by-line port (same fixed-step semi-implicit Euler, 1 ms, same tables
via `rom_data.js` generated by `python -m levitate.propulsion.rom`). It reproduces Python reference runs
(`sim/propulsion/reference/*.json`) to < 1e-6 relative error in every recorded state and identical event sequences.
The React tab imports the same two files.

---

## 4. Validation

`backend/tests/test_propulsion_*.py` — **38 tests, all pass** (full suite 80 passed incl. the 42 pre-existing).
`node sim/propulsion/test_propulsion.js` — **79 checks, all pass**.

| Check | Result |
|---|---|
| Ideal isothermal blowdown vs p₀e^(−t/τ) (solve_ivp / fixed-step) | < 1e-4 / < 3e-3 relative |
| Ideal adiabatic blowdown vs p₀(1+(γ−1)/2·t/τ)^(−2γ/(γ−1)) | < 1e-4 / < 3e-3 |
| Real-gas adiabatic blowdown follows the isentrope through the fill state | ≤ 1.5 K |
| Impulse = mass expelled × uₑ (isothermal, vacuum) | 0.2 % |
| Regulated thrust constant until set point, decays after | yes |
| Z(air, 300 K) vs reference EOS at 100–690 bar | ≤ 0.3 % |
| Tank mass from PV/m reproduces Toyota Mirai tanks (122.4 L, 700 bar → 87.5 kg) | 1 % |
| Kinney–Graham 1 psi radius for 1 kg TNT | 13.4 m (test band 12–20 m around published scaled-distance values) |
| Skateboard coast-down `t = v₀/(Crr g)`; drag decay `v₀/(1+k v₀ t)` | 1e-3 |
| Variable-mass rocket equation Δv = uₑ ln(m₀/m₁) (skateboard; 6-DOF ∫F/m dt) | 2e-3 / 1e-3 |
| Fixed-step skateboard boost vs SciPy LSODA of the same ODE | < 0.5 % speed |
| 6-DOF free fall with drag vs solve_ivp | 3 cm after 2.5 s (Euler O(dt)) |
| Hover time vs Isp·cos·ln(m₀/m₁) for constant T/W | between burn-out − lift-off and burn-out − ignition, within 3 % |
| CG shift with propellant use vs mass-moment formula | 1e-12 |
| Energy ledger closure (default track run, boost runs) | 3e-8 … 1e-5 |
| No free energy: jet KE ≤ exergy drawn; vehicle KE + losses ≤ jet KE | always (e.g. 3.6 kJ ≤ 223 kJ ≤ 838 kJ) |
| Failure cases: T/W 0.9 cannot lift off; run dry → falls; solid motor cannot hover; min throttle 95 % cannot hover | as expected |
| JS vs Python (6 reference runs, skateboard + 3 hover) | < 1e-6, identical events |

---

## 5. Assumptions (nominal, low–high, status, source) — full list in `assumptions.py` and `/api/propulsion/assumptions`

| Key | Nominal (range) | Status | Source |
|---|---|---|---|
| PV/m steel/Al cylinder | 18 kJ/kg (15–22) | catalog | AL80 11.1 L/207 bar/14.2 kg; 12 L/232 bar steel ~14.5 kg |
| PV/m Type 3 carbon (SCBA) | 44 kJ/kg (36–52) | catalog | 6.8 L/300 bar SCBA listed 6.8–7.1 kg filled (Scott/3M, Dräger retail) |
| PV/m Type 4 | 98 kJ/kg (80–110) | catalog | Toyota Mirai 122.4 L, 70 MPa, 87.5 kg |
| Nozzle C_d / η_CF | 0.97 / 0.95 | literature | Sutton & Biblarz |
| Regulator dropout | 5 bar (2–15) | judgment | — |
| Wall h during blowdown | 100 W/m²K (30–300) | judgment | fast fill/defuel literature order |
| Compressor isothermal eff. | 0.43 (0.30–0.60) | catalog | ~100 L/min FAD to 300 bar at ~2.2 kW class |
| Electricity | $0.20/kWh | judgment | — |
| Isp monoprop / biprop / solid (black box) | 140 / 250 / 200 s | literature | Bell Rocket Belt (~21 s flights), Sutton & Biblarz |
| Min throttle monoprop / biprop | 0.30 / 0.40 | judgment/literature | — |
| Acoustic efficiency rocket / cold gas | 0.005 / 0.003 | literature / judgment | NASA SP-8072 |
| Crr urethane | 0.015 (0.008–0.03) | judgment | reported ranges |
| CdA upright / crouch | 0.60 / 0.35 m² | literature | Wilson, *Bicycling Science* |
| μ urethane | 0.70 (0.5–0.9) | judgment | — |
| Hub drive: force / power / top speed / pack | 240 N / 2×1.5 kW / 11 m/s / 400 Wh | catalog | consumer dual-hub boards |
| Rider levers heel / toe, lag | 0.08 / 0.15 m, 0.15 s | literature | Winter, *Biomechanics*; postural latencies |
| Hover T/W margin | 1.30 (1.2–1.5) | judgment | same rule as `human_scale` |
| Board structure / avionics | 12 / 3 kg | judgment | — |

Hazard thresholds: jet 15 m/s; gas +40 K / −50 K from ambient; overpressure 6.9 kPa (1 psi) and 34.5 kPa (5 psi,
eardrum); 140 dB impulsive peak limit, 120 dB pain.

---

## 6. Results

### 6.1 Cold-gas boosted skateboard [SN]
Default (one 6.8 L Type-3 cylinder at 300 bar, 30 bar regulator, 6 mm throat, thrust line 0.15 m): 2.19 kg of air
(ideal gas would claim 2.42 kg), cylinder 4.6 kg, system dry 6.4 kg, 109 N, Isp 57 s at start / 47.7 s mean,
10.0 s boost, 920 N·s. Track run (3 s wheels, 10 s wheels + boost, coast, brake): top speed **12.9 m/s vs 10.7 m/s**
for the same board without the tank; 108.5 kg total; parts ~$2.5k; refill 0.55 kWh (~$0.11).
Energy: 218 kJ of jet KE from 802 kJ of tank exergy; only 4.7 % of the jet KE becomes thrust work on the board.
Hazards: 371 kJ burst energy (0.18 kg TNT eq.; 1 psi to 7.5 m, 5 psi to 2.6 m); jet > 15 m/s for 3 m; ~128 dB at 1 m;
−150 °C exhaust at the exit; a stuck-open valve pushes 0.10 g until empty.
Rider: a standing rider resists only ~0.08 g of *unexpected* push (heel lever/CoM height). A surprised rider (no anticipation,
instant valve) is thrown off when the boost starts while accelerating on the wheels (wheelie then fall, tested);
braking at ~0.25 g (0.35 of the traction limit) noses the board over with the default stance, 0.21 g does not.

Study `coldgas_skateboard` (NSGA-II, 160 designs, objectives: speed gain ↑, tank+air mass ↓, cost ↓; constraints:
rider stays on, push ≤ 0.2 g): 113 feasible; 47 rejected for rider fall/nose-over, 30 for too much push.
Largest gain +7.3 m/s (18 m/s, 13.7 kg, 23 s, $3.7k); best +0.59 m/s per kg of propulsion mass. Constraining top speed to
the ~13 m/s wobble onset leaves ≤ +2.2 m/s. The real benefit is acceleration: 0–10 m/s in 4.5 s vs 5.2 s.

### 6.2 Cold-gas hoverboard [A] + [SN]
Default (4 × 9 L Type 3, 300 bar, 40 bar regulator): 144 kg gross, 11.6 kg air, 1.87 kN installed (T/W 1.3), Isp 59.5 s,
**4.1 s** analytic hover; the 6-DOF autopilot lifts off, hovers and aborts to land on the 1.5 s reserve (3.1 s in the
air); without reserve it runs dry and falls (tested). Hover jet power ~420 kW. 2.0 MJ of stored gas (0.94 kg TNT eq.;
1 psi to 13 m). Ceiling for any amount of Type-3 tankage: 22.7 s.

Study `coldgas_hoverboard` (400 designs; volume, number of tanks, 150–700 bar, construction, regulator, T/W):
best hover by gross-mass limit **≤ 150 kg: 7.2 s; ≤ 200 kg: 13.1 s; ≤ 250 kg: 16.9 s**; longest 23.5 s at 597 kg
(8 × 57 L Type 4 at 568 bar, 222 kg of air, 14 MJ burst energy, ~$74k). All 5 Pareto designs completed the 6-DOF mission.
Scalability (best design re-sized): hover 29 s with no rider, 23.5 s at 90.7 kg, 21.5 s at 136 kg — thrust and tanks
scale with total mass, so payload is not the main limit: the gas's low Isp is.

### 6.3 Chemical-rocket hoverboard (theoretical black box) [A] + [SN]
Monoprop-class, 30 kg propellant: 151 kg gross, 4 × 489 N, **30.5 s** analytic hover, mission completed (max tilt 11°).
Biprop-class, 20 kg: 138 kg, 38.5 s. Solid-class: cannot be throttled or stopped — the board climbs, loses attitude
control and the mission fails (tested). Min throttle above the hover point (e.g. 95 %) also prevents hovering.
Study `rocket_hoverboard` (400 designs): best ≤ 150 kg 52 s; ≤ 200 kg 96 s; ≤ 250 kg 135 s (all biprop-class); longest
152 s at 289 kg (133 kg propellant). Hazards per engine: exhaust 1.4–2.5 km/s at 900–1800 K, hot gas beyond injury
level for 1.2–1.9 m, ground outwash > 15 m/s within ~1.4 m, **~149–151 dB at the rider's ears** (4 jets, SP-8072
scaling), > 140 dB within ~2 m of each jet; jet power 1–1.7 MW. Fire, explosion and toxicity are outside the model.

### 6.4 Comparison (rider 90.7 kg)

| Concept | Endurance | Power to stay up / move | Gross | Main hazard |
|---|---|---|---|---|
| Electric skateboard (dual hub) | ~20 km per 400 Wh | 3 kW peak | 100 kg | falls |
| Cold-gas boosted skateboard | 10 s boost per 6.8 L | 15 kW jet | 108 kg | vessel burst, stuck valve, rider thrown |
| **Air-cushion board LV-H1** (existing sim) | **~40 min / 5.4 kWh** | **7.5 kW** | 182 kg | edge jet 49 m/s (thin sheet) |
| Electric ducted-fan platform (RESEARCH_LOG) | 7.5 min | 107 kW | 282 kg | 45 m/s downwash |
| Micro-turbojet board (human_scale) | 3 min | — | ~165 kg | 500 m/s, 650 °C exhaust, kerosene |
| Cold-gas hoverboard | 4 s (default), 13 s (≤ 200 kg), ≤ 23–43 s ceiling | ~420–700 kW jet | 144–600 kg | MJ-scale stored gas, cryogenic jets |
| Rocket hoverboard (black box) | 30 s (default), 96 s (≤ 200 kg) | 1–2 MW jet | 138–290 kg | 150 dB, hot jets, fire/toxicity |

---

## 7. Practical limitations of these models
* Real-gas effects are carried in the tank and the mass flow; the nozzle expansion is ideal-gas (good below ~50 bar
  feed, a few % error for unregulated 300 bar feeds). No condensation inside the nozzle; the adiabatic tank model is
  stopped at 135 K. Regulator dynamics and Joule–Thomson cooling are not modelled.
* Lumped tank heat transfer with one assumed coefficient; real fast blowdowns stratify.
* PV/m factors are for commercial cylinders at service pressure; aerospace COPVs differ; nothing here addresses
  certification, fatigue, impact damage or fragment hazards (the dominant hazard of a vessel failure).
* Rider: a single inverted pendulum with centre-of-pressure limits; no stepping, hip strategy beyond an effective
  lever, or injury model. On hoverboards the rider is rigid.
* Hover: no ground effect on jets, no jet-induced suck-down or recirculation, no thruster failure cases, no gusts;
  autopilot gains tuned for nominal mass; first-order Euler (validated, 1 ms).
* Rocket engines are black boxes with assumed classes; no combustion, thermal, structural or propellant modelling, by
  design. Noise is an overall-level estimate (±5 dB) without directivity or shock-cell noise; hazard distances ±50 %.
* Costs are rough parts estimates.

## 8. Ranked recommendations for future research
1. **Stop pursuing thrust-borne (cold-gas or rocket) human hoverboards.** The ln((1+k)/k) ceiling, MW-scale jet power
   and hazards are fundamental; no plausible tank or Isp improvement changes the order of magnitude.
2. **Keep the air-cushion line as the human-scale hover platform** (7.5 kW, ~40 min): skirt-leakage and stability
   experiments from `RESEARCH_LOG.md` remain the highest-value next step.
3. If short "boost" effects are wanted on wheeled vehicles, study **electric burst power** (supercapacitor or
   high-power cells driving the hub motors) instead of cold gas: ~85 % vs ~0.5 % electricity-to-thrust-work; cold gas only
   makes sense where traction, not power, is the limit (the Tesla claim of "4–5× tire force"). A wheeled board is
   rider-balance-limited (~0.2 g sustained, ~0.08 g unexpected), so extra force has little use.
4. If cold-gas work continues at all, keep it to **professionally reviewed, unmanned, contained bench tests**: measure
   real blowdown temperature histories (to replace the lumped wall model), regulator dropout and nozzle Isp at 10–40 bar
   feed, with remote operation and burst containment. The model's real-gas and blowdown predictions are the parts that
   most need data.
5. Model refinements before any further cold-gas design study: nozzle condensation limits, regulator/JT cooling,
   multi-node tank thermal model, thruster-out cases in the 6-DOF, a rider model with stepping.

## 9. Files, commands, data
* Python: `backend/levitate/propulsion/` (`gas.py`, `coldgas.py`, `hazards.py`, `rocket.py`, `skateboard.py`,
  `hover.py`, `studies.py`, `rom.py`, `api.py`, `assumptions.py`, `gen_realgas.py`, `data/`).
* Tests: `backend/tests/test_propulsion_{coldgas,skateboard,hover,api}.py`; `node sim/propulsion/test_propulsion.js`.
* Regenerate browser data + references: `cd backend && python -m levitate.propulsion.rom`.
* Studies: `cd backend && python -m levitate.propulsion.studies 160 400` (kinds `coldgas_skateboard`,
  `coldgas_hoverboard`, `rocket_hoverboard` in the experiment DB; summary in `data/study_summary.json`).
* API: `/api/propulsion/{assumptions, tank, skateboard/evaluate, hover/evaluate, turbojet, results, studies, compare}`.
* UI: "Propulsion Lab" tab (React) and the standalone phone page `sim/propulsion/site/index.html`.
