"""Coupled electrostatics + unipolar ion transport for positive DC corona (ionic wind).

Geometry: an emitter wire of radius r_w parallel to either
  * a grounded collector plane at gap D (wire-to-plane thruster cell), or
  * a grounded outer cylinder of radius R with centre offset e (near-coaxial verification case).
Both are exactly coordinate-aligned in bipolar coordinates  z = x+iy = a*coth(w/2),  w = eta + i*xi:
circles are eta = const, the plane x = 0 is eta = 0, xi is periodic on (-pi, pi]. The map is conformal,
so the governing equations transform with the scale factor h = |dz/dw| = a / (cosh eta - cos xi):

    Poisson:            phi_ee + phi_xx = -h^2 rho / eps0
    Ion conservation:   d/de (rho phi_e) + d/dx (rho phi_x) = 0         (drift only, steady)

Model (standard Kaptzov / Peek corona model, e.g. Adamiak & Atten 2004; Masuyama & Barrett 2013):
  * the ionisation layer is infinitesimally thin; ions are injected at the wire with uniform
    density rho_w chosen so that the mean surface field equals Peek's onset field (Kaptzov condition)
  * ion diffusion and neutral-gas convection of ions are neglected (drift velocity >> flow velocity)
  * the Coulomb body force on the air  f = rho E  is computed and integrated; the reaction on the
    electrodes is the electrostatic thrust *before* aerodynamic drag of the electrodes is subtracted.

Discretisation: node-centred finite differences for Poisson (constant matrix, LU-factorised once),
first-order upwind finite volume for ion transport (sparse direct solve), Picard iteration with
under-relaxation, Brent root-finding for rho_w. Evidence category: SIMPLIFIED_NUMERICAL.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.optimize import brentq

from ..constants import EPS0


def peek_onset_field(r_wire_m: float, rel_air_density: float = 1.0, roughness: float = 1.0) -> float:
    """Peek's law for a wire (positive or negative corona), SI: E0 = 3.1e6 d m (1 + 0.0308/sqrt(d r)) V/m."""
    d = rel_air_density
    return 3.1e6 * d * roughness * (1.0 + 0.0308 / math.sqrt(d * r_wire_m))


@dataclass
class CoronaGeometry:
    r_wire: float
    gap: float | None = None            # wire centre to plane distance (wire-to-plane)
    r_outer: float | None = None        # outer cylinder radius (wire-in-cylinder)
    eccentricity: float = 0.0           # outer centre offset for wire-in-cylinder

    def bipolar(self) -> tuple[float, float, float]:
        """Return (a, eta_outer, eta_wire)."""
        if self.gap is not None:
            if self.gap <= self.r_wire:
                raise ValueError("gap must exceed wire radius")
            a = math.sqrt(self.gap ** 2 - self.r_wire ** 2)
            return a, 0.0, math.acosh(self.gap / self.r_wire)
        assert self.r_outer is not None
        e = max(self.eccentricity, 1e-6 * self.r_outer)
        x0 = ((self.r_outer ** 2 - self.r_wire ** 2) / e - e) / 2.0      # wire centre
        a = math.sqrt(x0 ** 2 - self.r_wire ** 2)
        eta_w = math.asinh(a / self.r_wire)
        eta_o = math.asinh(a / self.r_outer)
        return a, eta_o, eta_w


@dataclass
class CoronaResult:
    voltage: float
    corona_active: bool
    rho_wire: float                       # injected ion density [C/m^3]
    onset_field: float                    # Peek field [V/m]
    wire_field_mean: float                # achieved mean surface field [V/m]
    current_per_length: float             # [A/m] from the wire
    current_per_length_collector: float   # [A/m] arriving at the outer electrode
    force_per_length: tuple[float, float] # Coulomb force on the air (x toward wire, y lateral) [N/m]
    thrust_per_length: float              # reaction on the electrodes along +x (away from collector) [N/m]
    power_per_length: float               # V * I' [W/m]
    picard_iterations: int
    picard_residual: float
    current_conservation_error: float
    grid: tuple[int, int]
    strip_force_fraction: dict[str, float] = field(default_factory=dict)
    fields: dict | None = None            # sampled phi/rho/E on a physical grid for visualisation

    @property
    def thrust_to_power(self) -> float:
        return self.thrust_per_length / self.power_per_length if self.power_per_length > 0 else 0.0


class BipolarCoronaSolver:
    def __init__(self, geom: CoronaGeometry, n_eta: int = 64, n_xi: int = 128, mobility: float = 2.0e-4,
                 rel_air_density: float = 1.0, roughness: float = 1.0):
        self.g = geom
        self.mu = mobility
        self.E0 = peek_onset_field(geom.r_wire, rel_air_density, roughness)
        self.a, self.eta_o, self.eta_w = geom.bipolar()
        self.N, self.M = n_eta, n_xi
        self.eta = np.linspace(self.eta_o, self.eta_w, n_eta + 1)          # i = 0 outer ... N wire
        self.de = self.eta[1] - self.eta[0]
        self.dx = 2 * math.pi / n_xi
        self.xi = -math.pi + (np.arange(n_xi) + 0.5) * self.dx              # offset avoids xi = 0 at plane
        E, X = np.meshgrid(self.eta, self.xi, indexing="ij")
        self.h = self.a / (np.cosh(E) - np.cos(X))                           # (N+1, M)
        self.w = E + 1j * X
        self._build_poisson()

    # --------------------------------------------------------------- Poisson
    def _idx(self, i, j):
        return (i - 1) * self.M + (j % self.M)

    def _build_poisson(self):
        N, M = self.N, self.M
        n = (N - 1) * M
        ce, cx = 1.0 / self.de ** 2, 1.0 / self.dx ** 2
        rows, cols, vals = [], [], []
        for i in range(1, N):
            for j in range(M):
                k = self._idx(i, j)
                rows.append(k); cols.append(k); vals.append(-2 * ce - 2 * cx)
                for jj in (j - 1, j + 1):
                    rows.append(k); cols.append(self._idx(i, jj)); vals.append(cx)
                for ii in (i - 1, i + 1):
                    if 1 <= ii <= N - 1:
                        rows.append(k); cols.append(self._idx(ii, j)); vals.append(ce)
        A = sp.csc_matrix((vals, (rows, cols)), shape=(n, n))
        self._poisson_lu = spla.splu(A)

    def solve_poisson(self, rho: np.ndarray, V: float) -> np.ndarray:
        """rho on the full (N+1, M) node grid; returns phi on the full grid."""
        N, M = self.N, self.M
        rhs = (-(self.h[1:N] ** 2) * rho[1:N] / EPS0).ravel()
        # Dirichlet: phi(eta_o) = 0, phi(eta_w) = V
        rhs[(N - 2) * M:] -= V / self.de ** 2
        phi_int = self._poisson_lu.solve(rhs)
        phi = np.zeros((N + 1, M))
        phi[N] = V
        phi[1:N] = phi_int.reshape(N - 1, M)
        return phi

    # --------------------------------------------------------------- ion transport
    def solve_charge(self, phi: np.ndarray, rho_w: float) -> np.ndarray:
        N, M = self.N, self.M
        n = (N - 1) * M
        # face fluxes (mu omitted): +eta faces between i and i+1, +xi faces between j and j+1
        qe = -(phi[1:] - phi[:-1]) / self.de * self.dx                    # (N, M) face i+1/2
        qx = -(np.roll(phi, -1, axis=1) - phi) / self.dx * self.de        # (N+1, M) face j+1/2
        diag = np.full(n, 1e-30)
        rows, cols, vals = [], [], []
        rhs = np.zeros(n)
        I, J = np.meshgrid(np.arange(1, N), np.arange(M), indexing="ij")
        I, J = I.ravel(), J.ravel()
        K = self._idx(I, J)
        # four faces: (outflow flux from P, neighbour index or boundary)
        faces = [
            (qe[I, J], I + 1, J),            # +eta face (toward wire)
            (-qe[I - 1, J], I - 1, J),       # -eta face (toward collector)
            (qx[I, J], I, (J + 1) % M),      # +xi face
            (-qx[I, (J - 1) % M], I, (J - 1) % M),
        ]
        for q, ni, nj in faces:
            out = np.maximum(q, 0.0)
            inn = np.minimum(q, 0.0)                                      # negative = inflow
            diag += out
            interior = (ni >= 1) & (ni <= N - 1)
            rows.append(K[interior]); cols.append(self._idx(ni[interior], nj[interior])); vals.append(inn[interior])
            wire = ni == N
            rhs[K[wire]] -= inn[wire] * rho_w                             # inflow from the wire
            # inflow from the collector is zero (no ions emitted there)
        rows.append(K); cols.append(K); vals.append(diag)
        A = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
        rho_int = spla.spsolve(A.tocsc(), rhs)
        rho = np.zeros((N + 1, M))
        rho[N] = rho_w
        rho[1:N] = np.maximum(rho_int.reshape(N - 1, M), 0.0)
        return rho

    # --------------------------------------------------------------- diagnostics
    def wire_field_mean(self, phi: np.ndarray) -> float:
        N = self.N
        dphi = (3 * phi[N] - 4 * phi[N - 1] + phi[N - 2]) / (2 * self.de)
        return float(np.sum(dphi) * self.dx / (2 * math.pi * self.g.r_wire))

    def _currents(self, phi: np.ndarray, rho: np.ndarray, rho_w: float) -> tuple[float, float]:
        N = self.N
        i_wire = self.mu * rho_w * float(np.sum((phi[N] - phi[N - 1]) / self.de) * self.dx)
        i_coll = self.mu * float(np.sum(rho[1] * (phi[1] - phi[0]) / self.de) * self.dx)
        return i_wire, i_coll

    def physical_field(self, phi: np.ndarray):
        pe = np.gradient(phi, self.de, axis=0)
        px = (np.roll(phi, -1, axis=1) - np.roll(phi, 1, axis=1)) / (2 * self.dx)
        fprime = -self.a / (2 * np.sinh(self.w / 2) ** 2)
        G = (pe - 1j * px) / fprime
        return -G.real, G.imag            # Ex, Ey

    def coulomb_force(self, phi: np.ndarray, rho: np.ndarray, strips: tuple[float, ...] = ()):
        Ex, Ey = self.physical_field(phi)
        wgt = self.h ** 2 * self.de * self.dx
        wgt[0] *= 0.5
        wgt[-1] *= 0.5
        fx = rho * Ex * wgt
        fy = rho * Ey * wgt
        Fx, Fy = float(fx.sum()), float(fy.sum())
        z = self.a / np.tanh(self.w / 2)
        frac = {}
        for s in strips:
            mask = np.abs(z.imag) <= s / 2
            frac[f"{s * 1000:.1f}mm"] = float(fx[mask].sum() / Fx) if Fx else 0.0
        return Fx, Fy, frac

    # --------------------------------------------------------------- coupled solve
    def solve(self, V: float, strips: tuple[float, ...] = (), sample_fields: bool = False) -> CoronaResult:
        rho0 = np.zeros((self.N + 1, self.M))
        phi_lap = self.solve_poisson(rho0, V)
        e_lap = self.wire_field_mean(phi_lap)
        if e_lap <= self.E0:
            return CoronaResult(voltage=V, corona_active=False, rho_wire=0, onset_field=self.E0,
                                wire_field_mean=e_lap, current_per_length=0, current_per_length_collector=0,
                                force_per_length=(0, 0), thrust_per_length=0, power_per_length=0,
                                picard_iterations=0, picard_residual=0, current_conservation_error=0,
                                grid=(self.N, self.M),
                                fields=self.sample(phi_lap, rho0) if sample_fields else None)
        # Combined fixed-point iteration: Picard on (rho, phi) with the Kaptzov injection density
        # updated every sweep in log space; step size halves whenever the wire-field error changes sign.
        phi = phi_lap
        rho_w = 1e-6
        step = 1.0
        last_sign = 0
        relax = 0.6
        prev_res = math.inf
        its, res, kap = 0, math.inf, math.inf
        for its in range(1, 3001):
            rho = self.solve_charge(phi, rho_w)
            phi_new = self.solve_poisson(rho, V)
            res = float(np.max(np.abs(phi_new - phi))) / V
            if res > prev_res:
                relax = max(relax * 0.7, 0.05)
            prev_res = res
            phi = phi + relax * (phi_new - phi)
            kap = self.wire_field_mean(phi) / self.E0 - 1.0
            if res < 1e-7 and abs(kap) < 1e-4:
                break
            sign = 1 if kap > 0 else -1
            if last_sign and sign != last_sign:
                step *= 0.5
            last_sign = sign
            # log-space update bounded to a factor of 2 per sweep
            rho_w *= math.exp(max(-math.log(2), min(math.log(2), step * 3.0 * math.log1p(kap))))
        else:
            raise RuntimeError(f"corona iteration did not converge (res={res:.1e}, kaptzov={kap:.1e})")
        i_w, i_c = self._currents(phi, rho, rho_w)
        Fx, Fy, frac = self.coulomb_force(phi, rho, strips)
        return CoronaResult(
            voltage=V, corona_active=True, rho_wire=rho_w, onset_field=self.E0,
            wire_field_mean=self.wire_field_mean(phi), current_per_length=i_w,
            current_per_length_collector=i_c, force_per_length=(Fx, Fy), thrust_per_length=-Fx,
            power_per_length=V * i_w, picard_iterations=its, picard_residual=res,
            current_conservation_error=abs(i_w - i_c) / i_w if i_w else 0.0, grid=(self.N, self.M),
            strip_force_fraction=frac, fields=self.sample(phi, rho) if sample_fields else None)

    # --------------------------------------------------------------- visualisation sampling
    def sample(self, phi: np.ndarray, rho: np.ndarray, nx: int = 90, ny: int = 120) -> dict:
        """Bilinear resample onto a physical (x, y) grid via the inverse map w = log((z+a)/(z-a))."""
        D = self.g.gap if self.g.gap is not None else self.g.r_outer
        xs = np.linspace(0.0 if self.g.gap is not None else -D, 1.4 * D, nx)
        ys = np.linspace(-1.5 * D, 1.5 * D, ny)
        Xg, Yg = np.meshgrid(xs, ys, indexing="ij")
        z = Xg + 1j * Yg
        with np.errstate(divide="ignore", invalid="ignore"):
            w = np.log((z + self.a) / (z - self.a))
        eta, xi = w.real, w.imag
        inside = (eta >= self.eta_o) & (eta <= self.eta_w) & np.isfinite(eta)
        fi = np.clip((eta - self.eta_o) / self.de, 0, self.N - 1e-9)
        fj = (xi + math.pi) / self.dx - 0.5
        i0 = np.floor(fi).astype(int)
        j0 = np.floor(fj).astype(int)
        ti, tj = fi - i0, fj - j0
        j0m, j1m = j0 % self.M, (j0 + 1) % self.M
        i1 = np.minimum(i0 + 1, self.N)

        def interp(F):
            return ((1 - ti) * (1 - tj) * F[i0, j0m] + ti * (1 - tj) * F[i1, j0m]
                    + (1 - ti) * tj * F[i0, j1m] + ti * tj * F[i1, j1m])

        P = np.where(inside, interp(phi), np.nan)
        Rr = np.where(inside, interp(rho), np.nan)
        clean = lambda A: [[None if not np.isfinite(v) else float(v) for v in row] for row in A]
        return {"x": xs.tolist(), "y": ys.tolist(), "phi": clean(P), "rho": clean(Rr)}


# ------------------------------------------------------------------- exact coaxial reference
def coaxial_exact(V: float, r_wire: float, r_outer: float, mobility: float = 2.0e-4,
                  rel_air_density: float = 1.0) -> tuple[float, float]:
    """Exact Kaptzov solution for a coaxial wire-cylinder (drift-only, unipolar):
    E(r)^2 = (E0 r0 / r)^2 + (I'/(2 pi eps0 mu)) (1 - r0^2/r^2),  V = int E dr.
    Returns (current per length [A/m], onset voltage [V])."""
    from scipy.integrate import quad

    E0 = peek_onset_field(r_wire, rel_air_density)
    V0 = E0 * r_wire * math.log(r_outer / r_wire)
    if V <= V0:
        return 0.0, V0
    k = 1.0 / (2 * math.pi * EPS0 * mobility)

    def volt(I):
        return quad(lambda r: math.sqrt((E0 * r_wire / r) ** 2 + k * I * (1 - (r_wire / r) ** 2)),
                    r_wire, r_outer, limit=200)[0]

    hi = 1e-9
    while volt(hi) < V:
        hi *= 4
    return brentq(lambda I: volt(I) - V, 0.0, hi, xtol=1e-14, rtol=1e-10), V0
