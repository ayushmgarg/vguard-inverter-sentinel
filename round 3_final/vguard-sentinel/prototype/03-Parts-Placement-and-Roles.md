# 03 — Every part we add: what it is, where it physically sits, what it does, what it connects to

Element numbers (E*, I*, B*) refer to 01. All parts are for the **Retrofit** configuration unless marked (Embedded).

## 1. The Sentinel Core board (one PCB, 80 × 60 mm, in a 90 × 70 × 35 mm UL94 V-0 box beside the inverter)
| # | Part | Role | Connects to | Why this part |
|---|---|---|---|---|
| C1 | **ESP32-S3-WROOM-1-N16R8** (dual LX7 @ 240 MHz, 512 KB SRAM + 8 MB PSRAM, 16 MB flash, Wi-Fi/BLE) | the whole brain: sensing loop, EKF, feature pipeline, TinyML inference, NILM, PQ, autopilot, logging, radios | everything below | vector extensions (ESP-NN) make int8 CNNs 5–14× faster; enough flash for A/B firmware + A/B models + 1 MB data; cheapest MCU with this + radio |
| C2 | **MP2315** buck, 12/24 V → 3.3 V | powers the board from the battery, so it works during outages and needs no adapter | J1 BAT+, J3 BAT− | 0.85 mA quiescent; 4.5–24 V input covers 12 V and 24 V systems |
| C3 | **INA228** 20-bit ΔΣ current/voltage monitor | measures the shunt's ±50 mV drop (current) and battery voltage; hardware charge accumulator | J2 S+/S−, J1 divider; I²C to C1 | ±1 µV offset → 10 mA bias on 0.1 mΩ; 40-bit coulomb counter in silicon |
| C4 | **NTC 10 k β3950 input** (divider + RC to C1 ADC; or TMP117 on I²C for ±0.1 °C) | battery temperature for Arrhenius stress, charge compensation, EKF tables | J4 | battery temperature is the #1 aging driver in India and nothing else measures it |
| C5 | **AMC1311** isolated amplifier + 1 MΩ divider | isolated fast sample of AC-OUT voltage → C1 ADC at ~4 kS/s for half-cycle RMS, zero-cross, outage detection, sag/swell | J5 | reinforced isolation; independent of the AFE so outage detection survives an AFE fault |
| C6 | **ATM90E32AS** metering AFE + 2 × CT burden networks + voltage divider | true P, Q, S, PF, Irms, I-peak, fundamental/harmonic P at 3 Hz on the AC output (and optional mains) — the NILM signal | J5 (V), J6/J7 (CTs); SPI to C1 | the ESP32 ADC cannot do metrology; this chip is what smart meters use |
| C7 | **ULN2003** Darlington array (+ pull-downs on inputs) | sinks 12 V contactor-coil current, 4 channels, flyback diodes to COM | J8; GPIO from C1 | 500 mA/ch; coil off on reset = fail-safe |
| C8 | **Supervisory timer** (e.g., a 555/TPL5010-class watchdog or a small comparator) gating the coil-enable rail | if C1 stops toggling the heartbeat pin for 2 s, cuts all coils → all loads ON, regardless of firmware | between C7 and J8 COM | independent of the MCU's own watchdog |
| C9 | **Medical jumper** JP1 | hard-wires one contactor channel's coil to "never energise" | C7 channel 4 | a hardware guarantee the app cannot override |
| C10 | **DS3231** RTC + CR2032 | time-of-day through outages and Wi-Fi-less months; timestamps the health log | I²C | ESP32 RTC drifts unpowered |
| C11 | **ATECC608** secure element | per-device ECDSA key that never leaves the chip; signs the health log; TLS client identity | I²C | warranty evidence needs a non-extractable key |
| C12 | **Optocoupler input** (PC817) | reads an inverter "mains present"/relay-coil line if tapped | J9 | second vote for outage detection |
| C13 | **MCP4725 DAC** (Embedded only) + **UART level shifter** | injects the charge-setpoint offset into the SG3525/TL494 feedback node; talks to a charger MCU if present | J10 | the only way to make charging adaptive; hardware clamp on the inverter side |
| C14 | USB-C (CP2102/native), 3 status LEDs, reset/boot buttons, TVS on every external line, ferrite beads on cable entries | provisioning, service, protection | J11 | |

## 2. The parts outside the box
| # | Part | Where it physically sits | Role | Install note |
|---|---|---|---|---|
| X1 | **Busbar shunt 500 A / 50 mV (0.1 mΩ), 4-terminal** (Indian-market 500 A/75 mV = 0.15 mΩ is equally fine: INA228 range ±163.84 mV, INA226 ±81.92 mV) | **in the battery negative cable**: battery − lug → shunt → new short cable → inverter − terminal | all battery current passes through it; Kelvin terminals give the mV signal | the only cut in the system; bolt torque per shunt spec; keep total added resistance < 0.2 mΩ so inverter low-battery sensing is not affected |
| X2 | **NTC probe** | strapped/glued to the battery negative terminal post or the case wall near the middle cell | electrolyte-proximate temperature | terminal post tracks electrolyte within ~2 °C |
| X3 | **Fused BAT+ sense/power lead** (2 A blade fuse at the battery lug) | battery + lug → box J1 | module power + voltage reference | fuse at the source end |
| X4 | **CT1 SCT-013-030 split-core** | clamped on the **live** conductor of the inverter AC-OUT cable (before it enters the DB inverter group) | AC output current for the AFE | must clamp one conductor only |
| X5 | **AC voltage tap** | 2-pin plug into the inverter's AC-OUT socket (or terminal block) | reference voltage for P/Q and half-cycle RMS | double-insulated lead |
| X6 | **CT2 (optional)** | clamped on the mains live at the DB main switch | whole-house Coach (AC, geyser, pump) | |
| X7 | **Contactor panel**: 2–4 × 25 A 2NC DIN contactors, 12 V DC coils, on a DIN rail in/next to the DB | **in series with the inverter-group sub-circuits**: ch1 = T1 essentials (fridge/router/one light circuit) [jumper-locked], ch2 = T2 fans/TV, ch3 = T3 heavy sockets, ch4 = medical/never-shed | opens a sub-circuit when the coil is energised; closed (loads on) when de-energised | NC block in the live path; coil wiring must be verified with a "power-off = loads on" test before commissioning |
| X8 | **Optocoupled tap** (optional) | inside the inverter, on the "mains" LED or relay-coil line | mains-present signal | electrician-only; Embedded has it natively |
| X9 | **Phone app / cloud** | — | display, labels, OTA, telemetry | optional |

## 3. Placement drawing (retrofit, one battery)
```
 WALL/DB ─────────────────────────────────────────────────────────────────────────────
 │ [E3 DB]  main MCB ── mains L ──(X6 CT2 optional)── ...
 │           │
 │           ├─ MCB "inverter in" ───────────────────────────▶ [Inverter AC-IN]
 │           │                                                        │
 │           └─ inverter-group sub-DB ◀──(X4 CT1 on live)──── [Inverter AC-OUT] ──(X5 V tap)──▶ Sentinel J5
 │                 ├─ X7 ch1 (NC, locked)  ─ fridge, router, hall light
 │                 ├─ X7 ch2 (NC)          ─ fans, TV
 │                 ├─ X7 ch3 (NC)          ─ heavy sockets
 │                 └─ X7 ch4 (NC, medical) ─ CPAP socket
 │                       ▲ coils ◀── J8 (4 × 12 V) ─── [Sentinel Core box] ── J11 USB
 │                                                            │ J1 BAT+ (X3 fused) ── battery + lug
 │                                                            │ J2 S+/S− (Kelvin) ─── X1 shunt
 │                                                            │ J3 BAT− ──────────── shunt inverter side
 │                                                            │ J4 NTC ───────────── X2 on battery
 │  [Inverter]  BAT+ ───────────────────────────────── battery + ═╗
 │              BAT− ─── X1 SHUNT ─── battery − ═════════════════╝  [12 V tubular battery, 100–230 Ah]
```

## 4. Why each engine needs which part (traceability)
| Engine | Needs | Parts |
|---|---|---|
| SoC/R_int EKF (01) | I, V, T at 1 Hz; charger state (inferred) | C3, X1, X3, C4/X2 |
| SoH/RUL TinyML (02) | the EKF outputs + cycle segmentation | C1 (TFLM+ESP-NN), C3 |
| Autopilot (05) | SoC, load forecast tables, outage detection, contactors, clock | C1, C5, C7–C9, X7, C10 |
| NILM Coach (06) | P/Q/PF/Ipeak/harmonics at 3 Hz on AC-OUT | C6, X4, X5 (+X6) |
| Grid Shield (07) | half-cycle RMS + FFT of AC-OUT/mains voltage | C5 (+C6 sag flag) |
| Health log / warranty (09) | signed events, time | C11, C10 |
| Adaptive charging (03) | charger setpoint path | C13 (Embedded only) |
