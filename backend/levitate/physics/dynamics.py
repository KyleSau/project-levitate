"""Six-degree-of-freedom rigid-body flight simulation with cascaded control.

Plant
  * rigid body, quaternion attitude (scalar-first, body->world), RK4 at `dt`
  * per-rotor first-order thrust lag, thrust clamped to [0, T_max]
  * Cheeseman-Bennett ground-effect multiplier on thrust
  * quadratic aerodynamic drag on the body, linear rotational damping
  * penalty-method ground contact with Coulomb-like friction
  * optional gust (Ornstein-Uhlenbeck) force and sensor noise, optional plant/model mass mismatch
Controller (500 Hz zero-order hold)
  * position PD + feed-forward from a 2nd-order reference prefilter -> desired acceleration
  * geometric SO(3) attitude control (Lee, Leok & McClamroch 2010)
  * control allocation: pseudo-inverse, falling back to bounded least squares when saturated

The animation in the browser *replays* this trajectory; it is not an independent physics engine.
"""
from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel, Field
from scipy.optimize import lsq_linear

from ..constants import G0, RHO_AIR_SL
from .rotor import ground_effect_thrust_ratio


class Waypoint(BaseModel):
    t: float
    pos: tuple[float, float, float]
    yaw_deg: float = 0.0


def default_mission(alt: float = 0.3) -> list[Waypoint]:
    return [
        Waypoint(t=0.0, pos=(0, 0, 0)),
        Waypoint(t=0.5, pos=(0, 0, alt)),
        Waypoint(t=4.0, pos=(0.5, 0, alt)),
        Waypoint(t=6.5, pos=(0.5, 0.3, alt)),
        Waypoint(t=9.0, pos=(0.5, 0.3, alt), yaw_deg=90),
        Waypoint(t=11.0, pos=(0, 0, alt), yaw_deg=90),
        Waypoint(t=13.0, pos=(0, 0, -0.02), yaw_deg=90),
    ]


class SimConfig(BaseModel):
    duration_s: float = 15.0
    dt: float = 0.002
    output_hz: float = 50.0
    attitude_bandwidth: float = 30.0     # rad/s natural frequency of attitude loop
    attitude_damping: float = 0.8
    yaw_bandwidth: float = 6.0           # yaw is drag-torque limited: run it slower
    yaw_rate_limit_deg_s: float = 90.0
    position_bandwidth: float = 3.0
    position_damping: float = 0.9
    prefilter_bandwidth: float = 2.5
    max_tilt_deg: float = 35.0
    gust_std_n: float = 0.0              # std of OU gust force
    gust_tau_s: float = 0.5
    sensor_noise_pos_m: float = 0.0
    sensor_noise_att_rad: float = 0.0
    plant_mass_scale: float = 1.0        # plant mass / controller's mass model
    seed: int = 0
    mission: list[Waypoint] = Field(default_factory=default_mission)


class VehicleParams(BaseModel):
    mass_kg: float
    inertia: list[list[float]]
    rotor_pos_cg: list[tuple[float, float, float]]   # rotor positions relative to CG
    spins: list[int]
    kappa: float
    t_max_n: float
    motor_tau_s: float
    rotor_radius_m: float
    rotor_height_above_bottom_m: float
    drag_area_xy_m2: float
    drag_area_z_m2: float
    cd: float = 1.1


class SimResult(BaseModel):
    t: list[float]
    pos: list[list[float]]
    quat: list[list[float]]
    vel: list[list[float]]
    omega: list[list[float]]
    thrusts: list[list[float]]
    ref: list[list[float]]
    metrics: dict[str, float | bool | str]


# ---------------------------------------------------------------- quaternion helpers
def quat_mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
                     w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                     w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])


def quat_to_rot(q):
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def _vee(M):
    return np.array([M[2, 1], M[0, 2], M[1, 0]])


def allocation(rotor_pos_cg, spins, kappa):
    P = np.asarray(rotor_pos_cg)
    return np.vstack([np.ones(len(P)), P[:, 1], -P[:, 0], -kappa * np.asarray(spins, float)])


# ---------------------------------------------------------------- reference prefilter
class _Prefilter:
    """Critically-damped 2nd-order filter producing smooth (p, v, a) references."""

    def __init__(self, wn: float, p0: np.ndarray):
        self.wn, self.p, self.v = wn, p0.copy(), np.zeros_like(p0)

    def step(self, target: np.ndarray, dt: float):
        a = self.wn ** 2 * (target - self.p) - 2 * self.wn * self.v
        self.v = self.v + a * dt
        self.p = self.p + self.v * dt
        return self.p.copy(), self.v.copy(), a


def _waypoint_at(mission: list[Waypoint], t: float) -> Waypoint:
    cur = mission[0]
    for w in mission:
        if w.t <= t:
            cur = w
    return cur


def simulate(vp: VehicleParams, cfg: SimConfig = SimConfig()) -> SimResult:
    rng = np.random.default_rng(cfg.seed)
    m_ctrl = vp.mass_kg
    m = vp.mass_kg * cfg.plant_mass_scale
    J = np.asarray(vp.inertia)
    Jinv = np.linalg.inv(J)
    B = allocation(vp.rotor_pos_cg, vp.spins, vp.kappa)
    Bpinv = np.linalg.pinv(B)
    n = B.shape[1]
    rotor_z = np.array([p[2] for p in vp.rotor_pos_cg])
    e3 = np.array([0.0, 0.0, 1.0])

    kR = np.array([cfg.attitude_bandwidth ** 2] * 2 + [cfg.yaw_bandwidth ** 2])
    kW = np.array([2 * cfg.attitude_damping * cfg.attitude_bandwidth] * 2 + [2 * 0.9 * cfg.yaw_bandwidth])
    kP = cfg.position_bandwidth ** 2
    kD = 2 * cfg.position_damping * cfg.position_bandwidth
    # keep >=10 % vertical thrust margin at the tilt limit
    tw = len(vp.rotor_pos_cg) * vp.t_max_n / (m_ctrl * G0)
    tilt_max = math.radians(cfg.max_tilt_deg)
    if tw > 1.1:
        tilt_max = min(tilt_max, math.acos(1.1 / tw))
    else:
        tilt_max = math.radians(2.0)
    yaw_ref = math.radians(cfg.mission[0].yaw_deg)
    crashed = False
    k_contact, c_contact = 400.0 * m / 0.03, 40.0 * m / 0.03 * 0.03

    # state: p(3) v(3) q(4) w(3) u(n)
    x = np.zeros(13 + n)
    x[6] = 1.0          # identity attitude; z=0 means the board is resting on the ground
    gust = np.zeros(3)
    pre = _Prefilter(cfg.prefilter_bandwidth, x[0:3].copy())
    u_cmd = np.zeros(n)
    bottom_offset = vp.rotor_height_above_bottom_m  # CG height above board bottom

    def deriv(xs, ucmd, f_ext):
        p, v, q, w, u = xs[0:3], xs[3:6], xs[6:10], xs[10:13], xs[13:]
        R = quat_to_rot(q)
        h_rot = max(p[2] + bottom_offset, 1e-4)
        kge = ground_effect_thrust_ratio(vp.rotor_radius_m, h_rot)
        thrust = float(np.sum(u)) * kge
        F = R @ (thrust * e3) - m * G0 * e3 + f_ext
        # drag (world-frame velocity, crude anisotropic areas)
        F[0:2] -= 0.5 * RHO_AIR_SL * vp.cd * vp.drag_area_xy_m2 * v[0:2] * np.abs(v[0:2])
        F[2] -= 0.5 * RHO_AIR_SL * vp.cd * vp.drag_area_z_m2 * v[2] * abs(v[2])
        tau = B[1:] @ (u * kge) - 2e-6 * w
        # ground contact (penalty)
        if p[2] < 0:
            F[2] += -k_contact * p[2] - c_contact * v[2]
            F[0:2] -= 8.0 * m * v[0:2]
            tau = tau - 30 * J @ w
            # restoring torque toward level
            tilt_axis = np.cross(R @ e3, e3)
            tau = tau + R.T @ (400 * np.diag(J).max() * tilt_axis)
        dp = v
        dv = F / m
        dq = 0.5 * quat_mul(q, np.array([0.0, *w]))
        dw = Jinv @ (tau - np.cross(w, J @ w))
        du = (ucmd - u) / vp.motor_tau_s
        return np.concatenate([dp, dv, dq, dw, du])

    steps = int(cfg.duration_s / cfg.dt)
    out_every = max(1, int(round(1 / (cfg.output_hz * cfg.dt))))
    T_, P_, Q_, V_, W_, U_, REF_ = [], [], [], [], [], [], []
    sat_steps, airborne_steps, err_sq, max_tilt, max_err = 0, 0, 0.0, 0.0, 0.0
    diverged = False
    motors_armed = True
    landed_at = None

    for k in range(steps):
        t = k * cfg.dt
        wp = _waypoint_at(cfg.mission, t)
        p_ref, v_ref, a_ref = pre.step(np.array(wp.pos, float), cfg.dt)
        p, v, q, w = x[0:3], x[3:6], x[6:10], x[10:13]
        R = quat_to_rot(q)
        final = cfg.mission[-1]
        # landing phase: below 5 cm on the final (ground-level) waypoint, descend at a fixed 0.25 m/s
        if wp is final and final.pos[2] <= 0 and t > final.t and p[2] < 0.05:
            p_ref = np.array([p_ref[0], p_ref[1], p[2]])
            v_ref = np.array([v_ref[0], v_ref[1], -0.25])
            a_ref = np.array([a_ref[0], a_ref[1], 0.0])

        # sensing
        p_m = p + rng.normal(0, cfg.sensor_noise_pos_m, 3) if cfg.sensor_noise_pos_m else p
        if cfg.sensor_noise_att_rad:
            dth = rng.normal(0, cfg.sensor_noise_att_rad, 3)
            dq = np.array([1.0, *(dth / 2)])
            R_m = quat_to_rot(quat_mul(q, dq / np.linalg.norm(dq)))
        else:
            R_m = R

        # outer loop
        a_des = kP * (p_ref - p_m) + kD * (v_ref - v) + a_ref + G0 * e3
        # tilt limit
        horiz = np.linalg.norm(a_des[0:2])
        if a_des[2] < 0.3 * G0:
            a_des[2] = 0.3 * G0
        if horiz > a_des[2] * math.tan(tilt_max):
            a_des[0:2] *= a_des[2] * math.tan(tilt_max) / horiz
        b3 = a_des / np.linalg.norm(a_des)
        dyaw = (math.radians(wp.yaw_deg) - yaw_ref + math.pi) % (2 * math.pi) - math.pi
        yaw_ref += max(-1.0, min(1.0, dyaw / (math.radians(cfg.yaw_rate_limit_deg_s) * cfg.dt))) \
            * math.radians(cfg.yaw_rate_limit_deg_s) * cfg.dt
        yaw = yaw_ref
        b1c = np.array([math.cos(yaw), math.sin(yaw), 0.0])
        b2 = np.cross(b3, b1c)
        b2 /= np.linalg.norm(b2)
        Rd = np.column_stack([np.cross(b2, b3), b2, b3])
        collective = m_ctrl * float(a_des @ (R_m @ e3))
        eR = 0.5 * _vee(Rd.T @ R_m - R_m.T @ Rd)
        tau_cmd = J @ (-kR * eR - kW * w) + np.cross(w, J @ w)
        if math.acos(max(-1.0, min(1.0, R[2, 2]))) > math.radians(80):
            crashed = True          # flight firmware disarms on loss of attitude
        if crashed:
            motors_armed = False

        # landing logic: disarm once the final waypoint is below ground and we have touched down
        if wp is final and final.pos[2] <= 0 and p[2] < 0.003 and t > final.t:
            if landed_at is None:
                landed_at = t
            motors_armed = False

        if motors_armed and not (t < cfg.mission[1].t * 0.5):
            wrench = np.concatenate([[collective], tau_cmd])
            u_cmd = Bpinv @ wrench
            if np.any(u_cmd < 0) or np.any(u_cmd > vp.t_max_n):
                if x[2] > 0.02:
                    sat_steps += 1
                # prioritise thrust and roll/pitch over yaw
                Wt = np.diag([10.0, 3.0, 3.0, 0.3])
                u_cmd = lsq_linear(Wt @ B, Wt @ wrench, bounds=(0, vp.t_max_n), method="bvls").x
        else:
            u_cmd = np.zeros(n)

        # gust
        if cfg.gust_std_n:
            a_ou = cfg.dt / cfg.gust_tau_s
            gust = gust * (1 - a_ou) + cfg.gust_std_n * math.sqrt(2 * a_ou) * rng.normal(0, 1, 3)

        # RK4
        k1 = deriv(x, u_cmd, gust)
        k2 = deriv(x + 0.5 * cfg.dt * k1, u_cmd, gust)
        k3 = deriv(x + 0.5 * cfg.dt * k2, u_cmd, gust)
        k4 = deriv(x + cfg.dt * k3, u_cmd, gust)
        x = x + cfg.dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        x[6:10] /= np.linalg.norm(x[6:10])

        if not np.all(np.isfinite(x)) or np.linalg.norm(x[0:3]) > 50:
            diverged = True
            break

        tilt = math.acos(max(-1.0, min(1.0, quat_to_rot(x[6:10])[2, 2])))
        airborne = x[2] > 0.02 and motors_armed
        if airborne:
            airborne_steps += 1
            e = np.linalg.norm(x[0:3] - p_ref)
            err_sq += e * e
            max_err = max(max_err, e)
            max_tilt = max(max_tilt, tilt)

        if k % out_every == 0:
            T_.append(round(t, 4))
            P_.append(x[0:3].tolist())
            Q_.append(x[6:10].tolist())
            V_.append(x[3:6].tolist())
            W_.append(x[10:13].tolist())
            U_.append(x[13:].tolist())
            REF_.append(p_ref.tolist())

    final_pos = x[0:3]
    target = np.array(cfg.mission[-1].pos[:2])
    rms = math.sqrt(err_sq / airborne_steps) if airborne_steps else float("nan")
    stable = (not diverged and not crashed and airborne_steps > 0 and max_err < 0.25
              and math.degrees(max_tilt) < 60)
    metrics: dict[str, float | bool | str] = {
        "stable": bool(stable),
        "diverged": bool(diverged),
        "crashed": bool(crashed),
        "tilt_limit_deg": math.degrees(tilt_max),
        "rms_tracking_error_m": rms,
        "max_tracking_error_m": max_err,
        "max_tilt_deg": math.degrees(max_tilt),
        "saturation_fraction": sat_steps / max(airborne_steps, 1),
        "landing_error_m": float(np.linalg.norm(final_pos[0:2] - target)),
        "landed": landed_at is not None,
        "airborne_time_s": airborne_steps * cfg.dt,
    }
    return SimResult(t=T_, pos=P_, quat=Q_, vel=V_, omega=W_, thrusts=U_, ref=REF_, metrics=metrics)
