"""Lithium-polymer battery model: Thevenin source (V_oc, R_int) with derated usable energy."""
from __future__ import annotations

import math

from pydantic import BaseModel

V_OC_AVG_PER_CELL = 3.75    # mean open-circuit voltage over a 4.2 -> 3.3 V discharge
V_MIN_PER_CELL = 3.3        # low-voltage cutoff under load


class BatteryOperatingPoint(BaseModel):
    feasible: bool
    current_a: float
    terminal_v: float
    c_rate: float
    heat_w: float
    reason: str = ""


def operating_point(load_w: float, cells: int, r_int: float, capacity_mah: float) -> BatteryOperatingPoint:
    """Solve P_load = (V_oc - I R) I for the smaller root."""
    voc = V_OC_AVG_PER_CELL * cells
    disc = voc ** 2 - 4 * r_int * load_w
    if disc < 0:
        return BatteryOperatingPoint(feasible=False, current_a=math.inf, terminal_v=0, c_rate=math.inf,
                                     heat_w=math.inf, reason="load exceeds maximum power transfer of cell")
    i = (voc - math.sqrt(disc)) / (2 * r_int) if r_int > 0 else load_w / voc
    v = voc - i * r_int
    c = i / (capacity_mah / 1000)
    ok = v >= V_MIN_PER_CELL * cells
    return BatteryOperatingPoint(feasible=ok, current_a=i, terminal_v=v, c_rate=c, heat_w=i * i * r_int,
                                 reason="" if ok else f"terminal voltage {v:.2f} V below cutoff")


def max_deliverable_power(cells: int, r_int: float, capacity_mah: float, max_c: float) -> float:
    """Power at the lower of the C-rate limit and the voltage-cutoff limit."""
    voc = V_OC_AVG_PER_CELL * cells
    i_c = max_c * capacity_mah / 1000
    i_v = (voc - V_MIN_PER_CELL * cells) / r_int if r_int > 0 else math.inf
    i = min(i_c, i_v)
    return (voc - i * r_int) * i


def endurance_s(load_w: float, cells: int, r_int: float, capacity_mah: float, usable_fraction: float) -> float:
    op = operating_point(load_w, cells, r_int, capacity_mah)
    if not op.feasible:
        return 0.0
    energy_j = capacity_mah / 1000 * V_OC_AVG_PER_CELL * cells * 3600 * usable_fraction
    return energy_j / (load_w + op.heat_w)
