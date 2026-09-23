# Research Notes — Battery SoH/RUL (deeply cited, honesty-flagged)

## Degradation physics & measurable signals
- **EoL convention = 80% of rated capacity** (PVEducation).
- **Lead-acid (tubular/VRLA)** — Ruetschi, J. Power Sources 127 (2004); Vetter (Li) 147 (2005).
  - Irreversible **sulphation** (chronic undercharge/deep discharge) → ↑R_int, ↓charge-acceptance, depressed load voltage, slow OCV recovery.
  - **Positive-grid corrosion** (float/EoL, heat+overcharge) → ↑ohmic R, eventual open-circuit ("sudden death").
  - **Water loss/dry-out** (VRLA can't refill) → ↑R, ↓cap, ↑temp.
  - **PAM shedding** (deep-DoD); tubular gauntlet design retains PAM = why tubular is the Indian standard.
  - **Acid stratification** (tall cells, undercharge) → charge-acceptance can fall ~50-70% within months; fixed by periodic equalisation/boost.
- **Li-ion:** SEI growth (√t, loss of Li inventory) = main capacity fade; Li plating (cold + fast charge — the reverse of India's problem); power fade = R/DCIR/EIS growth; two-stage "knee" trajectory.
- **Arrhenius (MOST important for India):** lead-acid life **≈ halves per +10 °C above 25 °C** (BU-806a). 10-yr@25°C VRLA → ~5 yr@33°C → ~2.5 yr@41°C. Temperature is the dominant India stressor.
- **Signal→mechanism:** R_int rise (corrosion/dry-out/SEI/power-fade); voltage-sag-under-load (sulphation/R); **charge-acceptance decline (cheap, high-info lead-acid signal — sulphation/stratification)**; coulombic-eff <1 (SEI/plating/gassing); temp (Arrhenius + anomaly); Ah-throughput + DoD-histogram (cumulative stress). No single signal is diagnostic — need the combination.
- Cycle life vs DoD: ~200 (shallow SLI) to 1,500–2,000 (premium tubular/gel @80% DoD); 50% vs 80–100% DoD ≈ 2–3× life.

## Methods & accuracy
- **Coulomb counting** drifts (open-loop integration of sensor bias): ±0.5% current bias → ~2–5% SoC drift/week. Mitigate: OCV re-anchor at full/empty (inverters float near-full between outages → frequent recalibration). 
- **OCV:** lead-acid has usably sloped OCV (~2.1→1.95 V/cell) → anchoring works; LFP flat plateau makes OCV nearly useless 20–80%.
- **EKF/UKF + equivalent-circuit model** = mainstream; SoC RMSE ~0.3–1.6% (~1% typical); runs on fixed-point MCUs. Use EKF+ECM for SoC, ML for SoH/RUL.
- **EIS** = richest SoH probe but hardware-heavy → use single/few-frequency impedance or **DC-pulse DCIR** on-device.
- **ML accuracy (Li-ion, benchmarked):** LSTM SoH RMSE ~2.14% (NASA), ~1.90% (CALCE); MLP/TCN can match GRU/LSTM (~0.69%); hybrid GRU/Transformer <0.83% (NASA)/<0.61% (CALCE). **Lab numbers; field + on-device-quantized worse (~5%).**
- **Lead-acid ML is thin** (NN MAE ~0.175 SoC; GRU SoC MAE 0.64%); no canonical benchmark.
- **Top features:** ICA/DVA (dQ/dV, dV/dQ) peaks; **partial charge-curve segments (esp. partial CC charge after an outage — most practical feature source)**; R_int/DCIR; charge-acceptance/charge-time stats; temp + Ah + DoD histogram covariates.

## Datasets
- Li-ion: **NASA PCoE (B0005-18)** — the RUL benchmark; **NASA Randomized ("Ames")** — random-walk current, closest to erratic inverter loading; **CALCE**; **Oxford Degradation**; **Sandia (temp×DoD×rate — most India-relevant)**; **Severson (124 LFP, early-life RUL gold standard)**. Aggregators: batteryarchive.org, BatteryML.
- **CRITICAL GAP: no canonical open lead-acid cycling dataset exists.** Must collect own tubular aging data (partial charge curves, DCIR, charge-acceptance, T, Ah, DoD). Use Li-ion open data for architecture/feature prototyping + **transfer learning** only, not direct parameter reuse.

## On-MCU (TinyML) feasibility
- TFLM ~22 KB (real model) to ~40–80 KB total; int8 ≈4× smaller. CMSIS-NN ~4.6× runtime / 4.9× energy.
- Anchor results: UAV LiPo RUL int8 FFNN on **RP2040 (M0+): 11 KB flash, 1.2 KB RAM, 2 ms, RUL MAE 3.46 cyc** (Sensors 2024). On-MCU battery states on ESP32: best tiny ~3.4 KB/1.6 ms; **CNN-GRU RMSE ~4.88%** (J. Energy Storage 2026).
- Prefer small 1D-CNN/FFNN on engineered features (GRU/LSTM feasible at tens of KB; RF compiles tiny via emlearn).
- **Compute is NOT the constraint — sensing offset/shunt quality + training data are.** SoH updates once per cycle/charge/hour (latency irrelevant).

## Sensing specs
- Current ADC: Δ-Σ, ~15–16-bit effective, LSB ~3 µV, offset ~10 µV; **offset (bias) dominates drift, not bit-depth** → periodic auto-zero at true-zero-current.
- Shunt: ~2 mΩ (1–10), ≤50 ppm/°C, ≤0.5–1% tol, 4-terminal Kelvin.
- Voltage: ±1 mV (LFP flat) / ±5–10 mV (lead-acid/NMC sloped).
- Temp: ±1–2 °C per-battery. Sampling: 1–10 Hz current integration.
- Reference ICs: TI bq34z100-G1 / BQ34110 / BQ35100; INA226/228/238; ADI ModelGauge.

## Prediction lead-time (honest)
- Severson: predict life from **first 100 cycles at 9.1% error**; classify short/long from first 5 cycles at 4.9% (lab, controlled, LFP).
- **Hard limits:** the "knee" is a fundamental barrier; path dependence (future usage unknown); NOT predictable = internal shorts, corrosion open-circuit, thermal runaway → **advertise degradation-trend warning, NOT safety-event prediction**; lead-acid more conservative (gradual modes = weeks-to-months warning via IR/cap trend; sudden-death = little/no warning).
- **Defensible framing: report SoH with an uncertainty band; graded early warning ("healthy / degrading / replace within N weeks") months ahead for gradual wear + anomaly flags for fast faults — NOT a precise "X days remaining" gauge.**

Sources: NASA PCoE; CALCE; Oxford ORA; batteryarchive.org (Sandia); Nature Energy 2019 (Severson); Ruetschi JPS 2004; Vetter JPS 2005; Battery University BU-804/806a; TFLM arXiv 2010.08678; Sensors 2024 (PMC12196908); TI bq34z100-G1 datasheet.
