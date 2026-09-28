# 06 — Engine 3a: Energy Coach — how the ESP32 distinguishes appliances (NILM) — worked out to a T

**Resolves Gap Register:** H17 (how the ESP distinguishes appliances), H18 (NILM has no AC signal in the basic BOM), H27 (AC V/I taps), H28 (ESP32 ADC not metering-grade). Design changes D1 and D4 in 12.

## 0. The answer in five steps (what to tell the judge)
1. **Measure real electrical quantities, not just current.** A metering AFE (**Microchip ATM90E32AS**, ~₹350) samples voltage and current synchronously at 8 kHz on ΣΔ ADCs and gives the ESP32-S3 over SPI calibrated **P, Q, S, PF, phase angle, Irms, I-peak and the fundamental/harmonic split of P**, refreshed ≈3×/s. The ESP32 internal ADC is not used for metrology.
2. **Detect events**: steady state → step → new steady state (Hart-style edge detection, ΔP ≈ 25–30 W threshold, debounce, settling-time limit).
3. **Build a ~13-number signature per event**: ΔP (voltage-normalised), ΔQ, step angle, inrush ratio, settling time, transient overshoot area, harmonic share, run duration (from ON/OFF pairing), periodicity, time of day, inverter mode, circuit.
4. **Match against a per-home library**: rule layer (physics type) → k-NN over prototypes seeded from a factory table of Indian appliance classes, grown by unsupervised clustering, labelled by the user in the app ("~1,450 W with a motor start switched on at 21:04 — AC? pump?"). Each match carries a confidence; unmatched events open a new cluster.
5. **Account and coach**: ∫P between ON and OFF → kWh/day and ₹ at the home's ToD tariff; per-appliance baselines drive anomaly alerts.

**Honest headline:** this reliably separates the **five to eight large, distinctive loads** (AC, geyser, pump, fridge, iron/kettle/mixer-class) and lumps the rest into "fans & lights", "electronics" and "always-on". It will not distinguish two 75 W fans, a router from a TV in standby, or individual bulbs — no NILM method at this data rate does.

## 1. Signal and analogue front end
### 1.1 Where to measure — the report never said; here it is
An Indian home inverter sits between mains and a **backed-up sub-circuit** (fans, lights, TV, router, sometimes fridge/mixer ≤ 750 W). A changeover relay passes mains to that circuit when the grid is present and switches to the inverter bridge when it fails.
- **Primary tap = the inverter's AC OUTPUT terminals** (CT on output live; voltage across output L–N). Sees the backed-up loads in *both* grid-pass-through and battery modes. **Battery DC current is not used for NILM** (exists only during backup; charger DC draw is not load information). This is the design inconsistency H18 in the submitted report: it described NILM "from the ≤1 Hz current signal" the battery shunt provides — that signal cannot do it.
- **Optional second tap = whole-house mains** via a clip-on CT at the distribution board — needed to see AC (≈1.5 kW), geyser (2–3 kW), pump (375–750 W), which are normally not on a ≤1.5 kVA inverter's circuit. ATM90E32AS has three current channels: output CT, mains CT, and (embedded) charger input.
- **Subtract the inverter's own charger** on the mains channel (firmware knows charger state and current) — otherwise charger turn-on looks like a 100–400 W appliance.
### 1.2 What is measured and why
Hart's original NALM used ΔP/ΔQ precisely because two loads with equal current differ in P, Q, harmonics and transient (fridge "250 W + 200 var" vs a 250 W heater at ~0 var).
| Quantity | NILM use | ATM90E32AS register |
|---|---|---|
| P | step size, energy | PmeanA/B/C (LSB 0.00032 W) |
| Q | motor vs heater vs electronics | QmeanA/B/C |
| S, PF, angle | φ = atan2(ΔQ, ΔP) | SmeanA, PFmeanA (0.001), PAngleA (0.1°) |
| Irms, Vrms | normalisation, sanity | IrmsA (1 mA), UrmsA (10 mV) |
| I-peak | inrush ratio | IPeakA |
| P_fund / P_harm | **harmonic share** — SMPS/LED vs linear loads without any FFT on the MCU | PmeanAF / PmeanAH |
| Frequency | grid vs inverter mode, validity | Freq (0.01 Hz) |
| THD, harmonics 2–32 (optional) | richer electronic signatures | **ATM90E36A** only (pin-compatible, DFT engine) |
### 1.3 Sampling and cadence
AFE: 8 kHz/channel, 2 kHz BW; all mean registers are 16-line-cycle averages (320 ms, ≈3.125 Hz). **Fast stream** 3.125 Hz {P,Q,S,PF,Irms,Ipk,Pf,Ph,Vrms} in a 120 s ring (375 × 36 B ≈ 13.5 KB/channel); **slow stream** 1 Hz decimated for logging; 1-min aggregates persisted (≈23 KB/day). Per-cycle (20 ms) waveforms are not needed for this classifier; if later wanted, ATM90E36A can DMA raw 8 kHz samples, or an ADS131M04 with firmware metrology.
### 1.4 AFE selection (D4)
**Why not the ESP32-S3 internal ADC**: Espressif's own characterisation — 12-bit, DNL ±4 / INL ±8 LSB, non-linear above ~2.75 V, −30…0 mV residual after curve-fit calibration, noise-sensitive, no simultaneous V/I sampling. A 25 W step on a 1.5 kW background is 1.7 %; INL alone is 0.2 % FS plus noise — marginal for ΔQ/harmonics and all metrology would be firmware. Espressif's own guidance for metering is a dedicated AFE.
| Part | Channels | On-chip | Price | Fit |
|---|---|---|---|---|
| **ATM90E32AS** | 3 V + 3 I | P,Q,S,PF,angle,rms,Ipeak, fund/harm P, freq, sag/ZX; ±0.1 % energy over 6000:1; single-point cal | ₹350 @1, ₹291 @1k (DigiKey India) | **Recommended.** 3 I channels; proven with ESP32 (CircuitSetup, ESPHome driver) |
| ATM90E36A | same + THD/DFT + raw DMA | | similar | drop-in upgrade for harmonics |
| ADE7953 | 1 V + 2 I | energy, rms, ZX, sag/peak | $3.5 | single-tap alternative |
| ADE9153A | 1 V + 2 I | + mSure autocal (**shunt only, not CT**), dip/swell | $10.35 | best only for a shunt-based fully integrated design |
| ADS131M04 | 4× 24-bit ΣΔ, no DSP | raw samples | $3.6 | only if cycle-level waveforms required |
### 1.5 Taps and isolation
- **Current**: CT on inverter output live (I_max ≈ 6.5 A at 1.5 kVA) and optionally mains (≤ 30–40 A); 1000:1 or 2000:1 with burden so I_max → ≤ ~500 mVrms at the AFE (input 120 µV–720 mVrms, PGA 1/2/4). CTs are inherently isolated. Parts: SCT-013-030 (~₹489), SCT-013-000 100 A.
- **Voltage, option A (clip-on module, SELV)**: 230 V → 9–12 V PCB transformer feeding the V channel via divider (also powers the module); the AFE's phase-cal register removes the transformer shift. No digital isolator (CircuitSetup approach).
- **Voltage, option B (production, inside the inverter)**: resistor divider (~1 MΩ:1 kΩ) L–N into the AFE on the hot side; **4-channel digital isolator** (TI ISO7741 / ADuM4152, 5 kVrms) on SPI + IRQ; isolated 3.3 V for the AFE. Both CT channels share the single-phase voltage (phase A and B voltage inputs tied).
- **BOM delta**: AFE ₹300–350 + CT ₹150–500 + transformer/isolator ₹100–250 ≈ **₹600–1,100** over a module with no metering.

## 2. Event detection
### 2.1 Principle
Event-based NILM detects state transitions and classifies each; it runs on MCUs because it never stores or learns whole-day sequences. Base algorithm: Lu & Li's moving-average change test with time limit — compare the mean of a window before sample i with the mean after; flag when the difference exceeds P_th; merge alarms within T_merge; add a derivative test so long transients (AC 13 s, fridge 1.4 s, TV 0.3 s, kettle 0.1 s) yield one event. BLUED defines a real event as ΔP > 30 W lasting ≥ 5 s; unsupervised detectors reach > 99 % detection and pair ~95 % of ON/OFF activations on BLUED.
### 2.2 Parameters (3.125 Hz frames)
| Symbol | Value | Rationale |
|---|---|---|
| N_pre, N_post | 4 frames (1.28 s) | ≥ 1 s averages out flicker |
| P_th | 25 W or 2 % of pre-event P, whichever larger | BLUED 30 W; relative term for big backgrounds |
| Q_th | 25 var | catches ΔQ-dominant motor events |
| T_merge | 2 frames (0.64 s) | one transient → one event |
| SS_win | 5 frames: std(P) < max(8 W, 1 %) | steady-state test |
| T_max_transient | 15 s | > AC's 13 s; then force "settled" |
| ε_deriv | |dP/dt| < 15 W/frame over SS_win | Lu & Li ε criterion |
| V_norm | P_norm = P·(230/Vrms)² | Hart normalisation; India swung 180–250 V in iAWE |
### 2.3 Pseudocode
```
STATE: ring X[k] = {P,Q,S,PF,Irms,Ipk,Pf,Ph,V,t} @3.125 Hz per channel; mode ∈ {STEADY, TRANSIENT}; ss_ref
on_new_frame(x):
  push(X, x); Pn = x.P*(230/x.V)^2
  if mode == STEADY:
    m_pre = mean(Pn[k-N_post-N_pre .. k-N_post]); m_post = mean(Pn[k-N_post+1 .. k]); dQ likewise
    if |m_post-m_pre| > max(P_th, 0.02*m_pre) or |dQ| > Q_th: mode = TRANSIENT; t0 = k-N_post; ipk_max = 0
  else:
    ipk_max = max(ipk_max, x.Ipk)
    settled = std(Pn[last SS_win]) < max(8, 0.01*mean) and max|diff(Pn[last SS_win])| < ε_deriv
    if settled or (k-t0) > T_max_transient:
      ss_new = mean over last SS_win of (Pn,Q,Pf,Ph); ev = make_event(t0, ss_ref, ss_new, ipk_max, k-t0, X[t0..k])
      if |ev.dP| < P_th and |ev.dQ| < Q_th: discard else emit(ev)
      ss_ref = ss_new; mode = STEADY; suppress triggers for T_merge
```
O(N) on ≤ 50-element windows — microseconds on the LX7.
### 2.4 ON/OFF pairing
An OFF (ΔP < 0) pairs with the most recent unpaired ON with |ΔP_on + ΔP_off| ≤ max(15 W, 10 %) and |ΔQ_on + ΔQ_off| ≤ max(15 var, 15 %), searching back ≤ 24 h. Pairing yields duration, energy (∫P from the 1 Hz stream) and a cleaner ΔP. Unpaired ONs > 24 h close as "unknown-off".
### 2.5 Transient capture
Frames from t0 − N_pre to settle (≤ 51 × 36 B ≈ 1.8 KB) feed inrush ratio, settling time, overshoot area. Events are ~64 B records.

## 3. Appliance signatures
### 3.1 Feature vector (F = 13)
| # | Feature | Definition | Discriminates |
|---|---|---|---|
| 1 | ΔP | voltage-normalised step (W) | size class |
| 2 | ΔQ | reactive step (var) | motor (+Q) vs heater (~0) vs SMPS (small, often leading) |
| 3 | φ | atan2(ΔQ, ΔP) | scale-free version of 2 |
| 4 | r_pk | Ipk_transient / Irms_step | compressors/motors 5–7×, resistive ≈1, SMPS 1.5–3× |
| 5 | t_settle | frames to settled × 0.32 s | AC ≈13 s, fridge ≈1.4 s, heaters < 0.5 s |
| 6 | A_tr | Σ(P − P_ss,new) over transient (W·s) | motor-start hump vs monotone heater |
| 7 | h | ΔP_harm/ΔP_fund | electronics/LED (high) vs linear (~0) |
| 8 | ΔTHD_I (opt.) | ATM90E36A only | LED drivers 54–121 % THD |
| 9 | dur | ON→OFF (s) | fridge 5–20 min, geyser 10–60 min, mixer 1–3 min |
| 10 | period | since last event of same cluster | thermostat periodicity |
| 11 | tod | (sin, cos) hour | priors (pump morning, AC night) |
| 12 | src | 0 grid / 1 battery mode | battery mode = cleaner sub-circuit |
| 13 | ch | 0 output CT / 1 mains CT | which circuit |
Feature 7 is what makes the AFE worth more than a generic meter: it separates a 90 W LED TV from a 90 W fan without an FFT. MCU-class literature finds P, Q, |S| plus a few harmonics sufficient for > 90 % accuracy with random forests or small MLPs.
### 3.2 Factory prior table — Indian appliances
| Appliance | ΔP (W) | Q / PF | r_pk | t_settle | h | Pattern | Circuit |
|---|---|---|---|---|---|---|---|
| Fridge, fixed-speed (165–250 L) | 80–200 run; defrost heater 150–300 | lagging PF 0.6–0.8, ΔQ ≈ 0.7–1× ΔP | 5–6× 0.3–0.5 s | ~1.4 s | low | 5–20 min ON / 15–30 min OFF, ~50 % duty, all day | often inverter output |
| Fridge, inverter compressor | 40–150 drifting | PF > 0.9 | 1–2× soft start | ramps 10–60 s | medium | 80–90 % on, slow ramps | inverter output |
| AC 1.5 t fixed-speed | 1,400–1,800 | lagging PF 0.8–0.9 | 5–7× 0.5–1.5 s | ~13 s | low | 10–30 min cycles; indoor fan 50–100 W separate | mains only |
| AC 1.5 t inverter | 300–1,600 variable | PF ≈ 0.98 (PFC) | ~1× | ramps minutes | medium | only the initial 400–800 W step is an event | mains only |
| Geyser (storage) | 2,000–3,000 | PF ≈ 1, ΔQ ≈ 0 | ≈1 | < 0.5 s | ~0 | 10–60 min, thermostat re-cycles | mains only |
| Induction cooktop | 2,000–3,000 chopped | PF 0.9–1, high harmonics | ≈1 | fast | high | power-level steps | mains |
| Pump 0.5–1 HP | 375–900 | lagging PF 0.7–0.85 | 4–6× | 1–3 s | low | 5–30 min, morning/evening | mains |
| Iron | 750–1,500 | PF ≈ 1 | ≈1 | < 0.5 s | ~0 | cycles every 30–90 s in use | either |
| Mixer-grinder (universal motor) | 400–750 | PF 0.8–0.9 | 2–3× | < 1 s | medium-high | 30 s–3 min bursts | inverter output |
| Ceiling fan (induction + regulator) | 40–75 (BLDC 28–35) | PF ~0.9 | ~1.5× | < 1 s | low; regulator adds harmonics | hours; 10–20 W speed steps | inverter output |
| LED lights | 5–20/lamp | PF 0.5–0.9 | 1.5–3× | < 0.3 s | high | evening | inverter output |
| LED TV + STB | 40–120 | PF 0.5–0.9 | 2–3× | < 0.5 s | high | evening 1–4 h | inverter output |
| Router/chargers/standby | 5–30 total | — | — | — | high | constant | inverter output |
| Washing machine | 300–500 motor; 1,500–2,000 heater | multi-state | 3–5× | varies | mixed | 30–60 min FSM | mains |
### 3.3 Separability — what the P/Q/transient space can and cannot do
| Pair | Separable? | By |
|---|---|---|
| Geyser vs fixed AC | Yes | ΔQ ≈ 0 & r_pk ≈ 1 vs ΔQ large & r_pk 5–7× & 13 s settle |
| Fixed AC vs pump | Yes | ΔP + duration/time-of-day |
| Fridge vs mixer | Yes | strict periodicity vs bursts; r_pk, harmonics |
| Fridge vs one fan + something | Mostly | fridge inrush 5–6× and periodicity |
| Iron vs kettle vs room heater | **No (by step)** | all resistive 1–1.5 kW; duty pattern only → "heating appliance" |
| Two identical fans/lights | **No** | "fans ×2" by ΔP multiples at best |
| TV vs router vs chargers < 40 W | **No** | under P_th; "electronics/always-on" |
| Inverter AC/fridge mode changes | Partial | continuously variable (Hart's class 4); envelope tracking between start/stop |
| Fan regulator steps 10–20 W | No | below threshold |
Lab literature agrees: kettle vs iron at 2.2 kW differ only in harmonics; energy-saving bulbs "not recognised properly"; Sense is good at HVAC/water heaters, poor at small and identical devices.

## 4. Matching / classifier
### 4.1 Architecture (scalar code, no framework)
1. **Rule layer (physics type)**: RESISTIVE (|φ| < 10°, r_pk < 1.3, h < 0.05); MOTOR (φ 25–60°, r_pk > 3); ELECTRONIC (h > 0.15 or r_pk 1.5–3 with |φ| < 35°); VARIABLE (no settle, slow ramp). Hart's taxonomy per event.
2. **k-NN layer (per-home library)**: within type, standardised weighted Euclidean over (log ΔP, ΔQ/ΔP, log r_pk, log t_settle, h, log dur, tod), k = 3, weights (3, 2, 1.5, 1, 1.5, 1, 0.5) tuned offline on iAWE/UK-DALE.
3. **Decision**: score_c = Σ_{i∈kNN, label c} exp(−d_i²/2)·prior_c; confidence = score_best/Σ; d_best > d_open (≈2.5) → **new cluster**, unlabelled until the user names it or a factory prior matches ≥ 0.7.
A ≤64-node decision tree or a 13-24-12 int8 MLP (~1 KB) is an equal drop-in for layer 1; k-NN is kept for layer 2 because it learns from one labelled example. MCU evidence: Tsetlin classifier in 17 KB flash / 168 B SRAM at 0.43 ms on ESP32; RF on 5 features = 4.84 kcycles on Cortex-M4.
### 4.2 Building the library
1. **Factory priors** (~2 KB flash): §3.2 as feature ranges + per-circuit priors (a geyser cannot be on a 600 VA output).
2. **Auto-clustering from day 1**: leader clustering on paired events (join if d < 1.5, else new); Welford mean/variance, count, duration, period. Strict 20–40 min MOTOR periodicity → auto-label "refrigerator"; ≥ 2 kW RESISTIVE on mains → "geyser?".
3. **User labelling** ("what just turned on?"): when a cluster reaches N ≥ 3 events, one notification with a plain-language description and 3 ranked suggestions; plus assisted mode "switch your geyser on now" → next event within 60 s is labelled (the Smappee mechanism). Labels stay on device unless opted in.
4. **Merge/split**: same label + overlapping ranges merge; variance > 2× class prior → split (k=2) and re-ask.
### 4.3 Simultaneous and overlapping events
Near-simultaneous (> 0.64 s apart) → two events. Truly overlapping: if d_best > d_open and ΔP > 2·P_th, try the best pair (i, j) among the top-8 prototypes with |ΔP − ΔP_i − ΔP_j| < 10 % and |ΔQ…| < 15 %; accept at ×0.6 confidence (≤ 28 comparisons). Unresolved events are tracked as "unknown" so kWh totals stay correct; relabelled retroactively when a clean OFF arrives. **Energy reconciliation** every minute: Σ assigned ≤ measured aggregate; residual = "other/always-on".
### 4.4 Cost on ESP32-S3
| Item | Size / time |
|---|---|
| Fast-stream ring (2 ch × 120 s) | ≈ 27 KB SRAM |
| Event records (2,000 × 64 B, LittleFS) | 128 KB flash |
| Library (≤ 64 prototypes × 13 × 2 stats × 4 B) | ≈ 6.7 KB (NVS) |
| 1-min aggregates, 30 days | ≈ 700 KB flash |
| Detector per frame / features per event / k-NN | < 10 µs / < 200 µs / < 100 µs |
| SPI traffic | ≈ 0.2 kB/s |
| Total CPU | ≪ 1 % of one LX7 core |

## 5. Per-home calibration and honest accuracy
### 5.1 Calibration flow
| Phase | When | What |
|---|---|---|
| 0 Factory | production | AFE gain/phase calibrated per CT model; self-test |
| 1 Install | day 0 | detect taps (output only / + mains); CT polarity via sign of P; pull DISCOM ToD tariff in app |
| 2 Silent learning | days 1–7 | events + clustering only; user sees total kWh and backed-up vs rest split; battery-mode segments give clean sub-circuit data |
| 3 Guided labelling | days 3–14 | ≤ 2 questions/day for clusters with ≥ 3 events; optional assisted walk-through |
| 4 Confirmation | weeks 2–4 | per-appliance kWh with confidence badges; corrections re-cluster; baselines from ≥ 14 days |
| 5 Steady | after | anomaly alerts; seasonal drift (AC appears in April, geyser in November) reopens questions; recalibration prompt if Vrms/f statistics change |
### 5.2 What the literature supports
- **iAWE (India)**: one Delhi home, 73 days, 1 Hz P/Q/S/V/I/f/PF sub-meters; fridge, two ACs (≈ half the energy), washing machine, iron, TV; mains 180–260 V, outages up to 9 h/day — the right offline validation set (Indian, 1 Hz, has Q). REDD (1 Hz aggregate), UK-DALE (16 kHz whole-house).
- **1 Hz benchmarks**: NILMTK on iAWE, CO ≈ FHMM; 2025 NILMTK review: AC and fridge F1 0.7–0.9. Neural NILM fridge F1 0.87 (AE), seq2point 0.92 with a 599-sample window and 1,024-unit dense layer — the model class the MCU rules out.
- **MCU-class**: Tsetlin on ESP32 (REDD): fridge F1 0.89, microwave 0.84 (2 appliances); dishwasher/furnace collapse at 4 appliances. RF/MLP on STM32F4 with P, Q, |S| + odd harmonics: 89.8–95.2 % on 5–10-class lab sets.
- **Too-coarse fails**: 30-min data → kettle F1 ≈ 0.45 — why the 3 Hz event stream is kept.
### 5.3 What the Coach can honestly promise (after 2–4 weeks)
| Claim | Target | Basis |
|---|---|---|
| Fridge cycles, daily kWh, duty | F1 ≥ 0.85 | strongest class in every 1 Hz benchmark |
| Fixed AC and geyser (mains CT fitted) | F1 ≥ 0.85 each | large, distinct |
| Pump (mains CT) | F1 ≈ 0.8 | motor signature + ToD; may confuse with washer motor |
| "Heating appliance" (iron/kettle/heater) | F1 ≈ 0.8 as a class, not individually | identical resistive steps |
| Mixer-grinder | F1 ≈ 0.7 | short bursts; universal-motor harmonics |
| Inverter AC/fridge | energy envelope + start/stop only | continuously variable |
| Fans, LEDs, TV, router | pooled "fans & lights" / "always-on" kWh, **not individually** | industry-wide limit |
| Total energy split | ≥ 95 % of kWh assigned to some bucket | reconciliation |
State to the judge: identification is probabilistic; the product shows confidence badges, asks before it asserts, and never reports individual loads under ~40 W.

## 6. Outputs
1. **Per-appliance kWh/day and /month** with an "other/always-on" residual; per-circuit split when both CTs exist.
2. **Cost with ToD tariff**: Electricity (Rights of Consumers) Amendment Rules 2023 — ToD for domestic smart-meter consumers from 1 Apr 2025 (solar hours ≥ 20 % cheaper, peak ≥ 10–20 % dearer); TANGEDCO peak 06–10 & 18–22 (+25 %), night 22–05 (−5 %). Cost = Σ kWh_slot × rate_slot; directional coaching ("geyser at 13:00 instead of 07:00 saves ₹X/month").
3. **Backup-mode coaching**: "3 fans + TV + router = 320 W → ~2 h 10 min left; switching off the TV adds 35 min" — uses E_usable from 05 §4.1.
4. **Anomalies** (14-day EWMA baseline, alert when 3-day mean exceeds): fridge duty > 1.4× or period shortening ("check door seal/thermostat"); fridge ON > 2 h continuously; geyser > 45 min or odd hours; pump > 2× median (overflow/dry run); fixed AC short-cycling < 5 min; night always-on +30 % (phantom load); sustained Vrms < 200 / > 250 V during events ("motor loads at risk" — ties to Grid Shield).
5. **Confidence**: Confirmed / Likely / Unknown per row; unknown clusters generate the prompts of §4.2.

## 7. Verify before quoting
ADE7953 LINECYC mode if cited; ATM90E36A THD/DFT register specifics if harmonic features are claimed; INR pricing for ADE7953/ADS131M04 from an Indian distributor.

## References
Hart, Proc. IEEE 80(12), 1992 · Zoha et al., Sensors 2012 · Faustine et al. 2017 (arXiv:1703.00785) · Angelis et al., Energy & Buildings 2022 · Wójcik et al., Sensors 2019 · Lu & Li (arXiv:1903.09180) · Anderson et al., BLUED, SustKDD 2012 · Arfa & Shoab, FIT 2018 · Kaddour et al. (arXiv:2402.17809) · Tabanelli et al., IEEE TII 2021 (arXiv:2105.10302) · Wu et al. 2026 (arXiv:2608.18780) · Völker et al., Springer 2022 · Gerasimov et al. (arXiv:2501.16841) · Applied Energy 2024 (online robust NILM on edge) · Kelly & Knottenbelt, Neural NILM 2015; UK-DALE · Zhang et al., seq2point, AAAI 2018 · Kolter & Johnson, REDD 2011 · Batra et al., iAWE, BuildSys 2013; NILMTK, e-Energy 2014 · Petralia et al., e-Energy 2023 · Brito et al., IET Smart Grid 2021 · Microchip ATM90E32AS / ATM90E36A datasheets; ADI ADE7953, ADE9153A; TI ADS131M04 · Espressif ADC performance blog; ESP32-S3 datasheet · CircuitSetup Split-Single-Phase meter; ESPHome atm90e32 · MDPI Sensors 25(15):4601 (ATM90E36A + ESP32 harmonic dataset) · Smappee support; EcoWatch Sense review · PIB 2023 ToD rules; TNERC ToD · Bajaj Finserv / Nice Power appliance charts; nooutage.com inrush; EcoFlow LRA; LED THD survey · V-Guard Prime 1575 compatible-load list.
