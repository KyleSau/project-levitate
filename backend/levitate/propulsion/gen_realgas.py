"""Generate the real-gas property tables used by `levitate.propulsion.gas` (run once; output is committed).

Requires CoolProp (installed only in the worktree venv `.venv-prop`, not in the shared project venv):

    .venv-prop/Scripts/python.exe -m levitate.propulsion.gen_realgas      (cwd = backend/)

Equations of state (as implemented in CoolProp 8):
  * Air      : Lemmon, Jacobsen, Penoncello & Friend (2000), pseudo-pure fluid, J. Phys. Chem. Ref. Data 29, 331.
  * Nitrogen : Span, Lemmon, Jacobsen, Wagner & Yokozeki (2000), J. Phys. Chem. Ref. Data 29, 1361.
Grid: T = 135 ... 400 K (above the critical temperature of air, 132.5 K, so the table never enters the two-phase
dome), density on a log grid 0.02 ... 650 kg/m^3. Stored per point: p [Pa], u, h [J/kg], s [J/(kg K)], Z [-].
Energies use CoolProp's reference state; the model only ever uses differences.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent / "data"
T_GRID = np.arange(135.0, 400.0 + 1e-9, 5.0)
RHO_GRID = np.geomspace(0.02, 650.0, 110)
FLUIDS = {"air": "Air", "n2": "Nitrogen"}


def main() -> None:
    import CoolProp
    import CoolProp.CoolProp as CP

    OUT.mkdir(exist_ok=True)
    for key, name in FLUIDS.items():
        R = CP.PropsSI("GAS_CONSTANT", name) / CP.PropsSI("MOLAR_MASS", name)
        tab = {k: np.zeros((len(T_GRID), len(RHO_GRID))) for k in ("p", "u", "h", "s", "Z")}
        for i, T in enumerate(T_GRID):
            for j, d in enumerate(RHO_GRID):
                p, u, h, s = (CP.PropsSI(q, "T", float(T), "D", float(d), name) for q in ("P", "U", "H", "S"))
                tab["p"][i, j], tab["u"][i, j], tab["h"][i, j], tab["s"][i, j] = p, u, h, s
                tab["Z"][i, j] = p / (d * R * T)
        doc = {"fluid": name, "eos": "CoolProp " + CoolProp.__version__ + " (Helmholtz EOS, see module docstring)",
               "R": R, "T": T_GRID.tolist(), "rho": RHO_GRID.tolist(),
               **{k: np.round(v, 6).tolist() for k, v in tab.items()}}
        (OUT / f"realgas_{key}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        print(key, "written", (OUT / f"realgas_{key}.json").stat().st_size, "bytes")


if __name__ == "__main__":
    main()
