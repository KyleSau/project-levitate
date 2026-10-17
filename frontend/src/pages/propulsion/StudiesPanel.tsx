// Studies (Optuna, stored in the experiment DB) and the comparison dashboard.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useMemo, useState } from "react";
import { G0, PP, ROM, fmt } from "./physics";

const KINDS: [string, string][] = [["coldgas_skateboard", "Cold-gas skateboard"], ["coldgas_hoverboard", "Cold-gas hoverboard"], ["rocket_hoverboard", "Rocket hoverboard"]];

export default function StudiesPanel({ cfgs }: { cfgs: any }) {
  const [studies, setStudies] = useState<any[]>([]);
  const [compare, setCompare] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [kind, setKind] = useState("coldgas_hoverboard");
  const [n, setN] = useState(100);
  const load = () => {
    fetch("/api/propulsion/studies").then((r) => r.json()).then(setStudies).catch(() => setErr("backend not connected: showing the summary bundled with the browser model"));
    fetch("/api/propulsion/compare").then((r) => r.json()).then(setCompare).catch(() => {});
  };
  useEffect(() => { load(); const id = setInterval(load, 4000); return () => clearInterval(id); }, []);
  const summary = compare?.study_summary || ROM.studies;
  const base = compare?.baselines || ROM.baselines;
  const live = useMemo(() => liveComparison(cfgs), [cfgs]);

  return (<div>
    <h1>Propulsion studies &amp; comparison</h1>
    {err && <div className="note">{err}</div>}
    <div className="card">
      <h2>Key results</h2>
      {(summary?.lines || []).map((l: string, i: number) => <p key={i}>{l}</p>)}
    </div>
    <div className="card">
      <h2>Comparison (rider 90.7 kg)</h2>
      <table style={{ width: "100%", fontSize: 12 }}><thead><tr><th align="left">Concept</th><th align="right">Endurance</th><th align="right">Power / jet power</th><th align="right">Gross mass</th><th align="left">Notes</th></tr></thead>
        <tbody>
          <tr><td>Electric skateboard (dual hub)</td><td align="right">{fmt(live.ebike.range_km, 1)} km range</td><td align="right">{fmt(live.ebike.power_kw, 1)} kW peak</td><td align="right">{fmt(live.ebike.mass, 0)} kg</td><td>top {fmt(live.ebike.vmax, 1)} m/s</td></tr>
          <tr><td>Cold-gas boosted skateboard (current settings)</td><td align="right">{fmt(live.boost.boost_s, 0)} s boost</td><td align="right">{fmt(live.boost.jet_kw, 0)} kW jet</td><td align="right">{fmt(live.boost.mass, 0)} kg</td><td>top {fmt(live.boost.vmax, 1)} m/s; {live.boost.events || "no flags"}</td></tr>
          <tr><td>{base.air_cushion.label}</td><td align="right">{fmt(base.air_cushion.endurance_min, 0)} min</td><td align="right">{fmt(base.air_cushion.power_kw, 1)} kW</td><td align="right">{fmt(base.air_cushion.gross_kg, 0)} kg</td><td>rides cm above the surface</td></tr>
          <tr><td>{base.ducted_fan.label}</td><td align="right">{fmt(base.ducted_fan.endurance_min, 1)} min</td><td align="right">{fmt(base.ducted_fan.power_kw, 0)} kW</td><td align="right">{fmt(base.ducted_fan.gross_kg, 0)} kg</td><td>jet {fmt(base.ducted_fan.jet_m_s, 0)} m/s</td></tr>
          <tr><td>{base.turbojet.label}</td><td align="right">{fmt(base.turbojet.endurance_min, 0)} min</td><td align="right">–</td><td align="right">{fmt(base.turbojet.gross_kg, 0)} kg</td><td>500 m/s, ~650 C exhaust</td></tr>
          <tr><td>Cold-gas hoverboard (current settings)</td><td align="right">{fmt(live.cg.t, 1)} s</td><td align="right">{fmt(live.cg.jet_kw, 0)} kW jet</td><td align="right">{fmt(live.cg.m0, 0)} kg</td><td>ceiling {fmt(live.cg.ceil, 0)} s for any tank size</td></tr>
          <tr><td>Rocket hoverboard (current settings, black box)</td><td align="right">{fmt(live.rk.t, 0)} s</td><td align="right">{fmt(live.rk.jet_kw, 0)} kW jet</td><td align="right">{fmt(live.rk.m0, 0)} kg</td><td>Isp {fmt(live.rk.isp, 0)} s</td></tr>
        </tbody></table>
    </div>
    <div className="card">
      <h2>Run a study</h2>
      <div className="row"><select value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <input type="number" value={n} min={8} max={2000} onChange={(e) => setN(+e.target.value)} />
        <button className="btn primary" onClick={() => fetch("/api/propulsion/studies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, n_trials: n }) }).then(load)}>Start (NSGA-II)</button></div>
    </div>
    {studies.map((s) => (
      <div className="card" key={s.id}>
        <h2>#{s.id} {s.name} · {s.status} {s.status === "running" ? `${Math.round(s.progress * 100)} %` : ""}</h2>
        {s.result?.pareto && <ParetoTable kind={s.kind} rows={s.result.pareto} />}
        {s.result?.missions && <p className="note">6-DOF missions: {s.result.missions.map((m: any) => `#${m.experiment_id} ${m.mission_completed ? "completed" : m.failed || "aborted"}`).join(", ")}</p>}
        {s.result?.practical && <p className="note">Best hover by gross-mass limit: {Object.entries(s.result.practical).map(([k, v]: any) => v ? `≤${k} kg ${fmt(v.hover_s, 1)} s` : "").join(" · ")}</p>}
        {s.result?.error && <pre className="fail">{s.result.error}</pre>}
      </div>))}
    <p className="note">Rows of every design (feasible and infeasible) are in the experiment DB: <code>/api/propulsion/results?kind=…</code></p>
  </div>);
}

function ParetoTable({ kind, rows }: { kind: string; rows: any[] }) {
  const cols: [string, string, number][] = kind === "coldgas_skateboard"
    ? [["speed_gain_m_s", "gain m/s", 2], ["max_speed_m_s", "top m/s", 1], ["boost_s", "boost s", 0], ["boost_accel_g", "push g", 2], ["propulsion_kg", "tank+air kg", 1], ["cost_usd", "$", 0], ["burst_kj", "burst kJ", 0]]
    : [["hover_s", "hover s", 1], ["gross_kg", "gross kg", 0], ["propellant_kg", "propellant kg", 1], ["thrust_n", "thrust N", 0], ["isp_s", "Isp s", 0], ["cost_usd", "$", 0], ["jet_power_kw", "jet kW", 0]];
  return (<div style={{ overflowX: "auto" }}><table style={{ width: "100%", fontSize: 12 }}><thead><tr>{cols.map(([, l]) => <th key={l} align="right">{l}</th>)}<th align="left">design</th></tr></thead>
    <tbody>{rows.slice(0, 12).map((r, i) => <tr key={i}>{cols.map(([k, , d]) => <td key={k} align="right">{fmt(r[k], d)}</td>)}<td className="note">{Object.entries(r.params || {}).map(([k, v]: any) => `${k}=${typeof v === "number" ? v.toFixed(2) : v}`).join(" ")}</td></tr>)}</tbody></table></div>);
}

function liveComparison(cfgs: any) {
  const e = new PP.SkateSim({ ...cfgs.skate, coldgas: false }), re = e.run(PP.defaultSkateScenario(false), 25, 50);
  const b = new PP.SkateSim(cfgs.skate), rb = b.run(PP.defaultSkateScenario(true), 25, 50);
  const whPerKm = (re.ledger.batt_out - re.ledger.regen_in) / 3600 / Math.max(1e-3, re.x[re.x.length - 1] / 1000);   // Wh per km on the test scenario
  const on = rb.t.filter((_: number, i: number) => rb.thrust[i] > 1);
  const hov = (c: any) => {
    const s = new PP.HoverSim(c), [m0] = s.massProps(), cosd = Math.cos(c.cant_deg * Math.PI / 180);
    let usable, isp, ue, k;
    if (s.gas) { const st = s.gas.thrustState(1); isp = st.isp; ue = st.ue; const pr = (c.reg_pressure_bar + s.vc.reg_dropout_bar) * 1e5; usable = s.gas.m0 - PP.realGas(c.tank.gas).rho_from_pT(pr, c.tank.temperature_k) * s.gas.V; k = s.gas.m_wall / s.gas.m0; }
    else { isp = s.rules.isp_s; ue = isp * G0; usable = c.engine.propellant_kg; k = s.vr.tankage_fraction; }
    return { m0, isp, t: isp * cosd * Math.log(m0 / (m0 - usable)), ceil: isp * cosd * Math.log((1 + k) / k), jet_kw: 0.5 * m0 * G0 / cosd * ue / 1000 };
  };
  return {
    ebike: { vmax: Math.max(...re.v), mass: re.m[0], power_kw: 2 * ROM.assumptions.skateboard.motor_peak_w / 1000, range_km: ROM.assumptions.skateboard.batt_wh / Math.max(whPerKm, 1) },
    boost: { vmax: Math.max(...rb.v), mass: rb.m[0], boost_s: on.length > 1 ? on[on.length - 1] - on[0] : 0, jet_kw: b.gasSys ? 0.5 * b.gasSys.maxThrust() * b.gasSys.thrustState(1).ue / 1000 : 0,
      events: rb.events.map((x: any) => x[1]).join("; ") },
    cg: hov(cfgs.cghover), rk: hov(cfgs.rocket),
  };
}
