// Scenario + invariant checks for physics.js (run: node test_physics.js)
const path = require("path");
const { Sim, SPEC, compartments } = require(path.join(__dirname, "site", "physics.js"));
const dt = 0.001;
let fails = 0;
const check = (name, ok, info = "") => { console.log(`${ok ? "PASS" : "FAIL"}  ${name} ${info}`); if (!ok) fails++; };
const run = (sim, secs, f) => { let tel; for (let i = 0; i < Math.round(secs / dt); i++) { if (f) f(sim, i * dt); tel = sim.step(dt); } return tel; };
const fmt = (x, d = 3) => Number(x).toFixed(d);

// 0. geometry
const C = compartments(SPEC);
const area = C.reduce((s, c) => s + c.area, 0);
check("compartment areas sum to deck area", Math.abs(area - SPEC.L * SPEC.W) < 1e-9);
check("exposed perimeter = deck perimeter", Math.abs(C.reduce((s, c) => s + c.perim, 0) - 2 * (SPEC.L + SPEC.W)) < 1e-9);

// 1. at rest on skids, fans off
let s = new Sim();
let t = run(s, 3);
check("rests on skids, no NaN", Math.abs(t.rideHeight - SPEC.skidDepth) < 0.01 && isFinite(t.rideHeight), `ride ${fmt(t.rideHeight)} m`);
check("weight of empty board", Math.abs(t.weight - s.mass * 9.80665) < 1e-9, `mass ${fmt(s.mass, 1)} kg`);

// 2. lift on, empty board, gap hold 12 mm
s.ctl.lift = true;
t = run(s, 6);
console.log(`   empty board on cushion: ride ${fmt(t.rideHeight)} m, gap ${fmt(t.meanGap * 1000, 1)} mm, P ${fmt(t.totalKW, 2)} kW, lift ${fmt(t.lift, 0)} N vs W ${fmt(t.weight, 0)} N, edge jet ${fmt(t.edgeV, 1)} m/s`);
check("empty board hovers on cushion at target gap", Math.abs(t.meanGap - 0.012) < 0.004 && Math.abs(t.lift - t.weight) / t.weight < 0.05);
const pEmpty = t.totalKW;

// 3. rider steps on (gap hold): mass, CG, inertia update; board dips then recovers; power rises
const J0 = s.J[0][0], cg0 = s.cg[2];
s.setRider(true);
let minGap = 1;
t = run(s, 8, (sim) => { minGap = Math.min(minGap, sim.telemetry.meanGap ?? 1); });
console.log(`   with rider (hold): ride ${fmt(t.rideHeight)} m, gap ${fmt(t.meanGap * 1000, 1)} mm (min ${fmt(minGap * 1000, 1)} mm), P ${fmt(t.totalKW, 2)} kW, cushion ${fmt(t.pressures[0], 0)} Pa, edge jet ${fmt(t.edgeV, 1)} m/s, roll ${fmt(t.roll * 57.3, 2)} deg`);
check("mass/CG/inertia updated with rider", Math.abs(s.mass - (SPEC.parts.reduce((a, p) => a + p.m, 0) + 90.72)) < 1e-6 && s.cg[2] > cg0 && s.J[0][0] > J0);
check("weight 200 lb + board", Math.abs(t.weight - s.mass * 9.80665) < 1e-6, `${fmt(t.weight, 0)} N`);
check("rider: hovers, gap recovered by hold", Math.abs(t.meanGap - 0.012) < 0.005 && Math.abs(t.lift - t.weight) / t.weight < 0.05);
check("rider: more power than empty", t.totalKW > pEmpty, `${fmt(pEmpty, 2)} -> ${fmt(t.totalKW, 2)} kW`);
check("rider: upright (passive + active roll/pitch)", Math.abs(t.roll) < 0.05 && Math.abs(t.pitch) < 0.05);
const pRiderCruise = t.totalKW;

// 4. fixed fan speed: rider on lowers the board (the user's question)
let a = new Sim(); a.ctl.lift = true; a.ctl.holdGap = false; a.ctl.manualN = 0.66;
let ta = run(a, 6);
const rideEmpty = ta.rideHeight, gapEmpty = ta.meanGap;
a.setRider(true);
ta = run(a, 8);
console.log(`   fixed fan 66 %: empty ride ${fmt(rideEmpty)} m gap ${fmt(gapEmpty * 1000, 1)} mm -> rider ride ${fmt(ta.rideHeight)} m gap ${fmt(ta.meanGap * 1000, 1)} mm`);
check("fixed speed: rider lowers ride height", ta.rideHeight < rideEmpty - 0.003);

// 5. drive forward 15 s: governor limits speed; energy integral consistent
s.ctl.stick = [1, 0];
let eInt = 0, e0 = s.energyWh;
t = run(s, 15, (sim) => { eInt += (sim.telemetry.totalKW || 0) * 1000 * dt / 3600; });
console.log(`   forward: speed ${fmt(t.speed, 2)} m/s, P ${fmt(t.totalKW, 2)} kW (thrust ${fmt(t.thrustKW, 2)}), pos x ${fmt(s.pos[0], 1)} m on ${t.surface}`);
check("speed governed near 8 m/s", t.speed > 6.5 && t.speed < 8.6);
check("energy counter = integral of power", Math.abs((s.energyWh - e0) - eInt) / eInt < 0.01);

// 6. release stick: momentum persists (coasts), decelerates only by drag
s.ctl.stick = [0, 0];
const v0 = s.telemetry.speed;
t = run(s, 2);
check("coasts after releasing thrust (>60 % speed after 2 s)", t.speed > 0.6 * v0 && t.speed < v0, `${fmt(v0, 2)} -> ${fmt(t.speed, 2)} m/s`);

// 7. reverse to stop, then turn in place
s.ctl.stick = [-1, 0];
for (let i = 0; i < 20000 && rotDot(s) > 0.05; i++) s.step(dt);
s.ctl.stick = [0, 0]; run(s, 1);
const yaw0 = s.telemetry.yaw;
s.ctl.stick = [0, 1];
t = run(s, 3);
s.ctl.stick = [0, 0];
check("turns with differential thrust", Math.abs(angDiff(t.yaw, yaw0)) > 0.5, `yaw change ${fmt(angDiff(t.yaw, yaw0) * 57.3, 0)} deg in 3 s`);

// 8. hop (full lift fans) with rider
s.ctl.stick = [0, 0]; run(s, 3);
s.ctl.hop = true;
let maxH = 0, maxP = 0, maxTilt = 0;
t = run(s, 4, (sim) => { const tl = sim.telemetry; maxH = Math.max(maxH, tl.rideHeight || 0); maxP = Math.max(maxP, tl.totalKW || 0); maxTilt = Math.max(maxTilt, Math.abs(tl.pitch || 0), Math.abs(tl.roll || 0)); });
check("stays level in the hop with a rider (< 8 deg)", maxTilt < 0.14, `max tilt ${fmt(maxTilt * 57.3, 1)} deg`);
console.log(`   hop with rider: max ride height ${fmt(maxH)} m, peak power ${fmt(maxP, 1)} kW, burst left ${fmt(t.burstLeft, 1)} s, limited ${t.powerLimited}`);
check("hop raises the board above cushion height", maxH > 0.30);
check("hop respects the 1 m ceiling", maxH - SPEC.skirtDepth < 1.1, `max skirt-hem height ${fmt(maxH - SPEC.skirtDepth, 2)} m`);
s.ctl.hop = false;
let minVz = 0; t = run(s, 8, (sim) => { minVz = Math.min(minVz, sim.vel[2]); });
check("controlled descent (no free fall)", minVz > -1.2, `min vz ${fmt(minVz, 2)} m/s`);
check("returns to cushion after hop", Math.abs(t.meanGap - 0.012) < 0.006, `gap ${fmt(t.meanGap * 1000, 1)} mm`);

// 9. land: fans off -> settles on skids, power ~0
s.ctl.lift = false;
t = run(s, 6);
check("lands on skids", Math.abs(t.rideHeight - SPEC.skidDepth) < 0.02 && t.totalKW < 0.1, `ride ${fmt(t.rideHeight)} m, P ${fmt(t.totalKW, 2)} kW`);

// 10. empty board, hop: flies freely (T/W > 1 out of ground effect)
let e = new Sim(); e.ctl.lift = true; run(e, 4); e.ctl.hop = true;
let maxHE = 0; run(e, 2, (sim) => { maxHE = Math.max(maxHE, sim.telemetry.rideHeight || 0); });
console.log(`   empty board hop: ${fmt(maxHE, 2)} m in 2 s`);

// 11. water: float when landed in the pond
let w = new Sim(); w.pos = [-12, 12, 0.3]; w.ctl.lift = false;
let tw = run(w, 8);
check("floats on water when landed", tw.rideHeight > -0.2 && tw.rideHeight < 0.15 && Math.abs(w.vel[2]) < 0.02, `deck underside at ${fmt(tw.rideHeight)} m`);
w.ctl.lift = true; tw = run(w, 6);
console.log(`   on water, cushion on: ride ${fmt(tw.rideHeight)} m, P ${fmt(tw.totalKW, 2)} kW`);

// 12. grass needs more power than asphalt
let g = new Sim(); g.pos = [0, 10, 0.1]; g.ctl.lift = true; g.setRider(true); let tg = run(g, 10);
console.log(`   grass with rider: P ${fmt(tg.totalKW, 2)} kW vs asphalt ${fmt(pRiderCruise, 2)} kW`);
check("grass costs more power", tg.totalKW > pRiderCruise);

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);

function rotDot(sim) { const f = require(path.join(__dirname, "site", "physics.js")).rot(sim.q, [1, 0, 0]); return sim.vel[0] * f[0] + sim.vel[1] * f[1]; }
function angDiff(a, b) { let d = a - b; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; }
