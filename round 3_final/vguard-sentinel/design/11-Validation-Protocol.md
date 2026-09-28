# 11 — Validation Protocol and Prototype Stack (worked out to a T)

**Resolves Gap Register:** H31 (metric definitions), H32 (prototype stack), H38 (Flower simulation — with 08 §B5). Turns the report's §11 "success criteria" into definitions a judge can check.

## 1. Metric definitions
### 1.1 SoC (Engine 1a, doc 01)
- **Reference**: cycler-integrated Ah (0.1 % class) from a known full-charge anchor, Peukert/temperature-corrected to the same C_usable definition.
- **SoC error** = SoC_EKF − SoC_ref, sampled every 60 s over ≥ 7 days per test battery at 27/40 °C on the campaign duty (partial cycles, no reference anchors given to the EKF).
- **Pass**: RMS ≤ 3 %, |max| ≤ 5 % between natural anchor events; drift between anchors ≤ 2 %/week; zero false full-detections (SoC set to 100 % while cycler shows < 97 %).
- **Anchor test**: inject a 5 % SoC bias; measure time-to-recovery after (a) a full-charge taper, (b) a 90-min rest, (c) a 6-h rest — expect (a) and (c) < 2 %, (b) provisional pull-in only.
### 1.2 SoH / RUL (Engine 1b, doc 02) — evaluated on held-out batteries, GroupKFold by battery
| Metric | Definition | Target |
|---|---|---|
| SoH MAE / RMSE | mean and RMS of |SoH_P50 − SoH_true| (points), ground truth interpolated from 25-cycle reference C10 tests | MAE ≤ 3 pt after campaign; 4–5 pt in the first field season |
| RUL point error | |RUL_P50 − RUL_true| / RUL_true at SoH checkpoints 95/90/85 % | ≤ 25 % at 90 %, ≤ 15 % at 85 % |
| **RUL-window hit-rate** | fraction of (battery, checkpoint) pairs with EoL_true ∈ [k + RUL_P10, k + RUL_P90] | ≥ 75 % at nominal 80 % (conformal guarantees ≈ 80 % on exchangeable cells; the gap is condition shift) |
| Calibration | PICP at nominal 50/80 %; PICE = |PICP − nominal|; MPIW normalised by RUL_true | PICE ≤ 5 pt; NMPIW ≤ 0.8 at SoH 90 % |
| Warning lead time | cycles (→ weeks at field usage rate) from first persistent "Replace" grade to EoL_true; median and P10 | median ≥ 8 wk, P10 ≥ 4 wk |
| False alarm / miss | Replace grade with RUL_true > 26 wk / EoL reached with < 4 wk of Replace | ≤ 10 % each (sudden shorts scored under the anomaly detector) |
| Anomaly detector | detection rate on fault units ≥ 5 cycles before terminal event; false positives per 1,000 healthy cycles | 3/3 detected; < 1 FP/1,000 |
| Quantised vs float | ΔMAE, ΔPICP | ≤ 0.3 pt, ≤ 2 % |
| On-device latency | inference time on ESP32-S3 with ESP-NN, 3 seeds | ≤ 50 ms (expect 3–30 ms) |
### 1.3 Autopilot / load prioritisation (Engine 2, doc 05)
- **Load-shed correctness** (hardware-in-the-loop bench: programmable AC source, 4 contactors, load bank, battery simulator): for a scripted outage library (50 scenarios: varying SoC, load mix, durations), count (a) T1 ever de-energised while E_avail > 0 → must be 0; (b) T3 shed exactly when SoC ≤ 40 % and restored at ≥ 55 % (±1 %); (c) dwell violations (compressor channel switched < 3 min after last switch) → 0; (d) chatter (> 2 transitions/channel/10 min) → 0.
- **Fail-safe**: pull MCU reset / cut logic power / stall the heartbeat during a shed → all NC contacts close within 2 s in 100/100 trials.
- **Backup extension** (the report's "+20–30 %" claim): same scenario with and without Sentinel policy; metric = time until T1 loses power. Report the measured ratio.
- **Outage forecast**: on ≥ 8 weeks of field logs from the 6 home units: Brier score of P(outage, 3 h) vs a climatological baseline; reliability diagram; **must beat the baseline** or the pre-charge feature ships as advisory-only.
- **Outage detection**: 2-of-3 latency ≤ 2 s; false declarations on the IEC 61000-4-11 sag/dip test set = 0; missed declarations = 0.
### 1.4 NILM (Engine 3a, doc 06)
- Offline on **iAWE** (Indian, 1 Hz, P/Q available) and UK-DALE: per-appliance F1 (event-level, ±30 s tolerance) and energy-assignment error (|kWh_assigned − kWh_true| / kWh_true per day) for fridge, AC, geyser-class, pump-class, "heating" class.
- Bench: ≥ 10 labelled Indian appliances on a programmable switching rig, 200 events each, plus overlapping pairs.
- Field: 6 home units, user labels as truth after 4 weeks.
- **Targets**: as 06 §5.3 (fridge/AC/geyser F1 ≥ 0.85; total kWh assigned ≥ 95 %).
### 1.5 Grid Shield (Engine 3b, doc 07)
Programmable AC source per **IEC 61000-4-11** (dips 70/40/0 % for 0.5–250 cycles, interruptions) and IEC 61000-4-13 harmonics: event detection rate ≥ 99 % for dips ≥ 1 cycle; magnitude error ≤ 2 % of nominal; duration error ≤ 1 half-cycle; THD within ±1 pt of a reference PQ analyser (Class-S-like, not Class-A).
### 1.6 Fleet learning (doc 08)
- **Central**: ingest rejects 100 % of bad-CRC/replayed records in a fuzz set; retraining reproducible from a dataset hash (bit-identical metrics).
- **Federated vs central**: on the Flower simulation (08 §B5, 5/20/50 clients, non-IID): accuracy of the federated NILM prior model vs the central model on the held-out low-connectivity panel, at ε ∈ {4, 8, ∞}; report the ε-vs-accuracy curve honestly. Dropout test: 30 % of clients disconnect mid-round → round completes via SecAgg+ reconstruction.
- **Privacy**: ε, δ from the RDP accountant on the final config; k-anonymity check on every published aggregate (no cell < 20).
### 1.7 System
- **Power**: measured average battery-side current in each mode (idle / NILM-on / outage / shedding) vs 10 §5 — within ×1.5 of the proposal.
- **Security**: Secure Boot + flash encryption enabled; an unsigned image refused; a downgraded image refused; health-log chain with one altered byte fails verification.
- **EMC pre-compliance**: IEC 61000-4-2 L4, -4-4, -4-5 L3 on a pre-compliance bench before BIS submission.

## 2. Prototype stack (H32) — what is actually built for Phase 4 / finale
| Layer | Build |
|---|---|
| Hardware | ESP32-S3-DevKitC-1 (N16R8) + INA228 breakout on a 0.1 mΩ Kelvin shunt + 10 k NTC + ATM90E32AS board (CircuitSetup 6-channel or equivalent) with SCT-013 CT + 12 V transformer tap + ULN2003 board driving 4 × 12 V DC NC contactors/relays + DS3231 + (optional) ATECC608 breakout; bench 12 V 100–150 Ah tubular battery and a 600–900 VA inverter |
| Firmware | ESP-IDF 5.x; FreeRTOS tasks: `sense_1hz` (INA228/NTC), `ekf` (01), `features+inference` (02, esp-tflite-micro + ESP-NN), `afe_3hz` + `nilm` (06), `pq` (07, ESP-DSP FFT on AMC1311/ADC path), `autopilot` (05), `telemetry` (08, MQTT/TLS), `ota`, `healthlog`; LittleFS data partition; NVS config |
| Models | SoH/RUL CNN trained on Li-ion pre-train + synthetic bridge (Stage A+B; Stage C waits for the campaign — say so); anomaly AE; NILM priors from iAWE + bench |
| Cloud | MQTT broker (Mosquitto/EMQX) → Python ingest → Parquet/DVC → training notebooks → model registry → OTA server; Flower server + simulation |
| App | Flutter/React-Native: SoH window, RUL "replace within N weeks", circuit map config, override with countdown, Energy Coach with confidence badges and "what just turned on?", PQ log, warranty claim button (uploads signed chain) |
| Demo | live bench: scripted outage → 2-of-3 detection → T3 shed at 40 % → MCU reset → all loads restore (fail-safe); NILM: switch a fridge, iron, mixer → events labelled live; Flower: 5 simulated homes converging with DP on |
Honest labelling in the demo: Stage-C-trained SoH numbers are not available until the campaign; the demo shows the pipeline running on synthetic/Li-ion-transferred weights with the conformal band visibly wide.

## 3. Validation gates (the report's roadmap, made testable)
| Gate | Criterion | Evidence |
|---|---|---|
| G1 Dataset acceptance | 04 §4 | campaign report, dataset hash |
| G2 Field pilot | 100 units × 6 months: SoC RMS ≤ 3 % on units with reference shunts; ≥ 75 % RUL-window hit-rate on units that reach EoL; 0 unsafe sheds; NILM fridge/AC F1 ≥ 0.8 on labelled homes; < 1 % OTA failures; power within budget | pilot dashboard (k ≥ 20 cells) |
| G3 Learning stability | 3 consecutive model releases with no metric regression on the golden slice; federated model ≥ central on the held-out panel at ε ≤ 8 | registry metrics |
