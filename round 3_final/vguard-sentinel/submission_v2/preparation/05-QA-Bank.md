# 05 · Q&A bank: think like the judging engineers

> The Q&A is worth **15 marks**, more than the presentation (10). The judges are V-Guard R&D engineers: power electronics, battery, firmware and product people.
> Format: **Q** → **short answer (say this, ≤ 20 s)** → *if pushed* (the deeper layer) → `source`.
> Categories: [A Problem & market](#a-problem-market--why-this) · [B Battery science](#b-battery-science) · [C Battery-health ML](#c-battery-health-ml-soh--rul) · [D TinyML on the ESP32](#d-tinyml-on-the-esp32) · [E Autopilot & control](#e-autopilot--load-control) · [F Safety & electrical](#f-safety--electrical-design) · [G NILM & Grid Shield](#g-energy-coach-nilm--grid-shield) · [H Hardware, BOM, power](#h-hardware-bom-power) · [I Charging (Embedded)](#i-adaptive-charging-embedded) · [J Security, log, OTA, privacy](#j-security-health-log-ota-privacy) · [K Simulation & prototype](#k-the-simulation--prototype-itself) · [L Business & competition](#l-business-competition-ip) · [M Roadmap, team, ask](#m-roadmap-validation-team-ask) · [N Trap questions](#n-trap-questions--hostile-framings)

## The 5 rules for answering
1. **Answer first, then justify.** "Yes, because…" / "No, and here's why…".
2. **Separate proven / synthetic / planned** in every answer involving a number. It is our credibility signature.
3. **Name the mechanism, not the buzzword.** Say "quantile heads + three seeds + conformal offsets", not "AI uncertainty".
4. **Admit limits early and pivot to the plan.** "We don't know yet; Gate 1 measures it; here's the protocol."
5. **Hand off.** Whoever owns the topic answers; others stay silent. Suggested owners: **battery/ML → one person, firmware/hardware/safety → one, product/business/demo → one.**

---

## A. Problem, market, "why this"

**A1. Why focus on lead-acid when the world is moving to Li-ion?**
Lead-acid is still ~53 % of the Indian inverter-battery market and dominates the installed base: tens of millions of tubular batteries in homes now. The retrofit SKU serves them. The same core works for Li-ion too; only the features change (coulombic efficiency is useless there, dQ/dV and SEI-growth signatures matter).
*If pushed:* Li-ion packs already carry a BMS with some monitoring; lead-acid has none, so the value gap is biggest there. `research-market.md §1`

**A2. Is 85 % of households facing daily outages credible?**
It's a LocalCircles 2023 survey (25 k+ responses). Official feeder averages are ~22–23 h/day, but rural evening supply between 5 and 11 pm averages only ~4.7 h (PRAYAS). Outages cluster exactly when families need power.

**A3. What is the actual pain for V-Guard?**
Surprise battery deaths create unhappy customers and warranty disputes ("was the water topped up?"). Warranty was ≈1.52 % of revenue in FY24 (₹69.39 cr). The failure causes brands cite to void warranty (deep discharge, dry-out, heat, overcharge) are what we measure and sign.

**A4. Why not just tell users to check their battery water?**
Because they don't, and the water-topping reminder V-Guard already ships is time-based, not data-based. Sentinel measures the signatures (charge acceptance, coulombic efficiency, heat stress) and can flag real dry-out risk. It is the data-backed version of V-Guard's "Battery Gravity Builder" promise.

**A5. Who buys the retrofit?**
Existing inverter owners through V-Guard's ~100,000 retail touchpoints and electricians: families with elderly or medical needs, work-from-home users, anyone tired of the battery dying mid-outage. The embedded SKU is a premium tier in new inverters.

---

## B. Battery science

**B1. How do you measure SoC on a lead-acid battery?**
A 3-state Extended Kalman Filter (SoC, polarisation voltage, internal resistance) on a 1-RC Thevenin model, at 1 Hz. It predicts with coulomb counting and corrects with the voltage model. We re-anchor to 100 % on charge-current taper, and to the OCV table only after a true rest with the charger off. ≈3 % RMS vs 7.2 %/week drift for a naive counter, in simulation.
*If pushed (why 1-RC):* lead-acid's slow effects (diffusion, gassing, stratification) are non-linear; two time constants from one noisy shunt + voltage pair is poorly conditioned. R1/C1 come from lab tables (HPPC), R0 is tracked online. `design/01 §1`

**B2. Why not just use voltage like every inverter does?**
Voltage under load includes the I·R drop and polarisation, and the lead-acid OCV curve is flat between 30 and 70 % SoC: a few mV means many % SoC. Voltage alone also can't tell a weak battery from a heavily loaded healthy one.

**B3. What was the "float is not OCV" bug?**
Our own round-2 report said to anchor SoC to OCV during float. In float the charger drives current, so terminal voltage = OCV + I·R0 + polarisation, and the result over-reports SoC. We replaced it with a taper-based full-charge anchor, plus rest-OCV only with the charger verifiably off (D3). Then the code showed the per-tick voltage update re-created the bug during charging, so we gated it (D17).

**B4. How do you know the battery is full without a cycler?**
When the charger is in constant-voltage mode and the current tapers below ~2 % of C for 30 minutes, that is full. It's the same criterion Victron's shunt monitors use.

**B5. How do you measure internal resistance without special hardware?**
From natural load steps: R = −ΔV/ΔI when a load switches (|ΔI| ≥ 5 % of C, in discharge, ≥ 60 s after outage onset to skip the surface-charge artefact). The EKF also tracks R0 as a slowly varying state. Resistance growth precedes the capacity knee, which makes it the most transferable aging feature.

**B6. What kills tubular batteries in India?**
Sulphation (partial-state-of-charge living, deep discharge), grid corrosion and water loss (heat, overcharge), acid stratification. Heat roughly halves life per +10 °C. Our features map to each: time since last full charge, the DoD histogram, the Arrhenius heat integral, coulombic efficiency, charge acceptance.

**B7. What is SoH and what is end of life?**
SoH = present capacity ÷ rated capacity. End of life = 80 % (industry convention). The "Replace" grade triggers when SoH P50 < 82 % or remaining life P10 < 8 weeks.

**B8. What's Peukert and do you use it?**
Usable capacity drops at high current (flooded n ≈ 1.2–1.4). It's used in the available-energy estimate for the autopilot, and when converting a deep outage into a capacity sample. `design/05 §4.1`

**B9. Temperature: where exactly is the NTC?**
On the battery's negative post (or the case near the middle cell); the post tracks the electrolyte within ~2 °C. The inverter's own NTC is on its heatsink, which is useless for battery aging.

**B10. What about a 24 V (two-battery) system?**
The buck converter takes 4.5–24 V, and the EKF/features scale per cell. Our prototype and simulation are 12 V single-battery, which is every V-Guard retrofit target in the 900–1300 VA class (80–230 Ah).

---

## C. Battery-health ML (SoH / RUL)

**C1. What exactly does the model predict?**
SoH (P10, P50, P90) and remaining useful life in equivalent full cycles (P10/P50/P90). The cycles are converted to weeks using this home's own outage rate (EWMA), capped by calendar aging. The UI shows a window: "replace within 6–14 weeks, plan for 6".

**C2. Why a 1-D CNN and not an LSTM/GRU?**
Deployment reality on the ESP32-S3. TFLite Micro has no native GRU kernel, ESP-NN doesn't accelerate recurrent ops, and int8 recurrent state accumulates error. A CNN over the last 30 cycles uses exactly the ops ESP-NN accelerates (Conv 5.5–14×), learns shift-invariant knee/trend detectors, and the 6 static features carry the lifetime history.

**C3. Why not a simple MLP?**
30 × 14 = 420 flattened inputs with position-specific weights can't generalise "knee at cycle 20" vs "knee at cycle 25", and one layer to 64 units is already 27 k parameters.

**C4. How big is it, and how fast?**
≈28 k parameters (27,990 trained), ≈106 k MACs, int8 ≈ 36.7 KB per `.tflite`, three seeds. Estimated 1–10 ms per inference with ESP-NN, run once per outage cycle. The ML RAM is ~32 KB of 512 KB (16 KB arena + interpreter; seeds + anomaly model).
*If pushed:* the latency is an estimate scaled from Espressif's benchmark (8 MMAC at 54 ms with ESP-NN); it's **not measured on silicon yet**, and that's on the "needs hardware" list.

**C5. How do you get a trustworthy uncertainty band on a microcontroller?**
Three layers: (1) **quantile heads** trained with pinball loss (outputs q50 plus two non-negative deltas, so the quantiles never cross); (2) a **3-seed ensemble**, where disagreement > 5 points is flagged as out-of-distribution; (3) **split-conformal offsets** computed on held-out calibration batteries and stored in the model header, which gives finite-sample coverage. MC-dropout was rejected: not in TFLM, 30–100 passes, poorly calibrated.

**C6. Your SoH error is 8.2 points. Isn't that useless?**
On synthetic data with 16 batteries, it's honest and not flattering. The coverage is right (0.99 after conformal), but the band is too wide (~34 points). The architecture, quantisation, calibration and on-device path are proven; accuracy needs real tubular data, which doesn't exist publicly. The target after the campaign is ≤ 3 points MAE (≤ 4–5 in the first field season), and if we don't reach it, the prediction doesn't ship; the autopilot and log still do.

**C7. How did you avoid data leakage?**
GroupKFold **by battery ID** (never splitting cycles of one battery across train/test, since they're autocorrelated), an independent final test set never used for selection or calibration, timestamps instead of "one cycle per day", censored batteries excluded from lead-time stats, and a `test_leakage.py` in the suite. An external reviewer flagged the earlier evaluator; we fixed all six points (design/13).

**C8. Where does training data come from?**
Stage A: public Li-ion (NASA PCoE, CALCE) for shape priors only. Stage B: our synthetic Indian duty simulator (Poisson outages, lognormal durations, 150–900 W loads, 85 % inverter efficiency, Peukert, Schiffer aging, sulphation, Chennai/Delhi temperatures). Stage C: V-Guard's own aging campaign. Freeze the conv layers first, then fine-tune gently (L2-SP), 3 seeds, conformal on 6 held-out batteries.
*If pushed:* the synthetic→synthetic ablation showed pre-training helps SoH (MAE 16.4 → 10.5) but hurt RUL on n = 2. That's the kind of thing we measure rather than assume.

**C9. Does Li-ion data really transfer to lead-acid?**
Only *shapes* transfer: monotone drift, knee onset, resistance rising before capacity falls. That's why every feature is a ratio to the battery's own baseline. Absolute values and chemistry-specific channels (coulombic efficiency, dQ/dV peaks) don't transfer; they're learned in Stage C.

**C10. How do you know a real battery's SoH in the field for validation?**
Rare "direct capacity samples": an outage that runs from full charge to cut-off at roughly constant rate gives a real capacity measurement (Peukert and temperature corrected). It's used to update the conformal offset on the device, and in fleet analytics. The field pilot uses reference shunts on some units.

**C11. What if the battery suddenly shorts a cell? The model predicts gradual wear.**
A separate anomaly autoencoder (3 KB, 56→6→56) and hard rules run first. Reconstruction error above the 99th percentile on 2 of 3 cycles → "Service now", which overrides the grade, and the faulty cycle is masked from the SoH window.

**C12. Why grades with hysteresis instead of a live number?**
Users act on categories, and a grade flip-flopping would destroy trust. A grade changes only after 3 inferences on distinct cycles over ≥ 5 days, and upgrading is harder than downgrading.

**C13. How do you handle a brand-new battery with no history?**
"Collecting data" until ≥ 10 cycles; the first 10 cycles form the battery's own baseline for all the ratio features.

---

## D. TinyML on the ESP32

**D1. Does the model train on the device?**
No, never. Training is offline. The device does inference with fixed int8 weights. Personalisation comes from ratio-to-own-baseline features and on-device conformal offset updates, not gradients.

**D2. Walk me through deployment.**
Offline: train → full-integer post-training quantisation (representative dataset) → `.tflite` × 3 seeds → header (mean/scale, conformal offsets, schema version, grade thresholds) → signed `model.bin` → flashed into model slot A (or by OTA into B). At boot: CRC + signature + schema check → a MicroInterpreter per seed with a minimal op resolver (CONV_2D, FULLY_CONNECTED, RELU, …) → `AllocateTensors()` in a 16 KB arena → **golden self-test** on a built-in window; failure → fall back to the other slot. At each cycle end: standardise → clip ±3σ → quantise → `Invoke()` → dequantise → average the seeds → conformal band → grade → signed log.

**D3. What does the ESP32-S3 give that a cheaper MCU wouldn't?**
Vector (SIMD) instructions that ESP-NN uses for int8 conv/FC; 512 KB SRAM + 8 MB PSRAM; 16 MB flash for A/B firmware + A/B models + a 1 MB data log; Wi-Fi/BLE; dual core, so the radios are isolated from control. It's the cheapest chip with all that. **Not an NPU**: we corrected our own earlier wording (D16).

**D4. What did int8 quantisation cost?**
+0.013 SoH points of MAE, zero change in coverage (`quantization_report.json`). Target was ≤ 0.3 points.

**D5. Is the golden self-test real?**
Yes. `sentinel_int8_golden.h` holds a built-in input window with its expected output; the C inference must reproduce it bit-exactly. The firmware host build passes it.

**D6. What else runs on the device besides the CNN?**
EKF (physics), 168-bin EWMA habit tables, rules + k-NN appliance matcher, half-cycle RMS PQ classifier, the shed ladder, the health-log signer. Deliberately not neural where physics or auditability matters. `prototype/04 §5`

---

## E. Autopilot & load control

**E1. What does "habit learning" actually learn?**
A 7 × 24 hour-of-week table of average load and outage probability, EWMA-updated (α = 0.08, about a 3-week memory), with 4 seasonal copies, ≈4.7 KB. Outage probability is Beta-smoothed, (k+1)/(n+2), so one early outage can't lock in certainty.

**E2. Why not a neural forecaster? Isn't that less "AI"?**
Single-household load is extremely noisy; studies show simple statistical baselines stay competitive at household level. The predictable part is the *schedule* (DISCOM rosters repeat by hour and weekday), which a histogram captures exactly. And a table is auditable for a safety-adjacent decision. A tiny residual GRU is a v2 option, only if field data shows structure the table misses.

**E3. Can you predict outages?**
Only scheduled ones: "we forecast the roster, not the storm." Faults, storms and transformer trips are unpredictable from one home's history. Every forecast is phrased with its confidence, and it must beat a climatological baseline (Brier score) in the pilot or it ships advisory-only.

**E4. How is an outage detected on a retrofit that can't read the inverter?**
2-of-3 vote: s1 = our own mains-RMS sense < 0.1 pu for 1–2 s; s2 = mode pin (Embedded only); s3 = battery current turned to discharge. Outage = s1 AND (s2 OR s3), or s1 alone for ≥ 5 s. One broken sensor can't fake or miss it. Restore needs > 0.9 pu for 10–30 s, because grids flicker on return.

**E5. Why 55 % and 40 %?**
40 % follows the lead-acid guidance of not routinely going below ~40–50 % (sulphation); 55 % sheds comfort loads before heavy loads become urgent. 15-point hysteresis (restore at 70/55) prevents chatter. These are defaults an installer can tune per home, and the Gate-2 pilot validates them.

**E6. What's the "hard floor"?**
Every 60 s: available energy = SoH × usable SoC × capacity (Peukert, temperature). If it's below 1.2 × the forecast energy the essentials need for the rest of the expected outage, T3 is shed even above 40 %. In the sim, Home 5 (weak battery) triggers it at 20:07.

**E7. What about compressors (fridge/AC) and rapid switching?**
Min OFF dwell 3–5 min (anti short-cycle, per Copeland's ≥ 3 min), min ON dwell 5 min for compressor circuits, 60 s re-evaluation. The fridge is on T1 anyway (never shed). Stated trade-off: after a crash the fail-safe re-energises immediately, so the compressor delay can't be enforced then.

**E8. Can the user override?**
Yes: "keep this tier on" for 30 min (max 4 h), logged, visible countdown, auto-expiry. It can't beat the hard floor that protects the essentials.

**E9. Can you shed individual appliances inside a circuit?**
No, and we say so. One contactor = one circuit. Granularity = the number of channels wired (up to 4, optional 5th). Inside T1 we give staged alerts (50/35/20 %) and advice. Smart plugs are roadmap. `design/05 §5`

**E10. What happens when mains returns?**
Restore after 15 s stable; the inverter goes S6 → S1 and bulk charging. T2/T3 come back when SoC ≥ 70/55 % or the charger reaches absorption, so a depleted battery isn't asked to recharge while also running heavy loads. (This matches our Python controller.)

**E11. Who decides which circuit is T1/T2/T3?**
The installer at commissioning (app/BLE, ~10 min), with the family. Until configured, everything is T1: an unconfigured unit never sheds anything. The medical channel is locked by a hardware jumper.

---

## F. Safety & electrical design

**F1. What happens if Sentinel crashes during an outage while loads are shed?**
Every load comes back. The contactors are normally-closed: the circuit is closed when the coil is unpowered. Reset → GPIO pull-downs drop every coil instantly. Hang → no heartbeat for 2 s → an independent supervisory timer cuts the coil rail. The whole board dead → contacts are physically closed. **"Coil off means load on."** You can demonstrate it live.

**F2. Why NC contactors and not relays or latching relays?**
Latching relays hold their last state after a crash, so a shed circuit stays dark: rejected. NO relays would need power to keep loads on, so every failure would black out the house. NC is the only fail-safe choice for "loads default to energised". (Tesla's Backup Gateway uses the opposite convention; we chose NC deliberately, and installers must be told it's easy to wire backwards, so commissioning includes a power-off test.)

**F3. Isn't there risk in putting 25 A contactors in a home DB?**
They're standard DIN-rail modular contactors installed by an electrician, in series with the existing MCB-protected sub-circuits. The MCBs still provide overcurrent protection. Coils are 12 V DC, SELV side.

**F4. How is the mains-side sensing isolated?**
The AMC1311 is a reinforced isolated amplifier; the PC817 is an opto; both straddle a physical isolation moat on the PCB. The CT is inherently isolated. TVS diodes are on every external line and ferrites on cable entries. The target creepage across the moat is ~8.5 mm, to be confirmed in standards review.

**F5. Can your shunt affect the inverter?**
It adds < 0.2 mΩ in the negative lead: at 60 A that's < 12 mV, negligible against the inverter's low-battery sensing. The sense lead has a 2 A fuse at the battery end.

**F6. What about the battery's hydrogen / ventilation?**
The box sits beside the inverter, not on the battery. The only thing on the battery is the NTC probe; the enclosure is UL94 V-0 and there are no sparking contacts near the vents (the contactors are in the DB).

**F7. What standards apply?**
IS 13252 / IEC 62368-1 (the BIS gate), IEC 62040 (UPS), the IEC 61000 series (EMC; -4-11 for dip testing, -4-30 for PQ measurement methods), IEEE 1159 (event classes), UL94 V-0. Not certified yet; that comes after the PCB.

**F8. What if a sensor gives garbage?**
The engine falls back (EKF → coulomb-count only, NILM off), logs it, lights an LED, sends an app alert, and **never sheds on unreliable data**.

---

## G. Energy Coach (NILM) & Grid Shield

**G1. Why do you need a separate metering chip?**
With mains present, appliances run from mains through the relay; battery current tells you nothing about them. The ESP32's ADC isn't metering grade (INL ±8 LSB, no simultaneous V/I). The ATM90E32AS gives true P, Q, PF and harmonics at 3 Hz, like a smart meter (D1, D4).

**G2. How do you tell a fridge from a heater at the same wattage?**
Reactive power and dynamics: a fridge compressor has lagging PF (ΔQ ≈ 0.7–1× ΔP), a 5–6× inrush and ~1.4 s settling; a heater is purely resistive (ΔQ ≈ 0). Plus duration, periodicity (fridge cycles every 15–30 min) and time of day: a 13-number signature → rules → k-NN over a per-home library.

**G3. What accuracy?**
On synthetic streams: event recall 1.00, precision 0.74, fridge F1 0.97, iron 1.00, 87 % of energy assigned. Real-world benchmarks give 0.65–0.89 F1 for big loads at ≤ 1 Hz. The Gate-2 target is fridge/AC F1 ≥ 0.8 on labelled homes. Low-confidence events stay "unknown".

**G4. Why is Energy Coach useful for an inverter?**
Two reasons. Time-of-use tariffs are arriving with smart meters (5.28 crore installed under RDSS), and knowing which appliances drain the battery lets the autopilot forecast essential demand better.

**G5. What exactly does Grid Shield do?**
Half-cycle RMS every 10 ms on the isolated voltage tap; classifies per IEEE 1159 (sag 0.1–0.9 pu, swell > 1.1 pu, interruption < 0.1 pu, by duration); writes each event into the signed log with a timestamp. The value is evidence for appliance-damage or utility disputes. Monthly roll-up of counts.

**G6. Your chart says 0.54 when you injected 0.55. Is that an error?**
Yes, 0.007 pu, 0.7 % of nominal; the swell 1.165 vs 1.15 is 1.5 %. Our validation target is ≤ 2 % of nominal (design/11); on the dip test set the worst was 0.86 %. Half-cycle RMS windows straddling the event edges cause it.

**G7. Can it protect appliances?**
It detects and records; it doesn't "predict" sags (there's no local precursor). The inverter itself already rides through in UPS mode (180–260 V window). Future: trigger protective shedding on sustained swells.

---

## H. Hardware, BOM, power

**H1. What does the board cost?**
By tier (D7): basic ≈ ₹750 (ESP32-S3 module, INA228, NTC, AMC1311, ULN2003, supervisor, DS3231, ATECC608, buck, connectors); ≈ ₹1,050 standalone with the shunt; + Coach kit (AFE + CT + tap + isolator) ₹600–1,000 → ₹1,650–2,050. The embedded increment is ₹450–700, or ₹850–1,300 with the Coach, because it reuses the inverter's rail, shunt and enclosure. Contactors are extra.
*If pushed:* indicative Indian distributor prices (electronicscomp, probots, IndiaMART), not volume quotes.

**H2. How much power does Sentinel draw from the battery?**
≈2.6 mA average battery-side for the basic board: a proposal to be measured, not a measurement. That's ≈0.04 %/day of a 150 Ah battery, under a twentieth of its self-discharge. The NILM mode adds ~13 mA (the AFE is duty-cycled). In an outage: Wi-Fi off, BLE advertising every 5 s, NILM off. While shedding, each held coil adds 60–100 mA; that's still a net win because the shed load drew far more.

**H3. Why an external RTC and a secure element? More cost.**
The RTC: the ESP32's clock drifts unpowered, and habit tables and log timestamps need real time. The ATECC608: warranty evidence needs a private key that can't be extracted; the eFuse keys on the S3 are a cheaper but weaker fallback.

**H4. What's on the bench today vs the final PCB?**
Tier 0: ESP32-S3 devkit, INA226 + a 500 A / 75 mV shunt, PZEM-004T (instead of the ATM90E32AS), a 4-ch relay module or DIN contactors, ULN2003 + a 555 supervisor, DS3231. Tier 1: a custom 80 × 60 mm PCB with the INA228, ATM90E32AS and ATECC608. Some parts aren't sold in India as breakouts (INA228, ATM90E32 boards), hence the substitutions.

**H5. Why 90 × 70 × 35 mm?**
80 × 60 mm PCB + 2.5 mm walls + connector/relay clearance. It's about the size of a Victron SmartShunt head (69 × 69 × 31) and mounts on a DIN rail or with screws beside the inverter.

---

## I. Adaptive charging (Embedded)

**I1. Why can't the retrofit control charging?**
Indian home inverters use analog SG3525/TL494 charge loops with setpoints fixed by resistor dividers and a trim pot. There's no bus. Only solar-hybrid PCUs have RS-485, with proprietary registers. So the retrofit advises (the correct float voltage for the temperature, the right battery-type selector) and protects from the load side (D2).

**I2. How does the embedded version control an analog charger?**
An MCP4725 DAC injects a small, bounded offset into the SG3525 feedback node, shifting the regulated voltage. A hardware clamp limits it, and a 2-second heartbeat returns the charger to factory defaults if Sentinel dies. It needs V-Guard's charger schematic, which is part of our ask.

**I3. What does it change?**
Temperature compensation of −24 mV/°C per 12 V from 25 °C (Victron's default of −4 mV/°C/cell). For example, at 31 °C absorption drops 14.40 → 14.26 V and float 13.50 → 13.36 V. Current derating above 45 °C, hard stop about 58 °C. Equalisation only when due (≥ 30 days), when sulphation signs appear, below 40 °C and when no outage is predicted, with a water-loss guard.

**I4. You claim 15–30 % longer battery life?**
That was a round-2 target. Our current position: it's a hypothesis, **Embedded only**, to be **measured** in the campaign (compensated vs fixed charging at 40 °C, same DoD). We don't claim it as a result.

**I5. Your simulation uses 14.40/13.50 V but your charger code uses different numbers?**
The simulation uses typical Indian factory values (prototype/01: absorption 14.4, float 13.5–13.6). The charger policy code uses per-cell setpoints within the design/03 ranges (float 13.4–13.8), giving 13.62/14.61 V at 25 °C. The compensation slope is identical (−24 mV/°C). The final values come from Gate-1 characterisation of V-Guard's batteries.

---

## J. Security, health log, OTA, privacy

**J1. How is the health log tamper-proof?**
Each record = {monotonic counter, timestamp, event, hash of the previous record}, SHA-256 chained and signed ECDSA-P256 by a key generated inside the ATECC608 that never leaves it. With just the public key, a verifier detects tampering (the hash breaks), deletion (a counter gap), replay (the counter must increase) and truncation (signed checkpoints uploaded with telemetry). The demo's "Alter one byte" shows the chain breaking.

**J2. Can't someone fake the sensor data going in?**
Yes. A secure element can't stop a physically substituted sensor; that's a stated limitation. Mass cloning or forging needs lab-grade attacks, not casual tampering, and it's cheaper than the dispute it would win.

**J3. How does warranty use it?**
A one-tap claim uploads the chain; V-Guard verifies it and applies policy (e.g. deep discharges below 20 % fewer than N, temperature stress within band). Disputes are resolved by evidence rather than argument.

**J4. OTA risks?**
Firmware and models update on separate A/B channels. Firmware: Secure Boot V2 signature, post-boot self-test, automatic rollback, anti-rollback eFuse. Models: CRC + signature + schema match + golden self-test, and rollback if the first field inferences disagree by > 10 SoH points. Rollout rings 1 % → 10 % → 50 % → 100 %. Never during an outage.

**J5. What data leaves the home?**
Raw 1 Hz data never does. With consent (DPDPA), a ≈48-byte per-cycle summary and a ≈70-byte daily aggregate, pseudonymised (HMAC ID), with 5-minute time buckets. No GPS, no SSIDs, no appliance events (only per-appliance kWh, opt-in). We note the quasi-identifier risk (usage patterns) and need a red-team and legal review before production.

**J6. Why was federated learning dropped?**
The SoH model has no labels on the device, so federating it doesn't make sense (D6). The appliance classifier does (users name appliances), and it's privacy-sensitive, so it's the right federated target. The design (Flower, SecAgg, DP-FTRL, ε ≈ 4) is complete, but we deliberately cut it from the prototype (D15) to focus on what we could prove.

---

## K. The simulation & prototype itself

**K1. Is the simulation just an animation?**
No. It runs a time-stepped model: inverter states S1–S6 with an 8 ms transfer, battery charge/discharge with internal resistance, charger stages, and the Sentinel firmware behaviour (2-of-3 vote with debounce, 60 s ladder with hysteresis and dwell, the endurance hard floor, fail-safe paths, NILM events, the PQ log, a SHA-256 chain). The thresholds are from our design docs (`src/sim/params.js`). The 3D view just visualises that state.

**K2. So the Home 1 vs Home 6 chart is from the simulation, not real batteries?**
Correct, and the slide says so. It demonstrates the *logic* on a physically reasonable battery model (150 Ah, SoH 93 %, 85 % inverter efficiency, realistic evening loads). Real batteries come at Gate 1/2.

**K3. What's the relationship between the simulation and the Python/C code?**
The Python/C codebase (`prototype/code`, 245 tests) contains the real algorithms: the EKF, the trained int8 CNN, the autopilot controller, the NILM detector, the PQ classifier, the health-log signer, the charger policy, and the firmware host build. The simulation re-implements the *decision logic and thresholds* in JavaScript for an interactive demo. The battery-health grades in the sim come from the dashboard's fixture, labelled "synthetic aging".

**K4. What's actually running as the "prototype"?**
(1) The codebase with tests and a firmware host build that links the real C modules, passes the int8 golden self-test, runs a 1 Hz battery CSV end to end and writes a state file the Flask dashboard serves. (2) The Sentinel-Live simulation for the demo. (3) A fully specified and priced Tier-0 bench. It is not yet flashed on an ESP32. We say that on slide 13.

**K5. Why didn't you build the hardware?**
Honest answer: time, and some parts (INA228, ATM90E32 boards) aren't stocked in India. We prioritised making the software exact and tested, so the bench becomes a wiring exercise. The bench is Tier 0: days of work, ₹25–35 k including the battery and inverter.

**K6. Why 8 ms and 1.5 s?**
8 ms is inside V-Guard Prime's < 10 ms UPS-mode transfer spec. 1.5 s is our s1 debounce inside the design's 1–2 s window, sustained to reject flicker.

---

## L. Business, competition, IP

**L1. Why hasn't Luminous/Microtek/Exide done this?**
What they ship is telemetry, not intelligence: Luminous Zelio Wi-Fi (status monitoring, no ML), Microtek Luxe Wi-Fi (remote control, reminders), Su-Kam and Havells (no app), Exide lead-acid (zero telemetry). The barriers: analog charge loops with no data path, no public tubular aging data, cloud-first apps that go blind when the router dies in an outage, safety-critical load switching, and a tight BOM. AI battery prediction exists in academia and solar-farm asset management, not mass-market home backup.

**L2. Why is V-Guard uniquely placed?**
It makes both the inverter and the battery (so the model can be co-designed with the chemistry), has its own Kochi reliability lab for the aging campaign, can open its own charger schematics for the Embedded SKU, has ~100,000 retail touchpoints for the retrofit, already has Smart Pro with Wi-Fi/BLE and the Smart 2.0 app, and will accumulate fleet data that compounds. A third-party add-on company can do none of that.

**L3. Can a competitor copy it?**
The hardware, yes eventually. The moat is the tubular aging dataset, the fleet data and the chemistry co-design, plus time-to-market inside an existing install base.

**L4. What's the revenue model?**
(1) Premium "intelligent" inverter tier (Embedded). (2) Retrofit sales through electricians. (3) Timely battery replacement: the "replace within N weeks" window converts a surprise into a planned V-Guard sale. (4) Lower warranty cost through evidence. Optional later: a subscription for fleet insights.

**L5. Doesn't predicting end of life reduce battery sales?**
It moves them in time and to V-Guard: the customer replaces at the right time, from the brand that warned them, instead of a panic purchase from whoever is nearby. Extending life (Embedded charging) is a customer-trust feature.

**L6. Sustainability angle?**
60–80 % of India's used lead-acid recycling is informal; better-timed replacements and longer life reduce churn, and the signed log supports take-back programmes. Keep it brief unless asked.

**L7. Is there IP?**
Candidate novel combinations: the offline battery-health window (conformal + ensemble on MCU) for tubular inverter batteries; the retrofit 2-of-3 outage detection with tiered NC shedding and a hardware supervisor; the signed health log as a warranty instrument; DAC injection into analog charger feedback with a hardware clamp and heartbeat revert. A patent search would be needed; don't claim patents.

---

## M. Roadmap, validation, team, ask

**M1. What's the next concrete step?**
Tier 0 bench (days): flash the ESP32-S3, wire the INA226 + shunt, the PZEM and the relays, run the real outage/shed/fail-safe on a real battery and inverter. Then Tier 1 PCB (4–6 weeks), and the aging campaign in parallel.

**M2. How long until you know the ML works?**
Gate 1: 6–8 months (24–36 batteries; at 50 °C / 80 % DoD, end of life arrives in ~2–4 months, giving early labels). Gate 2 field pilot: 6 months, 100 homes.

**M3. What do you need from V-Guard?**
One opened Prime-series inverter with its charger-board schematic, the ESP32 bench parts, and access to batteries and cyclers in the Kochi reliability lab for Gate 1.

**M4. What are the pass/fail criteria?**
SoC RMS ≤ 3 %; SoH MAE ≤ 3 points after the campaign; RUL-window hit rate ≥ 75 %; median warning lead ≥ 8 weeks; false alarm/miss ≤ 10 %; zero unsafe sheds in 50 hardware-in-loop scenarios; outage detection ≤ 2 s with zero false declarations on IEC 61000-4-11 dips; fridge/AC F1 ≥ 0.8; quantised vs float ΔMAE ≤ 0.3 points; on-device latency ≤ 50 ms. `design/11`

**M5. What if Gate 1 fails?**
The battery-health prediction doesn't ship, or ships as "collecting data" with only a resistance-based health proxy. The autopilot, fail-safe shedding, Grid Shield and signed log still deliver value, and they don't depend on the ML.

---

## N. Trap questions & hostile framings

**N1. "Isn't this just a BMS?"**
A BMS protects a battery from inside the pack, typically for Li-ion. Tubular lead-acid has none. Sentinel is a system-level brain for the inverter–battery–house: it estimates health, decides which house circuits to keep, detects grid events and signs evidence. It's a BMS plus load management plus PQ logging plus warranty, in one ₹750–2,000 board.

**N2. "Where is the AI? This looks like thresholds."**
The shedding is deliberately deterministic, because safety logic must be auditable. The intelligence is in the Kalman estimation it acts on, the learned hour-of-week tables, the int8 CNN battery-health model with calibrated uncertainty, and the appliance recognition. We use neural nets only where they beat physics.

**N3. "Your accuracy numbers are all synthetic. Why should we believe anything?"**
You shouldn't believe the accuracy yet, and we don't claim it. What you can believe is the pipeline: it's tested (245 tests), quantised, self-tested in C, and calibrated. We've specified exactly how to get real accuracy (Gate 1) and what number would kill the feature.

**N4. "Why not just do it in the cloud? Cheaper."**
In an Indian outage the router is usually dead too. The decisions that matter (shedding, outage detection) happen exactly then. Battery health must work in homes that never connect. The cloud is additive: OTA, fleet learning, analytics.

**N5. "A relay failing closed means you can't shed. A contactor welding open blacks out a circuit."**
Correct. The NC design chooses the safe failure: a welded contact means "can't shed", which is annoying but not dangerous. An NC contact that fails open is a hardware fault. The commissioning "power-off = loads on" test catches wiring errors, a shed/restore that produces no step in AC-OUT power can be flagged as a suspect channel, and every contactor has an electrician-accessible manual bypass (design/05 §6). Per-channel current sensing would make detection certain, and it's a Tier-1 option we'd consider.

**N6. "Why would a family let a box switch off their fan?"**
They choose the tiers at install. They can override for 30 minutes. The alternative, as Home 6 shows, is losing everything including the fridge at 10 pm. Given that choice people pick the fridge.

**N7. "What if the user's DB isn't split into inverter/non-inverter groups?"**
Every inverter install already splits it; that's how inverters are wired (prototype/01). The contactors go on the inverter-group sub-circuits. If there's only one inverter circuit, Sentinel still does battery health, the log and Grid Shield, with alerts instead of shedding.

**N8. "You changed a lot since round 2. Were you wrong then?"**
We built it, and building exposed errors: float ≠ OCV, a battery shunt can't see appliances, a retrofit can't command a charger, and others. We fixed 17 things and documented each (design/12). We'd rather show you the corrections than defend the mistakes.

**N9. "How is this different from what V-Guard's Smart Pro app shows today?"**
Smart Pro shows present state: charge %, load, mode. Sentinel adds the future (remaining life with a window), decisions (autonomous shedding), evidence (a signed log, grid events), and works with no internet. Embedded is designed to slot into Smart Pro.

**N10. "What if Sentinel's SoC is wrong and it sheds too early/late?"**
Too early costs comfort (fans off sooner), not safety. Too late can't hurt the essentials: T1 is never shed, and the inverter's own cut-off protects the battery. The EKF re-anchors on taper and rest-OCV, and a forecast-disagreement monitor drops to pure SoC thresholds if actual drain is > 1.3× the forecast for 5 minutes.

**N11. "Your team is students. Can you really ship this?"**
We're not asking to ship; we're asking for Gate 1. We've shown that we can specify to the part, write tested code, correct ourselves, and state limits. V-Guard's R&D owns the production path; our value is the design, the code and the validation plan.

**N12. "What's the single biggest risk?"**
That real tubular aging doesn't give features the model can learn well enough, i.e. SoH error stays > 3 points. That's why it's Gate 1, why the band is conformal (it widens honestly rather than lying), and why every other feature stands without it.

---

## Rapid-fire numbers (for 1-line answers)
| Ask | Answer |
|---|---|
| transfer time | < 10 ms (Prime UPS mode); 8 ms in the sim |
| outage confirm | ≈1.5 s (1–2 s debounce, 2-of-3) |
| restore confirm | > 0.9 pu for 10–30 s (15 s in the sim) |
| supervisory cut | 2 s without heartbeat |
| shed thresholds | T2 55 % / T3 40 % / cut-off 20 %; restore 70 / 55 % |
| dwell / re-eval | 3–5 min OFF, 5 min ON (compressors) / 60 s |
| model | 28 k params · 106 k MACs · int8 36.7 KB × 3 · 16 KB arena |
| accuracy (synthetic) | SoH MAE 8.2, RMSE 9.6; coverage 0.99, width 34 pt |
| int8 loss | +0.013 pt |
| EKF | ≈3 % RMS vs 7.2 %/week naive |
| NILM | recall 1.00, fridge F1 0.97, iron 1.00, 87 % energy |
| PQ | 13/13 dips, ≤ 0.86 % magnitude error |
| tests | 245 (autopilot 65, charger 48, health log 31, model 21, dashboard 19 …) |
| cost | ₹750 basic · ₹1,050 standalone · ₹1,650–2,050 full · embedded ₹450–1,300 |
| draw | ≈2.6 mA avg (proposal) · +13 mA with NILM · coils 60–100 mA each while shedding |
| size | 90 × 70 × 35 mm box · 80 × 60 PCB · UL94 V-0 |
| charging | −24 mV/°C · derate > 45 °C · stop ≈58 °C · bulk 10 % C |
| campaign | 24–36 batteries · 27/40/50 °C · DoD 30/50/80 · 6–8 months |
| pilot | 100 homes · 6 months |
| market | home UPS USD 348 M → 487 M (2030) · inverter battery USD 197 M → 346 M · lead-acid ~53 % |
| V-Guard | FY26 ₹5,966 cr · Electronics ₹1,640 cr · warranty 1.52 % FY24 |
