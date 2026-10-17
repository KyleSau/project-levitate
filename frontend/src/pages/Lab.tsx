import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Grid, OrbitControls, Line } from "@react-three/drei";
import * as THREE from "three";
import { api, fmt, type Design, type Report } from "../api";
import Board3D, { quatToThree, toThree } from "../components/Board3D";
import LineChart from "../components/LineChart";

const NUM_FIELDS: [keyof Design, string, number, number, number][] = [
  ["length_mm", "Length (mm)", 80, 140, 0.5],
  ["width_mm", "Width (mm)", 25, 45, 0.5],
  ["board_height_mm", "Deck thickness (mm)", 4, 16, 0.1],
  ["skin_mm", "Skin (mm)", 0.4, 2, 0.05],
  ["wall_mm", "Duct wall (mm)", 0.4, 1.5, 0.05],
  ["n_rotors", "Rotors", 2, 8, 1],
  ["rotor_diameter_mm", "Rotor diameter (mm)", 10, 40, 0.1],
  ["lateral_offset_mm", "Lateral stagger (mm)", 0, 12, 0.1],
  ["tip_gap_mm", "Tip gap (mm)", 0.1, 1.5, 0.05],
  ["extra_payload_g", "Extra payload (g)", 0, 20, 0.5],
  ["hover_altitude_m", "Hover altitude (m)", 0.01, 2, 0.01],
];

function Scene({ rep, frame, xray, clipX, showForces, follow, trail }: {
  rep: Report; frame: number | null; xray: boolean; clipX: number | null; showForces: boolean; follow: boolean; trail: boolean;
}) {
  const g = rep.geometry;
  const sim = rep.sim;
  const group = useRef<THREE.Group>(null);
  const nominal = rep.scenarios.nominal;
  let pos = new THREE.Vector3(0, g.height_m / 2 + 0.06, 0);
  let quat = new THREE.Quaternion();
  let thrusts = nominal.hover_thrust_per_rotor_n;
  if (sim && frame !== null) {
    const i = Math.min(Math.floor(frame), sim.t.length - 1);
    // board bottom rests on the ground at z=0 in the sim; draw relative to CG height above bottom
    const p = sim.pos[i];
    pos = toThree([p[0], p[1], p[2] + g.height_m / 2 - g.cg[2]]);
    quat = quatToThree(sim.quat[i]);
    thrusts = sim.thrusts[i];
  }
  const trailPts = useMemo(() => (sim ? sim.pos.map((p) => toThree([p[0], p[1], p[2] + g.height_m / 2 - g.cg[2]])) : []), [sim, g]);
  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3; update: () => void } | null;
  useFrame(({ camera }) => {
    if (follow && group.current && controls) {
      // translate camera and orbit target together so the user can still orbit while following
      const delta = group.current.position.clone().sub(controls.target).multiplyScalar(0.15);
      camera.position.add(delta);
      controls.target.add(delta);
      controls.update();
    }
  });
  return (
    <>
      <group ref={group} position={pos} quaternion={quat}>
        <Board3D g={g} thrusts={thrusts} xray={xray} clipX={clipX} showForces={showForces} mass_kg={nominal.mass_g / 1000}
          spinning={!sim || frame === null || thrusts.some((t) => t > 1e-4)} />
      </group>
      {trail && trailPts.length > 1 && <Line points={trailPts} color="#7c6cff" lineWidth={1} transparent opacity={0.7} />}
    </>
  );
}

export default function Lab({ loadExperiment }: { loadExperiment: number | null }) {
  const [cat, setCat] = useState<any>(null);
  const [design, setDesign] = useState<Design | null>(null);
  const [rep, setRep] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [xray, setXray] = useState(false);
  const [clip, setClip] = useState(false);
  const [clipX, setClipX] = useState(0);
  const [forces, setForces] = useState(true);
  const [follow, setFollow] = useState(true);
  const [trail, setTrail] = useState(true);
  const [frame, setFrame] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [sens, setSens] = useState<any[] | null>(null);
  const deb = useRef<number>();

  useEffect(() => { api.catalog().then((c) => { setCat(c); setDesign(c.default_design); }).catch((e) => setError(String(e))); }, []);
  useEffect(() => {
    if (loadExperiment == null) return;
    api.experiment(loadExperiment).then((e) => {
      if (e.kind !== "rotor_design") return;
      const { run_sim, ...d } = e.config;
      setDesign(d as Design);
      if (e.results?.design) { setRep(e.results); setFrame(e.results.sim ? 0 : null); }
    });
  }, [loadExperiment]);

  // analytic re-evaluation on every edit (not saved), debounced
  useEffect(() => {
    if (!design) return;
    window.clearTimeout(deb.current);
    deb.current = window.setTimeout(() => {
      api.evaluateRotor(design, false, false).then((r) => { setRep(r); setFrame(null); setPlaying(false); setError(null); setSens(null); })
        .catch((e) => setError(String(e)));
    }, 250);
  }, [design]);

  // playback clock (frames are the solver's 50 Hz samples)
  useEffect(() => {
    if (!playing || !rep?.sim) return;
    let last = performance.now(), raf = 0;
    const tick = (now: number) => {
      const dt = (now - last) / 1000; last = now;
      setFrame((f) => {
        const n = (f ?? 0) + dt * 50 * speed;
        if (n >= rep.sim!.t.length - 1) { setPlaying(false); return rep.sim!.t.length - 1; }
        return n;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, rep, speed]);

  const runMission = async () => {
    if (!design) return;
    setBusy(true);
    try {
      const r = await api.evaluateRotor(design, true, true);
      setRep(r); setFrame(0); setPlaying(true);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  const save = async () => { if (design) { const r = await api.evaluateRotor(design, false, true); setRep(r); } };
  const set = (k: keyof Design, v: any) => setDesign((d) => (d ? { ...d, [k]: v } : d));

  if (!design || !cat) return <div className="page">{error ? <div className="fail">{error}</div> : "loading catalog…"}</div>;
  const n = rep?.scenarios.nominal;
  const sim = rep?.sim;
  const fi = sim && frame !== null && Number.isFinite(frame) ? Math.max(0, Math.min(Math.floor(frame), sim.t.length - 1)) : null;

  return (
    <div className="split">
      {/* ------------------------------------------------ designer */}
      <div className="col">
        <h2>Vehicle Designer</h2>
        <div className="card">
          <div className="row"><label>Propulsion</label>
            <select value={design.propulsion} onChange={(e) => set("propulsion", e.target.value)}>
              <option value="ducted_rotor">Ducted fans (concealed)</option><option value="open_rotor">Open rotors</option>
            </select></div>
          <div className="row"><label>Layout</label>
            <select value={design.layout} onChange={(e) => set("layout", e.target.value)}>
              <option value="staggered">Staggered line</option><option value="grid">2-column grid</option><option value="inline">Inline</option>
            </select></div>
          <div className="row"><label>Motor</label>
            <select value={design.motor} onChange={(e) => set("motor", e.target.value)}>
              {cat.motors.map((m: any) => <option key={m.key} value={m.key}>{m.name} · {m.mass_g} g</option>)}
            </select></div>
          <div className="row"><label>Battery</label>
            <select value={design.battery} onChange={(e) => set("battery", e.target.value)}>
              {cat.batteries.map((b: any) => <option key={b.key} value={b.key}>{b.name} · {b.mass_g} g</option>)}
            </select></div>
          <div className="row"><label>Deck material</label>
            <select value={design.deck_material} onChange={(e) => set("deck_material", e.target.value)}>
              {cat.materials.map((m: any) => <option key={m.key} value={m.key}>{m.name}</option>)}
            </select></div>
        </div>
        <div className="card">
          {NUM_FIELDS.map(([k, label, lo, hi, step]) => (
            <div className="row" key={k}>
              <label style={{ width: 120 }}>{label}</label>
              <input type="range" min={lo} max={hi} step={step} value={design[k] as number}
                onChange={(e) => set(k, step === 1 ? parseInt(e.target.value) : parseFloat(e.target.value))} />
              <span className="num">{fmt(design[k] as number, step < 1 ? (step < 0.1 ? 2 : 1) : 0)}</span>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn primary" disabled={busy} onClick={runMission}>{busy ? "Simulating…" : "Run 6-DOF mission"}</button>
          <button className="btn" onClick={save}>Save experiment</button>
          <button className="btn" onClick={() => api.sensitivity(design).then(setSens)}>Sensitivity</button>
        </div>
        {rep?.experiment_id && <p className="note">saved as experiment #{rep.experiment_id}</p>}
        <p className="note">The 3D view renders the design and replays the backend's RK4 6-DOF solution. It is not a physics solver.</p>
      </div>

      {/* ------------------------------------------------ 3D chamber */}
      <div className="canvas-wrap">
        <Canvas shadows camera={{ position: [0.16, 0.12, 0.2], fov: 40, near: 0.002, far: 20 }}
          onCreated={({ gl }) => { gl.localClippingEnabled = true; gl.setClearColor("#05080e"); }}>
          <ambientLight intensity={0.35} />
          <directionalLight position={[0.5, 1, 0.4]} intensity={1.3} castShadow />
          <pointLight position={[-0.3, 0.2, -0.2]} intensity={0.6} color="#7c6cff" />
          <Grid args={[4, 4]} cellSize={0.01} sectionSize={0.1} cellColor="#13233a" sectionColor="#1f4d6e" fadeDistance={2.5} infiniteGrid />
          <axesHelper args={[0.05]} />
          {rep && <Scene rep={rep} frame={frame} xray={xray} clipX={clip ? clipX : null} showForces={forces} follow={follow} trail={trail} />}
          <OrbitControls makeDefault target={[0, 0.05, 0]} />
        </Canvas>
        <div className="overlay">
          {[["X-ray", xray, setXray], ["Cross-section", clip, setClip], ["Forces", forces, setForces], ["Follow", follow, setFollow], ["Trail", trail, setTrail]].map(([l, v, f]: any) => (
            <button key={l} className={`btn ${v ? "on" : ""}`} onClick={() => f(!v)}>{l}</button>
          ))}
          {clip && <input type="range" min={-0.06} max={0.06} step={0.001} value={clipX} onChange={(e) => setClipX(parseFloat(e.target.value))} />}
        </div>
        {sim && (
          <div className="timeline">
            <button className="btn" onClick={() => { if (frame !== null && frame >= sim.t.length - 1) setFrame(0); setPlaying(!playing); }}>{playing ? "❚❚" : "▶"}</button>
            <button className="btn" onClick={() => { setPlaying(false); setFrame((f) => Math.max(0, Math.floor(f ?? 0) - 1)); }}>‹</button>
            <button className="btn" onClick={() => { setPlaying(false); setFrame((f) => Math.min(sim.t.length - 1, Math.floor(f ?? 0) + 1)); }}>›</button>
            <input type="range" min={0} max={sim.t.length - 1} step={1} value={frame ?? 0} onChange={(e) => { setPlaying(false); setFrame(parseFloat(e.target.value)); }} />
            <select value={speed} onChange={(e) => setSpeed(parseFloat(e.target.value))}>
              {[0.1, 0.25, 0.5, 1, 2].map((s) => <option key={s} value={s}>{s}×</option>)}
            </select>
            <span className="mono">t={fmt(fi !== null ? sim.t[fi] : 0, 2)} s</span>
          </div>
        )}
        <div className="hud" style={{ bottom: sim ? 62 : 12 }}>
          <div><span style={{ color: "#3ddc97" }}>■</span> rotor thrust · <span style={{ color: "#ff5d6c" }}>■</span> weight @ CG · 0.25 m/N</div>
          <div className="muted">grid 1 cm · sections 10 cm</div>
        </div>
      </div>

      {/* ------------------------------------------------ dashboard */}
      <div className="col">
        <h2>Physics Dashboard</h2>
        {error && <div className="card fail">{error}</div>}
        {rep && n && (
          <>
            <div className="card">
              <div className="row"><span className={`badge b-${rep.verdict}`}>{rep.verdict}</span><span className="ev">{rep.evidence}</span></div>
              <div className="note">{rep.verdict_reason}</div>
            </div>
            <div className="card">
              <table>
                <thead><tr><th></th><th>pess.</th><th>nominal</th><th>optim.</th></tr></thead>
                <tbody>
                  {([
                    ["Mass (g)", (s: any) => s.mass_g, 1],
                    ["Weight (N)", (s: any) => s.weight_n, 3],
                    ["Hover power (W)", (s: any) => s.hover_electrical_power_w, 2],
                    ["Current (A)", (s: any) => s.hover_current_a, 2],
                    ["Endurance (min)", (s: any) => s.endurance_s / 60, 1],
                    ["Thrust/weight", (s: any) => s.thrust_to_weight, 2],
                    ["Roll accel (rad/s²)", (s: any) => s.authority_rad_s2.roll, 0],
                    ["Pitch accel (rad/s²)", (s: any) => s.authority_rad_s2.pitch, 0],
                    ["Yaw accel (rad/s²)", (s: any) => s.authority_rad_s2.yaw, 0],
                    ["Power loading (g/W)", (s: any) => s.power_loading_g_per_w, 2],
                  ] as const).map(([label, f, d]) => (
                    <tr key={label}><td className="muted">{label}</td>
                      {(["pessimistic", "nominal", "optimistic"] as const).map((k) => <td key={k} className="n">{fmt(f(rep.scenarios[k]), d)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card kv">
              <span className="k">Gravity force</span><span className="v">{fmt(n.weight_n, 3)} N</span>
              <span className="k">Hover thrust / rotor</span><span className="v">{n.hover_thrust_per_rotor_n.map((t) => (t * 1000).toFixed(0)).join(" / ")} mN</span>
              <span className="k">Max thrust / rotor</span><span className="v">{fmt(n.max_thrust_per_rotor_n * 1000, 0)} mN</span>
              <span className="k">Disk loading</span><span className="v">{fmt(n.disk_loading_n_m2, 0)} N/m²</span>
              <span className="k">Hover rpm · tip Mach</span><span className="v">{fmt(n.rpm_hover, 0)} · {fmt(n.tip_mach, 2)}</span>
              <span className="k">Ground effect (T ratio)</span><span className="v">{fmt(n.ground_effect_thrust_ratio, 3)}</span>
              <span className="k">Deck 1st bending mode</span><span className="v">{fmt(n.bending_freq_hz, 0)} Hz</span>
              <span className="k">Battery heat</span><span className="v">{fmt(n.battery_heat_w, 2)} W</span>
              <span className="k">Parts cost</span><span className="v">${fmt(rep.cost_usd, 0)}</span>
            </div>
            <h2>Constraints (nominal)</h2>
            <div className="card cons">
              {n.constraints.map((c) => (
                <div key={c.key} title={c.message}>
                  <span className={c.passed ? "ok" : c.hard ? "fail" : "muted"}>{c.passed ? "✓" : "✗"} {c.key}</span>
                  <span className="mono muted">{c.value !== null ? fmt(c.value, 2) : ""}{c.limit !== null ? ` / ${fmt(c.limit, 2)}` : ""}</span>
                </div>
              ))}
            </div>
            <h2>Mass budget</h2>
            <div className="card">
              {Object.entries(rep.mass_budget.by_group_g).sort((a, b) => b[1] - a[1]).map(([g, m]) => (
                <div key={g} style={{ margin: "4px 0" }}>
                  <div className="row"><span className="muted">{g}</span><span className="num">{m.toFixed(2)} g</span></div>
                  <div className="bar"><div style={{ width: `${(100 * m) / rep.mass_budget.total_g}%` }} /></div>
                </div>
              ))}
            </div>
            {sim && (
              <>
                <h2>6-DOF mission <span className="ev">simplified_numerical (analytic forces)</span></h2>
                <div className="card kv">
                  {Object.entries(sim.metrics).flatMap(([k, v]) => [
                    <span className="k" key={k}>{k}</span>,
                    <span className="v" key={k + "v"}>{typeof v === "number" ? fmt(v, 3) : String(v)}</span>,
                  ])}
                </div>
                <div className="card">
                  <LineChart xs={sim.t} cursor={fi !== null ? sim.t[fi] : undefined} yLabel="position (m)" xLabel="t (s)"
                    series={[{ name: "x", color: "#38d6ff", ys: sim.pos.map((p) => p[0]) }, { name: "y", color: "#7c6cff", ys: sim.pos.map((p) => p[1]) }, { name: "z", color: "#3ddc97", ys: sim.pos.map((p) => p[2]) }]} />
                  <LineChart xs={sim.t} cursor={fi !== null ? sim.t[fi] : undefined} yLabel="rotor thrust (N)" xLabel="t (s)"
                    series={sim.thrusts[0].map((_, i) => ({ name: `r${i}`, color: ["#38d6ff", "#7c6cff", "#3ddc97", "#ffb547", "#ff5d6c", "#fff"][i % 6], ys: sim.thrusts.map((u) => u[i]) }))} />
                </div>
              </>
            )}
            {sens && (
              <>
                <h2>Sensitivity (endurance swing)</h2>
                <div className="card">
                  {sens.slice(1).map((r) => (
                    <div key={r.assumption} style={{ margin: "5px 0" }} title={r.description}>
                      <div className="row"><span className="muted">{r.assumption}</span><span className="num">{(r.endurance_low_s / 60).toFixed(1)}–{(r.endurance_high_s / 60).toFixed(1)} min</span></div>
                      <div className="bar"><div style={{ width: `${Math.min(100, (100 * r.swing_s) / (sens[1].swing_s || 1))}%` }} /></div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
