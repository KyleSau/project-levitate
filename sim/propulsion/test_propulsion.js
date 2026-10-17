// Node test for the browser propulsion physics:  node sim/propulsion/test_propulsion.js
// 1. JS model reproduces Python reference trajectories (same algorithm, same ROM tables) exported by levitate.propulsion.rom
// 2. physics checks run directly on the JS model (energy closure, no free energy, rocket equation, closed forms)
const fs = require("fs");
const path = require("path");
const P = require("./site/propulsion.js");

let fails = 0, passes = 0;
function check(name, ok, detail = "") {
  if (ok) { passes++; console.log(`  ok   ${name} ${detail}`); } else { fails++; console.log(`  FAIL ${name} ${detail}`); }
}
const ref = (n) => JSON.parse(fs.readFileSync(path.join(__dirname, "reference", n + ".json"), "utf8"));
const maxRel = (a, b, floor) => { let e = 0; for (let i = 0; i < Math.min(a.length, b.length); i++) e = Math.max(e, Math.abs(a[i] - b[i]) / Math.max(Math.abs(b[i]), floor)); return e; };

// ------------------------------------------------------------------ 1. parity with Python
console.log("Python parity (skateboard)");
for (const name of ["skate_default", "skate_surprised_rider", "skate_ideal_adiabatic"]) {
  const r = ref(name), cfg = r.config;
  const sim = new P.SkateSim(cfg);
  const scen = r.scenario.map(([t, c]) => [t, c]);
  const js = sim.run(scen, r.t_end, r.record_every), py = r.trace;
  check(`${name}: same sample count`, js.t.length === py.t.length, `${js.t.length} vs ${py.t.length}`);
  for (const [k, floor] of [["v", 1.0], ["x", 1.0], ["thrust", 10.0], ["gas_kg", 0.1], ["p_tank", 1e5], ["T_tank", 100], ["theta", 0.1]]) {
    const e = maxRel(js[k], py[k], floor);
    check(`${name}: ${k} matches Python`, e < 1e-6, `max rel err ${e.toExponential(2)}`);
  }
  check(`${name}: same events`, JSON.stringify(js.events.map((e) => e[1])) === JSON.stringify(py.events.map((e) => e[1])),
    JSON.stringify(js.events.map((e) => e[1])));
  check(`${name}: energy ledger closes (<1e-3)`, Math.abs(js.ledger.rel_residual) < 1e-3, `rel residual ${js.ledger.rel_residual.toExponential(2)}`);
  const pyL = py.ledger;
  check(`${name}: ledger equals Python`, Math.abs(js.ledger.jet_ke - pyL.jet_ke) <= 1e-6 * Math.max(1, pyL.jet_ke) && Math.abs(js.ledger.drag - pyL.drag) <= 1e-6 * Math.max(1, pyL.drag));
}

// ------------------------------------------------------------------ 2. physics on the JS model
console.log("Physics checks (JS)");
{ // no free energy: jet KE never exceeds the exergy drawn from the tank; boost cannot add more KE+losses than the jet gives
  const sim = new P.SkateSim({ electric: false });
  const r = sim.run([[0, { boost: true }]], 15, 50);
  const L = r.ledger;
  check("boost: jet KE <= exergy drawn from tank", L.jet_ke <= L.exergy_used, `jet ${(L.jet_ke / 1e3).toFixed(1)} kJ vs exergy ${(L.exergy_used / 1e3).toFixed(1)} kJ`);
  check("boost: thrust work <= jet KE + carried-propellant KE", L.thrust_work <= L.jet_ke + L.jet_residual, "");
  const useful = L.ke1 + L.drag + L.roll + L.brake_heat;
  check("boost: vehicle KE + losses <= jet energy supplied", useful <= L.jet_ke + 1e-6, `${(useful / 1e3).toFixed(2)} <= ${(L.jet_ke / 1e3).toFixed(1)} kJ`);
  check("boost: ledger closes", Math.abs(L.rel_residual) < 1e-4, L.rel_residual.toExponential(2));
}
{ // isothermal ideal-gas blowdown vs exp(-t/tau) closed form
  const tank = { real_gas: false, thermal: "isothermal", volume_l: 10, pressure_bar: 200 };
  const thr = { regulated: false, throat_diameter_mm: 3, ambient_pa: 0 };
  const s = new P.ColdGasSystem(tank, thr, Object.assign({}, P.A.coldgas, { nozzle_cd: 1.0 }));
  const g = P.GASES.air, tau = 0.01 / (s.At * P.gammaFlow(g.gamma) * Math.sqrt(g.R * 293.15));
  let t = 0, dt = 1e-4, e = 0;
  for (let i = 0; i < 20000; i++) { s.step(dt, 1); t += dt; if (i % 1000 === 999) { const p = s.state()[0], pa = 200e5 * Math.exp(-t / tau); e = Math.max(e, Math.abs(p - pa) / pa); } }
  check("isothermal blowdown = p0 exp(-t/tau)", e < 2e-3, `max rel err ${e.toExponential(2)} (dt=0.1 ms, explicit Euler)`);
}
{ // adiabatic ideal-gas blowdown vs closed form
  const tank = { real_gas: false, thermal: "adiabatic", volume_l: 10, pressure_bar: 200 };
  const thr = { regulated: false, throat_diameter_mm: 3, ambient_pa: 0 };
  const s = new P.ColdGasSystem(tank, thr, Object.assign({}, P.A.coldgas, { nozzle_cd: 1.0 }));
  const g = P.GASES.air, tau = 0.01 / (s.At * P.gammaFlow(g.gamma) * Math.sqrt(g.R * 293.15));
  let t = 0, dt = 1e-4, e = 0;
  for (let i = 0; i < 20000; i++) { s.step(dt, 1); t += dt; if (i % 1000 === 999) { const p = s.state()[0], pa = 200e5 * Math.pow(1 + 0.2 * t / tau, -7); e = Math.max(e, Math.abs(p - pa) / pa); } }
  check("adiabatic blowdown = p0 (1 + (g-1)/2 t/tau)^(-2g/(g-1))", e < 3e-3, `max rel err ${e.toExponential(2)}`);
}
{ // real gas matters: Z at 300 and 690 bar
  const Z300 = P.realGas("air").Z(300e5, 293.15), Z690 = P.realGas("air").Z(690e5, 293.15);
  check("real-gas Z(air, 300 bar, 293 K) ~ 1.10", Math.abs(Z300 - 1.105) < 0.01, Z300.toFixed(4));
  check("real-gas Z(air, 690 bar, 293 K) ~ 1.54", Math.abs(Z690 - 1.545) < 0.02, Z690.toFixed(4));
}
{ // electric-only coast-down closed form (no drag): v(t) = v0 - Crr g t
  const sim = new P.SkateSim({ coldgas: false, electric: false, overrides: { cda_upright: 0 } });
  sim.v = 8; sim.ctl = { throttle: 0, boost: false, brake: 0 };
  let t = 0; while (sim.v > 0 && t < 200) { sim.step(0.001); t += 0.001; }
  const expect = 8 / (P.A.skateboard.crr * P.G0);
  check("rolling coast-down time = v0/(Crr g)", Math.abs(t - expect) / expect < 2e-3, `${t.toFixed(3)} s vs ${expect.toFixed(3)} s`);
}
{ // drag-only decay: v(t) = v0 / (1 + k v0 t), k = rho CdA / (2m)
  const sim = new P.SkateSim({ coldgas: false, electric: false, overrides: { crr: 0 } });
  sim.v = 10; sim.ctl = { throttle: 0, boost: false, brake: 0 };
  const m = sim.massProps()[0], k = 1.225 * P.A.skateboard.cda_upright / (2 * m);
  for (let i = 0; i < 10000; i++) sim.step(0.001);
  const ve = 10 / (1 + k * 10 * 10);
  check("drag-only decay = v0/(1+k v0 t)", Math.abs(sim.v - ve) / ve < 1e-3, `${sim.v.toFixed(4)} vs ${ve.toFixed(4)} m/s`);
}

console.log(`\n${passes} passed, ${fails} failed`);
if (fails) process.exit(1);
