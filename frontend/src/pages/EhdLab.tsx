import { useEffect, useState } from "react";
import { api, fmt } from "../api";
import Heatmap from "../components/Heatmap";
import LineChart from "../components/LineChart";

export default function EhdLab() {
  const [wire, setWire] = useState({ voltage_kv: 9, gap_mm: 8, wire_radius_um: 25, grid: [48, 96], convergence_check: true });
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [surr, setSurr] = useState<any>(null);
  const [ead, setEad] = useState<any>({ voltage_kv: 8, gap_mm: 10, wire_radius_um: 25, pitch_over_gap: 1.5, n_stages: 3, battery: "lipo_1s_450", width_mm: 32, length_mm: 100, avionics_g: 2.5, max_stack_height_mm: 40 });
  const [eadRep, setEadRep] = useState<any>(null);

  useEffect(() => { fetch("/api/ehd/surrogate").then((r) => r.json()).then(setSurr).catch(() => {}); }, []);
  useEffect(() => {
    const id = setTimeout(() => api.evaluateEad({ name: "ui", ...ead }).then(setEadRep).catch((e) => setErr(String(e))), 250);
    return () => clearTimeout(id);
  }, [ead]);

  const run = async () => {
    setBusy(true); setErr(null);
    try { setRes(await api.solveWire(wire)); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const r = res?.results;
  const entry = surr?.entries?.find((e: any) => e.gap_mm === 8 && e.r_um === 25);

  return (
    <div className="page">
      <h1>Ionic-wind (EAD) laboratory</h1>
      <p className="note">Coupled Poisson + unipolar ion-drift solver (Kaptzov / Peek corona model) in bipolar coordinates.
        Fields below are the solver's actual output resampled to a physical grid. Evidence: <span className="ev">simplified_numerical_simulation</span>.
        Electrode drag and array shielding are not solved; they enter the board model as uncertain multipliers.</p>
      <div className="grid2">
        <div>
          <div className="card">
            <h2>Single emitter wire over collector plane</h2>
            {([["voltage_kv", "Voltage (kV)", 1, 30, 0.1], ["gap_mm", "Gap (mm)", 2, 30, 0.1], ["wire_radius_um", "Wire radius (µm)", 10, 60, 0.5]] as const).map(([k, l, lo, hi, s]) => (
              <div className="row" key={k}><label style={{ width: 110 }}>{l}</label>
                <input type="range" min={lo} max={hi} step={s} value={(wire as any)[k]} onChange={(e) => setWire({ ...wire, [k]: parseFloat(e.target.value) })} />
                <span className="num">{(wire as any)[k]}</span></div>
            ))}
            <div className="row"><label>Grid</label>
              <select value={wire.grid.join("x")} onChange={(e) => setWire({ ...wire, grid: e.target.value.split("x").map(Number) })}>
                {["24x48", "48x96", "64x128", "96x192"].map((g) => <option key={g}>{g}</option>)}
              </select>
              <label><input type="checkbox" checked={wire.convergence_check} onChange={(e) => setWire({ ...wire, convergence_check: e.target.checked })} /> 2× refinement check</label>
            </div>
            <button className="btn primary" disabled={busy} onClick={run}>{busy ? "Solving coupled system…" : "Run corona solver"}</button>
            {err && <div className="fail">{err}</div>}
          </div>
          {res && (
            <div className="card">
              <div className="row"><span className={`badge b-${res.verdict}`}>{res.verdict}</span><span className="ev">{res.evidence}</span><span className="note">experiment #{res.experiment_id}</span></div>
              <div className="kv" style={{ marginTop: 8 }}>
                <span className="k">Corona active</span><span className="v">{String(r.corona_active)}</span>
                <span className="k">Peek onset field</span><span className="v">{fmt(r.onset_field / 1e6, 2)} MV/m</span>
                <span className="k">Current / length</span><span className="v">{fmt(r.current_per_length * 1e6, 1)} µA/m</span>
                <span className="k">Thrust / length</span><span className="v">{fmt(r.thrust_per_length * 1000, 2)} mN/m</span>
                <span className="k">Thrust / power</span><span className="v">{fmt(r.power_per_length ? (r.thrust_per_length / r.power_per_length) * 1000 : 0, 2)} N/kW</span>
                <span className="k">Injected ρ at wire</span><span className="v">{fmt(r.rho_wire, 4)} C/m³</span>
                <span className="k">Charge conservation err</span><span className="v">{fmt(r.current_conservation_error, 2)}</span>
                <span className="k">Iterations · residual</span><span className="v">{r.picard_iterations} · {fmt(r.picard_residual, 1)}</span>
                <span className="k">Grid convergence</span><span className="v">{r.grid_convergence_rel != null ? `${(100 * r.grid_convergence_rel).toFixed(1)} %` : "not checked"}</span>
              </div>
              {res.validity_notes?.map((n: string) => <div key={n} className="note">• {n}</div>)}
            </div>
          )}
        </div>
        <div>
          {r?.fields ? (
            <div className="grid2">
              <div className="card"><Heatmap label="Electric potential φ" unit="V" values={r.fields.phi} xs={r.fields.x} ys={r.fields.y} /></div>
              <div className="card"><Heatmap label="Space charge ρ (log)" unit="C/m³" log values={r.fields.rho} xs={r.fields.x} ys={r.fields.y} /></div>
            </div>
          ) : <div className="card note">Run the solver to see its computed potential and space-charge fields.</div>}
          {entry && (
            <div className="card">
              <h2>Solver points behind the surrogate (8 mm gap, 25 µm wire)</h2>
              <LineChart xs={entry.points.map((p: any) => p.V / 1000)} xLabel="V (kV)" yLabel="mN/m · µA/m÷100"
                series={[{ name: "thrust mN/m", color: "#3ddc97", ys: entry.points.map((p: any) => p.T * 1000) },
                         { name: "current µA/m /100", color: "#38d6ff", ys: entry.points.map((p: any) => p.I * 1e4) }]} />
            </div>
          )}
        </div>
      </div>

      <h2>Board-level ionic-wind hoverboard</h2>
      <div className="grid2">
        <div className="card">
          {([["voltage_kv", "Voltage (kV)", 2, 30, 0.1], ["gap_mm", "Gap (mm)", 3, 30, 0.1], ["wire_radius_um", "Wire radius (µm)", 12.5, 50, 0.5],
            ["pitch_over_gap", "Pitch / gap", 1, 3, 0.05], ["n_stages", "Stages", 1, 8, 1], ["max_stack_height_mm", "Thickness budget (mm)", 10, 300, 1]] as const).map(([k, l, lo, hi, s]) => (
            <div className="row" key={k}><label style={{ width: 140 }}>{l}</label>
              <input type="range" min={lo} max={hi} step={s} value={ead[k]} onChange={(e) => setEad({ ...ead, [k]: s === 1 ? parseInt(e.target.value) : parseFloat(e.target.value) })} />
              <span className="num">{ead[k]}</span></div>
          ))}
          <div className="row"><label>Battery</label>
            <select value={ead.battery} onChange={(e) => setEad({ ...ead, battery: e.target.value })}>
              {[150, 200, 260, 300, 380, 450, 550, 660].map((c) => <option key={c} value={`lipo_1s_${c}`}>1S {c} mAh</option>)}
            </select></div>
        </div>
        {eadRep && (
          <div className="card">
            <div className="row"><span className={`badge b-${eadRep.verdict}`}>{eadRep.verdict}</span><span className="ev">{eadRep.evidence}</span></div>
            <div className="note">{eadRep.verdict_reason}</div>
            <table style={{ marginTop: 8 }}>
              <thead><tr><th></th><th>pess.</th><th>nominal</th><th>optim.</th></tr></thead>
              <tbody>
                {([["Thrust (mN)", (s: any) => s.thrust_n * 1000, 1], ["Weight (mN)", (s: any) => s.weight_n * 1000, 1], ["Thrust / weight", (s: any) => s.thrust_to_weight, 3],
                  ["SCL bound (mN)", (s: any) => s.scl_upper_bound_thrust_n * 1000, 1], ["Power in (W)", (s: any) => s.electrical_power_w, 1], ["Mass (g)", (s: any) => s.mass_g, 1],
                  ["HV converter (g)", (s: any) => s.mass_breakdown_g.hv_converter, 1], ["Wires / stage", (s: any) => s.n_wires_per_stage, 0]] as const).map(([l, f, d]) => (
                  <tr key={l}><td className="muted">{l}</td>{["pessimistic", "nominal", "optimistic"].map((k) => <td key={k} className="n">{fmt(f(eadRep.scenarios[k]), d)}</td>)}</tr>
                ))}
              </tbody>
            </table>
            {eadRep.scenarios.nominal.reasons.map((x: string) => <div key={x} className="note fail">• {x}</div>)}
          </div>
        )}
      </div>
    </div>
  );
}
