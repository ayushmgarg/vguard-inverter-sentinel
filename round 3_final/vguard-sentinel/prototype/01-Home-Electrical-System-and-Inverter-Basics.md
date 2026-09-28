# 01 — How a typical Indian home electrical system works, and what the inverter actually does

Purpose: the physical ground truth the product sits on. Everything in 02–05 refers back to the numbered elements here.

## 1. The home electrical system (single-phase, 230 V, 50 Hz)
```
DISCOM pole ──(service cable)──▶ [E1 Energy meter] ──▶ [E2 Main MCB/RCCB] ──▶ [E3 Distribution board (DB)]
                                                                                   ├─ MCB: AC bedroom        ─┐
                                                                                   ├─ MCB: geyser             ├─ NON-INVERTER group
                                                                                   ├─ MCB: kitchen / pump     ─┘
                                                                                   ├─ MCB: "inverter in"  ──▶ [E4 Inverter AC-IN]
                                                                                   │                              [E5 Inverter AC-OUT] ──▶ sub-DB / inverter MCB group
                                                                                   │                                                        ├─ lights + fans (rooms)   ─┐
                                                                                   │                                                        ├─ TV / router / sockets   ├─ INVERTER group
                                                                                   │                                                        └─ fridge (sometimes)     ─┘
                                                                                   └─ Neutral bar (common) · Earth bar
```
- **E1–E3**: meter, main breaker, DB with one MCB per circuit. Most flats are single-phase; larger houses are 3-phase but the inverter is wired on one phase.
- **The split the electrician makes when installing an inverter** (the single most important fact for this product): the DB is divided into an **inverter group** (lights, fans, TV, router, a few sockets, often the fridge) and a **non-inverter group** (AC, geyser, pump, oven, induction). Only the inverter group passes through the inverter. A 600–1,500 VA unit cannot run the heavy loads, so they are simply not wired through it.
- **Neutral** is common between both groups in most Indian installs (the inverter's output neutral is bonded to the mains neutral inside the unit or at the DB). **Earth** is bonded to the inverter chassis.
- **Battery cables**: 2 × short thick leads (typically 25–35 mm² / "6–10 sq mm or thicker" lugs) from inverter to battery, 0.5–1.5 m. This is the only place DC current flows — and where our shunt goes.

## 2. The inverter–battery system (the thing we instrument)
```
[E4 AC-IN] ──▶ [I1 mains sense] ──▶ [I2 changeover relay] ──▶ [E5 AC-OUT] ──▶ inverter group loads
                      │                    ▲
                      ▼                    │ (battery mode)
              [I3 control board] ──▶ [I4 MOSFET bridge] ──▶ [I5 LF transformer 12 V ↔ 230 V] ──┘
                      │                    ▲
              [I6 charger control]────────┘ (same bridge + transformer run in reverse as the charger)
                      │
        [I7 battery V sense] [I8 current sense (if any)] [I9 NTC (if any)] [I10 fan] [I11 panel: LEDs/LCD, buzzer, mode switch, battery-type selector]
                      │
              [B1 Battery +] ═══ 12 V tubular flooded, 100–230 Ah ═══ [B2 Battery −]      (24 V = two in series on 1.5–2 kVA+ units)
```
| Element | What it is | What it exposes |
|---|---|---|
| I1 mains sense | small transformer or resistor divider + comparator/zero-cross detector on the control board | "mains present" logic level internally; drives a front-panel LED |
| I2 changeover relay | electromechanical relay switching AC-OUT between mains pass-through and the bridge output | coil line on the control board (12 V); audible click |
| I3 control board | SG3525/TL494 PWM controller (+ optional 8-bit MCU for display/logic) | no external bus on non-solar units |
| I4/I5 bridge + transformer | push-pull MOSFETs at 50 Hz (pure sine = high-frequency PWM within the half-cycle) into a low-frequency iron transformer | — |
| I6 charger | the same bridge/transformer run as a controlled rectifier from mains; setpoints fixed by resistor dividers / trim pot; selector switches between tubular/SMF/Li profiles | battery-type selector switch on the panel |
| I7 battery V sense | resistor divider into the control board (low-battery cut-off, charge termination) | — |
| I8 current sense | often absent; some units: PCB shunt in the battery negative return or MOSFET source; overload sense sometimes via a CT on the AC output | — |
| I9 NTC | some units on the transformer/heatsink for thermal derating; almost never on the battery | — |
| I11 panel | LEDs (mains/battery/charging/overload), sometimes LCD %, buzzer, mode switch (UPS/normal or eco), battery-type selector | the only user interface |
| B1/B2 | two lead terminals; six vent plugs; float level indicators on some; **no electronics at all on the battery**; V-Guard units accept one 12 V battery of **80–230 Ah** | — |

**So: is our idea "on the battery or on the inverter"?** Neither alone. The battery is a dumb electrochemical cell; the inverter is the only powered, switching element. Sentinel is a module for the **inverter–battery system**: it sits *in the battery cable* (current), *on the battery* (temperature), *at the inverter output* (AC), and *in the DB* (contactors). See 02.

## 3. What the inverter does, state by state
| State | Trigger | What happens | Timing |
|---|---|---|---|
| **S1 Mains pass-through + charging** | mains inside the accepted window | AC-OUT = mains via I2; bridge idle; charger charges the battery (bulk → boost/absorption → float) | continuous |
| **S2 Transfer to battery** | I1 sees mains out of window: **UPS mode 180–260 V ±6 V, 47–53 Hz** (tight, for PCs); **Normal mode 90–290 V ±10 V, 43–57 Hz** (wide, saves battery) — or total loss (V-Guard Prime spec sheets) | I3 starts the bridge, I2 switches AC-OUT to the bridge output | **< 10 ms** on V-Guard Prime (UPS mode); generic units 10–20 ms UPS / up to ~40 ms normal — fast enough for lights/fans/router; PCs need UPS mode |
| **S3 Battery mode (backup)** | — | bridge draws 12 V DC from the battery: I_batt ≈ P_load / (12 V × η), η ≈ 0.80–0.88 → 300 W of load ≈ 30 A; battery voltage sags with load | until mains returns or cut-off |
| **S4 Low-battery cut-off** | V_batt ≈ 10.5–10.8 V under load (12 V system) | bridge stops; AC-OUT dead; buzzer; unit waits for mains | — |
| **S5 Overload / short** | I_out > rating (e.g., > 110–120 %) | bridge trips; retries or latches | ms |
| **S6 Mains return** | I1 sees mains stable for a few seconds | I2 switches back to pass-through; charger resumes in bulk | seconds |
| **S7 Charging stages** | — | 4-stage on Indian units: **bulk ≈ 10 % of Ah (15 A for 150 Ah)** until ≈ 14.4 V; **absorption 14.4 V** until current tapers; **float 13.5–13.6 V**; trickle. V-Guard quotes only "recharge 8–12 h depending on capacity and charging selection"; Smart Pro adds a "Turbo charge" (+30 %) mode | 8–12 h from cut-off |
Numbers are typical for the class; model-specific values are in §5 (filled from V-Guard datasheets).

## 4. The signals that exist and the ones that do not
| Signal | Exists on the battery? | Exists on the inverter? | How Sentinel gets it |
|---|---|---|---|
| Battery voltage | terminals | I7 internally | our own divider from B1/B2 |
| Battery current | no | I8 sometimes, internal | **our shunt in the B2 lead** (retrofit) / Kelvin tap on I8 (embedded) |
| Battery temperature | no | no (I9 is on the heatsink) | **our NTC on the battery** |
| Mains present / battery mode | no | I1/I2 internally; panel LED | our AC sense on AC-IN (retrofit), or the LED/relay-coil line via optocoupler (embedded, or retrofit if the electrician opens the unit) |
| AC output V, I, P, Q | no | I8 rarely, internal | **our CT + voltage tap on E5 / AC-OUT** |
| Charger state / setpoints | no | I6 internally, fixed | embedded: our DAC/UART (design 03); retrofit: inferred (current sign + V) |
| Load per circuit | no | no | our contactor channels in the DB |
| Time of day | no | no | our RTC |
Everything in bold is what the product adds. Nothing on the battery or the retrofit inverter has to be modified for the retrofit SKU except inserting the shunt in the negative cable.

## 5. V-Guard model facts (verified 2026-09-21 from vguard.in spec PDFs and retailer pages)
| Model | VA / peak W | Wave | Battery | Mains window | Transfer | Recharge | Size / weight | Extras | Price |
|---|---|---|---|---|---|---|---|---|---|
| **Prime 1050** | 900 VA | pure sine | 1 × 12 V, 80–230 Ah | Normal 90–290 V ±10 V, 43–57 Hz; UPS 180–260 V ±6 V, 47–53 Hz | < 10 ms | 8–12 h | 275×250×120 mm | 0–45 °C | — |
| **Prime 1150** | 1000 VA / 800 W | pure sine | 1 × 12 V, 80–230 Ah | (sibling-model windows; no separate PDF found) | — | 10–12 h | — | LED graphical display (mains, charging, low backup, overload, short-circuit, water-topping reminder), UPS/Normal switch, mute buzzer | ₹6,399–6,699 (MRP ₹9,590) |
| **Prime 1575** | 1300 VA | pure sine | 1 × 12 V, 80–230 Ah | as Prime 1050 | < 10 ms | 8–12 h | 275×255×120 mm | EV 2-wheeler charging ≤ 350 W, "Battery Gravity Builder" (overcharge/deep-discharge management), fuzzy-logic water-level reminder | — |
| **Smart Pro 1200S** | 1000 VA / ~800 W | pure sine | 1 × 12 V, 80–230 Ah | — | — | 8–10 h ("Turbo charge" 30 % faster) | ~275×250×120 mm, ~9.5 kg | **solar-hybrid with built-in charge controller (≤ 640 Wp), built-in Wi-Fi + Bluetooth, V-Guard Smart 2.0 app**, LCD (input/output V, battery level, modes), Appliance mode (to 1000 W), Holiday mode, water-topping reminder | ₹8,299–8,999 (MRP ₹13,490) |
Sources: V-Guard Prime 1050 and Prime 1575 legal-metrology PDFs (vguard.in/uploads/Documents), Prime 1150 and Smart Pro 1200S product pages, Flipkart/Amazon listings. **Not found in any V-Guard document**: the exact low-battery cut-off (industry: ~10.5 V; 11 V advised for tubular life), any USB/RS-232/"PC" port, any serial/Modbus interface. The Smart Pro's Wi-Fi/BLE is built in, not a UART dongle. V-Guard's "Smart DUPS" marketing lists BLE + Wi-Fi with Alexa/Google. Luminous, by contrast, sells a standalone Wi-Fi dongle with documented RS-485 + UART for its off-grid/hybrid inverters (register map not public).

**What this means for the product**: (1) every retrofit target is a 12 V single-battery unit in the 80–230 Ah range — one shunt SKU covers all; (2) the app-connected V-Guard unit already exists (Smart Pro 1200S) — Sentinel-Embedded slots into that family and inherits its Wi-Fi/BLE and app; (3) since the cut-off and charge setpoints are undocumented, the retrofit infers them from the battery terminals (design 01 §5) rather than assuming values; (4) the "Battery Gravity Builder" and water-topping reminders show V-Guard already markets battery-care logic — Sentinel is the data-backed version of that promise.

### Wiring facts verified
Dedicated MCB (often with its own RCCB) for the inverter-backed circuit; a 12-way DB example uses 2 RCCB + 8 MCB, one set for mains and one for inverter loads (eeetechs4u). Inverter AC-in from a dedicated mains MCB; AC-out to the inverter-line MCB/RCCB (electroniclinic). Common neutral for both circuits is standard practice. Battery-to-inverter cable ≥ 4 mm² Cu, inverter-out-to-DB ≥ 6 mm² Cu (Bajaj Finserv guide; other guides differ, so gauge is source-dependent). Typical inverter-line loads: fans, LED/tube lights, TV, router, laptop, small fridge — matching V-Guard's own application charts. Inside the unit: SG3525/KA3525 PWM into a push-pull MOSFET bank and a step-up transformer; changeover relay driven by an optocoupler-based mains-sense circuit (teardowns of Microtek/Luminous 173PCB); optocouplers and current sensors are noted failure points. Exact current-sense topology and NTC/fan lines are only visible in video teardowns — to be confirmed on the bench when a unit is opened (Tier 2).
