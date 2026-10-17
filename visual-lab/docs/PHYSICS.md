# Physics model — Visual Flight Physics Lab

All quantities SI. Code: `backend/vlab/`.

## Frames and state
* World: x forward, y left, z up; ground plane z = 0; g = 9.80665 m/s² (editable).
* Body: x forward (board length), y left, z up; origin of the *geometric* frame = deck centre.
  The dynamic state is referenced to the **centre of mass**.
* Attitude quaternion q = (w, x, y, z), scalar-first, body → world: v_world = R(q) v_body.
* State x = [p (3) world CG position, v (3) world CG velocity, q (4), ω (3) body angular velocity,
  f (n) actuator forces, E (1) electrical energy drawn].

## Mass properties (`vehicle.py`)
The vehicle is a list of mass components (solid boxes or point masses). Mass, CG and the inertia tensor
about the CG are always derived from them:
J = Σ [ J_box,i + m_i (|d_i|² I − d_i d_iᵀ) ],  d_i = r_i − r_CG.
Default 20 g board (100 × 32 × 9 mm): deck shell 7 g (uniform box approximation), 4 propulsion modules
1.5 g, avionics 2 g, CG-trim payload bay 5 g. Changing total mass scales all components (CG unchanged,
J ∝ m); moving the CG moves the trim component (J recomputed by parallel axis). Unreachable CG targets
are rejected. J is checked for symmetry, positive definiteness and the triangle inequality. The staggered
actuator layout (Agent A baseline) gives a genuine product of inertia J_xy.
Imported vehicles (v1 documents) carry their own J about their CG; it is used verbatim, scaled with mass,
and CG moves are refused (they would need the mass distribution).

## Equations of motion (`plant.py`)
```
dp/dt = v
(m I + R M_a Rᵀ) dv/dt = R (F_act + F_drag) − m g e_z + F_buoy + F_contact + F_ext
dq/dt = ½ q ⊗ (0, ω)
J dω/dt = τ_act + τ_drag + τ_contact + τ_ext − ω × (J ω)
df_i/dt = (u_i − f_i)/τ_i        (τ_i = 0: f_i = u_i held over the control period)
dE/dt   = P_cell(Σ P_i(f_i) + P_avionics)
```
* Actuator wrench about the CG: F = Σ a_i f_i k_GE,i ; τ = Σ (r_i − r_CG) × a_i f_i k_GE,i − s_i κ_i f_i k_GE,i a_i
  (rotor reaction torque, spin s_i = ±1, κ = 6 mm). k_GE is the Cheeseman–Bennett ground-effect factor
  (REALITY + ground_effect toggle, rotors only, clamped at z/R = 0.5).
* Drag (body axes, air-relative velocity): F_i = −½ ρ C_d,i A_i v_i|v_i|, A_x = WH, A_y = LH, A_z = LW,
  C_d = 1.05 / 1.05 / 1.17 (blunt section / flat plate, Hoerner). Rotational damping from flat-plate strip
  theory: τ_i = −k_i ω_i|ω_i|, k_x = ρ C_d L W⁴/64, k_y = ρ C_d W L⁴/64, k_z = ρ C_d H (L⁴+W⁴)/64.
* Added mass M_a (optional, from the FEM ROM): heave and sway, strip theory; Munk moment neglected.
* Buoyancy ρ V g (optional; 0.18 % of weight at 20 g).
* Ground contact: compliant penalty contact at the 8 deck corners: N = max(0, k δ − c δ̇) (no adhesion),
  tangential viscous-capped Coulomb friction F_t = −v_t min(c_t, μN/|v_t|) (μ = 0.5). k = 1000 N/m and
  c = 3 N·s/m per corner at 20 g, scaled ∝ m so static sag (49 µm) and contact frequencies are mass-independent.

## Integrators
* Real-time / interactive: classical RK4, fixed step dt = 1 ms, quaternion re-normalised every step, controller
  at 500 Hz zero-order hold, deterministic for a given seed. At construction the plant linearises the resting
  contact system (finite-difference Jacobian); while within 5 mm of the ground RK4 is sub-stepped so that
  |λ_max| h ≤ 2.0 (RK4 real-axis limit 2.785). For the default board |λ_max| = 3164 s⁻¹ → 2 sub-steps.
* Offline high accuracy: SciPy `solve_ivp` DOP853 (rtol 1e-9, atol 1e-12) over each control interval, same
  plant and controller (`integrator: "dop853"`, `/api/offline`).
* Live mode (`/ws/live`): the server steps the same RK4 simulation paced to wall-clock time and streams every
  recorded frame; commands (goto / land / takeoff / gust push) only change set-points or apply a declared external
  force. The full session recording is returned for replay / save / export.
* The browser never integrates physics: it replays the recorded state (100 Hz frames). There is no
  predetermined path and no easing; the mission autopilot only produces controller set-points.

## Flight controller (`controller.py`)
Cascade: position P → velocity PI → thrust vector / desired attitude → attitude P (quaternion error) → rate PI
→ τ = J α + ω × Jω → allocation. Anti-windup clamps; integrators frozen on the ground. Tilt limit 30°,
reduced automatically when available thrust is limited (keeps 5 % vertical margin). Allocation: pseudo-inverse,
falling back to bounded-variable least squares (`scipy.optimize.lsq_linear`, BVLS) with priorities
thrust & roll/pitch ≫ yaw when saturated; then the electrical power cap scales all forces (battery / ESC current
limit). "Direct" mode (actuator sets that can push sideways, rank-6 B) keeps the attitude level instead of tilting.

## Mission autopilot (`mission.py`)
Reactive state machine; quintic (minimum-jerk) set-point segments. Demo A–G: idle on ground → arm → takeoff to
0.30 m → hover (0.04 N lateral gust impulse at t = 5 s) → accelerate to 0.8 m/s → cruise → **coast with the
horizontal command removed** (level attitude, only drag acts) → active braking → stabilise → lateral move +0.3 m
with 90° yaw → controlled descent → touchdown detection (contact force > 5 % W for 100 ms) → spool-down 0.4 s →
disarm → re-arm → second takeoff to 0.25 m → hover. Failure handling: takeoff failure → mission abort; thrust
deficit, power limit, battery depletion, thermal derating, actuator failure, loss of control (tilt > 75° → disarm)
are detected and logged as events.

## Modes (`modes.py`)
**IDEAL PHYSICS — UNLIMITED ENERGY**: hypothetical force inputs (mechanism "hypothetical"), no energy limit,
zero-mass storage, force limits relaxable (default unlimited, optional bidirectional), instantaneous actuators.
Gravity, Newton–Euler, CG/inertia, drag and contact still apply. Electrical power is shown only as an ESTIMATE:
ideal actuator-disk induced power T^1.5/√(2ρA) for equivalent rotors (FM = 1); hypothetical forces have no
defined power. Evidence `hypothetical_ideal`.

**REALITY CONSTRAINTS** (each toggleable): propulsion type (ducted/open rotor, ionic wind), max force per
actuator, max torque, propulsion efficiency (FM, motor η, duct factor), electrical power cap, battery (Thevenin
1S LiPo: capacity, mass, R_int, C-rate → max power, usable energy, depletion), conversion (ESC/HV) losses, total
mass, dimensions, drag, ground effect, lumped thermal model with derating, actuator lag + transport delay,
added mass. A configuration that cannot produce its weight cannot hover in the simulation, and
`feasibility.py` names the binding constraint(s). Evidence `simplified_numerical_simulation`.

Rotor power (Agent A's model, `backend/levitate/physics/rotor.py`): P = T^1.5 k_duct / (FM η_m η_esc √(2ρA)),
FM 0.42, η_m 0.65, k_duct 0.854, avionics 0.45 W; battery formulas from `backend/levitate/physics/battery.py`
(V_oc 3.75 V, cutoff 3.3 V). Ionic wind: P = T/(thrust-per-power · η_conv), thrust-per-power taken from the last
valid Agent A corona-solver run when available (else 5 N/kW assumption).
