// Visual model of the board. Physics frame (x fwd, y left, z up) -> three.js (x, z, -y).
import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { Geometry } from "../api";

export const toThree = (p: number[]) => new THREE.Vector3(p[0], p[2], -p[1]);
export const quatToThree = (q: number[]) => new THREE.Quaternion(q[1], q[3], -q[2], q[0]); // (x,y,z,w)

export function Arrow({ origin, dir, length, color, radius = 0.0012 }: {
  origin: THREE.Vector3; dir: THREE.Vector3; length: number; color: string; radius?: number;
}) {
  const q = useMemo(() => new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize()), [dir]);
  if (!(length > 1e-5)) return null;
  const head = Math.min(length * 0.3, 0.012);
  return (
    <group position={origin} quaternion={q}>
      <mesh position={[0, (length - head) / 2, 0]}>
        <cylinderGeometry args={[radius, radius, length - head, 8]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <mesh position={[0, length - head / 2, 0]}>
        <coneGeometry args={[radius * 2.8, head, 12]} />
        <meshBasicMaterial color={color} />
      </mesh>
    </group>
  );
}

function deckShape(g: Geometry) {
  const L = g.length_m, W = g.width_m, r = Math.min(W * 0.35, 0.012);
  const s = new THREE.Shape();
  s.moveTo(-L / 2 + r, -W / 2);
  s.lineTo(L / 2 - r, -W / 2);
  s.quadraticCurveTo(L / 2, -W / 2, L / 2, -W / 2 + r);
  s.lineTo(L / 2, W / 2 - r);
  s.quadraticCurveTo(L / 2, W / 2, L / 2 - r, W / 2);
  s.lineTo(-L / 2 + r, W / 2);
  s.quadraticCurveTo(-L / 2, W / 2, -L / 2, W / 2 - r);
  s.lineTo(-L / 2, -W / 2 + r);
  s.quadraticCurveTo(-L / 2, -W / 2, -L / 2 + r, -W / 2);
  for (const ro of g.rotors) {
    const h = new THREE.Path();
    h.absarc(ro.pos[0], ro.pos[1], ro.r_in, 0, Math.PI * 2, true);
    s.holes.push(h);
  }
  return s;
}

function Rotor({ r, spin, speed }: { r: number; spin: number; speed: number }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, dt) => { if (ref.current) ref.current.rotation.y += spin * speed * dt; });
  return (
    <group ref={ref}>
      {[0, 1, 2].map((i) => (
        <mesh key={i} rotation={[0.25, (i * 2 * Math.PI) / 3, 0]} position={[0, 0, 0]}>
          <boxGeometry args={[r * 1.9, 0.0004, r * 0.28]} />
          <meshStandardMaterial color="#9fd8ff" metalness={0.2} roughness={0.4} transparent opacity={0.85} />
        </mesh>
      ))}
    </group>
  );
}

export default function Board3D({ g, thrusts, xray, clipX, showForces, mass_kg, spinning }: {
  g: Geometry; thrusts: number[]; xray: boolean; clipX: number | null; showForces: boolean; mass_kg: number; spinning: boolean;
}) {
  const shape = useMemo(() => deckShape(g), [g]);
  const clip = useMemo(() => (clipX === null ? [] : [new THREE.Plane(new THREE.Vector3(-1, 0, 0), clipX)]), [clipX]);
  const skinGeo = useMemo(() => new THREE.ExtrudeGeometry(shape, { depth: g.skin_m, bevelEnabled: false, curveSegments: 32 }), [shape, g.skin_m]);
  const bottomGeo = useMemo(() => new THREE.ExtrudeGeometry(shape, { depth: g.skin_m * 0.6, bevelEnabled: false, curveSegments: 32 }), [shape, g.skin_m]);
  const H = g.height_m;
  const deckMat = { color: "#1c2a40", metalness: 0.6, roughness: 0.35, transparent: xray, opacity: xray ? 0.25 : 1, clippingPlanes: clip, side: THREE.DoubleSide } as const;
  const F_SCALE = 0.25; // metres of arrow per newton
  const cg = toThree(g.cg);

  return (
    <group>
      {/* top skin (extruded in +z of shape space -> rotate so shape xy = physics xy) */}
      <mesh geometry={skinGeo} rotation={[-Math.PI / 2, 0, 0]} position={[0, H / 2 - g.skin_m, 0]} castShadow>
        <meshStandardMaterial {...deckMat} />
      </mesh>
      <mesh geometry={bottomGeo} rotation={[-Math.PI / 2, 0, 0]} position={[0, -H / 2, 0]}>
        <meshStandardMaterial {...deckMat} color="#132033" />
      </mesh>
      {/* perimeter glow strip */}
      <mesh position={[0, 0, 0]}>
        <boxGeometry args={[g.length_m * 0.985, H * 0.55, g.width_m * 0.985]} />
        <meshStandardMaterial color="#38d6ff" emissive="#1aa6d6" emissiveIntensity={0.6} transparent opacity={xray ? 0.05 : 0.18} clippingPlanes={clip} />
      </mesh>
      {g.rotors.map((ro, i) => {
        const p = toThree(ro.pos);
        const t = thrusts[i] ?? 0;
        return (
          <group key={i} position={p}>
            {g.ducted && (
              <mesh>
                <cylinderGeometry args={[ro.r_in + g.wall_m / 2, ro.r_in + g.wall_m / 2, H, 48, 1, true]} />
                <meshStandardMaterial color="#2a3b57" metalness={0.5} roughness={0.4} side={THREE.DoubleSide} transparent={xray} opacity={xray ? 0.35 : 1} clippingPlanes={clip} />
              </mesh>
            )}
            <mesh position={[0, -H * 0.1, 0]}>
              <cylinderGeometry args={[0.0035, 0.0035, H * 0.6, 20]} />
              <meshStandardMaterial color="#8a93a6" metalness={0.8} roughness={0.3} clippingPlanes={clip} />
            </mesh>
            <group position={[0, H * 0.25, 0]}>
              <Rotor r={ro.r_rotor} spin={ro.spin} speed={spinning ? 40 : 0} />
            </group>
            {showForces && (
              <Arrow origin={new THREE.Vector3(0, H / 2, 0)} dir={new THREE.Vector3(0, 1, 0)} length={t * F_SCALE} color="#3ddc97" />
            )}
          </group>
        );
      })}
      <mesh position={toThree(g.battery.pos)}>
        <boxGeometry args={[g.battery.size[0], g.battery.size[2], g.battery.size[1]]} />
        <meshStandardMaterial color="#c7832e" roughness={0.6} clippingPlanes={clip} />
      </mesh>
      <mesh position={toThree(g.avionics.pos)}>
        <boxGeometry args={[g.avionics.size[0], g.avionics.size[2], g.avionics.size[1]]} />
        <meshStandardMaterial color="#2e7d4f" roughness={0.5} clippingPlanes={clip} />
      </mesh>
      {/* centre of gravity marker + weight vector */}
      <mesh position={cg}>
        <sphereGeometry args={[0.0022, 16, 16]} />
        <meshBasicMaterial color="#ff5d6c" depthTest={false} />
      </mesh>
      {showForces && (
        <Arrow origin={cg} dir={new THREE.Vector3(0, -1, 0)} length={mass_kg * 9.80665 * F_SCALE} color="#ff5d6c" />
      )}
    </group>
  );
}
