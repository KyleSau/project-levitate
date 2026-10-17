"""Parametric hoverboard design: schema, rotor layout geometry and control allocation.

Body frame: x forward (along board length), y left (across width), z up. Origin at the
geometric centre of the deck mid-plane. Lengths in the schema are mm; physics is SI.
"""
from __future__ import annotations

import itertools
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from .catalog import BATTERIES, ELECTRONICS, MATERIALS, MOTORS


class Design(BaseModel):
    name: str = "baseline"
    # envelope
    length_mm: float = Field(100.0, ge=40, le=200)
    width_mm: float = Field(32.0, ge=15, le=120)
    board_height_mm: float = Field(9.0, ge=3, le=30, description="total deck thickness = duct height")
    skin_mm: float = Field(0.8, ge=0.3, le=3)
    wall_mm: float = Field(0.7, ge=0.3, le=3)
    deck_material: str = "pla_fdm"
    # propulsion
    propulsion: Literal["ducted_rotor", "open_rotor"] = "ducted_rotor"
    layout: Literal["staggered", "grid", "inline"] = "staggered"
    n_rotors: int = Field(4, ge=2, le=8)
    rotor_diameter_mm: float = Field(22.0, ge=8, le=60)
    lateral_offset_mm: float = Field(4.0, ge=0, le=30, description="staggered layout: |y| of rotor centres")
    tip_gap_mm: float = Field(0.4, ge=0.1, le=3)
    motor: str = "bl_0702"
    battery: str = "lipo_1s_300"
    extra_payload_g: float = Field(0.0, ge=0, le=50, description="shell, LEDs, camera, ballast")
    # operating point
    hover_altitude_m: float = Field(0.30, ge=0.005, le=10)

    def validate_keys(self) -> list[str]:
        errs = []
        if self.motor not in MOTORS:
            errs.append(f"unknown motor '{self.motor}'")
        if self.battery not in BATTERIES:
            errs.append(f"unknown battery '{self.battery}'")
        if self.deck_material not in MATERIALS:
            errs.append(f"unknown material '{self.deck_material}'")
        return errs

    @property
    def electronics_key(self) -> str:
        return "aio_brushless_1s" if MOTORS[self.motor].kind == "brushless" else "aio_brushed_1s"

    @property
    def electronics(self):
        return ELECTRONICS[self.electronics_key]


class RotorLayout(BaseModel):
    positions_m: list[tuple[float, float, float]]
    spins: list[int]                  # +1 = CCW viewed from above, -1 = CW
    duct_inner_radius_m: float
    duct_outer_radius_m: float
    fits: bool
    fit_issues: list[str]


EDGE_MARGIN_MM = 1.0
MIN_DUCT_SEPARATION_MM = 0.6


def rotor_layout(d: Design) -> RotorLayout:
    issues: list[str] = []
    r_in = d.rotor_diameter_mm / 2 + (d.tip_gap_mm if d.propulsion == "ducted_rotor" else 0.0)
    r_out = r_in + (d.wall_mm if d.propulsion == "ducted_rotor" else 0.0)
    L, W, n = d.length_mm, d.width_mm, d.n_rotors
    half_len_avail = L / 2 - r_out - EDGE_MARGIN_MM
    if half_len_avail <= 0:
        issues.append("rotor larger than board length")
        half_len_avail = 0.0

    pts: list[tuple[float, float]] = []
    if d.layout == "grid":
        cols = 2
        rows = int(np.ceil(n / cols))
        y0 = W / 2 - r_out - EDGE_MARGIN_MM
        if y0 < r_out + MIN_DUCT_SEPARATION_MM / 2:
            issues.append(f"grid: two rotors of {d.rotor_diameter_mm} mm do not fit across {W} mm width")
        xs = np.linspace(-half_len_avail, half_len_avail, rows) if rows > 1 else np.array([0.0])
        for i in range(n):
            pts.append((float(xs[i // cols]), y0 if i % cols == 0 else -y0))
    else:
        off = d.lateral_offset_mm if d.layout == "staggered" else 0.0
        xs = np.linspace(-half_len_avail, half_len_avail, n) if n > 1 else np.array([0.0])
        for i in range(n):
            pts.append((float(xs[i]), off if i % 2 == 0 else -off))
        if abs(off) + r_out + EDGE_MARGIN_MM > W / 2 + 1e-9:
            issues.append(f"rotor at |y|={off} mm with outer radius {r_out:.1f} mm exceeds half-width {W/2} mm")

    # pairwise overlap
    min_sep = 2 * r_out + MIN_DUCT_SEPARATION_MM
    for (i, a), (j, b) in itertools.combinations(enumerate(pts), 2):
        dist = float(np.hypot(a[0] - b[0], a[1] - b[1]))
        if dist < min_sep - 1e-9:
            issues.append(f"rotors {i} and {j} overlap (centre distance {dist:.1f} mm < {min_sep:.1f} mm)")
            break

    pos_m = [(x / 1000, y / 1000, 0.0) for x, y in pts]
    spins = best_spin_pattern(pos_m)
    return RotorLayout(positions_m=pos_m, spins=spins, duct_inner_radius_m=r_in / 1000,
                       duct_outer_radius_m=r_out / 1000, fits=not issues, fit_issues=issues)


def allocation_matrix(positions_m, spins, kappa: float, cg=(0.0, 0.0, 0.0)) -> np.ndarray:
    """Map per-rotor thrusts u [N] -> [Fz, tau_x, tau_y, tau_z] about the CG.

    Rotor i at r_i pushes +z: tau = (r_i - cg) x (0,0,T) = (y T, -x T, 0).
    A rotor spinning CCW (+z) exerts reaction torque -kappa*T about z on the body.
    """
    P = np.asarray(positions_m, dtype=float) - np.asarray(cg, dtype=float)
    s = np.asarray(spins, dtype=float)
    return np.vstack([np.ones(len(P)), P[:, 1], -P[:, 0], -kappa * s])


def best_spin_pattern(positions_m, kappa: float = 0.006) -> list[int]:
    """Choose rotor spin directions maximising the smallest singular value of the
    (column-normalised) allocation matrix. Balanced patterns preferred (zero net yaw at equal thrust)."""
    n = len(positions_m)
    best, best_score = [1] * n, -1.0
    for pat in itertools.product((1, -1), repeat=n):
        if pat[0] != 1:      # mirror symmetry
            continue
        if abs(sum(pat)) > (n % 2):
            continue
        B = allocation_matrix(positions_m, pat, kappa)
        Bn = B / np.maximum(np.abs(B).max(axis=1, keepdims=True), 1e-12)
        score = float(np.linalg.svd(Bn, compute_uv=False)[-1]) if n >= 4 else 0.0
        if score > best_score + 1e-12:
            best, best_score = list(pat), score
    return best
