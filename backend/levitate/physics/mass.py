"""Mass budget, centre of gravity and inertia tensor from a component list."""
from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel

from ..catalog import BATTERIES, MATERIALS, MOTORS
from ..design import Design, RotorLayout


class MassItem(BaseModel):
    name: str
    group: str
    mass_g: float
    position_m: tuple[float, float, float]
    # principal inertia of the item about its own centroid [kg m^2]
    inertia_local: tuple[float, float, float] = (0.0, 0.0, 0.0)
    cost_usd: float = 0.0
    source: str = "computed"


class MassBudget(BaseModel):
    items: list[MassItem]
    total_g: float
    cg_m: tuple[float, float, float]
    inertia_kgm2: list[list[float]]
    by_group_g: dict[str, float]
    cost_usd: float


def _box_inertia(m: float, a: float, b: float, c: float) -> tuple[float, float, float]:
    """Solid box with sides a (x), b (y), c (z)."""
    return (m * (b * b + c * c) / 12, m * (a * a + c * c) / 12, m * (a * a + b * b) / 12)


def _ring_inertia(m: float, r: float, h: float) -> tuple[float, float, float]:
    """Thin cylindrical shell, axis z."""
    ixx = m * (r * r / 2 + h * h / 12)
    return (ixx, ixx, m * r * r)


def battery_dims_m(capacity_mah: float) -> tuple[float, float, float]:
    """Approximate pouch-cell envelope from capacity (volumetric ~ 0.3 Wh/cm^3 incl. packaging)."""
    vol_cm3 = capacity_mah * 3.7 / 1000 / 0.30
    t = 0.0055 if capacity_mah < 400 else 0.0065
    w = 0.012 if capacity_mah < 400 else 0.016
    length = vol_cm3 * 1e-6 / (t * w)
    return (length, w, t)


def build_mass_budget(d: Design, lay: RotorLayout, vals: dict[str, float]) -> MassBudget:
    mat = MATERIALS[d.deck_material]
    motor = MOTORS[d.motor]
    batt = BATTERIES[d.battery]
    elec = d.electronics
    rho = mat.density_kg_m3
    L, W, H = d.length_mm / 1000, d.width_mm / 1000, d.board_height_mm / 1000
    skin, wall = max(d.skin_mm, mat.min_wall_mm) / 1000, max(d.wall_mm, mat.min_wall_mm) / 1000
    n = len(lay.positions_m)
    ducted = d.propulsion == "ducted_rotor"
    r_in = lay.duct_inner_radius_m

    items: list[MassItem] = []
    # deck: top skin with rotor openings + perimeter wall (+ bottom skin rim of same width as wall)
    skin_area = max(L * W - n * math.pi * r_in ** 2, 0.2 * L * W)
    m_skin = rho * skin_area * skin
    items.append(MassItem(name="deck skin", group="structure", mass_g=m_skin * 1e3,
                          position_m=(0, 0, H / 2 - skin / 2), inertia_local=_box_inertia(m_skin, L, W, skin),
                          cost_usd=mat.cost_usd_per_cm3 * skin_area * skin * 1e6, source=f"{mat.name} density"))
    m_perim = rho * 2 * (L + W) * wall * H
    items.append(MassItem(name="perimeter wall", group="structure", mass_g=m_perim * 1e3, position_m=(0, 0, 0),
                          inertia_local=_box_inertia(m_perim, L, W, H) if m_perim else (0, 0, 0),
                          cost_usd=mat.cost_usd_per_cm3 * 2 * (L + W) * wall * H * 1e6, source=f"{mat.name} density"))
    for i, p in enumerate(lay.positions_m):
        if ducted:
            m_duct = rho * 2 * math.pi * (r_in + wall / 2) * wall * H
            items.append(MassItem(name=f"duct {i}", group="structure", mass_g=m_duct * 1e3, position_m=p,
                                  inertia_local=_ring_inertia(m_duct, r_in, H),
                                  cost_usd=mat.cost_usd_per_cm3 * 2 * math.pi * r_in * wall * H * 1e6))
            # motor mount spokes (3 x 1.2 mm wide struts across the duct)
            m_spoke = rho * 3 * r_in * 0.0012 * max(skin, 0.0008)
            items.append(MassItem(name=f"motor mount {i}", group="structure", mass_g=m_spoke * 1e3, position_m=p))
        else:
            # open rotor: arm + guard ring equivalent
            m_arm = rho * 0.003 * skin * math.hypot(p[0], p[1])
            items.append(MassItem(name=f"arm {i}", group="structure", mass_g=m_arm * 1e3,
                                  position_m=(p[0] / 2, p[1] / 2, 0)))
        mm = motor.mass_g / 1000
        items.append(MassItem(name=f"motor {i}", group="propulsion", mass_g=motor.mass_g, position_m=p,
                              inertia_local=_box_inertia(mm, 0.007, 0.007, 0.008), cost_usd=motor.cost_usd,
                              source=f"{motor.name} ({motor.status.value})"))
        m_prop_g = vals["prop_mass_coeff"] * (d.rotor_diameter_mm / 31.0) ** 2.5
        items.append(MassItem(name=f"rotor {i}", group="propulsion", mass_g=m_prop_g,
                              position_m=(p[0], p[1], p[2] + H / 4), cost_usd=0.5, source="scaled from 31 mm prop"))

    bl, bw, bt = battery_dims_m(batt.capacity_mah)
    mb = batt.mass_g / 1000
    items.append(MassItem(name=batt.name, group="energy", mass_g=batt.mass_g, position_m=(0, 0, -H / 2 + bt / 2),
                          inertia_local=_box_inertia(mb, bl, bw, bt), cost_usd=batt.cost_usd,
                          source=f"catalog ({batt.status.value})"))
    me = elec.mass_g / 1000
    items.append(MassItem(name=elec.name, group="avionics", mass_g=elec.mass_g, position_m=(0, 0, H / 2 - 0.002),
                          inertia_local=_box_inertia(me, 0.02, 0.02, 0.004), cost_usd=elec.cost_usd,
                          source=f"catalog ({elec.status.value})"))
    if d.extra_payload_g > 0:
        mp = d.extra_payload_g / 1000
        items.append(MassItem(name="payload / shell", group="payload", mass_g=d.extra_payload_g,
                              position_m=(0, 0, H / 2), inertia_local=_box_inertia(mp, L, W, 0.002)))

    # mass growth allowance on everything except the catalogued battery
    growth = vals["mass_growth"] - 1.0
    base = sum(it.mass_g for it in items if it.group != "energy")
    items.append(MassItem(name="wiring/glue/fasteners allowance", group="allowance", mass_g=base * growth,
                          position_m=(0, 0, 0), inertia_local=_box_inertia(base * growth / 1000, L / 2, W / 2, H),
                          source=f"mass growth x{vals['mass_growth']:.2f}"))

    m = np.array([it.mass_g / 1000 for it in items])
    r = np.array([it.position_m for it in items])
    total = float(m.sum())
    cg = (m[:, None] * r).sum(axis=0) / total
    J = np.zeros((3, 3))
    for mi, ri, it in zip(m, r, items):
        d_ = ri - cg
        J += np.diag(it.inertia_local) + mi * (np.dot(d_, d_) * np.eye(3) - np.outer(d_, d_))
    groups: dict[str, float] = {}
    for it in items:
        groups[it.group] = groups.get(it.group, 0.0) + it.mass_g
    return MassBudget(items=items, total_g=total * 1000, cg_m=tuple(cg.tolist()), inertia_kgm2=J.tolist(),
                      by_group_g=groups, cost_usd=sum(it.cost_usd for it in items))
