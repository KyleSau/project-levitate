"""Print the human-scale concept sweep (lift area vs mass, power, downwash, endurance, cost)."""
from levitate.human_scale import HumanDesign, evaluate_human, min_area_for_jet_velocity

print(f"{'concept':20s}{'A m2':>6}{'foot':>6}{'gross':>7}{'P kW':>7}{'jet':>7}{'end':>6}{'cost k$':>8}  verdict  gross pess/nom/opt")
for c in ["ducted_electric", "open_rotor_electric", "ducted_hybrid"]:
    for A in [0.3, 0.5, 0.8, 1.5, 3, 6, 10, 15, 25]:
        d = HumanDesign(concept=c, lift_area_m2=A, exit_area_ratio=1.0 if c == "open_rotor_electric" else 1.3,
                        n_units=8, mission_min=5, packing=0.5 if c == "open_rotor_electric" else 0.6)
        r = evaluate_human(d)
        n, p, o = (r.scenarios[k] for k in ("nominal", "pessimistic", "optimistic"))
        print(f"{c:20s}{A:6.1f}{n.footprint_m2:6.1f}{n.gross_kg:7.0f}{n.hover_power_kw:7.0f}{n.jet_velocity_m_s:7.1f}"
              f"{n.endurance_min:6.1f}{n.cost_usd / 1000:8.0f}  {r.verdict:20s} {p.gross_kg:.0f}/{n.gross_kg:.0f}/{o.gross_kg:.0f}")
r = evaluate_human(HumanDesign(concept="turbojet", n_units=6, mission_min=5))
n = r.scenarios["nominal"]
print("turbojet", round(n.gross_kg), "kg, jet", n.jet_velocity_m_s, "m/s,", n.mass_breakdown_kg, "cost k$", round(n.cost_usd / 1000))
for v in (12, 25):
    print(f"min ducted (sigma 1.3) area for jet < {v} m/s at 200 kg: {min_area_for_jet_velocity(200, v, True, 1.3):.2f} m^2")
