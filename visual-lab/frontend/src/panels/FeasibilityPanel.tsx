// Feasibility frontier: required vs available lift, T/W, power, energy, endurance, payload, accelerations,
// control authority; per-manoeuvre force/torque requirements; sweeps with a Pareto front; optimisation.
// Every number is tagged calculated / ESTIMATE / HYPOTHETICAL (and "simulation" where a flight decided it).
import { useState } from "react";
import type { SimResult } from "../api";
import { fmt, postJSON } from "../api";
import { XYChart, type XYSeries } from "../components/XYChart";
import { useJob } from "../useJob";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;
interface SweepResult { params: { path: string; values: number[] }[]; rows: Row[]; pareto: number[]; simulated: boolean; basis: Record<string, string> }

const BASIS_LABEL: Record<string, string> = { calculated: "calculated", estimate: "ESTIMATE", hypothetical: "HYPOTHETICAL" };
const PATHS = ["mode.battery.capacity_mah", "total_mass_kg", "rotor_radius_m", "mode.efficiency.figure_of_merit",
  "mode.efficiency.motor_efficiency", "mode.power_limit.max_electrical_power_w", "mode.thrust_limit.max_force_per_actuator_n"];

export function FeasibilityPanel({ current }: { current: SimResult | null }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [optId, setOptId] = useState<string | null>(null);
  const [p1, setP1] = useState({ path: "mode.battery.capacity_mah", values: "100,150,200,260,300,380,450,550,660,800,1000" });
  const [p2, setP2] = useState({ path: "total_mass_kg", values: "0.010,0.015,0.020,0.025,0.030,0.040" });
  const [simulate, setSimulate] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const job = useJob<SweepResult>(jobId);
  const opt = useJob<Row>(optId);
  const f = current?.feasibility;
  const sw = job?.status === "done" ? job.result : null;

  const runSweep = async (useCurrent: boolean) => {
    setErr(null);
    const parse = (s: string) => s.split(",").map((x) => parseFloat(x)).filter(Number.isFinite);
    const body: Row = { params: [{ path: p1.path, values: parse(p1.values) }, { path: p2.path, values: parse(p2.values) }], simulate };
    if (useCurrent && current) {
      body.base = { mode: current.mode_config, gains: current.gains };
      if (current.mode_config.mode === "ideal") { setErr("sweeps of battery/power need REALITY mode; base uses the reality baseline"); delete body.base; }
    }
    try { setJobId((await postJSON<{ job: string }>("/api/sweep", body)).job); } catch (e) { setErr(String(e)); }
  };

  const series = (yKey: string, xKey = "mass_kg", xs = 1000): XYSeries[] => {
    if (!sw) return [];
    const mk = (name: string, color: string, pred: (r: Row) => boolean, hollow = false): XYSeries => ({
      name, color, points: sw.rows.map((r, i) => ({ r, i })).filter(({ r }) => !r.error && pred(r) && r[yKey] !== null).map(({ r, i }) => ({
        x: r[xKey] * xs, y: r[yKey], hollow, ring: sw.pareto.includes(i),
        label: `${r.verdict} · ${sw.params.map((p) => `${p.path.split(".").pop()}=${r[p.path]}`).join(", ")}${r.failing?.length ? " · fails: " + r.failing.join(",") : ""}`,
      })),
    });
    return [mk("FEASIBLE", "#3987e5", (r) => r.verdict.startsWith("FEASIBLE")), mk("MARGINAL", "#d95926", (r) => r.verdict.startsWith("MARGINAL")),
      mk("INFEASIBLE (hollow)", "#9aa7b4", (r) => r.verdict.startsWith("INFEASIBLE"), true)];
  };

  return (
    <div className="panel">
      <h2>Feasibility frontier</h2>
      <p className="muted">Basis legend: <span className="basis-calculated">calculated</span> = Newton / geometry / mass distribution;{" "}
        <span className="basis-estimate">ESTIMATE</span> = uncertain engineering model (momentum theory, battery, thermal);{" "}
        <span className="basis-hypothetical">HYPOTHETICAL</span> = only meaningful for hypothetical (ideal) force inputs.</p>
      {f && current && (
        <div className="grid2">
          <div className="card">
            <h3>Current configuration — <span className={`v-${f.verdict.split(" ")[0]}`}>{f.verdict}</span></h3>
            <div className="muted">{current.name} · evidence {f.evidence}</div>
            <table>
              <thead><tr><th>quantity</th><th>value</th><th>unit</th><th>basis</th></tr></thead>
              <tbody>{f.metrics.map((m) => (
                <tr key={m.key} title={m.note}><td>{m.label}</td><td className="num">{m.unbounded ? "unbounded" : fmt(m.value, 4)}</td>
                  <td>{m.unit}</td><td className={`basis-${m.basis}`}>{BASIS_LABEL[m.basis]}</td></tr>))}</tbody>
            </table>
            <div className="muted" style={{ marginTop: 4 }}>{f.power_model}</div>
          </div>
          <div className="card">
            <h3>Constraints</h3>
            <table>
              <thead><tr><th>constraint</th><th>value</th><th>limit</th><th>toggle</th><th /></tr></thead>
              <tbody>{f.constraints.map((c) => (
                <tr key={c.key} className={c.passed ? "" : c.hard ? "fail" : "soft"} title={c.message}>
                  <td>{c.label}{c.message && !c.passed && <div className="muted">{c.message}</div>}</td>
                  <td className="num">{fmt(c.value, 4)}</td><td className="num">{fmt(c.limit, 4)} {c.unit}</td><td>{c.toggle}</td>
                  <td><span className={`pill ${c.passed ? "ok" : c.hard ? "bad" : "warn"}`}>{c.passed ? "PASS" : c.hard ? "FAIL" : "MARGINAL"}</span></td>
                </tr>))}</tbody>
            </table>
            {f.limiting_toggles.length > 0 && <div style={{ color: "var(--bad)", marginTop: 6 }}>infeasible because of: {f.limiting_toggles.join(", ")}</div>}
          </div>
        </div>
      )}
      {current?.requirements && (
        <div className="card" style={{ marginTop: 10 }}>
          <h3>Required force & torque per manoeuvre (from the simulated flight)</h3>
          <div className="muted">{current.summary.mode === "ideal"
            ? "IDEAL mode: these are the forces/torques a HYPOTHETICAL actuator set must supply for each manoeuvre — not a claim that a propulsion system exists."
            : "REALITY mode: forces/torques actually delivered under the enabled constraints."}</div>
          <table>
            <thead><tr><th>segment</th><th>duration s</th><th>max |ΣF| N</th><th>mean |ΣF| N</th><th>actuator F min…max N</th>
              <th>max |τ| x,y,z N·m</th><th>max tilt °</th><th>max |a| m/s²</th><th>peak P W (est.)</th><th>energy J (est.)</th></tr></thead>
            <tbody>{current.requirements.map((r) => (
              <tr key={r.index}><td>{r.label}</td><td className="num">{fmt(r.duration_s, 3)}</td><td className="num">{fmt(r.max_total_force_n, 4)}</td>
                <td className="num">{fmt(r.mean_total_force_n, 4)}</td><td className="num">{fmt(r.min_actuator_force_n, 3)} … {fmt(r.max_actuator_force_n, 3)}</td>
                <td className="num">{r.max_abs_torque_nm.map((x) => fmt(x, 2)).join(", ")}</td><td className="num">{fmt(r.max_tilt_deg, 3)}</td>
                <td className="num">{fmt(r.max_accel_m_s2, 3)}</td><td className="num">{fmt(r.peak_power_w_estimate, 3)}</td>
                <td className="num">{fmt(r.energy_j_estimate, 3)}</td></tr>))}</tbody>
          </table>
        </div>
      )}

      <h3>Trade-off sweep (REALITY model; default base = Agent-A-derived rotor baseline)</h3>
      <div className="card">
        {[[p1, setP1], [p2, setP2]].map(([p, set], k) => {
          const pp = p as typeof p1; const st = set as typeof setP1;
          return (
            <div key={k} className="field">
              <select value={pp.path} onChange={(e) => st({ ...pp, path: e.target.value })}>{PATHS.map((x) => <option key={x}>{x}</option>)}</select>
              <input style={{ flex: 1 }} value={pp.values} onChange={(e) => st({ ...pp, values: e.target.value })} />
            </div>
          );
        })}
        <label><input type="checkbox" checked={simulate} onChange={(e) => setSimulate(e.target.checked)} /> verify each point with a closed-loop
          takeoff + hover simulation (≤ 60 points)</label>{" "}
        <button className="primary" onClick={() => runSweep(false)}>run sweep (background job)</button>{" "}
        <button onClick={async () => { setErr(null); try { setOptId((await postJSON<{ job: string }>("/api/optimise", {})).job); } catch (e) { setErr(String(e)); } }}>
          optimise endurance (capacity × rotor radius)</button>
        <div className="muted">Capacity sweeps couple battery mass (0.70 g + 0.0239 g/mAh) and internal resistance (45 Ω·mAh / C), fitted to Agent A's LiPo catalog.</div>
        {err && <div className="banner error">{err}</div>}
        {job && job.status !== "done" && <div>sweep: {job.status} {Math.round(job.progress * 100)} % {job.error}</div>}
        {opt && <div style={{ marginTop: 6 }}>optimisation: {opt.status} {Math.round(opt.progress * 100)} % {opt.error}
          {opt.result && <pre style={{ whiteSpace: "pre-wrap", fontSize: 11 }}>{JSON.stringify({ x: opt.result.x, endurance_s: opt.result.objective_endurance_s,
            evaluations: opt.result.evaluations, verified_by_simulation: opt.result.verified, note: opt.result.note }, null, 1)}</pre>}</div>}
      </div>
      {sw && (
        <>
          <div className="grid2" style={{ marginTop: 8 }}>
            <div className="card"><b>Endurance vs total mass</b> <span className="basis-estimate">ESTIMATE</span>
              <XYChart xLabel="total mass [g]" yLabel="hover endurance [s]" series={series("endurance_s")} />
              <div className="muted">White ring = Pareto-optimal (max endurance, min mass, min cost) among hover-feasible points.</div></div>
            <div className="card"><b>Thrust / weight vs total mass</b> <span className="basis-estimate">ESTIMATE</span>
              <XYChart xLabel="total mass [g]" yLabel="T/W" series={series("thrust_to_weight")} />
              <div className="muted">T/W &lt; 1: cannot hover; 1–1.3 marginal control authority.</div></div>
            <div className="card"><b>Hover power vs total mass</b> <span className="basis-estimate">ESTIMATE</span>
              <XYChart xLabel="total mass [g]" yLabel="hover electrical power [W]" series={series("hover_power_w")} /></div>
            <div className="card"><b>Endurance vs cost</b> <span className="basis-estimate">ESTIMATE (catalog-nominal prices)</span>
              <XYChart xLabel="cost [USD]" yLabel="hover endurance [s]" series={series("endurance_s", "cost_usd_estimate", 1)} /></div>
          </div>
          <div className="card" style={{ marginTop: 8 }}>
            <b>Sweep table</b> ({sw.rows.length} points{sw.simulated ? ", each verified by closed-loop simulation" : ""})
            <table>
              <thead><tr>{sw.params.map((p) => <th key={p.path}>{p.path}</th>)}<th>verdict</th><th>mass g</th><th>T/W</th><th>P hover W</th>
                <th>endurance s</th><th>max payload g</th><th>cost $</th>{sw.simulated && <th>sim: hover achieved</th>}<th>failing</th></tr></thead>
              <tbody>{sw.rows.map((r, i) => (
                <tr key={i} className={r.failing?.length ? "fail" : r.verdict?.startsWith("MARGINAL") ? "soft" : ""}>
                  {sw.params.map((p) => <td key={p.path} className="num">{r[p.path]}</td>)}
                  <td>{r.verdict ?? r.error}{sw.pareto.includes(i) ? " ★" : ""}</td><td className="num">{fmt(r.mass_kg * 1000, 4)}</td>
                  <td className="num">{fmt(r.thrust_to_weight, 3)}</td><td className="num">{fmt(r.hover_power_w, 3)}</td>
                  <td className="num">{fmt(r.endurance_s, 4)}</td><td className="num">{fmt((r.max_payload_kg ?? NaN) * 1000, 3)}</td>
                  <td className="num">{fmt(r.cost_usd_estimate, 3)}</td>{sw.simulated && <td>{String(r.hover_achieved)}</td>}
                  <td>{(r.failing ?? []).join(", ")}</td></tr>))}</tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
