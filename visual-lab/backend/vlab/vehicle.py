"""Vehicle definition: geometry, mass distribution -> (mass, CG, inertia tensor), actuators.

Mass properties are never typed in independently of the mass distribution: the vehicle is a list of
mass components (solid boxes or point masses) and mass, CG and the inertia tensor about the CG are
always *derived* from it (parallel-axis theorem). Changing total mass scales every component; moving
the CG moves the designated CG-trim component. Both therefore update the inertia tensor consistently.

The only exception is an imported vehicle (levitate.experiment-result/v1 `vehicle` block) that ships
its own inertia about the CG; that tensor is used verbatim, checked for physical validity, and scaled
proportionally if the total mass is later changed (uniform-density scaling assumption).
"""
from __future__ import annotations

import itertools
import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, field_validator

Vec3 = tuple[float, float, float]


class MassComponent(BaseModel):
    name: str
    mass_kg: float = Field(ge=0)
    pos_m: Vec3 = (0.0, 0.0, 0.0)          # centroid in body geometric frame (origin = deck centre)
    size_m: Vec3 = (0.0, 0.0, 0.0)         # solid box edge lengths (x, y, z); zeros = point mass
    group: str = "structure"
    cg_trim: bool = False                  # the component moved to achieve a requested CG


class Actuator(BaseModel):
    name: str
    pos_m: Vec3                            # point of force application, body geometric frame
    axis: Vec3 = (0.0, 0.0, 1.0)           # unit force direction, body frame
    max_force_n: float = 1.0
    min_force_n: float = 0.0
    spin: int = 0                          # +1 CCW seen from above, -1 CW, 0 none
    torque_ratio_m: float = 0.0            # reaction torque / force (rotors): tau = -spin * k * F * axis
    time_constant_s: float = 0.0           # first-order force lag (0 = instantaneous)
    mechanism: str = "hypothetical"        # physical momentum-exchange mechanism or 'hypothetical'
    radius_m: float = 0.011                # rotor radius (power model / ground effect)

    @field_validator("max_force_n", "min_force_n", mode="before")
    @classmethod
    def _null_is_unbounded(cls, v, info):
        """JSON has no infinity: null means unbounded (+inf for max, -inf for min)."""
        if v is None:
            return math.inf if info.field_name == "max_force_n" else -math.inf
        return v


class DragModel(BaseModel):
    """Quadratic body-axis drag  F_i = -1/2 rho Cd_i A_i v_i |v_i|  (v = body-frame air-relative velocity),
    A_x = W H, A_y = L H, A_z = L W.  Cd: flat plate normal to flow 1.17 (Hoerner 1965, Fluid-Dynamic Drag
    3-16), blunt rectangular edge-on sections ~1.05.  Rotational damping from strip theory on a flat plate:
    tau_i = -k_i w_i |w_i|, k_x = rho Cd_rot L W^4 / 64 (roll), k_y = rho Cd_rot W L^4 / 64 (pitch),
    k_z = rho Cd_rot H (L^4 + W^4)/64 (yaw, edges only)."""
    enabled: bool = True
    cd_x: float = 1.05
    cd_y: float = 1.05
    cd_z: float = 1.17
    cd_rot: float = 1.17


class ContactModel(BaseModel):
    """Compliant penalty contact at the 8 corners of the deck box against the plane z = 0.
    Normal: N = max(0, k d - c d_dot) (no adhesion). Tangential: viscous-capped Coulomb
    F_t = -v_t min(c_t, mu N / |v_t|), which never exceeds mu N and is integrator-stable."""
    stiffness_n_per_m: float = 1000.0      # per corner at the 20 g reference mass -> 49 um static sag
    damping_n_s_per_m: float = 3.0         # per corner, ~0.67 of critical for the heave mode (|lambda dt| < 0.9 at 1 ms)
    friction_coeff: float = 0.5
    tangential_damping_n_s_per_m: float = 2.0
    scale_with_mass: bool = True           # k, c scaled by m / 20 g: same sag, same contact frequency
    reference_mass_kg: float = 0.020


class PowerModel(BaseModel):
    """Electrical power per actuator (rotor types): P = T^1.5 k_duct / (FM sqrt(2 rho A)) / (eta_motor eta_esc).
    Defaults are Agent A's nominal assumptions (backend/levitate/catalog.py): FM 0.42 (Bohorquez & Pines 2003),
    duct effectiveness 0.5 -> k_duct = 1 - 0.5 (1 - 1/sqrt 2) = 0.854, brushless 0702 eta 0.65, avionics 0.45 W."""
    figure_of_merit: float = 0.42
    duct_factor: float = 0.8536
    motor_efficiency: float = 0.65
    esc_efficiency: float = 1.0
    avionics_w: float = 0.45
    ionic_thrust_per_power_n_per_w: float = 0.005   # EAD only (assumption; replace with Agent A solver value)


class VehicleConfig(BaseModel):
    name: str = "techdeck-hoverboard"
    length_m: float = 0.100
    width_m: float = 0.032
    height_m: float = 0.009
    components: list[MassComponent]
    actuators: list[Actuator]
    inertia_override_kgm2: list[list[float]] | None = None   # imported rigid body (about CG)
    cg_override_m: Vec3 | None = None
    drag: DragModel = Field(default_factory=DragModel)
    contact: ContactModel = Field(default_factory=ContactModel)
    power: PowerModel = Field(default_factory=PowerModel)
    added_mass_kg: Vec3 = (0.0, 0.0, 0.0)                   # body-axis added mass (from FEM ROM if enabled)
    source: str = "visual_lab.default"


class MassProperties(BaseModel):
    mass_kg: float
    cg_m: Vec3
    inertia_kgm2: list[list[float]]
    principal_moments_kgm2: Vec3
    valid: bool
    issues: list[str]
    weight_n: float


def box_inertia(m: float, a: float, b: float, c: float) -> np.ndarray:
    """Solid cuboid about its centroid, edges a (x), b (y), c (z)."""
    return np.diag([m * (b * b + c * c) / 12, m * (a * a + c * c) / 12, m * (a * a + b * b) / 12])


def check_inertia(J: np.ndarray) -> list[str]:
    issues = []
    if not np.allclose(J, J.T, atol=1e-15 + 1e-9 * np.abs(J).max()):
        issues.append("inertia tensor not symmetric")
    ev = np.linalg.eigvalsh(0.5 * (J + J.T))
    if np.any(ev <= 0):
        issues.append("inertia tensor not positive definite")
    a, b, c = sorted(ev)
    if a + b < c * (1 - 1e-9):
        issues.append("principal moments violate triangle inequality (I1 + I2 >= I3)")
    return issues


def mass_properties(v: VehicleConfig, g: float = 9.80665) -> MassProperties:
    m = np.array([c.mass_kg for c in v.components])
    r = np.array([c.pos_m for c in v.components], float)
    total = float(m.sum())
    if total <= 0:
        raise ValueError("vehicle has no mass")
    cg = (m[:, None] * r).sum(axis=0) / total if v.cg_override_m is None else np.array(v.cg_override_m)
    if v.inertia_override_kgm2 is not None:
        J = np.array(v.inertia_override_kgm2, float)
    else:
        J = np.zeros((3, 3))
        for c, mi, ri in zip(v.components, m, r):
            d = ri - cg
            J += box_inertia(mi, *c.size_m) + mi * (np.dot(d, d) * np.eye(3) - np.outer(d, d))
    issues = check_inertia(J)
    ev = np.linalg.eigvalsh(0.5 * (J + J.T))
    return MassProperties(mass_kg=total, cg_m=tuple(cg.tolist()), inertia_kgm2=J.tolist(),
                          principal_moments_kgm2=tuple(ev.tolist()), valid=not issues, issues=issues,
                          weight_n=total * g)


# ------------------------------------------------------------------------------ default vehicle
def staggered_positions(length_m: float, rotor_diameter_m: float = 0.022, lateral_offset_m: float = 0.004,
                        duct_wall_m: float = 0.0007, tip_gap_m: float = 0.0004, n: int = 4) -> list[Vec3]:
    """Agent A's baseline 'staggered' layout (backend/levitate/design.py rotor_layout): rotor centres evenly
    spread along x within the deck, alternating +-lateral offset in y."""
    r_out = rotor_diameter_m / 2 + tip_gap_m + duct_wall_m
    half = length_m / 2 - r_out - 0.001
    xs = np.linspace(-half, half, n)
    return [(float(x), lateral_offset_m if i % 2 == 0 else -lateral_offset_m, 0.0) for i, x in enumerate(xs)]


def best_spin_pattern(pos: list[Vec3], kappa: float = 0.006) -> list[int]:
    """Balanced spin pattern maximising the smallest singular value of the normalised [Fz, tx, ty, tz] map."""
    n = len(pos)
    P = np.asarray(pos)
    best, score_best = [1] * n, -1.0
    for pat in itertools.product((1, -1), repeat=n):
        if pat[0] != 1 or abs(sum(pat)) > n % 2:
            continue
        B = np.vstack([np.ones(n), P[:, 1], -P[:, 0], -kappa * np.asarray(pat, float)])
        Bn = B / np.maximum(np.abs(B).max(axis=1, keepdims=True), 1e-12)
        s = float(np.linalg.svd(Bn, compute_uv=False)[-1])
        if s > score_best + 1e-12:
            best, score_best = list(pat), s
    return best


PropulsionKind = Literal["hypothetical_ideal", "ducted_rotor", "open_rotor", "ionic_wind"]


def default_vehicle(total_mass_kg: float = 0.020, cg_m: Vec3 | None = None, length_m: float = 0.100,
                    width_m: float = 0.032, height_m: float = 0.009, rotor_diameter_m: float = 0.022,
                    propulsion: PropulsionKind = "hypothetical_ideal") -> VehicleConfig:
    """20 g Tech-Deck-sized board: deck shell 7 g, 4 propulsion modules 1.5 g, avionics 2 g, CG-trim bay 5 g."""
    L, W, H = length_m, width_m, height_m
    pos = staggered_positions(L, rotor_diameter_m)
    spins = best_spin_pattern(pos)
    mech = {"hypothetical_ideal": "hypothetical", "ducted_rotor": "ducted rotor (air momentum)",
            "open_rotor": "open rotor (air momentum)", "ionic_wind": "electroaerodynamic ionic wind (air momentum)"}
    acts = [Actuator(name=f"A{i}", pos_m=p, axis=(0.0, 0.0, 1.0), max_force_n=math.inf, spin=s,
                     torque_ratio_m=0.006, time_constant_s=0.0, mechanism=mech[propulsion],
                     radius_m=rotor_diameter_m / 2) for i, (p, s) in enumerate(zip(pos, spins))]
    comps = [MassComponent(name="deck shell (uniform box approx.)", mass_kg=0.007, pos_m=(0, 0, 0), size_m=(L, W, H)),
             *[MassComponent(name=f"propulsion module {i}", mass_kg=0.0015, pos_m=p, size_m=(0.007, 0.007, 0.007),
                             group="propulsion") for i, p in enumerate(pos)],
             MassComponent(name="avionics", mass_kg=0.002, pos_m=(0, 0, H / 2 - 0.002), size_m=(0.02, 0.02, 0.004),
                           group="avionics"),
             MassComponent(name="payload / CG-trim bay", mass_kg=0.005, pos_m=(0, 0, -H / 2 + 0.00275),
                           size_m=(0.030, 0.012, 0.0055), group="payload", cg_trim=True)]
    v = VehicleConfig(length_m=L, width_m=W, height_m=H, components=comps, actuators=acts)
    v = scale_total_mass(v, total_mass_kg)
    if cg_m is not None:
        v = set_cg(v, cg_m)
    return v


def scale_total_mass(v: VehicleConfig, total_mass_kg: float) -> VehicleConfig:
    """Scale every component mass (and an imported inertia) by the same factor: shape of the mass
    distribution preserved, so CG is unchanged and inertia scales linearly with mass."""
    if total_mass_kg <= 0:
        raise ValueError("total mass must be positive")
    cur = sum(c.mass_kg for c in v.components)
    k = total_mass_kg / cur
    out = v.model_copy(deep=True)
    for c in out.components:
        c.mass_kg *= k
    if out.inertia_override_kgm2 is not None:
        out.inertia_override_kgm2 = (np.array(out.inertia_override_kgm2) * k).tolist()
    return out


def set_cg(v: VehicleConfig, cg_m: Vec3) -> VehicleConfig:
    """Move the CG-trim component so that the composite CG equals `cg_m` (geometric frame).
    Raises ValueError if that would put the component outside the deck envelope."""
    out = v.model_copy(deep=True)
    if out.inertia_override_kgm2 is not None:
        raise ValueError("imported rigid body: its inertia is given about its own CG; moving the CG without a mass "
                         "distribution would violate consistency - edit the source design instead")
    trims = [c for c in out.components if c.cg_trim]
    if not trims:
        raise ValueError("vehicle has no CG-trim component")
    t = trims[0]
    M = sum(c.mass_kg for c in out.components)
    rest = sum(np.array(c.pos_m) * c.mass_kg for c in out.components if c is not t)
    if t.mass_kg <= 0:
        raise ValueError("CG-trim component has zero mass")
    new = (np.asarray(cg_m) * M - rest) / t.mass_kg
    lim = np.array([out.length_m, out.width_m, out.height_m]) / 2 - np.array(t.size_m) / 2
    if np.any(np.abs(new) > lim + 1e-12):
        reach = (lim * t.mass_kg + np.abs(rest)) / M
        raise ValueError(f"CG {[round(float(c) * 1000, 2) for c in cg_m]} mm not reachable by moving the "
                         f"{t.mass_kg * 1000:.2f} g trim mass inside the deck (approx. reach "
                         f"+-{np.round(reach * 1000, 2).tolist()} mm); add ballast or move components")
    t.pos_m = tuple(new.tolist())
    return out


def corners_geom(v: VehicleConfig) -> np.ndarray:
    L, W, H = v.length_m / 2, v.width_m / 2, v.height_m / 2
    return np.array([(sx * L, sy * W, sz * H) for sz in (-1, 1) for sx in (-1, 1) for sy in (-1, 1)])
