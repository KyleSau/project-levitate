"""Cascaded flight controller: position -> velocity -> attitude -> angular rate, plus control allocation.

  1. position P          v_cmd = v_ref + Kp_pos (p_ref - p)                         (saturated)
  2. velocity PI         a_cmd = a_ref + Kp_vel (v_cmd - v) + Ki_vel int(v_cmd - v)  (anti-windup clamp,
                         integrators frozen while on the ground)
  3. thrust vector       F_des = m_model (a_cmd + g e_z); tilt limited so that vertical thrust is kept;
                         "tilt" mode (all actuators along body z): desired attitude = b3 along F_des with
                         yaw reference; collective T = F_des . (R e_z).
                         "direct" mode (actuator set can push sideways, rank-6 B): attitude stays level,
                         body force = R^T F_des.
  4. attitude P (quaternion error)  w_cmd = 2 K_att sign(q_e,w) q_e,vec,  q_e = q^-1 (x) q_des
  5. rate PI             alpha = Kp_rate (w_cmd - w) + Ki_rate int(...);  tau = J alpha + w x J w
  6. allocation          minimise || W (B_sel f - wrench_sel) ||  s.t. f_min <= f <= f_max
                         (pseudo-inverse when unconstrained, bounded-variable least squares when not;
                         priorities: thrust, roll/pitch >> yaw), then a total electrical-power cap scales
                         all forces (models battery/ESC current limiting).
"""
from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel
from scipy.optimize import lsq_linear

from . import quat


class Gains(BaseModel):
    pos_kp_xy: float = 1.6
    pos_kp_z: float = 2.0
    vel_kp_xy: float = 3.2
    vel_ki_xy: float = 0.6
    vel_kp_z: float = 5.0
    vel_ki_z: float = 3.0
    vel_int_limit: float = 3.0           # m/s^2 equivalent
    att_kp_rp: float = 9.0               # (rad/s) / rad
    att_kp_yaw: float = 2.5
    rate_kp: tuple[float, float, float] = (22.0, 22.0, 8.0)
    rate_ki: tuple[float, float, float] = (4.0, 4.0, 1.0)
    rate_int_limit: float = 20.0         # rad/s^2 equivalent
    max_tilt_deg: float = 30.0
    max_rate_rp: float = 8.0
    max_rate_yaw: float = 2.5
    max_vel_xy: float = 1.5
    max_vel_z: float = 1.0
    control_hz: float = 500.0


class Reference(BaseModel):
    p: tuple[float, float, float]
    v: tuple[float, float, float] = (0.0, 0.0, 0.0)
    a: tuple[float, float, float] = (0.0, 0.0, 0.0)
    yaw: float = 0.0
    horizontal_control: bool = True
    armed: bool = False
    throttle_scale: float = 1.0
    freeze_integrators: bool = False


class Controller:
    def __init__(self, plant, gains: Gains, f_min, f_max, mass_model: float | None = None,
                 torque_limit=None, power_cap_w: float = math.inf):
        self.p = plant
        self.k = gains
        self.m_model = mass_model if mass_model is not None else plant.m
        self.J = plant.J
        self.B = plant.B
        self.f_min0 = np.array(f_min, float)
        self.f_max0 = np.array(f_max, float)
        self.torque_limit = None if torque_limit is None else np.array(torque_limit, float)
        self.power_cap = power_cap_w
        self.dt = 1.0 / gains.control_hz
        # total thrust available with equal sharing under the electrical power cap (inf if uncapped)
        n = plant.n
        budget = power_cap_w - plant.power.avionics_w
        self.t_avail_power = n * plant.power.thrust_at_power(budget / n) if power_cap_w < math.inf else math.inf
        # does the actuator set produce lateral body force? -> direct force mode
        self.direct = np.linalg.matrix_rank(self.B, tol=1e-9) == 6 and np.linalg.norm(self.B[0:2]) > 1e-9
        self.rows = [0, 1, 2, 3, 4, 5] if self.direct else [2, 3, 4, 5]
        mg = self.m_model * plant.g
        arm = 0.01
        prio = {0: 1.0 / mg, 1: 1.0 / mg, 2: 3.0 / mg, 3: 1.0 / (mg * arm), 4: 1.0 / (mg * arm), 5: 0.1 / (mg * arm)}
        self.Wsel = np.diag([prio[r] for r in self.rows])
        self.Bsel = self.B[self.rows]
        self.Bpinv = np.linalg.pinv(self.Bsel)
        self.reset()

    def reset(self):
        self.iv = np.zeros(3)
        self.iw = np.zeros(3)

    def update(self, meas_x, ref: Reference, f_min=None, f_max=None):
        k = self.k
        g = self.p.g
        p, v, q, w = meas_x[0:3], meas_x[3:6], meas_x[6:10], meas_x[10:13]
        R = quat.to_rot(q)
        f_min = self.f_min0 if f_min is None else f_min
        f_max = self.f_max0 if f_max is None else f_max
        diag: dict = {}
        if not ref.armed:
            self.reset()
            return np.zeros(len(f_min)), dict(saturated=False, thrust_deficit=False, power_limited=False,
                                                 tilt_cmd=0.0, F_des_w=[0.0, 0.0, 0.0], tau_cmd_b=[0.0, 0.0, 0.0],
                                                 collective=0.0, q_des=[1.0, 0.0, 0.0, 0.0], w_cmd=[0.0, 0.0, 0.0])
        pr, vr, ar = np.array(ref.p), np.array(ref.v), np.array(ref.a)
        kp_pos = np.array([k.pos_kp_xy, k.pos_kp_xy, k.pos_kp_z])
        v_cmd = vr + kp_pos * (pr - p)
        hxy = math.hypot(v_cmd[0], v_cmd[1])
        if hxy > k.max_vel_xy:
            v_cmd[0:2] *= k.max_vel_xy / hxy
        v_cmd[2] = max(-k.max_vel_z, min(k.max_vel_z, v_cmd[2]))
        if not ref.horizontal_control:
            v_cmd[0:2] = v[0:2]
            ar = np.array([0.0, 0.0, ar[2]])
        ev = v_cmd - v
        if not ref.freeze_integrators:
            self.iv += ev * self.dt
            ki = np.array([k.vel_ki_xy, k.vel_ki_xy, k.vel_ki_z])
            lim = k.vel_int_limit / np.maximum(ki, 1e-9)
            self.iv = np.clip(self.iv, -lim, lim)
        if not ref.horizontal_control:
            self.iv[0:2] = 0.0
        kpv = np.array([k.vel_kp_xy, k.vel_kp_xy, k.vel_kp_z])
        kiv = np.array([k.vel_ki_xy, k.vel_ki_xy, k.vel_ki_z])
        a_cmd = ar + kpv * ev + kiv * self.iv
        if not ref.horizontal_control:
            a_cmd[0:2] = 0.0
        F_des = self.m_model * (a_cmd + np.array([0.0, 0.0, g]))

        # tilt limit: keep vertical thrust; reduce tilt envelope when total thrust is limited
        tilt_max = math.radians(k.max_tilt_deg)
        t_avail = float(np.sum(f_max)) if np.all(np.isfinite(f_max)) else math.inf
        t_avail = min(t_avail, self.t_avail_power)
        w_model = self.m_model * g
        if t_avail < math.inf:
            ratio = w_model / max(0.95 * t_avail, 1e-12)
            tilt_max = min(tilt_max, math.acos(ratio)) if ratio < 1 else math.radians(3.0)
        thrust_deficit = t_avail < F_des[2]
        F_des[2] = max(F_des[2], 0.05 * w_model)
        hor = math.hypot(F_des[0], F_des[1])
        hmax = F_des[2] * math.tan(tilt_max)
        if hor > hmax:
            F_des[0:2] *= hmax / hor

        yaw = ref.yaw
        if self.direct:
            Rd = quat.to_rot(quat.from_yaw(yaw))
            F_body = R.T @ F_des
        else:
            b3 = F_des / np.linalg.norm(F_des)
            b1c = np.array([math.cos(yaw), math.sin(yaw), 0.0])
            b2 = quat.cross(b3, b1c)
            b2 /= np.linalg.norm(b2)
            Rd = np.column_stack([quat.cross(b2, b3), b2, b3])
            F_body = np.array([0.0, 0.0, float(F_des @ R[:, 2])])
        q_des = quat.from_rot(Rd)
        qe = quat.mul(quat.conj(q), q_des)
        if qe[0] < 0:
            qe = -qe
        w_cmd = 2.0 * np.array([k.att_kp_rp * qe[1], k.att_kp_rp * qe[2], k.att_kp_yaw * qe[3]])
        w_cmd[0:2] = np.clip(w_cmd[0:2], -k.max_rate_rp, k.max_rate_rp)
        w_cmd[2] = max(-k.max_rate_yaw, min(k.max_rate_yaw, w_cmd[2]))
        ew = w_cmd - w
        kr, kri = np.array(k.rate_kp), np.array(k.rate_ki)
        if not ref.freeze_integrators:
            self.iw += ew * self.dt
            lim = k.rate_int_limit / np.maximum(kri, 1e-9)
            self.iw = np.clip(self.iw, -lim, lim)
        alpha = kr * ew + kri * self.iw
        tau = self.J @ alpha + quat.cross(w, self.J @ w)
        if self.torque_limit is not None:
            tau = np.clip(tau, -self.torque_limit, self.torque_limit)

        wrench = np.concatenate([F_body, tau])[self.rows]
        u = self.Bpinv @ wrench
        saturated = bool(np.any(u < f_min - 1e-12) or np.any(u > f_max + 1e-12))
        if saturated:
            lb = np.where(np.isfinite(f_min), f_min, -1e6)
            ub = np.where(np.isfinite(f_max), f_max, 1e6)
            ub = np.maximum(ub, lb + 1e-15)
            u = lsq_linear(self.Wsel @ self.Bsel, self.Wsel @ wrench, bounds=(lb, ub), method="bvls").x
        u = u * ref.throttle_scale
        power_limited = False
        if self.power_cap < math.inf:
            pw = self.p.power
            p_act = float(np.sum(pw.actuator_power(u)))
            budget = max(self.power_cap - pw.avionics_w, 0.0)
            if p_act > budget:
                power_limited = True
                s = (budget / p_act) ** (2 / 3) if pw.kind != "ionic" else budget / p_act
                u = u * s
        diag.update(saturated=saturated, thrust_deficit=bool(thrust_deficit), power_limited=power_limited,
                    tilt_cmd=math.degrees(math.acos(max(-1.0, min(1.0, Rd[2, 2])))), F_des_w=F_des.tolist(),
                    tau_cmd_b=tau.tolist(), collective=float(F_body[2]), q_des=q_des.tolist(), w_cmd=w_cmd.tolist())
        return u, diag
