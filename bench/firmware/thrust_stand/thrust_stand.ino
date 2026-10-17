// Project Levitate thrust stand: Arduino Nano/Uno + HX711 load cell + INA226 power monitor + 1S ESC.
// Optional: IR/hall tach on D2 (one pulse per blade pass), second HX711 on D6/D7 for reaction torque.
// Libraries: "HX711" by Bogdan Necula, "INA226" by Rob Tillaart, Servo (built in).
// Serial 115200. Prints CSV at ~40 Hz: t_s,throttle_us,thrust_g,voltage_v,current_a,rpm,torque_nmm
// Commands (newline-terminated):
//   t            tare thrust (and torque) cells, propeller stopped
//   k<grams>     calibrate thrust cell with a known mass hanging/resting, e.g. k100
//   q<nmm_per_c> set torque cell scale (from your own lever-arm calibration)
//   b<blades>    blades per rev for the tach (default 3)
//   a            arm ESC (sends 1000 us for 3 s)
//   p<us>        hold a single throttle value, e.g. p1350
//   s            sweep 1100..2000 us in 100 us steps, 4 s each, then stop
//   r            step test: 1200 us for 3 s, then 1600 us for 3 s, then stop
//   x            STOP (1000 us) - also triggered by limits below
#include <HX711.h>
#include <INA226.h>
#include <Servo.h>
#include <Wire.h>

const int PIN_ESC = 9, PIN_LC_DT = 4, PIN_LC_SCK = 5, PIN_TQ_DT = 6, PIN_TQ_SCK = 7, PIN_TACH = 2;
const float MAX_CURRENT_A = 6.0;     // hard kill
const float MIN_VOLTAGE_V = 3.0;     // protects the 1S cell
const float SHUNT_OHM = 0.01;        // typical INA226 module "R010"; check yours

HX711 lc, tq;
INA226 ina(0x40);
Servo esc;
float lcScale = 400.0, tqScale = 1.0;   // counts per gram / counts per N*mm, set by calibration
volatile unsigned long tachPulses = 0;
int blades = 3, throttle = 1000;
bool haveTorque = false;
unsigned long t0, lastTach = 0, lastPulses = 0;
float rpm = 0;
// sequence player
const int SWEEP[] = {1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900, 2000};
int seqMode = 0, seqIdx = 0; unsigned long seqT = 0;

void tachISR() { tachPulses++; }

void setThrottle(int us) { throttle = constrain(us, 1000, 2000); esc.writeMicroseconds(throttle); }
void stopAll(const char* why) { seqMode = 0; setThrottle(1000); Serial.print("# STOP "); Serial.println(why); }

void setup() {
  Serial.begin(115200);
  esc.attach(PIN_ESC); setThrottle(1000);
  lc.begin(PIN_LC_DT, PIN_LC_SCK); lc.set_scale(lcScale);
  tq.begin(PIN_TQ_DT, PIN_TQ_SCK); haveTorque = tq.wait_ready_timeout(500);
  Wire.begin(); ina.begin(); ina.setMaxCurrentShunt(8.0, SHUNT_OHM);
  pinMode(PIN_TACH, INPUT_PULLUP); attachInterrupt(digitalPinToInterrupt(PIN_TACH), tachISR, FALLING);
  t0 = millis();
  Serial.println("# levitate thrust stand ready");
  Serial.println("t_s,throttle_us,thrust_g,voltage_v,current_a,rpm,torque_nmm");
}

void handle(String c) {
  if (c == "x") { stopAll("user"); return; }
  if (c == "t") { lc.tare(20); if (haveTorque) tq.tare(20); Serial.println("# tared"); return; }
  if (c.startsWith("k")) { float g = c.substring(1).toFloat(); long raw = lc.get_value(20); lcScale = raw / g; lc.set_scale(lcScale);
                           Serial.print("# thrust scale "); Serial.println(lcScale, 4); return; }
  if (c.startsWith("q")) { tqScale = c.substring(1).toFloat(); tq.set_scale(tqScale); return; }
  if (c.startsWith("b")) { blades = max(1, (int)c.substring(1).toInt()); return; }
  if (c == "a") { setThrottle(1000); delay(3000); Serial.println("# armed"); return; }
  if (c.startsWith("p")) { seqMode = 0; setThrottle(c.substring(1).toInt()); return; }
  if (c == "s") { seqMode = 1; seqIdx = 0; seqT = millis(); setThrottle(SWEEP[0]); return; }
  if (c == "r") { seqMode = 2; seqIdx = 0; seqT = millis(); setThrottle(1200); return; }
}

void loop() {
  if (Serial.available()) { String c = Serial.readStringUntil('\n'); c.trim(); if (c.length()) handle(c); }
  // sequences
  if (seqMode == 1 && millis() - seqT > 4000) {
    seqIdx++; seqT = millis();
    if (seqIdx >= (int)(sizeof(SWEEP) / sizeof(SWEEP[0]))) stopAll("sweep done"); else setThrottle(SWEEP[seqIdx]);
  }
  if (seqMode == 2 && millis() - seqT > 3000) {
    seqIdx++; seqT = millis();
    if (seqIdx == 1) setThrottle(1600); else stopAll("step done");
  }
  // tach
  unsigned long now = millis();
  if (now - lastTach >= 250) {
    noInterrupts(); unsigned long p = tachPulses; interrupts();
    rpm = (p - lastPulses) * 60000.0 / ((now - lastTach) * blades);
    lastPulses = p; lastTach = now;
  }
  float thrust = lc.is_ready() ? lc.get_units(1) : NAN;
  float v = ina.getBusVoltage(), i = ina.getCurrent();
  float torque = (haveTorque && tq.is_ready()) ? tq.get_units(1) : NAN;
  if (i > MAX_CURRENT_A) stopAll("overcurrent");
  if (throttle > 1000 && v < MIN_VOLTAGE_V) stopAll("undervoltage");
  Serial.print((now - t0) / 1000.0, 3); Serial.print(',');
  Serial.print(throttle); Serial.print(',');
  Serial.print(thrust, 3); Serial.print(',');
  Serial.print(v, 4); Serial.print(',');
  Serial.print(i, 4); Serial.print(',');
  Serial.print(rpm, 0); Serial.print(',');
  if (isnan(torque)) Serial.println(""); else Serial.println(torque, 3);
}
