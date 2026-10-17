// Physics parameter editor. Every change is re-analysed by the backend (static feasibility + mass
// properties derived from the mass distribution). Changing mass/CG/geometry never edits a running
// simulation: "Run" restarts the mission from rest with the new configuration, so no conservation law
// is violated by a mid-flight parameter jump.
import { useEffect, useMemo, useRef, useState } from "react";
import type { Feasibility, ModeConfig, SimResult, VehicleInfo } from "../api";
import { fmt, getJSON, postJSON } from "../api";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Obj = Record<string, any>;

interface Defaults { vehicle: Obj; gains: Obj; settings: Obj; mission: Obj[]; presets: Record<string, ModeConfig> }
interface Analysis { feasibility: Feasibility; vehicle: VehicleInfo; labels: string[]; power_model: string;
  air: { rho: number; mu: number; source: string }; evidence: string; contact_lambda_max: number }

const TOGGLE_INFO: Record<string, string> = {
  thrust_limit: "max force per actuator",
  torque_limit: "max body torque per axis (applied to the controller command)",
  efficiency: "propulsion efficiency: figure of merit, motor efficiency, duct factor",
  power_limit: "max total electrical power (motor/ESC rating)",
  battery: "battery: capacity, mass, internal resistance, C-rate (energy depletes, power capped)",
  conversion_losses: "ESC / HV-converter efficiency",
  total_mass: "override total mass (incl. battery)",
  dimensions: "board dimensions (scales mass layout & actuator positions)",
  drag: "aerodynamic drag (also active in IDEAL mode)",
  ground_effect: "rotor ground effect (Cheeseman-Bennett)",
  thermal: "lumped actuator thermal model with derating",
  delays: "actuator first-order lag + transport delay",
  added_mass: "added (fluid) mass from the FEM reduced-order model",
};

function Num({ label, value, onChange, scale = 1, unit, disabled }: {
  label: string; value: number | null; onChange: (v: number) => void; scale?: number; unit?: string; disabled?: boolean;
}) {
  const show = (v: number | null) => (v === null ? "" : String(+(v * scale).toPrecision(6)));
  const [txt, setTxt] = useState<string>(show(value));
  useEffect(() => { setTxt(show(value)); }, [value, scale]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="field">
      <span>{label}</span>
      <span>
        <input type="number" value={txt} step="any" disabled={disabled}
          onChange={(e) => { setTxt(e.target.value); const v = parseFloat(e.target.value); if (Number.isFinite(v)) onChange(v / scale); }} />
        {unit && <span className="muted"> {unit}</span>}
      </span>
    </div>
  );
}

function clone<T>(o: T): T { return JSON.parse(JSON.stringify(o)); }

export function ParameterEditor({ onResult, current }: { onResult: (r: SimResult) => void; current: SimResult | null }) {
  const [defs, setDefs] = useState<Defaults | null>(null);
  const [mode, setMode] = useState<ModeConfig | null>(null);
  const [vehicle, setVehicle] = useState<Obj | null>(null);
  const [gains, setGains] = useState<Obj | null>(null);
  const [settings, setSettings] = useState<Obj | null>(null);
  const [massG, setMassG] = useState(20);
  const [cgMm, setCgMm] = useState<[number, number, number]>([0, 0, 0]);
  const [cgOn, setCgOn] = useState(false);
  const [an, setAn] = useState<Analysis | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    getJSON<Defaults>("/api/defaults").then((d) => {
      setDefs(d);
      setVehicle(clone(d.vehicle));
      setGains(clone(d.gains));
      setSettings(clone(d.settings));
      setMode(clone(current?.mode_config ?? d.presets.ideal));
    }).catch((e) => setErr(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const request = useMemo(() => {
    if (!mode || !vehicle || !gains || !settings) return null;
    return { vehicle, total_mass_kg: massG / 1000, cg_m: cgOn ? cgMm.map((c) => c / 1000) : null, mode, gains, settings,
      name: `custom (${mode.mode})` };
  }, [mode, vehicle, gains, settings, massG, cgMm, cgOn]);

  useEffect(() => {
    if (!request) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      postJSON<Analysis>("/api/analyse", request).then((a) => { setAn(a); setErr(null); }).catch((e) => setErr(String(e)));
    }, 350);
  }, [request]);

  if (!defs || !mode || !vehicle || !gains || !settings) return <div className="panel">{err ?? "loading defaults…"}</div>;

  const setM = (path: string[], v: unknown) => {
    const m = clone(mode);
    let o: Obj = m;
    for (const k of path.slice(0, -1)) o = o[k];
    o[path[path.length - 1]] = v;
    setMode(m);
  };
  const limiting = new Set(an?.feasibility.limiting_toggles ?? []);
  const ideal = mode.mode === "ideal";

  const run = async () => {
    if (!request) return;
    setBusy(true);
    setErr(null);
    try {
      onResult(await postJSON<SimResult>("/api/simulate", request));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const moveActuator = (i: number, axis: 0 | 1, valM: number) => {
    if (!Number.isFinite(valM)) return;
    const v = clone(vehicle);
    v.actuators[i].pos_m[axis] = valM;
    const comp = v.components.find((c: Obj) => c.name === `propulsion module ${i}`);
    if (comp) comp.pos_m[axis] = valM; // the module's mass moves with its actuator -> inertia stays consistent
    setVehicle(v);
  };

  const J = an?.vehicle.inertia_kgm2;
  return (
    <div className="panel">
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>Physics parameters</h2>
        <label><input type="radio" checked={ideal} onChange={() => setM(["mode"], "ideal")} /> IDEAL PHYSICS — UNLIMITED ENERGY</label>
        <label><input type="radio" checked={!ideal} onChange={() => setM(["mode"], "reality")} /> REALITY CONSTRAINTS</label>
        <label>load preset <select defaultValue="" onChange={(e) => { if (e.target.value) setMode(clone(defs.presets[e.target.value])); }}>
          <option value="">—</option>{Object.keys(defs.presets).map((p) => <option key={p}>{p}</option>)}</select></label>
        <label>integrator <select value={settings.integrator} onChange={(e) => setSettings({ ...settings, integrator: e.target.value })}>
          <option value="rk4">RK4 fixed step (real-time)</option><option value="dop853">SciPy DOP853 (offline, slow)</option></select></label>
        <Num label="dt" value={settings.dt} scale={1000} unit="ms" onChange={(v) => setSettings({ ...settings, dt: v })} />
        <button className="primary" disabled={busy} onClick={run}>{busy ? "simulating…" : "▶ Run demo mission (restart from rest)"}</button>
        <button onClick={() => { setVehicle(clone(defs.vehicle)); setGains(clone(defs.gains)); setSettings(clone(defs.settings)); setMassG(20); setCgOn(false); setCgMm([0, 0, 0]); }}>reset vehicle & gains</button>
      </div>
      {err && <div className="banner error">{err}</div>}
      {an && (
        <div className="card" style={{ marginTop: 10 }}>
          <b className={`verdict v-${an.feasibility.verdict.split(" ")[0]}`}>{an.feasibility.verdict}</b>{" "}
          <span className="muted">evidence: {an.evidence}</span>
          {an.feasibility.failing.length > 0 && (
            <div style={{ color: "var(--bad)", marginTop: 4 }}>
              Infeasible because of: {an.feasibility.constraints.filter((c) => !c.passed && c.hard).map((c) =>
                `${c.label} (${fmt(c.value)} vs ${fmt(c.limit)} ${c.unit}; constraint: ${c.toggle})`).join(" · ")}
            </div>
          )}
          {an.feasibility.marginal.length > 0 && <div style={{ color: "var(--warn)" }}>marginal: {an.feasibility.marginal.join(", ")}</div>}
          <div className="muted">{an.labels.join(" · ")}</div>
        </div>
      )}
      <div className="grid2" style={{ marginTop: 10 }}>
        <div className="card">
          <h3>Vehicle mass distribution</h3>
          <Num label="total mass (structure; battery added in REALITY)" value={massG} unit="g" onChange={setMassG} />
          <label className="field"><span>set centre of mass (moves CG-trim payload)</span><input type="checkbox" checked={cgOn} onChange={(e) => setCgOn(e.target.checked)} /></label>
          {(["x", "y", "z"] as const).map((ax, i) => (
            <Num key={ax} label={`CG ${ax}`} value={cgMm[i]} unit="mm" disabled={!cgOn}
              onChange={(v) => { const c = [...cgMm] as [number, number, number]; c[i] = v; setCgMm(c); }} />
          ))}
          {an && (
            <>
              <div className="field"><span>mass (derived)</span><b>{fmt(an.vehicle.mass_kg * 1000, 5)} g</b></div>
              <div className="field"><span>weight m·g</span><b>{fmt(an.vehicle.mass_kg * mode.environment.g, 5)} N</b></div>
              <div className="field"><span>CG (derived)</span><span>{an.vehicle.cg_m.map((c) => fmt(c * 1000, 3)).join(", ")} mm</span></div>
              <div className="muted">inertia tensor about CG [kg·m²] (from components, parallel-axis theorem) — {an.vehicle.inertia_valid ? "valid" : "INVALID"}</div>
              <table><tbody>{J?.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className="num">{v.toExponential(3)}</td>)}</tr>)}</tbody></table>
              <div className="muted">principal moments: {an.vehicle.principal_moments_kgm2.map((v) => v.toExponential(3)).join(", ")}</div>
              <table style={{ marginTop: 6 }}>
                <thead><tr><th>component</th><th>mass g</th><th>pos mm</th></tr></thead>
                <tbody>{an.vehicle.components.map((c, i) => (
                  <tr key={i}><td>{c.name}</td><td className="num">{fmt(c.mass_kg * 1000, 4)}</td>
                    <td className="num">{c.pos_m.map((p) => (p * 1000).toFixed(1)).join(", ")}</td></tr>))}</tbody>
              </table>
            </>
          )}
        </div>
        <div className="card">
          <h3>Actuators {ideal ? "(HYPOTHETICAL force inputs)" : ""}</h3>
          <table>
            <thead><tr><th>#</th><th>x mm</th><th>y mm</th><th>spin</th><th>F max (resolved)</th><th>mechanism</th></tr></thead>
            <tbody>
              {vehicle.actuators.map((a: Obj, i: number) => (
                <tr key={i}>
                  <td>A{i}</td>
                  <td><input type="number" style={{ width: 70 }} value={+(a.pos_m[0] * 1000).toFixed(2)} onChange={(e) => moveActuator(i, 0, parseFloat(e.target.value) / 1000)} /></td>
                  <td><input type="number" style={{ width: 60 }} value={+(a.pos_m[1] * 1000).toFixed(2)} onChange={(e) => moveActuator(i, 1, parseFloat(e.target.value) / 1000)} /></td>
                  <td>{a.spin > 0 ? "CCW" : "CW"}</td>
                  <td className="num">{an ? fmt(an.vehicle.actuators[i]?.max_force_n ?? Infinity) : "—"} N</td>
                  <td className="muted">{an?.vehicle.actuators[i]?.mechanism}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Num label="rotor radius (power model / ground effect)" value={vehicle.actuators[0].radius_m} scale={1000} unit="mm"
            onChange={(v) => { const x = clone(vehicle); x.actuators.forEach((a: Obj) => { a.radius_m = v; }); setVehicle(x); }} />
          <Num label="reaction torque ratio κ" value={vehicle.actuators[0].torque_ratio_m} scale={1000} unit="mm"
            onChange={(v) => { const x = clone(vehicle); x.actuators.forEach((a: Obj) => { a.torque_ratio_m = v; }); setVehicle(x); }} />
          {ideal && (
            <>
              <h3>Ideal mode</h3>
              <label className="field"><span>unlimited actuator force</span>
                <input type="checkbox" checked={mode.ideal_force_limit_n === null} onChange={(e) => setM(["ideal_force_limit_n"], e.target.checked ? null : 0.1)} /></label>
              {mode.ideal_force_limit_n !== null && <Num label="|F| limit per actuator" value={mode.ideal_force_limit_n} unit="N" onChange={(v) => setM(["ideal_force_limit_n"], v)} />}
              <label className="field"><span>bidirectional (push & pull) force</span>
                <input type="checkbox" checked={mode.ideal_bidirectional} onChange={(e) => setM(["ideal_bidirectional"], e.target.checked)} /></label>
              <label className="field"><span>aerodynamic drag</span><input type="checkbox" checked={mode.drag.enabled} onChange={(e) => setM(["drag", "enabled"], e.target.checked)} /></label>
              <label className="field"><span>added mass (FEM ROM)</span><input type="checkbox" checked={mode.added_mass.enabled} onChange={(e) => setM(["added_mass", "enabled"], e.target.checked)} /></label>
              <div className="muted">Energy unlimited, storage massless, actuators instantaneous. Gravity, Newton–Euler, CG/inertia, drag and contact still apply.</div>
            </>
          )}
          {!ideal && (
            <div className="field"><span>propulsion type</span>
              <select value={mode.propulsion} onChange={(e) => setM(["propulsion"], e.target.value)}>
                {["ducted_rotor", "open_rotor", "ionic_wind", "hypothetical_ideal"].map((p) => <option key={p}>{p}</option>)}
              </select></div>
          )}
        </div>
        {!ideal && Object.keys(TOGGLE_INFO).map((k) => {
          const c = mode[k] as Obj;
          if (!c) return null;
          return (
            <div key={k} className={`card ${c.enabled ? "" : "off"}`} style={limiting.has(k) ? { borderColor: "var(--bad)" } : undefined}>
              <label className="field"><b>{k}{limiting.has(k) && <span className="pill bad" style={{ marginLeft: 6 }}>LIMITING</span>}</b>
                <input type="checkbox" checked={!!c.enabled} onChange={(e) => setM([k, "enabled"], e.target.checked)} /></label>
              <div className="muted">{TOGGLE_INFO[k]}</div>
              {Object.entries(c).filter(([f]) => f !== "enabled").map(([f, v]) => (
                typeof v === "number" ? <Num key={f} label={f} value={v} disabled={!c.enabled} onChange={(x) => setM([k, f], x)} />
                  : typeof v === "boolean" ? <label key={f} className="field"><span>{f}</span><input type="checkbox" checked={v} disabled={!c.enabled} onChange={(e) => setM([k, f], e.target.checked)} /></label>
                    : Array.isArray(v) ? <div key={f} className="field"><span>{f}</span><span>{v.map((x: number, i: number) => (
                      <input key={i} type="number" style={{ width: 70 }} value={x} disabled={!c.enabled}
                        onChange={(e) => { const arr = [...v]; arr[i] = parseFloat(e.target.value); setM([k, f], arr); }} />))}</span></div> : null
              ))}
            </div>
          );
        })}
        <div className="card">
          <h3>Environment</h3>
          <Num label="gravity g" value={mode.environment.g} unit="m/s²" onChange={(v) => setM(["environment", "g"], v)} />
          <Num label="temperature" value={mode.environment.temperature_k} unit="K" onChange={(v) => setM(["environment", "temperature_k"], v)} />
          <Num label="pressure" value={mode.environment.pressure_pa} scale={0.001} unit="kPa" onChange={(v) => setM(["environment", "pressure_pa"], v)} />
          <div className="field"><span>air properties</span>
            <select value={mode.environment.air_model} onChange={(e) => setM(["environment", "air_model"], e.target.value)}>
              <option value="isa_ideal_gas">ideal gas + Sutherland</option><option value="cantera_rom">Cantera lookup table (ROM)</option></select></div>
          {an && <div className="muted">ρ = {an.air.rho.toFixed(5)} kg/m³ · μ = {an.air.mu.toExponential(4)} Pa·s · {an.air.source}</div>}
          <label className="field"><span>buoyancy ρ·V·g</span><input type="checkbox" checked={mode.environment.buoyancy} onChange={(e) => setM(["environment", "buoyancy"], e.target.checked)} /></label>
          {[0, 1, 2].map((i) => <Num key={i} label={`wind ${"xyz"[i]}`} value={mode.environment.wind_m_s[i]} unit="m/s"
            onChange={(v) => { const w = [...mode.environment.wind_m_s]; w[i] = v; setM(["environment", "wind_m_s"], w); }} />)}
        </div>
        <div className="card">
          <h3>Disturbances & failures</h3>
          <Num label="gust force std (OU process)" value={mode.disturbances.gust_std_n} unit="N" onChange={(v) => setM(["disturbances", "gust_std_n"], v)} />
          <Num label="gust correlation time" value={mode.disturbances.gust_tau_s} unit="s" onChange={(v) => setM(["disturbances", "gust_tau_s"], v)} />
          <Num label="position sensor noise σ" value={mode.disturbances.sensor_noise_pos_m} scale={1000} unit="mm" onChange={(v) => setM(["disturbances", "sensor_noise_pos_m"], v)} />
          <Num label="attitude sensor noise σ" value={mode.disturbances.sensor_noise_att_rad} unit="rad" onChange={(v) => setM(["disturbances", "sensor_noise_att_rad"], v)} />
          <Num label="controller mass model error" value={mode.disturbances.controller_mass_error} scale={100} unit="%" onChange={(v) => setM(["disturbances", "controller_mass_error"], v)} />
          <div className="field"><span>fail actuator</span>
            <select value={mode.disturbances.actuator_failure_index ?? ""} onChange={(e) => setM(["disturbances", "actuator_failure_index"], e.target.value === "" ? null : parseInt(e.target.value))}>
              <option value="">none</option>{vehicle.actuators.map((_: Obj, i: number) => <option key={i} value={i}>A{i}</option>)}</select></div>
          <Num label="failure time" value={mode.disturbances.actuator_failure_t_s} unit="s" onChange={(v) => setM(["disturbances", "actuator_failure_t_s"], v)} />
          <div className="muted">Default demo applies a 0.04 N lateral gust impulse at t = 5 s unless impulses are set via the API.</div>
        </div>
        <div className="card">
          <h3>Controller gains (cascade)</h3>
          {Object.entries(gains).map(([k, v]) => typeof v === "number" ? <Num key={k} label={k} value={v} onChange={(x) => setGains({ ...gains, [k]: x })} />
            : Array.isArray(v) ? <div key={k} className="field"><span>{k}</span><span>{(v as number[]).map((x, i) => (
              <input key={i} type="number" style={{ width: 60 }} value={x} onChange={(e) => { const a = [...v]; a[i] = parseFloat(e.target.value); setGains({ ...gains, [k]: a }); }} />))}</span></div> : null)}
        </div>
      </div>
    </div>
  );
}
