# 05 — Prototype build plan: what to buy, how to wire it, how to bring it up, what to demo

Three tiers. **Tier 0 is what can be on the table at the finale**; Tier 1 is the real retrofit prototype; Tier 2 is the embedded proof. Prices are indicative INR from Indian hobby distributors (verified figures in §6).

## 1. Tier 0 — bench demonstrator (days; ~₹25–35 k incl. battery + inverter)
Goal: a real 12 V tubular battery and a real inverter on the table; live SoC/R_int; real outage → tiered shedding → fail-safe; live appliance events; the TinyML pipeline running end to end (on transferred/synthetic weights, labelled honestly).
| Item | Qty | Purpose | Approx |
|---|---|---|---|
| ESP32-S3 N16R8 devkit (probots) or DevKitC-1-N8R8 (robu) | 1 | Core | ~₹1,299 |
| **INA226 module** (INA228 breakouts are not sold in India — INA226 is 16-bit, ±2.5 µV offset, ±81.92 mV input; **remove/bypass its onboard 2 mΩ shunt** and wire IN± to the external shunt's Kelvin terminals) | 1 | battery I/V | ~₹529 (probots; also robu) |
| Busbar shunt **500 A/75 mV** (CG FL-P, robu.in) or 200 A/75 mV, 4-terminal — 75 mV fits INA226's ±81.92 mV range | 1 | battery current (Tier 0 currents ≤ 60 A) | ~₹1,500 (IndiaMART, 500 A) |
| 10 k NTC probe (waterproof, 1 m) | 1 | battery T | ₹75 |
| **PZEM-004T v3** (UART 9600, 100 A split CT; V 80–260 V, I 0–100 A @1 mA, P, PF, energy; class 1.0; polled ~1 Hz) | 1–2 | AC-OUT (and mains) metering for the NILM demo — a pragmatic stand-in for the ATM90E32AS (no harmonics/I-peak; Q from S·sin φ) | ₹799–999 each |
| SCT-013-030 + ZMPT101B (optional) | 1 | only if an ATM90E32 board is imported (CircuitSetup ships from the US; no Indian stock found) | ₹460 + ₹136 |
| 4-channel 12 V opto relay module, **10 A @ 250 VAC, NO+NC** (a 30 A 4-ch module exists on robu) — or 2 × branded 25 A DIN contactors, 12 V DC coil, for realism | 1 | tier switching; wire loads through **NC** | ₹183 / ₹1,050–1,100 each |
| ULN2003 board, pull-down resistors, a 555 monostable as supervisory timer | 1 | fail-safe demo | ₹150 |
| DS3231 module | 1 | clock | ₹223 |
| ATECC608 breakout (optional at Tier 0) | 1 | signing demo | ₹300–600 |
| MP2315/LM2596 buck 12 V→5 V/3.3 V, 2 A blade fuse + holder, 1 mm² fused lead | 1 | power from battery | ₹150 |
| Loads: 2 LED bulbs 9 W, table fan 50 W, 100 W incandescent, 500 W heater/iron, small fridge or a 90 W motor | — | T1/T2/T3 and NILM events | ₹1,500–3,000 |
| 12 V 150 Ah tubular battery + 900–1000 VA inverter (e.g., V-Guard Prime 1050/1150 ₹6.4–6.7 k) | 1+1 | the system under test | ₹14–20 k + ₹6.4–8 k (combos ₹15–28 k) |
| Extension boards, 2.5 mm² wire, lugs, crimp tool, DIN rail, enclosure | — | | ₹1,500 |

### Bench wiring (Tier 0)
```
mains socket ──[MCB 6 A]── inverter AC-IN
inverter AC-OUT ──(PZEM-004T CT on live)──▶ 3-way splitter:
      ├─ RELAY1 NC ── LED bulb + phone charger + Wi-Fi router     (T1, jumper-locked)
      ├─ RELAY2 NC ── table fan + 100 W bulb                       (T2)
      └─ RELAY3 NC ── 500 W iron/heater                            (T3)
battery + ──(2 A fuse)── buck → ESP32 5 V;  battery + ── INA228 VBUS/divider
battery − ── SHUNT ── inverter − ;  shunt Kelvin → INA228 IN+/IN−
NTC on battery − post → ESP32 ADC (divider)
PZEM TX/RX → ESP32 UART1;  DS3231 → I²C;  relay module IN1–4 ← ULN2003 ← ESP32 GPIO (+ 555 supervisory gating relay VCC)
```
Outage = flip the 6 A MCB. Fail-safe demo = press the ESP32 reset while T3 is shed → RELAY3 re-closes within ~1 s.

### Bring-up sequence (order matters)
1. Power + INA228: read V, zero-current offset cal; add a known 5 A load (bulb on inverter) → check I within 2 %.
2. NTC: compare to a kitchen thermometer.
3. EKF (design 01): run 24 h of charge/discharge; log fused vs raw SoC; check re-anchoring on a full-charge taper.
4. Relays: verify "power-off = loads on" with the ESP32 unpowered before connecting any load.
5. Outage detection 2-of-3 (PZEM Vrms < 20 V, current sign flips, [opto if tapped]) → autopilot thresholds (design 05).
6. PZEM stream at 1 Hz → event detector with N_pre/N_post = 3 s, P_th = 25 W → clusters → label in a serial console/app.
7. Feature pipeline + TFLM: flash the Stage-A/B model; confirm the golden self-test; run inference on replayed feature windows (see demo mode).
8. Health log: sign events with ATECC608 (or a software key at Tier 0); verify on a laptop.
9. App/dashboard — **built**: `python -m dashboard.app --provider file --file firmware/host/state.json` (or `--provider fixture` for the scripted finale sequence); all code paths in `code/` with `bash code/run_all.sh` reproducing every number in `00-Status-Crosswalk.md`.

### Demo mode for SoH/RUL (honest) — implemented in `code/firmware/main/replay.c` and `code/dashboard` (fixture provider)
The bench battery will not age in a week. Ship a **replay** switch: the device ingests a pre-computed per-cycle feature trajectory from the synthetic simulator (design 02 §4.3) as if the cycles had happened, so the judge sees the grade move Healthy → Degrading → "Replace within 9 weeks (6–14)" with the conformal band, while a banner says "replayed synthetic aging; live battery is at cycle 12 — collecting data". Live SoC/R_int and everything else is real.

## 2. Tier 1 — retrofit prototype (4–6 weeks; ~₹8–12 k for the module, excluding battery/inverter)
- Custom 80 × 60 mm PCB per design 10 and 03 §1: ESP32-S3-WROOM-1, MP2315, INA228 on a 500 A/50 mV shunt, NTC input, AMC1311 tap, **ATM90E32AS** with 2 CT inputs (CircuitSetup 6-channel board is an acceptable interim), ULN2003 + supervisory timer + medical jumper, DS3231, ATECC608, USB-C, TVS on all lines, moat between HV and SELV.
- 4 × 25 A 2NC DIN contactors on a rail; installer wiring per 03 §2.
- Firmware per 04 §2 with all tasks; app over BLE/Wi-Fi.
- Test per design 11: SoC RMS vs a lab shunt, outage-detection latency, fail-safe 100/100, NILM on ≥ 10 appliances, PQ vs a programmable source (or a variac for sags).
- Two units installed in team members' homes for 4+ weeks of real outage logs → the first real habit tables and NILM labels.

## 3. Tier 2 — embedded proof (with V-Guard R&D)
Open one V-Guard inverter: locate the SG3525/TL494 feedback divider; add the MCP4725 offset injection + hardware clamp (design 03 §1.1); tap the mains-present line and the charger relay; Kelvin-tap the internal shunt if present. Demonstrate temperature-compensated float and a scheduled equalisation commanded by Sentinel, with the safety ceiling tested.

## 4. Finale demo script (8 minutes, Tier 0)
1. (0:00) Open with the physical thing: battery, shunt in the negative lead, box, three NC relays with lamps/fan/iron. "Nothing here needs the internet."
2. (1:00) Live SoC/R_int/backup-time on screen; show the raw coulomb counter vs fused EKF.
3. (2:00) Flip the MCB: outage detected < 2 s (show the 2-of-3 votes); loads keep running on the inverter; backup-time drops as the iron is switched on.
4. (3:30) Force SoC ≤ 40 % (bench override) → iron circuit (T3) sheds with a click; fan stays; router stays. Restore mains → T3 returns after dwell.
5. (5:00) Press reset while T3 is shed → everything comes back within a second. "Coil off means load on."
6. (5:30) Switch the fan, then the iron: the Coach shows two events with ΔP/ΔQ/inrush and asks "what just turned on?"; label it; kWh accumulates.
7. (6:30) SoH/RUL replay: grade walks to "Replace within 9 weeks (6–14)"; explain the band and the banner.
8. (7:30) Show the signed health log verifying on the laptop; one altered byte fails.

## 5. What is deliberately not in the prototype
Federated learning — the Flower simulation promised in the report is cut from the prototype scope (design 12 D15); charger control on the retrofit inverter; individual loads under ~40 W; SoH numbers trained on real tubular data (campaign pending).

## 6. Verified part and product facts (2026-09-21)
- **Prices confirmed** from electronicscomp.com and probots.co.in (SCT-013-030 ₹460, ZMPT101B ₹136, 4-ch 12 V relay ₹183, DS3231 ₹223, INA226 ₹529, ESP32-S3 N16R8 ₹1,299); robu.in blocks automated fetches so its prices are unconfirmed; IndiaMART figures for the 500 A shunt (~₹1,500) and 25 A 12 V-DC-coil contactors (₹1,050–1,100 branded; unbranded ₹150–650 with unverified specs); PZEM-004T v3 ₹799–999 (IndiaMART/robu).
- **Not available in India** (import or substitute): INA228 breakouts; CircuitSetup ATM90E32 boards; ADE7953 breakouts. Tier 0 therefore uses INA226 + PZEM-004T; Tier 1 places the ATM90E32AS (₹350 bare IC, DigiKey India) on our own PCB.
- **PZEM-004T limits**: 1 Hz polling, no I-peak, no harmonics → the Tier 0 NILM demo shows ΔP/ΔQ/duration/periodicity events on big loads only; inrush and harmonic-share features arrive with the AFE at Tier 1.
- **Inverter under test**: a V-Guard Prime 1050/1150 (900–1000 VA, 12 V, 80–230 Ah, < 10 ms transfer, UPS 180–260 V / Normal 90–290 V windows) is the natural choice — same family as the retrofit target. Its display already flags mains/charging/low-backup/overload; Sentinel's outage detection can be sanity-checked against the panel LED.
- **Contest-relevant**: V-Guard's Smart Pro 1200S already has built-in Wi-Fi/BLE and the Smart 2.0 app — the Embedded SKU is a daughter-board into that platform, not a new connectivity stack.
