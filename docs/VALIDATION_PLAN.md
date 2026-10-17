# Physical validation plan (conventional baseline first)

Goal: replace every `catalog_nominal` / `engineering_judgment` assumption that drives the hover verdict with **[M]** data, then progress to tethered and untethered hover. Low-voltage (1S, 4.2 V) work only. High-voltage ionic-wind or hydrogen hardware is **out of scope** until a specialist review, interlocked HV enclosure, ozone monitoring and fire controls are in place, and the analysis above says it cannot fly anyway.

## Stage 1 — component metrology (bench, no flight)
| Item | Method | Replaces assumption |
|---|---|---|
| Mass of every part (motor with leads, fan, AIO, battery, printed duct/deck coupons) | 0.01 g scale, 3 repeats | catalog masses, `mass_growth` |
| Battery: usable energy and voltage sag | constant-power discharge at 5, 8, 12 W to 3.3 V/cell; log V, I at 10 Hz | `battery_specific_energy_derate`, internal resistance, max power |
| Motor + fan static thrust vs electrical power | load cell (≥ 0.01 N resolution, e.g. 100 g cell + HX711) on a rigid arm, inline power meter; sweep throttle 10–100 % | `figure_of_merit`, `motor_eff_scale`, max thrust |
| Same fan inside the printed duct (deck section coupon) | same rig | `duct_effectiveness`, tip-gap sensitivity (print 0.3 / 0.5 mm gaps) |
| Reaction torque | torque cell or bifilar pendulum | `rotor_torque_ratio` |
| Thrust step response | high-rate load-cell logging of throttle steps | `motor_time_constant` |
| Ground effect | thrust vs height above plate (5–60 mm), concrete / plywood / grass sod | Cheeseman–Bennett model for ducts |

Acceptance: fit parameters with uncertainty, enter them as `SourceStatus.MEASURED` assumptions, re-run studies #1/#2, compare predicted vs measured hover current within ±10 %.

## Stage 2 — integrated board on a test stand
* Build the leading Pareto design (exp #5101 class) on a 3-DOF gimbal (roll/pitch/yaw free, translation locked): verify attitude loop, allocation, saturation margins; record current at hover thrust.
* Vertical-rail tether (1-DOF) to measure hover current, thrust margin and ground-effect take-off.

## Stage 3 — controlled flight
* Tethered (light line, safety net) hover → compare current, endurance, attitude noise with model.
* Untethered hover over a net, then over the target surfaces (concrete, wood, grass, water — water only with a float and waterproofed electronics).
* Investigate discrepancies > 10 % before modifying any model coefficient; record each change in RESEARCH_LOG.md.

## Safety
Spinning 22 mm fans at ~60k rpm: eye protection, finger guards, current-limited bench supply for first spin-up. LiPo: fireproof bag for charging/discharge tests, never below 3.0 V/cell.
