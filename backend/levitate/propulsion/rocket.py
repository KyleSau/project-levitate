"""Chemical-rocket BLACK-BOX propulsion model (theoretical comparison only).

An engine is described purely by external behaviour: maximum thrust F, sea-level specific impulse Isp, throttle range,
start/stop/restart rules, start delay, exhaust exit temperature, engine dry mass (thrust/weight) and tankage fraction.
  mdot = F / (Isp g0),  ue_eff = Isp g0,  propellant used = integral(mdot dt)
No propellant chemistry, hardware, construction or operating procedure is modelled. Classes and numbers are generic
published ranges (assumptions.rocket_assumptions); nothing here is build guidance.

Also: an air-breathing micro-turbojet comparator using the TSFC assumptions of `levitate.human_scale` (turbojet concept).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..constants import G0
from ..human_scale import human_assumptions
from .assumptions import rocket_assumptions
from .hazards import JetHazard, jet_hazard

EngineClass = Literal["monoprop", "biprop", "solid"]


class RocketEngineConfig(BaseModel):
    engine_class: EngineClass = "monoprop"
    n_engines: int = Field(4, ge=1, le=12)
    thrust_per_engine_n: float = Field(600.0, gt=1, le=50000)
    propellant_kg: float = Field(30.0, ge=0.0, le=2000)
    isp_override_s: float | None = None
    min_throttle_override: float | None = None


class EngineRules(BaseModel):
    isp_s: float
    min_throttle: float          # fraction of max thrust; 1.0 = not throttleable
    can_stop: bool
    max_starts: int              # including the first start
    start_delay_s: float
    exit_temp_k: float
    profile: Literal["throttle", "fixed"]


def engine_rules(cfg: RocketEngineConfig, vals: dict[str, float] | None = None) -> EngineRules:
    v = vals or rocket_assumptions().values()
    c = cfg.engine_class
    if c == "monoprop":
        r = EngineRules(isp_s=v["isp_mono"], min_throttle=v["min_throttle_mono"], can_stop=True, max_starts=1000,
                        start_delay_s=0.5 * v["start_delay_s"], exit_temp_k=v["texit_mono"], profile="throttle")
    elif c == "biprop":
        r = EngineRules(isp_s=v["isp_biprop"], min_throttle=v["min_throttle_biprop"], can_stop=True,
                        max_starts=1 + int(round(v["biprop_restarts"])), start_delay_s=v["start_delay_s"],
                        exit_temp_k=v["texit_biprop"], profile="throttle")
    else:
        r = EngineRules(isp_s=v["isp_solid"], min_throttle=1.0, can_stop=False, max_starts=1, start_delay_s=0.2,
                        exit_temp_k=v["texit_solid"], profile="fixed")
    if cfg.isp_override_s:
        r.isp_s = cfg.isp_override_s
    if cfg.min_throttle_override is not None and c != "solid":
        r.min_throttle = cfg.min_throttle_override
    return r


class RocketEngine:
    """One black-box engine with start/stop/throttle state. step() returns delivered thrust and mass flow."""

    def __init__(self, cfg: RocketEngineConfig, rules: EngineRules):
        self.cfg, self.r = cfg, rules
        self.F = cfg.thrust_per_engine_n
        self.reset()

    def reset(self):
        self.running = False
        self.starts = 0
        self.t_since_start = 0.0
        self.level = 0.0
        self.burned_out = False

    def command(self, u: float) -> None:
        """u <= 0: request stop; u > 0: request thrust fraction u (clamped to the throttle range)."""
        if u > 0 and not self.running and not self.burned_out and self.starts < self.r.max_starts:
            self.running = True
            self.starts += 1
            self.t_since_start = 0.0
        elif u <= 0 and self.running and self.r.can_stop:
            self.running = False
        self._u = u

    def step(self, dt: float, propellant_available: bool) -> tuple[float, float]:
        if self.running and not propellant_available:
            self.running = False
            self.burned_out = True
        if not self.running:
            self.level = 0.0
            return 0.0, 0.0
        self.t_since_start += dt
        ramp = min(1.0, self.t_since_start / max(self.r.start_delay_s, 1e-6))
        u = getattr(self, "_u", 1.0)
        target = 1.0 if self.r.profile == "fixed" else min(max(u, self.r.min_throttle), 1.0)
        self.level = ramp * target
        T = self.level * self.F
        return T, T / (self.r.isp_s * G0)


def engine_mass(cfg: RocketEngineConfig, vals: dict[str, float] | None = None) -> dict[str, float]:
    v = vals or rocket_assumptions().values()
    eng = cfg.n_engines * cfg.thrust_per_engine_n / (v["engine_tw"] * G0)
    tank = v["tankage_fraction"] * cfg.propellant_kg
    return {"engines": eng, "tankage": tank, "propellant": cfg.propellant_kg}


def rocket_cost(cfg: RocketEngineConfig, vals: dict[str, float] | None = None) -> dict[str, float]:
    v = vals or rocket_assumptions().values()
    return {"engines_usd": cfg.n_engines * cfg.thrust_per_engine_n * v["cost_engine_per_n"],
            "propellant_per_flight_usd": cfg.propellant_kg * v["cost_prop_per_kg"]}


def rocket_hazard(cfg: RocketEngineConfig, vals: dict[str, float] | None = None, throttle: float = 1.0) -> JetHazard:
    v = vals or rocket_assumptions().values()
    r = engine_rules(cfg, v)
    F = cfg.thrust_per_engine_n * throttle
    ue = r.isp_s * G0
    return jet_hazard(F, ue, r.exit_temp_k, F / ue, v["acoustic_eff"])


def hover_time_constant_tw(isp_s: float, m0: float, m1: float, g: float = G0) -> float:
    """Exact hover time at T = W (vertical, no drag): m(t) = m0 exp(-g t / (Isp g0)) -> t = (Isp g0 / g) ln(m0/m1)."""
    import math
    return isp_s * G0 / g * math.log(m0 / m1)


# ------------------------------------------------------------------------------- air-breathing comparator
class TurbojetComparator(BaseModel):
    tsfc_kg_per_n_h: float
    equivalent_isp_s: float
    engine_tw: float
    exhaust_velocity_m_s: float
    exhaust_temp_k: float
    hazard: JetHazard


def turbojet_comparator(thrust_n: float, scenario: str = "nominal") -> TurbojetComparator:
    v = human_assumptions().values(scenario)
    isp_eq = 3600.0 / (v["turbojet_tsfc"] * G0)        # fuel-only specific impulse (air is not carried)
    ue = v["turbojet_v_exhaust"]
    hz = jet_hazard(thrust_n, ue, 923.0, thrust_n / ue, rocket_assumptions().values()["acoustic_eff"])
    return TurbojetComparator(tsfc_kg_per_n_h=v["turbojet_tsfc"], equivalent_isp_s=isp_eq, engine_tw=v["turbojet_tw"],
                              exhaust_velocity_m_s=ue, exhaust_temp_k=923.0, hazard=hz)
