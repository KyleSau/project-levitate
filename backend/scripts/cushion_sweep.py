"""Air-cushion hoverboard for a 200 lb rider: deck size and surface vs power, edge-jet speed, endurance."""
from levitate.human_scale import HumanDesign, evaluate_human

print(f"{'deck m2':>8}{'L x W m':>12}{'surface':>14}{'gross':>7}{'P kW':>7}{'edge jet':>9}{'end min':>8}{'cost k$':>8}  verdict")
for A in [0.8, 1.2, 2.0, 3.0]:
    for surf, rough in [("floor", 0.5), ("asphalt", 3), ("water chop", 5), ("short grass", 30)]:
        d = HumanDesign(concept="air_cushion", lift_area_m2=A, n_units=4, mission_min=20, hover_gap_mm=8,
                        surface_roughness_mm=rough)
        r = evaluate_human(d)
        n = r.scenarios["nominal"]
        w = (A / d.cushion_aspect) ** 0.5
        print(f"{A:8.1f}{w * d.cushion_aspect:6.2f} x{w:4.2f}{surf:>14}{n.gross_kg:7.0f}{n.hover_power_kw:7.1f}"
              f"{n.jet_velocity_m_s:9.1f}{n.endurance_min:8.1f}{n.cost_usd / 1000:8.1f}  {r.verdict}"
              f"  (pess {r.scenarios['pessimistic'].hover_power_kw:.1f} / opt {r.scenarios['optimistic'].hover_power_kw:.1f} kW)")
