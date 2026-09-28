# 02 — Product definition: what Sentinel is, where it sits, what it talks to

## 1. One-sentence definition
**V-Guard Sentinel is a self-contained sensing-and-control module for the home inverter–battery system**: a small box powered from the battery that measures the battery (V, I, T) and the inverter's AC output (V, I, P, Q), runs all its estimation and TinyML on an ESP32-S3 without any network, and acts through (a) load contactors in the distribution board and (b) — on new V-Guard inverters only — the charger.

## 2. System boundary
```
                         ┌──────────────── Sentinel Core (box, 90×70×35 mm) ────────────────┐
  battery + ─────────────┤ V sense (fused)                                                    │
  battery − ══[SHUNT]════┤ INA228 Kelvin sense           ESP32-S3 ── TFLM (int8 CNN) ── EKF   ├──▶ 4 coil outputs ──▶ [contactor panel in DB]
  NTC on battery ────────┤ NTC input                     LittleFS · NVS · RTC · secure element│──▶ (embedded) DAC/UART ──▶ charger feedback node
  AC-OUT L/N ────────────┤ AMC1311 fast V tap             Wi-Fi/BLE (optional, off in outages) ├──▶ app / cloud (optional)
  CT on AC-OUT live ─────┤ ATM90E32AS metering AFE                                             │
  CT on mains (optional)─┤ AFE channel 2                                                       │
  12 V from battery ─────┤ MP2315 buck → 3.3 V (≈2.6 mA avg)                                   │
                         └───────────────────────────────────────────────────────────────────┘
```
Inside the boundary: all sensing, estimation, ML, decisions, logging. Outside: the inverter (unmodified on retrofit), the battery (unmodified), the DB contactors (installed by an electrician), the phone app and cloud (optional, additive).

## 3. Two SKUs — the same core, different attachment
| | Sentinel-Retrofit (what the prototype is) | Sentinel-Embedded (what V-Guard would ship) |
|---|---|---|
| Form | box beside the inverter | daughter-board inside the inverter |
| Battery current | external busbar shunt in the negative lead | Kelvin tap on the inverter's own shunt |
| AC sensing | CT clamped on the AC-OUT live + plug-in voltage tap | divider + isolator on the AC-OUT rail |
| Mains present | own AC-IN sense or inferred from current sign | control-board signal |
| Charger | **no control** (advisory) | DAC on the PWM feedback node (design 03) |
| Contactors | external panel, 2–4 channels | same |
| Power | from battery via buck | from the inverter's 12 V rail |
| Install | electrician: 30–45 min (cut negative lead, clamp CT, wire contactors) | factory |

## 4. Interfaces (every connector on the box)
| # | Connector | Signal | Wire | Notes |
|---|---|---|---|---|
| J1 | BAT+ | battery positive sense + module power | 1 mm², 2 A fuse at the battery end | powers the buck; sense divider 1 MΩ:56 kΩ |
| J2 | SHUNT S+ / S− | Kelvin sense (≤ 50 mV) | twisted pair | never carries load current |
| J3 | BAT− | ground reference | 1 mm² | from the shunt's inverter-side terminal |
| J4 | NTC | 10 k NTC probe on the battery terminal/case | 2-wire, 0.5 m | |
| J5 | AC-OUT V tap | 230 V L/N | 2-pin plug into an inverter output socket | feeds AMC1311 (isolated) and AFE voltage channel via divider |
| J6 | CT1 | 3.5 mm jack, SCT-013 on AC-OUT live | | burden on board |
| J7 | CT2 (optional) | SCT-013 on mains incoming | | for whole-house Coach |
| J8 | COIL1–4 + COM | 12 V DC to contactor coils, ≤ 500 mA each | 0.75 mm² | ULN2003 sinks; COM = 12 V |
| J9 | AUX-IN | optocoupled "mains present"/mode line (embedded, or retrofit if opened) | 2-wire | 3.3 V logic after opto |
| J10 | CHG (embedded only) | I²C to DAC / UART to charger MCU + charger-state | 4-wire | |
| J11 | USB-C | provisioning, logs, firmware | | |
| — | Wi-Fi / BLE | app, OTA, telemetry | — | optional |

## 5. What the product does, in the order it does it (a day in the life)
1. **Powers up** from the battery, restores its last state from NVS, closes nothing (contactor coils off = all loads on).
2. **Senses at 1 Hz**: battery V/I/T → EKF → SoC, R_int (design 01). Detects charge/discharge state transitions itself (no inverter signal needed).
3. **At every outage/recharge cycle end**: computes 14 features, runs the TinyML SoH/RUL model, updates the grade (design 02). Signs the events into the health log (design 09).
4. **Continuously (mains present)**: AFE streams P/Q at 3 Hz → NILM events → per-appliance kWh (design 06); AMC1311 path watches for sags/swells (design 07); hourly load/outage tables update (design 05).
5. **When mains fails** (detected 2-of-3 within 2 s): Wi-Fi off, NILM paused, autopilot evaluates every 60 s and sheds T3/T2 by SoC with hysteresis (design 05); shows estimated backup time.
6. **When mains returns**: restores tiers after dwell, watches the recharge taper for the full-charge anchor, closes the cycle.
7. **When a phone is near / Wi-Fi is up**: syncs summaries, labels, OTA — none of which is required for steps 1–6.

## 6. Non-goals for the prototype (say them out loud)
No federated learning demo (deferred). No charger control on a retrofit inverter. No claims about individual loads under ~40 W. No SoH numbers trained on real lead-acid data until the campaign — the prototype shows the pipeline live on a real battery for SoC/R_int and the SoH/RUL model on transferred/synthetic weights with its band visibly wide.
