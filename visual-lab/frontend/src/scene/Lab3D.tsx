// Technical 3D lab. World frame: x forward, y left, z up (camera.up = +z), 1 unit = 1 metre (true scale).
// The board pose and every arrow are taken from the recorded simulation frame `idx`; nothing is animated
// independently of the physics state.
import { Edges, Grid, Html, Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { SimResult, V3 } from "../api";
import type { FieldOverlayData } from "../components/FieldOverlay";
import { FieldPlane } from "../components/FieldOverlay";

export interface SceneOptions {
  gravity: boolean;
  actuators: boolean;
  net: boolean;
  drag: boolean;
  contact: boolean;
  velocity: boolean;
  torque: boolean;
  trail: boolean;
  setpoint: boolean;
  labels: boolean;
  follow: boolean;
  forceScale: number; // m per N
  torqueScale: number; // m per N m
  velScale: number; // m per (m/s)
}

export const defaultOptions: SceneOptions = {
  gravity: true,
  actuators: true,
  net: true,
  drag: false,
  contact: true,
  velocity: true,
  torque: true,
  trail: true,
  setpoint: true,
  labels: true,
  follow: true,
  forceScale: 1.0,
  torqueScale: 2000,
  velScale: 0.4,
};

const UP = new THREE.Vector3(0, 1, 0);

function Arrow({ origin, vec, scale, color, label, show, radius = 0.0016 }: {
  origin: THREE.Vector3; vec: V3 | THREE.Vector3; scale: number; color: string; label?: string; show: boolean; radius?: number;
}) {
  const v = vec instanceof THREE.Vector3 ? vec.clone() : new THREE.Vector3(...vec);
  const len = v.length() * scale;
  if (!show || len < 1e-4) return null;
  const dir = v.normalize();
  const q = new THREE.Quaternion().setFromUnitVectors(UP, dir);
  const head = Math.min(0.018, len * 0.35);
  const shaft = Math.max(len - head, 1e-5);
  return (
    <group position={origin} quaternion={q}>
      <mesh position={[0, shaft / 2, 0]}>
        <cylinderGeometry args={[radius, radius, shaft, 10]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.35} />
      </mesh>
      <mesh position={[0, shaft + head / 2, 0]}>
        <coneGeometry args={[radius * 2.8, head, 14]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.35} />
      </mesh>
      {label && (
        <Html position={[0, len + 0.012, 0]} center style={{ pointerEvents: "none" }}>
          <div className="arrow-label" style={{ color }}>{label}</div>
        </Html>
      )}
    </group>
  );
}

function TorqueRing({ origin, tauW, scale, show }: { origin: THREE.Vector3; tauW: THREE.Vector3; scale: number; show: boolean }) {
  const mag = tauW.length();
  if (!show || mag * scale < 2e-3) return null;
  const dir = tauW.clone().normalize();
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), dir);
  const r = 0.03;
  return (
    <group position={origin}>
      <group quaternion={q}>
        <mesh>
          <torusGeometry args={[r, 0.0012, 8, 48, Math.PI * 1.6]} />
          <meshStandardMaterial color="#f5a524" emissive="#f5a524" emissiveIntensity={0.4} />
        </mesh>
        <mesh position={[r * Math.cos(Math.PI * 1.6), r * Math.sin(Math.PI * 1.6), 0]}
          rotation={[0, 0, Math.PI * 1.6]}>
          <coneGeometry args={[0.004, 0.01, 12]} />
          <meshStandardMaterial color="#f5a524" emissive="#f5a524" emissiveIntensity={0.4} />
        </mesh>
      </group>
      <Arrow origin={new THREE.Vector3()} vec={tauW} scale={scale} color="#f5a524" show radius={0.0012} />
    </group>
  );
}

function Board({ res, idx, opt }: { res: SimResult; idx: number; opt: SceneOptions }) {
  const tr = res.trajectory;
  const veh = res.vehicle;
  const p = tr.pos[idx];
  const qa = tr.quat[idx];
  const quat = useMemo(() => new THREE.Quaternion(qa[1], qa[2], qa[3], qa[0]), [qa]);
  const pos = useMemo(() => new THREE.Vector3(p[0], p[1], p[2]), [p]);
  const cg = new THREE.Vector3(...veh.cg_m);
  const L = veh.length_m, W = veh.width_m, H = veh.height_m;
  const fa = tr.f_act[idx];
  const hyp = veh.hypothetical;
  const tauW = new THREE.Vector3(...tr.tau_net[idx]).applyQuaternion(quat);
  const bottom = new THREE.Vector3(p[0], p[1], Math.max(0, p[2] - (cg.z + H / 2)));
  return (
    <>
      <group position={pos} quaternion={quat}>
        <group position={cg.clone().negate()}>
          {/* deck */}
          <mesh castShadow>
            <boxGeometry args={[L, W, H]} />
            <meshStandardMaterial color="#2b3440" metalness={0.2} roughness={0.6} transparent opacity={0.92} />
            <Edges color="#8fb3d9" />
          </mesh>
          {/* grip tape top + nose marker (+x) */}
          <mesh position={[0, 0, H / 2 + 0.0002]}>
            <boxGeometry args={[L * 0.98, W * 0.96, 0.0003]} />
            <meshStandardMaterial color="#11161c" roughness={0.95} />
          </mesh>
          <mesh position={[L / 2 - 0.006, 0, H / 2 + 0.0006]}>
            <coneGeometry args={[0.004, 0.008, 3]} />
            <meshStandardMaterial color="#35d0ba" />
          </mesh>
          {veh.actuators.map((a, i) => (
            <group key={i} position={a.pos_m}>
              <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
                <torusGeometry args={[a.radius_m * 0.5, 0.0006, 8, 32]} />
                <meshStandardMaterial color={hyp ? "#d36cff" : a.spin > 0 ? "#4fa3ff" : "#ff7a59"} />
              </mesh>
              <mesh position={[0, 0, H / 2 + 0.0005]}>
                <circleGeometry args={[a.radius_m * 0.48, 32]} />
                <meshBasicMaterial color={hyp ? "#d36cff" : "#6fb7ff"} transparent opacity={0.18 + 0.6 * Math.min(1, Math.abs(fa[i]) / 0.1)} />
              </mesh>
            </group>
          ))}
          {/* body axes */}
          <Line points={[[0, 0, 0], [L * 0.7, 0, 0]]} color="#ff5c5c" lineWidth={1} />
          <Line points={[[0, 0, 0], [0, W * 1.2, 0]]} color="#5cff8a" lineWidth={1} />
          <Line points={[[0, 0, 0], [0, 0, 0.03]]} color="#5ca8ff" lineWidth={1} />
        </group>
        {/* CG marker (body origin = CG) */}
        <mesh>
          <sphereGeometry args={[0.0028, 16, 16]} />
          <meshStandardMaterial color="#ffe066" emissive="#ffe066" emissiveIntensity={0.6} />
        </mesh>
        {opt.labels && (
          <Html position={[0, 0, -0.012]} center style={{ pointerEvents: "none" }}>
            <div className="arrow-label" style={{ color: "#ffe066" }}>CG</div>
          </Html>
        )}
      </group>
      {/* per-actuator forces at their world application points */}
      {veh.actuators.map((a, i) => {
        const o = new THREE.Vector3(...a.pos_m).sub(cg).applyQuaternion(quat).add(pos);
        const f = new THREE.Vector3(...a.axis).multiplyScalar(fa[i]).applyQuaternion(quat);
        return <Arrow key={i} origin={o} vec={f} scale={opt.forceScale} color={hyp ? "#d36cff" : "#4fa3ff"}
          show={opt.actuators} label={opt.labels && i === 0 ? (hyp ? "HYPOTHETICAL actuator force" : "actuator force") : undefined} radius={0.0011} />;
      })}
      <Arrow origin={pos} vec={tr.F_grav[idx]} scale={opt.forceScale} color="#ff5c7a" show={opt.gravity} label={opt.labels ? "gravity m·g" : undefined} />
      <Arrow origin={pos} vec={tr.F_net[idx]} scale={opt.forceScale * 5} color="#ffffff" show={opt.net} label={opt.labels ? "net force ×5" : undefined} radius={0.0012} />
      <Arrow origin={pos} vec={tr.F_drag[idx]} scale={opt.forceScale * 20} color="#9be15d" show={opt.drag} label={opt.labels ? "drag ×20" : undefined} radius={0.001} />
      <Arrow origin={bottom} vec={tr.F_contact[idx]} scale={opt.forceScale} color="#ffb000" show={opt.contact} label={opt.labels ? "ground contact" : undefined} />
      <Arrow origin={pos} vec={tr.F_ext[idx]} scale={opt.forceScale} color="#ff00aa" show label={opt.labels ? "disturbance" : undefined} />
      <Arrow origin={pos} vec={tr.vel[idx]} scale={opt.velScale} color="#35d0ba" show={opt.velocity} label={opt.labels ? "velocity" : undefined} radius={0.0011} />
      <TorqueRing origin={pos} tauW={tauW} scale={opt.torqueScale} show={opt.torque} />
    </>
  );
}

function Trail({ res, idx, show }: { res: SimResult; idx: number; show: boolean }) {
  const pts = useMemo(() => res.trajectory.pos.map((p) => new THREE.Vector3(p[0], p[1], p[2])), [res]);
  if (!show || idx < 2) return null;
  const step = Math.max(1, Math.floor(idx / 1500));
  const sub = pts.slice(0, idx + 1).filter((_, i) => i % step === 0);
  return <Line points={sub} color="#35d0ba" lineWidth={1.5} transparent opacity={0.65} />;
}

function Setpoint({ res, idx, show }: { res: SimResult; idx: number; show: boolean }) {
  if (!show) return null;
  const r = res.trajectory.ref_pos[idx];
  return (
    <mesh position={r}>
      <sphereGeometry args={[0.004, 12, 12]} />
      <meshBasicMaterial color="#ffffff" wireframe transparent opacity={0.6} />
    </mesh>
  );
}

function Follow({ res, idx, follow }: { res: SimResult; idx: number; follow: boolean }) {
  const controls = useThree((s) => s.controls) as unknown as OrbitControlsImpl | null;
  const camera = useThree((s) => s.camera);
  const last = useRef<THREE.Vector3 | null>(null);
  useFrame(() => {
    if (!controls || !follow) {
      last.current = null;
      return;
    }
    const p = res.trajectory.pos[idx];
    const target = new THREE.Vector3(p[0], p[1], p[2]);
    if (last.current) {
      const d = target.clone().sub(last.current);
      camera.position.add(d);
    }
    controls.target.copy(target);
    controls.update();
    last.current = target;
  });
  return null;
}

function WorldAxes() {
  const L = 0.25;
  return (
    <group>
      <Line points={[[0, 0, 0.0005], [L, 0, 0.0005]]} color="#ff5c5c" lineWidth={2} />
      <Line points={[[0, 0, 0.0005], [0, L, 0.0005]]} color="#5cff8a" lineWidth={2} />
      <Line points={[[0, 0, 0], [0, 0, L]]} color="#5ca8ff" lineWidth={2} />
      <Html position={[L + 0.02, 0, 0]} center><div className="axis-label" style={{ color: "#ff5c5c" }}>X fwd</div></Html>
      <Html position={[0, L + 0.02, 0]} center><div className="axis-label" style={{ color: "#5cff8a" }}>Y left</div></Html>
      <Html position={[0, 0, L + 0.02]} center><div className="axis-label" style={{ color: "#5ca8ff" }}>Z up</div></Html>
    </group>
  );
}

function AltitudeRuler({ res, idx }: { res: SimResult; idx: number }) {
  const p = res.trajectory.pos[idx];
  const ticks = [];
  for (let z = 0; z <= 0.4001; z += 0.05) ticks.push(z);
  return (
    <group position={[p[0], p[1] - 0.12, 0]}>
      <Line points={[[0, 0, 0], [0, 0, 0.4]]} color="#5d6b7a" lineWidth={1} />
      {ticks.map((z) => (
        <group key={z}>
          <Line points={[[0, 0, z], [0, 0.01, z]]} color="#5d6b7a" lineWidth={1} />
          <Html position={[0, 0.022, z]} center style={{ pointerEvents: "none" }}>
            <div className="axis-label" style={{ color: "#7f8c99" }}>{(z * 100).toFixed(0)} cm</div>
          </Html>
        </group>
      ))}
    </group>
  );
}

export function Lab3D({ res, idx, opt, field }: { res: SimResult; idx: number; opt: SceneOptions; field?: FieldOverlayData | null }) {
  return (
    <Canvas shadows camera={{ position: [-0.45, -0.55, 0.42], fov: 42, near: 0.002, far: 60, up: [0, 0, 1] }}
      gl={{ antialias: true }} style={{ background: "#0b0f14" }}>
      <ambientLight intensity={0.55} />
      <directionalLight position={[1.5, -1, 3]} intensity={1.2} castShadow />
      <Grid args={[8, 8]} position={[1, 0, 0]} rotation={[Math.PI / 2, 0, 0]} cellSize={0.01} cellThickness={0.5}
        sectionSize={0.1} sectionThickness={1} cellColor="#1d2733" sectionColor="#34506b" fadeDistance={6} fadeStrength={1.5}
        infiniteGrid={false} />
      <mesh position={[1, 0, -0.0005]} receiveShadow>
        <planeGeometry args={[8, 8]} />
        <meshStandardMaterial color="#0e141b" />
      </mesh>
      <WorldAxes />
      <AltitudeRuler res={res} idx={idx} />
      <Trail res={res} idx={idx} show={opt.trail} />
      <Setpoint res={res} idx={idx} show={opt.setpoint} />
      <Board res={res} idx={idx} opt={opt} />
      {field && <FieldPlane field={field} res={res} idx={idx} />}
      <OrbitControls makeDefault enableDamping dampingFactor={0.15} />
      <Follow res={res} idx={idx} follow={opt.follow} />
    </Canvas>
  );
}
