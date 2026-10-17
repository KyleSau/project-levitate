"""6-DOF rigid-body plant.

State x = [p(3) world CG position, v(3) world CG velocity, q(4) attitude body->world (w,x,y,z),
           w(3) body angular velocity, f(n) actuator forces (OGE-equivalent), E(1) energy drawn].

Equations of motion (Newton-Euler about the CG):
    dp/dt = v
    (m I + R M_a R^T) dv/dt = F_world = R (F_act + F_drag) - m g e_z + F_buoy + F_contact + F_ext
    dq/dt = 1/2 q (x) (0, w)
    J dw/dt = tau_body - w x (J w)
    df_i/dt = (u_i - f_i) / tau_i         (tau_i = 0: f_i = u_i, held over the control period)
    dE/dt  = P_cell(sum_i P_i(f_i) + P_avionics)
M_a is the (optional) body-axis added-mass tensor from the FEM reduced-order model. Gravity acts on
the body mass only. The Munk moment of the added mass is neglected (documented limitation).
"""
from __future__ import annotations

import math

import numpy as np

from . import quat
from .modes import Environment, ResolvedModel, cell_power
from .vehicle import corners_geom, mass_properties


def ground_effect_ratio(radius_m: float, height_m: float) -> float:
    """Cheeseman & Bennett (1955) at constant power, clamped at z/R = 0.5 (Agent A rotor.py)."""
    z = max(height_m, 0.5 * radius_m)
    return 1.0 / (1.0 - (radius_m / (4.0 * z)) ** 2)


class Plant:
    def __init__(self, rm: ResolvedModel, env: Environment | None = None):
        env = env or Environment()
        self.rm = rm
        v = rm.vehicle
        mp = mass_properties(v, env.g)
        if not mp.valid:
            raise ValueError("invalid mass properties: " + "; ".join(mp.issues))
        self.mp = mp
        self.g = env.g
        self.m = mp.mass_kg
        self.cg = np.array(mp.cg_m)
        self.J = np.array(mp.inertia_kgm2)
        self.Jinv = np.linalg.inv(self.J)
        self.n = len(v.actuators)
        self.r_act = np.array([a.pos_m for a in v.actuators], float) - self.cg      # relative to CG, body
        ax = np.array([a.axis for a in v.actuators], float)
        self.axis = ax / np.linalg.norm(ax, axis=1, keepdims=True)
        spin = np.array([a.spin for a in v.actuators], float)
        kap = np.array([a.torque_ratio_m for a in v.actuators], float)
        # body wrench map B (6 x n): [F; tau] = B f
        self.B = np.zeros((6, self.n))
        for i in range(self.n):
            self.B[0:3, i] = self.axis[i]
            self.B[3:6, i] = np.cross(self.r_act[i], self.axis[i]) - spin[i] * kap[i] * self.axis[i]
        self.radius = np.array([a.radius_m for a in v.actuators], float)
        self.tau_s = np.array(rm.tau_s, float)
        self.lag = self.tau_s > 0
        self.inv_tau = np.where(self.lag, 1.0 / np.maximum(self.tau_s, 1e-12), 0.0)
        # aerodynamics
        rho = rm.rho
        self.rho = rho
        L, W, H = v.length_m, v.width_m, v.height_m
        d = v.drag
        self.drag_on = d.enabled
        self.kd = 0.5 * rho * np.array([d.cd_x * W * H, d.cd_y * L * H, d.cd_z * L * W])
        self.krot = rho * d.cd_rot * np.array([L * W ** 4, W * L ** 4, H * (L ** 4 + W ** 4)]) / 64.0
        self.wind = np.array(env.wind_m_s, float)
        self.volume = L * W * H
        self.buoy = rho * self.volume * self.g if env.buoyancy else 0.0
        # added mass (body axes)
        self.Ma = np.diag(v.added_mass_kg)
        self.has_added_mass = bool(np.any(np.array(v.added_mass_kg) > 0))
        # contact
        self.corners = corners_geom(v) - self.cg
        self.max_extent = float(np.max(np.linalg.norm(self.corners, axis=1)))
        c = v.contact
        ks = self.m / c.reference_mass_kg if c.scale_with_mass else 1.0
        self.kc, self.cc, self.mu_f, self.ct = (c.stiffness_n_per_m * ks, c.damping_n_s_per_m * ks, c.friction_coeff,
                                                c.tangential_damping_n_s_per_m * ks)
        self.ge = rm.ground_effect
        self.power = rm.power
        self.battery = rm.battery
        self.e3 = np.array([0.0, 0.0, 1.0])
        self.nx = 13 + self.n + 1
        self._ones = np.ones(self.n)
        self._z3 = np.zeros(3)
        self.tau_ext_b = np.zeros(3)          # external body torque (validation tests / disturbances)
        self.contact_lambda_max = self._contact_eigen_bound()

    # ------------------------------------------------------------------ initial state
    def rest_state(self, x0: float = 0.0, y0: float = 0.0, yaw: float = 0.0) -> np.ndarray:
        """Board level on the ground at static contact equilibrium (4 bottom corners loaded)."""
        x = np.zeros(self.nx)
        h_cg = self.cg[2] + self.rm.vehicle.height_m / 2           # CG height above board bottom
        sag = self.m * self.g / (4 * self.kc)
        x[0:3] = (x0, y0, h_cg - sag)
        x[6:10] = quat.from_yaw(yaw)
        return x

    # ------------------------------------------------------------------ forces
    def ge_factor(self, p, R) -> np.ndarray:
        if not self.ge:
            return self._ones
        h = p[2] + (self.r_act @ R.T)[:, 2]      # actuator heights above ground
        return np.array([ground_effect_ratio(r, max(hi, 1e-4)) for r, hi in zip(self.radius, h)])

    def contact(self, p, v, R, w):
        """Return (F_world, tau_body, N_total, n_points)."""
        if p[2] - self.max_extent > 0.0:
            return None
        rw = self.corners @ R.T                       # corner offsets in world
        z = p[2] + rw[:, 2]
        mask = z < 0.0
        if not mask.any():
            return None
        rwc = rw[mask]
        vc = v + quat.cross_rows(-rwc, R @ w)                # contact point velocity (world)
        pen = -z[mask]
        N = np.maximum(0.0, self.kc * pen - self.cc * vc[:, 2])
        vt = vc[:, 0:2]
        sp = np.linalg.norm(vt, axis=1)
        coef = np.minimum(self.ct, self.mu_f * N / np.maximum(sp, 1e-12))
        Ft = -vt * coef[:, None]
        Fc = np.column_stack([Ft, N])
        F = Fc.sum(axis=0)
        tau_w = quat.cross_rows(rwc, Fc).sum(axis=0)
        return F, R.T @ tau_w, float(N.sum()), int(mask.sum())

    def wrench(self, x, f_ext):
        """Full force/torque breakdown at state x. Returns dict (used by deriv and recorder)."""
        p, v, q, w = x[0:3], x[3:6], x[6:10], x[10:13]
        f = x[13:13 + self.n]
        R = quat.to_rot(q)
        kge = self.ge_factor(p, R)
        fa = f * kge
        Fb_act = self.B[0:3] @ fa
        tb_act = self.B[3:6] @ fa
        if self.drag_on:
            vb = R.T @ (v - self.wind)
            Fb_drag = -self.kd * vb * np.abs(vb)
            tb_drag = -self.krot * w * np.abs(w)
        else:
            Fb_drag = self._z3
            tb_drag = self._z3
        Fg = np.array([0.0, 0.0, -self.m * self.g])
        Fbuoy = np.array([0.0, 0.0, self.buoy])
        c = self.contact(p, v, R, w)
        if c is None:
            Fc, tc, N, npts = self._z3, self._z3, 0.0, 0
        else:
            Fc, tc, N, npts = c
        F_act_w = R @ Fb_act
        F_drag_w = R @ Fb_drag
        F = F_act_w + F_drag_w + Fg + Fbuoy + Fc + f_ext
        tau = tb_act + tb_drag + tc + self.tau_ext_b
        return dict(R=R, f_actual=fa, kge=kge, F_act_w=F_act_w, F_drag_w=F_drag_w, F_grav_w=Fg, F_buoy_w=Fbuoy,
                    F_contact_w=Fc, F_ext_w=f_ext, F_net_w=F, tau_act_b=tb_act, tau_drag_b=tb_drag,
                    tau_contact_b=tc, tau_net_b=tau, contact_N=N, contact_pts=npts)

    def accel(self, R, F):
        if not self.has_added_mass:
            return F / self.m
        M = self.m * np.eye(3) + R @ self.Ma @ R.T
        return np.linalg.solve(M, F)

    def electrical_power(self, f) -> float:
        p_load = float(np.sum(self.power.actuator_power(f))) + self.power.avionics_w
        return cell_power(p_load, self.battery) if self.battery is not None else p_load

    def deriv(self, x, u, f_ext):
        wr = self.wrench(x, f_ext)
        R = wr["R"]
        q, w = x[6:10], x[10:13]
        f = x[13:13 + self.n]
        dx = np.empty(self.nx)
        dx[0:3] = x[3:6]
        dx[3:6] = self.accel(R, wr["F_net_w"])
        dx[6:10] = 0.5 * quat.mul(q, (0.0, w[0], w[1], w[2]))
        dx[10:13] = self.Jinv @ (wr["tau_net_b"] - quat.cross(w, self.J @ w))
        dx[13:13 + self.n] = (u - f) * self.inv_tau
        dx[-1] = self.electrical_power(f)
        return dx

    def _contact_eigen_bound(self) -> float:
        """Largest |eigenvalue| of the linearised rigid-body + contact system at rest (finite differences)."""
        x0 = self.rest_state()
        u = np.zeros(self.n)
        z3 = np.zeros(3)
        f0 = self.deriv(x0, u, z3)[:13]
        Jac = np.zeros((13, 13))
        for i in range(13):
            h = 1e-7 if i < 3 else 1e-6
            x = x0.copy()
            x[i] += h
            Jac[:, i] = (self.deriv(x, u, z3)[:13] - f0) / h
        return float(np.abs(np.linalg.eigvals(Jac)).max())

    def substeps(self, x, dt) -> int:
        """RK4 is stable for real eigenvalues |lambda h| < 2.785. Near the ground we sub-step so that
        |lambda_max h| <= 2.0 for the stiff contact modes; in free flight one step is used."""
        if x[2] - self.max_extent > 0.005:
            return 1
        return max(1, math.ceil(dt * self.contact_lambda_max / 2.0))

    def step(self, x, u, f_ext, dt):
        k = self.substeps(x, dt)
        h = dt / k
        for _ in range(k):
            x = self.rk4_step(x, u, f_ext, h)
        return x

    def rk4_step(self, x, u, f_ext, dt):
        k1 = self.deriv(x, u, f_ext)
        k2 = self.deriv(x + 0.5 * dt * k1, u, f_ext)
        k3 = self.deriv(x + 0.5 * dt * k2, u, f_ext)
        k4 = self.deriv(x + dt * k3, u, f_ext)
        xn = x + dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
        xn[6:10] /= math.sqrt(float(xn[6:10] @ xn[6:10]))      # quaternion re-normalisation
        return xn

    # ------------------------------------------------------------------ diagnostics
    def energy(self, x) -> tuple[float, float]:
        """(kinetic, potential) mechanical energy; potential relative to z = 0."""
        v, w = x[3:6], x[10:13]
        ke = 0.5 * self.m * float(v @ v) + 0.5 * float(w @ self.J @ w)
        return ke, self.m * self.g * float(x[2])

    def angular_momentum_world(self, x) -> np.ndarray:
        return quat.to_rot(x[6:10]) @ (self.J @ x[10:13])
