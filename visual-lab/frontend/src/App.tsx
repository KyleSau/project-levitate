import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SimResult } from "./api";
import { frameAt, getJSON } from "./api";
import { MiniChart } from "./components/Charts";
import { Dashboard } from "./components/Dashboard";
import type { FieldOverlayData } from "./components/FieldOverlay";
import { Timeline } from "./components/Timeline";
import { defaultOptions, Lab3D, type SceneOptions } from "./scene/Lab3D";
import { ParameterEditor } from "./panels/ParameterEditor";
import { FeasibilityPanel } from "./panels/FeasibilityPanel";
import { SolversPanel } from "./panels/SolversPanel";
import { ExperimentsPanel } from "./panels/ExperimentsPanel";

type Tab = "lab" | "params" | "feasibility" | "solvers" | "experiments";

interface Health { status: string; versions: Record<string, string | null> }
interface HarnessStatus { connected: boolean; url: string; detail: string }

export default function App() {
  const [res, setRes] = useState<SimResult | null>(null);
  const [preset, setPreset] = useState("ideal");
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [opt, setOpt] = useState<SceneOptions>(defaultOptions);
  const [tab, setTab] = useState<Tab>("lab");
  const [health, setHealth] = useState<Health | null>(null);
  const [harness, setHarness] = useState<HarnessStatus | null>(null);
  const [field, setField] = useState<FieldOverlayData | null>(null);
  const simTime = useRef(0);

  const load = useCallback(async (p: string) => {
    setLoading(`running demo mission (${p}) …`);
    setError(null);
    setPlaying(false);
    try {
      const r = await getJSON<SimResult>(`/api/demo?preset=${encodeURIComponent(p)}`);
      setRes(r);
      setIdx(0);
      simTime.current = 0;
      setPlaying(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(null);
    }
  }, []);

  const showResult = useCallback((r: SimResult) => {
    setRes(r);
    setIdx(0);
    simTime.current = 0;
    setPlaying(true);
    setTab("lab");
  }, []);

  useEffect(() => { load("ideal"); }, [load]);
  useEffect(() => {
    const poll = () => {
      getJSON<Health>("/api/health").then(setHealth).catch(() => setHealth(null));
      getJSON<HarnessStatus>("/api/harness/status").then(setHarness).catch(() => setHarness(null));
    };
    poll();
    const h = setInterval(poll, 10000);
    return () => clearInterval(h);
  }, []);

  // playback clock: advances simulated time at `speed` x wall time and picks the recorded frame
  useEffect(() => {
    if (!playing || !res) return;
    let raf = 0;
    let last = performance.now();
    const t = res.trajectory.t;
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      simTime.current = Math.min(t[t.length - 1], simTime.current + dt * speed);
      setIdx(frameAt(t, simTime.current));
      if (simTime.current >= t[t.length - 1]) {
        setPlaying(false);
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, res]);

  const seek = (i: number) => {
    if (!res) return;
    const n = res.trajectory.t.length;
    const j = Math.max(0, Math.min(n - 1, i));
    setIdx(j);
    simTime.current = res.trajectory.t[j];
  };

  // keyboard: space play/pause, arrows frame step
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT" || (e.target as HTMLElement).tagName === "SELECT") return;
      if (e.code === "Space") { e.preventDefault(); setPlaying((p) => !p); }
      if (e.code === "ArrowRight") { setPlaying(false); seek(idx + 1); }
      if (e.code === "ArrowLeft") { setPlaying(false); seek(idx - 1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const charts = useMemo(() => {
    if (!res) return null;
    const tr = res.trajectory;
    const h0 = res.vehicle.cg_m[2] + res.vehicle.height_m / 2;
    return {
      alt: [{ name: "altitude", color: "#3987e5", data: tr.pos.map((p) => p[2] - h0) },
        { name: "setpoint", color: "#9aa7b4", data: tr.ref_pos.map((p) => p[2] - h0), dashed: true }],
      vel: [{ name: "vx", color: "#3987e5", data: tr.vel.map((v) => v[0]) }, { name: "vy", color: "#d95926", data: tr.vel.map((v) => v[1]) },
        { name: "vz", color: "#199e70", data: tr.vel.map((v) => v[2]) }],
      force: [{ name: "lift", color: "#3987e5", data: tr.F_act.map((f) => f[2]) },
        { name: "weight", color: "#d95926", data: tr.F_grav.map((f) => -f[2]), dashed: true },
        { name: "contact", color: "#199e70", data: tr.F_contact.map((f) => f[2]) }],
      att: [{ name: "roll", color: "#3987e5", data: tr.euler_deg.map((e) => e[0]) }, { name: "pitch", color: "#d95926", data: tr.euler_deg.map((e) => e[1]) },
        { name: "yaw", color: "#199e70", data: tr.euler_deg.map((e) => e[2]) }],
      power: [{ name: "P (est.)", color: "#3987e5", data: tr.power_w }],
    };
  }, [res]);

  const mode = res?.summary.mode;
  return (
    <div className="app">
      <header>
        <div className="brand">LEVITATE <span>· Visual Flight Physics Lab</span></div>
        {res && (
          <div className={`mode-badge ${mode === "ideal" ? "ideal" : "reality"}`}>
            {mode === "ideal" ? "IDEAL PHYSICS — UNLIMITED ENERGY · hypothetical force inputs" : "REALITY CONSTRAINTS"}
          </div>
        )}
        {res && <div className={`verdict v-${res.feasibility.verdict.split(" ")[0]}`}>{res.feasibility.verdict}</div>}
        <div className="status">
          <span className={health ? "ok" : "bad"}>lab API {health ? "connected" : "NOT CONNECTED"}</span>
          <span className={harness?.connected ? "ok" : "bad"} title={harness?.detail}>
            Research harness: {harness?.connected ? "CONNECTED" : "NOT CONNECTED"}
          </span>
        </div>
      </header>
      <nav className="tabs">
        {([["lab", "3D flight lab"], ["params", "Parameters"], ["feasibility", "Feasibility frontier"], ["solvers", "Solvers & fields"],
          ["experiments", "Experiments"]] as [Tab, string][]).map(([k, label]) => (
          <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{label}</button>
        ))}
        <div className="spacer" />
        <label>demo preset&nbsp;
          <select value={preset} onChange={(e) => { setPreset(e.target.value); load(e.target.value); }}>
            {["ideal", "reality_baseline", "underpowered", "too_heavy", "thrust_capped"].map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <button onClick={() => load(preset)}>re-run demo</button>
      </nav>
      {loading && <div className="banner">{loading}</div>}
      {error && <div className="banner error">{error}</div>}
      <main className={tab === "lab" ? "" : "hidden"}>
        {res && charts && (
          <div className="lab">
            <div className="lab-main">
              <div className="viewport">
                <Lab3D res={res} idx={idx} opt={opt} field={field} />
                <SceneToggles opt={opt} setOpt={setOpt} />
                <div className="labels-box">
                  {res.feasibility.failing.length > 0 && (
                    <div style={{ color: "var(--bad)", fontWeight: 600 }}>
                      INFEASIBLE — failing constraints: {res.feasibility.constraints.filter((c) => c.hard && !c.passed)
                        .map((c) => `${c.label} [${c.toggle}]`).join(" · ")}
                    </div>
                  )}
                  {(res.summary.failures as string[]).length > 0 && (
                    <div style={{ color: "var(--bad)" }}>simulated outcome: {(res.summary.failures as string[]).join(", ")}</div>
                  )}
                  {res.labels.map((l, i) => <div key={i}>{l}</div>)}
                  <div>air: ρ = {res.air.rho.toFixed(4)} kg/m³, μ = {res.air.mu.toExponential(3)} Pa·s ({res.air.source})</div>
                  <div className="muted">motion = integrated forces/torques (recorded state replay; setpoint sphere = controller reference only)</div>
                </div>
              </div>
              <Timeline t={res.trajectory.t} idx={idx} playing={playing} speed={speed} phases={res.phases}
                phaseIdx={res.trajectory.phase} events={res.events} onSeek={(i) => { setPlaying(false); seek(i); }}
                onPlay={() => { if (idx >= res.trajectory.t.length - 1) seek(0); setPlaying(true); }}
                onPause={() => setPlaying(false)} onRestart={() => { seek(0); setPlaying(true); }}
                onStep={(d) => { setPlaying(false); seek(idx + d); }} onSpeed={setSpeed} />
              <div className="charts">
                <MiniChart title="altitude" unit="m" t={res.trajectory.t} series={charts.alt} idx={idx} onSeek={seek} />
                <MiniChart title="velocity" unit="m/s" t={res.trajectory.t} series={charts.vel} idx={idx} onSeek={seek} />
                <MiniChart title="vertical forces" unit="N" t={res.trajectory.t} series={charts.force} idx={idx} onSeek={seek} />
                <MiniChart title="attitude" unit="deg" t={res.trajectory.t} series={charts.att} idx={idx} onSeek={seek} />
                <MiniChart title="electrical power ESTIMATE" unit="W" t={res.trajectory.t} series={charts.power} idx={idx} onSeek={seek} />
              </div>
            </div>
            <aside>
              <Dashboard res={res} idx={idx} />
              <div className="events">
                <div className="dash-title">Events</div>
                {res.events.map((e, i) => (
                  <div key={i} className={`event ${/FAIL|DEFICIT|DEPLETED|LOSS|ABORT|DIVERGED/.test(e.kind) ? "bad" : ""}`}
                    onClick={() => { setPlaying(false); seek(frameAt(res.trajectory.t, e.t)); }}>
                    <b>{e.t.toFixed(2)} s</b> {e.kind}: {e.message}
                  </div>
                ))}
              </div>
            </aside>
          </div>
        )}
      </main>
      {tab === "params" && <ParameterEditor onResult={showResult} current={res} />}
      {tab === "feasibility" && <FeasibilityPanel current={res} />}
      {tab === "solvers" && <SolversPanel onOverlay={(f) => { setField(f); }} overlay={field} harness={harness} />}
      {tab === "experiments" && <ExperimentsPanel current={res} onLoad={showResult} />}
      <footer>
        {health?.versions && Object.entries(health.versions).map(([k, v]) => <span key={k}>{k} {v ?? "—"}</span>)}
      </footer>
    </div>
  );
}

function SceneToggles({ opt, setOpt }: { opt: SceneOptions; setOpt: (o: SceneOptions) => void }) {
  const keys: [keyof SceneOptions, string][] = [["actuators", "actuator forces"], ["gravity", "gravity"], ["net", "net force"],
    ["contact", "contact"], ["drag", "drag"], ["velocity", "velocity"], ["torque", "torque"], ["trail", "trail"],
    ["setpoint", "setpoint"], ["labels", "labels"], ["follow", "camera follow"]];
  return (
    <div className="scene-toggles">
      {keys.map(([k, label]) => (
        <label key={k}><input type="checkbox" checked={opt[k] as boolean} onChange={(e) => setOpt({ ...opt, [k]: e.target.checked })} />{label}</label>
      ))}
      <label title="force arrow scale">F scale
        <input type="range" min={0.1} max={3} step={0.1} value={opt.forceScale} onChange={(e) => setOpt({ ...opt, forceScale: parseFloat(e.target.value) })} />
        {opt.forceScale.toFixed(1)} m/N</label>
      <label title="torque arrow scale">τ scale
        <input type="range" min={200} max={10000} step={100} value={opt.torqueScale} onChange={(e) => setOpt({ ...opt, torqueScale: parseFloat(e.target.value) })} />
        {opt.torqueScale} m/(N·m)</label>
    </div>
  );
}
