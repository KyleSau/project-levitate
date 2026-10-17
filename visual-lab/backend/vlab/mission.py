"""Mission autopilot: a reactive state machine that produces *controller references* (setpoints).

The reference is only the controller's setpoint. The vehicle's motion is produced exclusively by the
integrated forces and torques of the plant; nothing here moves the vehicle. Reference segments are
quintic (minimum-jerk) polynomials that start from the current reference (or, for braking and takeoff,
from the measured state) so that setpoints are continuous.

Takeoff / landing logic uses the simulated landing-gear contact sensor (total normal contact force):
  * touchdown is declared when contact force > 5 % of weight for 100 ms (gaps < 30 ms tolerated)
    during a landing step; the descent setpoint stops at first contact;
  * then throttle is ramped to zero over 0.4 s (spool-down) and the motors are disarmed;
  * lift-off is reported when contact force vanishes during a takeoff.
"""
from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel

from .controller import Reference


class Step(BaseModel):
    kind: Literal["idle", "arm", "takeoff", "hold", "goto", "accelerate", "cruise", "coast", "brake", "land"]
    duration_s: float = 1.0
    alt_m: float | None = None                 # takeoff: CG altitude target
    target: tuple[float, float, float] | None = None
    rel: tuple[float, float, float] | None = None
    vel: tuple[float, float, float] | None = None
    yaw_deg: float | None = None
    descent_rate_m_s: float = 0.12
    segment: str = ""
    label: str = ""


def demo_mission(alt: float = 0.30, alt2: float = 0.25, v_fwd: float = 0.8) -> list[Step]:
    return [
        Step(kind="idle", duration_s=0.8, segment="A", label="A  on ground, disarmed: contact force carries weight"),
        Step(kind="arm", duration_s=0.5, segment="A", label="A  arm: spin-up, thrust ramps to weight"),
        Step(kind="takeoff", duration_s=2.5, alt_m=alt, segment="A", label="A  takeoff to target altitude"),
        Step(kind="hold", duration_s=3.0, segment="B", label="B  stable hover (gust impulse at +1.2 s)"),
        Step(kind="accelerate", duration_s=1.3, vel=(v_fwd, 0, 0), segment="C", label="C  forward flight: accelerate (pitch forward)"),
        Step(kind="cruise", duration_s=1.2, vel=(v_fwd, 0, 0), segment="C", label="C  forward flight: cruise"),
        Step(kind="coast", duration_s=1.2, segment="D", label="D  forward command removed: level attitude, momentum persists"),
        Step(kind="brake", duration_s=1.5, segment="D", label="D  active braking (pitch back)"),
        Step(kind="hold", duration_s=1.4, segment="D", label="D  stabilise"),
        Step(kind="goto", duration_s=3.0, rel=(0, 0.30, 0), yaw_deg=90, segment="E", label="E  lateral move + yaw 90 deg"),
        Step(kind="hold", duration_s=1.5, segment="E", label="E  stabilise"),
        Step(kind="land", duration_s=1.5, segment="F", label="F  controlled descent, contact detection, landing"),
        Step(kind="arm", duration_s=0.5, segment="G", label="G  re-arm"),
        Step(kind="takeoff", duration_s=2.5, alt_m=alt2, segment="G", label="G  second takeoff"),
        Step(kind="hold", duration_s=3.0, segment="G", label="G  stable hover"),
    ]


def quintic(p0, v0, a0, p1, v1, a1, T):
    """Coefficients c[0..5] (each array-like) of p(t) = sum c_k t^k meeting the boundary conditions."""
    p0, v0, a0, p1, v1, a1 = map(lambda z: np.asarray(z, float), (p0, v0, a0, p1, v1, a1))
    T2, T3, T4, T5 = T * T, T ** 3, T ** 4, T ** 5
    c0, c1, c2 = p0, v0, a0 / 2
    d = p1 - (c0 + c1 * T + c2 * T2)
    e = v1 - (c1 + 2 * c2 * T)
    f = a1 - 2 * c2
    c3 = (10 * d - 4 * e * T + 0.5 * f * T2) / T3
    c4 = (-15 * d + 7 * e * T - f * T2) / T4
    c5 = (6 * d - 3 * e * T + 0.5 * f * T2) / T5
    return [c0, c1, c2, c3, c4, c5]


def eval_quintic(c, t):
    p = c[0] + t * (c[1] + t * (c[2] + t * (c[3] + t * (c[4] + t * c[5]))))
    v = c[1] + t * (2 * c[2] + t * (3 * c[3] + t * (4 * c[4] + t * 5 * c[5])))
    a = 2 * c[2] + t * (6 * c[3] + t * (12 * c[4] + t * 20 * c[5]))
    return p, v, a


class Autopilot:
    def __init__(self, steps: list[Step], weight_n: float, ground_cg_height_m: float, x0: np.ndarray):
        self.steps = steps
        self.W = weight_n
        self.hz = ground_cg_height_m
        self.i = -1
        self.events: list[dict] = []
        self.p = x0[0:3].copy()
        self.v = np.zeros(3)
        self.a = np.zeros(3)
        self.yaw = 0.0
        self.armed = False
        self.throttle = 0.0
        self.contact_timer = 0.0
        self.sub = "none"
        self.done = False
        self.airborne = False
        self.phase_t0 = 0.0
        self.takeoff_count = 0
        self.landing_count = 0

    def event(self, t, kind, msg):
        self.events.append({"t": round(t, 4), "kind": kind, "message": msg})

    @property
    def step(self) -> Step | None:
        return self.steps[self.i] if 0 <= self.i < len(self.steps) else None

    def _enter(self, t, meas):
        self.i += 1
        self.t0 = t
        s = self.step
        if s is None:
            self.done = True
            return
        pm, vm = meas[0:3], meas[3:6]
        self.sub = s.kind
        if s.kind in ("idle",):
            self.armed = False
            self.throttle = 0.0
            self.p, self.v, self.a = pm.copy(), np.zeros(3), np.zeros(3)
        elif s.kind == "arm":
            self.armed = True
            self.p, self.v, self.a = pm.copy(), np.zeros(3), np.zeros(3)
            self.event(t, "ARM", "motors armed; spin-up")
        elif s.kind == "takeoff":
            start = pm.copy()
            tgt = np.array([pm[0], pm[1], s.alt_m])
            self.c = quintic(start, 0 * start, 0 * start, tgt, 0 * start, 0 * start, s.duration_s)
            self.event(t, "TAKEOFF_CMD", f"takeoff to CG altitude {s.alt_m:.3f} m")
        elif s.kind == "goto":
            tgt = np.array(s.target) if s.target is not None else self.p + np.array(s.rel or (0, 0, 0))
            self.c = quintic(self.p, self.v, self.a, tgt, np.zeros(3), np.zeros(3), s.duration_s)
            y1 = math.radians(s.yaw_deg) if s.yaw_deg is not None else self.yaw
            self.cy = quintic(self.yaw, 0.0, 0.0, y1, 0.0, 0.0, s.duration_s)
        elif s.kind == "accelerate":
            v1 = np.array(s.vel)
            p1 = self.p + (self.v + v1) * s.duration_s / 2
            self.c = quintic(self.p, self.v, self.a, p1, v1, np.zeros(3), s.duration_s)
        elif s.kind == "cruise":
            self.cp0 = self.p.copy()
            self.cv = np.array(s.vel)
        elif s.kind == "coast":
            self.event(t, "COMMAND_REMOVED", "horizontal command removed: attitude levelled, no horizontal thrust")
        elif s.kind == "brake":
            p0 = np.array([pm[0], pm[1], self.p[2]])
            v0 = np.array([vm[0], vm[1], 0.0])
            p1 = p0 + v0 * s.duration_s / 2
            self.c = quintic(p0, v0, np.zeros(3), p1, np.zeros(3), np.zeros(3), s.duration_s)
            self.event(t, "BRAKE", f"active braking from {math.hypot(vm[0], vm[1]):.3f} m/s")
        elif s.kind == "land":
            z1 = self.hz + 0.02
            T1 = max(1.0, 1.8 * abs(self.p[2] - z1) / s.descent_rate_m_s)
            self.c = quintic(self.p, self.v, self.a, np.array([self.p[0], self.p[1], z1]),
                             np.array([0, 0, -s.descent_rate_m_s]), np.zeros(3), T1)
            self.T1 = T1
            self.sub = "descent"
            self.contact_timer = 0.0
            self.event(t, "LAND_CMD", "controlled descent")
        else:  # hold
            self.v, self.a = np.zeros(3), np.zeros(3)

    def update(self, t: float, meas: np.ndarray, contact_n: float, dt: float) -> Reference:
        if self.i < 0:
            self._enter(t, meas)
        s = self.step
        while s is not None and self._finished(t):
            self._enter(t, meas)
            s = self.step
        on_ground = contact_n > 0.3 * self.W
        # lift-off / touchdown reporting (independent of mission)
        if self.armed and self.airborne is False and contact_n == 0.0 and meas[2] > self.hz + 0.003:
            self.airborne = True
            self.takeoff_count += 1
            self.event(t, "LIFTOFF", "contact force vanished: vehicle airborne")
        if self.airborne and contact_n > 0.0:
            self.airborne = False
            self.event(t, "CONTACT", f"ground contact, normal force {contact_n:.3f} N")
        if s is None:
            return Reference(p=tuple(self.p), yaw=self.yaw, armed=self.armed, throttle_scale=self.throttle)
        tau = t - self.t0
        horizontal = True
        freeze = on_ground and s.kind in ("idle", "arm", "takeoff", "land")
        if s.kind == "idle":
            self.p = meas[0:3].copy()
        elif s.kind == "arm":
            self.throttle = min(1.0, tau / max(s.duration_s, 1e-6))
            # reference just below the resting height keeps the board seated while spinning up
            self.p = np.array([meas[0], meas[1], self.hz - 0.002])
        elif s.kind == "takeoff":
            self.throttle = 1.0
            self.p, self.v, self.a = eval_quintic(self.c, min(tau, s.duration_s))
            if tau >= s.duration_s - dt and meas[2] < self.hz + 0.25 * (s.alt_m - self.hz):
                if not any(e["kind"] == "TAKEOFF_FAILED" and e["t"] > self.t0 for e in self.events):
                    self.event(t, "TAKEOFF_FAILED", f"altitude {meas[2]:.3f} m after takeoff window: insufficient thrust")
                    self.event(t, "MISSION_ABORT", "takeoff failed: motors disarmed, mission aborted")
                    self.steps = self.steps[:self.i + 1] + [Step(kind="idle", duration_s=2.0, segment="X",
                                                                   label="X  mission aborted (cannot take off)")]
        elif s.kind in ("goto", "accelerate", "brake"):
            self.p, self.v, self.a = eval_quintic(self.c, min(tau, s.duration_s))
            if s.kind == "goto":
                y, _, _ = eval_quintic(self.cy, min(tau, s.duration_s))
                self.yaw = float(y)
        elif s.kind == "cruise":
            self.p = self.cp0 + self.cv * tau
            self.v, self.a = self.cv.copy(), np.zeros(3)
        elif s.kind == "coast":
            horizontal = False
            self.p = np.array([meas[0], meas[1], self.p[2]])
            self.v = np.array([meas[3], meas[4], 0.0])
            self.a = np.zeros(3)
        elif s.kind == "land":
            self._land(t, tau, s, meas, contact_n, dt)
            freeze = freeze or self.sub != "descent"
        else:
            self.v, self.a = np.zeros(3), np.zeros(3)
        return Reference(p=tuple(self.p), v=tuple(self.v), a=tuple(self.a), yaw=self.yaw, horizontal_control=horizontal,
                         armed=self.armed, throttle_scale=self.throttle, freeze_integrators=freeze)

    def _land(self, t, tau, s, meas, contact_n, dt):
        if self.sub == "descent":
            if tau <= self.T1:
                self.p, self.v, self.a = eval_quintic(self.c, tau)
            else:
                self.v = np.array([0.0, 0.0, -s.descent_rate_m_s])
                self.a = np.zeros(3)
                self.p = self.p + self.v * dt
            if contact_n > 0.05 * self.W:
                self.contact_timer += dt
                self.gap_timer = 0.0
                # first contact: stop driving the setpoint further into the ground
                self.p = np.array([self.p[0], self.p[1], min(self.p[2], self.hz - 0.01)])
                self.v = np.zeros(3)
            else:
                self.gap_timer = getattr(self, "gap_timer", 0.0) + dt
                if self.gap_timer > 0.03:
                    self.contact_timer = 0.0
            if self.contact_timer >= 0.10:
                self.sub = "spooldown"
                self.t_sub = t
                self.v, self.a = np.zeros(3), np.zeros(3)
                self.landing_count += 1
                self.event(t, "TOUCHDOWN", f"touchdown confirmed (contact {contact_n:.3f} N, > 5% of weight for 100 ms)")
        elif self.sub == "spooldown":
            self.throttle = max(0.0, 1.0 - (t - self.t_sub) / 0.4)
            if self.throttle <= 0.0:
                self.sub = "landed"
                self.t_sub = t
                self.armed = False
                self.event(t, "LANDED", "spool-down complete, motors disarmed; weight carried by ground contact")
        if self.sub == "landed":
            self.p = meas[0:3].copy()

    # ------------------------------------------------------------------ live commands
    def command(self, t: float, kind: str, rel=None, yaw_deg=None, alt_m=None, speed_m_s: float = 0.35) -> str:
        """Interactive command: replaces the remaining mission. Returns '' or a reason for refusal.
        Commands only change controller set-points; the motion still comes from the integrated forces."""
        s = self.step
        landed = not self.armed
        if kind == "goto":
            if landed:
                return "vehicle is landed/disarmed: take off first"
            rel = np.array(rel or (0, 0, 0), float)
            tgt = self.p + rel
            tgt[2] = max(tgt[2], self.hz + 0.03)
            dist = float(np.linalg.norm(tgt - self.p))
            dur = max(1.2, 1.875 * dist / speed_m_s)       # quintic peak speed = 1.875 * mean speed
            yaw = self.yaw if yaw_deg is None else math.radians(yaw_deg)
            new = [Step(kind="goto", duration_s=dur, target=tuple(tgt), yaw_deg=math.degrees(yaw), segment="L",
                        label=f"L  live: goto {np.round(tgt, 3).tolist()} m"),
                   Step(kind="hold", duration_s=1e9, segment="L", label="L  live: hover, awaiting commands")]
        elif kind == "land":
            if landed:
                return "already landed"
            new = [Step(kind="land", duration_s=1e9, segment="L", label="L  live: controlled descent and landing")]
        elif kind == "takeoff":
            if not landed or (s is not None and s.kind == "land" and self.sub != "landed"):
                return "already flying"
            new = [Step(kind="arm", duration_s=0.5, segment="L", label="L  live: arm"),
                   Step(kind="takeoff", duration_s=2.0, alt_m=alt_m or 0.25, segment="L", label="L  live: takeoff"),
                   Step(kind="hold", duration_s=1e9, segment="L", label="L  live: hover, awaiting commands")]
        else:
            return f"unknown command {kind}"
        self.steps = self.steps[: self.i + 1] + new
        self._force_next = True
        self.event(t, "COMMAND", f"live command: {kind}" + (f" {list(rel)}" if rel is not None else ""))
        return ""

    def _finished(self, t) -> bool:
        s = self.step
        if s is None:
            return False
        if getattr(self, "_force_next", False):
            self._force_next = False
            return True
        if s.kind == "land":
            return self.sub == "landed" and t - self.t_sub >= s.duration_s
        return t - self.t0 >= s.duration_s - 1e-9

    def phase_label(self) -> tuple[int, str, str]:
        s = self.step
        if s is None:
            return len(self.steps), "end", "mission complete"
        lab = s.label or s.kind
        if s.kind == "land" and self.sub != "descent":
            lab = f"{lab} [{self.sub}]"
        return self.i, s.segment, lab
