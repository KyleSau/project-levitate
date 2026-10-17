// Renders a real solver field (regular grid, from a solver run or an imported v1 document) as a
// colour-mapped plane. Values that are null (outside the fluid domain / inside the body) are transparent.
import { Html } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";
import type { SimResult } from "../api";

export interface FieldOverlayData {
  title: string;
  source: string;
  quantity: string;
  unit: string;
  u: number[]; // first in-plane coordinate (m)
  v: number[]; // second in-plane coordinate (m)
  values: (number | null)[][]; // values[iv][iu]
  plane: "yz" | "xz" | "xy";
  attach: "board" | "world";
  vmin?: number;
  vmax?: number;
}

// sequential: one hue (blue), dark -> light on the dark lab surface; diverging: orange <- grey -> blue
const SEQ: [number, number, number][] = [[13, 34, 64], [24, 79, 149], [57, 135, 229], [140, 190, 245], [222, 238, 255]];
const DIV: [number, number, number][] = [[217, 89, 38], [180, 130, 105], [128, 128, 128], [100, 140, 200], [57, 135, 229]];

export function colormap(t: number, diverging = false): [number, number, number] {
  const stops = diverging ? DIV : SEQ;
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const f = x - i;
  return [0, 1, 2].map((k) => stops[i][k] + f * (stops[i + 1][k] - stops[i][k])) as [number, number, number];
}

export function fieldRange(f: FieldOverlayData): [number, number] {
  let lo = Infinity, hi = -Infinity;
  for (const row of f.values) for (const v of row) if (v !== null && Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  if (isDiverging(f)) { const m = Math.max(Math.abs(lo), Math.abs(hi)); return [-m, m]; }
  return [f.vmin ?? lo, f.vmax ?? hi];
}

/** signed quantities (both signs present) use the diverging map centred on zero */
export function isDiverging(f: FieldOverlayData): boolean {
  let neg = false, pos = false;
  for (const row of f.values) for (const v of row) if (v !== null) { if (v < 0) neg = true; if (v > 0) pos = true; }
  return neg && pos;
}

export function FieldPlane({ field, res, idx }: { field: FieldOverlayData; res: SimResult; idx: number }) {
  const tex = useMemo(() => {
    const nu = field.u.length, nv = field.v.length;
    const [lo, hi] = fieldRange(field);
    const div = isDiverging(field);
    const data = new Uint8Array(nu * nv * 4);
    for (let j = 0; j < nv; j++) for (let i = 0; i < nu; i++) {
      const val = field.values[j][i];
      const o = 4 * (j * nu + i);
      if (val === null || !Number.isFinite(val)) { data[o + 3] = 0; continue; }
      const [r, g, b] = colormap((val - lo) / (hi - lo || 1), div);
      data[o] = r; data[o + 1] = g; data[o + 2] = b; data[o + 3] = 200;
    }
    const t = new THREE.DataTexture(data, nu, nv, THREE.RGBAFormat);
    t.magFilter = THREE.LinearFilter;
    t.needsUpdate = true;
    return t;
  }, [field]);
  const u0 = field.u[0], u1 = field.u[field.u.length - 1], v0 = field.v[0], v1 = field.v[field.v.length - 1];
  const w = u1 - u0, h = v1 - v0;
  const p = res.trajectory.pos[idx];
  const q = res.trajectory.quat[idx];
  const cg = res.vehicle.cg_m;
  // plane geometry lies in local XY; rotate into the requested plane of the body/world frame
  // map plane-local X -> first coordinate axis, local Y -> second coordinate axis
  const basis: Record<string, [THREE.Vector3, THREE.Vector3, THREE.Vector3]> = {
    yz: [new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(1, 0, 0)],
    xz: [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, -1, 0)],
    xy: [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1)],
  };
  const rotq = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(...basis[field.plane]));
  const centre: [number, number, number] = field.plane === "yz" ? [0, (u0 + u1) / 2, (v0 + v1) / 2]
    : field.plane === "xz" ? [(u0 + u1) / 2, 0, (v0 + v1) / 2] : [(u0 + u1) / 2, (v0 + v1) / 2, 0];
  const inner = (
    <group position={[-cg[0], -cg[1], -cg[2]]}>
      <mesh position={centre} quaternion={rotq}>
        <planeGeometry args={[w, h]} />
        <meshBasicMaterial map={tex} transparent side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      <Html position={[centre[0], centre[1], v1 + 0.004]} center style={{ pointerEvents: "none" }}>
        <div className="arrow-label" style={{ color: "#c9f" }}>{field.title} — {field.quantity} [{field.unit}] ({field.source})</div>
      </Html>
    </group>
  );
  if (field.attach === "world") return inner;
  return (
    <group position={[p[0], p[1], p[2]]} quaternion={new THREE.Quaternion(q[1], q[2], q[3], q[0])}>
      {inner}
    </group>
  );
}
