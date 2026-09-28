# 01 — Engine 1a: Battery State Estimation (SoC / R_int / re-anchoring) — worked out to a T

**Resolves Gap Register:** H1 (EKF unspecified), H2 (coulomb drift & re-anchor), H3 (R_int from transients), H30 (float ≠ OCV technical error), H37 (coulombic efficiency).

Hardware assumed: ESP32-S3 + INA228 on an external 500 A / 50 mV (0.1 mΩ) busbar shunt, NTC on the battery terminal, 12 V tubular flooded lead-acid 100–230 Ah, 1 Hz estimator loop. See 10 for the interfaces.

## 0. The one real bug in the submitted report (H30)
The report says SoC is anchored to the OCV table "during float-rest". **Float is not rest.** Under float/absorption the charger drives current into the battery, so terminal voltage = OCV + I·R0 + V_pol, not OCV. Looking that voltage up in an OCV table **systematically over-reports SoC**, and it looks convincing because the voltage is steady (it is steady because it is being regulated, not because current is zero). The fix (§5) splits anchoring into two non-interchangeable mechanisms: **full detection by charge-current taper** (charger ON) and **true rest-OCV** (charger verifiably OFF).

## 1. Battery model — 1-RC Thevenin
### 1.1 Why 1-RC, not 2-RC
Li-ion BMS work uses 2-RC because Li-ion has two well-separated time constants. Lead-acid's slow dynamics (diffusion, gassing, stratification) are nonlinear and not well captured by a second linear RC; identifying two time constants from noisy natural transients on one shunt+voltage pair is poorly conditioned. **Baseline: 1-RC.** A very slow second branch (τ ~ tens of minutes) is a Phase-2 option only if bench data shows post-transient voltage creep matters for the ±5 % target.

### 1.2 State vector
```
x = [ SoC , V1 , R0 ]ᵀ
```
- SoC: fraction of usable capacity.
- V1: polarisation voltage across R1‖C1.
- R0: ohmic resistance **as a slowly-varying state**, not a constant — R0 moves ≈+40 % from full to empty and ≈+50 % from +30 °C to −18 °C (Battery University), and rises with sulphation/grid corrosion. A fixed R0 is wrong most of the year in India (10–45 °C ambient, hotter in the enclosure). Tracking it also yields the resistance-based SoH proxy for free (§6).
- R1, C1 are **table-driven parameters** (functions of SoC, T from the bench), not states — adding them as states is what makes 4-state lead-acid EKFs unobservable on one sensor pair (Plett's practice: identify R1/C1 offline, filter SoC and R0 online).

### 1.3 Discrete-time equations, Δt = 1 s (I > 0 discharge, I < 0 charge)
```
SoC_{k+1} = SoC_k − η(I_k)·I_k·Δt / Q_usable(T_k, I_k)             + w_SoC
V1_{k+1}  = V1_k·exp(−Δt/τ) + R1·(1 − exp(−Δt/τ))·I_k              + w_V1     (τ = R1·C1, exact ZOH — not Euler)
R0_{k+1}  = R0_k                                                    + w_R0     (random walk, noise gated to transient events)
η(I) = 1.0 on discharge;  η_charge(SoC,T) on charge: ≈0.98 below 70 % SoC tapering to 0.70–0.85 above 90 % (gassing)
```
Q_usable = Q_rated(C20) · f_temp(T) · Peukert multiplier (§2.5).

### 1.4 Measurement equation
```
V_term,k = OCV(SoC_k, T_k) − I_k·R0_k − V1_k + v_k
```
OCV(SoC,T) is the only nonlinearity — hence EKF, linearised each step via dOCV/dSoC.

### 1.5 Typical parameters — 150 Ah tubular, 25 °C, fresh, mid-SoC (**characterise-in-lab; do not ship these as truth**)
| Parameter | Value | Note |
|---|---|---|
| R0 | 3–6 mΩ | R0 ≈ k/C_Ah, k ≈ 0.6–1.2 Ω·Ah for flooded; +40 % empty, +50 % cold |
| R1 | 2–5 mΩ | same order as R0; rises sharply < 20 % SoC |
| C1 | 2,000–8,000 F | chosen so τ lands in 20–120 s |
| τ | 20–120 s | fast branch; surface-charge decay is a separate, hours-long process (§5b) |
| Full rest OCV | 12.65–12.70 V | §2 |
| Peukert n | 1.2–1.3 (default 1.25) | §2.5 |
Open-literature Thevenin tables for **tubular** plates (Exide/Amaron/Luminous class) essentially do not exist — most papers use SLI flat-plate automotive batteries. This is exactly what the aging campaign (04) must produce.

### 1.6 How to obtain R0/R1/τ — HPPC adapted to lead-acid
At ~8–10 SoC points (100…10 %) × 3 temperatures (0/25/45 °C, climate chamber): C/5 pulse 10 s discharge, rest 40 min, C/5 pulse 10 s charge, rest 40 min. R0 from the instantaneous step; R1/C1 from the exponential relaxation over the next 60–120 s. Output = the 2-D (SoC×T) tables the firmware needs.

## 2. OCV–SoC curve
### 2.1 Table (25 °C, rest)
BCI reference (Battery University BU-903, 24 h rest, 26 °C): 100 % 12.65 · 75 % 12.45 · 50 % 12.24 · 25 % 12.06 · 0 % 11.89 V (SLI). Working default for tubular deep-cycle (higher SG, ≈12.70 V full):
| SoC | 100 | 90 | 75 | 50 | 25 | 10 | 0 % |
|---|---|---|---|---|---|---|---|
| OCV | 12.70 | 12.60 | 12.50 | 12.30 | 12.05 | 11.90 | 11.80 V |
The curve is **flattest at 30–70 % SoC** — a few mV of error maps to many % SoC there. This is why coulomb counting carries the mid-range and OCV is used only at rest and near the knees.

### 2.2 Temperature coefficient
≈ −3 to −4 mV/°C per 12 V battery (−0.5 to −0.7 mV/°C/cell) referenced to 25 °C, as calibration-day fallback only. **Ship a 2-D OCV(SoC,T) table** built from the 0/25/45 °C rest characterisation and bilinearly interpolate — avoids ever fitting the coefficient.

### 2.3 Hysteresis
Rest OCV after charging sits tens of mV above rest OCV after discharging at the same SoC, decaying with rest (surface charge; lead dioxide electrode may take up to 24 h, lead electrode ≤1 h — BU-804c). **Decision rule from the bench:** if separation > ~20 mV at matched SoC and rest time, store two curves (charge-direction / discharge-direction) and select by direction of last significant current; otherwise one curve plus a rest-time-dependent decay correction. Either way, never trust OCV below the rest thresholds in §5b — that error dominates.

### 2.4 Storage
11 SoC × 3 T × (1–2 curves) float32 = 33–66 entries ≈ 130–260 B. Model-ID → LUT-pointer table so one firmware supports every battery SKU V-Guard sells, selected at commissioning.

### 2.5 Capacity vs temperature and Peukert
- f_temp(T): from the SKU datasheet (≈100 % at 25 °C, mid-80s % at 0 °C). India's heat side is handled via the R0/SoH path, not capacity derating.
- Peukert (Victron SmartShunt default n = 1.25, lead-acid; adjustable 1.00–1.50):
```
Q_usable(I) = Q_rated(C20) · (I20/|I|)^(n−1)   for |I| > I20, multiplier clamped ≥ 0.5–0.6
```
Applied as a running effective-capacity correction in the coulomb-count denominator. Bites during mains-fail transfer with inrush/multiple loads — exactly when SoC accuracy matters most.

## 3. Extended Kalman Filter
### 3.1 Jacobians
```
F = [[1, 0, 0], [0, exp(−Δt/τ), 0], [0, 0, 1]]
H = [ ∂OCV/∂SoC |_(SoĈ,T̂) ,  −1 ,  −I_k ]
```
∂OCV/∂SoC from finite difference on the LUT (or analytic spline slope). It is small mid-range and steep at the knees, so the Kalman gain is naturally weak mid-range and strong near empty/full — physically correct, not a defect. ∂/∂R0 = −I_k is ≈0 at rest, which is precisely why R0 is updated from transient events (§6) rather than every tick.

### 3.2 Noise tuning
- **R (measurement):** INA228 VBUS channel with ≥16–64× averaging inside the 1 s window → sub-mV RMS; start at **σ_v = 2–5 mV** (R = (2–5 mV)²) to cover harness/connector noise; raise if the bench shows more.
- **Q_SoC:** from the current-channel error (§4): ≈ (1e-5 … 1e-4)² per step — small, because the counter is trusted between corrections.
- **Q_V1:** (5–15 mV)² per step — the single-exponential RC is an approximation.
- **Q_R0:** two regimes — ≈1e-10 on ordinary ticks (no random drift); inflated to (0.5 mΩ)² for the single update following a qualifying ΔI transient, then closed. This makes "R0 as a state" and "R0 from natural transients" **one mechanism**, not two estimators.

### 3.3 Initialisation
1. Prefer the **persisted state** (SoC, V1≈0, R0, P) from NVS, saved every 5–10 min and on clean shutdown — avoids re-anchoring to a stale under-load OCV reading on every power cycle.
2. Else, if §5b rest criteria currently hold: SoC₀ = OCV⁻¹(V, T).
3. Else: SoC₀ = 50 % with σ_SoC0 ≈ 20 % (humble; converges at the first anchor event). P₀(R0): LUT nominal ± 30 %.

### 3.4 Divergence guards (lead-acid EKFs diverge silently because the OCV curve is flat)
1. **Innovation gating:** reject/down-weight an update if y²/S > 9 (≈3σ) — a glitchy sample cannot corrupt the state.
2. **Hard bounds:** SoC ∈ [0,1]; R0 ∈ [1, 50] mΩ; Joseph-form or symmetrise + eigenvalue floor on P.
3. **Covariance floor and ceiling.**
4. **Raw-counter cross-check:** keep the pure coulomb-count SoC alongside; if fused vs raw diverge > 8–10 % for minutes without an anchor → log a fault, widen Q_SoC.
5. **R0 sanity:** a transient-derived R0 > 3× the LUT envelope is a misclassified charger transition — discard.

### 3.5 Float vs fixed-point
ESP32-S3 has a hardware single-precision FPU. One scalar measurement → the "matrix inverse" is a scalar division; the 3×3 update is microseconds at 1 Hz. **Float32 throughout; no fixed-point needed.**

## 4. Coulomb-counting error budget (INA228 datasheet + 0.1 mΩ shunt)
| Source | Spec | Equivalent |
|---|---|---|
| INA228 offset | ±1 µV max, ±0.01 µV/°C | **I_os = 1 µV / 0.1 mΩ = 10 mA bias** (integrates linearly) |
| INA228 gain | ±0.05 %, ±20 ppm/°C | multiplicative, minor |
| Shunt tolerance / tempco | ±0.5 %, ±50 ppm/°C | multiplicative: 25–75 mA at 5–15 A loads; ≈0 at idle |

**Idle-bias drift:** 10 mA × 604,800 s = 1.68 Ah/week → **≈1.1 % SoC/week** on 150 Ah, uncorrected.
**Active-duty gain drift:** 140 Ah/week moved × 0.5 % = 0.7 Ah → **≈0.47 %/week**; tempco adds < 0.1 %/week.
**Combined worst case ≈ 1.5–2 % SoC/week** before re-anchoring. The ±5 % claim is therefore **not** met by counting alone over long stretches — it is met by a low-drift counter **plus re-anchoring at least ~weekly**, which Indian duty cycles supply naturally (daily-to-weekly outages → rest periods; mains return → full-charge taper most days). This is the same "synchronisation" mechanism Victron's BMV/SmartShunt documents.
**Zero-current auto-calibration:** whenever I≈0 is independently known (charger relay open AND no load, or flat terminal voltage for seconds), refresh a stored offset correction → residual bias falls to the tempco term (≈0.1 mA/°C). Cheap and mandatory.

## 5. Re-anchoring — the corrected logic
### 5a. FULL detection (charger ON) → SoC := 100 %, **not** via the OCV table
Modelled on Victron BMV/SmartShunt "synchronisation": charged-voltage AND tail-current AND detection-time.
| Condition | Threshold |
|---|---|
| V_term | ≥ ~13.5 V (12 V flooded, 25 °C), temperature-compensated ≈ −24 mV/°C per 12 V (use the charger's own coefficient if we control it) |
| I_charge | tapers below **1–2 % of C20** (75–150 mA for 150 Ah, C20 = 7.5 A) |
| Dwell | both true continuously for **10–30 min** (rejects momentary load-off dips) |
Action: SoC = 1.0; collapse P_SoC; close out the cycle and compute η and measured capacity (§7); lock the trigger until the next discharge.

### 5b. TRUE rest-OCV anchor — only when the charger is verifiably OFF
All required simultaneously:
1. **Charger off — hard evidence** (charger-state GPIO / relay status on the embedded SKU; on retrofit, "grid known absent" is the proxy). *This single guard is the fix for H30.*
2. |I| ≤ **0.5–1 % of C20** (≈40–75 mA for 150 Ah) — parasitic draw allowed, not zero.
3. Rest duration, **two-tier confidence** (full 24 h is never available in service):
   - **≥ 60–90 min → provisional**: feed the LUT value into the EKF as a measurement with **medium** R (residual +10–30 mV hysteresis possible).
   - **≥ 4–6 h (ideally an overnight outage, 8–12 h) → high-confidence**: same update with **small** R → near-direct set, P_SoC collapses. (BU-903 cites 4 h as the practical minimum.)
4. Temperature-compensated lookup at T_batt.
Implemented as an **EKF measurement update with R scaled by rest time**, not a hard if/else override — lets the filter blend.

### 5c. Summary thresholds
| Item | Value |
|---|---|
| Charger state for rest anchor | OFF (direct signal preferred) |
| I_rest | ≤ 0.5–1 % C20 |
| t_rest provisional / high-confidence | ≥ 60–90 min / ≥ 4–6 h |
| V_full (12 V, temp-comp.) | ≥ ~13.5 V |
| I_tail | < 1–2 % C20 |
| T_full dwell | 10–30 min |

## 6. Internal resistance from natural transients
### 6.1 Event detection
- Trigger: |ΔI| ≥ **5–10 % of C20** (0.4–0.75 A for 150 Ah) between consecutive samples — a fridge compressor, fan bank, or mains-fail load transfer.
- R_meas = (V_before − V_after)/(I_after − I_before).
- **Honest 1 Hz limitation:** the true ohmic window (hundreds of µs to ~1–2 ms) is not resolvable at 1 Hz; what is measured is R0 + the fraction of R1 that builds in the first second ≈ 1−exp(−1/τ) ≈ 1–5 % of the R1 step for τ = 20–120 s — a small, pessimistic bias.
- **Refinement (recommended, no new sensors):** keep INA228 in continuous mode at a fast conversion time (down to 50 µs) and on a step edge (fast poll or ALERT pin) capture a **20–50-sample burst over 200–500 ms** purely for the R0 fit; keep 1 Hz for logging. This cleanly separates the ohmic step from the RC rise.
- **Reject** any event coincident with a charger transition (bulk→absorption, PWM/relay ripple), gated by the same charger-state signal as §5b.

### 6.2 Filtering and normalisation
Rolling buffer of the last 20–50 qualifying events → **median** (outlier-robust) before it may move the EKF's R0 (event-gated Q_R0). Normalise every event to 25 °C / 100 % SoC using the R0(SoC,T) LUT shape:
```
R_norm = R_meas · R0_LUT(100 %, 25 °C) / R0_LUT(SoC_now, T_now)
```
so events at arbitrary household conditions feed one comparable trend.

### 6.3 SoH proxy
```
SoH_R(t) = R0_new / R0_norm(t)      (1.0 = as-new)
```
Combine with the capacity proxy (§7). Two independent signals converging on one SoH number is far more defensible than either alone; the TinyML model (02) consumes both.

### 6.4 Cooperative charger pulse (Phase 2, embedded SKU)
Where the charger is commandable, inject a controlled ΔI for 1–2 s during bulk with margin → clean on-demand R0 — a field HPPC pulse. Not a v1 claim.

## 7. Coulombic efficiency and measured capacity per cycle
At each full-detection event (a natural cycle boundary):
```
Ah_out = Σ I·Δt (I>0) / 3600 ;  Ah_in = Σ |I|·Δt (I<0) / 3600
η_measured = Ah_out / Ah_in                        (≈0.85–0.98; ~85 % Ah / ~70 % Wh over the full range)
Capacity_measured = Ah_out delivered between the SoC=100 % anchor and the start of recharge
SoH_capacity = Capacity_measured / Capacity_BoL
```
Only count cycles with DoD ≥ 30 % toward the capacity trend; median/EMA across cycles. Capacity, tail current and efficiency all drift with age — commercial monitors already treat them as tracked, not nameplate, quantities.

## 8. Consolidated parameter table
| Parameter | Value | § |
|---|---|---|
| Loop rate | 1 Hz (+ burst capture on transients) | — |
| Shunt | 500 A/50 mV, 0.1 mΩ, ±0.5 %, ±50 ppm/°C | 4 |
| INA228 offset / gain | ±1 µV, ±0.01 µV/°C / ±0.05 %, ±20 ppm/°C | 4 |
| I_os equivalent | ~10 mA pre-cal | 4 |
| Peukert n | 1.25 default (1.2–1.3) | 2.5 |
| OCV full / empty (25 °C) | 12.70 / 11.80 V | 2.1 |
| OCV temp coef. | −3 to −4 mV/°C per 12 V | 2.2 |
| R0 / R1 / τ (fresh) | 3–6 mΩ / 2–5 mΩ / 20–120 s (characterise) | 1.5 |
| η_charge | 0.85–0.98, SoC-dependent | 1.3 |
| V_full / I_tail / T_full | ≥13.5 V / 1–2 % C20 / 10–30 min | 5a |
| I_rest / t_rest | 0.5–1 % C20 / 60–90 min, 4–6 h | 5b |
| ΔI_thresh | 5–10 % C20 | 6.1 |
| R0 median window | 20–50 events | 6.2 |
| χ² gate | 9 | 3.4 |
| R / Q_SoC / Q_V1 / Q_R0 | (2–5 mV)² / (1e-5–1e-4)² / (5–15 mV)² / 1e-10 ↔ (0.5 mΩ)² | 3.2 |
| Min DoD for capacity cycle | 30 % | 7 |

## 9. 1 Hz loop pseudocode
```c
void sentinel_1hz_tick(void) {
  float I_raw = ina228_current();  float V = ina228_bus_voltage();  float T = ntc_temp();
  bool chgr_on = charger_status();                       // hard signal (embedded) or grid-absent proxy (retrofit)
  float I = correct_offset_gain(I_raw);
  burst_capture_hook(I, V);                              // arms 20–50-sample fast burst on a step edge
  // predict
  float Qu = usable_capacity(T, I);  float eta = (I >= 0) ? 1.0f : eta_charge_lut(x.SoC, T);
  ekf_predict(&x, &P, I, eta, Qu, T);
  // correct (innovation-gated)
  float innov = V - (ocv_lut(x.SoC, T) - I*x.R0 - x.V1);
  float H[3] = { docv_dsoc(x.SoC, T), -1.0f, -I };  float S = HPHt(H, P) + R_ekf;
  if (innov*innov / S < 9.0f) { ekf_correct(&x, &P, innov, H, S); repair_cov(&P); } else log_reject(innov, S);
  clamp_state(&x);
  // full detection (charger ON, taper)
  if (chgr_on && V >= v_full(T) && fabsf(I) < i_tail) { if (++full_t >= T_FULL && !full_locked) { close_cycle(); x.SoC = 1.0f; shrink_P_soc(&P); full_locked = true; } }
  else { full_t = 0; if (I > 0) full_locked = false; }
  // true rest OCV (charger OFF)
  rest_t = (!chgr_on && fabsf(I) < i_rest) ? rest_t + 1 : 0;
  if (rest_t >= T_REST_PROV) { float Rocv = (rest_t >= T_REST_HIGH) ? R_LOW : R_MED;
                               ekf_correct_ocv(&x, &P, V - ocv_lut(x.SoC, T), Rocv); }
  // R_int event
  if (burst_ready()) { float dI, dV; burst_deltas(&dI, &dV);
    if (fabsf(dI) >= dI_thresh && !charger_transition()) { push_median(&r0buf, normalise_r0(dV/dI, x.SoC, T));
      if (median_ready(&r0buf)) { open_Q_R0(&P); ekf_correct_r0(&x, &P, median(&r0buf)); close_Q_R0(&P); soh_r_trend(median(&r0buf)); } } }
  // accumulators, persist, log
  if (I >= 0) Ah_out += I/3600.0f; else Ah_in += -I/3600.0f;
  periodic_persist(&x, &P, Ah_in, Ah_out);  log_telemetry(x, P, I, V, T, chgr_on);
}
```

## 10. Six-step summary (judge-ready)
1. **Sense** current (INA228 on a 0.1 mΩ external shunt), voltage and terminal temperature at 1 Hz.
2. **Integrate** — coulomb count with Peukert, temperature and charge-efficiency corrections: the fast, primary SoC.
3. **Model & fuse** — 1-RC Thevenin (SoC, V1, R0) predicts terminal voltage; a 3-state EKF corrects the counter's slow drift (≈1–2 %/week from datasheet numbers).
4. **Anchor correctly** — SoC hard-set to 100 % only on charge-current taper (< 1–2 % C20 for 10–30 min at absorption/float voltage); OCV-table anchoring only with the charger verifiably off, current < 0.5–1 % C20, and rest ≥ 1 h (provisional) / ≥ 4–6 h (high confidence). Never during float.
5. **Health for free** — ΔV/ΔI from real household load steps, median-filtered and T/SoC-normalised, drives R0 and a resistance-SoH trend; Ah-in vs Ah-out between full anchors gives efficiency and measured-capacity SoH.
6. **Result** — SoC stays inside the counter's short-term drift between anchors and is pulled back to truth at every natural full-charge or true-rest event, which Indian duty cycles supply weekly or better. That, not "float-rest OCV", is how ±5 % is achievable.

## References
TI INA228 datasheet · Plett, *Extended Kalman filtering for BMS of LiPB-based HEV packs*, Parts 1–3, J. Power Sources 134(2), 2004 · Battery University BU-903 (SoC), BU-804c (stratification & surface charge), BU-808c (coulombic efficiency), *How internal resistance affects performance* · Peukert's law (Wikipedia) · Victron SmartShunt manual, *Battery capacity and Peukert exponent* · Victron Community, *What is the point of BMV synchronisation?*; *Optimise BMV SOC detection with ESS* · ScienceDirect, *Ah efficiency*.

## 11. Amendment from the prototype build (2026-09-22)
Implementing §9 literally — a per-tick voltage measurement update every second — **reintroduced the float≠OCV error through the back door**: during absorption/float the terminal voltage (13.5–14.4 V) cannot be explained by OCV(SoC) + I·R0 with a few-mΩ R0, so thousands of small, individually χ²-plausible innovations dragged SoC toward 100 %. **Rule adopted (and coded in `prototype/code/ekf/`): the generic per-tick voltage correction runs only while `charger_on == false`.** While charging, SoC relies on the coulomb counter plus the two physically gated anchors (§5a full detection, §5b rest-OCV). Measured on the synthetic 8-day duty with a 10 mA offset injected: naive counter drift ≈7 %/week; EKF RMS error ≈3 %; zero false rest anchors; R0 recovered within 5 % after 25 events; C port within 0.006 % SoC of Python. The §9 pseudocode should be read with this gate added at step "correct".
