"""Cold-gas boosted wheeled skateboard (and the plain electric skateboard it is compared with).

Planar model, x forward along a straight track, z up. Rear axle contact = x 0, front axle contact = x L (wheelbase).
  Translation:   m dv/dt = Tx + F_drive - D - R - B,     m = rider + board + e-drive + cold-gas dry + gas (variable)
      D = 1/2 rho CdA v|v|,  R = Crr (m g - Tz),  F_drive <= min(F_torque, eta P_peak / v) and <= mu N_rear (rear hubs),
      B = brake command x min(B_max, mu N_total) (regenerative part up to the motor force limit, rest friction).
  Pitch / tipping (quasi-static while both axles are loaded): moments about the rear contact with d'Alembert -m a at
      the CG give N_front; N_front < 0 -> wheelie (rotate about the rear contact), N_rear < 0 -> nose-over (rotate
      about the front contact). Thrust above the CG loads the nose; below it unloads the nose.
  Rider balance: inverted pendulum (CoM height l above the deck) with ankle/hip torque limited by the centre-of-pressure
      levers (heel / toe), lagged perception of the board acceleration, PD postural control toward the lean
      theta_ref = atan(a/g). Exceeding the lever limits -> the rider falls (sudden boosts are the danger).
  Cold-gas boost: rear-facing thruster(s) fed from the tank through a regulator (coldgas.ColdGasSystem).
  Energy ledger (ground frame) must close:  battery + jet KE (vehicle frame) + initial KE
                                           = final KE + drag + rolling + brake heat + motor losses + residual jet KE
                                             - regen stored.
Fixed step semi-implicit Euler (identical to sim/propulsion/site/propulsion.js). Units SI.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from ..constants import G0, RHO_AIR_SL
from .assumptions import coldgas_assumptions, skateboard_assumptions
from .coldgas import ColdGasSystem, TankConfig, ThrusterConfig, energy_report, tank_cost
from .gas import real_gas

RIDER_KG = 90.72


class SkateConfig(BaseModel):
    rider_kg: float = Field(RIDER_KG, ge=30, le=160)
    rider_height_m: float = Field(1.75, ge=1.3, le=2.1)
    board_kg: float = Field(4.5, ge=1, le=20)
    wheelbase_m: float = Field(0.60, ge=0.3, le=1.2)
    deck_height_m: float = Field(0.10, ge=0.05, le=0.3)
    stance: Literal["upright", "crouch"] = "upright"
    electric: bool = True
    coldgas: bool = True
    tank: TankConfig = TankConfig(volume_l=6.8, pressure_bar=300, tank_class="type3")
    thruster: ThrusterConfig = ThrusterConfig(n_thrusters=1, throat_diameter_mm=6.0, expansion_ratio=2.0,
                                              regulated=True, reg_pressure_bar=30)
    thrust_height_m: float = Field(0.15, ge=0.03, le=1.6, description="thrust line height above ground")
    thrust_angle_deg: float = Field(0.0, ge=-20, le=45, description="thrust tilted upward")
    tank_x_m: float = Field(-0.05, ge=-0.4, le=1.2, description="tank centre, from the rear axle")
    tank_h_m: float = Field(0.17, ge=0.05, le=1.6, description="tank centre height above ground")
    boost_ramp_s: float = Field(0.4, ge=0.0, le=3.0, description="valve opening ramp")
    throttle_ramp_s: float = Field(1.0, ge=0.0, le=5.0, description="ESC acceleration ramp 0 -> full throttle")
    brake_ramp_s: float = Field(0.6, ge=0.0, le=5.0, description="brake application ramp 0 -> full")
    rider_anticipates: bool = True       # rider leans in when they command the boost (feed-forward)
    deadman: bool = True                 # thrust cut when the rider leaves the board
    dt: float = Field(0.001, ge=1e-4, le=0.01)
    overrides: dict[str, float] | None = None


class Controls(BaseModel):
    throttle: float = 0.0      # wheel drive 0..1
    boost: bool = False
    brake: float = 0.0         # 0..1


Scenario = list[tuple[float, Controls]]


def default_scenario(boost: bool = True) -> Scenario:
    """Accelerate on wheels, boost, coast, brake to a stop."""
    return [(0.0, Controls(throttle=1.0)),
            (3.0, Controls(throttle=1.0, boost=boost)),
            (13.0, Controls(throttle=0.0)),
            (17.0, Controls(brake=0.3))]


class SkateSim:
    def __init__(self, cfg: SkateConfig):
        self.cfg = cfg
        ov = cfg.overrides or {}
        sk = skateboard_assumptions().values()
        cg = coldgas_assumptions().values()
        self.v_sk = {k: ov.get(k, v) for k, v in sk.items()}
        self.v_cg = {k: ov.get(k, v) for k, v in cg.items()}
        self.gas_sys = ColdGasSystem(cfg.tank, cfg.thruster, self.v_cg) if cfg.coldgas else None
        self.reset()

    # -------------------------------------------------------------------------- mass properties
    def parts(self):
        c, v = self.cfg, self.v_sk
        L = c.wheelbase_m
        out = [("board", c.board_kg, L / 2, c.deck_height_m - 0.03)]
        if c.electric:
            out.append(("hub motors", 2.0, 0.0, 0.045))
            out.append(("battery", v["batt_wh"] / v["batt_wh_per_kg"], L / 2, c.deck_height_m - 0.04))
        if self.gas_sys:
            out.append(("cold-gas dry", self.gas_sys.dry_mass, c.tank_x_m, c.tank_h_m))
            out.append(("gas", self.gas_sys.m, c.tank_x_m, c.tank_h_m))
        if self.rider_on:
            l = self.l
            out.append(("rider", c.rider_kg, L / 2 + l * math.sin(self.theta), c.deck_height_m + l * math.cos(self.theta)))
        return out

    def mass_props(self):
        ps = self.parts()
        m = sum(p[1] for p in ps)
        x = sum(p[1] * p[2] for p in ps) / m
        z = sum(p[1] * p[3] for p in ps) / m
        return m, x, z, ps

    def reset(self):
        c = self.cfg
        self.t = 0.0
        self.x = 0.0
        self.v = 0.0
        self.a = 0.0
        self.l = 0.55 * c.rider_height_m          # rider CoM height above the ankles (Winter: 0.55 H)
        self.theta = 0.0                          # rider lean (forward +)
        self.omega = 0.0
        self.a_perc = 0.0
        self.rider_on = True
        self.rider_x = None
        self.rider_v = 0.0
        self.phi = 0.0                            # board pitch (nose up +), only in wheelie / nose-over mode
        self.phid = 0.0
        self.mode = "rolling"                     # rolling | wheelie | noseover | crashed
        self.valve = 0.0
        self.thr = 0.0
        self.brk = 0.0
        self.T_full = self.gas_sys.max_thrust() if self.gas_sys else 0.0
        self.batt_j = self.v_sk["batt_wh"] * 3600 if c.electric else 0.0
        if self.gas_sys:
            self.gas_sys.reset()
        self.ctl = Controls()
        self.events: list[tuple[float, str]] = []
        self.flags = {"rider_fell": False, "wheelie": False, "noseover": False, "wheelspin": False, "skid": False}
        m, _, _, _ = self.mass_props()
        self.L = {"batt_out": 0.0, "regen_in": 0.0, "jet_ke": 0.0, "ke0": 0.0, "drag": 0.0, "roll": 0.0,
                  "brake_heat": 0.0, "motor_loss": 0.0, "jet_residual": 0.0, "rider_ke_lost": 0.0,
                  "thrust_work": 0.0, "drive_work": 0.0, "gas_used": 0.0}
        self.exergy0 = self._exergy()
        self.tel = {}

    def _exergy(self) -> float:
        if not self.gas_sys:
            return 0.0
        p, T, _, _ = self.gas_sys.state()
        tab = real_gas(self.cfg.tank.gas, self.cfg.tank.rom_table)
        try:
            return self.gas_sys.m * tab.closed_exergy(max(p, 1.2e5), T)
        except ValueError:
            return 0.0

    def kinetic(self, m):
        return 0.5 * m * self.v * self.v

    # -------------------------------------------------------------------------- one step
    def step(self, dt: float) -> dict:
        c, vs = self.cfg, self.v_sk
        ctl = self.ctl
        m, xc, zc, _ = self.mass_props()
        W = m * G0
        L = c.wheelbase_m
        mu = vs["mu"]

        # ---- cold-gas valve (ramped) and thrust
        want = 1.0 if (ctl.boost and (self.rider_on or not c.deadman)) else 0.0
        if c.boost_ramp_s > 0:
            self.valve += max(-dt / 0.05, min(dt / c.boost_ramp_s, want - self.valve))
        else:
            self.valve = want
        if c.throttle_ramp_s > 0:
            self.thr += max(-dt / 0.1, min(dt / c.throttle_ramp_s, ctl.throttle - self.thr))
        else:
            self.thr = ctl.throttle
        if c.brake_ramp_s > 0:
            self.brk += max(-dt / 0.1, min(dt / c.brake_ramp_s, ctl.brake - self.brk))
        else:
            self.brk = ctl.brake
        T = mdot = 0.0
        gas_st = None
        if self.gas_sys:
            gas_st = self.gas_sys.step(dt, self.valve)
            T, mdot = gas_st["thrust"], gas_st["mdot_used"]
            if self.valve > 0.5:
                self.T_full = T / self.valve
        ang = math.radians(c.thrust_angle_deg) + self.phi
        Tx, Tz = T * math.cos(ang), T * math.sin(ang)
        N_tot = max(W - Tz, 0.0)

        # ---- resistive forces
        v = self.v
        cda = vs["cda_upright"] if c.stance == "upright" else vs["cda_crouch"]
        if not self.rider_on:
            cda = 0.05
        D = 0.5 * RHO_AIR_SL * cda * v * abs(v)
        R = vs["crr"] * N_tot if v > 1e-6 else 0.0

        # ---- wheel drive (rear hub motors), power and torque limited, taper to the electric top speed
        F_drive_req = F_drive_full = 0.0
        if c.electric and self.batt_j > 0 and self.mode == "rolling":
            p_mech = 2 * vs["motor_peak_w"] * vs["drive_eff"]
            taper = min(1.0, max(0.0, (vs["top_speed_m_s"] - v) / (0.1 * vs["top_speed_m_s"])))
            F_drive_full = min(vs["wheel_force_max_n"], p_mech / max(v, 0.5)) * taper
            F_drive_req = self.thr * F_drive_full
        # ---- brake: regen up to the motor force limit, friction for the rest; total limited by traction
        B_req = 0.0
        if self.brk > 0 and v > 1e-6:
            B_req = self.brk * mu * N_tot

        def load_split(a, F_rear_ground_x):
            # moments about the rear contact (nose-up +):  N_f L - W x_cg + m a z_cg - Tx h_t + Tz x_t + D h_d = 0
            h_t = c.thrust_height_m
            x_t = c.tank_x_m - 0.1
            h_d = c.deck_height_m + 0.55 * self.l if self.rider_on else c.deck_height_m
            Nf = (W * xc - m * a * zc + Tx * h_t - Tz * x_t - D * h_d) / L
            return Nf, N_tot - Nf

        F_drive = F_drive_req
        a = (Tx + F_drive - D - R - B_req) / m
        Nf, Nr = load_split(a, F_drive)
        if F_drive > mu * max(Nr, 0.0):
            F_drive = 0.9 * mu * max(Nr, 0.0)
            self.flags["wheelspin"] = True
        B = min(B_req, mu * N_tot)
        if B_req > mu * N_tot * 0.999 and B_req > 0:
            self.flags["skid"] = True
        a = (Tx + F_drive - D - R - B) / m
        Nf, Nr = load_split(a, F_drive)

        # ---- pitch modes
        if self.mode == "rolling":
            if Nf < 0:
                self.mode = "wheelie"; self._event("wheelie"); self.flags["wheelie"] = True
            elif Nr < 0:
                self.mode = "noseover"; self._event("nose-over"); self.flags["noseover"] = True
        if self.mode in ("wheelie", "noseover"):
            piv = 0.0 if self.mode == "wheelie" else L
            I = sum(pm * ((px - piv) ** 2 + pz ** 2) for _, pm, px, pz in self.parts()) + (
                c.rider_kg * 0.08 if self.rider_on else 0.0)
            cph, sph = math.cos(self.phi), math.sin(self.phi)
            rx, rz = (xc - piv) * cph - zc * sph, (xc - piv) * sph + zc * cph
            tx, tz = (c.tank_x_m - 0.1 - piv) * cph - c.thrust_height_m * sph, (c.tank_x_m - 0.1 - piv) * sph + c.thrust_height_m * cph
            M = -W * rx + m * a * rz + (tx * Tz - tz * Tx) + D * (c.deck_height_m + 0.5)
            self.phid += M / I * dt
            self.phi += self.phid * dt
            if (self.mode == "wheelie" and self.phi <= 0) or (self.mode == "noseover" and self.phi >= 0):
                self.phi = 0.0; self.phid = 0.0; self.mode = "rolling"
            elif abs(self.phi) > (0.45 if self.mode == "wheelie" else 0.15):
                self.events.append((self.t, "loop-out" if self.mode == "wheelie" else "nose-dive crash"))
                self.mode = "crashed"
                self._rider_falls("pitched off the board")
        if self.mode == "crashed":
            # board scraping on its tail/nose: sliding friction on the whole weight
            B = max(B, 0.5 * N_tot) if v > 0 else 0.0
            F_drive = 0.0
            a = (Tx - D - R - B) / m

        # ---- rider balance (inverted pendulum on the deck)
        if self.rider_on:
            mr, l = c.rider_kg, self.l
            self.a_perc += (a - self.a_perc) * min(1.0, dt / vs["rider_lag_s"])
            a_ff = self.a_perc
            if c.rider_anticipates:
                # the rider commands the board, so they lean for the acceleration they asked for (feed-forward)
                T_tgt = want * self.T_full * math.cos(math.radians(c.thrust_angle_deg))
                B_tgt = ctl.brake * mu * N_tot if v > 1e-6 else 0.0
                a_ff = (T_tgt + ctl.throttle * F_drive_full - D - R - B_tgt) / m
            th_ref = math.atan2(a_ff, G0)
            Kp, Kd = 2.0 * mr * G0 * l, 0.5 * mr * G0 * l
            tau = Kp * (self.theta - th_ref) + Kd * self.omega
            tau = max(-mr * G0 * vs["rider_heel_lever_m"], min(mr * G0 * vs["rider_toe_lever_m"], tau))
            alpha = (G0 * math.sin(self.theta) - a * math.cos(self.theta)) / l - tau / (mr * l * l)
            self.omega += alpha * dt
            self.theta += self.omega * dt
            if abs(self.theta - th_ref) > 0.45 or abs(self.theta) > 0.7:
                self._rider_falls("lost balance (lean %.0f deg vs needed %.0f deg)" % (math.degrees(self.theta),
                                                                                      math.degrees(th_ref)))
        elif self.rider_x is not None:
            # fallen rider slides to a stop (body-on-asphalt friction ~0.5)
            if self.rider_v > 0:
                self.rider_v = max(0.0, self.rider_v - 0.5 * G0 * dt)
                self.rider_x += self.rider_v * dt

        # ---- integrate translation (semi-implicit Euler), no rolling backwards on the flat track
        v0 = v
        v1 = v0 + a * dt
        if v1 < 0:
            v1 = 0.0
        v_avg = 0.5 * (v0 + v1)
        m_before = m
        # ---- energy ledger (works use the step-average speed, consistent with the discrete kinetic-energy change)
        Lg = self.L
        P_drive_mech = F_drive * v_avg
        Lg["drive_work"] += P_drive_mech * dt
        if P_drive_mech > 0:
            e_el = P_drive_mech * dt / vs["drive_eff"]
            Lg["batt_out"] += e_el
            Lg["motor_loss"] += e_el - P_drive_mech * dt
            self.batt_j -= e_el
        if B > 0:
            regen = 0.0
            if c.electric and self.mode == "rolling":
                regen = min(B, vs["wheel_force_max_n"]) * v_avg * dt
            Lg["regen_in"] += regen * vs["regen_eff"]
            self.batt_j = min(self.batt_j + regen * vs["regen_eff"], vs["batt_wh"] * 3600) if c.electric else 0.0
            Lg["brake_heat"] += B * v_avg * dt - regen * vs["regen_eff"]
        Lg["drag"] += D * v_avg * dt
        Lg["roll"] += R * v_avg * dt
        if T > 0 and mdot > 0:
            ue = T / mdot                         # effective exhaust velocity (incl. pressure thrust)
            Lg["jet_ke"] += 0.5 * mdot * ue * ue * dt
            Lg["thrust_work"] += Tx * v_avg * dt
            # ground-frame KE left in the jet; the thrust-normal component Tz does no work on the level track
            Lg["jet_residual"] += 0.5 * mdot * ue * ue * dt - Tx * v_avg * dt + 0.5 * mdot * v_avg * v_avg * dt
            Lg["gas_used"] += mdot * dt
        self.v = v1
        self.x += v_avg * dt
        self.a = a
        self.t += dt
        m_after, _, _, _ = self.mass_props()
        # KE of mass that left the vehicle with the jet is counted in jet_residual (0.5 mdot v^2 term above)
        self._ke_check = (m_before, m_after)
        g = gas_st or {}
        self.tel = {"t": self.t, "x": self.x, "v": self.v, "a": a, "m": m_after, "thrust": T, "Tx": Tx, "mdot": mdot,
                    "F_drive": F_drive, "drag": D, "roll": R, "brake": B, "Nf": Nf, "Nr": Nr, "theta": self.theta,
                    "phi": self.phi, "mode": self.mode, "rider_on": self.rider_on, "valve": self.valve,
                    "gas_kg": self.gas_sys.m if self.gas_sys else 0.0, "p_tank": g.get("p_tank", 0.0),
                    "T_tank": g.get("T_tank", 0.0), "isp": g.get("isp", 0.0), "Te": g.get("Te", 0.0),
                    "batt_wh": self.batt_j / 3600, "cg_x": xc, "cg_z": zc, "rider_x": self.rider_x}
        return self.tel

    def _event(self, what: str):
        last = next((t for t, e in reversed(self.events) if e == what), None)
        if last is None or self.t - last > 0.5:
            self.events.append((round(self.t, 3), what))

    def _rider_falls(self, why: str):
        if not self.rider_on:
            return
        c = self.cfg
        m_before, _, _, _ = self.mass_props()
        self.rider_on = False
        self.flags["rider_fell"] = True
        self.events.append((self.t, "RIDER FELL: " + why))
        self.rider_x = self.x + c.wheelbase_m / 2
        self.rider_v = self.v
        # the rider's kinetic energy leaves the vehicle system (dissipated in the fall/slide)
        self.L["rider_ke_lost"] += 0.5 * c.rider_kg * self.v * self.v
        self.theta = 0.0

    # -------------------------------------------------------------------------- scenario runner
    def run(self, scenario: Scenario, t_end: float = 30.0, record_every: int = 20) -> dict:
        self.reset()
        m0, _, _, _ = self.mass_props()
        self.L["ke0"] = 0.0
        seg = 0
        rec = {k: [] for k in ("t", "x", "v", "a", "thrust", "gas_kg", "p_tank", "T_tank", "theta", "phi", "Nf",
                               "Nr", "batt_wh", "F_drive", "drag", "m")}
        n = 0
        while self.t < t_end - 1e-12:
            while seg + 1 < len(scenario) and self.t >= scenario[seg + 1][0] - 1e-12:
                seg += 1
            self.ctl = scenario[seg][1]
            tel = self.step(self.cfg.dt)
            if n % record_every == 0:
                for k in rec:
                    rec[k].append(tel[k])
            n += 1
            if self.v <= 0 and self.ctl.brake > 0 and self.t > scenario[-1][0]:
                break
        m1, _, _, _ = self.mass_props()
        rec["events"] = self.events
        rec["ledger"] = self.ledger(m1)
        return rec

    def ledger(self, m_now: float) -> dict:
        Lg = dict(self.L)
        ke1 = 0.5 * m_now * self.v * self.v
        sources = Lg["batt_out"] + Lg["jet_ke"] + Lg["ke0"]
        sinks = (ke1 + Lg["drag"] + Lg["roll"] + Lg["brake_heat"] + Lg["motor_loss"] + Lg["jet_residual"]
                 + Lg["rider_ke_lost"] + Lg["regen_in"])
        exergy_used = self.exergy0 - self._exergy()
        Lg.update(ke1=ke1, sources=sources, sinks=sinks, residual=sources - sinks,
                  rel_residual=(sources - sinks) / max(sources, 1e-9), exergy_used=exergy_used,
                  jet_over_exergy=Lg["jet_ke"] / exergy_used if exergy_used > 0 else 0.0)
        return Lg


# ------------------------------------------------------------------------------------------ evaluation
class SkateResult(BaseModel):
    config: SkateConfig
    total_mass_kg: float
    propulsion_mass_kg: float
    gas_mass_kg: float
    tank_mass_kg: float
    max_speed_m_s: float
    max_speed_no_boost_m_s: float
    speed_gain_m_s: float
    boost_duration_s: float
    boost_impulse_ns: float
    peak_accel_g: float
    peak_boost_accel_g: float
    distance_m: float
    stop_time_s: float
    initial_thrust_n: float
    mean_isp_s: float
    speed_gain_per_kg_tank: float
    gas_used_kg: float
    energy_ledger: dict
    no_boost_ledger: dict
    flags: dict
    events: list
    hazards: dict
    cost: dict
    feasible: bool
    warnings: list[str]
    trace: dict | None = None


def _boost_metrics(rec):
    t, th = rec["t"], rec["thrust"]
    on = [ti for ti, f in zip(t, th) if f > 1.0]
    dur = (on[-1] - on[0]) if len(on) > 1 else 0.0
    imp = sum(0.5 * (th[i] + th[i + 1]) * (t[i + 1] - t[i]) for i in range(len(t) - 1))
    return dur, imp


def evaluate_skateboard(cfg: SkateConfig, scenario: Scenario | None = None, t_end: float = 30.0,
                        keep_trace: bool = False) -> SkateResult:
    from .hazards import jet_hazard

    sc = scenario or default_scenario(True)
    sim = SkateSim(cfg)
    rec = sim.run(sc, t_end)
    flags = dict(sim.flags)
    sc0 = [(t0, Controls(throttle=c.throttle, boost=False, brake=c.brake)) for t0, c in sc]
    cfg0 = cfg.model_copy(update={"coldgas": False})
    sim0 = SkateSim(cfg0)
    rec0 = sim0.run(sc0, t_end)
    dur, imp = _boost_metrics(rec)
    m_tot = rec["m"][0]
    gs = sim.gas_sys
    tank_kg = gs.m_wall if gs else 0.0
    prop_kg = (gs.dry_mass + gs.m0) if gs else 0.0
    vmax, vmax0 = max(rec["v"]), max(rec0["v"])
    acc = rec["a"]
    boost_acc = [a for a, f in zip(acc, rec["thrust"]) if f > 1]
    vals_cg = sim.v_cg
    hz: dict = {}
    warnings: list[str] = []
    cost = {"board_usd": sim.v_sk["cost_board"], "edrive_usd": sim.v_sk["cost_edrive"] if cfg.electric else 0.0}
    if gs:
        st0 = gs.thrust_state(1.0)
        gs.reset()
        er = energy_report(cfg.tank, residual_bar=max(min(rec["p_tank"][-1] / 1e5, cfg.tank.pressure_bar), 1.0),
                           vals=vals_cg)
        jh = jet_hazard(st0["per_thruster"], st0["ue"], st0["Te"], st0["mdot"] / cfg.thruster.n_thrusters,
                        0.003)
        hz = {"tank": er.model_dump(), "jet": jh.model_dump()}
        cost.update(tank_usd=tank_cost(cfg.tank, vals_cg),
                    valves_usd=vals_cg["cost_valves_base"] + cfg.thruster.n_thrusters * vals_cg["cost_per_thruster"],
                    refill_usd=er.refill_cost_usd)
        if er.tnt_equiv_kg > 0.05:
            warnings.append(f"stored gas = {er.burst_energy_kj:.0f} kJ burst energy ({er.tnt_equiv_kg:.2f} kg TNT eq.): "
                            f"1 psi overpressure out to {er.blast_radius_1psi_m:.1f} m on vessel failure")
        warnings.append(f"exhaust jet above 15 m/s for {jh.velocity_zone_m:.1f} m behind the board; "
                        f"{jh.spl_at_1m_db:.0f} dB at 1 m")
        stuck = gs.max_thrust() / m_tot
        warnings.append(f"valve stuck open: uncommanded {stuck / G0:.2f} g push until the tank empties "
                        f"(~{dur:.0f} s) - needs a dead-man cut-off")
    cost["total_usd"] = sum(v for k, v in cost.items() if k != "refill_usd")
    if flags["rider_fell"]:
        warnings.append("rider falls: " + "; ".join(e for _, e in rec["events"] if "RIDER" in e))
    if flags["wheelie"]:
        warnings.append("front wheels lift (wheelie) under acceleration")
    if flags["noseover"]:
        warnings.append("rear wheels lift (nose-over): thrust line too high")
    if vmax > 13:
        warnings.append(f"top speed {vmax:.1f} m/s exceeds typical skateboard speed-wobble onset (~12-13 m/s)")
    feasible = not (flags["rider_fell"] or flags["noseover"] or sim.mode == "crashed")
    trace = None
    if keep_trace:
        trace = {k: rec[k] for k in ("t", "x", "v", "a", "thrust", "gas_kg", "p_tank", "T_tank", "theta", "Nf", "Nr")}
        trace["v_no_boost"] = rec0["v"]
    return SkateResult(config=cfg, total_mass_kg=m_tot, propulsion_mass_kg=prop_kg, gas_mass_kg=gs.m0 if gs else 0.0,
                       tank_mass_kg=tank_kg, max_speed_m_s=vmax, max_speed_no_boost_m_s=vmax0,
                       speed_gain_m_s=vmax - vmax0, boost_duration_s=dur, boost_impulse_ns=imp,
                       peak_accel_g=max(acc) / G0, peak_boost_accel_g=(max(boost_acc) / G0) if boost_acc else 0.0,
                       distance_m=rec["x"][-1], stop_time_s=rec["t"][-1],
                       initial_thrust_n=gs.thrust_state(1.0)["thrust"] if gs else 0.0,
                       mean_isp_s=imp / (rec["ledger"]["gas_used"] * G0) if rec["ledger"]["gas_used"] > 0 else 0.0,
                       speed_gain_per_kg_tank=(vmax - vmax0) / prop_kg if prop_kg else 0.0,
                       gas_used_kg=rec["ledger"]["gas_used"], energy_ledger=rec["ledger"], no_boost_ledger=rec0["ledger"],
                       flags=flags, events=rec["events"], hazards=hz, cost=cost, feasible=feasible, warnings=warnings,
                       trace=trace)
