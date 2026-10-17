import { useEffect, useMemo, useState } from "react";
import { api, fmt } from "../api";

const COLS: Record<string, [string, string][]> = {
  rotor_design: [["mass_g", "mass g"], ["hover_power_w", "P W"], ["endurance_s_pess", "end. pess s"], ["endurance_s_nom", "end. nom s"],
    ["thrust_to_weight", "T/W"], ["roll_accel", "roll α"], ["n_rotors", "rotors"], ["rotor_diameter_mm", "D mm"], ["motor", "motor"], ["battery", "battery"], ["cost_usd", "$"]],
  ead_design: [["mass_g", "mass g"], ["thrust_mn", "thrust mN"], ["thrust_to_weight", "T/W nom"], ["thrust_to_weight_opt", "T/W opt"],
    ["power_w", "P W"], ["voltage_kv", "kV"], ["gap_mm", "gap mm"], ["n_stages", "stages"], ["scl_bound_mn", "SCL mN"]],
  ehd_wire: [["voltage_kv", "kV"], ["gap_mm", "gap mm"], ["wire_radius_um", "r µm"], ["current_ua_per_m", "µA/m"], ["thrust_mn_per_m", "mN/m"],
    ["thrust_to_power_n_per_kw", "N/kW"], ["grid_convergence_rel", "grid Δ"]],
};

export default function Explorer({ onOpen }: { onOpen: (id: number) => void }) {
  const [kind, setKind] = useState("rotor_design");
  const [verdict, setVerdict] = useState("");
  const [rows, setRows] = useState<any[]>([]);
  const [sort, setSort] = useState<[string, number]>(["id", -1]);
  const [sel, setSel] = useState<number[]>([]);
  const [detail, setDetail] = useState<any>(null);

  useEffect(() => {
    api.experiments(`?kind=${kind}${verdict ? `&verdict=${verdict}` : ""}&limit=2000`).then(setRows);
    setSel([]); setDetail(null);
  }, [kind, verdict]);

  const cols = COLS[kind] ?? [];
  const sorted = useMemo(() => {
    const [k, dir] = sort;
    const get = (r: any) => (k === "id" ? r.id : r.summary[k]);
    return [...rows].sort((a, b) => (get(a) > get(b) ? dir : get(a) < get(b) ? -dir : 0));
  }, [rows, sort]);
  const counts = rows.reduce((m: any, r) => ({ ...m, [r.verdict]: (m[r.verdict] ?? 0) + 1 }), {});

  const toggle = (id: number) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s.slice(-1), id]));
  useEffect(() => {
    if (sel.length === 0) { setDetail(null); return; }
    Promise.all(sel.map((id) => api.experiment(id))).then(setDetail);
  }, [sel]);

  return (
    <div className="page">
      <h1>Experiment explorer</h1>
      <div className="row" style={{ justifyContent: "flex-start", gap: 12 }}>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="rotor_design">Rotor / ducted-fan designs</option><option value="ead_design">Ionic-wind boards</option><option value="ehd_wire">Corona solver runs</option>
        </select>
        <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
          <option value="">all verdicts</option>{["FEASIBLE", "MARGINAL", "INFEASIBLE", "VALID", "UNCONVERGED"].map((v) => <option key={v}>{v}</option>)}
        </select>
        <span className="note">{rows.length} rows · {Object.entries(counts).map(([k, v]) => `${k}: ${v}`).join(" · ")} · click to select (2 = compare)</span>
      </div>
      <div className="grid2" style={{ gridTemplateColumns: detail ? "1.6fr 1fr" : "1fr" }}>
        <div className="card" style={{ maxHeight: "75vh", overflow: "auto", padding: 0 }}>
          <table>
            <thead><tr>
              <th onClick={() => setSort(["id", -sort[1]])}>#</th><th>verdict</th><th>evidence</th>
              {cols.map(([k, l]) => <th key={k} onClick={() => setSort([k, sort[0] === k ? -sort[1] : -1])}>{l}{sort[0] === k ? (sort[1] > 0 ? " ▲" : " ▼") : ""}</th>)}
            </tr></thead>
            <tbody>{sorted.slice(0, 600).map((r) => (
              <tr key={r.id} className={sel.includes(r.id) ? "sel" : ""} onClick={() => toggle(r.id)}>
                <td className="mono">{r.id}</td><td><span className={`badge b-${r.verdict}`}>{r.verdict}</span></td><td><span className="ev">{r.evidence.split("_")[0]}</span></td>
                {cols.map(([k]) => <td key={k} className="n">{typeof r.summary[k] === "number" ? fmt(r.summary[k], 2) : String(r.summary[k] ?? "")}</td>)}
              </tr>
            ))}</tbody>
          </table>
        </div>
        {detail && (
          <div>
            {detail.map((e: any) => (
              <div className="card" key={e.id}>
                <div className="row"><b>#{e.id} {e.name}</b><span className={`badge b-${e.verdict}`}>{e.verdict}</span></div>
                <div className="note mono">{e.solver} · code {e.versions?.code_sha} · cfg {e.config_hash}</div>
                {e.kind === "rotor_design" && <button className="btn" style={{ margin: "6px 0" }} onClick={() => onOpen(e.id)}>Open in Testing Chamber</button>}
                {e.results?.scenarios?.nominal?.constraints && (
                  <div className="cons">{e.results.scenarios.nominal.constraints.filter((c: any) => !c.passed).map((c: any) => (
                    <div key={c.key}><span className="fail">✗ {c.key}</span><span className="mono muted">{fmt(c.value, 2)} / {fmt(c.limit, 2)}</span></div>
                  ))}</div>
                )}
                {e.notes && <div className="note">{e.notes}</div>}
                <pre>{JSON.stringify(e.config, null, 1)}</pre>
              </div>
            ))}
            {detail.length === 2 && (
              <div className="card"><h2>Difference (B − A)</h2>
                <div className="kv">{cols.filter(([k]) => typeof detail[0].summary[k] === "number").flatMap(([k, l]) => [
                  <span key={k} className="k">{l}</span>, <span key={k + "v"} className="v">{fmt(detail[1].summary[k] - detail[0].summary[k], 2)}</span>])}</div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
