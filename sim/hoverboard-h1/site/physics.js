/* LV-H1 hybrid air-cushion hoverboard: real-time 6-DOF physics (SI units, z up, x forward, y left).
 *
 * Lift: 6 skirted plenum compartments (2 across x 3 along), each fed by a variable-pitch lift fan.
 *   Fan map (per fan, speed fraction n, pitch fraction b):  p_f = p0 n^2 (1 - (Q / (Qm(b) n))^2),  Qm(b) = Qm1 (0.15 + 0.85 b)
 *   Compartment system:  p_f = p_s + 1/2 rho (Q/A_c)^2,   leakage under the skirt hem  Q = Cd * perim * h_eff * sqrt(2 p_s / rho)
 *   => closed form  Q^2 = p0 n^2 / (K + p0/Qm^2),  K = rho/2 (1/A_gap^2 + 1/A_c^2)
 *   Force on the hull per compartment (along body z):  F = p_s A_c + rho Q^2 / A_c
 *     small gap  -> F ~ p_s A_c (cushion);  large gap -> F = 2 * dynamic pressure * A_c (free jet momentum)
 *   Fan shaft power  P = p_f Q / eta(phi),  phi = Q/(Qm n),  eta = 0.72 (1 - ((phi-0.55)/0.55)^2) >= 0.08, plus windage floor.
 * Propulsion: 2 rear ducted thrust fans (momentum theory power), reverse at 50 %.
 * Battery: 24S14P Molicel P45B-class pack, OCV(SoC) table, internal resistance, continuous/burst current limits, 3.0 V cutoff.
 * Contact: penalty springs at skids and hull corners against a height field (ground, dock block, pond with buoyancy).
 * Integration: fixed 1 ms steps, semi-implicit Euler for translation, quaternion + Euler's equations for rotation.
 * All parameters below are design/catalog assumptions, not measurements.
 */
(function (root) {
  const G = 9.80665, RHO = 1.225;

  const SPEC = {
    L: 1.80, W: 0.72, deckThick: 0.07, skirtDepth: 0.15, skidDepth: 0.10, cd: 0.6,
    fan: { n: 6, p0: 1900, Qm1: 10.0, diam: 0.33, tau: 0.45, pitchTau: 0.25, pRefShaft: 9800 },
    thrust: { diam: 0.30, maxN: 180, reverse: 0.5, fm: 0.75, tau: 0.25 },
    motorEff: 0.92, avionicsW: 150,
    battery: { series: 24, parallel: 14, cellAh: 4.5, cellR: 0.015, interconnectR: 0.005, cellCont: 45, cellBurst: 70,
               burstSeconds: 10, cutoffCell: 3.0 },
    speedLimit: 8.0,
    // component masses [kg] and positions in body frame (origin = centre of deck underside)
    parts: [
      { name: "deck + frame", m: 14, pos: [0, 0, 0.035], box: [1.8, 0.72, 0.07] },
      { name: "skirt", m: 6, pos: [0, 0, -0.075], box: [1.8, 0.72, 0.15] },
      { name: "lift fans (6)", m: 27, pos: [0, 0, 0.04], box: [1.6, 0.6, 0.08] },
      { name: "thrust fans (2)", m: 8, pos: [-0.78, 0, 0.18], box: [0.2, 0.7, 0.3] },
      { name: "battery 5.4 kWh", m: 31, pos: [0, 0, 0.09], box: [1.2, 0.3, 0.06] },
      { name: "electronics", m: 5, pos: [0.4, 0, 0.09], box: [0.3, 0.2, 0.05] },
    ],
    rider: { m: 90.72, cgHeight: 1.00, box: [0.30, 0.45, 1.75] },
  };

  const SURFACES = {
    asphalt: { rough: 0.003, hem: 0.015, mu: 0.7 },
    concrete: { rough: 0.001, hem: 0.010, mu: 0.6 },
    grass: { rough: 0.030, hem: 0.050, mu: 0.5 },
    water: { rough: 0.005, hem: 0.020, mu: 0.0 },
  };

  // world: road along x, concrete plaza, grass field, pond, raised loading dock (0.30 m)
  const WORLD = {
    dock: { x0: 14, x1: 18, y0: 7, y1: 12, h: 0.30 },
    pond: { x: -12, y: 12, r: 7 },
    ground(x, y) {
      const d = this.dock;
      if (x >= d.x0 && x <= d.x1 && y >= d.y0 && y <= d.y1) return { h: d.h, s: "concrete", dock: true };
      const dx = x - this.pond.x, dy = y - this.pond.y;
      if (dx * dx + dy * dy < this.pond.r * this.pond.r) return { h: 0, s: "water" };
      if (Math.abs(y) <= 4) return { h: 0, s: "asphalt" };
      if (x > 8) return { h: 0, s: "concrete" };
      return { h: 0, s: "grass" };
    },
  };

  // Li-ion NMC/NCA open-circuit voltage per cell vs state of charge
  const OCV = [[0, 3.0], [0.05, 3.3], [0.1, 3.45], [0.2, 3.56], [0.3, 3.63], [0.4, 3.69], [0.5, 3.75], [0.6, 3.83],
    [0.7, 3.92], [0.8, 4.0], [0.9, 4.08], [1, 4.18]];
  const ocvCell = (s) => {
    s = Math.max(0, Math.min(1, s));
    for (let i = 1; i < OCV.length; i++) if (s <= OCV[i][0]) {
      const [a, va] = OCV[i - 1], [b, vb] = OCV[i];
      return va + (vb - va) * (s - a) / (b - a);
    }
    return OCV[OCV.length - 1][1];
  };

  // ---------- small vector/quaternion helpers
  const qmul = (a, b) => [a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3], a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
    a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1], a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0]];
  const rot = (q, v) => { // body -> world
    const [w, x, y, z] = q;
    return [
      (1 - 2 * (y * y + z * z)) * v[0] + 2 * (x * y - w * z) * v[1] + 2 * (x * z + w * y) * v[2],
      2 * (x * y + w * z) * v[0] + (1 - 2 * (x * x + z * z)) * v[1] + 2 * (y * z - w * x) * v[2],
      2 * (x * z - w * y) * v[0] + 2 * (y * z + w * x) * v[1] + (1 - 2 * (x * x + y * y)) * v[2]];
  };
  const rotT = (q, v) => rot([q[0], -q[1], -q[2], -q[3]], v);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const scl = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const len = (a) => Math.sqrt(dot(a, a));

  function solve3(M, b) { // Cramer's rule for 3x3 (inertia)
    const det = M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1]) - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0]) + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]);
    const c = (r) => { const A = M.map((row) => row.slice()); for (let i = 0; i < 3; i++) A[i][r] = b[i]; return A; };
    const d3 = (A) => A[0][0] * (A[1][1] * A[2][2] - A[1][2] * A[2][1]) - A[0][1] * (A[1][0] * A[2][2] - A[1][2] * A[2][0]) + A[0][2] * (A[1][0] * A[2][1] - A[1][1] * A[2][0]);
    return [d3(c(0)) / det, d3(c(1)) / det, d3(c(2)) / det];
  }

  // ---------- geometry: compartments (2 across x 3 along)
  function compartments(S) {
    const out = [], a = S.L / 3, b = S.W / 2;
    for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) {
      const cx = -S.L / 2 + a * (i + 0.5), cy = (j === 0 ? 1 : -1) * b / 2;
      const ys = (j === 0 ? 1 : -1) * S.W / 2;
      // exposed hem: the outer side edge, plus the end edge for front/rear compartments
      const pts = [[cx - a / 2, ys], [cx, ys], [cx + a / 2, ys]];
      let perim = a;
      if (i === 0) { perim += b; pts.push([-S.L / 2, cy]); }
      if (i === 2) { perim += b; pts.push([S.L / 2, cy]); }
      out.push({ i, j, cx, cy, area: a * b, perim, hemPts: pts });
    }
    return out;
  }

  class Sim {
    constructor(spec = SPEC) {
      this.S = spec;
      this.C = compartments(spec);
      const bt = spec.battery;
      this.packAh = bt.parallel * bt.cellAh;
      this.packR = bt.series * bt.cellR / bt.parallel + bt.interconnectR;
      // free-air (out-of-ground-effect) thrust at full speed and full pitch: Q^2 = p0/(rho/2/A^2 + p0/Qm^2), T = rho Q^2 / A
      this.thrustFree1 = this.C.reduce((s, c) => {
        const Q2 = spec.fan.p0 / (0.5 * RHO / (c.area * c.area) + spec.fan.p0 / (spec.fan.Qm1 * spec.fan.Qm1));
        return s + RHO * Q2 / c.area;
      }, 0);
      this.reset();
    }

    reset() {
      this.t = 0;
      this.riderOn = false;
      this.riderMass = this.S.rider.m;
      this.riderFrac = 0;                 // 0..1 while stepping on/off
      this.riderTarget = 0;
      this.pos = [0, 0, this.S.skidDepth];  // body origin (deck underside centre) in world
      this.vel = [0, 0, 0];
      this.q = [1, 0, 0, 0];
      this.w = [0, 0, 0];
      this.fanN = Array(6).fill(0);         // actual fan speed fraction
      this.fanB = Array(6).fill(0.2);       // actual pitch fraction
      this.thrustN = [0, 0];                // actual thrust-fan command (-0.5..1)
      this.soc = 1.0;
      this.energyWh = 0;
      this.burstUsed = 0;                   // seconds of burst budget used
      this.ctl = { lift: false, hop: false, hopHeight: 1.0, holdGap: true, gapTarget: 0.012, manualN: 0.66, stick: [0, 0] };
      this.wasAirborne = false;
      this.gapInt = 0;
      this.attInt = [0, 0];
      this.colN = 0;
      this.diffN = Array(6).fill(0);
      this.pAvg = 0;
      this.telemetry = {};
      this.updateMass();
    }

    // composite mass, CG and inertia (parallel-axis), updated whenever the rider mass fraction changes
    updateMass() {
      const items = this.S.parts.map((p) => ({ m: p.m, pos: p.pos, box: p.box }));
      const mr = this.riderMass * this.riderFrac;
      if (mr > 0) items.push({ m: mr, pos: [0, 0, this.S.deckThick + this.S.rider.cgHeight], box: this.S.rider.box });
      const m = items.reduce((s, it) => s + it.m, 0);
      const cg = items.reduce((s, it) => add(s, scl(it.pos, it.m / m)), [0, 0, 0]);
      const J = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
      for (const it of items) {
        const [a, b, c] = it.box, d = sub(it.pos, cg);
        const loc = [it.m * (b * b + c * c) / 12, it.m * (a * a + c * c) / 12, it.m * (a * a + b * b) / 12];
        for (let i = 0; i < 3; i++) for (let k = 0; k < 3; k++)
          J[i][k] += (i === k ? loc[i] + it.m * dot(d, d) : 0) - it.m * d[i] * d[k];
      }
      this.mass = m; this.cg = cg; this.J = J;
    }

    // ------------------------------------------------------------------ battery
    battery(loadW) {
      const bt = this.S.battery;
      const voc = ocvCell(this.soc) * bt.series;
      const vmin = bt.cutoffCell * bt.series;
      const iCont = bt.cellCont * bt.parallel, iBurst = bt.cellBurst * bt.parallel;
      const iLimit = this.burstUsed < bt.burstSeconds ? iBurst : iCont;
      const iVolt = (voc - vmin) / this.packR;
      const iMax = Math.max(0, Math.min(iLimit, iVolt));
      const pMax = (voc - iMax * this.packR) * iMax;
      let p = Math.min(loadW, pMax);
      const disc = voc * voc - 4 * this.packR * p;
      const i = disc > 0 ? (voc - Math.sqrt(disc)) / (2 * this.packR) : voc / (2 * this.packR);
      return { voc, v: voc - i * this.packR, i, p, pMax, limited: loadW > pMax + 1, iCont, iBurst };
    }

    // ------------------------------------------------------------------ one fixed step
    step(dt) {
      const S = this.S, ctl = this.ctl;
      // rider stepping on/off: mass transferred over 0.6 s; linear momentum conserved (inelastic merge with a rider at rest)
      if (this.riderFrac !== this.riderTarget) {
        const before = this.mass;
        this.riderFrac = Math.max(0, Math.min(1, this.riderFrac + Math.sign(this.riderTarget - this.riderFrac) * dt / 0.6));
        this.updateMass();
        if (this.mass > before) this.vel = scl(this.vel, before / this.mass);
      }
      const m = this.mass, W = m * G;
      const R = (v) => rot(this.q, v);
      const cgW = add(this.pos, R(this.cg));

      // ---------------- height above ground under each compartment's exposed hem
      const up = R([0, 0, 1]);
      let F = [0, 0, -W], T = [0, 0, 0];
      const comp = [];
      let sumGap = 0, liftTot = 0, qTot = 0, ps = [];
      for (let k = 0; k < 6; k++) {
        const c = this.C[k];
        let gsum = 0, rough = 0, hem = 0, water = false;
        for (const [px, py] of c.hemPts) {
          const pw = add(this.pos, R([px, py, -S.skirtDepth]));
          const gr = WORLD.ground(pw[0], pw[1]);
          gsum += pw[2] - gr.h;
          rough += SURFACES[gr.s].rough; hem += SURFACES[gr.s].hem; water = water || gr.s === "water";
        }
        const n = c.hemPts.length;
        const gap = gsum / n;
        comp.push({ gap, rough: rough / n, hem: hem / n, water });
        sumGap += gap;
      }
      const meanGap = sumGap / 6;

      // ---------------- controller: collective lift (gap hold or manual) + attitude trim per compartment
      let collective;
      // airborne (out of cushion) control: climb-rate loop; free-air thrust scales ~ n^2 (fan laws)
      const rideH = meanGap;                                     // skirt hem above ground (mean)
      const nFree = Math.sqrt(Math.min(1, W / this.thrustFree1));
      const airborne = (vzCmd) => Math.max(0, Math.min(1, nFree + 0.5 * (vzCmd - this.vel[2])));
      const blend = Math.max(0, Math.min(1, (rideH - 0.06) / 0.09));   // 0 on cushion -> 1 when >15 cm up
      if (!ctl.lift) collective = 0;
      else if (ctl.hop) {
        this.wasAirborne = true;
        const vzCmd = Math.max(-0.8, Math.min(1.5, 1.2 * (ctl.hopHeight - rideH)));
        collective = Math.max(airborne(vzCmd), blend < 1 ? 1.0 * (1 - blend) : 0);
      } else if (this.wasAirborne) {
        // descending from a hop at 0.6 m/s, handing over to the cushion as the skirt nears the ground
        if (blend <= 0) this.wasAirborne = false;
        const eG = ctl.gapTarget - meanGap;
        const cushion = Math.max(0, Math.min(1, Math.sqrt(W / (S.L * S.W) / S.fan.p0) + 6 * eG + this.gapInt - 0.6 * this.vel[2]));
        collective = blend * airborne(-0.6) + (1 - blend) * cushion;
      } else if (ctl.holdGap) {
        const e = ctl.gapTarget - meanGap;
        this.gapInt = Math.max(-0.5, Math.min(0.5, this.gapInt + e * dt * 12));
        const vz = this.vel[2];
        // feed-forward: speed whose shutoff pressure just carries the weight, then PI on gap and damping on climb rate
        const nFF = Math.sqrt(W / (S.L * S.W) / S.fan.p0);
        collective = Math.max(0, Math.min(1, nFF + 6 * e + this.gapInt - 0.6 * vz));
      } else collective = ctl.manualN;
      // attitude: roll from left/right difference, pitch from front/rear difference (body angles)
      const fwd = R([1, 0, 0]), left = R([0, 1, 0]);
      const pitch = Math.asin(Math.max(-1, Math.min(1, -fwd[2]))), roll = Math.asin(Math.max(-1, Math.min(1, left[2])));
      const wb = this.w;
      // on the cushion the plenums level the board passively; airborne it is an inverted pendulum (rider CG ~1 m up)
      const air = ctl.lift ? blend : 0;
      const kp = 1.2 + 2.3 * air, kd = 0.25 + 0.65 * air;
      if (ctl.lift) {   // integral trim removes the steady tilt from an off-centre CG (rider stance, rear fan mass)
        this.attInt[0] = Math.max(-0.3, Math.min(0.3, this.attInt[0] + roll * dt * 2));
        this.attInt[1] = Math.max(-0.3, Math.min(0.3, this.attInt[1] + pitch * dt * 2));
      }
      const uRoll = -(kp * roll + kd * wb[0] + this.attInt[0]);   // >0 lifts the left side
      const uPitch = (kp * pitch + kd * wb[1] + this.attInt[1]);  // >0 lifts the front
      // attitude-priority mixing: differential first, collective lowered if any fan would saturate.
      // Collective acts through rotor speed (slow, tau 0.45 s); differential through blade pitch (fast, tau 0.1 s).
      const diff = this.C.map((c) => ctl.lift
        ? (c.j === 0 ? 1 : -1) * uRoll * 0.5 + (c.i === 2 ? 1 : c.i === 0 ? -1 : 0) * uPitch * 0.5 : 0);
      const dMax = Math.max(...diff);
      if (collective + dMax > 1) collective = Math.max(0, 1 - dMax);
      this.colN += (collective - this.colN) * Math.min(1, dt / S.fan.tau);
      for (let k = 0; k < 6; k++) {
        this.diffN[k] += (diff[k] - this.diffN[k]) * Math.min(1, dt / 0.1);
        this.fanN[k] = Math.max(0, Math.min(1, this.colN + this.diffN[k]));
      }

      // ---------------- per-compartment fan / plenum / leakage solution
      let fanShaft = 0, edgeV = 0, edgeQ = 0, pSum = 0;
      for (let k = 0; k < 6; k++) {
        const c = this.C[k], st = comp[k];
        const n = this.fanN[k];
        const hEff = Math.max(st.gap, 0) + st.rough;
        const Agap = Math.max(S.cd * c.perim * hEff, 1e-5);
        const Qm = S.fan.Qm1 * (0.15 + 0.85 * this.fanB[k]);
        const K = 0.5 * RHO * (1 / (Agap * Agap) + 1 / (c.area * c.area));
        const p0n = S.fan.p0 * n * n;
        const Q = n > 1e-3 ? Math.sqrt(p0n / (K + S.fan.p0 / (Qm * Qm))) : 0;
        const pf = n > 1e-3 ? p0n * (1 - (Q / (Qm * n)) ** 2) : 0;
        // plenum pumping: a compartment rising at v_up enlarges its volume by A_c v_up per second, so that much of the
        // fan flow refills it instead of leaking out; leakage (and hence p_s ~ Q_leak^2) drops. Descending does the reverse.
        // This is the dominant heave damping of an air cushion.
        const rC = sub(R([c.cx, c.cy, 0]), R(this.cg));
        const vUp = this.vel[2] + cross(R(this.w), rC)[2];
        const qLeak = Math.max(Q - c.area * vUp, 0.05 * Q);
        const pS = 0.5 * RHO * (qLeak / Agap) ** 2;
        const lift = pS * c.area + RHO * Q * Q / c.area;
        const phi = n > 1e-3 ? Q / (Qm * n) : 0;
        const eta = Math.max(0.08, 0.72 * (1 - ((phi - 0.55) / 0.55) ** 2));
        fanShaft += pf * Q / eta + 0.03 * S.fan.pRefShaft * n * n * n;
        // auto-pitch: steer the fan toward its efficient flow coefficient (rate-limited actuator)
        const bWant = Math.max(0, Math.min(1, (Q / (0.55 * Math.max(n, 0.05)) / S.fan.Qm1 - 0.15) / 0.85));
        const bCmd = ctl.hop ? 1 : bWant;
        this.fanB[k] += (bCmd - this.fanB[k]) * Math.min(1, dt / S.fan.pitchTau);
        // force along body z at the compartment centroid
        const r = [c.cx, c.cy, 0];
        const fW = R([0, 0, lift]);
        F = add(F, fW);
        T = add(T, cross(sub(R(r), R(this.cg)), fW));
        liftTot += lift; qTot += Q; ps.push(pS); pSum += pS;
        edgeV = Math.max(edgeV, Math.sqrt(2 * pS / RHO)); edgeQ += Q;
        st.Q = Q; st.pS = pS; st.lift = lift; st.n = n;
      }

      this.pAvg = pSum / 6;
      // ---------------- thrust fans (rear, y = +/-0.25, z = 0.18)
      const [sy, sx] = ctl.stick;     // stick y: forward/back, x: turn (right positive)
      const vBody = rotT(this.q, this.vel);
      let thrustCmd = sy;
      if (vBody[0] > S.speedLimit && thrustCmd > 0) thrustCmd = 0;          // governor
      if (vBody[0] < -S.speedLimit / 2 && thrustCmd < 0) thrustCmd = 0;
      const tc = [thrustCmd - 0.6 * sx, thrustCmd + 0.6 * sx];             // left, right
      let thrustShaft = 0;
      const At = Math.PI * (S.thrust.diam / 2) ** 2;
      for (let s = 0; s < 2; s++) {
        let c = Math.max(-S.thrust.reverse, Math.min(1, tc[s]));
        if (!ctl.lift) c = 0;
        this.thrustN[s] += (c - this.thrustN[s]) * Math.min(1, dt / S.thrust.tau);
        const Tn = this.thrustN[s] * S.thrust.maxN;
        const fW = R([Tn, 0, 0]);
        const r = [-0.78, s === 0 ? 0.25 : -0.25, 0.18];
        F = add(F, fW);
        T = add(T, cross(sub(R(r), R(this.cg)), fW));
        thrustShaft += Math.abs(Tn) ** 1.5 / (Math.sqrt(4 * RHO * At) * S.thrust.fm);
      }

      // ---------------- electrical power & battery (power cap scales all fans back if the pack can't deliver)
      const loadW = (fanShaft + thrustShaft) / S.motorEff + (ctl.lift ? S.avionicsW : 30);
      const bat = this.battery(loadW);
      if (bat.limited) {
        const k = Math.sqrt(bat.p / loadW);
        this.colN *= Math.pow(k, 1 / 3);   // P ~ n^3: the pack throttles the rotors
      }
      if (bat.i > bat.iCont) this.burstUsed += dt; else this.burstUsed = Math.max(0, this.burstUsed - dt * 0.2);
      this.soc -= bat.i * dt / 3600 / this.packAh;
      this.energyWh += bat.p * dt / 3600;
      if (this.soc <= 0) { this.soc = 0; this.ctl.lift = false; }

      // ---------------- surface drag (skirt hem), aero drag, contact
      const vH = [this.vel[0], this.vel[1], 0];
      const sp = len(vH);
      let hemC = 0, gapMin = 1e9, water = false;
      for (const st of comp) { hemC += st.hem / 6; gapMin = Math.min(gapMin, st.gap); water = water || st.water; }
      const cushionLoad = Math.min(liftTot, W);
      if (sp > 1e-4) F = add(F, scl(vH, -hemC * cushionLoad * Math.min(sp / 0.3, 1) / sp * Math.exp(-Math.max(gapMin, 0) / 0.05)));
      const CdA = 0.20 + 0.60 * this.riderFrac;
      F = add(F, scl(this.vel, -0.5 * RHO * CdA * len(this.vel)));
      // yaw/roll/pitch aerodynamic + skirt damping
      const wW = R(this.w);
      T = add(T, scl(wW, -(8 + 30 * hemC * cushionLoad / 100)));

      // contact points: 4 skids, 4 hull bottom corners at the hem, 4 deck corners (for the dock wall)
      const hx = S.L / 2, hy = S.W / 2;
      const pts = [[0.6, 0.25, -S.skidDepth], [0.6, -0.25, -S.skidDepth], [-0.6, 0.25, -S.skidDepth], [-0.6, -0.25, -S.skidDepth],
        [hx, hy, -S.skirtDepth], [hx, -hy, -S.skirtDepth], [-hx, hy, -S.skirtDepth], [-hx, -hy, -S.skirtDepth],
        [hx, hy, 0], [hx, -hy, 0], [-hx, hy, 0], [-hx, -hy, 0]];
      let contactN = 0;
      for (let k = 0; k < pts.length; k++) {
        const isSkirt = k >= 4 && k < 8;
        const rB = pts[k], rW = R(rB), p = add(this.pos, rW);
        const gr = WORLD.ground(p[0], p[1]);
        const pen = gr.h - p[2];
        const vP = add(this.vel, cross(R(this.w), sub(rW, R(this.cg))));
        const lever = sub(rW, R(this.cg));
        if (gr.s === "water" && !gr.dock) {
          // buoyant hull (deck + sealed skirt pontoons, 0.45 m^3 total), spread over the 12 points
          if (pen > 0) {
            const fb = Math.min(pen, 0.25) * 1000 * G * (S.L * S.W / 12) * 1.0 - 400 * vP[2];
            const f = [0, 0, Math.max(fb, 0)];
            F = add(F, f); T = add(T, cross(lever, f));
            const fd = scl([vP[0], vP[1], 0], -60);
            F = add(F, fd); T = add(T, cross(lever, fd));
          }
          continue;
        }
        if (pen > 0) {
          const d = WORLD.dock;
          const insideDock = gr.dock && pen > 0.06;
          let f;
          if (insideDock) {
            // hitting the dock face: push out horizontally through the nearest face
            const dists = [[p[0] - d.x0, [-1, 0]], [d.x1 - p[0], [1, 0]], [p[1] - d.y0, [0, -1]], [d.y1 - p[1], [0, 1]]];
            dists.sort((a, b) => a[0] - b[0]);
            const [depth, nrm] = dists[0];
            const vn = vP[0] * nrm[0] + vP[1] * nrm[1];
            const fn = Math.max(0, 2.0e5 * depth - 3000 * vn);
            f = [nrm[0] * fn, nrm[1] * fn, 0];
          } else {
            // an inflated skirt is stiff (stiffness ~ cushion pressure); a deflated one folds flat
            const kz = isSkirt ? 300 + 30 * this.pAvg : 1.5e5, cz = isSkirt ? 40 + 0.6 * this.pAvg : 4000;
            const fn = Math.max(0, kz * pen - cz * vP[2]);
            const mu = isSkirt ? 0.3 : SURFACES[gr.s].mu;
            const vt = [vP[0], vP[1], 0], vt_ = len(vt);
            const ft = vt_ > 1e-4 ? scl(vt, -Math.min(mu * fn, 2000 * vt_) / vt_) : [0, 0, 0];
            f = [ft[0], ft[1], fn];
            contactN += fn;
          }
          F = add(F, f); T = add(T, cross(lever, f));
        }
      }

      // ---------------- integrate (forces/torques about the CG)
      const acc = scl(F, 1 / m);
      this.vel = add(this.vel, scl(acc, dt));
      // translate the CG, then recover the body origin so that rotation happens about the CG
      const cgNew = add(cgW, scl(this.vel, dt));
      const Tb = rotT(this.q, T);
      const Jw = [dot(this.J[0], this.w), dot(this.J[1], this.w), dot(this.J[2], this.w)];
      const wdot = solve3(this.J, sub(Tb, cross(this.w, Jw)));
      this.w = add(this.w, scl(wdot, dt));
      const dq = qmul(this.q, [0, this.w[0], this.w[1], this.w[2]]);
      this.q = this.q.map((v, i) => v + 0.5 * dt * dq[i]);
      const qn = Math.hypot(...this.q); this.q = this.q.map((v) => v / qn);
      this.pos = sub(cgNew, rot(this.q, this.cg));
      this.t += dt;

      const grC = WORLD.ground(this.pos[0], this.pos[1]);
      this.telemetry = {
        t: this.t, mass: m, weight: W, lift: liftTot, contactN,
        rideHeight: this.pos[2] - grC.h, meanGap, gaps: comp.map((c) => c.gap), pressures: ps,
        flow: qTot, edgeV, fanN: this.fanN.slice(), fanPitch: this.fanB.slice(), thrust: this.thrustN.map((x) => x * S.thrust.maxN),
        liftKW: fanShaft / S.motorEff / 1000, thrustKW: thrustShaft / S.motorEff / 1000, totalKW: bat.p / 1000,
        demandKW: loadW / 1000, powerLimited: bat.limited, volts: bat.v, amps: bat.i, soc: this.soc, energyWh: this.energyWh,
        burstLeft: Math.max(0, S.battery.burstSeconds - this.burstUsed), speed: sp, surface: grC.s,
        roll, pitch, yaw: Math.atan2(fwd[1], fwd[0]), riderFrac: this.riderFrac,
        remainingMin: bat.p > 1 ? (this.soc * this.packAh * ocvCell(this.soc) * S.battery.series) / bat.p * 60 : Infinity,
      };
      return this.telemetry;
    }

    setRider(on) {
      if (on && len(this.vel) > 0.5) return "Slow down below 0.5 m/s to step on";
      this.riderOn = on; this.riderTarget = on ? 1 : 0; return null;
    }
  }

  const api = { Sim, SPEC, SURFACES, WORLD, ocvCell, rot, compartments };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.HoverPhysics = api;
})(typeof window !== "undefined" ? window : globalThis);
