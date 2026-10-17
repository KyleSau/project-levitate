// Propulsion Lab: cold-gas boosted skateboard, cold-gas hoverboard, chemical-rocket hoverboard (theoretical).
// Live 3D motion is integrated in the browser by the validated shared model (sim/propulsion/site/propulsion.js);
// studies and stored experiments come from the FastAPI backend (/api/propulsion/...).
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import LineChart from "../../components/LineChart";
import PropScene from "./PropScene";
import StudiesPanel from "./StudiesPanel";
import { G0, PP, ROM, fmt } from "./physics";
import type { Mode } from "./physics";

const MODES: [Mode | "studies", string][] = [
  ["skate", "Cold-gas boosted skateboard"], ["cghover", "Cold-gas hoverboard"], ["rocket", "Chemical-rocket hoverboard"], ["studies", "Studies & comparison"],
];
const clone = (o: any) => JSON.parse(JSON.stringify(o));

function snapshot(mode: Mode, sim: any) {
  const t = sim.tel;
  if (mode === "skate") return { t: t.t, x: t.x, v: t.v, a: t.a, thrust: t.thrust, gas: t.gas_kg, p: t.p_tank, T: t.T_tank, isp: t.isp, phi: t.phi, theta: t.theta,
    mode: t.mode, rider: t.rider_on, rx: t.rider_x, Nf: t.Nf, Nr: t.Nr, drag: t.drag, Fd: t.F_drive, bat: t.batt_wh, cgx: t.cg_x, cgz: t.cg_z, mass: t.m, mdot: t.mdot, valve: t.valve };
  return { t: t.t, pos: t.pos, q: t.q, vel: t.vel, F: t.F, mdot: t.mdot, prop: t.prop, m: t.m, cg: t.cg, cgW: t.cgW, phase: t.phase, z: t.z, tilt: t.tilt,
    p: t.p_tank, T: t.T_tank, trem: t.t_rem, failed: t.failed, thrust: t.F ? t.F.reduce((a: number, b: number) => a + b, 0) : 0 };
}

function Driver({ mode, simRef, frameRef, framesRef, ctlRef, run, replay, onTick }: any) {
  const acc = useRef(0), rec = useRef(0), hud = useRef(0);
  useFrame((_, real) => {
    const sim = simRef.current; if (!sim || sim.__mode !== mode) return;
    real = Math.min(real, 0.1);
    if (replay.current) {
      const r = replay.current, fr = framesRef.current;
      if (r.playing && r.i < fr.length - 1) { r.acc += real; while (r.i < fr.length - 1 && fr[r.i + 1].t - fr[r.i].t <= r.acc) { r.acc -= fr[r.i + 1].t - fr[r.i].t; r.i++; } }
      frameRef.current = fr[r.i];
    } else if (run.current) {
      if (mode === "skate") sim.ctl = ctlRef.current;
      acc.current += real; let n = 0;
      while (acc.current >= 0.001 && n < 120) { sim.step(0.001); acc.current -= 0.001; n++; }
      if (n >= 120) acc.current = 0;
      frameRef.current = snapshot(mode, sim);
      rec.current += real;
      if (rec.current > 1 / 30) { framesRef.current.push(frameRef.current); rec.current = 0; }
    } else if (!frameRef.current) frameRef.current = snapshot(mode, sim);
    hud.current += real;
    if (hud.current > 0.1) { hud.current = 0; onTick(); }
  });
  return null;
}

export default function PropulsionLab() {
  const [mode, setMode] = useState<Mode | "studies">("skate");
  const cfgs = useRef<Record<Mode, any>>({
    skate: clone(PP.SKATE_DEFAULT),
    cghover: { ...clone(PP.HOVER_DEFAULT), propulsion: "coldgas", tw_design: ROM.assumptions.hover.tw_margin },
    rocket: { ...clone(PP.HOVER_DEFAULT), propulsion: "rocket", tw_design: ROM.assumptions.hover.tw_margin },
  });
  const simRef = useRef<any>(null), frameRef = useRef<any>(null), framesRef = useRef<any[]>([]);
  const ctlRef = useRef({ throttle: 0, boost: false, brake: 0 });
  const run = useRef(false), replay = useRef<any>(null);
  const [tick, setTick] = useState(0);
  const [showVectors, setShowVectors] = useState(true);
  const [toastMsg, setToast] = useState<string | null>(null);
  const seenEvents = useRef(0);

  const reset = useCallback((m: Mode) => {
    const sim = m === "skate" ? new PP.SkateSim(cfgs.current.skate) : new PP.HoverSim(cfgs.current[m]);
    sim.step(0.001);
    sim.__mode = m;
    simRef.current = sim; frameRef.current = snapshot(m, sim); framesRef.current = []; replay.current = null; seenEvents.current = 0;
    run.current = m === "skate";
    ctlRef.current = { throttle: 0, boost: false, brake: 0 };
    setTick((t) => t + 1);
  }, []);
  useEffect(() => { if (mode !== "studies") reset(mode); }, [mode, reset]);
  const onTick = useCallback(() => {
    const sim = simRef.current;
    if (sim && sim.events.length > seenEvents.current) { const e = sim.events[sim.events.length - 1][1]; seenEvents.current = sim.events.length; if (!/^(climb|hover|translate|stop|yaw|hold)$/.test(e)) setToast(e); }
    setTick((t) => t + 1);
  }, []);
  useEffect(() => {
    const down = (e: KeyboardEvent) => { if (mode !== "skate") return; const k = e.key.toLowerCase();
      if (k === "w" || k === "arrowup") ctlRef.current = { ...ctlRef.current, throttle: 1, brake: 0 };
      if (k === "s" || k === "arrowdown") ctlRef.current = { ...ctlRef.current, brake: 0.2, throttle: 0 };
      if (k === " ") { e.preventDefault(); ctlRef.current = { ...ctlRef.current, boost: !ctlRef.current.boost }; } };
    const up = (e: KeyboardEvent) => { const k = e.key.toLowerCase();
      if (k === "w" || k === "arrowup") ctlRef.current = { ...ctlRef.current, throttle: 0 };
      if (k === "s" || k === "arrowdown") ctlRef.current = { ...ctlRef.current, brake: 0 }; };
    addEventListener("keydown", down); addEventListener("keyup", up);
    return () => { removeEventListener("keydown", down); removeEventListener("keyup", up); };
  }, [mode]);

  if (mode === "studies") return (<div className="page"><ModeTabs mode={mode} setMode={setMode} /><StudiesPanel cfgs={cfgs.current} /></div>);
  const ready = simRef.current && simRef.current.__mode === mode;
  const sim = ready ? simRef.current : null, f = ready ? frameRef.current : null;
  const frames = ready ? framesRef.current : [];
  void tick;
  return (
    <div className="split">
      <div className="col">
        <ModeTabs mode={mode} setMode={setMode} vertical />
        <Params mode={mode} cfg={cfgs.current[mode]} onApply={() => reset(mode)} />
      </div>
      <div style={{ position: "relative", minHeight: 0, display: "grid", gridTemplateRows: "1fr auto" }}>
        <div style={{ position: "relative", minHeight: 0 }}>
          <Canvas shadows camera={{ position: mode === "skate" ? [1, 1.6, 4.5] : [1.5, 2.2, 19], fov: 50 }}>
            <Driver mode={mode} simRef={simRef} frameRef={frameRef} framesRef={framesRef} ctlRef={ctlRef} run={run} replay={replay} onTick={onTick} />
            <PropScene mode={mode} simRef={simRef} frameRef={frameRef} showVectors={showVectors} />
          </Canvas>
          {sim && f && <Hud mode={mode} sim={sim} f={f} />}
          {toastMsg && <div className="card" style={{ position: "absolute", left: "50%", top: 12, transform: "translateX(-50%)", borderColor: /FELL|FAIL|IMPACT|LOST|CANNOT|crash/i.test(toastMsg) ? "var(--bad)" : "var(--line)" }}
            onClick={() => setToast(null)}>{toastMsg}</div>}
        </div>
        <div className="card" style={{ margin: 8, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {mode === "skate" ? <SkateControls ctlRef={ctlRef} /> : (
            <>
              <button className="btn primary" onClick={() => { if (sim?.phase === "done") reset(mode); run.current = true; replay.current = null; }}>Fly mission</button>
              <button className="btn" onClick={() => { if (sim) sim.manualLand = true; }}>Land now</button>
            </>)}
          <button className="btn" onClick={() => { if (replay.current) replay.current.playing = !replay.current.playing; else run.current = !run.current; setTick((t) => t + 1); }}>
            {(replay.current ? replay.current.playing : run.current) ? "Pause" : "Play"}</button>
          <button className="btn" onClick={() => reset(mode as Mode)}>Restart</button>
          <button className="btn" onClick={() => { if (frames.length) replay.current = { i: 0, playing: true, acc: 0 }; }}>Replay</button>
          <input type="range" min={0} max={Math.max(frames.length - 1, 0)} value={replay.current ? replay.current.i : Math.max(frames.length - 1, 0)} style={{ flex: 1, minWidth: 120 }}
            onChange={(e) => { replay.current = { i: +e.target.value, playing: false, acc: 0 }; setTick((t) => t + 1); }} />
          <span className="num">{fmt(f?.t, 1)} s</span>
          <label className="note"><input type="checkbox" checked={showVectors} onChange={(e) => setShowVectors(e.target.checked)} /> vectors</label>
        </div>
      </div>
      <div className="col">{sim && f && <Dashboard mode={mode} sim={sim} f={f} frames={frames} />}</div>
    </div>
  );
}

function ModeTabs({ mode, setMode, vertical }: any) {
  return (<div style={{ display: "flex", flexDirection: vertical ? "column" : "row", gap: 4, marginBottom: 10 }}>
    {MODES.map(([k, l]) => <button key={k} className={`tab ${mode === k ? "active" : ""}`} onClick={() => setMode(k)}>{l}</button>)}</div>);
}

function SkateControls({ ctlRef }: any) {
  const [boost, setBoost] = useState(false);
  const hold = (k: "throttle" | "brake", v: number) => ({
    onPointerDown: () => { ctlRef.current = { ...ctlRef.current, [k]: v, ...(k === "throttle" ? { brake: 0 } : { throttle: 0 }) }; },
    onPointerUp: () => { ctlRef.current = { ...ctlRef.current, [k]: 0 }; }, onPointerLeave: () => { ctlRef.current = { ...ctlRef.current, [k]: 0 }; },
  });
  return (<>
    <button className="btn primary" {...hold("throttle", 1)}>Accelerate (hold, W)</button>
    <button className="btn" style={{ borderColor: boost ? "var(--warn)" : undefined }} onClick={() => { const b = !ctlRef.current.boost; ctlRef.current = { ...ctlRef.current, boost: b }; setBoost(b); }}>Boost {boost ? "ON" : "off"} (space)</button>
    <button className="btn" onClick={() => { ctlRef.current = { throttle: 0, boost: false, brake: 0 }; setBoost(false); }}>Coast</button>
    <button className="btn" {...hold("brake", 0.2)}>Brake (hold, S)</button>
  </>);
}

function Hud({ mode, sim, f }: any) {
  const items: [string, string][] = mode === "skate"
    ? [["speed", `${fmt(f.v * 3.6, 0)} km/h`], ["accel", `${fmt(f.a / G0, 2)} g`], ["thrust", `${fmt(f.thrust, 0)} N`], ["air", sim.gasSys ? `${fmt(f.gas / sim.gasSys.m0 * 100, 0)} %` : "–"],
      ["state", f.rider ? f.mode : "RIDER FELL"]]
    : [["height", `${fmt(Math.max(f.z, 0), 2)} m`], ["thrust", `${fmt(f.thrust, 0)} N`], ["propellant", `${fmt(f.prop, 1)} kg`], ["hover left", `${fmt(f.trem, 1)} s`], ["phase", f.failed ? "FAILED" : f.phase]];
  return (<div style={{ position: "absolute", left: 8, top: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
    {items.map(([k, v]) => <div key={k} className="card" style={{ margin: 0, padding: "6px 10px" }}><div className="note">{k}</div><div className="num" style={{ fontSize: 16, textAlign: "left" }}>{v}</div></div>)}</div>);
}

function Params({ mode, cfg, onApply }: any) {
  const [, force] = useState(0);
  const set = (path: string, v: any) => { const ks = path.split("."); let o = cfg; for (const k of ks.slice(0, -1)) o = o[k]; o[ks[ks.length - 1]] = v; force((x) => x + 1); };
  const get = (path: string) => path.split(".").reduce((o, k) => o?.[k], cfg);
  const num = (path: string, label: string, lo: number, hi: number, step: number) => (
    <div className="row" key={path}><label style={{ width: 150 }}>{label}</label>
      <input type="range" min={lo} max={hi} step={step} value={get(path) ?? lo} onChange={(e) => set(path, +e.target.value)} /><span className="num">{fmt(get(path), step < 1 ? 2 : 0)}</span></div>);
  const sel = (path: string, label: string, opts: [string, string][]) => (
    <div className="row" key={path}><label>{label}</label><select value={String(get(path))} onChange={(e) => set(path, e.target.value === "true" ? true : e.target.value === "false" ? false : e.target.value)}>
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>);
  const tankRows = [num("tank.volume_l", "Tank volume (L, each)", 1, 60, 0.5), num("tank.n_tanks", "Tanks", 1, 8, 1), num("tank.pressure_bar", "Fill pressure (bar)", 50, 700, 10),
    sel("tank.tank_class", "Tank construction", [["metal", "steel/Al (18 kJ/kg)"], ["type3", "carbon T3 (44 kJ/kg)"], ["type4", "carbon T4 (98 kJ/kg)"]]),
    sel("tank.gas", "Gas", [["air", "air"], ["n2", "nitrogen"]]), sel("tank.thermal", "Tank thermal model", [["heat_transfer", "wall heat transfer"], ["adiabatic", "adiabatic"], ["isothermal", "isothermal"]])];
  return (<div>
    <h2>Parameters</h2>
    {mode === "skate" ? [num("rider_kg", "Rider (kg)", 40, 150, 1), sel("stance", "Stance", [["upright", "upright"], ["crouch", "crouch"]]), sel("electric", "Hub motors", [["true", "dual hub"], ["false", "none"]]),
      sel("coldgas", "Cold-gas boost", [["true", "fitted"], ["false", "none"]]), ...tankRows, num("thruster.reg_pressure_bar", "Regulator (bar)", 5, 80, 1),
      num("thruster.throat_diameter_mm", "Throat dia. (mm)", 2, 14, 0.5), num("thrust_height_m", "Thrust line height (m)", 0.05, 1.4, 0.01), num("boost_ramp_s", "Valve ramp (s)", 0, 2, 0.1),
      sel("rider_anticipates", "Rider", [["true", "leans in (anticipates)"], ["false", "surprised"]]), sel("deadman", "Dead-man cut-off", [["true", "on"], ["false", "off"]])]
      : [num("rider_kg", "Rider (kg)", 0, 150, 1), num("tw_design", "Installed T/W", 0.8, 2, 0.05), num("cant_deg", "Thruster cant (deg)", 0, 20, 1),
        ...(mode === "cghover" ? [...tankRows, num("reg_pressure_bar", "Regulator (bar)", 10, 100, 1)]
          : [sel("engine.engine_class", "Engine class (black box)", [["monoprop", "monoprop-class Isp 140 s"], ["biprop", "biprop-class Isp 250 s"], ["solid", "solid-class (no throttle/stop)"]]),
            num("engine.propellant_kg", "Propellant (kg)", 2, 150, 1)]),
        num("mission.hover_height_m", "Hover height (m)", 0.2, 3, 0.1), num("mission.translate_m", "Translate (m)", 0, 20, 0.5), num("mission.yaw_deg", "Rotate (deg)", -180, 180, 15),
        num("mission.hold_s", "Hold (s)", 0, 10, 0.5), num("reserve_s", "Land with reserve (s)", 0, 5, 0.5)]}
    <button className="btn primary" style={{ marginTop: 10, width: "100%" }} onClick={onApply}>Apply &amp; restart</button>
    <p className="note">All values are assumptions (see Studies tab for sources). Engines/thrusters are black boxes. Simulation only — any physical test must be professionally reviewed, unmanned and contained.</p>
  </div>);
}

function Dashboard({ mode, sim, f, frames }: any) {
  const xs = frames.map((x: any) => x.t);
  const charts = mode === "skate"
    ? [{ name: "speed m/s", color: "#38d6ff", ys: frames.map((x: any) => x.v) }, { name: "thrust N", color: "#ffb547", ys: frames.map((x: any) => x.thrust) }, { name: "accel g", color: "#3ddc97", ys: frames.map((x: any) => x.a / G0) }]
    : [{ name: "height m", color: "#38d6ff", ys: frames.map((x: any) => Math.max(x.z, 0)) }, { name: "thrust N", color: "#ffb547", ys: frames.map((x: any) => x.thrust) }, { name: "propellant kg", color: "#3ddc97", ys: frames.map((x: any) => x.prop) }];
  const rows = useMemo(() => dashRows(mode, sim, f), [mode, sim, f]);
  return (<div>
    <h2>Dashboard</h2>
    <div className="card"><div className="kv">{rows.map(([k, v]) => [<div className="k" key={k + "k"}>{k}</div>, <div className="num" key={k + "v"}>{v}</div>])}</div></div>
    <h2>Time histories</h2>
    {charts.map((s) => <div className="card" key={s.name}><LineChart xs={xs} series={[s]} height={110} xLabel="t (s)" yLabel={s.name} /></div>)}
    <h2>Warnings</h2>
    {warnings(mode, sim, f).map((w, i) => <div key={i} className={w[0] ? "fail" : "note"} style={{ marginBottom: 6 }}>{w[1]}</div>)}
  </div>);
}

function dashRows(mode: Mode, sim: any, f: any): [string, string][] {
  if (mode === "skate") {
    const parts = sim.parts(), gs = sim.gasSys, c = sim.cfg;
    const cost = ROM.assumptions.skateboard.cost_board + (c.electric ? ROM.assumptions.skateboard.cost_edrive : 0) + (gs ? PP.tankCost(c.tank) + ROM.assumptions.coldgas.cost_valves_base + ROM.assumptions.coldgas.cost_per_thruster : 0);
    return [["total mass", `${fmt(f.mass, 1)} kg`], ...parts.map((p: any) => [p[0], `${fmt(p[1], 2)} kg`] as [string, string]),
      ["thrust", `${fmt(f.thrust, 0)} N`], ["Isp", `${fmt(f.isp, 0)} s`], ["gas flow", `${fmt(f.mdot * 1000, 0)} g/s`], ["speed", `${fmt(f.v, 2)} m/s`], ["acceleration", `${fmt(f.a / G0, 3)} g`],
      ["air remaining", gs ? `${fmt(f.gas, 2)} kg · ${fmt(f.p / 1e5, 0)} bar` : "–"], ["boost left (full valve)", gs && f.mdot > 0 ? `${fmt(f.gas / f.mdot, 1)} s` : "–"],
      ["battery", `${fmt(f.bat, 0)} Wh`], ["distance", `${fmt(f.x, 1)} m`], ["parts cost", `$${fmt(cost, 0)}`], ["energy closure", `${fmt(sim.ledger().rel_residual * 100, 5)} %`]];
  }
  const [m0] = sim.massProps(), cosd = Math.cos(sim.cfg.cant_deg * Math.PI / 180);
  return [["total mass", `${fmt(f.m, 1)} kg`], ["gross at start", `${fmt(m0, 1)} kg`], ...sim.parts().map((p: any) => [p[0], `${fmt(p[1], 2)} kg`] as [string, string]),
    ["installed thrust", `${fmt(4 * sim.F_design, 0)} N`], ["thrust now", `${fmt(f.thrust, 0)} N`], ["T/W now", fmt(f.thrust * cosd / (f.m * G0), 2)], ["consumption", `${fmt(f.mdot, 2)} kg/s`],
    ["height", `${fmt(f.z, 2)} m`], ["speed", `${fmt(Math.hypot(f.vel[0], f.vel[1]), 2)} m/s`], ["propellant", `${fmt(f.prop, 2)} kg`], ["hover time left", `${fmt(f.trem, 1)} s`], ["phase", f.failed || f.phase]];
}

function warnings(mode: Mode, sim: any, f: any): [boolean, string][] {
  const w: [boolean, string][] = [];
  if (mode === "skate") {
    if (!f.rider) w.push([true, "Rider fell off the board."]);
    if (f.mode !== "rolling") w.push([true, `Board ${f.mode}.`]);
    if (f.v > 12) w.push([true, "Above ~12-13 m/s urethane-wheel boards develop speed wobble."]);
    if (sim.gasSys) { const r = PP.energyReport(sim.cfg.tank); w.push([false, `Stored gas ${fmt(r.burst_energy_kj, 0)} kJ (${fmt(r.tnt_equiv_kg, 2)} kg TNT eq.): 1 psi to ${fmt(r.blast_radius_1psi_m, 1)} m on vessel failure.`]); }
  } else {
    if (f.failed) w.push([true, "FAILED: " + f.failed]);
    if (sim.aborted) w.push([true, "Mission aborted on propellant reserve."]);
    w.push([false, sim.gas ? "Cold exhaust jets, ~-150 C at the nozzle; tens of MJ of stored gas under the rider." : "Black-box chemical rocket: hot exhaust, extreme noise (>145 dB at the rider), fire/toxicity not modelled."]);
  }
  return w;
}
