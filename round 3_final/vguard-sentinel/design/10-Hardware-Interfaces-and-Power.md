# 10 — Hardware Interfaces, Fail-Safe Switching, Power Budget, Time, EMC (worked out to a T)

**Resolves Gap Register:** H15 (fail-safe wiring/watchdog — hardware half), H18/H27 (AC taps), H24 (power budget), H25 (reading an existing shunt), H26 (charger interface — see 03), H28 (metering AFE — see 06 §1.4), H29 (EMC), H35 (time sync), H36 (outage detection — hardware half).

## 1. Two SKUs — stated once, used everywhere
| | Sentinel-Embedded (new V-Guard inverter) | Sentinel-Retrofit (clip-on module) |
|---|---|---|
| Battery current | Kelvin-tap the inverter's own shunt (§2.1) | external 0.1 mΩ busbar shunt in the battery negative lead (§2.2) |
| Charger control | DAC/UART path (03 §1) | none — advisory |
| Charger-state signal | GPIO/status | grid-absent proxy |
| Inverter mode pin | available | only if physically accessible |
| AC metering | ATM90E32AS on the hot side, divider + digital isolator (06 §1.5 option B) | ATM90E32AS SELV via 230→12 V transformer (option A) |
| Contactors | driver board with 4 channels + medical jumper | same driver board, installer-wired |
| Enclosure | inside the inverter | 90×70×35 mm UL94 V-0, PCB 80×60 mm, mounts beside the inverter (Victron SmartShunt 69×69×31 precedent) |

## 2. Reading the battery current
### 2.1 Embedded — tap the existing shunt
Budget inverters that sense current use a manganin/constantan PCB shunt in the battery negative return (many sense nothing). Route two **Kelvin sense traces from the shunt's 4-terminal pads** (add Kelvin pads at layout if the existing shunt is 2-terminal — a one-time PCB change) to INA228 IN±; set `SHUNT_CAL` to the actual resistance (INA228 accepts a wide range; it need not be 0.1 mΩ).
### 2.2 Retrofit — external Kelvin shunt, low side
0.1 mΩ 4-terminal busbar shunt in the **negative lead** (common-mode near ground; INA228 CM range −0.3…+85 V). Twisted-pair sense wiring straight to the INA228 with a differential RC (10–33 Ω + 1–10 nF) to reject charger PWM noise; sense leads never routed near coil-drive wiring.
### 2.3 Range and burden
ADCRANGE = ±40.96 mV → **±409.6 A** full scale on 0.1 mΩ (a 1.5 kVA/12 V inverter peaks ≈ 125 A); ±163.84 mV range as an over-current fallback. At 125 A: 12.5 mV burden, **1.56 W** in the shunt → specify ≥ 3 W with copper pour/heatsinking. INA228 supply < 1 mA. The **Hall alternative (ACS758/TMCS1100)** remains a documented, mutually exclusive option for installations where cutting the battery lead is undesirable; it trades the INA228's 10 mA offset for a ~1 % gain error and ≈ ±0.5–1 A offset, which pushes coulomb drift to several %/week — acceptable only with daily re-anchoring. Default: shunt.

## 3. AC taps and the metering AFE
Decided in 06 §1: **ATM90E32AS** (3 CT channels: inverter output, mains, charger input), CT for current (inherently isolated), voltage by transformer (retrofit, SELV) or divider + isolated SPI (embedded). The **AMC1311** isolated divider feeding the ESP32-S3 ADC at ~4 kS/s is kept as an independent fast path for **half-cycle RMS** (07 §1) and outage detection — it needs no SPI, no AFE settling, and no metering accuracy (10 % class thresholds). THD: 4-cycle FFT on the AMC1311 path (ESP-DSP) is Class-S-like; if on-chip THD is wanted, ATM90E36A is pin-compatible.

## 4. Contactor fail-safe wiring and watchdog (H15)
- **NC (Form-B) contacts in the load path; coil energised = load shed; de-energised = load ON.** A normal DIN contactor's NC block does this — no special part.
- **Driver**: ULN2003 (500 mA/ch, internal flyback diodes; **COM pin tied to the coil rail**). Typical 25 A modular contactor coil 150–250 mA holding at 24 V DC → one channel with margin. **Coil economiser**: full pull-in for 50–100 ms, then PWM to 30–40 % duty → holding 60–100 mA.
- **Why not latching relays**: they hold their last state on power loss — the opposite of fail-safe. Monostable NC costs hold power only while shedding, which is the rare state.
- **Medical never-shed**: one branch whose coil circuit is wired through a **PCB jumper, not a GPIO**; removing the jumper is the only way to make it sheddable. Firmware also forces T1 on any channel whose DIP/jumper reads "locked" (05 §3).
- **Watchdog chain**: ESP32-S3 RWDT/MWDT → reset → GPIOs default to high-Z → ULN2003 inputs pulled low by **10–100 kΩ pull-downs** → coils off → NC contacts close → **all loads ON**. Plus an **independent supervisory timer on the driver board** gating the coil-enable rail: if the MCU's heartbeat GPIO stops toggling for 2 s, coils are cut regardless of firmware (05 §6).
- **Interlocks**: break-before-make ≥ 50 ms between any two channels that could cross-connect; auxiliary NC contact of one contactor in series with the other's coil where a mechanical interlock is warranted.
- **Part class**: 25 A, 2-pole (2NC), DIN modular, 12/24 V DC coil; Indian-market ₹500–1,500 (branded European ₹3,400–4,100 as a ceiling reference).

## 5. Power budget (H24) — a proposal to be measured, not a measured figure
| Element | State | Current | Source |
|---|---|---|---|
| ESP32-S3 | Wi-Fi TX peak | 240–335 mA bursts | Espressif datasheet; Qoitech S3 study |
| ESP32-S3 | modem-sleep | ~15 mA | Qoitech |
| ESP32-S3 | light-sleep | 240 µA (SoC); 1–3 mA board-level | Qoitech; ESP-IDF sleep docs |
| ESP32-S3 | deep-sleep | 7–8 µA | — |
| INA228 | active | < 1 mA | TI |
| ATM90E32AS | active | 13 mA — **duty-cycle via load switch** (sample 1 in 10 s for metering; keep on continuously only when NILM event detection is enabled) | Microchip |
| AMC1311 | active | ~10 mA/side — **duty-cycled** to the sample window | TI |
| DS3231 | backup | ~3 µA | ADI |
| ATECC608 | idle | µA | Microchip |
| MP2315 buck | quiescent | 0.85 mA; AAM light-load mode | MPS |
| Contactor coil | holding while shedding | 60–100 mA (economised) | — |
**Duty**: 1 Hz sense in light-sleep (20 ms awake @ ~30 mA) ≈ 2.6 mA; Wi-Fi 2 min/day ≈ 0.2 mA; BLE 1 s advertising ≈ 1–2 mA (design margin — a combo SoC is not a dedicated BLE chip; validate); AMC1311 duty-cycled ≈ 0.3 mA; INA228 + AFE amortised ≈ 1 mA (**NILM-on mode adds ~13 mA continuous for the AFE**). Steady state ≈ **5.6 mA at 3.3 V** → battery-side at 12 V, 87 % buck efficiency: ≈ 1.8 mA + 0.85 mA quiescent ≈ **2.6 mA ≈ 0.75 Wh/day ≈ 0.04 %/day of a 150 Ah battery** (its self-discharge is 2–5 %/month). NILM-on: ≈ +4 mA battery-side ≈ +1.2 Wh/day — still negligible on mains, and NILM is paused during outages.
**Outage policy**: Wi-Fi off (router is usually dead anyway), BLE advertising 5 s, NILM off, 1 Hz sensing kept (battery protection matters more, not less). **Shedding worst case**: +60–100 mA coil hold for hours — 15–20× the baseline; surfaced to the policy as a cost, still a net win because the shed load drew far more.

## 6. Time sync (H35)
SNTP whenever Wi-Fi is up; **DS3231** (±2 ppm, ≈ ±1 min/year, TCXO, CR2032 backup, ~3 µA) keeps time-of-day through any outage — the habit table (05) depends on it. The ESP32 RTC alone drifts too much unpowered.

## 7. Outage detection (H36) — hardware side
| Signal | Source | Debounce |
|---|---|---|
| Mains RMS < 0.1 pu (< 70 % for "sag-going-to-outage") | AMC1311 → ESP32 ADC half-cycle RMS; cross-checked by ATM90E32AS sag flag | ≥ 2 half-cycles to flag; ≥ 500 ms–2 s to declare |
| Inverter mode pin | embedded (retrofit only if accessible) | 100–200 ms |
| Battery discharge onset | INA228 sustained discharge > idle floor | 1–2 s |
Declare on **2 of 3 within 1 s** (or s1 alone for a longer window on retrofit); clear only when all agree mains is back > 0.9 pu for 10–30 s (05 §7).

## 8. EMC and protection (H29)
- **ESD**: IEC 61000-4-2 **Level 4 (±8 kV contact / ±15 kV air)** on user-accessible terminals. **Surge**: IEC 61000-4-5 1.2/50–8/20 µs, **Level 3 (1–2 kV)** on mains-adjacent lines. **EFT**: IEC 61000-4-4 on AC lines. Host standard IEC 62040 / IS/IEC 62368-1 remains the BIS gate (report §11).
- **Per line**: TVS at the protected pin (minimal trace inductance), series 10s–100s Ω, MOV ahead of the AC divider, ferrite/common-mode choke on every multi-wire cable entry (NTC leads, shunt Kelvin pair).
- **PCB partitioning**: a routed **keep-out moat** between the HV zone (AC divider, MOV, hot-side AFE) and the SELV zone (ESP32-S3, INA228, radios); the only crossings are the AMC1311 and the digital isolator. Creepage/clearance from **IEC 60664-1** tables for 230 V working voltage, pollution degree 2, the chosen material group — a design-review gate before layout freeze, not an eyeball figure (several mm class).

## 9. Consolidated BOM delta vs the submitted report
| Item | Status vs report | Est. |
|---|---|---|
| ATM90E32AS + CT + transformer/isolator | **added** (report's Coach had no AC signal) | ₹600–1,100 |
| MCP4725 DAC + hardware voltage/thermal clamp (embedded only) | **added** | < ₹100 |
| DS3231 + CR2032 | **added** | ₹250–400 |
| ATECC608 | **added** (report implied signing without a key store) | ₹50–80 |
| Driver-board supervisory timer + pull-downs + medical jumper | **added** | < ₹50 |
| Contactors ×4 (installer-supplied, per channel) | unchanged | ₹500–1,500 each |
| Basic board (ESP32-S3, INA228, NTC, MP2315, AMC1311, ULN2003, enclosure) | unchanged | ~₹500 embedded / ~₹800 retrofit with shunt |
Net, by engine tier: **basic board (Engines 1+2) ≈ ₹750; ≈ ₹1,050 standalone with shunt; + Coach kit (Engine 3) ₹600–1,000 → full retrofit ≈ ₹1,650–2,050; embedded increment ≈ ₹450–700 basic / ₹850–1,300 with Coach** — still small against a ₹15 k battery, but the report's ₹150–300 embedded figure must be revised (12 §D7).

## References
TI INA228, ULN2003V12, AMC1311, SLVA711 (IEC 61000-4-x protection) · Microchip ATM90E32AS; ATECC608A/B; MCP4725 · ADI DS3231; ADE9153A · MPS MP2315 · Espressif ESP32-S3 datasheet; ESP-IDF sleep modes; Qoitech ESP32-S3/C3/C6 sleep-power study · Finder/Europa/GEYA modular contactor listings (RS, Amazon.in) · IEC 61000-4-2/-4-4/-4-5; IEC 60664-1; IEC 62040; IS/IEC 62368-1 · Silicon Labs AN895 · Victron SmartShunt mechanical data.
