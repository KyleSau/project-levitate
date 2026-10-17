"""Build the README figures from the experiment database, solver outputs and sim runs.

    node docs/figures/sim_data.js > docs/figures/sim_data.json
    .venv/Scripts/python docs/figures/make_figures.py

Palette: validated categorical order (blue, orange, aqua, yellow, magenta, ...) on a light surface;
status colors only for verdicts. One y-axis per chart; small multiples instead of dual axes.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "backend"))

SURF, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
S = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 10.5, "text.color": INK,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.titlesize": 12.5, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.titlepad": 12, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.7, "axes.spines.top": False,
    "axes.spines.right": False, "lines.linewidth": 2.0, "legend.frameon": False, "legend.fontsize": 9.5,
})


def save(fig, name, note=None):
    if note:
        fig.text(0.01, 0.01, note, fontsize=8.5, color=MUTED, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04 if note else 0, 1, 1))
    fig.savefig(OUT / name, dpi=160)
    plt.close(fig)
    print("wrote", name)


db = sqlite3.connect(ROOT / "data" / "experiments.sqlite")
db.row_factory = sqlite3.Row
rows = lambda q, *a: [dict(r) for r in db.execute(q, a)]  # noqa: E731
sim = json.loads((ROOT / "docs" / "figures" / "sim_data.json").read_text())

# ------------------------------------------------------------------ 1. mini-board design space
ds = rows("SELECT summary_json, verdict FROM experiments WHERE kind='rotor_design' AND study_id=1")
pts = [(json.loads(r["summary_json"]), r["verdict"]) for r in ds]
fig, ax = plt.subplots(figsize=(8, 4.6))
bad = [(s["mass_g"], s["endurance_s_nom"] / 60) for s, v in pts if v == "INFEASIBLE" and s["endurance_s_nom"] > 1]
ok = [(s["mass_g"], s["endurance_s_nom"] / 60) for s, v in pts if v != "INFEASIBLE"]
ax.scatter(*zip(*bad), s=9, color=AXIS, label=f"fails a hard check ({len(bad)})", linewidths=0)
ax.scatter(*zip(*ok), s=12, color=S[0], label=f"passes at nominal assumptions ({len(ok)})", linewidths=0)
best = max(ok, key=lambda p: p[1])
ax.scatter([best[0]], [best[1]], s=70, color=S[1], edgecolor=SURF, linewidth=2, zorder=5)
ax.annotate("best feasible: 30.3 g, 12.5 min\n4 x 22 mm ducted fans", best, xytext=(-150, 22), textcoords="offset points", color=INK2, fontsize=9.5,
            arrowprops=dict(arrowstyle="-", color=MUTED, linewidth=1))
ax.set_xlim(15, 60); ax.set_ylim(0, 16)
ax.set_xlabel("All-up mass (g)"); ax.set_ylabel("Hover endurance, nominal (min)")
ax.set_title("2,000 candidate 100 mm hoverboards (NSGA-II search)")
ax.text(59.5, 0.4, "designs with no usable endurance not shown", ha="right", color=MUTED, fontsize=8.5)
ax.legend(loc="upper right")
save(fig, "mini_design_space.png", "Analytical model: momentum theory + mass budget + battery + control-authority LP. Source: experiment DB, study 1.")

# ------------------------------------------------------------------ 2. endurance uncertainty + calibration
fig, ax = plt.subplots(figsize=(8, 2.9))
rows_ = [("Best mini board (model)", 5.5, 12.5, 20.9, None), ("Crazyflie-class check (model)", 5.0, 7.2, 11.6, 7.0)]
for i, (lab, lo, nom, hi, ref) in enumerate(rows_):
    y = len(rows_) - 1 - i
    ax.plot([lo, hi], [y, y], color=S[0], linewidth=6, solid_capstyle="round", alpha=0.35)
    ax.scatter([nom], [y], s=60, color=S[0], zorder=5)
    ax.text(hi + 0.4, y, f"{lo}–{hi} min (nominal {nom})", va="center", color=INK2, fontsize=9.5)
    if ref:
        ax.scatter([ref], [y], marker="D", s=46, color=S[1], zorder=6)
        ax.text(ref, y + 0.32, "published ~7 min", ha="center", color=INK2, fontsize=9)
ax.set_yticks(range(len(rows_))); ax.set_yticklabels([r[0] for r in reversed(rows_)], color=INK2)
ax.set_xlim(0, 28); ax.set_ylim(-0.6, 1.8); ax.set_xlabel("Hover endurance (min): pessimistic – optimistic assumptions")
ax.grid(axis="y", visible=False)
ax.set_title("Endurance uncertainty and a real-vehicle calibration point")
save(fig, "mini_endurance.png", "Spread comes from rotor efficiency, duct benefit, motor efficiency and battery assumptions. Bench test (docs/BENCH_TEST.md) will narrow it.")

# ------------------------------------------------------------------ 3. 6-DOF mission trajectory
r = db.execute("SELECT results_json FROM experiments WHERE id=5101").fetchone()
sm = json.loads(r["results_json"])["sim"]
t = np.array(sm["t"]); P = np.array(sm["pos"])
fig, ax = plt.subplots(figsize=(8, 3.8))
for k, lab in enumerate(["x (forward)", "y (left)", "z (altitude)"]):
    ax.plot(t, P[:, k], color=S[k], label=lab)
ax.set_xlabel("Time (s)"); ax.set_ylabel("Position (m)")
ax.set_title("Closed-loop 6-DOF mission of the best mini board")
ax.legend(loc="upper left", bbox_to_anchor=(0.005, 0.86))
for tt, lab in [(0.5, "take-off"), (4, "forward"), (6.5, "sideways"), (9, "yaw 90°"), (11, "return"), (13, "land")]:
    ax.axvline(tt, color=GRID, linewidth=1, zorder=0); ax.text(tt + 0.1, 0.56, lab, fontsize=8.5, color=MUTED)
ax.set_ylim(-0.05, 0.62)
save(fig, "mini_mission.png", "RK4 rigid-body integration at 500 Hz with geometric attitude control; RMS tracking error 6.5 mm. Experiment 5101.")

# ------------------------------------------------------------------ 4. corona solver: thrust vs voltage
sur = json.loads((ROOT / "data" / "ehd_surrogate.json").read_text())
fig, ax = plt.subplots(figsize=(8, 4.2))
for i, gap in enumerate([5, 8, 12, 20]):
    e = next(x for x in sur["entries"] if x["gap_mm"] == gap and x["r_um"] == 25)
    V = [p["V"] / 1000 for p in e["points"]]; T = [p["T"] * 1000 for p in e["points"]]
    ax.plot(V, T, color=S[i], marker="o", markersize=5, label=f"{gap} mm gap")
    ax.text(V[-1] + 0.3, T[-1], f"{gap} mm", va="center", color=INK2, fontsize=9)
ax.set_xlabel("Emitter voltage (kV)"); ax.set_ylabel("Thrust per metre of wire (mN/m)")
ax.set_title("Ionic wind: coupled corona solver output (25 µm wire over a plane)")
ax.legend(loc="upper left")
save(fig, "ionic_thrust.png", "Poisson + ion-drift transport with Kaptzov/Peek injection, bipolar coordinates. Thrust/power 2–8 N/kW, in line with published wire-electrode data.")

# ------------------------------------------------------------------ 5. corona solver verification
from levitate.solvers.ehd_bipolar import BipolarCoronaSolver, CoronaGeometry, coaxial_exact  # noqa: E402

exact, _ = coaxial_exact(12e3, 50e-6, 10e-3)
ns, errs = [16, 24, 32, 48, 64], []
for n in ns:
    s = BipolarCoronaSolver(CoronaGeometry(r_wire=50e-6, r_outer=10e-3, eccentricity=1e-5), n, 2 * n).solve(12e3)
    errs.append(abs(s.current_per_length / exact - 1) * 100)
fig, ax = plt.subplots(figsize=(8, 3.8))
ax.loglog(ns, errs, color=S[0], marker="o", markersize=6, label="solver vs exact coaxial solution")
ref = [errs[0] * ns[0] / n for n in ns]
ax.loglog(ns, ref, color=MUTED, linestyle="--", linewidth=1.2, label="first-order slope")
ax.set_xlabel("Radial grid cells"); ax.set_ylabel("Corona current error (%)")
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402
ax.xaxis.set_major_locator(FixedLocator(ns)); ax.xaxis.set_minor_locator(NullLocator()); ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
ax.yaxis.set_major_locator(FixedLocator([3, 5, 10, 15])); ax.yaxis.set_minor_locator(NullLocator()); ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
ax.set_title("Verification: the solver converges to the exact answer")
ax.legend(loc="upper right")
save(fig, "ionic_verification.png", "Near-coaxial wire-in-cylinder, 12 kV. Richardson extrapolation of the two finest grids lands within 0.3 % of exact.")

# ------------------------------------------------------------------ 6. ionic wind board feasibility
fig, ax = plt.subplots(figsize=(8, 3.2))
cases = [("Nominal assumptions, 40 mm thick", 0.066), ("Optimistic assumptions, 40 mm thick", 0.157), ("Optimistic, 300 mm tall stack", 0.275)]
for i, (lab, v) in enumerate(cases):
    y = len(cases) - 1 - i
    ax.barh(y, v, height=0.5, color=S[0])
    ax.text(v + 0.02, y, f"{v:.3f}", va="center", color=INK2)
ax.axvline(1.0, color=CRIT, linewidth=1.6); ax.text(1.0, 2.55, "needed to hover (1.0)", ha="right", color=INK2, fontsize=9)
ax.set_yticks(range(len(cases))); ax.set_yticklabels([c[0] for c in reversed(cases)], color=INK2)
ax.set_xlim(0, 1.1); ax.set_xlabel("Best thrust-to-weight found (800-design searches)")
ax.grid(axis="y", visible=False); ax.set_ylim(-0.5, 2.8)
ax.set_title("Ionic wind cannot lift a 100 mm board")
save(fig, "ionic_feasibility.png", "Space-charge-limited thrust density and the mass of high-voltage converters are the binding limits.")

# ------------------------------------------------------------------ 7. human scale: downwash vs footprint frontier
hs = rows("SELECT summary_json, verdict FROM experiments WHERE kind='human_design' AND study_id=5")
names = {"air_cushion": "Air cushion", "ducted_electric": "Electric ducted fans", "open_rotor_electric": "Electric open rotors",
         "ducted_hybrid": "Ducted + generator", "turbojet": "Micro turbojets"}
fig, ax = plt.subplots(figsize=(8, 4.8))
bins = np.geomspace(0.3, 50, 18)
for i, c in enumerate(names):
    pts_ = [json.loads(r["summary_json"]) for r in hs if r["verdict"] != "DOES_NOT_CLOSE"]
    pts_ = [p for p in pts_ if p["concept"] == c]
    if c == "turbojet":
        ax.scatter([0.6], [500], s=60, color=S[i], zorder=5); ax.text(0.68, 500, "Micro turbojets (650 °C exhaust)", va="center", color=INK2, fontsize=9)
        continue
    xs, ys = [], []
    for b in bins:
        inb = [p["jet_m_s"] for p in pts_ if p["footprint_m2"] <= b]
        if inb:
            xs.append(b); ys.append(min(inb))
    ax.plot(xs, ys, color=S[i], label=names[c], drawstyle="steps-post")
for v, lab in [(12, "strong breeze"), (25, "throws sand and litter"), (50, "throws gravel")]:
    ax.axhline(v, color=GRID, linewidth=1.2, zorder=0); ax.text(0.31, v * 1.06, lab, color=MUTED, fontsize=8.5)
ax.scatter([], [], s=60, color=S[4], label=names["turbojet"])
ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(0.3, 80); ax.set_ylim(6, 800)
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402
ax.xaxis.set_major_locator(FixedLocator([0.3, 1, 3, 10, 30])); ax.xaxis.set_minor_locator(NullLocator())
ax.yaxis.set_major_locator(FixedLocator([10, 25, 50, 100, 250, 500])); ax.yaxis.set_minor_locator(NullLocator())
ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}")); ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
ax.legend(loc="upper right")
ax.set_xlabel("Footprint (m²)"); ax.set_ylabel("Lowest jet / edge-jet speed achievable (m/s)")
ax.set_title("Carrying a 200 lb rider: debris vs size (designs whose mass budget closes)")
save(fig, "human_frontier.png", "1,606 of 2,000 designs close at nominal assumptions (study 5). Momentum flux = weight, so jet speed falls only as the jet area grows.")

# ------------------------------------------------------------------ 8. hover endurance comparison
fig, ax = plt.subplots(figsize=(8, 3.6))
items = [("Cold-gas hoverboard (≤200 kg)", 13.1), ("Rocket hoverboard, theoretical (≤200 kg)", 95.8), ("Micro-turbojet board", 180),
         ("Electric ducted-fan platform", 450), ("Air-cushion board LV-H1", 2400)]
for i, (lab, s_) in enumerate(items):
    y = len(items) - 1 - i
    ax.barh(y, s_, height=0.55, color=S[0] if "cushion" in lab else AXIS if "Cold" in lab else "#86b6ef")
    ax.text(s_ * 1.12, y, f"{s_:.0f} s" if s_ < 120 else f"{s_ / 60:.1f} min" if s_ < 600 else f"{s_ / 60:.0f} min", va="center", color=INK2)
ax.set_xscale("log"); ax.set_xlim(5, 12000)
ax.xaxis.set_major_locator(FixedLocator([10, 60, 600, 3600])); ax.xaxis.set_minor_locator(NullLocator())
ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: {10: "10 s", 60: "1 min", 600: "10 min", 3600: "1 h"}[v]))
ax.set_yticks(range(len(items))); ax.set_yticklabels([i[0] for i in reversed(items)], color=INK2)
ax.grid(axis="y", visible=False); ax.set_xlabel("Time aloft per charge / tank, 200 lb rider (log scale)")
ax.set_title("How long each concept can keep a person up")
save(fig, "hover_endurance.png", "Modelled values. Air cushion rides cm above the surface; the others are free-flying. Sources: propulsion studies + human_scale + LV-H1 sim.")

# ------------------------------------------------------------------ 9. rider weight on the cushion board (small multiples)
hold = sim["cushion_hold"]; fx = sim["cushion_fixed085"]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.8))
a1.plot([h["rider_kg"] for h in hold], [h["power_kw"] for h in hold], color=S[0], marker="o", markersize=5)
a1.set_xlabel("Rider mass (kg)"); a1.set_ylabel("Electrical power (kW)"); a1.set_title("Hold air gap: weight costs power")
a2.plot([h["rider_kg"] for h in hold], [h["ride_cm"] for h in hold], color=S[0], marker="o", markersize=5, label="hold air gap")
a2.plot([h["rider_kg"] for h in fx], [h["ride_cm"] for h in fx], color=S[1], marker="o", markersize=5, label="fixed fan speed 85 %")
a2.set_xlabel("Rider mass (kg)"); a2.set_ylabel("Ride height, deck underside (cm)"); a2.set_title("Fixed fans: weight lowers the board")
a2.legend(loc="lower left"); a2.set_ylim(14, 17.6)
save(fig, "cushion_weight.png", "Steady states from the LV-H1 real-time physics (sim/hoverboard-h1). At 85 % fan speed the skirt touches down from ~90 kg.")

# ------------------------------------------------------------------ 10. boosted skateboard vs electric
sk = sim["skate"]
fig, ax = plt.subplots(figsize=(8, 3.8))
ax.axvspan(3, 13, color="#fef3d6", zorder=0); ax.text(3.2, 13.6, "boost valve open", color=MUTED, fontsize=8.5)
ax.plot(sk["electric"]["t"], sk["electric"]["v"], color=S[0], label="electric only")
ax.plot(sk["boosted"]["t"], sk["boosted"]["v"], color=S[1], label="electric + cold-gas boost")
ax.set_xlabel("Time (s)"); ax.set_ylabel("Speed (m/s)"); ax.set_ylim(0, 14.5)
ax.set_title("Cold-gas boost on a skateboard: +2.2 m/s for 8.6 kg of tank")
ax.legend(loc="upper right")
save(fig, "skateboard_boost.png", "Same scenario: 3 s wheels, 10 s boost (6.8 L, 300 bar), coast, brake. Only ~0.5 % of the compressor energy becomes thrust work.")
print("done")
