"""Record a thrust-stand run to CSV and (optionally) analyse it into the harness.

    pip install pyserial            (bench PC only)
    python bench/logger.py COM5 sweep  open_22mm.csv
    python bench/logger.py COM5 sweep  ducted_22mm.csv
    python bench/logger.py COM5 step   step_22mm.csv
    python bench/logger.py COM5 discharge discharge_300.csv   (runs until the stand's 3.0 V cutoff)
    python bench/logger.py --analyse --open open_22mm.csv --ducted ducted_22mm.csv --step step_22mm.csv \
        --diameter-mm 22 [--discharge discharge_300.csv --capacity-mah 300]

Modes: sweep (s), step (r). The stand firmware enforces current/voltage limits; Ctrl-C sends STOP.
Columns that the stand cannot measure (no tach, no torque cell) are left empty and the analysis adapts.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def record(port: str, mode: str, out: str) -> None:
    import serial  # pyserial

    cmd = {"sweep": "s", "step": "r", "discharge": "p1400"}[mode]
    alt, last_switch = ["p1400", "p1550"], time.time()
    with serial.Serial(port, 115200, timeout=1) as ser, open(out, "w", newline="") as fh:
        time.sleep(2.0)                       # board resets on connect
        ser.reset_input_buffer()
        for c in ("t", "a"):                  # tare with prop stopped, then arm
            ser.write((c + "\n").encode())
            time.sleep(3.5 if c == "a" else 1.5)
        fh.write("t_s,throttle_us,thrust_g,voltage_v,current_a,rpm,torque_nmm\n")
        ser.write((cmd + "\n").encode())
        print(f"recording {mode} -> {out}  (Ctrl-C = STOP)")
        try:
            while True:
                line = ser.readline().decode(errors="ignore").strip()
                if not line:
                    continue
                if line.startswith("#"):
                    print(line)
                    if "STOP" in line:
                        break
                    continue
                if line[0].isdigit():
                    fh.write(line + "\n")
                if mode == "discharge" and time.time() - last_switch > 20:
                    alt.reverse()                     # load steps every 20 s -> internal resistance
                    ser.write((alt[0] + "\n").encode())
                    last_switch = time.time()
        except KeyboardInterrupt:
            ser.write(b"x\n")
            print("STOP sent")


def analyse(a) -> None:
    import json

    from levitate.bench import analyse_session

    rep = analyse_session(a.open, a.diameter_mm / 1000, a.ducted, a.discharge, a.capacity_mah, a.step,
                          label=a.label or Path(a.open).stem)
    print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("port", nargs="?")
    p.add_argument("mode", nargs="?", choices=["sweep", "step", "discharge"])
    p.add_argument("out", nargs="?")
    p.add_argument("--analyse", action="store_true")
    p.add_argument("--open"), p.add_argument("--ducted"), p.add_argument("--discharge"), p.add_argument("--step")
    p.add_argument("--diameter-mm", type=float), p.add_argument("--capacity-mah", type=float)
    p.add_argument("--label")
    a = p.parse_args()
    if a.analyse:
        analyse(a)
    else:
        record(a.port, a.mode, a.out)
