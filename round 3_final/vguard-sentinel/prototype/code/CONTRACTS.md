# Shared contracts for the Sentinel prototype code (all modules must conform)

Root: `documentation/prototype/code/`. Python 3.9, numpy/scipy/pandas/scikit-learn/torch/matplotlib/cryptography/flask/pytest available. **Do not install large packages** (no TensorFlow, no venvs); small pure-Python packages via `pip install --user` only if unavoidable. All tests: `pytest -q` from this root. C code: C99, host-buildable with `gcc -std=c99 -O2 -lm`, no ESP-IDF dependency in algorithm modules (ESP glue lives in `firmware/` only).

## 1. 1 Hz sample stream (sim → features/ekf)
CSV or numpy record array, one row per second:
| column | unit | note |
|---|---|---|
| t | s (int) | monotonic epoch seconds |
| I | A (float) | **+ charge, − discharge** (battery convention used by 02 features; the EKF doc uses the opposite sign internally — the EKF module must convert) |
| V | V | terminal voltage |
| T | °C | battery temperature |
| grid | 0/1 | mains present |
| P_load | W | AC load (sim only; not sensed by the battery path) |
| soc_true | 0–1 | sim ground truth (absent on real data) |
| soh_true | % | sim ground truth per cycle (absent on real data) |

## 2. Per-cycle feature record (features → model), `features/schema.py` is the single source of truth
14 dynamic channels (float32) exactly in this order, then 6 static channels, then labels:
`r_ratio, sag_ratio, q_dis_norm, dod, eta_c, eta_stale, ca_ratio, cv_frac, ic_peak_h, ic_peak_v, ica_stale, t_mean, ln_tfull, ocv_err` | statics: `efc, st_total_per_day, st_float, f_dod50, f_lowsoc, age_years` | labels: `soh_true (%), rul_efc_true (EFC to 80 %), battery_id, cycle_idx`.
Stored as CSV `data/features_<name>.csv` and as int16-quantised arrays only inside the firmware. Window for the model = last 30 cycles × 14 + 6 statics (design 02 §1.10, §2.1).

## 3. Model outputs (model → dashboard/firmware)
`soh_p10, soh_p50, soh_p90` (%), `rul_efc_p10, rul_efc_p50, rul_efc_p90`, `rul_weeks_p10/p50/p90`, `grade ∈ {COLLECTING, HEALTHY, DEGRADING, REPLACE, SERVICE_NOW}`, `n_weeks`, `confidence ∈ {LOW, MED, HIGH}` (design 02 §3).

## 4. AC power stream (PZEM/AFE → nilm/pq), 1–3 Hz
`t, Vrms, Irms, P, Q, PF, f` (+ `Ipk, Pf, Ph` when an AFE is present; NaN otherwise). NILM event record: `t0, dP, dQ, phi_deg, r_pk, t_settle_s, A_tr, h, dur_s, label, confidence` (design 06 §3.1).

## 5. Autopilot inputs/outputs (design 05)
Inputs each 60 s: `soc, soh, grid, load_w, hour, dow, tier_config[4]`. Outputs: `channel_state[4] ∈ {ON, SHED}` (SHED = coil energised on an NC contactor), `reasons[]`, `est_backup_min`. Thresholds: T3 shed ≤40 % / restore ≥55 %; T2 defer ≤55 % / restore ≥70 %; T1 never; dwell 300 s ON / 180 s OFF; override timeout 1800 s.

## 6. C API names (firmware glue calls these; algorithm modules provide them)
```c
// ekf/ekf.h
void ekf_init(ekf_t*, const ekf_params_t*); void ekf_step(ekf_t*, float I_discharge_pos, float V, float T, int charger_on); float ekf_soc(const ekf_t*); float ekf_r0(const ekf_t*);
// autopilot/autopilot.h
void ap_init(ap_t*, const ap_config_t*); void ap_evaluate(ap_t*, const ap_input_t*, ap_output_t*);   // call every 60 s
// nilm/event_detector.h
int  ev_push(ev_det_t*, float t, float P, float Q, float V, ev_event_t* out);   // returns 1 when an event is emitted
// pq/pq.h
void pq_push_sample(pq_t*, float v_sample);   // 4 kS/s
int  pq_poll_event(pq_t*, pq_event_t* out);
// healthlog/healthlog.h
int  hl_append(hl_t*, uint16_t type, const uint8_t* payload, size_t n);  // hash-chains + signs (sw ECDSA-P256 via provided callback)
int  hl_verify_chain(const uint8_t* buf, size_t n, const uint8_t pubkey[64]);
```

## 7. Honesty labels
Every README states what was executed here (synthetic data, host C) versus what needs hardware or the aging campaign. No claimed number without a script that reproduces it.
