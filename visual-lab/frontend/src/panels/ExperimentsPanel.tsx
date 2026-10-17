// Experiments: save / load / delete recorded flights (SQLite), export in levitate.experiment-result/v1,
// import v1 documents (e.g. from Agent A), fly Agent A's designs, and queue offline DOP853 runs.
import { useCallback, useEffect, useState } from "react";
import type { SimResult } from "../api";
import { fmt, getJSON, postJSON } from "../api";
import { useJob } from "../useJob";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

function download(name: string, obj: unknown) {
  const blob = new Blob([JSON.stringify(obj)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function ExperimentsPanel({ current, onLoad }: { current: SimResult | null; onLoad: (r: SimResult) => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [imported, setImported] = useState<Row | null>(null);
  const [harnessRows, setHarnessRows] = useState<Row[] | null>(null);
  const [harnessErr, setHarnessErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [offId, setOffId] = useState<string | null>(null);
  const off = useJob<Row>(offId);
  const refresh = useCallback(() => { getJSON<Row[]>("/api/experiments").then(setRows).catch((e) => setErr(String(e))); }, []);
  useEffect(refresh, [refresh]);
  useEffect(() => { if (off?.status === "done") refresh(); }, [off?.status, refresh]);

  const wrap = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); setErr(null); setMsg(null);
    try { await fn(); } catch (e) { setErr(String(e)); } finally { setBusy(null); }
  };

  const loadHarness = () => wrap("harness", async () => {
    setHarnessErr(null);
    try {
      const a = await getJSON<Row[]>("/api/harness/experiments?kind=rotor_design&verdict=FEASIBLE&limit=10").catch(() => []);
      const b = await getJSON<Row[]>("/api/harness/experiments?kind=rotor_design&verdict=MARGINAL&limit=10");
      setHarnessRows([...a, ...b]);
    } catch (e) { setHarnessErr(String(e)); setHarnessRows(null); }
  });

  return (
    <div className="panel">
      <h2>Experiments</h2>
      {busy && <div className="banner">{busy} …</div>}
      {err && <div className="banner error">{err}</div>}
      {msg && <div className="banner">{msg}</div>}
      <div className="grid2">
        <div className="card">
          <h3>Current flight</h3>
          {current ? (
            <>
              <div>{current.name} · {String(current.summary.mode)} · {current.feasibility.verdict} · {current.trajectory.t.length} frames</div>
              <div className="field"><input style={{ flex: 1 }} placeholder="experiment name" value={name} onChange={(e) => setName(e.target.value)} />
                <button className="primary" onClick={() => wrap("saving", async () => {
                  const r = await postJSON<{ id: number }>("/api/experiments/save_result", { result: current, name: name || current.name });
                  setMsg(`saved as experiment #${r.id}`); refresh();
                })}>save</button></div>
              <button onClick={() => wrap("exporting", async () => {
                const r = await postJSON<{ document: Row; schema_errors: string[] }>("/api/export", { result: current, every: 1 });
                if (r.schema_errors.length) throw new Error("schema errors: " + r.schema_errors.join("; "));
                download(`visual_lab_flight_${Date.now()}.v1.json`, r.document);
                setMsg(`exported levitate.experiment-result/v1 (evidence ${r.document.evidence}), schema-valid`);
              })}>export as levitate.experiment-result/v1</button>{" "}
              <button onClick={() => wrap("queueing", async () => {
                const body = { mode: current.mode_config, gains: current.gains, settings: current.settings, name: current.name };
                setOffId((await postJSON<{ job: string }>("/api/offline", body)).job);
              })}>re-run offline with SciPy DOP853 (background)</button>
              {off && <div className="muted">offline job: {off.status} {Math.round(off.progress * 100)} % {off.error ?? ""}
                {off.result && ` → experiment #${off.result.experiment_id}`}</div>}
              <div className="muted">The offline run uses the default vehicle with the current mode/gains (custom vehicles: save + reload).</div>
            </>
          ) : <div className="muted">no flight loaded</div>}
        </div>
        <div className="card">
          <h3>Import levitate.experiment-result/v1</h3>
          <input type="file" accept=".json" onChange={(e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            wrap("importing", async () => {
              const doc = JSON.parse(await file.text());
              if (doc.schema_version === "levitate.experiment-result/v1" && doc.source === "visual_lab" && doc.trajectory) {
                setMsg("this is a visual-lab flight export; vehicle imported below (trajectory replay of foreign documents is not supported)");
              }
              setImported(await postJSON<Row>("/api/import", doc));
            });
          }} />
          {imported && (
            <div style={{ marginTop: 6 }}>
              <div>source {imported.source} #{String(imported.experiment_id)} · kind {imported.kind} · evidence <b>{imported.evidence}</b> · verdict {String(imported.verdict)}</div>
              {imported.schema_errors?.length > 0 && <div style={{ color: "var(--warn)" }}>schema: {imported.schema_errors.join("; ")}</div>}
              {imported.vehicle_error && <div style={{ color: "var(--bad)" }}>{imported.vehicle_error}</div>}
              {imported.notes && <ul>{imported.notes.map((n: string, i: number) => <li key={i} className="muted">{n}</li>)}</ul>}
              {imported.fields?.length > 0 && <div className="muted">fields: {imported.fields.map((f: Row) => `${f.quantity} [${f.unit}]`).join(", ")}</div>}
              {imported.vehicle && <button className="primary" onClick={() => wrap("simulating imported vehicle", async () => {
                onLoad(await postJSON<SimResult>("/api/simulate", { vehicle: imported.vehicle, mode: imported.mode, name: `imported ${imported.source}#${imported.experiment_id}` }));
              })}>fly demo mission with imported vehicle (REALITY)</button>}
            </div>
          )}
        </div>
        <div className="card">
          <h3>Agent A designs (research harness)</h3>
          <button onClick={loadHarness}>list feasible / marginal rotor designs</button>
          {harnessErr && <div style={{ color: "var(--bad)" }}>Research harness: NOT CONNECTED or unavailable ({harnessErr})</div>}
          {harnessRows && (
            <table>
              <thead><tr><th>id</th><th>verdict</th><th>mass g</th><th>T/W</th><th>endurance (nom) s</th><th /></tr></thead>
              <tbody>{harnessRows.map((r) => (
                <tr key={r.id}><td>{r.id}</td><td>{r.verdict}</td><td className="num">{fmt(r.summary?.mass_g, 4)}</td>
                  <td className="num">{fmt(r.summary?.thrust_to_weight, 3)}</td><td className="num">{fmt(r.summary?.endurance_s_nom, 4)}</td>
                  <td><button onClick={() => wrap(`importing Agent A #${r.id}`, async () => {
                    onLoad(await postJSON<SimResult>(`/api/simulate_imported/${r.id}`, {}));
                  })}>fly</button></td></tr>))}</tbody>
            </table>
          )}
          <div className="muted">Uses GET /api/experiments/{"{id}"}/export (contract v1). Evidence of the source design is kept; the flight itself is a
            simplified numerical simulation.</div>
        </div>
      </div>
      <h3>Saved experiments</h3>
      <table>
        <thead><tr><th>#</th><th>created</th><th>name</th><th>mode</th><th>evidence</th><th>verdict</th><th>takeoffs</th><th>failures</th><th /></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.id}><td>{r.id}</td><td>{new Date(r.created * 1000).toLocaleString()}</td><td>{r.name}</td><td>{r.mode}</td><td>{r.evidence}</td>
            <td>{r.verdict}</td><td className="num">{r.summary?.takeoffs}</td><td>{Array.isArray(r.summary?.failures) ? r.summary.failures.join(",") : ""}</td>
            <td>
              <button onClick={() => wrap("loading", async () => onLoad(await getJSON<SimResult>(`/api/experiments/${r.id}`)))}>replay</button>{" "}
              <button onClick={() => wrap("exporting", async () => download(`experiment_${r.id}.v1.json`, await getJSON(`/api/experiments/${r.id}/export`)))}>export v1</button>{" "}
              <button onClick={() => wrap("deleting", async () => { await fetch(`/api/experiments/${r.id}`, { method: "DELETE" }); refresh(); })}>delete</button>
            </td></tr>))}</tbody>
      </table>
    </div>
  );
}
