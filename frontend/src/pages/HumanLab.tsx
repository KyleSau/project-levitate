import { useEffect, useState } from "react";
import { fmt } from "../api";

const CONCEPTS: [string, string][] = [
  ["air_cushion", "Air-cushion board (skirted plenum)"],
  ["ducted_electric", "Electric ducted fans (free flight)"],
  ["open_rotor_electric", "Electric open rotors (free flight)"],
  ["ducted_hybrid", "Ducted fans + engine-generator"],
  ["turbojet", "Micro turbojets (Flyboard-Air style)"],
];
const SURFACES: [string, number][] = [["smooth floor", 0.5], ["asphalt", 3], ["water chop", 5], ["short grass", 30]];

export default function HumanLab() {
  const [d, setD] = useState<any>({ concept: "air_cushion", lift_area_m2: 1.2, exit_area_ratio: 1.3, n_units: 6, mission_min: 20,
    payload_kg: 0, packing: 0.6, hover_gap_mm: 8, surface_roughness_mm: 3, cushion_aspect: 2.5 });
  const [rep, setRep] = useState<any>(null);
  const [studies, setStudies] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const id = setTimeout(() => {
      fetch("/api/evaluate/human", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ design: d }) })
        .then((r) => (r.ok ? r.json() : r.text().then((t) => Promise.reject(t)))).then((x) => { setRep(x); setErr(null); }).catch((e) => setErr(String(e)));
    }, 200);
    return () => clearTimeout(id);
  }, [d]);
  useEffect(() => { fetch("/api/studies").then((r) => r.json()).then((s) => setStudies(s.filter((x: any) => x.kind === "human_study"))); }, []);

  const set = (k: string, v: any) => setD({ ...d, [k]: v });
  const n = rep?.scenarios?.nominal;
  const cushion = d.concept === "air_cushion";
  const sliders: [string, string, number, number, number][] = [
    ["lift_area_m2", cushion ? "Cushion (deck) area m²" : "Total fan area m²", 0.3, 30, 0.1],
    ["n_units", cushion ? "Lift fans" : "Lift units (N−1 redundant)", 4, 16, 1],
    ["mission_min", "Mission (min)", 2, 60, 1],
    ["payload_kg", "Payload beyond rider (kg)", 0, 50, 1],
    ...(cushion ? [["hover_gap_mm", "Skirt clearance (mm)", 2, 40, 1] as [string, string, number, number, number]]
      : d.concept === "turbojet" ? [] : [["exit_area_ratio", "Duct exit/fan area", 1, 1.5, 0.05] as [string, string, number, number, number]]),
  ];

  return (
    <div className="page">
      <h1>Human-scale hover vehicle · 200 lb rider</h1>
      <p className="note">Analytical sizing with mass closure, one-unit-out redundancy and downwash. In hover the downward jet's momentum flux equals the weight,
        so jet speed (debris) depends only on jet area. <span className="ev">analytical_estimate</span></p>
      <div className="grid2">
        <div className="card">
          <div className="row"><label>Concept</label>
            <select value={d.concept} onChange={(e) => set("concept", e.target.value)}>{CONCEPTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
          {cushion && (
            <div className="row"><label>Surface</label>
              <select value={d.surface_roughness_mm} onChange={(e) => set("surface_roughness_mm", parseFloat(e.target.value))}>
                {SURFACES.map(([l, r]) => <option key={l} value={r}>{l}</option>)}</select></div>
          )}
          {sliders.map(([k, l, lo, hi, s]) => (
            <div className="row" key={k}><label style={{ width: 170 }}>{l}</label>
              <input type="range" min={lo} max={hi} step={s} value={d[k]} onChange={(e) => set(k, s === 1 ? parseInt(e.target.value) : parseFloat(e.target.value))} />
              <span className="num">{d[k]}</span></div>
          ))}
          {err && <div className="fail">{err}</div>}
        </div>
        {rep && n && (
          <div className="card">
            <div className="row"><span className={`badge ${rep.verdict === "CLOSES" ? "b-FEASIBLE" : rep.verdict === "DOES_NOT_CLOSE" ? "b-INFEASIBLE" : "b-MARGINAL"}`}>{rep.verdict.replaceAll("_", " ")}</span>
              <span className="mono">{n.form}</span></div>
            <table style={{ marginTop: 8 }}>
              <thead><tr><th></th><th>pess.</th><th>nominal</th><th>optim.</th></tr></thead>
              <tbody>{([["Gross mass (kg)", "gross_kg", 0], ["Hover power (kW)", "hover_power_kw", 1], ["Installed power (kW)", "installed_power_kw", 0],
                ["Jet / edge velocity (m/s)", "jet_velocity_m_s", 1], ["Endurance (min)", "endurance_min", 1], ["Footprint (m²)", "footprint_m2", 2],
                ["Parts cost (k$)", "cost_usd", 1, 1e-3], ["Energy per flight ($)", "energy_cost_per_flight_usd", 2]] as const).map(([l, k, dd, s]: any) => (
                <tr key={k}><td className="muted">{l}</td>{["pessimistic", "nominal", "optimistic"].map((sc) => (
                  <td key={sc} className="n">{rep.scenarios[sc].closes ? fmt(rep.scenarios[sc][k] * (s ?? 1), dd) : "—"}</td>))}</tr>
              ))}</tbody>
            </table>
            <div style={{ marginTop: 8 }}><b>Debris:</b> {n.debris}</div>
            {n.notes.map((x: string) => <div key={x} className="note">• {x}</div>)}
            <h2>Mass (nominal)</h2>
            {Object.entries(n.mass_breakdown_kg).sort((a: any, b: any) => b[1] - a[1]).map(([k, m]: any) => (
              <div key={k} className="row"><span className="muted">{k}</span><span className="num">{fmt(m, 1)} kg</span></div>))}
          </div>
        )}
      </div>
      <h2>Optimisation studies</h2>
      {studies.map((s) => (
        <div className="card" key={s.id}>
          <div className="row"><b>#{s.id} {s.goal}</b><span className={`badge b-${s.status}`}>{s.status}</span></div>
          {s.result?.by_concept && <div className="note">{Object.entries(s.result.by_concept).map(([c, b]: any) => `${c}: ${b.closed}/${b.tried} close`).join(" · ")}</div>}
          {s.result?.pareto && (
            <div style={{ overflowX: "auto" }}><table>
              <thead><tr><th>exp</th><th>concept</th><th>jet m/s</th><th>footprint m²</th><th>endurance min</th><th>cost k$</th></tr></thead>
              <tbody>{s.result.pareto.slice(0, 15).map((p: any) => (
                <tr key={p.experiment_id}><td className="mono">#{p.experiment_id}</td><td>{p.concept}</td><td className="n">{p.jet_m_s}</td>
                  <td className="n">{p.footprint_m2}</td><td className="n">{p.endurance_min}</td><td className="n">{fmt(p.cost_usd / 1000, 1)}</td></tr>))}</tbody>
            </table></div>
          )}
        </div>
      ))}
    </div>
  );
}
