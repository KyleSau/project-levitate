"""Thrust-borne hoverboards: cold-gas and black-box chemical rocket, carrying a standing rider. 6-DOF rigid body.

Rigid body with variable mass (Evidence: simplified numerical simulation):
  * body frame: x forward, y left, z up; origin = deck centre. Parts are point masses + box inertias; the gas or
    propellant mass sits at the tank location, so CG and inertia change as it is used.
  * instantaneous rigid body about the current CG:  J w' + w x J w = M_cg,  a_cg = F / m,
    the deck origin is integrated with a_o = a_cg - R(w' x c + w x (w x c))  (c = CG in body axes).
    Momentum of the gas still inside the tank relative to the structure and the jet-damping torque are neglected
    (both are O(mdot * r^2 * w), < 1 % of the control torques here).
  * forces: 4 thrusters at the deck corners pointing up, each canted tangentially by `cant_deg` so differential
    thrust gives yaw torque; gravity; drag -1/2 rho CdA |v| v and rotational damping; ground contact with penalty
    springs + Coulomb friction at the 4 feet and 4 deck corners.
  * autopilot: mission state machine (lift-off -> hover -> translate -> stop -> yaw -> land) producing smoothed
    references; position PID -> desired thrust vector -> attitude PD (quaternion error) -> allocation (4x4 solve with
    attitude-priority saturation). Propellant reserve logic aborts to landing; without enough thrust or propellant
    the vehicle fails (does not lift, or falls when it runs dry) and the impact speed is reported.
  * propulsion: cold gas = one regulated tank feeding 4 proportional valves (coldgas.ColdGasSystem.step_multi);
    rocket = 4 black-box engines (rocket.RocketEngine: Isp, throttle range, start delay, stop/restart rules).
Fixed-step semi-implicit Euler, identical to the browser port (sim/propulsion/site/propulsion.js).
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from ..constants import G0, RHO_AIR_SL
from .assumptions import coldgas_assumptions, hover_assumptions, rocket_assumptions
from .coldgas import ColdGasSystem, TankConfig, ThrusterConfig, nozzle, tank_cost
from .gas import GASES
from .rocket import RocketEngine, RocketEngineConfig, engine_mass, engine_rules

RIDER_KG = 90.72


class MissionConfig(BaseModel):
    hover_height_m: float = Field(0.6, ge=0.1, le=5)
    translate_m: float = Field(2.0, ge=0, le=50)
    yaw_deg: float = Field(90.0, ge=-180, le=180)
    hold_s: float = Field(1.0, ge=0, le=600)
    speed_m_s: float = Field(1.0, gt=0, le=10)
    climb_m_s: float = Field(0.6, gt=0, le=5)
    descent_m_s: float = Field(0.4, gt=0, le=3)
    yaw_rate_deg_s: float = Field(45.0, gt=0, le=180)


class HoverConfig(BaseModel):
    propulsion: Literal["coldgas", "rocket"] = "coldgas"
    rider_kg: float = Field(RIDER_KG, ge=0, le=160)
    rider_height_m: float = Field(1.75, ge=1.3, le=2.1)
    deck_length_m: float = Field(1.0, ge=0.5, le=2.5)
    deck_width_m: float = Field(0.5, ge=0.3, le=1.5)
    leg_height_m: float = Field(0.30, ge=0.1, le=1.0)
    thruster_x_m: float = Field(0.42, ge=0.1, le=1.2)
    thruster_y_m: float = Field(0.20, ge=0.05, le=0.7)
    thruster_z_m: float = Field(-0.05, ge=-0.5, le=0.3)
    cant_deg: float = Field(10.0, ge=0, le=30)
    tw_design: float | None = Field(None, ge=0.5, le=4, description="installed thrust / initial weight (None = assumption)")
    # cold gas
    tank: TankConfig = TankConfig(volume_l=9.0, n_tanks=4, pressure_bar=300, tank_class="type3")
    reg_pressure_bar: float = Field(40.0, ge=5, le=300)
    expansion_ratio: float = Field(3.0, ge=1, le=20)
    tank_x_m: float = Field(0.08, ge=-0.5, le=0.5)
    tank_z_m: float = Field(-0.13, ge=-0.5, le=0.5)
    # rocket (black box)
    engine: RocketEngineConfig = RocketEngineConfig(engine_class="monoprop", n_engines=4, thrust_per_engine_n=600.0,
                                                    propellant_kg=30.0)
    auto_thrust: bool = True
    mission: MissionConfig = MissionConfig()
    reserve_s: float = Field(1.5, ge=0, le=60, description="abort to landing when estimated hover time left < this")
    gravity: float = Field(G0, ge=0, le=20)
    drag: bool = True
    start_height_m: float | None = None
    dt: float = Field(0.001, ge=2e-4, le=0.005)
    overrides: dict[str, float] | None = None


# --------------------------------------------------------------------------------------------- small math
def qmul(a, b):
    return [a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3], a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
            a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1], a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0]]


def rot(q, v):
    w, x, y, z = q
    return [(1 - 2 * (y * y + z * z)) * v[0] + 2 * (x * y - w * z) * v[1] + 2 * (x * z + w * y) * v[2],
            2 * (x * y + w * z) * v[0] + (1 - 2 * (x * x + z * z)) * v[1] + 2 * (y * z - w * x) * v[2],
            2 * (x * z - w * y) * v[0] + 2 * (y * z + w * x) * v[1] + (1 - 2 * (x * x + y * y)) * v[2]]


def rotT(q, v):
    return rot([q[0], -q[1], -q[2], -q[3]], v)


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def scl(a, s):
    return [a[0] * s, a[1] * s, a[2] * s]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a):
    return math.sqrt(dot(a, a))


def solve(M, b):
    """Gaussian elimination with partial pivoting (n <= 4); identical in the JS port."""
    n = len(b)
    A = [row[:] + [b[i]] for i, row in enumerate(M)]
    for k in range(n):
        piv = max(range(k, n), key=lambda i: abs(A[i][k]))
        A[k], A[piv] = A[piv], A[k]
        for i in range(k + 1, n):
            f = A[i][k] / A[k][k]
            for j in range(k, n + 1):
                A[i][j] -= f * A[k][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (A[i][n] - sum(A[i][j] * x[j] for j in range(i + 1, n))) / A[i][i]
    return x


def quat_from_euler(yaw, pitch, roll):
    cy, sy, cp, sp, cr, sr = (math.cos(yaw / 2), math.sin(yaw / 2), math.cos(pitch / 2), math.sin(pitch / 2),
                              math.cos(roll / 2), math.sin(roll / 2))
    return [cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy]


# --------------------------------------------------------------------------------------------- the simulator
class HoverSim:
    PHASES = ("ground", "climb", "hover", "translate", "stop", "yaw", "hold", "land", "done")

    def __init__(self, cfg: HoverConfig):
        self.cfg = cfg
        ov = cfg.overrides or {}
        self.vh = {k: ov.get(k, v) for k, v in hover_assumptions().values().items()}
        self.vc = {k: ov.get(k, v) for k, v in coldgas_assumptions().values().items()}
        self.vr = {k: ov.get(k, v) for k, v in rocket_assumptions().values().items()}
        self.cda = ov.get("hover_cda", 0.8) if cfg.drag else 0.0
        self.tw = cfg.tw_design if cfg.tw_design is not None else self.vh["tw_margin"]
        c = cfg
        d = math.radians(c.cant_deg)
        X, Y, Z = c.thruster_x_m, c.thruster_y_m, c.thruster_z_m
        self.r_thr = [[X, Y, Z], [-X, Y, Z], [-X, -Y, Z], [X, -Y, Z]]
        spins = [1, -1, 1, -1]
        self.d_thr = []
        for (x, y, _), s in zip(self.r_thr, spins):
            r = math.hypot(x, y)
            t = [-y / r, x / r, 0.0]
            self.d_thr.append([s * math.sin(d) * t[0], s * math.sin(d) * t[1], math.cos(d)])
        self._size()
        self.reset()

    # ---------------------------------------------------------------- sizing (thrust from the T/W rule)
    def _fixed_parts(self):
        c, v = self.cfg, self.vh
        L, W = c.deck_length_m, c.deck_width_m
        parts = [("deck + structure", v["board_struct_kg"], [0.0, 0.0, 0.0], [L, W, 0.05]),
                 ("avionics", v["avionics_kg"], [-0.15, 0.0, 0.03], [0.2, 0.15, 0.05])]
        if c.rider_kg > 0:
            parts.append(("rider", c.rider_kg, [0.0, 0.0, 0.55 * c.rider_height_m], [0.3, 0.45, c.rider_height_m]))
        return parts

    def _size(self):
        c = self.cfg
        cosd = math.cos(math.radians(c.cant_deg))
        fixed = sum(p[1] for p in self._fixed_parts())
        if c.propulsion == "coldgas":
            thr = ThrusterConfig(n_thrusters=4, throat_diameter_mm=5.0, expansion_ratio=c.expansion_ratio,
                                 regulated=True, reg_pressure_bar=c.reg_pressure_bar)
            probe = ColdGasSystem(c.tank, thr, self.vc)
            m0 = fixed + probe.dry_mass + probe.m0
            F_need = self.tw * m0 * c.gravity / (4 * cosd) if c.gravity > 0 else self.tw * m0 * G0 / (4 * cosd)
            g = GASES[c.tank.gas]
            unit = nozzle(c.reg_pressure_bar * 1e5, c.tank.temperature_k, g, 1e-4, c.expansion_ratio, 101325.0,
                          self.vc["nozzle_cd"], self.vc["nozzle_cf_eff"], 1.0, None)
            At = 1e-4 * F_need / unit.thrust
            thr.throat_diameter_mm = 2000 * math.sqrt(At / math.pi)
            self.thr_cfg = thr
            self.gas = ColdGasSystem(c.tank, thr, self.vc)
            self.F_design = F_need
            self.engines = None
        else:
            ec = c.engine.model_copy()
            if c.auto_thrust:
                F = 500.0
                for _ in range(30):
                    ec.thrust_per_engine_n = F
                    em = engine_mass(ec, self.vr)
                    m0 = fixed + sum(em.values())
                    F = self.tw * m0 * (c.gravity or G0) / (4 * cosd)
                ec.thrust_per_engine_n = F
            self.eng_cfg = ec
            self.rules = engine_rules(ec, self.vr)
            self.engines = [RocketEngine(ec, self.rules) for _ in range(4)]
            self.F_design = ec.thrust_per_engine_n
            self.gas = None

    def parts(self):
        c = self.cfg
        out = list(self._fixed_parts())
        tpos = [c.tank_x_m, 0.0, c.tank_z_m]
        if self.gas:
            out.append(("tanks + valves", self.gas.dry_mass - 4 * self.vc["kg_per_thruster"], tpos, [0.5, 0.4, 0.15]))
            for r in self.r_thr:
                out.append(("thruster", self.vc["kg_per_thruster"], r, [0.08, 0.08, 0.1]))
            out.append(("gas", self.gas.m, tpos, [0.5, 0.4, 0.15]))
        else:
            em = engine_mass(self.eng_cfg, self.vr)
            out.append(("propellant tankage", em["tankage"], tpos, [0.5, 0.4, 0.15]))
            for r in self.r_thr:
                out.append(("engine", em["engines"] / 4, r, [0.1, 0.1, 0.15]))
            out.append(("propellant", self.prop, tpos, [0.5, 0.4, 0.15]))
        return out

    def mass_props(self):
        ps = self.parts()
        m = sum(p[1] for p in ps)
        cg = [sum(p[1] * p[2][i] for p in ps) / m for i in range(3)]
        J = [[0.0] * 3 for _ in range(3)]
        for _, pm, pos, box in ps:
            a, b, cc = box
            d = sub(pos, cg)
            loc = [pm * (b * b + cc * cc) / 12, pm * (a * a + cc * cc) / 12, pm * (a * a + b * b) / 12]
            dd = dot(d, d)
            for i in range(3):
                for k in range(3):
                    J[i][k] += (loc[i] + pm * dd if i == k else 0.0) - pm * d[i] * d[k]
        return m, cg, J

    # ---------------------------------------------------------------- state
    def reset(self):
        c = self.cfg
        self.t = 0.0
        h0 = c.start_height_m if c.start_height_m is not None else c.leg_height_m
        self.pos = [0.0, 0.0, h0]
        self.vel = [0.0, 0.0, 0.0]
        self.q = [1.0, 0.0, 0.0, 0.0]
        self.w = [0.0, 0.0, 0.0]
        self.u = [0.0] * 4
        if self.gas:
            self.gas.reset()
            self.Fmax = [self.F_design] * 4
        else:
            self.prop = c.engine.propellant_kg
            for e in self.engines:
                e.reset()
            self.Fmax = [self.F_design] * 4
        self.phase = "ground"
        self.t_phase = 0.0
        self.ref = [0.0, 0.0, 0.0]          # x, y, yaw
        self.z_ref = None
        self.zint = 0.0
        self.aborted = False
        self.failed = None
        self.airborne = False
        self.ran_dry = False
        self.t_liftoff = None
        self.t_burnout = None
        self.max_tilt = 0.0
        self.impact_v = 0.0
        self.t_rem = float("inf")
        self.n = 0
        self.events: list[tuple[float, str]] = []
        self.impulse = 0.0
        self.used = 0.0
        self.mdot = 0.0
        self.F = [0.0] * 4
        self.tel: dict = {}
        self.contact = True
        self.manual_land = False

    def propellant(self) -> float:
        return self.gas.m if self.gas else self.prop

    def _event(self, txt):
        self.events.append((round(self.t, 3), txt))

    # ---------------------------------------------------------------- autopilot
    def _mission(self, dt, z_cg_ground, vz):
        c, M = self.cfg, self.cfg.mission
        self.t_phase += dt
        ph = self.phase
        h_ref_cg = None
        if ph == "ground":
            if self.t >= 0.5:
                self._set_phase("climb")
        elif ph == "climb":
            if self.z_ref >= z_cg_ground + M.hover_height_m - 1e-3 and self.t_phase > 0.3:
                self._set_phase("hover")
        elif ph == "hover" and self.t_phase >= M.hold_s:
            self._set_phase("translate")
        elif ph == "translate" and self.ref[0] >= M.translate_m - 1e-9:
            self._set_phase("stop")
        elif ph == "stop" and self.t_phase >= M.hold_s:
            self._set_phase("yaw")
        elif ph == "yaw" and abs(self.ref[2] - math.radians(M.yaw_deg)) < 1e-9:
            self._set_phase("hold")
        elif ph == "hold" and self.t_phase >= M.hold_s:
            self._set_phase("land")
        elif ph == "land" and self.contact and self.t_phase > 0.3 and abs(vz) < 0.3:
            self._set_phase("done")
            self.airborne = False
        if (c.reserve_s > 0 and self.phase in ("climb", "hover", "translate", "stop", "yaw", "hold")
                and self.t_rem < c.reserve_s and not self.aborted):
            self.aborted = True
            if not self.airborne:
                self.failed = "cannot lift off: thrust below weight"
                self._event("CANNOT LIFT OFF")
                self._set_phase("done")
            else:
                self._event(f"propellant reserve reached ({self.t_rem:.1f} s left): aborting to land")
                self._set_phase("land")
        if self.manual_land and self.phase in ("climb", "hover", "translate", "stop", "yaw", "hold"):
            self.manual_land = False
            self.aborted = True
            self._event("pilot: land now")
            self._set_phase("land")
        ph = self.phase
        if ph == "climb":
            self.z_ref = min(self.z_ref + M.climb_m_s * dt, z_cg_ground + M.hover_height_m)
        elif ph == "translate":
            self.ref[0] = min(self.ref[0] + M.speed_m_s * dt, M.translate_m)
        elif ph == "yaw":
            tgt = math.radians(M.yaw_deg)
            step = math.radians(M.yaw_rate_deg_s) * dt
            self.ref[2] = tgt if abs(tgt - self.ref[2]) <= step else self.ref[2] + math.copysign(step, tgt - self.ref[2])
        elif ph == "land":
            self.z_ref -= M.descent_m_s * dt
        return h_ref_cg

    def _set_phase(self, ph):
        self.phase = ph
        self.t_phase = 0.0
        self._event(ph)

    def _control(self, dt, m, cg, J, cgW, vcg):
        c = self.cfg
        g = c.gravity
        R = self.q
        if self.phase in ("ground", "done"):
            self.zint = 0.0
            return [0.0] * 4, False
        x_ref, y_ref, yaw_ref = self.ref
        # position loop (world)
        ex, ey, ez = x_ref - cgW[0], y_ref - cgW[1], self.z_ref - cgW[2]
        vxr = c.mission.speed_m_s if (self.phase == "translate") else 0.0
        vzr = c.mission.climb_m_s if self.phase == "climb" else (-c.mission.descent_m_s if self.phase == "land" else 0.0)
        ax = 1.2 * ex + 1.8 * (vxr - vcg[0])
        ay = 1.2 * ey + 1.8 * (0.0 - vcg[1])
        amax = 0.25 * G0
        ah = math.hypot(ax, ay)
        if ah > amax:
            ax, ay = ax * amax / ah, ay * amax / ah
        if self.airborne:
            self.zint = max(-1.0, min(1.0, self.zint + ez * dt))
        az = 4.0 * ez + 3.5 * (vzr - vcg[2]) + 1.0 * self.zint
        # desired thrust direction -> roll/pitch in the yaw frame
        cy, sy = math.cos(yaw_ref), math.sin(yaw_ref)
        axb, ayb = cy * ax + sy * ay, -sy * ax + cy * ay
        gz = max(g + az, 0.2 * (g or G0))
        pitch_ref = max(-0.3, min(0.3, math.atan2(axb, gz)))
        roll_ref = max(-0.3, min(0.3, -math.atan2(ayb, gz)))
        qd = quat_from_euler(yaw_ref, pitch_ref, roll_ref)
        qe = qmul([R[0], -R[1], -R[2], -R[3]], qd)
        s = 1.0 if qe[0] >= 0 else -1.0
        e = [2 * s * qe[1], 2 * s * qe[2], 2 * s * qe[3]]
        alpha = [25.0 * e[i] - 9.0 * self.w[i] for i in range(3)]
        alpha[2] = 8.0 * e[2] - 5.0 * self.w[2]
        Mb = [sum(J[i][k] * alpha[k] for k in range(3)) for i in range(3)]
        bz = rot(R, [0.0, 0.0, 1.0])[2]
        # collective along body z, sized for the vertical acceleration demand
        T = m * (g + az) / max(bz, 0.5)
        T = max(T, 0.0)
        # allocation: rows = [sum Fz_body, Mx, My, Mz] about the CG
        B = [[0.0] * 4 for _ in range(4)]
        for i in range(4):
            dvec = self.d_thr[i]
            r = sub(self.r_thr[i], cg)
            mom = cross(r, dvec)
            B[0][i], B[1][i], B[2][i], B[3][i] = dvec[2], mom[0], mom[1], mom[2]
        col = solve(B, [T, 0.0, 0.0, 0.0])
        dif = solve(B, [0.0, Mb[0], Mb[1], Mb[2]])
        Fmin = [0.0] * 4
        Fmax = self.Fmax[:]
        if self.engines:
            for i, e_ in enumerate(self.engines):
                if e_.burned_out or (not e_.running and e_.starts >= e_.r.max_starts):
                    Fmax[i] = 0.0
                else:
                    Fmin[i] = self.rules.min_throttle * self.F_design
        sd = 1.0
        for _ in range(12):
            lo, hi = -1e18, 1e18
            for i in range(4):
                ci, di = col[i], sd * dif[i]
                if ci > 1e-9:
                    lo = max(lo, (Fmin[i] - di) / ci)
                    hi = min(hi, (Fmax[i] - di) / ci)
            if lo <= hi:
                break
            sd *= 0.6
        k = min(max(1.0, lo), hi) if lo <= hi else 0.0
        F = [min(max(k * col[i] + sd * dif[i], Fmin[i]), Fmax[i]) for i in range(4)]
        return [F[i] / self.Fmax[i] if self.Fmax[i] > 0 else 0.0 for i in range(4)], True

    # ---------------------------------------------------------------- one step
    def step(self, dt: float) -> dict:
        c = self.cfg
        g = c.gravity
        m, cg, J = self.mass_props()
        cgW = add(self.pos, rot(self.q, cg))
        wW = rot(self.q, self.w)
        vcg = add(self.vel, cross(wW, rot(self.q, cg)))
        z_cg_ground = cg[2] + c.leg_height_m
        if self.z_ref is None:
            self.z_ref = cgW[2]
        self._mission(dt, z_cg_ground, vcg[2])
        u_cmd, active = self._control(dt, m, cg, J, cgW, vcg)
        # ---- propulsion
        if self.gas:
            for i in range(4):
                self.u[i] += (u_cmd[i] - self.u[i]) * min(1.0, dt / 0.03)
            st = self.gas.step_multi(dt, self.u)
            F, mdot = st["F"], st["mdot_total"]
            # available full-throttle thrust per thruster at the current tank state (for the allocator)
            full = self.thrust_at_full(st)
            self.Fmax = [full] * 4
            dry = (not st["valid"]) or full < 0.02 * self.F_design
            pt, Tt = st["p_tank"], st["T_tank"]
        else:
            F = [0.0] * 4
            mdot = 0.0
            for i, e in enumerate(self.engines):
                if active and u_cmd[i] > 0:
                    e.command(u_cmd[i])
                elif not active:
                    e.command(0.0)
                Fi, mi = e.step(dt, self.prop > 1e-6)
                F[i] = Fi
                mdot += mi
            if mdot * dt > self.prop:
                k = self.prop / (mdot * dt)
                F = [f * k for f in F]
                mdot = self.prop / dt
            self.prop -= mdot * dt
            dry = self.prop <= 1e-6
            pt, Tt = 0.0, 0.0
        if dry and self.airborne and not self.contact and not self.ran_dry:
            self.ran_dry = True
            self.t_burnout = self.t
            self._event("PROPELLANT EXHAUSTED in flight")
        self.F, self.mdot = F, mdot
        self.impulse += sum(F) * dt
        self.used += mdot * dt
        # ---- forces and torques (world, torques about the CG)
        Fw = [0.0, 0.0, -m * g]
        Mw = [0.0, 0.0, 0.0]
        for i in range(4):
            f = rot(self.q, scl(self.d_thr[i], F[i]))
            r = rot(self.q, sub(self.r_thr[i], cg))
            Fw = add(Fw, f)
            Mw = add(Mw, cross(r, f))
        sp = norm(vcg)
        if self.cda > 0:
            Fw = add(Fw, scl(vcg, -0.5 * RHO_AIR_SL * self.cda * sp))
        Mw = add(Mw, scl(wW, -5.0))
        # ---- ground contact: feet + deck corners
        L2, W2 = c.deck_length_m / 2, c.deck_width_m / 2
        fx, fy = 0.8 * L2, 0.8 * W2
        pts = [[fx, fy, -c.leg_height_m], [-fx, fy, -c.leg_height_m], [-fx, -fy, -c.leg_height_m], [fx, -fy, -c.leg_height_m],
               [L2, W2, 0.0], [-L2, W2, 0.0], [-L2, -W2, 0.0], [L2, -W2, 0.0]]
        contact = False
        for k in range(8):
            rb = sub(pts[k], cg)
            rW = rot(self.q, rb)
            p = add(cgW, rW)
            if p[2] < 0:
                vP = add(vcg, cross(wW, rW))
                fn = max(0.0, -2.0e5 * p[2] - 4000.0 * vP[2])
                vt = [vP[0], vP[1], 0.0]
                vtn = norm(vt)
                ft = scl(vt, -min(0.6 * fn, 3000.0 * vtn) / vtn) if vtn > 1e-6 else [0.0, 0.0, 0.0]
                f = [ft[0], ft[1], fn]
                Fw = add(Fw, f)
                Mw = add(Mw, cross(rW, f))
                if k < 4:
                    contact = True
                if vP[2] < -self.impact_v and self.ran_dry:
                    self.impact_v = -vP[2]
        if self.airborne and contact and self.ran_dry and not self.failed:
            self.failed = f"fell after running dry: hit the ground at {self.impact_v:.1f} m/s"
            self._event("IMPACT " + self.failed)
        self.contact = contact
        if not contact and cgW[2] > z_cg_ground + 0.05 and not self.airborne:
            self.airborne = True
            self.t_liftoff = self.t
            self._event("lift-off")
        # ---- integrate (instantaneous rigid body about the CG; deck origin integrated)
        a_cg = scl(Fw, 1.0 / m)
        Mb = rotT(self.q, Mw)
        Jw = [dot(J[0], self.w), dot(J[1], self.w), dot(J[2], self.w)]
        wdot = solve(J, sub(Mb, cross(self.w, Jw)))
        a_o = sub(a_cg, rot(self.q, add(cross(wdot, cg), cross(self.w, cross(self.w, cg)))))
        self.vel = add(self.vel, scl(a_o, dt))
        self.pos = add(self.pos, scl(self.vel, dt))
        self.w = add(self.w, scl(wdot, dt))
        dq = qmul(self.q, [0.0, self.w[0], self.w[1], self.w[2]])
        self.q = [self.q[i] + 0.5 * dt * dq[i] for i in range(4)]
        qn = math.sqrt(sum(x * x for x in self.q))
        self.q = [x / qn for x in self.q]
        self.t += dt
        self.n += 1
        # ---- bookkeeping
        up = rot(self.q, [0.0, 0.0, 1.0])
        tilt = math.acos(max(-1.0, min(1.0, up[2])))
        self.max_tilt = max(self.max_tilt, tilt if self.airborne else 0.0)
        if tilt > math.radians(60) and not self.failed:
            self.failed = "lost attitude control (tilt > 60 deg)"
            self._event("LOST CONTROL")
        if self.phase == "climb" and self.t_phase > 3.0 + 2 * c.mission.hover_height_m / c.mission.climb_m_s and not self.airborne \
                and not self.failed:
            self.failed = "cannot lift off: thrust below weight"
            self._event("CANNOT LIFT OFF")
            self._set_phase("done")
        if self.n % 50 == 0:
            self.t_rem = self.time_left(mdot)
        fwd = rot(self.q, [1.0, 0.0, 0.0])
        self.tel = {"t": self.t, "pos": self.pos[:], "q": self.q[:], "vel": vcg[:], "w": self.w[:], "F": list(F),
                    "mdot": mdot, "prop": self.propellant(), "m": m, "cg": cg[:], "cgW": cgW[:], "phase": self.phase,
                    "z": cgW[2] - z_cg_ground, "tilt": tilt, "yaw": math.atan2(fwd[1], fwd[0]), "p_tank": pt,
                    "T_tank": Tt, "t_rem": self.t_rem, "contact": contact, "failed": self.failed,
                    "x_ref": self.ref[0], "z_ref": self.z_ref - z_cg_ground}
        return self.tel

    def thrust_at_full(self, st) -> float:
        g = GASES[self.cfg.tank.gas]
        if not st["valid"] or st["pmax"] <= 0:
            return 0.0
        nz = nozzle(st["pmax"], st["T_tank"], g, self.thr_cfg.throat_area, self.cfg.expansion_ratio, 101325.0,
                    self.vc["nozzle_cd"], self.vc["nozzle_cf_eff"], 1.0, self.gas.pe_ratio)
        return nz.thrust

    def time_left(self, mdot_now: float) -> float:
        """Hover time left at the current consumption, counting only propellant usable at full regulated thrust."""
        m, _, _ = self.mass_props()
        cosd = math.cos(math.radians(self.cfg.cant_deg))
        if self.gas:
            p, T, _, ok = self.gas.state()
            if not ok:
                return 0.0
            p_res = (self.cfg.reg_pressure_bar + self.vc["reg_dropout_bar"]) * 1e5
            if p <= p_res:
                return 0.0
            rho_res = (self.gas.tab.rho_from_pT(p_res, T) if self.gas.tab else p_res / (GASES[self.cfg.tank.gas].R * T))
            usable = self.gas.m - rho_res * self.gas.V
            st = self.gas.thrust_state(1.0)
            isp = st["isp"] if st["isp"] > 0 else 50.0
        else:
            usable = self.prop
            isp = self.rules.isp_s
        md = m * self.cfg.gravity / cosd / (isp * G0) if self.cfg.gravity > 0 else 1e-9
        return usable / max(md, 1e-9)

    # ---------------------------------------------------------------- run
    def run(self, t_end: float = 60.0, record_every: int = 20) -> dict:
        self.reset()
        rec = {k: [] for k in ("t", "pos", "q", "vel", "F", "prop", "m", "cg", "phase", "z", "tilt", "p_tank", "T_tank",
                               "t_rem", "mdot")}
        while self.t < t_end - 1e-12:
            tel = self.step(self.cfg.dt)
            if (self.n - 1) % record_every == 0:
                for k in rec:
                    rec[k].append(tel[k])
            if self.phase == "done" and self.t_phase > 1.0:
                break
            if self.failed and self.contact and self.t > (self.t_burnout or 0) + 2.0 and self.ran_dry:
                break
        rec["events"] = self.events
        return rec


# --------------------------------------------------------------------------------------------- evaluation
class HoverResult(BaseModel):
    propulsion: str
    config: HoverConfig
    gross_mass_kg: float
    dry_mass_kg: float
    propellant_kg: float
    propulsion_mass_kg: float
    installed_thrust_n: float
    thrust_to_weight: float
    hover_thrust_n: float
    isp_s: float
    hover_time_analytic_s: float
    hover_time_upper_bound_s: float
    flight_time_s: float
    mission_completed: bool
    aborted: bool
    failed: str | None
    impact_speed_m_s: float
    max_tilt_deg: float
    propellant_used_kg: float
    impulse_ns: float
    cg_shift_mm: float
    events: list
    hazards: dict
    cost: dict
    warnings: list[str]
    trace: dict | None = None


def evaluate_hover(cfg: HoverConfig, run: bool = True, t_end: float = 90.0, keep_trace: bool = False) -> HoverResult:
    from .coldgas import energy_report
    from .hazards import combine_spl, jet_hazard
    from .rocket import rocket_cost

    sim = HoverSim(cfg)
    m0, cg0, _ = sim.mass_props()
    cosd = math.cos(math.radians(cfg.cant_deg))
    W0 = m0 * G0
    hazards: dict = {}
    warnings: list[str] = []
    if sim.gas:
        prop0 = sim.gas.m0
        st = sim.gas.thrust_state(1.0)
        isp = st["isp"]
        p_res = (cfg.reg_pressure_bar + sim.vc["reg_dropout_bar"]) * 1e5
        from .gas import density
        usable = prop0 - density(cfg.tank.gas, p_res, cfg.tank.temperature_k, cfg.tank.real_gas) * sim.gas.V
        prop_mass = sim.gas.dry_mass
        er = energy_report(cfg.tank, vals=sim.vc)
        jh = jet_hazard(sim.F_design, st["ue"], st["Te"], st["mdot"] / 4, sim.vr["acoustic_eff_coldgas"])
        hazards = {"tank": er.model_dump(), "jet": jh.model_dump(),
                   "spl_4_jets_1m_db": combine_spl([jh.spl_at_1m_db] * 4)}
        cost = {"tanks_usd": tank_cost(cfg.tank, sim.vc),
                "valves_thrusters_usd": sim.vc["cost_valves_base"] + 4 * sim.vc["cost_per_thruster"],
                "refill_usd": er.refill_cost_usd}
        warnings.append(f"{er.burst_energy_kj / 1e3:.1f} MJ of compressed gas on board ({er.tnt_equiv_kg:.1f} kg TNT eq.): "
                        f"1 psi to {er.blast_radius_1psi_m:.0f} m if a vessel fails")
        warnings.append(f"exhaust {st['Te'] - 273.15:.0f} C at the nozzle exit; ground outwash > 15 m/s within "
                        f"{jh.ground_outwash_zone_m:.1f} m of each jet")
    else:
        prop0 = cfg.engine.propellant_kg
        isp = sim.rules.isp_s
        usable = prop0
        em = engine_mass(sim.eng_cfg, sim.vr)
        prop_mass = em["engines"] + em["tankage"]
        jh = jet_hazard(sim.F_design, isp * G0, sim.rules.exit_temp_k, sim.F_design / (isp * G0), sim.vr["acoustic_eff"])
        hazards = {"jet": jh.model_dump(), "spl_4_jets_1m_db": combine_spl([jh.spl_at_1m_db] * 4),
                   "spl_4_jets_rider_db": combine_spl([jh.spl_rider_db] * 4), "rules": sim.rules.model_dump()}
        rc = rocket_cost(sim.eng_cfg, sim.vr)
        cost = {"engines_usd": rc["engines_usd"], "propellant_per_flight_usd": rc["propellant_per_flight_usd"]}
        warnings.append(f"exhaust ~{sim.rules.exit_temp_k - 273:.0f} C at {isp * G0:.0f} m/s: burns/ignition hazard "
                        f"{jh.temperature_zone_m:.1f} m along each jet, ground outwash > 15 m/s to {jh.ground_outwash_zone_m:.1f} m")
        warnings.append(f"noise ~{hazards['spl_4_jets_rider_db']:.0f} dB at the rider's ears (4 jets): hearing damage "
                        f"(>140 dB peak limit within {jh.distance_140db_m:.1f} m)")
        if sim.rules.profile == "fixed":
            warnings.append("solid-class motor: no throttle, cannot be stopped - hover control is impossible")
        if sim.rules.min_throttle > 1 / sim.tw * cosd:
            warnings.append(f"minimum throttle {sim.rules.min_throttle:.0%} exceeds the hover setting: cannot hover")
    cost.update(avionics_usd=sim.vh["avionics_cost"], structure_usd=sim.vh["struct_cost"])
    cost["total_hardware_usd"] = sum(v for k, v in cost.items() if k not in ("refill_usd", "propellant_per_flight_usd"))
    m_end = m0 - usable
    t_an = isp * cosd * math.log(m0 / m_end) if usable > 0 else 0.0
    # upper bound with infinite tank: dry mass grows with propellant (k = tank kg per kg propellant)
    if sim.gas:
        k = sim.gas.m_wall / max(prop0, 1e-9)
        m_fix = m0 - prop0 - sim.gas.m_wall
    else:
        k = sim.vr["tankage_fraction"]
        m_fix = m0 - prop0 - k * prop0
    t_ub = isp * cosd * math.log((1 + k) / k) if k > 0 else float("inf")
    del m_fix
    res = dict(flight_time_s=0.0, mission_completed=False, aborted=False, failed=None, impact_speed_m_s=0.0,
               max_tilt_deg=0.0, propellant_used_kg=0.0, impulse_ns=0.0, cg_shift_mm=0.0, events=[])
    trace = None
    if run:
        rec = sim.run(t_end)
        t_off = sim.t_liftoff
        t_end_fl = sim.t if sim.phase != "done" else sim.t - sim.t_phase
        res.update(flight_time_s=(t_end_fl - t_off) if t_off is not None else 0.0,
                   mission_completed=sim.phase == "done" and not sim.aborted and not sim.failed,
                   aborted=sim.aborted, failed=sim.failed, impact_speed_m_s=sim.impact_v,
                   max_tilt_deg=math.degrees(sim.max_tilt), propellant_used_kg=sim.used, impulse_ns=sim.impulse,
                   events=sim.events)
        m1, cg1, _ = sim.mass_props()
        res["cg_shift_mm"] = 1000 * math.dist(cg0, cg1)
        if keep_trace:
            trace = {k: rec[k] for k in ("t", "pos", "z", "tilt", "prop", "phase", "t_rem")}
            trace["F_total"] = [sum(f) for f in rec["F"]]
    if sim.failed:
        warnings.insert(0, "FAILED: " + sim.failed)
    elif res["aborted"]:
        warnings.insert(0, "mission aborted on propellant reserve")
    return HoverResult(propulsion=cfg.propulsion, config=cfg, gross_mass_kg=m0, dry_mass_kg=m0 - prop0,
                       propellant_kg=prop0, propulsion_mass_kg=prop_mass + prop0,
                       installed_thrust_n=4 * sim.F_design, thrust_to_weight=4 * sim.F_design * cosd / W0,
                       hover_thrust_n=W0 / cosd, isp_s=isp, hover_time_analytic_s=t_an, hover_time_upper_bound_s=t_ub,
                       hazards=hazards, cost=cost, warnings=warnings, trace=trace, **res)


def write_hover_references(REF) -> None:
    """Python fixed-step hover runs that the JS port must reproduce (ROM gas table)."""
    import json
    cases = {
        "hover_coldgas": HoverConfig(tank=TankConfig(volume_l=9.0, n_tanks=4, pressure_bar=300, tank_class="type3",
                                                     rom_table=True)),
        "hover_rocket": HoverConfig(propulsion="rocket"),
        "hover_rocket_biprop": HoverConfig(propulsion="rocket", engine=RocketEngineConfig(engine_class="biprop",
                                                                                          propellant_kg=20)),
    }
    for name, cfg in cases.items():
        sim = HoverSim(cfg)
        rec = sim.run(40.0, record_every=50)
        rec["t_rem"] = [x if math.isfinite(x) else 1e9 for x in rec["t_rem"]]
        doc = {"config": json.loads(cfg.model_dump_json()), "t_end": 40.0, "record_every": 50, "trace": rec,
               "F_design": sim.F_design}
        (REF / f"{name}.json").write_text(json.dumps(doc, default=float), encoding="utf-8")
