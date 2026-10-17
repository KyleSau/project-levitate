// Generates figure data from the browser physics engines (same code as the live sims).
// node docs/figures/sim_data.js > docs/figures/sim_data.json
const path = require("path");
const root = path.resolve(__dirname, "..", "..");
const H1 = require(path.join(root, "sim", "hoverboard-h1", "site", "physics.js"));
const PP = require(path.join(root, "sim", "propulsion", "site", "propulsion.js"));
const dt = 0.001;
const settle = (sim, s) => { let t; for (let i = 0; i < s / dt; i++) t = sim.step(dt); return t; };

// air-cushion board: steady state vs rider mass
const riders = [0, 50, 60, 70, 80, 90.72, 100, 110, 120, 130];
const hold = [], fixed = [];
for (const rm of riders) {
  const a = new H1.Sim(); a.riderMass = rm || 1; a.ctl.lift = true; settle(a, 4);
  if (rm) { a.setRider(true); }
  const t = settle(a, 8);
  hold.push({ rider_kg: rm, power_kw: t.totalKW, ride_cm: t.rideHeight * 100, gap_mm: t.meanGap * 1000 });
}
for (const rm of riders.filter((r) => r >= 60)) {
  const b = new H1.Sim(); b.riderMass = rm; b.ctl.lift = true; settle(b, 4); b.setRider(true); settle(b, 2);
  b.ctl.holdGap = false; b.ctl.manualN = 0.85;
  const t = settle(b, 8);
  fixed.push({ rider_kg: rm, power_kw: t.totalKW, ride_cm: t.rideHeight * 100, gap_mm: t.meanGap * 1000 });
}

// boosted skateboard vs plain electric board, same scenario (3 s wheels, 10 s boost, coast, brake)
const skate = {};
for (const [k, boost] of [["electric", false], ["boosted", true]]) {
  const s = new PP.SkateSim(Object.assign({}, PP.SKATE_DEFAULT, { coldgas: boost }));
  const r = s.run(PP.defaultSkateScenario(boost), 30, 100);
  skate[k] = { t: r.t, v: r.v, thrust: r.thrust, gas_kg: r.gas_kg, mass: r.m[0], events: r.events };
}
process.stdout.write(JSON.stringify({ cushion_hold: hold, cushion_fixed085: fixed, skate }));
