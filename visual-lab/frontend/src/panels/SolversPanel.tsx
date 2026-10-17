// Solver-integration layer: registry with honest availability, background runs with validation checks,
// the reduced-order models consumed by the flight model, and real exported field data.
import { useCallback, useEffect, useState } from "react";
import { fmt, getJSON, postJSON } from "../api";
import type { FieldOverlayData } from "../components/FieldOverlay";
import { Heatmap } from "../components/Heatmap";
import { XYChart } from "../components/XYChart";
import { useJob } from "../useJob";

interface Check { check: string; value: unknown; limit?: number; passed: boolean; soft?: boolean; detail?: string }
interface SolverInfo {
  name: string; description: string; evidence: string; available: boolean; status: string; detail: string; produces: string;
  params: Record<string, number>;
  rom?: { valid: boolean; created: number; checks?: Check[]; summary?: Record<string, unknown>; deck_section?: Record<string, number>; limitations?: string } | null;
}
interface FieldRef { id: string; title: string; quantity: string; unit: string; source: string; valid: boolean }

function Checks({ checks }: { checks: Check[] }) {
  return (
    <table>
      <thead><tr><th>validation check</th><th>value</th><th>limit</th><th /></tr></thead>
      <tbody>{checks.map((c, i) => (
        <tr key={i} className={c.passed ? "" : c.soft ? "soft" : "fail"}>
          <td>{c.check}{c.detail && <div className="muted">{c.detail}</div>}</td>
          <td className="num">{typeof c.value === "number" ? fmt(c.value, 3) : String(c.value)}</td>
          <td className="num">{c.limit !== undefined ? fmt(c.limit, 3) : ""}</td>
          <td><span className={`pill ${c.passed ? "ok" : c.soft ? "warn" : "bad"}`}>{c.passed ? "PASS" : c.soft ? "SOFT FAIL" : "FAIL"}</span></td>
        </tr>))}</tbody>
    </table>
  );
}

function SolverCard({ s, onDone }: { s: SolverInfo; onDone: () => void }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [params, setParams] = useState<Record<string, number>>(s.params ?? {});
  const [err, setErr] = useState<string | null>(null);
  const job = useJob<{ valid: boolean; checks: Check[] }>(jobId);
  useEffect(() => { if (job?.status === "done" || job?.status === "failed") onDone(); }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const running = job && (job.status === "queued" || job.status === "running");
  return (
    <div className={`card ${s.available ? "" : "off"}`}>
      <div className="field">
        <b>{s.name}</b>
        <span className={`pill ${s.available ? "ok" : "bad"}`}>{s.status}</span>
      </div>
      <div style={{ margin: "4px 0" }}>{s.description}</div>
      <div className="muted">{s.detail}</div>
      {s.available && <div className="muted">evidence: {s.evidence} · output: {s.produces}</div>}
      {s.available && Object.entries(params).map(([k, v]) => (
        <div key={k} className="field"><span>{k}</span>
          <input type="number" value={v} onChange={(e) => setParams({ ...params, [k]: parseFloat(e.target.value) })} /></div>
      ))}
      {s.available && (
        <button className="primary" disabled={!!running} onClick={async () => {
          setErr(null);
          try { setJobId((await postJSON<{ job: string }>(`/api/solvers/${s.name}/run`, params)).job); } catch (e) { setErr(String(e)); }
        }}>{running ? `running… ${Math.round((job?.progress ?? 0) * 100)} %` : "run solver (background job)"}</button>
      )}
      {err && <div className="banner error">{err}</div>}
      {job?.status === "failed" && <div className="banner error">{job.error}</div>}
      {s.rom && (
        <div style={{ marginTop: 6 }}>
          <div>last result: <span className={`pill ${s.rom.valid ? "ok" : "bad"}`}>{s.rom.valid ? "VALID" : "INVALID"}</span>{" "}
            <span className="muted">{new Date(s.rom.created * 1000).toLocaleString()}</span></div>
          {s.rom.checks && <Checks checks={s.rom.checks} />}
          {s.rom.limitations && <div className="muted">limitations: {s.rom.limitations}</div>}
          {s.rom.summary && <div className="muted">{Object.entries(s.rom.summary).map(([k, v]) => `${k} = ${String(v)}`).join(" · ")}</div>}
        </div>
      )}
      {!s.rom && s.available && <div className="muted">not run yet</div>}
    </div>
  );
}

export function SolversPanel({ onOverlay, overlay, harness }: { onOverlay: (f: FieldOverlayData | null) => void; overlay: FieldOverlayData | null;
  harness: { connected: boolean; url: string; detail: string } | null }) {
  const [list, setList] = useState<SolverInfo[]>([]);
  const [fields, setFields] = useState<FieldRef[]>([]);
  const [preview, setPreview] = useState<FieldOverlayData | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [air, setAir] = useState<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [am, setAm] = useState<any>(null);
  const refresh = useCallback(() => {
    getJSON<SolverInfo[]>("/api/solvers").then(setList).catch(() => setList([]));
    getJSON<FieldRef[]>("/api/fields").then(setFields).catch(() => setFields([]));
    getJSON("/api/rom/air").then(setAir).catch(() => setAir(null));
    getJSON("/api/rom/added_mass").then(setAm).catch(() => setAm(null));
  }, []);
  useEffect(refresh, [refresh]);
  const loadField = async (id: string) => {
    const f = await getJSON<FieldOverlayData>(`/api/fields/${encodeURIComponent(id)}`);
    setPreview(f);
    return f;
  };
  const SEQ3 = ["#3987e5", "#d95926", "#199e70"];
  return (
    <div className="panel">
      <h2>Scientific solver integration</h2>
      <p className="muted">Pipeline: solve offline → validate → lookup table / reduced-order model → flight dynamics → visualisation.
        No solver runs per animation frame. Engines that are not installed are listed as NOT CONNECTED; no field is ever synthesised.
        Research harness: <b className={harness?.connected ? "basis-calculated" : "basis-hypothetical"}>{harness?.connected ? "CONNECTED" : "NOT CONNECTED"}</b> ({harness?.url})</p>
      <div className="grid2">{list.map((s) => <SolverCard key={s.name} s={s} onDone={refresh} />)}</div>

      <h3>Reduced-order models consumed by the flight model</h3>
      <div className="grid2">
        <div className="card">
          <b>Air density (Cantera ROM)</b>
          {air ? (
            <>
              <XYChart xLabel="temperature [K]" yLabel="ρ [kg/m³]" series={[0, 3, 5].map((j, k) => ({
                name: `p = ${(air.p_Pa[j] / 1000).toFixed(1)} kPa`, color: SEQ3[k], line: true,
                points: air.T_K.map((T: number, i: number) => ({ x: T, y: air.tables.rho[i][j] })),
              }))} />
              <XYChart xLabel="temperature [K]" yLabel="μ [Pa·s]" height={200} series={[{
                name: "dynamic viscosity (pressure-independent)", color: SEQ3[0], line: true,
                points: air.T_K.map((T: number, i: number) => ({ x: T, y: air.tables.mu[i][0] })),
              }]} />
              <div className="muted">Cantera {air.meta.cantera_version}, {air.meta.mechanism}, transport {air.meta.transport}.
                Used when Environment → air properties = Cantera ROM (drag, rotor power, added mass, buoyancy).
                He at sea level: ρ = {fmt(air.tables.rho_he[3][5], 4)} kg/m³ → buoyant lift of the 28.8 mL deck volume filled with He ≈
                {" "}{fmt((air.tables.rho[3][5] - air.tables.rho_he[3][5]) * 0.1 * 0.032 * 0.009 * 9.80665 * 1000, 3)} mN vs 196 mN weight (calculated).</div>
            </>
          ) : <div className="muted">not built — run cantera_air</div>}
        </div>
        <div className="card">
          <b>Added-mass coefficient (Gmsh + scikit-fem ROM)</b>
          {am ? (
            <>
              <XYChart logX xLabel="section aspect β = depth along motion / width across" yLabel="C_A = m_a' / (ρπa²)" series={[{
                name: "FEM P2, rectangle sections", color: SEQ3[0], line: true,
                points: am.table.map((r: { beta: number; C_A: number; n_dofs: number }) => ({ x: r.beta, y: r.C_A, label: `${r.n_dofs} dofs`,
                  ring: Math.abs(r.beta - 0.28125) < 1e-6 })),
              }]} />
              <div className="muted">Ringed point = deck section (9/32): C_A = {fmt(am.meta.deck_section.C_A_heave, 5)}.
                Heave added mass (strip theory, ρ = 1.225): {fmt(am.meta.deck_section.C_A_heave * 1.225 * Math.PI * 0.016 ** 2 * 0.1 * 1e6, 4)} mg
                = {fmt(am.meta.deck_section.C_A_heave * 1.225 * Math.PI * 0.016 ** 2 * 0.1 / 0.02 * 100, 3)} % of 20 g. Enable "added_mass" in parameters to include it. {am.meta.limitations}</div>
            </>
          ) : <div className="muted">not built — run fem_added_mass (~3–4 min)</div>}
        </div>
      </div>

      <h3>Exported field data (real solver output)</h3>
      {fields.length === 0 && <div className="muted">no fields yet — run fem_added_mass or harness_ehd_wire</div>}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {fields.map((f) => (
          <button key={f.id} onClick={() => loadField(f.id)}>{f.title}: {f.quantity} [{f.unit}] {f.valid ? "" : "(INVALID)"}</button>
        ))}
        {overlay && <button onClick={() => onOverlay(null)}>remove 3D overlay</button>}
      </div>
      {preview && (
        <div className="card" style={{ marginTop: 8 }}>
          <div className="field"><b>{preview.title} — {preview.quantity} [{preview.unit}]</b>
            <button className="primary" onClick={() => onOverlay(preview)}>show in 3D lab ({preview.attach === "board" ? "attached to board cross-section" : "world origin"})</button></div>
          <div className="muted">source: {preview.source}</div>
          <Heatmap field={preview} />
        </div>
      )}
    </div>
  );
}
