import { Fragment, useEffect, useState } from "react";
import { api, fmt } from "../api";

const ORDER = ["BASELINE", "VIABLE", "CONDITIONAL", "NOT_VIABLE"];

export default function Survey() {
  const [rows, setRows] = useState<any[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [solvers, setSolvers] = useState<any[]>([]);
  useEffect(() => { api.screening().then(setRows); api.solvers().then(setSolvers); }, []);
  const sorted = [...rows].sort((a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict));
  return (
    <div className="page">
      <h1>Propulsion survey</h1>
      <p className="note">First-principles screening against a 30 g, 100 × 32 mm free-flying board. These <span className="ev">analytical_estimate</span>s
        eliminate concepts that violate scale or conservation limits; surviving concepts still need numerical and physical validation.</p>
      <div className="card">
        <table>
          <thead><tr><th>Verdict</th><th>Mechanism</th><th>Free flight</th><th>Headline result</th></tr></thead>
          <tbody>
            {sorted.map((s) => (
              <Fragment key={s.key}>
                <tr key={s.key} onClick={() => setOpen(open === s.key ? null : s.key)} className={open === s.key ? "sel" : ""}>
                  <td><span className={`badge b-${s.verdict}`}>{s.verdict}</span></td>
                  <td>{s.mechanism}</td><td>{s.free_flight}</td><td className="note">{s.headline}</td>
                </tr>
                {open === s.key && (
                  <tr key={s.key + "-d"}><td colSpan={4}>
                    <div className="grid3">
                      <div><h2>Lift principle</h2><div>{s.lift_principle}</div><h2>Equations</h2>{s.equations.map((e: string) => <div key={e} className="mono">{e}</div>)}</div>
                      <div><h2>Reasoning</h2>{s.reasons.map((r: string) => <div key={r}>• {r}</div>)}<h2>Safety</h2><div>{s.safety}</div><h2>Scaling</h2><div>{s.scaling}</div></div>
                      <div><h2>Numbers</h2><div className="kv">{Object.entries(s.numbers).flatMap(([k, v]: any) => [<span key={k} className="k">{k}</span>, <span key={k + "v"} className="v">{fmt(v, 3)}</span>])}</div></div>
                    </div>
                  </td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <h2>Solver adapters</h2>
      <div className="card">
        <table>
          <thead><tr><th>Adapter</th><th>Status</th><th>Evidence</th><th>Handles</th><th>Notes</th></tr></thead>
          <tbody>{solvers.map((s) => (
            <tr key={s.name}><td className="mono">{s.name}</td>
              <td><span className={`badge ${s.available ? "b-VALID" : "b-INFEASIBLE"}`}>{s.available ? "CONNECTED" : "NOT CONNECTED"}</span></td>
              <td><span className="ev">{s.evidence}</span></td><td className="mono">{s.handles.join(", ")}</td><td className="note">{s.description} {s.available ? "" : `— ${s.status}`}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}
