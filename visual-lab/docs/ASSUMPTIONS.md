# Assumptions, limitations and provenance

## What the lab claims and does not claim
* IDEAL mode results answer "which force/torque history would this manoeuvre need". Actuators are hypothetical;
  no propulsion mechanism is claimed. Power/energy shown there is an ideal actuator-disk ESTIMATE only.
* REALITY mode results are simplified numerical simulations driven by analytical engineering models
  (momentum theory, Thevenin battery, lumped thermal). Treat absolute power/endurance numbers as ESTIMATES with
  the same uncertainty as Agent A's assumption ranges (FM 0.32–0.52 etc.).

## Engineering assumptions (with sources)
| Item | Value | Source / status |
|---|---|---|
| Rotor figure of merit | 0.42 | Agent A catalog (Bohorquez & Pines 2003); uncertain |
| Duct factor | 0.854 (50 % of ideal σ=1 duct saving) | Agent A engineering judgment |
| Motor efficiency | 0.65 | Agent A catalog, brushless 0702 |
| ESC efficiency | 0.95 (presets) / 0.92 (toggle default) | engineering judgment |
| Avionics | 0.45 W | Agent A catalog AIO F4 |
| Battery | 1S LiPo, V_oc 3.75 V, cutoff 3.3 V, 300 mAh 8.2 g, 0.15 Ω, 20 C, 80 % usable | Agent A battery model & catalog |
| Battery scaling in sweeps | m = 0.70 g + 0.0239 g/mAh, R = 45 Ω·mAh/C | fit to Agent A catalog |
| Motor time constant | 30 ms; transport delay 4 ms | Agent A nominal; judgment |
| Thermal | R_th 40 K/W, C_th 1 J/K, limit 100 °C, derate to 0 over 10 K | lumped estimate |
| Drag | C_d 1.17 broadside, 1.05 edge-on; strip-theory rotational damping | Hoerner 1965 |
| Ground effect | Cheeseman & Bennett 1955, clamped z/R ≥ 0.5 | Agent A rotor.py |
| Contact | 1000 N/m, 3 N·s/m per corner at 20 g (∝ m), μ = 0.5 | compliant pads; numerical choice |
| Reaction torque ratio κ | 6 mm | Agent A nominal |
| Ionic wind thrust/power | Agent A corona solver (single wire, 2-D) else 5 N/kW | excludes collector drag / array effects |
| Cost | catalog-nominal prices | ESTIMATE |

## Known limitations
* Deck shell modelled as a uniform solid box (a hollow shell has ~20–40 % larger moments).
* Aerodynamics are quasi-steady and body-axis decoupled; no rotor inflow/outwash interaction, no rotor
  blade-flapping or H-force, no wind gradients near ground except the ground-effect thrust factor.
* Added mass: 2-D strip theory (upper bound, no 3-D end relief), no ground proximity, no Munk moment; x-axis
  added mass not modelled.
* Penalty contact (compliant): penetrations of ~0.05 mm at rest, ~1.2 mm after a 1 m/s impact.
* Landing detection uses the simulated contact force (an ideal touch sensor).
* Controller uses true state unless sensor noise is enabled; no state estimator.
* Elmer, OpenFOAM, MOOSE, FEniCSx and GetDP are not installed: listed as NOT CONNECTED, never emulated.
