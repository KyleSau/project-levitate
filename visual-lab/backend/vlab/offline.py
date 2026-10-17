"""High-accuracy offline integration with SciPy solve_ivp (DOP853, 8th-order Dormand-Prince).

Used (a) as an independent reference for the fixed-step RK4 integrator in the validation tests and
(b) as the `integrator="dop853"` option of the closed-loop runner (the controller output is held
constant over each control interval, exactly as in the RK4 runner, so both solve the same ODE).
"""
from __future__ import annotations

import numpy as np
from scipy.integrate import solve_ivp

RTOL = 1e-9
ATOL = 1e-12


def dop853_interval(plant, x, u, f_ext, dt, rtol=RTOL, atol=ATOL):
    sol = solve_ivp(lambda t, y: plant.deriv(y, u, f_ext), (0.0, dt), x, method="DOP853", rtol=rtol, atol=atol)
    y = sol.y[:, -1].copy()
    y[6:10] /= np.linalg.norm(y[6:10])
    return y


def integrate_open_loop(plant, x0, u, t_end, f_ext=None, rtol=RTOL, atol=ATOL, t_eval=None):
    """Open-loop trajectory (constant actuator command) for validation."""
    f_ext = np.zeros(3) if f_ext is None else np.asarray(f_ext, float)
    sol = solve_ivp(lambda t, y: plant.deriv(y, u, f_ext), (0.0, t_end), x0, method="DOP853", rtol=rtol, atol=atol,
                    t_eval=t_eval, dense_output=False)
    return sol


def rk4_open_loop(plant, x0, u, t_end, dt, f_ext=None):
    f_ext = np.zeros(3) if f_ext is None else np.asarray(f_ext, float)
    x = np.array(x0, float)
    n = int(round(t_end / dt))
    for _ in range(n):
        x = plant.rk4_step(x, u, f_ext, dt)
    return x
