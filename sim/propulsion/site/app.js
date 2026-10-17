/* Propulsion Lab - 3D view, controls, dashboard. Physics lives in propulsion.js (validated against Python). */
(() => {
"use strict";
const PP = window.PropulsionPhysics, ROM = window.PROP_ROM;
const $ = (id) => document.getElementById(id);
const G0 = PP.G0;
const fmt = (v, d = 1) => (v === null || v === undefined || !Number.isFinite(v)) ? "–" : v.toFixed(d);
const T3 = (x, y, z) => new THREE.Vector3(x, z, -y);            // physics (x fwd, y left, z up) -> three (y up)

// =============================================================================== renderer & scene
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputEncoding = THREE.sRGBEncoding; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
$("app").appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xa9c3d6); scene.fog = new THREE.Fog(0xa9c3d6, 60, 220);
const camera = new THREE.PerspectiveCamera(55, 1, 0.05, 600);
scene.add(new THREE.HemisphereLight(0xdcecff, 0x4a4f3a, 0.7));
const sun = new THREE.DirectionalLight(0xfff3e0, 2.1);
sun.castShadow = true; sun.shadow.mapSize.set(1024, 1024);
Object.assign(sun.shadow.camera, { left: -8, right: 8, top: 8, bottom: -8, near: 0.5, far: 50 });
sun.shadow.bias = -0.0004; scene.add(sun); scene.add(sun.target);

const loader = new THREE.TextureLoader();
function mat(name, repeat, opts = {}) {
  const tex = (m) => { const t = loader.load(`tex/${name}_${m}.jpg`); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(repeat[0], repeat[1]); t.anisotropy = 4; return t; };
  const map = tex("diff"); map.encoding = THREE.sRGBEncoding;
  return new THREE.MeshStandardMaterial({ map, normalMap: tex("nor_gl"), roughnessMap: tex("rough"), ...opts });
}
const TILE = 2.5;
function ground(w, h, m, cx, cy, z = 0) {   // physics-frame centre (cx, cy)
  const g = new THREE.Mesh(new THREE.PlaneGeometry(w, h), m); g.rotation.x = -Math.PI / 2; g.position.copy(T3(cx, cy, z)); g.receiveShadow = true; scene.add(g); return g;
}
// track: 8 m wide asphalt road along +x from -40 to 460 m, concrete test pad at the origin (hover modes), grass beyond
const ROAD0 = -40, ROAD1 = 460, RL = ROAD1 - ROAD0;
ground(RL, 8, mat("asphalt_02", [RL / TILE, 8 / TILE], { roughness: 1 }), (ROAD0 + ROAD1) / 2, 0);
ground(RL + 80, 120, mat("sparse_grass", [(RL + 80) / 3, 40]), (ROAD0 + ROAD1) / 2, 64, -0.002);
ground(RL + 80, 120, mat("sparse_grass", [(RL + 80) / 3, 40]), (ROAD0 + ROAD1) / 2, -64, -0.002);
const padMat = mat("concrete_floor_02", [16 / TILE, 16 / TILE]);
ground(16, 16, padMat, 0, 14, 0.001);
const lineMat = new THREE.MeshStandardMaterial({ color: 0xeeeeee, roughness: 0.6 });
for (let x = ROAD0; x < ROAD1; x += 9) ground(3, 0.12, lineMat, x + 1.5, 0, 0.003);
for (const y of [-3.9, 3.9]) ground(RL, 0.12, lineMat, (ROAD0 + ROAD1) / 2, y, 0.003);
ground(0.3, 8, new THREE.MeshStandardMaterial({ color: 0xffffff }), 0, 0, 0.004);           // start line
// distance boards every 25 m (canvas text, true size 0.8 x 0.5 m)
function signTex(text, bg = "#f4f4f4", fg = "#1a1a1a") {
  const c = document.createElement("canvas"); c.width = 256; c.height = 160; const g = c.getContext("2d");
  g.fillStyle = bg; g.fillRect(0, 0, 256, 160); g.fillStyle = fg; g.font = "bold 84px Arial"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(text, 128, 84);
  const t = new THREE.CanvasTexture(c); t.encoding = THREE.sRGBEncoding; return t;
}
const postMat = new THREE.MeshStandardMaterial({ color: 0x6c7680, metalness: 0.5, roughness: 0.5 });
for (let x = 25; x <= 450; x += 25) {
  const s = new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.5), new THREE.MeshStandardMaterial({ map: signTex(`${x}`), side: THREE.DoubleSide }));
  s.position.copy(T3(x, 4.6, 1.3)); scene.add(s);
  const p = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 1.1, 8), postMat); p.position.copy(T3(x, 4.6, 0.55)); p.castShadow = true; scene.add(p);
}
const coneMat = new THREE.MeshStandardMaterial({ color: 0xff6a1a, roughness: 0.6 });
for (let x = 10; x < 450; x += 20) for (const y of [-3.5, 3.5]) { const c = new THREE.Mesh(new THREE.ConeGeometry(0.15, 0.46, 16), coneMat); c.position.copy(T3(x, y, 0.23)); c.castShadow = true; scene.add(c); }
for (let x = -40; x <= 460; x += 30) for (const y of [-6, 6]) {
  const p = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.08, 6, 10), postMat); p.position.copy(T3(x, y, 3)); p.castShadow = true; scene.add(p);
}
const treeMat = new THREE.MeshStandardMaterial({ color: 0x2f5a2c, roughness: 0.9 }), trunkMat = new THREE.MeshStandardMaterial({ color: 0x5a4130 });
for (let i = 0; i < 46; i++) {
  const x = -30 + i * 11 + ((i * 37) % 7), y = (i % 2 ? 1 : -1) * (12 + ((i * 53) % 17));
  const t = new THREE.Group();
  const tr = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.2, 2.2, 8), trunkMat); tr.position.y = 1.1; t.add(tr);
  const cr = new THREE.Mesh(new THREE.ConeGeometry(1.6, 4.5, 10), treeMat); cr.position.y = 4.2; t.add(cr);
  t.traverse((o) => { o.castShadow = true; }); t.position.copy(T3(x, y, 0)); scene.add(t);
}
// 1 m scale post with 10 cm bands next to the hover pad
const scalePost = new THREE.Group();
for (let i = 0; i < 20; i++) { const b = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.1, 0.06), new THREE.MeshStandardMaterial({ color: i % 2 ? 0xffffff : 0xd8262c })); b.position.y = 0.05 + i * 0.1; b.castShadow = true; scalePost.add(b); }
scalePost.position.copy(T3(-1.5, 11.5, 0)); scene.add(scalePost);

// =============================================================================== shared visual helpers
const arrows = {};
function arrow(key, color) {
  const a = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), 1, color, 0.12, 0.07);
  a.line.material.depthTest = false; a.cone.material.depthTest = false; a.renderOrder = 10; scene.add(a); arrows[key] = a; return a;
}
function setArrow(key, origin, dir, length, show = true) {
  const a = arrows[key]; if (!a) return;
  if (!show || !(length > 0.02)) { a.visible = false; return; }
  a.visible = true; a.position.copy(origin); a.setDirection(dir.clone().normalize()); a.setLength(length, Math.min(0.18, 0.3 * length), Math.min(0.1, 0.18 * length));
}
arrow("thrust", 0xffb648); arrow("vel", 0x3fd2ff); arrow("drag", 0xff5a5f); arrow("Nf", 0x48e08f); arrow("Nr", 0x48e08f); arrow("grav", 0xa993ff); arrow("drive", 0x3fd2ff);
arrow("t1", 0xffb648); arrow("t2", 0xffb648); arrow("t3", 0xffb648); arrow("t4", 0xffb648);
const cgMarker = new THREE.Group();
{ const s1 = new THREE.Mesh(new THREE.SphereGeometry(0.045, 16, 12, 0, Math.PI), new THREE.MeshBasicMaterial({ color: 0x111111, depthTest: false }));
  const s2 = new THREE.Mesh(new THREE.SphereGeometry(0.045, 16, 12, Math.PI, Math.PI), new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false }));
  s1.renderOrder = s2.renderOrder = 11; cgMarker.add(s1, s2); scene.add(cgMarker); }
let showVectors = true;

// exhaust particles (cold-gas: frost fog; rocket: hot glow)
const NP = 900, pPos = new Float32Array(NP * 3), pVel = new Float32Array(NP * 3), pLife = new Float32Array(NP), pCol = new Float32Array(NP * 3);
const pGeo = new THREE.BufferGeometry(); pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3)); pGeo.setAttribute("color", new THREE.BufferAttribute(pCol, 3));
const pts = new THREE.Points(pGeo, new THREE.PointsMaterial({ size: 0.09, vertexColors: true, transparent: true, opacity: 0.6, depthWrite: false }));
pts.frustumCulled = false; scene.add(pts);
let pNext = 0;
function emit(n, origin, dir, speed, spread, col, life) {   // three-space vectors
  for (let k = 0; k < n; k++) {
    const i = pNext; pNext = (pNext + 1) % NP;
    pPos[3 * i] = origin.x; pPos[3 * i + 1] = origin.y; pPos[3 * i + 2] = origin.z;
    const s = speed * (0.6 + 0.6 * Math.random());
    pVel[3 * i] = dir.x * s + (Math.random() - 0.5) * spread; pVel[3 * i + 1] = dir.y * s + (Math.random() - 0.5) * spread; pVel[3 * i + 2] = dir.z * s + (Math.random() - 0.5) * spread;
    pLife[i] = life * (0.7 + 0.6 * Math.random()); pCol[3 * i] = col[0]; pCol[3 * i + 1] = col[1]; pCol[3 * i + 2] = col[2];
  }
}
function stepParticles(dt) {
  for (let i = 0; i < NP; i++) {
    if (pLife[i] <= 0) { pPos[3 * i + 1] = -50; continue; }
    pLife[i] -= dt;
    const k = Math.exp(-3.5 * dt);
    pVel[3 * i] *= k; pVel[3 * i + 1] = pVel[3 * i + 1] * k + 0.25 * dt; pVel[3 * i + 2] *= k;
    pPos[3 * i] += pVel[3 * i] * dt; pPos[3 * i + 1] += pVel[3 * i + 1] * dt; pPos[3 * i + 2] += pVel[3 * i + 2] * dt;
    if (pPos[3 * i + 1] < 0.01) { pPos[3 * i + 1] = 0.01; pVel[3 * i + 1] = Math.abs(pVel[3 * i + 1]) * 0.2; }
  }
  pGeo.attributes.position.needsUpdate = true; pGeo.attributes.color.needsUpdate = true;
}

// =============================================================================== rider (Mixamo Soldier, decoded from base64 GLB)
const riderRoot = new THREE.Group(); scene.add(riderRoot);
const riderLean = new THREE.Group(); riderRoot.add(riderLean);
const fallback = new THREE.Group(); riderLean.add(fallback);
{ const m = new THREE.MeshStandardMaterial({ color: 0x2f6fb3, roughness: 0.8 }), skin = new THREE.MeshStandardMaterial({ color: 0xc99372 });
  const legs = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.1, 0.9, 12), new THREE.MeshStandardMaterial({ color: 0x2a2d33 })); legs.position.y = 0.45; fallback.add(legs);
  const torso = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.14, 0.6, 12), m); torso.position.y = 1.2; fallback.add(torso);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.11, 14, 10), skin); head.position.y = 1.62; fallback.add(head);
  fallback.traverse((o) => { if (o.isMesh) o.castShadow = true; }); }
let soldier = null, mixer = null; const acts = {}, bones = {};
const POSE = { hipFlex: 0.45, knee: 0.8, spread: 0.30, armOut: 0.9, crouchDrop: 0.10 };
if (THREE.GLTFLoader) fetch("models/soldier.glb.b64.txt").then((r) => { if (!r.ok) throw new Error(r.status); return r.text(); }).then((b64) => {
  const bin = atob(b64.trim()), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Promise((res, rej) => new THREE.GLTFLoader().parse(bytes.buffer, "models/", res, rej));
}).then((g) => {
  soldier = g.scene;
  const box = new THREE.Box3().setFromObject(soldier);
  soldier.scale.setScalar(1.75 / (box.max.y - box.min.y));
  soldier.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.frustumCulled = false; } if (o.isBone) bones[o.name] = o; });
  mixer = new THREE.AnimationMixer(soldier);
  for (const clip of g.animations) acts[clip.name] = mixer.clipAction(clip);
  if (acts.Idle) acts.Idle.play();
  riderLean.add(soldier); fallback.visible = false;
}).catch((e) => console.warn("rider model unavailable; using the simple figure", e));
const AX = new THREE.Vector3(1, 0, 0), AZ = new THREE.Vector3(0, 0, 1);
const _qa = new THREE.Quaternion(), _qp = new THREE.Quaternion(), _qs = new THREE.Quaternion(), _qd = new THREE.Quaternion();
function bend(name, axis, ang) {
  const b = bones[name]; if (!b || !ang) return;
  soldier.getWorldQuaternion(_qs).invert();
  b.parent.getWorldQuaternion(_qp); _qp.premultiply(_qs);
  _qa.setFromAxisAngle(axis, ang);
  _qd.copy(_qp).invert().multiply(_qa).multiply(_qp);
  b.quaternion.premultiply(_qd); b.updateMatrixWorld(true);
}
function ridePose(k, armK) {
  soldier.updateMatrixWorld(true);
  bend("mixamorigSpine", AX, -0.2 * k);
  for (const [s, side] of [["Left", -1], ["Right", 1]]) {
    bend(`mixamorig${s}UpLeg`, AX, POSE.hipFlex * k);
    bend(`mixamorig${s}UpLeg`, AZ, side * POSE.spread);
    bend(`mixamorig${s}Leg`, AX, -POSE.knee * k);
    bend(`mixamorig${s}Foot`, AX, (POSE.knee - POSE.hipFlex) * 0.5 * k);
    bend(`mixamorig${s}Arm`, AZ, side * POSE.armOut * armK);
  }
  soldier.position.y = -POSE.crouchDrop * k;
}
function lyingPose() { if (!soldier) return; soldier.position.y = 0; }

// =============================================================================== skateboard model
const skate = new THREE.Group(); scene.add(skate);
const skatePitch = new THREE.Group(); skate.add(skatePitch);
const deckMat = new THREE.MeshStandardMaterial({ color: 0x1d2a3a, roughness: 0.55 });
const gripMat = new THREE.MeshStandardMaterial({ color: 0x15171a, roughness: 1 });
const wheelMat = new THREE.MeshStandardMaterial({ color: 0xf2e6c8, roughness: 0.5 });
const truckMat = new THREE.MeshStandardMaterial({ color: 0x9aa4ad, metalness: 0.8, roughness: 0.35 });
const tankMat = mat("blue_metal_plate", [1, 1], { metalness: 0.6, roughness: 0.35, color: 0x9fb4c8 });
const nozzleMat = new THREE.MeshStandardMaterial({ color: 0x555b62, metalness: 0.9, roughness: 0.3 });
let skateParts = null;
function buildSkate(cfg) {
  while (skatePitch.children.length) skatePitch.remove(skatePitch.children[0]);
  const L = cfg.wheelbase_m, h = cfg.deck_height_m, r = 0.045;
  const deckL = L + 0.24;
  const deck = new THREE.Mesh(new THREE.BoxGeometry(deckL, 0.014, 0.23), deckMat); deck.position.copy(T3(L / 2, 0, h - 0.007)); deck.castShadow = deck.receiveShadow = true; skatePitch.add(deck);
  const grip = new THREE.Mesh(new THREE.BoxGeometry(deckL - 0.02, 0.002, 0.22), gripMat); grip.position.copy(T3(L / 2, 0, h + 0.001)); skatePitch.add(grip);
  const wheels = [];
  for (const x of [0, L]) {
    const tr = new THREE.Mesh(new THREE.BoxGeometry(0.05, h - r - 0.005, 0.16), truckMat); tr.position.copy(T3(x, 0, (h + r) / 2 - 0.004)); tr.castShadow = true; skatePitch.add(tr);
    for (const y of [-0.1, 0.1]) {
      const w = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.045, 20), wheelMat); w.rotation.x = Math.PI / 2;
      const g = new THREE.Group(); g.position.copy(T3(x, y, r)); g.add(w); skatePitch.add(g); w.castShadow = true; wheels.push(g);
      const hub = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.012, 0.047), truckMat); g.add(hub);   // shows rotation
    }
  }
  let tankMesh = null, nozzle = null;
  if (cfg.coldgas) {
    const t = cfg.tank, [D, Lt] = PP.tankGeometry(t.volume_l / 1000);
    tankMesh = new THREE.Group();
    for (let k = 0; k < t.n_tanks; k++) {
      const c = new THREE.Mesh(new THREE.CylinderGeometry(D / 2, D / 2, Lt, 20), tankMat);
      c.rotation.z = Math.PI / 2; c.castShadow = true;
      const off = (k - (t.n_tanks - 1) / 2) * (D + 0.01);
      c.position.copy(T3(cfg.tank_x_m, off, cfg.tank_h_m - h > D / 2 ? cfg.tank_h_m : h + D / 2)); tankMesh.add(c);
    }
    skatePitch.add(tankMesh);
    nozzle = new THREE.Mesh(new THREE.ConeGeometry(0.025, 0.08, 16, 1, true), nozzleMat);
    nozzle.rotation.z = -Math.PI / 2; nozzle.position.copy(T3(cfg.tank_x_m - 0.12, 0, cfg.thrust_height_m)); skatePitch.add(nozzle);
    const line = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, Math.abs(cfg.tank_h_m - cfg.thrust_height_m) + 0.05, 8), nozzleMat);
    line.position.copy(T3(cfg.tank_x_m - 0.08, 0, (cfg.tank_h_m + cfg.thrust_height_m) / 2)); skatePitch.add(line);
  }
  if (cfg.electric) {
    const bat = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.035, 0.16), new THREE.MeshStandardMaterial({ color: 0x24292f })); bat.position.copy(T3(L / 2, 0, h - 0.032)); skatePitch.add(bat);
  }
  skateParts = { wheels, tankMesh, nozzle, wheelAngle: 0 };
}

// =============================================================================== hover-board models (filled in by hover modes)
const hover = new THREE.Group(); scene.add(hover);
let hoverParts = null;
function buildHover(spec) {
  while (hover.children.length) hover.remove(hover.children[0]);
  const deck = new THREE.Mesh(new THREE.BoxGeometry(spec.length, 0.05, spec.width), mat("blue_metal_plate", [2, 1], { metalness: 0.55 }));
  deck.position.y = spec.deckZ; deck.castShadow = deck.receiveShadow = true; hover.add(deck);
  const pods = [], tanks = [];
  for (const th of spec.thrusters) {
    const pod = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.09, 0.16, 16), nozzleMat);
    pod.position.copy(T3(th.pos[0], th.pos[1], th.pos[2] + 0.08)); pod.castShadow = true; hover.add(pod); pods.push(pod);
  }
  for (const tk of spec.tanks) {
    const c = new THREE.Mesh(new THREE.CylinderGeometry(tk.r, tk.r, tk.len, 18), tankMat);
    c.rotation.z = Math.PI / 2; c.position.copy(T3(tk.pos[0], tk.pos[1], tk.pos[2])); c.castShadow = true; hover.add(c); tanks.push(c);
  }
  for (const [x, y] of spec.feet) {
    const f = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.03, spec.deckZ, 8), truckMat); f.position.copy(T3(x, y, spec.deckZ / 2)); hover.add(f);
  }
  hoverParts = { pods, tanks };
}

// =============================================================================== camera
const CAMS = ["Side", "Chase", "Top"];
let camMode = 0, orbit = 0, tilt = 0.18, dist = 4.0;
$("bCam").addEventListener("click", () => { camMode = (camMode + 1) % 3; orbit = 0; tilt = camMode === 2 ? 1.35 : camMode === 1 ? 0.3 : 0.18; toast(CAMS[camMode] + " camera"); });
const touches = new Map();
renderer.domElement.addEventListener("pointerdown", (e) => { touches.set(e.pointerId, [e.clientX, e.clientY]); });
renderer.domElement.addEventListener("pointermove", (e) => {
  const prev = touches.get(e.pointerId); if (!prev) return;
  if (touches.size === 1) { orbit -= (e.clientX - prev[0]) * 0.008; tilt = Math.max(0.02, Math.min(1.45, tilt + (e.clientY - prev[1]) * 0.005)); }
  else if (touches.size === 2) {
    const [a, b] = [...touches.entries()]; const other = a[0] === e.pointerId ? b[1] : a[1];
    const d0 = Math.hypot(prev[0] - other[0], prev[1] - other[1]), d1 = Math.hypot(e.clientX - other[0], e.clientY - other[1]);
    dist = Math.max(1.5, Math.min(30, dist * d0 / Math.max(d1, 1)));
  }
  touches.set(e.pointerId, [e.clientX, e.clientY]);
});
const tEnd = (e) => touches.delete(e.pointerId);
renderer.domElement.addEventListener("pointerup", tEnd); renderer.domElement.addEventListener("pointercancel", tEnd);
renderer.domElement.addEventListener("wheel", (e) => { e.preventDefault(); dist = Math.max(1.5, Math.min(30, dist * (1 + Math.sign(e.deltaY) * 0.1))); }, { passive: false });
const camPos = new THREE.Vector3(0, 2, 5), camLook = new THREE.Vector3();
function updateCamera(target, heading, dt) {
  if (![target.x, target.y, target.z].every(Number.isFinite)) return;
  if (![camPos.x, camPos.y, camPos.z, camLook.x].every(Number.isFinite)) { camPos.set(target.x, target.y + 2, target.z + 5); camLook.copy(target); }
  dt = Math.max(dt, 0);
  const base = camMode === 0 ? Math.PI / 2 : 0;      // side: look from the right of the track
  const ang = heading + Math.PI + base + orbit;
  const d = camMode === 2 ? dist * 2.2 : dist;
  const want = new THREE.Vector3(target.x + Math.cos(ang) * d * Math.cos(tilt), target.y + 0.6 + d * Math.sin(tilt), target.z - Math.sin(ang) * d * Math.cos(tilt));
  const k = Math.min(1, dt * 6);
  camPos.lerp(want, k); camLook.lerp(target, Math.min(1, dt * 10));
  camera.position.copy(camPos); camera.lookAt(camLook);
  sun.position.set(target.x + 6, target.y + 12, target.z + 4); sun.target.position.copy(target);
}

// =============================================================================== UI helpers
let toastT = 0;
function toast(msg, bad = false) { const t = $("toast"); t.textContent = msg; t.classList.toggle("bad", bad); t.style.opacity = 1; toastT = bad ? 4 : 2.2; }
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => { b.closest(".sheet").hidden = true; }));
$("go").addEventListener("click", () => { $("intro").hidden = true; });
function holdButton(el, on, off) {
  const down = (e) => { e.preventDefault(); try { el.setPointerCapture(e.pointerId); } catch (_) { /* synthetic (keyboard) press */ } el.classList.add("on"); on(); };
  const up = () => { el.classList.remove("on"); off(); };
  el.addEventListener("pointerdown", down); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up); el.addEventListener("lostpointercapture", up);
}
function strip(items) {   // items: [{id, label, wide}]
  $("strip").innerHTML = items.map((it) => `<div class="panel ${it.wide ? "wideOnly" : ""}" id="p_${it.id}"><div class="lbl">${it.label}</div><div class="big" id="v_${it.id}">–</div><div class="sub" id="s_${it.id}"></div>${it.bar ? `<div class="bar"><div id="b_${it.id}"></div></div>` : ""}</div>`).join("");
  const wide = innerWidth >= 760; document.querySelectorAll(".wideOnly").forEach((e) => { e.style.display = wide ? "" : "none"; });
}
function setV(id, big, unit, sub, bar, barColor) {
  const v = $("v_" + id); if (v) v.innerHTML = `${big}<span class="unit">${unit || ""}</span>`;
  const s = $("s_" + id); if (s) s.textContent = sub || "";
  const b = $("b_" + id); if (b && bar !== undefined) { b.style.width = `${Math.max(0, Math.min(100, bar * 100))}%`; if (barColor) b.style.background = barColor; }
}
function status(text, color = "var(--green)") { $("stext").textContent = text; $("sdot").style.background = color; }
const barColor = (f) => f > 0.4 ? "var(--green)" : f > 0.15 ? "var(--amber)" : "var(--red)";

// graph: last 40 s of up to 3 normalised series, each labelled with its current value
const gcv = $("graph"), gctx = gcv.getContext("2d");
function drawGraph(frames, upto, series) {
  const w = gcv.clientWidth, h = gcv.clientHeight, dpr = Math.min(devicePixelRatio || 1, 2);
  if (gcv.width !== Math.round(w * dpr)) { gcv.width = Math.round(w * dpr); gcv.height = Math.round(h * dpr); }
  gctx.setTransform(dpr, 0, 0, dpr, 0, 0); gctx.clearRect(0, 0, w, h);
  if (!frames.length) return;
  const tNow = frames[Math.min(upto, frames.length - 1)].t, t0 = Math.max(0, tNow - 40);
  gctx.strokeStyle = "rgba(160,190,215,0.18)"; gctx.lineWidth = 1;
  for (let k = 0; k <= 4; k++) { const y = 4 + (h - 16) * k / 4; gctx.beginPath(); gctx.moveTo(0, y); gctx.lineTo(w, y); gctx.stroke(); }
  gctx.fillStyle = "rgba(147,166,184,0.9)"; gctx.font = "10px system-ui"; gctx.fillText(`${t0.toFixed(0)} s`, 2, h - 2); gctx.fillText(`${tNow.toFixed(1)} s`, w - 38, h - 2);
  let leg = "";
  for (const s of series) {
    let mx = s.max || 1e-9;
    for (let i = 0; i <= upto && i < frames.length; i++) if (frames[i].t >= t0) mx = Math.max(mx, Math.abs(s.get(frames[i])));
    gctx.strokeStyle = s.color; gctx.lineWidth = 1.8; gctx.beginPath();
    let first = true;
    const step = Math.max(1, Math.floor(upto / 600));
    for (let i = 0; i <= upto && i < frames.length; i += step) {
      const f = frames[i]; if (f.t < t0) continue;
      const x = (f.t - t0) / Math.max(tNow - t0, 1e-6) * w, y = 4 + (h - 16) * (1 - s.get(f) / mx);
      if (first) { gctx.moveTo(x, y); first = false; } else gctx.lineTo(x, y);
    }
    gctx.stroke();
    const cur = s.get(frames[Math.min(upto, frames.length - 1)]);
    leg += `<span><i style="background:${s.color}"></i>${s.name} ${s.fmt ? s.fmt(cur) : fmt(cur)}</span>`;
  }
  $("legend").innerHTML = leg;
}

// =============================================================================== recorder / timeline
let frames = [], replay = null, paused = false;
const scrub = $("scrub");
scrub.addEventListener("input", () => {
  if (!frames.length) return;
  replay = { i: Math.round(scrub.value / 1000 * (frames.length - 1)), playing: false };
  paused = true; setPlayIcon();
});
$("bReplay").addEventListener("click", () => { if (!frames.length) return; replay = { i: 0, playing: true, acc: 0 }; paused = false; setPlayIcon(); toast("Replay"); });
$("bPlay").addEventListener("click", () => {
  if (replay && !replay.playing && replay.i >= frames.length - 1) { replay = null; paused = false; }
  else if (replay) { replay.playing = !replay.playing; }
  else paused = !paused;
  setPlayIcon();
});
function setPlayIcon() {
  const playing = replay ? replay.playing : !paused;
  $("bPlay").innerHTML = playing ? '<svg viewBox="0 0 24 24"><path d="M8 5v14M16 5v14"/></svg>' : '<svg viewBox="0 0 24 24"><path d="M6 4v16l13-8z"/></svg>';
}
$("bRestart").addEventListener("click", () => { mode.reset(); frames = []; replay = null; paused = false; setPlayIcon(); toast("Restarted"); });

// =============================================================================== modes
const MODES = {};
let mode = null;

// ------------------------------------------------------------------------------- skateboard mode
MODES.skate = (() => {
  const cfg = JSON.parse(JSON.stringify(PP.SKATE_DEFAULT));
  let sim = null, ctl = { throttle: 0, boost: false, brake: 0 }, lastEvents = 0, eskate = null, report = null, jet = null;
  const m = {
    title: "Cold-gas boosted skateboard", cfg,
    enter() {
      skate.visible = true; hover.visible = false; dist = 4.2; tilt = 0.18; camMode = 0;
      strip([{ id: "spd", label: "Speed" }, { id: "acc", label: "Accel" }, { id: "thr", label: "Thrust" }, { id: "gas", label: "Air left", bar: true },
        { id: "bat", label: "Battery", bar: true, wide: true }, { id: "dst", label: "Distance", wide: true }]);
      $("pad").innerHTML = `<div class="cluster"><button class="btn brake" id="kBrake">BRAKE<small>hold</small></button><button class="btn" id="kCoast">COAST<small>tap</small></button></div>
        <div class="cluster"><button class="btn boost" id="kBoost">BOOST<small>tap on / off</small></button><button class="btn go" id="kAcc">ACCEL<small>hold · wheels</small></button></div>`;
      holdButton($("kAcc"), () => { ctl.throttle = 1; ctl.brake = 0; }, () => { ctl.throttle = 0; });
      holdButton($("kBrake"), () => { ctl.brake = brakeLevel; ctl.throttle = 0; }, () => { ctl.brake = 0; });
      $("kBoost").addEventListener("click", () => { ctl.boost = !ctl.boost; $("kBoost").classList.toggle("on", ctl.boost); });
      $("kCoast").addEventListener("click", () => { ctl.throttle = 0; ctl.boost = false; ctl.brake = 0; $("kBoost").classList.remove("on"); });
      this.reset();
    },
    reset() {
      sim = new PP.SkateSim(cfg); ctl = { throttle: 0, boost: false, brake: 0 }; lastEvents = 0;
      const kb = $("kBoost"); if (kb) kb.classList.remove("on");
      buildSkate(sim.cfg);
      report = cfg.coldgas ? PP.energyReport(cfg.tank) : null;
      if (sim.gasSys) { const st = sim.gasSys.thrustState(1); jet = PP.jetHazard(st.per_thruster, st.ue, st.Te, st.mdot / cfg.thruster.n_thrusters, ROM.assumptions.rocket.acoustic_eff_coldgas); } else jet = null;
      eskate = null;
      riderRoot.visible = true;
      sim.ctl = ctl; sim.step(0.001);          // populate telemetry
    },
    step(dt) { sim.ctl = ctl; return sim.step(dt); },
    snapshot() {
      const t = sim.tel; return { t: t.t, x: t.x, v: t.v, a: t.a, thrust: t.thrust, Tx: t.Tx, gas: t.gas_kg, p: t.p_tank, T: t.T_tank, isp: t.isp, phi: t.phi, theta: t.theta,
        mode: t.mode, rider: t.rider_on, rx: t.rider_x, Nf: t.Nf, Nr: t.Nr, drag: t.drag, Fd: t.F_drive, bat: t.batt_wh, cgx: t.cg_x, cgz: t.cg_z, mass: t.m, mdot: t.mdot, valve: t.valve, brake: t.brake };
    },
    events() { const ev = sim.events.slice(lastEvents); lastEvents = sim.events.length; return ev; },
    view(f, dt) {
      const c = sim.cfg, L = c.wheelbase_m;
      // board: rotate about the active pivot (rear contact for wheelies, front for nose-overs)
      const piv = f.phi >= 0 ? 0 : L;
      skate.position.copy(T3(f.x + piv, 0, 0)); skatePitch.position.copy(T3(-piv, 0, 0));
      skate.rotation.set(0, 0, f.phi);
      skateParts.wheelAngle -= f.v * dt / 0.045;
      for (const w of skateParts.wheels) w.rotation.z = skateParts.wheelAngle;
      // rider: ankles at deck centre, lean theta forward; fallen rider lies on the road where they left the board
      const R = (x, z) => new THREE.Vector3().copy(T3(x - piv, 0, z)).applyAxisAngle(new THREE.Vector3(0, 0, 1), f.phi).add(skate.position);
      if (f.rider) {
        riderRoot.position.copy(R(L / 2, c.deck_height_m));
        riderRoot.rotation.set(0, 0, f.phi); riderLean.rotation.set(0, 0, -f.theta);
        if (soldier) { soldier.rotation.set(0, 0, 0); }
      } else {
        riderRoot.position.copy(T3((f.rx ?? f.x) + 0.6, 0.3, 0.12)); riderRoot.rotation.set(0, 0, 0); riderLean.rotation.set(0, 0, Math.PI / 2);
      }
      // vectors (scale: 1 m per 200 N; velocity 0.12 m per m/s)
      const cg = R(f.cgx, f.cgz); cgMarker.position.copy(cg); cgMarker.visible = showVectors;
      const dirPitch = new THREE.Vector3(Math.cos(f.phi), Math.sin(f.phi), 0);
      setArrow("thrust", R(c.tank_x_m - 0.16, c.thrust_height_m), dirPitch, f.thrust / 200, showVectors);
      setArrow("vel", cg.clone().add(new THREE.Vector3(0, 0.35, 0)), new THREE.Vector3(1, 0, 0), f.v * 0.12, showVectors);
      setArrow("drag", R(L / 2 + 0.1, c.deck_height_m + 1.0), new THREE.Vector3(-1, 0, 0), f.drag / 200, showVectors);
      setArrow("Nf", R(L, 0), new THREE.Vector3(0, 1, 0), Math.max(f.Nf, 0) / 600, showVectors);
      setArrow("Nr", R(0, 0), new THREE.Vector3(0, 1, 0), Math.max(f.Nr, 0) / 600, showVectors);
      setArrow("grav", cg, new THREE.Vector3(0, -1, 0), f.mass * G0 / 600, showVectors);
      setArrow("drive", R(0, 0.02), new THREE.Vector3(1, 0, 0), f.Fd / 200, showVectors);
      for (const k of ["t1", "t2", "t3", "t4"]) arrows[k].visible = false;
      // cold exhaust: frost fog behind the nozzle; amount ~ mass flow, speed ~ jet
      if (f.thrust > 2 && dt > 0) {
        const n = Math.min(40, Math.round(f.mdot * 260 * dt * 60));
        emit(n, R(c.tank_x_m - 0.17, c.thrust_height_m), dirPitch.clone().negate(), 9, 1.2, [0.93, 0.96, 1.0], 0.9);
      }
      return { target: cg.clone(), heading: 0 };
    },
    hud(f) {
      setV("spd", fmt(f.v * 3.6, 0), "km/h", `${fmt(f.v, 1)} m/s · ${fmt(f.v * 2.237, 0)} mph`);
      setV("acc", fmt(f.a / G0, 2), "g", f.brake > 0 ? `braking ${fmt(f.brake, 0)} N` : `drive ${fmt(f.Fd, 0)} N`);
      setV("thr", fmt(f.thrust, 0), "N", f.thrust > 1 ? `Isp ${fmt(f.isp, 0)} s · ${fmt(f.mdot * 1000, 0)} g/s` : "valve closed");
      const g0 = sim.gasSys ? sim.gasSys.m0 : 0;
      const gf = g0 ? f.gas / g0 : 0;
      setV("gas", cfg.coldgas ? fmt(gf * 100, 0) : "–", cfg.coldgas ? "%" : "", cfg.coldgas ? `${fmt(f.gas, 2)} kg · ${fmt(f.p / 1e5, 0)} bar · ${fmt(f.T - 273.15, 0)}°C` : "no tank", gf, barColor(gf));
      const bmax = ROM.assumptions.skateboard.batt_wh;
      setV("bat", cfg.electric ? fmt(f.bat, 0) : "–", "Wh", cfg.electric ? `${fmt(f.bat / bmax * 100, 0)} %` : "no motors", cfg.electric ? f.bat / bmax : 0, barColor(f.bat / bmax));
      setV("dst", fmt(f.x, 0), "m", `t ${fmt(f.t, 1)} s`);
      let st = f.mode === "crashed" ? "CRASHED" : f.mode === "wheelie" ? "WHEELIE: front wheels up" : f.mode === "noseover" ? "NOSE-OVER: rear wheels up" : "rolling";
      if (!f.rider) st = "RIDER FELL · " + st;
      else st += ` · lean ${fmt(f.theta * 57.3, 0)}°`;
      if (f.thrust > 1) st += ` · boost ${fmt(f.valve * 100, 0)} %`;
      status(st, !f.rider || f.mode !== "rolling" ? "var(--red)" : f.thrust > 1 ? "var(--amber)" : "var(--green)");
    },
    graph: [
      { name: "speed", color: "#3fd2ff", get: (f) => f.v, fmt: (v) => fmt(v, 1) + " m/s", max: 5 },
      { name: "thrust", color: "#ffb648", get: (f) => f.thrust, fmt: (v) => fmt(v, 0) + " N", max: 50 },
      { name: "accel", color: "#48e08f", get: (f) => Math.max(0, f.a / G0), fmt: (v) => fmt(v, 2) + " g", max: 0.1 },
    ],
    params() { return skateParams(); },
    dash(tab) { return skateDash(tab); },
    sim: () => sim,
    report: () => report, jet: () => jet,
    eskate() {
      if (!eskate) {
        const s = new PP.SkateSim(Object.assign({}, cfg, { coldgas: false })), r = s.run(PP.defaultSkateScenario(false), 25, 50);
        const b = new PP.SkateSim(cfg), rb = b.run(PP.defaultSkateScenario(true), 25, 50);
        eskate = { e: { vmax: Math.max(...r.v), mass: r.m[0], ledger: r.ledger, t: r.t, v: r.v }, b: { vmax: Math.max(...rb.v), mass: rb.m[0], ledger: rb.ledger, events: rb.events } };
      }
      return eskate;
    },
  };
  return m;
})();
let brakeLevel = 0.2;

// parameter sheet builders ----------------------------------------------------------------
function slider(key, label, min, max, step, val, show) {
  return `<div class="ctl"><label for="i_${key}">${label}</label><output id="o_${key}">${show(val)}</output><input type="range" id="i_${key}" data-k="${key}" min="${min}" max="${max}" step="${step}" value="${val}"></div>`;
}
function seg(key, label, opts, val) {
  return `<h3>${label}</h3><div class="seg" data-seg="${key}">${opts.map(([v, l]) => `<button data-v="${v}" class="${String(v) === String(val) ? "on" : ""}">${l}</button>`).join("")}</div>`;
}
let paramSpec = [];
function openParams() {
  const p = mode.params(); paramSpec = p.spec;
  $("paramTitle").textContent = mode.title + " · parameters";
  $("paramBody").innerHTML = p.html;
  $("paramBody").querySelectorAll("input[type=range]").forEach((el) => el.addEventListener("input", () => {
    const s = paramSpec.find((x) => x.key === el.dataset.k); $("o_" + s.key).textContent = s.show(+el.value);
  }));
  $("paramBody").querySelectorAll(".seg").forEach((sg) => sg.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    sg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
  })));
  $("sheetParams").hidden = false;
}
$("bGear").addEventListener("click", openParams);
$("applyParams").addEventListener("click", () => {
  for (const s of paramSpec) {
    let v;
    if (s.seg) { const b = $("paramBody").querySelector(`[data-seg="${s.key}"] button.on`); v = b ? b.dataset.v : null; if (v === "true") v = true; else if (v === "false") v = false; else if (v !== null && s.num) v = +v; }
    else v = +$("i_" + s.key).value;
    s.set(v);
  }
  $("sheetParams").hidden = true; mode.reset(); frames = []; replay = null; paused = false; setPlayIcon(); toast("New configuration");
});
const lb = (kg) => `${Math.round(kg)} kg · ${Math.round(kg * 2.20462)} lb`;
function skateParams() {
  const c = MODES.skate.cfg, t = c.tank, th = c.thruster;
  const spec = [
    { key: "rider", show: lb, set: (v) => { c.rider_kg = v; } },
    { key: "vol", show: (v) => `${v} L`, set: (v) => { t.volume_l = v; } },
    { key: "ntank", show: (v) => `${v}`, set: (v) => { t.n_tanks = v; } },
    { key: "pbar", show: (v) => `${v} bar`, set: (v) => { t.pressure_bar = v; } },
    { key: "preg", show: (v) => `${v} bar`, set: (v) => { th.reg_pressure_bar = v; } },
    { key: "dthr", show: (v) => `${v} mm`, set: (v) => { th.throat_diameter_mm = v; } },
    { key: "hthr", show: (v) => `${v.toFixed(2)} m`, set: (v) => { c.thrust_height_m = v; } },
    { key: "ramp", show: (v) => `${v.toFixed(1)} s`, set: (v) => { c.boost_ramp_s = v; } },
    { key: "brake", show: (v) => `${(v * 100).toFixed(0)} %`, set: (v) => { brakeLevel = v; } },
    { key: "tclass", seg: true, set: (v) => { t.tank_class = v; } },
    { key: "gas", seg: true, set: (v) => { t.gas = v; } },
    { key: "thermal", seg: true, set: (v) => { t.thermal = v; } },
    { key: "coldgas", seg: true, set: (v) => { c.coldgas = v; } },
    { key: "electric", seg: true, set: (v) => { c.electric = v; } },
    { key: "stance", seg: true, set: (v) => { c.stance = v; } },
    { key: "antic", seg: true, set: (v) => { c.rider_anticipates = v; } },
    { key: "deadman", seg: true, set: (v) => { c.deadman = v; } },
    { key: "vectors", seg: true, set: (v) => { showVectors = v; } },
  ];
  const s = (k) => spec.find((x) => x.key === k);
  const html =
    `<h3>Rider</h3>` + slider("rider", "Rider mass", 40, 150, 1, c.rider_kg, s("rider").show) +
    seg("stance", "Stance", [["upright", "Upright (CdA 0.60)"], ["crouch", "Crouch (CdA 0.35)"]], c.stance) +
    seg("antic", "Rider expects the boost", [[true, "Leans in (anticipates)"], [false, "Surprised"]], c.rider_anticipates) +
    `<h3>Cold-gas boost</h3>` + seg("coldgas", "Boost system", [[true, "Fitted"], [false, "None (plain e-board)"]], c.coldgas) +
    slider("vol", "Tank water volume (each)", 1, 20, 0.1, t.volume_l, s("vol").show) + slider("ntank", "Number of tanks", 1, 4, 1, t.n_tanks, s("ntank").show) +
    slider("pbar", "Fill pressure", 50, 700, 10, t.pressure_bar, s("pbar").show) +
    seg("tclass", "Tank construction (PV/m)", [["metal", "Steel/Al 18 kJ/kg"], ["type3", "Carbon T3 44 kJ/kg"], ["type4", "Carbon T4 98 kJ/kg"]], t.tank_class) +
    seg("gas", "Gas", [["air", "Air"], ["n2", "Nitrogen"]], t.gas) +
    seg("thermal", "Tank thermal model", [["heat_transfer", "Wall heat transfer"], ["adiabatic", "Adiabatic"], ["isothermal", "Isothermal"]], t.thermal) +
    slider("preg", "Regulator set pressure", 5, 80, 1, th.reg_pressure_bar, s("preg").show) + slider("dthr", "Nozzle throat diameter", 2, 14, 0.5, th.throat_diameter_mm, s("dthr").show) +
    slider("hthr", "Thrust line height", 0.05, 1.4, 0.01, c.thrust_height_m, s("hthr").show) + slider("ramp", "Valve opening ramp", 0, 2, 0.1, c.boost_ramp_s, s("ramp").show) +
    seg("deadman", "Dead-man cut-off", [[true, "On (thrust stops if rider falls)"], [false, "Off"]], c.deadman) +
    `<h3>Wheels</h3>` + seg("electric", "Hub motors", [[true, "Dual hub 2 × 1.5 kW"], [false, "None"]], c.electric) +
    slider("brake", "Brake strength (of traction limit)", 0.1, 1, 0.05, brakeLevel, s("brake").show) +
    seg("vectors", "Force vectors", [[true, "Show"], [false, "Hide"]], showVectors) +
    `<p class="note">Rolling resistance Crr ${ROM.assumptions.skateboard.crr}, friction μ ${ROM.assumptions.skateboard.mu}, wheelbase ${c.wheelbase_m} m. Tank mass = P·V / (PV/m). Real-gas air/N₂ properties from reference equations of state.</p>`;
  return { spec, html };
}

// dashboard -------------------------------------------------------------------------------
let dashTab = "now";
document.querySelectorAll("#dashTabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#dashTabs button").forEach((x) => x.classList.toggle("on", x === b)); dashTab = b.dataset.t; renderDash();
}));
$("bDash").addEventListener("click", () => { $("sheetDash").hidden = false; renderDash(); });
function renderDash() { $("dashBody").innerHTML = mode.dash(dashTab); }
const rowsT = (rows) => `<div class="scroll"><table>${rows.map((r) => r[0] === "#" ? `<tr><th colspan="3">${r[1]}</th></tr>` : `<tr><td>${r[0]}</td><td class="n">${r[1]}</td><td class="note">${r[2] || ""}</td></tr>`).join("")}</table></div>`;
function warnList(ws) { return ws.map(([lvl, txt]) => `<div class="warn ${lvl}">${txt}</div>`).join(""); }

function skateDash(tab) {
  const M = MODES.skate, sim = M.sim(), f = frames.length ? frames[frames.length - 1] : M.snapshot(), c = sim.cfg, gs = sim.gasSys, rep = M.report(), jet = M.jet();
  const parts = sim.parts();
  if (tab === "now") {
    const g0 = gs ? gs.m0 : 0, mdot = f.mdot || (gs ? gs.thrustState(1).mdot : 0);
    const cost = { board: ROM.assumptions.skateboard.cost_board, edrive: c.electric ? ROM.assumptions.skateboard.cost_edrive : 0, tank: gs ? PP.tankCost(c.tank) : 0,
      valves: gs ? ROM.assumptions.coldgas.cost_valves_base + c.thruster.n_thrusters * ROM.assumptions.coldgas.cost_per_thruster : 0 };
    const total = cost.board + cost.edrive + cost.tank + cost.valves;
    const ws = [];
    if (!f.rider) ws.push(["bad", "Rider has fallen off. With the dead-man cut-off " + (c.deadman ? "ON the thrust stopped." : "OFF the board keeps accelerating riderless.")]);
    if (f.mode === "wheelie") ws.push(["bad", "Front wheels have lifted: acceleration too high for the stance/thrust line."]);
    if (f.mode === "noseover") ws.push(["bad", "Rear wheels have lifted: braking too hard or thrust line too high."]);
    if (f.v > 12) ws.push(["", `Speed ${fmt(f.v, 1)} m/s: urethane-wheel boards develop speed wobble around 12–13 m/s.`]);
    if (gs && gs.maxThrust() / f.mass > 0.25 * G0) ws.push(["bad", "Boost alone exceeds 0.25 g: an unprepared rider cannot hold that."]);
    if (!ws.length) ws.push(["ok", "No feasibility flags at the current state."]);
    return warnList(ws) + rowsT([
      ["#", "Mass"], ["Total", fmt(f.mass, 1) + " kg"], ...parts.map((p) => [p[0], fmt(p[1], 2) + " kg"]),
      ["#", "State"], ["Speed", fmt(f.v, 2) + " m/s", fmt(f.v * 3.6, 0) + " km/h"], ["Acceleration", fmt(f.a, 2) + " m/s²", fmt(f.a / G0, 3) + " g"],
      ["Thrust", fmt(f.thrust, 1) + " N", f.thrust > 1 ? `Isp ${fmt(f.isp, 1)} s` : ""], ["Gas flow", fmt((f.mdot || 0) * 1000, 0) + " g/s"],
      ["Air remaining", gs ? fmt(f.gas, 3) + " kg" : "–", gs ? `${fmt(f.gas / g0 * 100, 0)} % · ${fmt(f.p / 1e5, 0)} bar · ${fmt(f.T - 273.15, 0)} °C` : ""],
      ["Boost time left (full valve)", gs && mdot > 0 ? fmt(f.gas / mdot, 1) + " s" : "–", "approx., ignores pressure decay"],
      ["Battery", c.electric ? fmt(f.bat, 0) + " Wh" : "–"], ["Distance", fmt(f.x, 1) + " m"], ["Front / rear wheel load", `${fmt(f.Nf, 0)} / ${fmt(f.Nr, 0)} N`],
      ["#", "Cost (parts, nominal)"], ["Deck, trucks, wheels", "$" + fmt(cost.board, 0)], ["Hub motors + battery", "$" + fmt(cost.edrive, 0)], ["Tank(s)", "$" + fmt(cost.tank, 0)],
      ["Regulator, valves, thruster", "$" + fmt(cost.valves, 0)], ["Total", "$" + fmt(total, 0)], ["Refill electricity", rep ? "$" + fmt(rep.refill_cost_usd, 2) : "–", rep ? `${fmt(rep.refill_electric_kwh, 2)} kWh at compressor` : ""],
    ]);
  }
  if (tab === "hazard") {
    if (!rep) return `<p>No pressurised gas on board: hazards are those of an ordinary electric skateboard.</p>`;
    const H = ROM.hazards;
    return warnList([["bad", `Stored gas: ${fmt(rep.burst_energy_kj, 0)} kJ of expansion energy (${fmt(rep.tnt_equiv_kg, 2)} kg TNT equivalent, surface burst). A vessel rupture would give ≥1 psi overpressure to ${fmt(rep.blast_radius_1psi_m, 1)} m and ≥5 psi (eardrum rupture) to ${fmt(rep.blast_radius_5psi_m, 1)} m. Fragments, the main killer in vessel failures, are not modelled.`],
      ["", `Exhaust jet: above ${H.jet_velocity_m_s} m/s for ${fmt(jet.velocity_zone_m, 1)} m behind the board; exit gas at ${fmt((sim.gasSys.thrustState(1).Te) - 273.15, 0)} °C (frost/condensation), below ${fmt(PP.T_AMB - 273.15 + H.jet_cold_excess_k, 0)} °C for ${fmt(jet.temperature_zone_m, 1)} m.`],
      ["", `Noise: ~${fmt(jet.spl_at_1m_db, 0)} dB at 1 m, ${fmt(jet.spl_rider_db, 0)} dB at the rider's ears, ${fmt(jet.spl_at_10m_db, 0)} dB at 10 m (NASA SP-8072 scaling, acoustic efficiency ${ROM.assumptions.rocket.acoustic_eff_coldgas}). ${jet.distance_120db_m > 1 ? `Above 120 dB within ${fmt(jet.distance_120db_m, 1)} m.` : ""}`],
      ["bad", `Valve stuck open: ${fmt(sim.gasSys.maxThrust(), 0)} N uncommanded push (${fmt(sim.gasSys.maxThrust() / f.mass / G0, 2)} g) until the tank is empty. A dead-man cut-off and a manual dump valve are mandatory for any concept like this.`],
      ["", `Loss of balance: a standing rider can resist only about ${fmt(ROM.assumptions.skateboard.rider_heel_lever_m / (0.55 * c.rider_height_m), 2)} g of sudden push without leaning first (heel lever / CoM height). Try "Surprised" in the parameters.`],
      ["", `Real gas: at ${c.tank.pressure_bar} bar the compressibility factor is Z = ${fmt(rep.Z_fill, 3)}; an ideal-gas model would over-state the air on board by ${fmt((rep.gas_mass_ideal_kg / rep.gas_mass_kg - 1) * 100, 1)} %.`],
    ]) + `<p class="note">Any physical work on this concept must be professionally reviewed, unmanned and safely contained (blast/fragment containment, remote operation). This page is a computational model only.</p>`;
  }
  if (tab === "energy") {
    const L = sim.ledger(), k = (j) => fmt(j / 1000, 2) + " kJ";
    return `<p class="note">Ground-frame energy ledger of the current run. Sources must equal sinks; the cold-gas boost cannot create energy, it converts stored gas exergy into jet kinetic energy, most of which is left behind in the exhaust.</p>` + rowsT([
      ["#", "Sources"], ["Battery to motors", k(L.batt_out)], ["Jet kinetic energy (vehicle frame)", k(L.jet_ke), "from gas enthalpy"], ["#", "Sinks"],
      ["Kinetic energy now", k(L.ke1)], ["Aerodynamic drag", k(L.drag)], ["Rolling resistance", k(L.roll)], ["Brake heat", k(L.brake_heat)], ["Regenerated to battery", k(L.regen_in)],
      ["Motor + controller losses", k(L.motor_loss)], ["Kinetic energy left in the exhaust", k(L.jet_residual), "ground frame"], ["Rider KE lost in a fall", k(L.rider_ke_lost)],
      ["#", "Checks"], ["Closure residual", fmt(L.rel_residual * 100, 5) + " %", "sources − sinks"], ["Thrust work on board", k(L.thrust_work)],
      ["Propulsive efficiency (thrust work / jet KE)", L.jet_ke > 0 ? fmt(L.thrust_work / L.jet_ke * 100, 1) + " %" : "–", "≈ 2v/(v+ue): low at skateboard speeds"],
      ["Gas exergy drawn from tank", k(L.exergy_used)], ["Jet KE / exergy drawn", L.exergy_used > 0 ? fmt(L.jet_over_exergy * 100, 1) + " %" : "–", "must be ≤ 100 %"],
      ["Gas expelled", fmt(L.gas_used, 3) + " kg"],
    ]);
  }
  if (tab === "compare") return compareTable();
  return aboutText();
}

function compareTable() {
  const B = ROM.baselines, sk = MODES.skate.eskate();
  const rows = [["#", "Wheeled (same track scenario: 3 s wheels, 10 s boost, coast, brake)"],
    ["Electric skateboard (no boost)", `${fmt(sk.e.vmax, 1)} m/s`, `${fmt(sk.e.mass, 0)} kg total · ${fmt(sk.e.ledger.batt_out / 3600, 1)} Wh used`],
    ["Cold-gas boosted (current settings)", `${fmt(sk.b.vmax, 1)} m/s`, `${fmt(sk.b.mass, 0)} kg · ${fmt(sk.b.ledger.gas_used, 2)} kg air · ${sk.b.events.length ? sk.b.events.map((e) => e[1]).join("; ") : "no flags"}`],
    ["#", "Hovering, 200 lb rider (existing Project Levitate results)"],
    [B.air_cushion.label, `${fmt(B.air_cushion.power_kw, 1)} kW`, `~${fmt(B.air_cushion.endurance_min, 0)} min on ${B.air_cushion.battery_kwh} kWh, rides cm above the surface`],
    [B.ducted_fan.label, `${fmt(B.ducted_fan.power_kw, 0)} kW`, `${fmt(B.ducted_fan.endurance_min, 1)} min, ${fmt(B.ducted_fan.gross_kg, 0)} kg, jet ${fmt(B.ducted_fan.jet_m_s, 0)} m/s`],
    [B.turbojet.label, `${fmt(B.turbojet.endurance_min, 0)} min`, `${fmt(B.turbojet.gross_kg, 0)} kg, exhaust ${fmt(B.turbojet.jet_m_s, 0)} m/s, ~650 °C`]];
  for (const k of ["cghover", "rocket"]) if (MODES[k] && MODES[k].summary) rows.push([MODES[k].title + " (current settings)", ...MODES[k].summary()]);
  const st = ROM.studies;
  let extra = "";
  if (st) extra = `<h3>Optimisation studies (Python, saved to the experiment database)</h3>` + (st.lines || []).map((l) => `<div class="warn">${l}</div>`).join("");
  return rowsT(rows) + extra;
}
function aboutText() {
  return `<h3>What is modelled</h3><ul>
  <li>Tank: real-gas air/N₂ (reference Helmholtz EOS tables), mass and energy balance with wall heat transfer; regulator; choked-nozzle mass flow; thrust = ṁ·uₑ + (pₑ−pₐ)·Aₑ.</li>
  <li>Skateboard: variable mass, rolling resistance, drag, hub-motor torque/power/traction limits, braking with traction limit, pitch load transfer with wheelie/nose-over, rider as a balancing inverted pendulum.</li>
  <li>Hoverboards: 6-DOF rigid body with mass and CG changing as propellant is used, thrust-vector forces and torques, ground contact, autopilot (lift-off, hover, translate, stop, rotate, land) that can fail.</li>
  <li>Engines are black boxes (thrust, Isp, throttle range, start/stop rules). No construction or propellant details are modelled.</li></ul>
  <h3>Validation</h3><p class="note">This JavaScript model is a line-by-line port of the Python model (backend/levitate/propulsion) and reproduces Python reference runs to 1e-6. Python tests check closed forms: blowdown (isothermal, adiabatic), rocket equation, coast-down, drag decay, energy closure, no free energy, hover time.</p>
  <h3>Tesla Roadster cold-gas demo (Oct 2026)</h3><p class="note">Press reports of Tesla's 15 Oct 2026 event near Waco/McGregor, Texas describe SpaceX-developed cold-gas thrusters on the new Roadster. Reported (not Tesla technical documents): 200 L of storage on the "Thrust" trim, a further 400 L on the "Rocket" trim, 10,000 psi, "80 kN" rear thrust, a refill of "6 or 7 hours" (30 min target), and Tesla's claim of "4–5× the force the tires can". Nothing in this lab uses those numbers as model inputs: the models here are generic cold-gas physics ("Tesla-inspired").</p>
  <p class="note">Textures: Poly Haven (CC0). Rider: Mixamo-rigged "Soldier" character from the three.js examples.</p>`;
}

// =============================================================================== mode switching & loop
function setMode(k) {
  if (!MODES[k]) { toast("Coming in the next build"); return; }
  document.querySelectorAll("#modes button").forEach((b) => b.classList.toggle("on", b.dataset.m === k));
  mode = MODES[k]; frames = []; replay = null; paused = false; setPlayIcon();
  for (let i = 0; i < NP; i++) pLife[i] = 0;
  mode.enter();
}
document.querySelectorAll("#modes button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.m)));
const keys = {};
addEventListener("keydown", (e) => {
  const k = e.key.toLowerCase(); if (keys[k]) return; keys[k] = true;
  const btn = { w: "kAcc", arrowup: "kAcc", s: "kBrake", arrowdown: "kBrake" }[k];
  if (btn && $(btn)) $(btn).dispatchEvent(new PointerEvent("pointerdown", { pointerId: 99 }));
  if (k === " " && $("kBoost")) { e.preventDefault(); $("kBoost").click(); }
});
addEventListener("keyup", (e) => {
  const k = e.key.toLowerCase(); keys[k] = false;
  const btn = { w: "kAcc", arrowup: "kAcc", s: "kBrake", arrowdown: "kBrake" }[k];
  if (btn && $(btn)) { $(btn).classList.remove("on"); $(btn).dispatchEvent(new PointerEvent("pointerup", { pointerId: 99 })); }
});
function resize() { const w = innerWidth, h = innerHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.fov = w < h ? 64 : 50; camera.updateProjectionMatrix();
  document.querySelectorAll(".wideOnly").forEach((e) => { e.style.display = w >= 760 ? "" : "none"; }); }
addEventListener("resize", resize); resize();

const DT = 0.001;
let acc = 0, last = performance.now(), hudT = 0, recT = 0;
setMode("skate");
function frame(now) {
  const real = Math.min((now - last) / 1000, 0.1); last = now;
  let f;
  if (replay) {
    if (replay.playing) {
      replay.acc = (replay.acc || 0) + real;
      while (replay.i < frames.length - 1 && frames[replay.i + 1].t - frames[0].t <= (frames[replay.i].t - frames[0].t) + replay.acc) { replay.acc -= frames[replay.i + 1].t - frames[replay.i].t; replay.i++; }
      if (replay.i >= frames.length - 1) { replay.playing = false; setPlayIcon(); }
    }
    f = frames[replay.i]; scrub.value = Math.round(replay.i / Math.max(frames.length - 1, 1) * 1000);
  } else {
    if (!paused) {
      acc += real; let n = 0;
      while (acc >= DT && n < 120) { mode.step(DT); acc -= DT; n++; }
      if (n >= 120) acc = 0;
      for (const [t, e] of mode.events()) toast(e, /FELL|crash|loop|nose/i.test(e));
    }
    f = mode.snapshot();
    recT += real;
    if (!paused && (recT >= 1 / 30 || !frames.length)) { frames.push(f); recT = 0; if (frames.length > 30 * 600) frames.splice(0, 30 * 60); }
    scrub.value = 1000;
  }
  const view = mode.view(f, replay && !replay.playing ? 0 : (paused && !replay ? 0 : real));
  stepParticles(paused && !replay ? 0 : real);
  if (mixer) mixer.update(real);
  if (soldier && riderLean.visible) { ridePose(0.6, 0.4); }
  updateCamera(view.target, view.heading, real);
  hudT += real;
  if (hudT > 0.08) { hudT = 0; mode.hud(f); drawGraph(frames, replay ? replay.i : frames.length - 1, mode.graph); $("tlabel").textContent = `${fmt(f.t, 1)} s`; }
  if (toastT > 0) { toastT -= real; if (toastT <= 0) $("toast").style.opacity = 0; }
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
window.__lab = { MODES, setMode, camera, scene, camLook, riderRoot, get mode() { return mode; }, frames: () => frames };
})();
