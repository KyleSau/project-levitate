// 3D view for the propulsion lab: imperative three.js objects updated every frame from the physical state.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { G0, PP } from "./physics";
import type { Mode } from "./physics";

const T3 = (x: number, y: number, z: number) => new THREE.Vector3(x, z, -y);
const Q3 = (q: number[]) => new THREE.Quaternion(q[1], q[3], -q[2], q[0]);
export const HOVER_ORIGIN = [0, 14];

function makeArrow(color: number) {
  const a = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), 1, color, 0.12, 0.07);
  (a.line.material as THREE.Material).depthTest = false; (a.cone.material as THREE.Material).depthTest = false; a.renderOrder = 10;
  return a;
}
function setArrow(a: THREE.ArrowHelper, o: THREE.Vector3, d: THREE.Vector3, len: number, show: boolean) {
  if (!show || !(len > 0.02)) { a.visible = false; return; }
  a.visible = true; a.position.copy(o); a.setDirection(d.clone().normalize()); a.setLength(len, Math.min(0.18, 0.3 * len), Math.min(0.1, 0.18 * len));
}

export function buildWorld(scene: THREE.Scene) {
  const g = new THREE.Group();
  const road = new THREE.Mesh(new THREE.PlaneGeometry(500, 8), new THREE.MeshStandardMaterial({ color: 0x3a3d42, roughness: 1 }));
  road.rotation.x = -Math.PI / 2; road.position.set(210, 0, 0); road.receiveShadow = true; g.add(road);
  const grass = new THREE.Mesh(new THREE.PlaneGeometry(600, 300), new THREE.MeshStandardMaterial({ color: 0x51683a, roughness: 1 }));
  grass.rotation.x = -Math.PI / 2; grass.position.set(210, -0.01, 0); grass.receiveShadow = true; g.add(grass);
  const pad = new THREE.Mesh(new THREE.PlaneGeometry(16, 16), new THREE.MeshStandardMaterial({ color: 0x9a9890, roughness: 0.9 }));
  pad.rotation.x = -Math.PI / 2; pad.position.copy(T3(0, 14, 0.002)); pad.receiveShadow = true; g.add(pad);
  const white = new THREE.MeshBasicMaterial({ color: 0xeeeeee });
  for (let x = -40; x < 460; x += 9) { const m = new THREE.Mesh(new THREE.PlaneGeometry(3, 0.12), white); m.rotation.x = -Math.PI / 2; m.position.set(x + 1.5, 0.003, 0); g.add(m); }
  const post = new THREE.MeshStandardMaterial({ color: 0xff6a1a });
  for (let x = 10; x <= 450; x += 10) { const c = new THREE.Mesh(new THREE.ConeGeometry(0.15, 0.46, 12), post); c.position.copy(T3(x, x % 20 ? 3.6 : -3.6, 0.23)); c.castShadow = true; g.add(c); }
  scene.add(g);
  return g;
}

export default function PropScene({ mode, simRef, frameRef, showVectors }: {
  mode: Mode; simRef: React.MutableRefObject<any>; frameRef: React.MutableRefObject<any>; showVectors: boolean;
}) {
  const { scene, camera } = useThree();
  const controls = useRef<any>(null);
  const objs = useMemo(() => {
    const root = new THREE.Group();
    const arrows: Record<string, THREE.ArrowHelper> = {};
    for (const [k, c] of [["thrust", 0xffb648], ["vel", 0x3fd2ff], ["drag", 0xff5a5f], ["Nf", 0x48e08f], ["Nr", 0x48e08f], ["grav", 0xa993ff],
      ["t0", 0xffb648], ["t1", 0xffb648], ["t2", 0xffb648], ["t3", 0xffb648]] as [string, number][]) { arrows[k] = makeArrow(c); root.add(arrows[k]); }
    const cg = new THREE.Mesh(new THREE.SphereGeometry(0.045, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false })); cg.renderOrder = 11; root.add(cg);
    const body = new THREE.Group(); root.add(body);
    const rider = new THREE.Group();
    const rmat = new THREE.MeshStandardMaterial({ color: 0x2f6fb3, roughness: 0.8 });
    const legs = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.1, 0.9, 12), new THREE.MeshStandardMaterial({ color: 0x2a2d33 })); legs.position.y = 0.45; rider.add(legs);
    const torso = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.14, 0.6, 12), rmat); torso.position.y = 1.2; rider.add(torso);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.11, 14, 10), new THREE.MeshStandardMaterial({ color: 0xc99372 })); head.position.y = 1.62; rider.add(head);
    rider.traverse((o: any) => { if (o.isMesh) o.castShadow = true; });
    root.add(rider);
    const NP = 500, pos = new Float32Array(NP * 3), vel = new Float32Array(NP * 3), life = new Float32Array(NP);
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({ size: 0.09, color: 0xeef4ff, transparent: true, opacity: 0.6, depthWrite: false }));
    pts.frustumCulled = false; root.add(pts);
    return { root, arrows, cg, body, rider, parts: { pos, vel, life, geo, pts, next: 0, NP }, wheels: [] as THREE.Object3D[], wheelAng: 0 };
  }, []);

  useEffect(() => { const w = buildWorld(scene); scene.add(objs.root); return () => { scene.remove(w); scene.remove(objs.root); }; }, [scene, objs]);

  // (re)build the vehicle model whenever the simulator instance changes
  const builtFor = useRef<any>(null);
  function build(sim: any) {
    const b = objs.body; while (b.children.length) b.remove(b.children[0]);
    objs.wheels = [];
    const metal = new THREE.MeshStandardMaterial({ color: 0x9aa4ad, metalness: 0.8, roughness: 0.35 });
    const tankMat = new THREE.MeshStandardMaterial({ color: 0x9fb4c8, metalness: 0.6, roughness: 0.35 });
    if (mode === "skate") {
      const c = sim.cfg, L = c.wheelbase_m, h = c.deck_height_m;
      const deck = new THREE.Mesh(new THREE.BoxGeometry(L + 0.24, 0.014, 0.23), new THREE.MeshStandardMaterial({ color: 0x1d2a3a })); deck.position.copy(T3(L / 2, 0, h)); deck.castShadow = true; b.add(deck);
      for (const x of [0, L]) for (const y of [-0.1, 0.1]) {
        const w = new THREE.Group(); w.position.copy(T3(x, y, 0.045));
        const cyl = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.045, 18), new THREE.MeshStandardMaterial({ color: 0xf2e6c8 })); cyl.rotation.x = Math.PI / 2; w.add(cyl);
        const mark = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.012, 0.047), metal); w.add(mark); b.add(w); objs.wheels.push(w);
      }
      if (c.coldgas) {
        const [D, Lt] = PP.tankGeometry(c.tank.volume_l / 1000);
        for (let k = 0; k < c.tank.n_tanks; k++) { const t = new THREE.Mesh(new THREE.CylinderGeometry(D / 2, D / 2, Lt, 18), tankMat); t.rotation.z = Math.PI / 2; t.position.copy(T3(c.tank_x_m, (k - (c.tank.n_tanks - 1) / 2) * (D + 0.01), Math.max(c.tank_h_m, h + D / 2))); t.castShadow = true; b.add(t); }
        const nz = new THREE.Mesh(new THREE.ConeGeometry(0.025, 0.08, 14, 1, true), metal); nz.rotation.z = -Math.PI / 2; nz.position.copy(T3(c.tank_x_m - 0.12, 0, c.thrust_height_m)); b.add(nz);
      }
    } else {
      const c = sim.cfg;
      const deck = new THREE.Mesh(new THREE.BoxGeometry(c.deck_length_m, 0.05, c.deck_width_m), new THREE.MeshStandardMaterial({ color: 0x2b4f7a, metalness: 0.5 })); deck.castShadow = true; b.add(deck);
      sim.r_thr.forEach((r: number[]) => { const p = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.06, 0.14, 14), metal); p.position.copy(T3(r[0], r[1], r[2])); p.castShadow = true; b.add(p); });
      const tk = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.15, 0.4), tankMat); tk.position.copy(T3(c.tank_x_m, 0, c.tank_z_m)); tk.castShadow = true; b.add(tk);
      const fx = 0.4 * c.deck_length_m, fy = 0.4 * c.deck_width_m;
      for (const [x, y] of [[fx, fy], [-fx, fy], [-fx, -fy], [fx, -fy]]) { const l = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.02, c.leg_height_m, 8), metal); l.position.copy(T3(x, y, -c.leg_height_m / 2)); b.add(l); }
    }
    builtFor.current = sim;
  }

  useFrame((_, real) => {
    const sim = simRef.current, f = frameRef.current;
    if (!sim || !f || sim.__mode !== mode) return;
    if (builtFor.current !== sim) build(sim);
    const A = objs.arrows;
    let target = new THREE.Vector3();
    const P = objs.parts;
    const emit = (o: THREE.Vector3, d: THREE.Vector3, n: number, sp: number) => {
      for (let k = 0; k < n; k++) { const i = P.next; P.next = (P.next + 1) % P.NP; P.pos.set([o.x, o.y, o.z], 3 * i);
        P.vel.set([d.x * sp * (0.6 + 0.6 * Math.random()) + (Math.random() - 0.5), d.y * sp * (0.6 + 0.6 * Math.random()) + (Math.random() - 0.5), d.z * sp * (0.6 + 0.6 * Math.random()) + (Math.random() - 0.5)], 3 * i); P.life[i] = 0.8; }
    };
    if (mode === "skate") {
      const c = sim.cfg, L = c.wheelbase_m, piv = f.phi >= 0 ? 0 : L;
      const R = (x: number, z: number) => T3(x - piv, 0, z).applyAxisAngle(new THREE.Vector3(0, 0, 1), f.phi).add(T3(f.x + piv, 0, 0));
      objs.body.position.copy(T3(f.x + piv, 0, 0)); objs.body.rotation.set(0, 0, f.phi);
      objs.body.children.forEach((ch) => { if (!(ch as any).__off) { (ch as any).__off = ch.position.clone(); } ch.position.copy((ch as any).__off).add(T3(-piv, 0, 0)); });
      objs.wheelAng -= f.v * real / 0.045; objs.wheels.forEach((w) => { w.rotation.z = objs.wheelAng; });
      if (f.rider) { objs.rider.position.copy(R(L / 2, c.deck_height_m)); objs.rider.rotation.set(0, 0, f.phi - f.theta); }
      else { objs.rider.position.copy(T3((f.rx ?? f.x) + 0.6, 0.3, 0.15)); objs.rider.rotation.set(0, 0, Math.PI / 2); }
      const cg = R(f.cgx, f.cgz); objs.cg.position.copy(cg); objs.cg.visible = showVectors;
      const dir = new THREE.Vector3(Math.cos(f.phi), Math.sin(f.phi), 0);
      setArrow(A.thrust, R(c.tank_x_m - 0.16, c.thrust_height_m), dir, f.thrust / 200, showVectors);
      setArrow(A.vel, cg.clone().add(new THREE.Vector3(0, 0.35, 0)), new THREE.Vector3(1, 0, 0), f.v * 0.12, showVectors);
      setArrow(A.drag, R(L / 2 + 0.1, c.deck_height_m + 1.0), new THREE.Vector3(-1, 0, 0), f.drag / 200, showVectors);
      setArrow(A.Nf, R(L, 0), new THREE.Vector3(0, 1, 0), Math.max(f.Nf, 0) / 600, showVectors);
      setArrow(A.Nr, R(0, 0), new THREE.Vector3(0, 1, 0), Math.max(f.Nr, 0) / 600, showVectors);
      setArrow(A.grav, cg, new THREE.Vector3(0, -1, 0), f.mass * G0 / 600, showVectors);
      for (const k of ["t0", "t1", "t2", "t3"]) A[k].visible = false;
      if (f.thrust > 2 && real > 0) emit(R(c.tank_x_m - 0.17, c.thrust_height_m), dir.clone().negate(), Math.min(20, Math.round(f.thrust / 10)), 8);
      target = cg;
    } else {
      const pos = T3(f.pos[0] + HOVER_ORIGIN[0], f.pos[1] + HOVER_ORIGIN[1], f.pos[2]), q = Q3(f.q);
      objs.body.position.copy(pos); objs.body.quaternion.copy(q); objs.body.updateMatrixWorld(true);
      objs.body.children.forEach((ch) => { if ((ch as any).__off) ch.position.copy((ch as any).__off); });
      objs.rider.position.copy(pos).add(new THREE.Vector3(0, 0.025, 0).applyQuaternion(q)); objs.rider.quaternion.copy(q);
      const cg = T3(f.cgW[0] + HOVER_ORIGIN[0], f.cgW[1] + HOVER_ORIGIN[1], f.cgW[2]); objs.cg.position.copy(cg); objs.cg.visible = showVectors;
      sim.r_thr.forEach((r: number[], i: number) => {
        const o = T3(r[0], r[1], r[2]).applyMatrix4(objs.body.matrixWorld), d = T3(sim.d_thr[i][0], sim.d_thr[i][1], sim.d_thr[i][2]).applyQuaternion(q).normalize();
        setArrow(A["t" + i], o.clone().add(d.clone().multiplyScalar(0.1)), d, f.F[i] / 1000, showVectors);
        if (f.F[i] > 5 && real > 0) emit(o, d.clone().negate(), Math.min(8, Math.round(f.F[i] / 80)), 12);
      });
      setArrow(A.vel, cg.clone().add(new THREE.Vector3(0, 0.4, 0)), T3(f.vel[0], f.vel[1], f.vel[2]), Math.hypot(f.vel[0], f.vel[1], f.vel[2]) * 0.3, showVectors);
      setArrow(A.grav, cg, new THREE.Vector3(0, -1, 0), f.m * G0 / 1500, showVectors);
      for (const k of ["thrust", "drag", "Nf", "Nr"]) A[k].visible = false;
      target = cg;
    }
    for (let i = 0; i < P.NP; i++) {
      if (P.life[i] <= 0) { P.pos[3 * i + 1] = -50; continue; }
      P.life[i] -= real; const k = Math.exp(-3.5 * real);
      for (let j = 0; j < 3; j++) { P.vel[3 * i + j] *= k; P.pos[3 * i + j] += P.vel[3 * i + j] * real; }
      if (P.pos[3 * i + 1] < 0.01) P.pos[3 * i + 1] = 0.01;
    }
    P.geo.attributes.position.needsUpdate = true;
    if (controls.current) {
      const delta = target.clone().sub(controls.current.target);
      controls.current.target.add(delta); camera.position.add(delta); controls.current.update();
    }
  });

  return (
    <>
      <ambientLight intensity={0.5} />
      <directionalLight position={[8, 14, 6]} intensity={1.6} castShadow />
      <color attach="background" args={["#a9c3d6"]} />
      <OrbitControls ref={controls} makeDefault enableDamping={false} />
    </>
  );
}
