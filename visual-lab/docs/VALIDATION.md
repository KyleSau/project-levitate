# Validation — automated tests

Run: `cd visual-lab\backend; ..\.venv\Scripts\python -m pytest -q`

## Analytic checks (`tests/test_physics_analytic.py`)
| Test | Reference | Tolerance |
|---|---|---|
| 20 g weight | m g = 0.196133 N | 1e-7 N |
| Free fall (RK4 and DOP853) | z = z0 − g t²/2 | 1e-10 m |
| Constant upward acceleration | z = z0 + a t²/2 | rel 1e-10 |
| Exactly balancing force → hover | ΣF = 0, Στ = 0, drift < 1e-8 m in 5 s | machine precision |
| 95 % thrust | descends with a = −0.05 g | rel 1e-9 |
| Forward acceleration | a = F/m | rel 1e-10 |
| Tilted thrust | a_x = g tan θ, a_z = 0 | rel 1e-12 |
| Removing forward thrust (no drag) | velocity unchanged for 2 s | rel 1e-9 |
| Quadratic drag decay | v = v0 / (1 + k v0 t / m) | rel 1e-9 |
| Torque-free asymmetric body (products of inertia) | |L| and rotational KE conserved; ω precesses | rel 1e-8 |
| Constant torque along each principal axis | ω = τ t / I, angle = τ t²/(2I), axis fixed | rel 1e-9 |
| Rotation responds to inertia tensor | dω/dt = J⁻¹τ; doubling mass halves α; off-diagonal coupling | rel 1e-12 |
| Actuator geometry torque | τ = r × F | rel 1e-12 |
| Quaternion norm | |q| = 1 every step | 1e-14 |

## Contact and convergence (`tests/test_contact_convergence.py`)
* 5 cm drop at 20 g and 120 g: max compression < 2 mm, rebound < 2 mm, no teleport (|Δz| per step ≤ 1.5 v dt),
  comes to rest at the static sag m g/(4k) (±5 %), contact normal force = weight at rest (±0.1 %).
* Landing at the autopilot descent rate (0.12 m/s): compression < 0.3 mm.
* Resting board stays static (|v| < 1e-9).
* RK4 order: torque-free asymmetric rotation, dt = 8, 4, 2, 1 ms vs DOP853 (rtol 1e-13): observed order 3.5–4.6.
* RK4 vs DOP853 with thrust, torque and drag: |Δp| < 1e-9 m after 1 s.
* Contact eigenvalues × actual sub-step inside RK4 stability region (|R(z)| ≤ 1) for 20 g, 120 g and an offset CG.

## Closed loop (`tests/test_closed_loop.py`)
* Demo mission A–G (ideal): completes, 2 takeoffs, 1 landing, hover actuator force / weight = 1 ± 2e-3,
  penetration < 0.2 mm, quaternion norms preserved in the record.
* Coast segment: velocity retained > 95 % over 1.2 s with level attitude; ΣF_x equals drag (no hidden thrust).
* Forward flight pitches nose-down (quad-type actuators); lateral gust impulse is rejected (error < 35 % of peak
  1.7 s later).
* Lands (contact carries weight, clearance ≈ 0) and takes off again to > 0.2 m.
* Reality baseline (Agent A ducted rotors + 300 mAh battery, 28.2 g) flies the mission.
* `underpowered`, `too_heavy`, `thrust_capped` presets: INFEASIBLE with the expected failing constraint and the
  simulated vehicle never leaves the ground (clearance < 1 cm), `TAKEOFF_FAILED` logged.
* Battery exhausted mid-hover: `BATTERY_DEPLETED`, falls and stops on the ground without penetrating.
* Step-size independence (1 ms vs 0.5 ms) < 2 mm; RK4 vs DOP853 closed loop < 0.1 mm.
* Actuator failure injection reported and enforced.

## Solvers & exchange (`tests/test_solvers_exchange.py`)
* Cantera table: density = ideal gas (same M) to 1e-6; ISA ρ_SL within 0.2 %; viscosity vs Sutherland within 3 %
  (observed 1.4 %); μ pressure-independent; speed of sound vs ISA within 0.3 %; He/air density ratio exact;
  ROM bilinear error vs fresh Cantera < 0.2 % (observed 0.035 %). ROM vs direct Cantera at 3 off-grid points.
* Flight model consumes the ROM density (drag force check).
* FEM (Gmsh + scikit-fem P2): circle C_A = 1 (exact) within 0.6 %; deck section C_A in [1.22, 1.30];
  energy identity (volume = boundary integral) to 1e-8. Full ROM build (`fem_added_mass` job) additionally checks
  two ellipses (exact C_A = 1, observed 0.9991/0.9993), motion along the major axis (0.9972), mesh convergence
  (Δ = 1.1e-4), monotonicity, and the square section against literature C_A = 1.51 (observed 1.5098).
* Added mass reduces heave acceleration to exactly F/(m + m_a).
* Agent A v1 document (#5105, fixture) validates, imports (J verbatim) and flies; visual-lab export validates
  against `schema/experiment_result.v1.schema.json`; harness fields convert without modification;
  uninstalled engines report NOT CONNECTED and refuse to run.

## API (`tests/test_api.py`)
defaults round-trip through `/api/analyse`, mass/CG changes update inertia consistently, unreachable CG rejected
with reason, `/api/simulate` short mission.

## Frontend
`npx tsc --noEmit` and `npm run build` (TypeScript strict).
