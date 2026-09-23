# V-Guard Intelligence — Detailed Report (Phase 3)
## Flagship: V-Guard Sentinel — an on-device AI core that makes power backup self-aware
*Big Idea Tech Design Contest 2026 · Track 4 · Team Codey Tingle · MPSTME, Mumbai*

> Draft body (~4,500 words target). Figure callouts [Fig X] map to `docs/figures/` and `docs/diagrams/`. Battery-science citations and BOM line-items to be reconciled against research streams A (battery) and B (hardware) on completion.

---

## 1. Introduction & Recap
The Big Idea Tech 2026 theme asks how V-Guard moves *from smart products to intelligent products*. Our Phase-2 submission proposed **V-Guard Intelligence**: a low-cost, on-device **AI Core** that lets each V-Guard product predict its own failures, learn its owner's habits, and act autonomously — with the whole installed base improving together through privacy-preserving **federated learning**, all working offline. The flagship is **V-Guard Sentinel**, an intelligence upgrade to the home inverter/UPS + battery.

This report elaborates the concept into an engineering-grade proposal: the problem physics, the system and hardware architecture, the machine-learning methods and their honest limits, the parameters to be defined, a prototype and validation plan, standards and safety, unit economics, and the rollout. Throughout we are deliberate about the line between what is *deployable today* and what is a *research target* — because the judges are R&D engineers, and credibility is the whole game.

## 2. The Problem — Revisited and Deepened
### 2.1 India still runs on unreliable power
Independent surveys put the lived reality far below official feeder averages: **85% of Indian households face outages daily and 37% experience 2–8 hours of outage a day** (LocalCircles, 2023), and **one in three households hits a blackout, low-voltage or appliance-damage event within any single month** (CEEW IRES). Government figures (rural ~22.6 h/day supply) mask the evening collapse — rural 5–11 PM supply averages only ~4.7 hours (PRAYAS). Household voltage swings **180–270 V** against a 230 V spec. The home inverter/UPS + battery is therefore not a convenience; it is critical infrastructure for tens of millions of homes.

### 2.2 The battery is the weak link — and it fails silently
The lead-acid battery (still ~53% of the Indian inverter-battery market) is the component that strands users. Crucially, **its failure is never truly sudden** — it is the end-point of measurable, months-long degradation:
- **Sulphation** — lead-sulphate crystals harden on the plates during under-charging/deep discharge, raising internal resistance and reducing charge acceptance.
- **Grid corrosion** and **positive-active-material shedding** — the plate lattice corrodes and sheds, permanently losing capacity.
- **Water loss / dry-out** — India's >40 °C summers accelerate electrolyte evaporation; neglected top-up exposes plates.
- **Acid stratification** — acid concentrates at the bottom in partial-cycling use, corroding lower plates.
For Li-ion the mechanisms differ (SEI-layer growth, lithium plating, capacity vs power fade) but the principle holds: **degradation is progressive and observable.**

Each mechanism leaves an electrical fingerprint: rising **internal resistance**, worsening **voltage sag under load**, falling **charge acceptance/coulombic efficiency**, and shifts in the **rest-OCV vs state-of-charge** curve [Fig: degradation-signatures]. Today's inverters — even "smart" Wi-Fi models — measure the present state at best; **none forecast the trajectory.** So the battery dies mid-blackout with no warning.

### 2.3 Four unmet needs
1. **No failure foresight** — batteries and internals (relays, capacitors, fan, MOSFETs) fail without warning.
2. **No load intelligence** — on outage, backup drains on non-essential loads; nothing decides what to protect.
3. **No energy insight** — households have no idea where power goes; smart-meter ToU tariffs are arriving with no device to exploit them.
4. **Reactive service** — warranty claims are disputes ("was the water topped up?"), and service is emergency, not planned.

### 2.4 Why this is V-Guard's problem to own
V-Guard was founded in 1977 to solve exactly Indian power unreliability. It runs a **₹5,966-crore business (FY26)** across the precise categories involved, its **Electronics segment grew ~8.6% for the year and +22.3% in Q4 FY26**, it manufactures its own batteries, has taken a **30.35% stake in Gegadyne Energy**, and has just opened a **₹120-crore Kochi Innovation Campus** with IoT and reliability labs. No competitor is positioned as well to close the smart→intelligent gap. [refs: research-market]

## 3. The Solution — V-Guard Sentinel
Sentinel is an intelligence layer, not a new gadget. A compact **AI Core** — a microcontroller with a neural-processing accelerator plus a small sensor set — is embedded in new inverters and offered as a **retrofit module** for the installed base. It runs four on-device engines and participates in a privacy-preserving federated-learning loop. [Fig: architecture-detailed]

**Engine 1 — Predictive Health & Longevity.** Estimates true battery **State-of-Health (SoH)** and predicts a **Remaining-Useful-Life (RUL) window** ("safe until ~15 Nov ± 2 weeks"), and flags degrading internals early. Adaptive charge/thermal policy targets **15–30% longer battery life**; a tamper-proof health-log turns warranty into a one-tap, data-backed process.

**Engine 2 — Habit-Learning Autopilot.** Learns the home's load and outage patterns on-device and, during a blackout, runs **autonomous load-prioritisation**: keep critical loads (fridge, lights, Wi-Fi, medical), defer/shed the rest — stretching usable backup for essentials. [Fig: load-prioritisation-flow]

**Engine 3 — Energy Coach & Grid Shield.** Uses lightweight NILM to show where power goes and coach savings (valuable as ToU smart-meter tariffs roll out), and **fast power-quality detection** (sag/swell) for appliance protection and grid-abuse logging.

**Engine 4 — Federated Fleet Intelligence.** Each unit contributes encrypted model improvements — never raw data — so the shared model sharpens as the fleet grows. [Fig: federated-lifecycle]

Together these turn the inverter into the **brain of the V-Guard home**, and the same AI Core extends across pumps, stabilisers and water heaters.

## 4. System Architecture
Sentinel is organised as five on-device layers inside an **offline-first boundary**, with opportunistic links to a phone/app (BLE) and the V-Guard cloud (Wi-Fi) [Fig: architecture-detailed]:
1. **Sensing** — current (shunt + Hall), isolated voltage, temperature (NTC/digital), vibration (MEMS accelerometer), acoustic (MEMS mic).
2. **Signal conditioning & acquisition** — analog front-end, galvanic isolation, 16-bit ADC, anti-alias filtering, a hardware/firmware coulomb counter, and windowed buffers for FFT/statistics.
3. **Edge compute (the AI Core)** — an Arm Cortex-M-class MCU with an NPU accelerator; feature extraction (FFT, RMS, current-signature, statistical features).
4. **On-device AI engines** — int8-quantised TinyML models (SoH/RUL regressor, fault autoencoder, habit forecaster, NILM classifier, power-quality detector).
5. **Decision & actuation** — adaptive charge/thermal control, relay-based load prioritisation, predictive alerts and the warranty health-log.
Every core function runs with **zero internet**; the cloud is a bonus for federated aggregation, OTA and analytics.

## 5. The Sentinel AI Core — Hardware Design
### 5.1 Compute
The workloads (a small GRU for RUL, an autoencoder for anomalies, FFT-based PQ, light NILM) fit comfortably in TinyML budgets (models 5–100 KB, int8). Two credible tiers:
- **Cost tier:** an **ESP32-S3** (dual-core LX7, vector instructions, integrated BLE/Wi-Fi) — cheapest path, adequate for RUL + PQ + load logic.
- **Performance tier:** an **STM32N6** (Cortex-M55 + Ethos-U NPU) or STM32H7 for heavier NILM/anomaly models with headroom.
Feature extraction uses **CMSIS-DSP** (a 1024-pt Q15 FFT runs in ~1 ms on an M4-class core), leaving ample budget within the IEC power-quality half-cycle window (~10 ms).

### 5.2 Sensing front-end
- **Current:** low-side shunt + high-precision monitor (e.g., INA228, 20-bit) for coulomb counting, and/or a Hall sensor (ACS758/TMCS1100) for isolated, high-current battery/mains measurement.
- **Voltage:** divider + isolation amplifier / isolated ADC for safe 150–300 V bus sensing.
- **Temperature:** battery/ambient NTC + a digital sensor (TMP117-class) for accuracy.
- **Vibration/acoustic:** MEMS accelerometer (ADXL345-class) and MEMS microphone for bearing/relay/fan and corona-discharge fingerprints.
Coulomb counting needs a stable ~16-bit-effective current channel; a milliohm shunt with low-tempco tolerance keeps SoC error inside a ±5% budget when fused with OCV/EKF [Fig: ekf-drift].

### 5.3 Actuation, power, connectivity, mechanical
- **Load control:** relay/contactor or SSR channels (16–25 A) with driver ICs for household-circuit shedding, with fail-safe defaults.
- **Power:** a buck converter taps the inverter's existing rail; sub-mW-class idle budget so the module never meaningfully loads the battery.
- **Connectivity:** BLE for the local app; Wi-Fi for opportunistic sync; **all AI runs without either.**
- **Mechanical:** a flame-retardant **ABS/PC (UL94 V-0)** enclosure (~90 × 70 × 30 mm) housing an ~80 × 60 mm PCB, indoor-rated, with screw-terminal I/O and a screw/DIN mount — detailed in the CAD package (`docs/cad/`).

### 5.4 Bill of materials
Two variants keep the added cost within **₹150–₹800** (a <10–15% premium on a typical inverter), justified in `docs/report/Parameters.md` (BOM table): a **basic** variant (cost-tier MCU, shunt current sense, NTC, relays) and a **premium** variant (NPU MCU, Hall + isolated voltage sense, digital temperature, accelerometer + mic). *Line items reconciled with hardware research stream B.*

## 6. Engine 1 — Battery SoH & RUL Estimation
### 6.1 Method stack
Sentinel fuses classical estimation with a small learned corrector [Fig: battery-rul-flow]:
1. **Coulomb counting** (∫I·dt) for a fast SoC estimate — but it drifts without correction.
2. **Rest-OCV correction** and an **internal-resistance probe** (ΔV/ΔI on load steps).
3. An **Extended Kalman Filter** fusing these into a bounded SoC + R_int state [Fig: ekf-drift].
4. A **feature vector** — ΔV under load, R_int trend, Ah throughput, depth-of-discharge histogram, temperature-stress integral, coulombic efficiency.
5. A **TinyML SoH/RUL model** (a compact quantised GRU/1-D CNN) mapping the feature history to SoH % and an RUL window.

### 6.2 Data & accuracy — honestly framed
Base models are pre-trained on public degradation datasets (**NASA randomized battery usage, CALCE, Oxford**) and refined on V-Guard's own tubular-battery duty cycles. Peer-reviewed SoH estimators report single-digit-percent error (≈85–95% accuracy) — but generalisation across chemistries and climates is real work. **We therefore present a warning *window*, not a false-precision date** — e.g., "replace within ~3–5 weeks, 90% confidence." This honesty is a feature: it builds installer/consumer trust and avoids the over-promising that discredits "AI" claims. *Exact datasets/accuracy figures reconciled with battery research stream A.*

### 6.3 What it unlocks
Weeks-ahead warning eliminates surprise mid-blackout death; adaptive charge/thermal policy slows sulphation/water-loss to extend life; the health-log makes warranty data-driven — directly attacking the failure causes that today *void* warranty (electrolyte neglect, deep discharge, overcharge).

## 7. Engine 2 — Habit-Learning Autopilot & Load Prioritisation
### 7.1 Honest positioning
Load prioritisation is a **mature, rule-based** capability in premium products (Tesla Powerwall essential-circuits, SPAN/Lumin panels) but is **absent from Indian home inverters**, where control is manual at best. Fully AI/RL-driven prioritisation is research-grade (simulation gains are inflated; realistic peak/energy gains are ~8–20%). Sentinel therefore ships a **hybrid**: robust rule-based tiers made smarter by a *learned demand/outage forecaster*.

### 7.2 Control logic [Fig: load-prioritisation-flow]
On outage detection, the autopilot: estimates available energy (Ŵh = SoH × SoC × capacity); forecasts demand and likely outage duration from learned patterns; tiers loads (T1 keep — fridge, lights, Wi-Fi, medical; T2 defer — geyser, pump; T3 shed — AC); actuates relays to protect T1; and continuously re-evaluates until the grid restores, then recharges optimally. On-device clustering learns the household's daily/weekly rhythm; no cloud needed. Safety defaults ensure that a sensor or model fault never strands critical loads.

## 8. Engine 3 — Energy Coach & Grid Shield
### 8.1 Energy Coach (NILM) — feasible, with limits stated
Low-frequency (≤1 Hz) disaggregation reliably separates **high-power loads** (AC, geyser, pump, fridge) at ~0.65–0.89 F1 on benchmark datasets; low-power/overlapping loads and cross-home generalisation are known weaknesses, and Indian public data is thin (iAWE = one Delhi home). We therefore position the Coach as **directional insight + per-home calibration**, running on the AI Core for headline loads and treating fine-grained disaggregation as a roadmap/cloud-assisted item — not an over-claim.

### 8.2 Grid Shield — detect, don't "predict"
Grid-origin voltage sags propagate near-instantly; there is **no locally observable precursor**, so honest engineering is **fast detection + ride-through/response**, not prediction. Using CMSIS-DSP RMS/FFT the Core detects a sag within ~1 cycle (≈20 ms) and can protect/annotate accordingly, targeting **IEC 61000-4-30 Class-S-like** measurement (not certified Class A). The only genuinely anticipatable case is a self-caused local motor start; seasonal/statistical risk is advisory only.

## 9. Engine 4 — Federated Fleet Intelligence
### 9.1 A deployable architecture (not hype) [Fig: federated-lifecycle]
On-MCU training of deep models across a fleet is **not** realistic today. The honest, deployable pipeline is:
1. **Cloud pre-train** a base model on public data.
2. **OTA-deploy** the quantised model; the MCU runs **inference** continuously (optionally light sparse on-device personalisation, MCUNetV3-style).
3. A **home gateway or paired phone** performs the actual local training round (it has RAM, FPU, reliable power).
4. **Opportunistic upload of model deltas only** (tens–hundreds of KB) when power + connectivity allow.
5. **Server-side FedAvg / DP-FTRL** aggregation → improved global model on the next OTA window.

### 9.2 Privacy — done properly
"Encrypted updates only" is not sufficient on its own (updates leak via gradient inversion). Sentinel combines **Secure Aggregation** (server sees only the summed update) **with Differential Privacy** (DP-FTRL, the production technique behind Google Gboard, ~single-digit ε). We are candid that strong privacy scales with cohort size, so early-pilot privacy claims are modest and tighten as the fleet grows — which is also the moat: **accuracy and privacy both compound with V-Guard's installed base**, something no competitor can rebuild without the same scale [Fig: federated-moat].

## 10. Key Parameters to be Defined
A full specification lives in `docs/report/Parameters.md`; the headline parameters are:
- **Electrical sensing:** current range/resolution & shunt tolerance; isolated voltage range (150–300 V); ADC effective bits (≥16 for coulomb counting); temperature range/accuracy; sampling rates (1 Hz energy, ~6.4–12.8 kS/s power-quality).
- **Compute:** MCU/NPU, clock, RAM/flash, model sizes (5–100 KB), inference latency budget (<10 ms PQ window).
- **ML thresholds:** SoH usable threshold (80%), RUL warning window & confidence, SoC error budget (±5%), load tiers T1/T2/T3, FFT window (128–256 samples/cycle).
- **Federated:** round cadence (~daily, opportunistic), client fraction, update size, DP target, secure-aggregation cohort minimum.
- **Product targets:** battery-life extension 15–30%, backup extension for essentials, prediction lead-time (weeks), added BOM ₹150–800, module idle power.
- **Environment/compliance:** operating 0–55 °C, enclosure UL94 V-0, indoor IP, relevant BIS/IEC standards.

## 11. Prototype & Validation Plan
For the detailed round we will demonstrate (software-led, matching our team's ML + full-stack strengths):
1. **Battery-RUL model** trained on NASA/CALCE + synthetic Indian tubular duty-cycles, predicting a failure *window* on held-out cells; report MAE/RMSE and calibration.
2. **Federated-learning simulation** with Flower across ≥5 simulated "homes," showing the shared model improve **without raw data leaving a client**, with SecAgg + DP.
3. **App/dashboard** visualising SoH, the RUL countdown, the autonomous load-prioritisation simulation, and energy insights.
4. **Optional edge demo:** the quantised RUL model flashed to an ESP32-S3 + current-sensor breadboard to prove true on-device inference (no PCB/CAD manufacture needed).
5. **CAD/CAD-render** of the AI Core enclosure and PCB (this package) to visualise the physical product.
**Success metrics:** RUL window hit-rate, SoC error within ±5%, load-shed correctness, FL accuracy vs centralised baseline, and on-device latency/footprint.

## 12. Manufacturing, Integration & Cost
Sentinel is a **software-led upgrade to products V-Guard already builds at scale**, so the path to revenue is short. New inverters embed the Core on the main board; the installed base is addressed by a retrofit module. BOM sits within a <10–15% price premium. V-Guard's in-house battery manufacturing lets health models be co-designed with the cell chemistry — an advantage third-party add-ons cannot match — and the Kochi reliability lab provides validation infrastructure.

## 13. Standards, Safety & Compliance
- **Electrical safety:** BIS **IS 302** (household appliance safety, QCO in force Oct 2026) and **IEC 62040** (UPS).
- **EMC/immunity:** **IEC 61000** family; power-quality measurement follows **IEC 61000-4-30 (Class-S-like)**.
- **Battery safety:** **IS 16046 / IEC 62133** for Li cells; ventilation/thermal design for lead-acid.
- **IT/electronics safety:** **IEC 62368-1 / IS 13252**; **RoHS/CE**; India **e-waste** rules.
- **Efficiency labelling:** home UPS/batteries/stabilisers currently carry **no BEE energy-star** — an open differentiation niche Sentinel can help V-Guard lead.
Isolation on all mains-referenced sensing and fail-safe relay defaults are core safety requirements.

## 14. Market & Business Value
### 14.1 Opportunity
India's **home-UPS market** is ~USD 348M (2024) → ~USD 487M (2030, 5.6% CAGR); the **inverter-battery** market ~USD 197M → 346M (6.24%); **stabilisers** ~USD 730M → 1,160M; **geysers** ~USD 457M → 859M. V-Guard already sells across all of these through ~100,000 retail touchpoints, so the addressable base for a software-led upgrade is enormous. Smart-meter ToU tariffs (5.28 crore meters installed under RDSS) create demand for exactly the energy-optimisation Sentinel provides.

### 14.2 Why it compounds for V-Guard
- **Recurring, perfectly-timed aftermarket revenue:** predicting the replacement window prompts the next battery purchase from V-Guard, converting a one-time sale into a managed lifecycle.
- **Warranty & service savings:** V-Guard's **warranty cost was ~1.52% of revenue (₹69.39 cr, FY24)**; predictive maintenance converts emergency claims into planned interventions and defends against disputed (avoidable) failures — a direct margin lever.
- **Retention & premiumisation; a data moat** that deepens with every unit via federated learning [Fig: federated-moat; competitive-gap].
- **Portfolio leverage:** one AI Core extends to pumps (bearing/dry-run), stabilisers (PQ), water heaters (predictive preheating) [Fig: platform-roadmap].

## 15. Sustainability & Social Impact
Extending battery life 15–30% and pinpointing replacement reduces premature disposal of lead-acid batteries — significant given that **60–80% of India's used-lead-acid recycling is informal**, and lead exposure already affects an estimated **275 million Indian children**. Optimised charging cuts wasted energy; predictive maintenance extends product lifespans and reduces material consumption. For price-sensitive and rural homes, resilient self-managing backup protects food, study hours, connectivity and medical devices through the outages that remain a daily reality.

## 16. Risks & Mitigations
- **Over-claiming AI** → we scope every engine to deployed-vs-research reality and present windows/ranges, not false precision.
- **Model generalisation** (chemistry/climate/home) → fleet data + federated refinement + per-home calibration; conservative confidence bounds.
- **Privacy** → SecAgg + DP; modest early claims that strengthen with cohort size.
- **Cost creep** → tiered BOM; reuse of existing sensing; software-first rollout.
- **Safety** → isolation, fail-safe relay defaults, standards compliance, reliability-lab validation.

## 17. Roadmap
- **Phase 1 (0–6 mo):** Sentinel battery-RUL + autopilot in the Smart Pro inverter line; federated-learning pilot.
- **Phase 2 (6–18 mo):** Energy Coach + Grid Shield; AI Core as a retrofit module for the installed base.
- **Phase 3 (18–36 mo):** portfolio rollout — pumps, stabilisers, water heaters — coordinated as one intelligent V-Guard home.

## 18. Vision
By 2030, every V-Guard product in a home runs on one shared AI Core, operating not as separate appliances but as a single self-aware system that predicts its own failures, manages the home's power, and keeps essentials running through any outage — without the user thinking about it. Because every unit shipped feeds the same models through federated learning, **scale itself becomes an advantage rivals cannot rebuild.** V-Guard stops being the company that protects India's power and becomes the intelligence layer the Indian home runs on.

---
*References: consolidated in `docs/report/research-market.md` and `docs/report/research-edge-ai.md` (battery + hardware citations appended on stream completion).*
