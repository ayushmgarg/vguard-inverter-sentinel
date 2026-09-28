# Sentinel — Gap Register (master index)

Line-by-line audit of the submitted Phase-3 report (TI3271, 28 Aug 2026). Each row is a mechanism the
report *names* but does not *specify* — i.e. something a judge can ask "how, exactly?" about.
Severity: **A** = judge will almost certainly probe / design risk · **B** = likely probed · **C** = polish.
Each hole is worked out in the design doc linked in the last column. Decisions on design changes are
consolidated in `documentation/design/12-Design-Changes-Decided.md`.

| ID | Report claim (section) | The hole — what is unspecified | Sev | Resolved in | Status |
|---|---|---|---|---|---|
| H1 | "Extended Kalman Filter … bounded state" (§6.1) | No state vector, battery (equivalent-circuit) model, measurement equations, tuning | A | 01 | ✅ closed |
| H2 | "coulomb counting … drifts" (§6.1) | Drift/bias model tied to sensor spec; when/how it is re-anchored | A | 01 | ✅ closed |
| H3 | "internal resistance from ΔV/ΔI of natural transients" (§6.1) | Transient detection criteria, filtering, T/SoC normalisation, R_int→SoH map | A | 01 | ✅ closed |
| H4 | Feature vector: sag, R_int trend, Ah, DoD hist, temp-stress, coulombic eff., ICA peaks (§6.1) | How each is computed on an MCU from 1 Hz I/V/T; ICA on a partial lead-acid charge | A | 02 | ✅ closed |
| H5 | "compact quantised model maps feature history to SoH and RUL" (§6.1, §6.3) | Architecture, input window, outputs, uncertainty method, training, transfer, quantisation, deployment, cadence, versioning | **A** | 02 | ✅ closed |
| H6 | "graded warning: replace within N weeks" (§6.4) | RUL definition, extrapolation-to-80% logic, warning thresholds, uncertainty → weeks | A | 02 | ✅ closed |
| H7 | "adaptive charge-and-thermal policy … extends life 15–30%" (§3, §15) | What the policy changes; **how a signal-only module commands the inverter's charger**; retrofit vs embedded | **A** | 03 | ✅ closed |
| H8 | "autoencoder for anomaly detection" (§5.1) | Input signals, architecture, threshold, what anomalies, training | B | 02 | ✅ closed |
| H9 | "representative matrix of tubular cells … aging campaign" (§6.2) | Cell count, T×DoD×rate matrix, duration, instrumentation, Gate-1 acceptance metric | A | 04 | ✅ closed |
| H10 | "transfer learning rather than direct parameter reuse" (§6.2) | What transfers Li→lead-acid, fine-tune recipe, data volumes | B | 02 | ✅ closed |
| H11 | "learned demand-and-outage forecaster" (§7) | What is learned, representation, algorithm, memory, forecast horizon | A | 05 | ✅ closed |
| H12 | "pre-charges the battery ahead of a predicted outage" (§7) | How an outage is predicted (only from local history), confidence, limits | A | 05 | ✅ closed |
| H13 | "external contactors … keep/defer/shed tiers" (§7) | Circuit-map: how installer assigns contactor→tier, medical lock, app config | A | 05 | ✅ closed |
| H14 | Shedding decision logic (§7, Exh. 8) | Energy budget, thresholds, hysteresis, re-evaluation cadence, user override, wrong-forecast handling | A | 05 | ✅ closed |
| H15 | "fail-safe: loads default to energised on fault, with watchdog" (§17) | Contactor NC/NO wiring, coil drive, interlocks, watchdog behaviour | A | 05, 10 | ✅ closed |
| H16 | "prioritising *inside* the single essential circuit" (§7) | Inconsistent: one circuit cannot be prioritised within without per-load control → clarify what is honestly possible | B | 05 | ✅ closed |
| H17 | "NILM disaggregates … from ≤1 Hz current signal" (§8) | **How the ESP32 distinguishes appliances** — signals, event detection, signatures, matching, per-home calibration, feasible appliance set, accuracy | **A** | 06 | ✅ closed |
| H18 | (implicit) | **Design inconsistency:** NILM needs AC *output* real power during grid-present operation; basic BOM senses only battery DC current → no signal for the Coach | **A** | 06, 10, 12 | ✅ closed |
| H19 | "one-cycle RMS sag detection … Class-S-like" (§8) | RMS window, IEEE 1159 thresholds, event record schema, storage, alerting | B | 07 | ✅ closed |
| H20 | "units log anonymous telemetry … upload opportunistically … central training" (§9) | Telemetry schema, rates, on-device storage/flash budget, upload protocol, pseudonymisation, consent, cloud pipeline | A | 08 | ✅ closed |
| H21 | "FedAvg or DP-FTRL … Secure Aggregation … ε=4, δ=1e-5" (§9) | **What is federated, client roles, round protocol, cohort size, clipping/noise → how ε=4/yr is achieved, non-IID/participation bias, versioning, fallback** | **A** | 08 | ✅ closed |
| H22 | "pushes models over the air" (§9) | OTA mechanism: signed images, A/B partitions, rollback, model-vs-firmware | A | 09 | ✅ closed |
| H23 | "signed, append-only, device-key-authenticated health log" (§3) | Key provisioning, signature scheme, log structure, verification by V-Guard, threat model | A | 09 | ✅ closed |
| H24 | "microamp quiescent … never meaningfully loads the battery" (§5.3) | Real module current budget (ESP32-S3 active/radio/sleep), mWh/day, impact on backup, radio policy | B | 10 | ✅ closed |
| H25 | "reads the inverter's existing shunt" (§5.2) | Physical/electrical interface to an existing shunt or metering; embedded vs retrofit | B | 10 | ✅ closed |
| H26 | (see H7) | Charger-control interface options on Indian inverters; feasibility per variant | **A** | 03, 10 | ✅ closed |
| H27 | AC voltage/current sensing for PQ/NILM (§5.2, §8) | Where taps go (inverter AC output), synchronous V/I sampling for P/Q | A | 06, 10 | ✅ closed |
| H28 | Sampling at "128–256 samples/cycle" (Exh. 14) | **ESP32-S3 internal ADC is not metering-grade** → need a metering AFE or external ADC; decide | A | 10, 12 | ✅ closed |
| H29 | EMC/ESD/surge on sense lines (§12) | Component-level protection, creepage, PCB partitioning | C | 10 | ✅ closed |
| H30 | "float-rest OCV anchoring" (§5.2, §6.1) | **Technical error:** float voltage ≠ OCV. Correct mechanism = full-detection by current taper (+ true rest OCV only when charger off) | **A** | 01, 12 | ✅ closed |
| H31 | "success criteria: RUL-window hit-rate, SoC error ±5 %, load-shed correctness, FL vs central, latency" (§11) | Precise metric definitions and test protocols | B | 11 | ✅ closed |
| H32 | Prototype (§11) | Concrete architecture/stack of what is built | C | 11 | ✅ closed |
| H33 | "none of it personally identifiable" (§9) | Usage patterns are quasi-identifiers; DP/aggregation on the central path; honest privacy statement | B | 08 | ✅ closed |
| H34 | Habit data stored on-device (§7) | Storage, retention, privacy | C | 05 | ✅ closed |
| H35 | Time-of-day learning (§7) | RTC drift, NTP sync, backup RTC | C | 10 | ✅ closed |
| H36 | "on outage detection" (§7) | The actual outage-detection signal (mains V sense / inverter mode / discharge onset) | B | 05, 10 | ✅ closed |
| H37 | "coulombic efficiency" feature (§6.1) | Requires charge/discharge pairs — how computed per outage cycle | C | 01 | ✅ closed |
| H38 | Validation "≥5 simulated homes in Flower" (§11) | Simulation design, non-IID partitioning, what it can/cannot validate | B | 08, 11 | ✅ closed |

## Status (2026-09-21)
All 38 holes are worked out in docs 01–11; the 14 resulting design decisions (D1–D14) are in 12. Read order for the finale: 12 → 00 → the engine doc a judge is probing.

## Design inconsistencies found (must be decided, not just documented)
1. **H18/H27** — the Energy Coach has no AC signal in the basic variant. **Decided (D1): ATM90E32AS AFE + CT on the inverter AC output.**
2. **H7/H26** — adaptive charging needs a charger-control interface the retrofit lacks. **Decided (D2): two SKUs; life-extension claim scoped to Embedded and measured in the campaign.**
3. **H30** — float ≠ OCV. **Decided (D3): full detection by current taper + rest-OCV only with charger off.**
4. **H28** — ESP32-S3 ADC is inadequate for PQ/NILM. **Decided (D4): metrology on the AFE; ESP32 ADC only for the AMC1311 fast sag/outage tap.**
5. **H16** — "prioritise within one circuit" is not literally possible. **Decided (D5): staged alerts + advisory + optional installer sub-circuit; smart plugs = roadmap.**
6. **H21** — what is federated was never specified and the implicit answer (SoH) has no on-device labels. **Decided (D6): federate the NILM classifier (+ anomaly AE); SoH stays central.**
7. **BOM** — report's ₹150–300 embedded increment omits the AFE, RTC, secure element. **Decided (D7): ₹450–700 embedded / ₹800–1,300 retrofit board.**

## Document map
| Doc | Covers |
|---|---|
| 01-Battery-State-Estimation.md | H1 H2 H3 H30 H37 |
| 02-TinyML-SoH-RUL-Pipeline.md | H4 H5 H6 H8 H10 |
| 03-Adaptive-Charging-and-Charger-Interface.md | H7 H26 |
| 04-Aging-Campaign-Design.md | H9 |
| 05-Habit-Autopilot-and-Load-Prioritisation.md | H11–H16 H34 H36 |
| 06-NILM-Appliance-Disaggregation.md | H17 H18 H27 |
| 07-Grid-Shield-Power-Quality.md | H19 |
| 08-Fleet-Learning-Central-and-Federated.md | H20 H21 H33 H38 |
| 09-Security-OTA-and-Health-Log.md | H22 H23 |
| 10-Hardware-Interfaces-and-Power.md | H24 H25 H27 H28 H29 H35 H36 |
| 11-Validation-Protocol.md | H31 H32 |
| 12-Design-Changes-Decided.md | all decisions |
