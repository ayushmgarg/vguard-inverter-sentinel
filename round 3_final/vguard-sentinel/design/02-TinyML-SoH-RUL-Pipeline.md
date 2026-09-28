# 02 — Engine 1b: TinyML SoH / RUL Pipeline (worked out to a T)

**Resolves Gap Register:** H4 (feature computation on MCU), H5 (model black box), H6 ("replace within N weeks" logic), H8 (anomaly autoencoder), H10 (Li→Pb transfer recipe), H31 (metric definitions — see also 11).

Target: ESP32-S3 (2× Xtensa LX7 @ 240 MHz, PIE SIMD, 512 KB SRAM, 8 MB flash), INA228 on 0.1 mΩ shunt, 12 V tubular flooded lead-acid 100–230 Ah (C10), 1 Hz I/V/T, EKF (01) supplying SoC and R_int.

## 0. Definitions
- **SoH (%)** = 100 · C10,meas(27 °C) / C_rated. C10 measured at I10 to 10.5 V (1.75 V/cell), temperature-corrected to the IS reference 27 °C: C(27) = C(T)/(1 + k_T·(T−27)), k_T ≈ 0.006–0.008/°C (fit on campaign).
- **EoL** = SoH ≤ 80 % (how Exide/Luminous rate "1,200–1,500 cycles @ 80 % DoD" and how NASA/CALCE/Sandia define Li-ion EoL).
- **Cycle** = one discharge event (outage) with Q_dis ≥ 0.02·C_rated, plus the recharge to the next event. **EFC** = Σ Q_dis / C_rated. Indian homes: 0.5–3 partial cycles/day. RUL is computed in EFC then converted to weeks.
- **Physics prior**: Schiffer/Sauer weighted-Ah-throughput model (wear per Ah weighted by DoD, rate, stratification, time since full charge) and Ruetschi's aging modes (grid corrosion, PAM shedding, irreversible sulphation, shorts, water loss). Every feature below is one of those quantities.

## 1. Feature engineering — what the MCU computes, and when
### 1.0 Front end
INA228: ADCRANGE=1 (±40.96 mV → ±409.6 A), 4.12 ms conversion, AVG=128 → one averaged sample per ~0.5 s, read at 1 Hz (the averaging is the anti-alias filter). The on-chip 40-bit CHARGE accumulator is read each second as a cross-check on the firmware Ah integral. Per-sample struct {I, V, T, SoC, R_int} = 12 B in a 600-sample ring (10 min, 7.2 KB). Median-of-3 spike rejection on I and V; EMA V_f (τ = 5 s) for ICA.

**Cycle segmentation state machine** (per sample): FLOAT→DISCHARGE when I < −0.02C for 3 s; DISCHARGE→CHARGE when I > +0.01C for 3 s; CHARGE_CC→CHARGE_CV when V ≥ V_boost − 0.1 V (typ. 14.4 V); CHARGE_CV→FLOAT when I < 0.02C for 30 min or V drops to float (13.6–13.8 V). **FULL_CHARGE** event = entering FLOAT via the tail-current criterion (the same rule as 01 §5a).

### 1.1 Voltage sag under load (normalised)
```
ΔI = I[t+1]−I[t−1];  ΔV = V[t+1]−V[t−1];  R_step = −ΔV/ΔI     valid if |ΔI| ≥ 0.05·C, state==DISCHARGE, t_in_state ≥ 60 s
sag_norm = R_step · 0.1·C_rated                                 (mV at I10)
sag_ref  = sag_norm · g(SoC) · h(T)     g: 8-entry SoC→70 % table; h = 1 + κ_R·(T−25), κ_R ≈ +0.01…0.02/°C
feature  = sag_ref / sag_ref,baseline   (baseline = median of the battery's first 10 cycles, in NVS)
```
16-slot per-cycle buffer → median at cycle end. The 60 s guard removes the surface-charge artefact at outage onset. (The EKF's burst capture in 01 §6.1 feeds the same buffer with cleaner values when available.)

### 1.2 R_int trend (from EKF)
R_ref(k) = median over cycle k of R_int·h(T), sampled only at 0.4 ≤ SoC ≤ 0.95 and |I| ≥ 0.05C. Features: R_ref/R_baseline and dR/dEFC via RLS over the last 30 cycles (λ = 0.97, 4 floats). Resistance growth precedes the capacity knee in both Li-ion and lead-acid — the single most transferable feature.

### 1.3 Ah throughput, raw and Schiffer-weighted
```
Q_dis(k), Q_chg(k) as int64 mAs integrals;  EFC = Σ Q_dis / C_rated (NVS daily)
Q_w(k) = Q_dis(k)·w_k,  w_k = 1 + a·max(0, DoD_k − 0.5) + b·max(0, ln(t_full,k / 24 h))     a=1.0, b=0.3 defaults, fit on campaign
```
t_full,k = hours since the last FULL_CHARGE at discharge start (time in partial state of charge drives sulphation).

### 1.4 DoD histogram and low-SoC exposure
DoD_k = SoC_start − SoC_min (rest-OCV-calibrated when available). Bins [0–10,10–20,20–30,30–40,40–50,50–60,60–80,80–100] %; H_life[b] += Q_dis (uint32); H_ewma[b] = 0.98·H_ewma[b] + Q_dis. Statics: f_DoD50, f_DoD80, DoD_mean_recent; SoC-band time histogram (5 bands) → f_lowSoC = time at SoC < 50 % / total. Rainflow is unnecessary — inverter cycles are single-valley.

### 1.5 Arrhenius temperature-stress integrals
```
AF(T) = exp( 6400·(1/298.15 − 1/(T+273.15)) )       doubles per ≈10 °C
S_T,total += AF·Δt/86400  (25 °C-equivalent days);  S_T,float only in FLOAT (corrosion/water loss);  S_T,disch only at SoC < 0.5 (sulphation)
```
61-entry Q8.8 LUT (122 B), 32-bit accumulators, published daily. This is the quantitative form of the report's "life halves per +10 °C".

### 1.6 Coulombic efficiency (informative in lead-acid, useless in Li-ion)
Between consecutive FULL_CHARGE events: η_c = Q_dis/Q_chg (valid if Q_dis ≥ 0.1C); typically 0.85–0.95, **falls** with sulphation and gassing. If no valid value in a cycle, carry the last plus a **staleness channel** (cycles since valid, clipped at 30).

### 1.7 Incremental capacity dQ/dV from the CC recharge (empirical, ablation-gated)
Preconditions: CHARGE_CC, |I − I_cc,nom| ≤ 10 %, 15–45 °C. V_corr = V_f − I·R_int; bin = floor((V_corr − 12.0)/20 mV), 120 bins, Qbin[b] += I·1 s. At CC exit: 5-bin moving average; peak search 12.9–13.8 V (main PbSO₄ conversion, ≈2.15–2.30 V/cell; sulphation shifts it up and flattens it; gassing rise > 2.35 V/cell arrives earlier in Ah). Features: ic_peak_h ratio, ic_peak_v shift, ic_area; ic_valid only if SoC_start ≤ 70 % and ≥ 0.15C charged. Memory 480 B. Lead-acid ICA literature is thin — treated as a candidate feature with a staleness flag, **not** a load-bearing claim.

### 1.8 Charge acceptance (free IRCA test every recharge)
At CHARGE_CV entry t0: CA_5 = I(t0+5 s)/C, CA_60 = I(t0+60 s)/C; CA_ref = CA_60·(1 − κ_CA(T−25))·c(SoC_t0); cv_frac = Q_CV/(Q_CC+Q_CV); t_tail = time from CV entry to I < 0.02C. Declines reversibly and irreversibly with partial-SoC cycling.

### 1.9 Two "free" ground-truth-ish signals
- **Rest OCV** (≥ 4 h at |I| < 0.005C): OCV ≈ 11.9 + 0.9·SoC (calibrate), re-anchors the EKF and, with t_full, flags stratification.
- **Direct capacity sample**: an outage running from FULL_CHARGE to inverter cut-off (10.5–10.8 V) at roughly constant rate gives C_meas = Q_dis·(I/I10)^(n−1), n ≈ 1.2, temperature-corrected — a true SoH observation used for **on-device conformal re-anchoring (§5.5)**, never for gradient training.

### 1.10 Per-cycle feature vector (14 dynamic + 6 static)
| # | channel | § | # | channel | § |
|---|---|---|---|---|---|
| 1 | R_ref ratio | 1.2 | 8 | cv_frac | 1.8 |
| 2 | sag_ref ratio | 1.1 | 9 | ic_peak_h ratio (last valid) | 1.7 |
| 3 | Q_dis/C_rated | 1.3 | 10 | ic_peak_v shift (last valid) | 1.7 |
| 4 | DoD_k | 1.4 | 11 | staleness(ICA)/30 | 1.7 |
| 5 | η_c (last valid) | 1.6 | 12 | mean T in cycle | raw |
| 6 | staleness(η_c)/30 | 1.6 | 13 | ln(1 + t_full/24 h) | 1.3 |
| 7 | CA_ref ratio | 1.8 | 14 | rest-OCV-implied SoC error vs EKF | 1.9 |
Statics s ∈ R⁶: EFC, S_T,total/age, S_T,float, f_DoD50, f_lowSoC, age_days/365.
Storage: 36 B/cycle; RAM ring of 64 cycles (2.3 KB); LittleFS log of full history (256 KB ≈ 7,000 cycles). **Live feature state < 12 KB RAM.**

## 2. Model
### 2.1 Choice: 1-D temporal CNN over the last 30 cycles + static branch, quantile heads
- **Not an MLP on flattened features**: 30×14 = 420 inputs → 64 hidden is already 27 k params in one layer with position-specific weights that do not generalise between "knee at cycle 20" and "knee at cycle 25".
- **Not a GRU**: TFLM has no native GRU kernel (decomposes into many ops), ESP-NN does not accelerate recurrent ops, int8 quantisation of recurrent state accumulates error.
- **CNN** uses exactly the ops ESP-NN hand-optimises on the S3 (CONV_2D 5.5–14×, FULLY_CONNECTED 5.5×, RELU 11×), gives shift-invariant knee/trend/jump detectors; 30-cycle context suffices because the statics carry the lifetime integrals. First inference requires ≥ 10 real cycles; earlier slots are padded by repeating the oldest cycle.

### 2.2 Architecture
| layer | config | out | params | MACs |
|---|---|---|---|---|
| Conv1D-1 | k=5, 14→16, ReLU | 26×16 | 1,136 | 29,120 |
| Conv1D-2 | k=5, 16→32, stride 2, ReLU | 11×32 | 2,592 | 28,160 |
| Conv1D-3 | k=3, 32→32, ReLU | 9×32 | 3,104 | 27,648 |
| Flatten ⊕ statics | 288 + 6 | 294 | 0 | 0 |
| Dense-1 | 294→64, ReLU | 64 | 18,880 | 18,816 |
| Dense-2 | 64→32, ReLU | 32 | 2,080 | 2,048 |
| Head-SoH | 32→3 [q50, d_lo, d_hi] | 3 | 99 | 96 |
| Head-RUL | 32→3 on ln(1+RUL_EFC) | 3 | 99 | 96 |
| **Total** | | | **≈ 28.0 k** | **≈ 106 k** |
Conv1D exports as Conv2D with height 1. Ops: RESHAPE, CONV_2D, FULLY_CONNECTED, CONCATENATION, RELU (+ EXPAND_DIMS). **Non-crossing quantiles**: heads emit q50 plus two non-negative deltas; P10 = q50 − d_lo, P90 = q50 + d_hi — guaranteed ordering with no SOFTPLUS and no sort.

### 2.3 Size, memory, latency on ESP32-S3
Weights int8 ≈ 28 KB; flatbuffer ≈ 32 KB flash per model. Largest activation 416 B; graph fits < 8 KB arena; reserve **16 KB** + ~4 KB interpreter. **ML subsystem ≈ 32 KB of 512 KB RAM.** Espressif's VWW benchmark (≈8 MMAC) runs 54 ms with ESP-NN vs 2,300 ms without → our 106 k-MAC graph is **≈1–10 ms** with ESP-NN, ≤ 50 ms without, once per cycle. Invisible against EKF and Wi-Fi tasks.

### 2.4 Uncertainty band: quantile heads + 3-seed ensemble, **not** MC-dropout
| option | flash | passes | int8 | captures | verdict |
|---|---|---|---|---|---|
| Quantile heads (pinball loss) | +0.2 KB | 1 | yes | aleatoric | **primary** |
| 3-seed ensemble, heads averaged | 3×32 KB | 3 (3–30 ms) | yes | epistemic (unfamiliar duty) | **add; budget allows** |
| MC-dropout | 0 | 30–100 | needs RNG + inference-time dropout op (absent in TFLM) | epistemic, poorly calibrated | rejected |
On-device band: P10 = mean_seeds(q50 − d_lo) − c_lo; P90 = mean_seeds(q50 + d_hi) + c_hi, with **split-conformal offsets** c_lo, c_hi computed on held-out calibration batteries and stored in the model header → finite-sample coverage guarantee. Ensemble spread > 5 SoH points = out-of-distribution flag → UI shows "uncertain — collecting data".

## 3. RUL and the "replace within N weeks" logic (H6)
### 3.1 Conversion to weeks
```
RUL_EFC quantiles from the model (exponentiate ln(1+·)).
r = EFC/week, EWMA over 8 weeks (α = 0.2), with variance σ_r²; blend a per-region prior when < 4 weeks of history.
RUL_weeks,P10 = RUL_EFC,P10 / (r + σ_r);   P50 = RUL_EFC,P50 / r;   P90 = RUL_EFC,P90 / max(r − σ_r, 0.3 r)
Calendar bound: RUL_cal = max(0, L_cal / AF_mean − age), L_cal = 5 y float life at 25 °C (per brand).   RUL = min(RUL_cycle, RUL_cal) per quantile.
```
### 3.2 On-device second opinion
RLS line through the last 20 SoH_P50 vs EFC → RUL_lin = (SoH_now − 80)/|m|. If RUL_lin and RUL_P50 differ by > 2× while RLS residual σ < 1.5 pt → widen the window to cover both and set confidence = LOW. Catches a mis-calibrated model without hiding it.
### 3.3 Grades
| grade | condition (conformalised quantities) |
|---|---|
| Healthy | SoH_P50 ≥ 88 AND RUL_weeks,P10 > 26 |
| Degrading | else, if SoH_P50 ≥ 82 AND RUL_weeks,P10 ≥ 8 |
| **Replace within N weeks** | SoH_P50 < 82 OR RUL_weeks,P10 < 8 → **N = max(1, round(RUL_weeks,P10))**, window [P10, P90] shown |
| Service now (overrides) | anomaly detector (§6) fires persistently |
### 3.4 Hysteresis and honesty rules
- Grade change requires the condition to hold for **3 consecutive inferences on distinct cycles spanning ≥ 5 days**.
- Upgrading is harder than downgrading: back to Healthy needs SoH_P50 ≥ 90 and RUL_P10 > 30 weeks.
- N recomputed **weekly**, moving at most ±2 weeks/week unless the anomaly detector or a direct capacity sample justifies a jump.
- UI shows a **window, never a date**: "Likely needs replacement in 6–14 weeks (plan for 6)". Confidence high/medium/low from ensemble spread, staleness of ICA/η_c channels, and RLS agreement.
- Copy states that the SoH forecast covers gradual wear; sudden failures are routed to the anomaly path.

## 4. Training and transfer (H10)
### 4.1 Loss
```
L = Σ_{τ∈{0.1,0.5,0.9}} pinball_τ(SoH) + λ_R·Σ_τ pinball_τ(ln(1+RUL))            λ_R = 1
  + λ_mono·mean(ReLU(ŜoH_50(k) − ŜoH_50(k−1) − 0.5))                                (SoH must not rise > 0.5 pt/cycle)
  + λ_cross·(ReLU(−d_lo) + ReLU(−d_hi));   sample weight w = 1 + 3·exp(−RUL_EFC/100)   (near-EoL windows matter most)
AdamW, lr 1e-3 cosine, batch 64, early stop on grouped validation pinball loss.
```
### 4.2 Stage A — pre-train on public Li-ion (shape priors)
NASA PCoE, CALCE CS2/CX2, Sandia, Severson/Toyota 124 LFP cells — the **same** 14+6 feature pipeline run offline on their raw series → ~10⁵ windows. **What transfers**: the architecture and ratio-to-own-baseline normalisation (filters learn *shape* — monotone drift, knee onset, R growth preceding capacity loss — not absolute values); concave capacity-vs-throughput with late knee; quantile-width growth with horizon. **What does not**: η_c (≈99.9 % and uninformative in Li-ion), ICA peak semantics, temperature/DoD sensitivity (lead-acid life ≈ 50–100 cycles @100 % DoD vs 800+ @30 %), partial-cycle statistics. Literature: cross-chemistry transfer works with fine-tuning on as little as one cell / ~10 % of a target cell's early life; **zero-shot reuse fails**.
### 4.3 Stage B — synthetic Indian duty simulator (sim-to-real bridge)
1 Hz I/V/T from virtual tubular batteries through the *firmware feature code compiled for host*: Poisson outages (0.3–3/day, seasonal), lognormal durations (median 1 h), load 150–900 W with appliance switching, inverter η 85 %; charger CC 10–15 % of C10 to 14.4 V, CV, float 13.7 V; Shepherd/Thevenin with Peukert n ∈ [1.15, 1.35]; aging via Schiffer weighted-Ah with randomised parameters plus sulphation-driven acceptance decline and R growth; Chennai/Delhi ambient profiles + self-heating; domain randomisation; ±1.5 pt label noise. Fine-tune all layers a few epochs. Purpose: partial-cycle statistics and static-channel semantics, not truth about real batteries.
### 4.4 Stage C — fine-tune on the in-house aging campaign (04)
1. **C1** (20 epochs): freeze Conv1–3; train Dense-1/2 + heads, lr 1e-3 — re-learns statics and the η_c/CA/ICA channels.
2. **C2** (≤ 60 epochs, early stop): unfreeze all; lr 1e-4 conv / 5e-4 dense; **L2-SP** toward Stage-B weights (β = 1e-3) so a small set cannot drag the filters far.
3. Train 3 seeds → ensemble.
4. Split-conformal calibration on 6 held-out batteries: c_lo = q_0.9(P10 − y), c_hi = q_0.9(y − P90), separately for SoH and ln RUL.
5. CV: **GroupKFold by battery ID** (never split within a cell — autocorrelated cycles leak), 6 folds; plus **leave-one-condition-out** (hold out 50 °C, hold out PSoC) to quantify extrapolation loss — what field data will look like.
Data volume: 24 batteries × ~200 cycles ≈ 4,800 windows — small, hence freeze/L2-SP/augmentation (time-warp ±15 %, sensor-matched noise, random masking of ICA/η_c with matching staleness).

## 5. Quantisation and deployment
### 5.1 int8: PTQ first, QAT fallback
Full-integer PTQ (int8 weights/activations/IO) with ~500 representative windows spanning healthy → near-EoL and both temperature extremes; per-axis weight quantisation. Expected loss: SoH MAE +0.1–0.3 pt, RUL pinball +2–3 %, coverage shift ≤ 2 % → **re-conformalise on the quantised model** so coverage is restored exactly. QAT only if quantised RUL P10 shifts > 5 %. Output scaling: SoH head trained on (SoH−60)/40 → int8 step ≈ 0.16 pt; RUL head on ln(1+RUL)/8 → 3 % relative step; inputs standardised to [−1, 1], clipped ±3σ.
### 5.2 Runtime and budget
esp-tflite-micro 1.4.x with ESP-NN (ESP-IDF 5.1–6.0), MicroMutableOpResolver with exactly the ops used, static 16 KB arena in internal SRAM (no PSRAM), models in a dedicated flash partition.
| item | flash | RAM |
|---|---|---|
| SoH/RUL model × 3 seeds | 96 KB | — |
| Anomaly AE | 4 KB | — |
| TFLM + ESP-NN code | ~90 KB | ~4 KB |
| tensor arena | — | 16 KB |
| feature state | — | 12 KB |
| feature history (LittleFS) | 256 KB | — |
| **total** | **< 0.5 MB of 8 MB** | **≈ 32 KB of 512 KB** |
### 5.3 Cadence
Feature pipeline every second (≈ 200 integer ops/sample). Inference at every cycle-end event and at least once per 24 h (statics still move). Warning state machine aggregates weekly (§3.4).
### 5.4 Model versioning and OTA (see 09)
Two 128 KB model slots (A/B): {magic, model_version, feature_schema_version, mean/scale[20], conformal c[2×2], threshold table, CRC32, flatbuffer}. Firmware refuses a model whose feature_schema_version ≠ its own. Swap = download to inactive slot → CRC → trial AllocateTensors() + one inference on a built-in golden window with expected outputs → flip active pointer in NVS. Rollback if the trial fails or the first 5 field inferences disagree with the previous model by > 10 SoH points. Model refresh = ~100 KB download, not a firmware image.
### 5.5 On-device personalisation: **no gradient fine-tuning**
MCUNetV3 shows on-device training under 256 KB is possible, but it needs its own engine (not TFLM), and — decisively — **there are no labels on device**: true SoH is unobserved except at rare deep-outage capacity samples, and a safety-relevant warning must not drift under self-training. Personalisation = (a) ratio-to-own-baseline features, (b) scalar conformal re-anchoring when a direct capacity sample arrives: offset = SoH_meas − SoH_P50, applied as a clipped (±5 pt) EWMA bias, (c) fleet learning: 36 B feature records uploaded (08), retraining in the cloud, models return by OTA.

## 6. Anomaly autoencoder (H8) + rule fast path
- Input: last 3 per-cycle vectors + first differences → 56 dims. Architecture 56→24 (ReLU)→6 (linear)→24 (ReLU)→56 (linear) = **3,086 params (3 KB int8)**.
- Training: MSE on standardised features from windows with SoH > 90 % (campaign + synthetic healthy runs); validated on campaign fault cells (deliberately shorted cell, heavily sulphated unit, chamber over-temperature) and synthetic fault injections.
- Threshold: e = Σ((x̂_i − x_i)/σ_i)²; alarm if e > e_99 on 2 of 3 consecutive cycles, or e > e_99.9 once. Per-feature contribution vector names the culprit.
- **Rule fast path (per second, no ML)**: R_int jump > 30 % in one cycle; **cell short** = rest OCV drops ≈ 2.1 V (12.7 → ~10.6 V) while charger reaches CV early and float current jumps; **thermal** = T > 55 °C, dT/dt > 1 °C/min in charge, or T − T_amb > 15 °C; **open/loose connection** = sag_ref > 3× baseline with normal EKF R_int.
- Effect: "Service now" overrides the SoH grade; flagged cycles are masked (staleness incremented) so a fault does not corrupt the SoH trajectory; report carries the top-3 contributing features.

## 7. Pseudocode
```c
void on_sample(int32_t I_mA, int32_t V_mV, int16_t T_dC, q15 soc, q15 r_int) {
  I = median3(I_mA); V = median3(V_mV); V_f = ema(V_f, V, 5); ring_push(&raw10min, {I,V,T_dC,soc,r_int});
  state = segment(state, I, V);
  if (I < 0) q_dis_mAs += -I; else q_chg_mAs += I;  charge_reg_check(ina228_read_charge());
  uint16_t af = AF_LUT[clamp(T_dC/10,0,60)]; s_total += af; if (state==FLOAT) s_float += af; if (soc < Q15(0.5)) s_disch += af;
  soc_band_time[band(soc)]++;
  if (state==DISCHARGE && t_in_state >= 60 && fabs(dI2()) >= 0.05*C) push_sag(r_step_ref(dI2(), dV2(), soc, T_dC));
  if (soc in [0.4,0.95] && fabs(I) >= 0.05*C) push_rint(r_int * hT(T_dC));
  if (state==CC && near(I, I_cc_nom, 10%) && T in [15,45]) { b = (V_f - I*r_int - 12000)/20; if (0<=b && b<120) qbin[b] += I; }
  if (entered(CV)) t_cv0 = now; if (state==CV) { if (now-t_cv0==5) ca5=I; if (now-t_cv0==60) ca60=I; q_cv_mAs += I; }
  if (entered(FLOAT_via_tail)) on_full_charge();  if (rest_ge_4h()) on_rest_ocv(V);  if (cycle_ended(state)) on_cycle_end();
}
void on_cycle_end(void) {
  x.r_ratio = median(rint_buf)/base.r;  x.sag_ratio = median(sag_buf)/base.sag;  x.q_dis = q_dis_mAs/C;  x.dod = soc_start - soc_min;
  x.eta_c = last_eta; x.eta_stale = min(30, cycles_since_eta);  x.ca_ratio = ca_ref(ca60,T_cv0,soc_cv0)/base.ca;  x.cv_frac = q_cv/(q_cc+q_cv);
  if (ica_valid()) { smooth(qbin); ica_features(qbin,&x.ic_h,&x.ic_v); ica_stale=0; } else ica_stale++;
  x.T_mean = t_acc/n; x.ln_tfull = ln1p(t_full_h/24); x.ocv_err = ocv_soc_err;
  hist_update(x.dod, x.q_dis); efc += x.q_dis;  ring_push(&cycles64, quantize_int16(x)); fs_append(x);  reset_cycle_accumulators(); request_inference();
}
void inference_task(void) {
  wait_event(CYCLE_END | DAILY_TICK);  if (cycles64.count < 10) { publish_grade(COLLECTING); return; }
  build_window(A, S);
  e = ae_recon_error(last3_with_diffs());
  if (rules_fire() || debounced(e > e99)) { publish_grade(SERVICE_NOW, top3_contrib()); mask_current_cycle(); return; }
  for (m=0;m<3;m++) { out[m] = run(model[m], A, S); }
  soh50 = mean(q50); p10 = mean(q50-dlo) - c_lo_soh; p90 = mean(q50+dhi) + c_hi_soh;
  rul_efc = { exp(mean(r50-rdlo) - c_lo_rul)-1, exp(mean(r50))-1, exp(mean(r50+rdhi) + c_hi_rul)-1 };
  if (spread(q50) > 5) confidence = LOW;
  rul_w = min_each(to_weeks(rul_efc, r_ewma, sigma_r), calendar_bound());
  rls_update(soh50, efc); if (disagree(rls_extrapolate(), rul_w.p50, 2.0)) { widen(&rul_w); confidence = LOW; }
  grade = grade_state_machine(soh50, rul_w, /*debounce*/3, /*min_days*/5, /*hysteresis*/2pt_4wk);
  publish(soh50, p10, p90, rul_w, grade, confidence);      // "6–14 weeks, plan for 6"
}
```

## 8. Six-step summary (judge-ready)
1. **Measure** 1 Hz I/V/T (INA228 on a 0.1 mΩ shunt); EKF supplies SoC and R_int. Only a 10-minute raw ring is kept.
2. **Reduce each outage/recharge to 14 physics features + 6 lifetime integrals** — resistance and sag relative to the battery's own new-state baseline, throughput, DoD, coulombic efficiency between full charges, charge acceptance 60 s after the charger hits 14.4 V, the dQ/dV signature of the CC recharge, temperature, time since full charge; plus EFC, Arrhenius stress, DoD histogram, low-SoC time, age. These are the quantities the classical lead-acid lifetime models say govern wear.
3. **Infer with a 28 k-parameter int8 1-D CNN** over the last 30 cycles in a 16 KB arena in ~1–10 ms, once per cycle; three seeds averaged; P10/P50/P90 for SoH and remaining equivalent cycles to 80 %, with conformal offsets guaranteeing the band's coverage on held-out batteries.
4. **Convert to weeks honestly**: remaining cycles ÷ this home's observed outage rate (with variance), capped by calendar aging, cross-checked by an on-device linear extrapolation. The user sees a window, never a date.
5. **Grade with hysteresis**: Healthy / Degrading / Replace-within-N-weeks from SoH-P50 and RUL-P10, debounced over 3 cycles and ≥ 5 days, harder to upgrade than to downgrade, N moving ≤ ±2 weeks/week.
6. **Sudden failure is watched separately**: a 3 k-parameter autoencoder plus hard rules (R_int jump, ~2.1 V OCV drop for a shorted cell, thermal signatures) raise "Service now" and mask faulty cycles. Trained: Li-ion pre-training for shape priors → synthetic Indian-duty bridge → frozen-then-L2-SP fine-tuning on a 24–36-battery accelerated tubular campaign, cross-validated by battery, shipped by OTA to a two-slot model partition. **No gradient training on the ESP32.**

## References
Chaoraingern & Numsomran, Sensors 25(12):3810, 2025 (TinyML RUL on RP2040) · Severson et al., Nature Energy 2019 · David et al., *TensorFlow Lite Micro*, MLSys 2021 · Espressif esp-nn benchmarks; esp-tflite-micro component · Quantile RUL: Springer 2024 (SVQR); arXiv:2512.23725 (non-crossing quantile MoE); arXiv:2212.14612 (conformal RUL) · Transfer learning: Sci. Rep. 2022 (s41598-022-16692-4); Energies 18(20):5439; J. Energy Storage 2026; Ionics 2026 meta-analysis · MCUNetV3 (arXiv:2206.15472) · QUTE (arXiv:2404.12599); Tiny Deep Ensemble (arXiv:2405.05286) · TF Lite PTQ docs; Novac et al. 2021 (arXiv:2105.13331) · Schiffer et al., J. Power Sources 168:66, 2007 · Ruetschi, J. Power Sources 127:33, 2004 · PVEducation lead-acid characteristics · Batteries 11(4):131, 2025 (IRCA) · Victron Peukert · ICA: PMC12056397; J. Energy Storage 2019 · Volta Foundation dataset comparison; batteryarchive.org · Exide InvaTubular; Luminous product pages · SoH accuracy: WEVJ 16(11):594; Sustainability 17(9):4014; Energies 19(17):4161 (PICP/MPIW).
