"""Gmsh + scikit-fem: 2-D potential flow around the deck cross-section -> added (fluid) mass ROM.

Physics. A body accelerating through still air must also accelerate the surrounding fluid. For inviscid,
irrotational flow the disturbance potential phi solves
    laplace(phi) = 0 in the fluid,   d(phi)/dn_f = U . n_f on the body,   phi -> 0 far away,
(n_f = outward normal of the fluid domain) and the added mass per unit length is the fluid kinetic energy
    m_a' = rho * integral |grad phi|^2 dA / U^2 = rho * integral_body (U . n_f) phi ds / U^2.
This is the classical, well-validated part of unsteady aerodynamics (Lamb 1932, Newman 1977); the result
is independent of viscosity, so it is valid for the board's accelerating manoeuvres.

Numerics. Gmsh (OpenCASCADE kernel) meshes the annulus between the body (rectangle W x H with optional
corner radius, ellipse, or circle) and a far-field circle of radius R = 40 a, graded from h = a/25 at the body.
scikit-fem assembles P2 Lagrange elements; phi = 0 Dirichlet on the far circle (truncation error O((a/R)^2)).

Validation (hard): circle (m_a' = rho pi a^2) and ellipse moving normal to its major axis
(m_a' = rho pi a^2, a = semi-axis perpendicular to motion), plus 2-level mesh convergence.
Literature cross-check (soft): square section C_A = 1.51 (Wendel 1956; DNV-RP-C205 Table A-1).

Reduced-order model: C_A(beta) = m_a' / (rho pi a^2) tabulated over the section aspect ratio
beta = (extent along motion)/(extent across motion); heave uses beta = H/W, sway beta = W/H.
3-D board: strip theory m_a = m_a' L (an upper bound - end effects reduce it; documented).
"""
from __future__ import annotations

import json
import math
import threading
import time

import numpy as np

from ..util import DATA, sanitize

ROM_PATH = DATA / "rom" / "added_mass.json"
FIELD_PATH = DATA / "rom" / "added_mass_field.json"
_gmsh_lock = threading.Lock()


def mesh_section(shape: str, a: float, b: float, R_over_a: float = 40.0, h_body_over_a: float = 1 / 25,
                 corner_radius: float = 0.0):
    """Mesh the fluid region around a body of half-extent a (across motion, x-axis of the 2-D plane)
    and b (along motion, y-axis), motion along +y. Returns (points 2xN, triangles 3xM)."""
    import gmsh
    with _gmsh_lock:
        gmsh.initialize(interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("section")
            occ = gmsh.model.occ
            R = R_over_a * a
            outer = occ.addDisk(0, 0, 0, R, R)
            if shape == "rect":
                body = occ.addRectangle(-a, -b, 0, 2 * a, 2 * b, roundedRadius=corner_radius if corner_radius > 0 else 0.0)
            elif shape == "ellipse":
                if a >= b:
                    body = occ.addDisk(0, 0, 0, a, b)
                else:
                    body = occ.addDisk(0, 0, 0, b, a)
                    occ.rotate([(2, body)], 0, 0, 0, 0, 0, 1, math.pi / 2)
            elif shape == "circle":
                body = occ.addDisk(0, 0, 0, a, a)
            else:
                raise ValueError(shape)
            occ.cut([(2, outer)], [(2, body)])
            occ.synchronize()
            curves = [c[1] for c in gmsh.model.getEntities(1)]
            body_curves = []
            for c in curves:
                bb = gmsh.model.getBoundingBox(1, c)
                if max(abs(v) for v in bb) < 0.5 * R:
                    body_curves.append(c)
            h0 = h_body_over_a * min(a, max(b, a / 4))
            f = gmsh.model.mesh.field
            d = f.add("Distance")
            f.setNumbers(d, "CurvesList", body_curves)
            f.setNumber(d, "Sampling", 400)
            t = f.add("Threshold")
            f.setNumber(t, "InField", d)
            f.setNumber(t, "SizeMin", h0)
            f.setNumber(t, "SizeMax", R / 8)
            f.setNumber(t, "DistMin", 0.2 * a)
            f.setNumber(t, "DistMax", R * 0.8)
            f.setNumber(t, "StopAtDistMax", 1)
            # smooth geometric growth instead of linear: second field on log scale via MathEval
            m = f.add("MathEval")
            f.setString(m, "F", f"Min({R / 8}, {h0} + 0.18*F{d})")
            mn = f.add("Min")
            f.setNumbers(mn, "FieldsList", [t, m])
            f.setAsBackgroundMesh(mn)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.model.mesh.generate(2)
            tags, coords, _ = gmsh.model.mesh.getNodes()
            etypes, _, enodes = gmsh.model.mesh.getElements(2)
            k = list(etypes).index(2)
            tri = np.asarray(enodes[k], dtype=np.int64).reshape(-1, 3)
            idx = {int(tg): i for i, tg in enumerate(tags)}
            pts = np.asarray(coords).reshape(-1, 3)[:, :2]
            tri = np.vectorize(idx.get)(tri)
            used = np.unique(tri)
            remap = -np.ones(len(pts), dtype=np.int64)
            remap[used] = np.arange(len(used))
            return pts[used].T.copy(), remap[tri].T.copy(), R
        finally:
            gmsh.finalize()


def solve_section(shape: str, a: float, b: float, refine: float = 1.0, corner_radius: float = 0.0, keep=False):
    """Return dict(m_coeff = integral |grad phi|^2 per unit U^2 (m^2), C_A, n_dofs, ...)."""
    from skfem import Basis, ElementTriP2, FacetBasis, LinearForm, MeshTri, asm, condense, solve
    from skfem.helpers import dot, grad
    from skfem.models.poisson import laplace
    p, t, R = mesh_section(shape, a, b, h_body_over_a=1 / 25 / refine, corner_radius=corner_radius)
    mesh = MeshTri(p, t)
    e = ElementTriP2()
    basis = Basis(mesh, e, intorder=4)
    mid = mesh.p[:, mesh.facets].mean(axis=1)
    bf = mesh.boundary_facets()
    r_mid = np.hypot(*mid[:, bf])
    outer = bf[r_mid > 0.5 * R]
    body = bf[r_mid <= 0.5 * R]
    fb = FacetBasis(mesh, e, facets=body, intorder=6)

    @LinearForm
    def rhs(v, w):
        return w.n[1] * v                       # U = (0, 1): g = U . n_f

    A = asm(laplace, basis)
    f = asm(rhs, fb)
    D = basis.get_dofs(outer).all()
    phi = solve(*condense(A, f, D=D))
    energy = float(phi @ A @ phi)               # integral |grad phi|^2
    flux = float(f @ phi)                       # integral_body g phi ds (must equal energy)
    out = {"shape": shape, "a": a, "b": b, "beta": b / a, "integral_grad2": energy, "boundary_form": flux,
           "C_A": energy / (math.pi * a * a), "n_dofs": int(basis.N), "n_elements": int(mesh.t.shape[1]),
           "R_over_a": R / a, "energy_identity_rel": abs(energy - flux) / energy}
    if keep:
        out["_basis"], out["_phi"], out["_mesh"] = basis, phi, mesh
    return out


def field_grid(sol: dict, u_half: float, v_half: float, n_u: int = 121, n_v: int = 81) -> dict:
    """Sample phi and |grad phi| (U = 1 m/s) on a regular grid from the FEM solution (null inside body)."""
    from skfem import Basis, ElementTriP1
    basis, phi, mesh = sol["_basis"], sol["_phi"], sol["_mesh"]
    u = np.linspace(-u_half, u_half, n_u)
    v = np.linspace(-v_half, v_half, n_v)
    U, V = np.meshgrid(u, v)
    pts = np.vstack([U.ravel(), V.ravel()])
    a, b, shape = sol["a"], sol["b"], sol["shape"]
    if shape == "rect":
        inside = (np.abs(pts[0]) <= a) & (np.abs(pts[1]) <= b)
    else:
        inside = (pts[0] / a) ** 2 + (pts[1] / b) ** 2 <= 1
    q = pts[:, ~inside]
    ib = Basis(mesh, ElementTriP1(), intorder=4)
    g = basis.interpolate(phi).grad
    gx = ib.project(g[0])
    gy = ib.project(g[1])
    vals_phi = np.full(pts.shape[1], np.nan)
    vals_spd = np.full(pts.shape[1], np.nan)
    Pq = basis.probes(q)
    Pl = ib.probes(q)
    vals_phi[~inside] = Pq @ phi
    vals_spd[~inside] = np.hypot(Pl @ gx, Pl @ gy)
    return {"u": u.tolist(), "v": v.tolist(),
            "phi": [[None if not np.isfinite(x) else float(x) for x in row] for row in vals_phi.reshape(n_v, n_u)],
            "speed": [[None if not np.isfinite(x) else float(x) for x in row] for row in vals_spd.reshape(n_v, n_u)]}


BETAS = [0.05, 0.1, 0.2, 0.28125, 0.4, 0.6, 1.0, 1.6, 2.5, 3.5556, 5.0, 10.0]


def build_rom(progress=None, W: float = 0.032, H: float = 0.009) -> dict:
    """Validate, then tabulate C_A(beta) for rectangles; export the deck-section heave field."""
    import gmsh
    import skfem
    t0 = time.perf_counter()
    checks = []
    a = 0.016
    c = solve_section("circle", a, a)
    e = abs(c["C_A"] - 1.0)
    checks.append({"check": "circle: m_a' = rho pi a^2 (C_A = 1)", "value": e, "limit": 5e-3, "passed": e < 5e-3,
                   "detail": f"C_A = {c['C_A']:.5f}, {c['n_dofs']} dofs"})
    for bb in (0.5 * a, 0.25 * a):
        el = solve_section("ellipse", a, bb)
        e = abs(el["C_A"] - 1.0)
        checks.append({"check": f"ellipse b/a = {bb / a:.2f} moving along minor axis: C_A = 1", "value": e,
                       "limit": 5e-3, "passed": e < 5e-3, "detail": f"C_A = {el['C_A']:.5f}"})
    el = solve_section("ellipse", 0.5 * a, a)
    e = abs(el["C_A"] - 1.0)     # moving along the major axis: m_a' = rho pi (a_perp)^2 -> C_A wrt a_perp = 1
    checks.append({"check": "ellipse moving along major axis: m_a' = rho pi (perpendicular semi-axis)^2", "value": e,
                   "limit": 5e-3, "passed": e < 5e-3, "detail": f"C_A = {el['C_A']:.5f}"})
    deck1 = solve_section("rect", W / 2, H / 2)
    deck2 = solve_section("rect", W / 2, H / 2, refine=2.0, keep=True)
    conv = abs(deck2["C_A"] / deck1["C_A"] - 1)
    checks.append({"check": "deck section mesh convergence (h -> h/2)", "value": conv, "limit": 5e-3,
                   "passed": conv < 5e-3, "detail": f"C_A {deck1['C_A']:.5f} -> {deck2['C_A']:.5f}"})
    checks.append({"check": "energy identity: volume integral = boundary integral", "value": deck2["energy_identity_rel"],
                   "limit": 1e-8, "passed": deck2["energy_identity_rel"] < 1e-8})
    sq = solve_section("rect", a, a)
    e = abs(sq["C_A"] / 1.51 - 1)
    checks.append({"check": "square section vs literature C_A = 1.51 (Wendel 1956 / DNV-RP-C205)", "value": e,
                   "limit": 0.02, "passed": e < 0.02, "soft": True, "detail": f"C_A = {sq['C_A']:.4f}"})
    table = []
    for i, beta in enumerate(BETAS):
        s = solve_section("rect", 0.01, 0.01 * beta)
        table.append({"beta": beta, "C_A": s["C_A"], "n_dofs": s["n_dofs"]})
        if progress:
            progress((i + 1) / len(BETAS))
    cs = [r["C_A"] for r in table]
    mono = all(cs[i] < cs[i + 1] for i in range(len(cs) - 1))
    checks.append({"check": "C_A increases monotonically with section depth along motion", "value": float(mono),
                   "limit": 1, "passed": mono})
    valid = all(c["passed"] for c in checks if not c.get("soft"))
    field = field_grid(deck2, u_half=0.04, v_half=0.025)
    meta = {"solver": "gmsh + scikit-fem (P2 Lagrange, potential flow)", "gmsh_version": gmsh.__version__,
            "skfem_version": skfem.__version__, "created": time.time(), "valid": valid, "checks": checks,
            "wall_time_s": round(time.perf_counter() - t0, 2), "evidence": "simplified_numerical_simulation",
            "deck_section": {"W_m": W, "H_m": H, "C_A_heave": deck2["C_A"], "n_dofs": deck2["n_dofs"]},
            "limitations": "2-D strip theory x board length (upper bound, no 3-D end relief); inviscid; no ground "
                           "proximity; Munk moment neglected in the flight model"}
    doc = {"meta": meta, "table": table}
    ROM_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROM_PATH.write_text(json.dumps(sanitize(doc)))
    fdoc = {"title": "deck cross-section potential flow (heave, U = 1 m/s)", "plane": "yz", "u_axis": "y_body",
            "v_axis": "z_body", "grid": {"y": field["u"], "z": field["v"]},
            "quantities": {"phi": {"unit": "m^2/s", "values": field["phi"]},
                           "speed": {"unit": "m/s", "values": field["speed"]}},
            "source": meta["solver"], "valid": valid}
    FIELD_PATH.write_text(json.dumps(sanitize(fdoc)))
    return doc


class AddedMassROM:
    def __init__(self, doc: dict):
        self.meta = doc["meta"]
        t = doc["table"]
        self.lb = np.log([r["beta"] for r in t])
        self.c = np.array([r["C_A"] for r in t])

    @classmethod
    def load(cls) -> "AddedMassROM | None":
        if not ROM_PATH.exists():
            return None
        d = json.loads(ROM_PATH.read_text())
        return cls(d) if d["meta"].get("valid") else None

    def C(self, beta: float) -> float:
        return float(np.interp(math.log(beta), self.lb, self.c))

    def added_mass_kg(self, L: float, W: float, H: float, rho: float) -> tuple[float, float, float]:
        """Body-axis added masses (x, y, z). x (along the length) is not modelled (set 0, small: thin end)."""
        heave = self.C(H / W) * rho * math.pi * (W / 2) ** 2 * L
        sway = self.C(W / H) * rho * math.pi * (H / 2) ** 2 * L
        return (0.0, sway, heave)
