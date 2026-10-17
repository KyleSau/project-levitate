import { useEffect, useState } from "react";
import { api, fmt } from "../api";

const EXAMPLES = [
  "Find the longest endurance design under 30 g, 1500 trials",
  "Robust design: maximise endurance and stability with pessimistic assumptions, 1000 trials",
  "Lightest and cheapest board with at least 5 min endurance",
  "Optimise an ionic wind board, 800 trials",
];

export default function ResearchConsole({ onOpen }: { onOpen: (id: number) => void }) {
  const [goal, setGoal] = useState(EXAMPLES[0]);
  const [plan, setPlan] = useState<any>(null);
  const [cfgText, setCfgText] = useState("");
  const [studies, setStudies] = useState<any[]>([]);
  const [cat, setCat] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = () => api.studies().then(setStudies).catch(() => {});
  useEffect(() => { refresh(); api.catalog().then(setCat); const id = setInterval(refresh, 1500); return () => clearInterval(id); }, []);

  const makePlan = async () => { const p = await api.plan(goal); setPlan(p); setCfgText(JSON.stringify(p.config, null, 2)); };
  const launch = async () => {
    try { setErr(null); await api.createStudy(plan.kind, JSON.parse(cfgText), goal); refresh(); } catch (e) { setErr(String(e)); }
  };

  return (
    <div className="page">
      <h1>AI research console</h1>
      <p className="note">Goals are translated into optimisation studies by a deterministic keyword planner (no language model is called).
        Inspect and edit the plan before running. Studies run in the backend; every candidate, feasible or rejected, is stored.</p>
      <div className="grid2">
        <div>
          <div className="card">
            <h2>Research goal</h2>
            <textarea value={goal} onChange={(e) => setGoal(e.target.value)} />
            <div className="row" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
              {EXAMPLES.map((x) => <button key={x} className="btn" style={{ fontSize: 11 }} onClick={() => setGoal(x)}>{x.slice(0, 38)}…</button>)}
            </div>
            <button className="btn primary" onClick={makePlan}>Plan experiments</button>
          </div>
          {plan && (
            <div className="card">
              <h2>Plan · {plan.kind}</h2>
              <div className="note">{plan.planner}</div>
              {plan.rationale.map((r: string) => <div key={r}>• {r}</div>)}
              <textarea className="mono" style={{ minHeight: 200, marginTop: 8 }} value={cfgText} onChange={(e) => setCfgText(e.target.value)} />
              <button className="btn primary" onClick={launch}>Run study</button>
              {err && <div className="fail">{err}</div>}
            </div>
          )}
          {cat && (
            <div className="card">
              <h2>Model assumptions (must be measured)</h2>
              <table><thead><tr><th>key</th><th>low</th><th>nom</th><th>high</th><th>status</th></tr></thead>
                <tbody>{[...cat.assumptions_rotor, ...cat.assumptions_ead].map((a: any) => (
                  <tr key={a.key + a.unit} title={`${a.description} — ${a.source}`}><td className="mono">{a.key}</td><td className="n">{fmt(a.low, 3)}</td><td className="n">{fmt(a.nominal, 3)}</td><td className="n">{fmt(a.high, 3)}</td><td className="note">{a.status}</td></tr>
                ))}</tbody></table>
            </div>
          )}
        </div>
        <div>
          <h2>Studies</h2>
          {studies.map((s) => (
            <div className="card" key={s.id}>
              <div className="row"><b>#{s.id} {s.name}</b><span className={`badge b-${s.status}`}>{s.status}</span></div>
              {s.goal && <div className="note">“{s.goal}”</div>}
              <div className="bar" style={{ margin: "6px 0" }}><div style={{ width: `${100 * (s.progress ?? 0)}%` }} /></div>
              {s.result?.error && <pre className="fail">{s.result.error}</pre>}
              {s.kind === "rotor_study" && s.result?.pareto && (
                <>
                  <div className="note">{s.result.n_trials} candidates · {s.result.n_feasible} satisfy all hard constraints · {s.result.pareto.length} on the feasible Pareto front</div>
                  <table><thead><tr><th>exp</th>{s.result.objectives.map((o: string) => <th key={o}>{o}</th>)}</tr></thead>
                    <tbody>{s.result.pareto.slice(0, 12).map((p: any) => (
                      <tr key={p.trial} onClick={() => onOpen(p.experiment_id)}><td className="mono">#{p.experiment_id}</td>
                        {s.result.objectives.map((o: string) => <td key={o} className="n">{fmt(p.values[o], 1)}</td>)}</tr>
                    ))}</tbody></table>
                  {s.result.verified?.length > 0 && (
                    <>
                      <h2>Verified in 6-DOF closed loop</h2>
                      {s.result.verified.map((v: any) => (
                        <div key={v.experiment_id} className="row" onClick={() => onOpen(v.experiment_id)} style={{ cursor: "pointer" }}>
                          <span className="mono">#{v.experiment_id}</span><span className={`badge b-${v.verdict}`}>{v.verdict}</span>
                          <span className="mono">{fmt(v.mass_g, 1)} g · {fmt(v.endurance_s_pess / 60, 1)}–{fmt(v.endurance_s_opt / 60, 1)} min</span>
                          <span className={v.sim_stable ? "ok" : "fail"}>{v.sim_stable ? "stable" : "unstable"}</span>
                        </div>
                      ))}
                    </>
                  )}
                </>
              )}
              {s.kind === "ead_study" && s.result?.best_summary && (
                <div className="kv">
                  <span className="k">best T/W ({s.result.scenario})</span><span className="v">{fmt(s.result.best_thrust_to_weight, 3)}</span>
                  {Object.entries(s.result.best_summary).flatMap(([k, v]: any) => [<span key={k} className="k">{k}</span>, <span key={k + "v"} className="v">{typeof v === "number" ? fmt(v, 2) : String(v)}</span>])}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
