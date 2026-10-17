# Bench test: motor, fan, duct and battery

Purpose: measure the four numbers that dominate the mini-board verdict, and feed them back into the harness as **measured** assumptions:
rotor figure of merit (FM), motor efficiency, duct effectiveness, and battery usable energy / peak power. Also motor response time and reaction torque if the optional sensors are fitted.

Budget: about $60–90 for the stand, plus the flight parts you would buy anyway. Prices are typical hobby-retail and should be checked.

## Parts
| Part | Notes | ~Cost |
|---|---|---|
| Arduino Nano or Uno | any 5 V AVR board | $8 |
| 500 g bar load cell + HX711 board | thrust cell (resolution ~0.05 g) | $8 |
| INA226 current/voltage module (R010 shunt) | measures battery-side power up to ~8 A | $5 |
| 1S brushless ESC (or the AIO board you will fly) | PWM input 1000–2000 µs | $10–40 |
| Brushless 0702 motor + 22 mm fan | the leading design's propulsion | $15 |
| 3D-printed duct coupon | short section of the deck around one fan, 0.4 mm tip gap (print a 0.3 and 0.6 mm version too) | — |
| 1S LiPo 300–660 mAh (as in the design) + XT30/BT2.0 pigtail | test cells are consumed by discharge tests | $6–10 |
| Optional: IR reflective sensor (TCRT5000) on D2 | rpm → separates FM from motor efficiency | $2 |
| Optional: second 100 g load cell + HX711 on a lever arm | reaction torque | $8 |
| 2 kg rigid base, M3 hardware, 50/100 g calibration mass | the stand must not flex | $10 |

## Build
* Mount the motor on top of the thrust cell with the fan **pushing air up**, so the cell is loaded in compression and the outflow is not blocked by the bench. Keep ≥ 10 fan diameters of free space above and below, because ground and ceiling effect contaminate the reading.
* Wiring: HX711 DT→D4, SCK→D5. Optional torque HX711 DT→D6, SCK→D7. INA226 SDA/SCL→A4/A5, with the shunt in series with the battery positive lead. ESC signal→D9, ESC ground→Arduino GND. Tach→D2.
* Flash `bench/firmware/thrust_stand/thrust_stand.ino` (libraries: HX711 by Bogdan Necula, INA226 by Rob Tillaart).
* Calibrate with the fan stopped. Send `t` (tare), place the 100 g mass and send `k100`. Repeat with 50 g and check it reads 50 ± 0.3 g.

## Procedure
On the bench PC: `pip install pyserial`, then from the repo root:

1. **Open fan sweep:** `python bench/logger.py COM5 sweep open_22mm.csv`
2. **Ducted sweep** (same motor and fan, now in the duct coupon): `python bench/logger.py COM5 sweep ducted_22mm.csv`
3. **Step response:** `python bench/logger.py COM5 step step_22mm.csv`
4. **Battery discharge** with a fresh, fully charged cell (alternates two throttle levels, stops at the 3.0 V firmware cutoff): `python bench/logger.py COM5 discharge discharge_300.csv`
5. **Weigh** every flight part (motor with leads, fan, AIO board, battery, printed coupons) three times and note the masses in `data/measurements/masses.md`.
6. **Analyse and update the harness:**
   ```
   python bench/logger.py --analyse --open open_22mm.csv --ducted ducted_22mm.csv --step step_22mm.csv \
       --discharge discharge_300.csv --capacity-mah 300 --diameter-mm 22 --label "2026-10-xx 0702+22mm"
   ```
   This writes `data/measurements/assumptions_measured.json`. From then on every evaluation uses the measured values, marked MEASURED. Re-run the studies from the AI Research Console and compare.

Repeat each sweep 3 times and on 2 batteries if possible. The analysis reports a ±2σ band including 2 % calibration uncertainty.

## Acceptance
* Duct coupon result decides open vs ducted.
* Model vs measurement on hover current within ±10 % after the overlay. Larger gaps get investigated before any coefficient is tuned.
* If measured FM × η puts the pessimistic T/W ≥ 1.5, the leading design moves from MARGINAL to FEASIBLE and goes to the gimbal stage (VALIDATION_PLAN.md).

## Safety
Eye protection and a clear zone in the fan plane. Prop stopped for tare/calibration. Charge and discharge LiPos in a fireproof bag, never below 3.0 V/cell. The firmware stops at 6 A or 3.0 V; Ctrl-C in the logger also sends STOP.
