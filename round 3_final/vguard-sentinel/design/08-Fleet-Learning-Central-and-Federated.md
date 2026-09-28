# 08 — Engine 4: Fleet Learning — central telemetry path and optional federated path (worked out to a T)

**Resolves Gap Register:** H20 (telemetry schema/pipeline), H21 (federated protocol), H33 (usage patterns as quasi-identifiers), H38 (Flower ≥5-home simulation). Design change D6 in 12 (what is actually federated).

## 0. Decision on scope — a correction to the report's implicit framing
The report reads as if the SoH/RUL model is what federated learning improves. Working it through (02 §5.5): **there are almost no SoH labels on device** (only rare deep-outage capacity samples), and the habit forecaster is an interpretable EWMA table, not a neural net (05 §1). A federated round needs local labels or a self-supervised objective. What actually has labels on every device is the **NILM appliance classifier** (user-named clusters, 06 §4.2) — and it is exactly the privacy-sensitive, household-specific model FL was invented for. The anomaly autoencoder (02 §6) is label-free and also federatable.

| Model | Trained where | Why |
|---|---|---|
| SoH/RUL CNN (02) | **Central** on campaign + opt-in per-cycle feature telemetry; personalised by conformal offset on device | no on-device labels; safety-relevant; needs pooled diversity |
| Anomaly AE (02 §6) | Central primary; **federated optional** (unsupervised MSE on healthy windows) | label-free |
| NILM classifier priors / rule-layer MLP (06 §4) | **Federated primary** (labels are user-provided on device; raw events never leave) | privacy-sensitive, household-specific, labelled |
| Habit/outage table (05) | Never leaves the device; aggregate outage statistics per region uploaded only as coarse counts | interpretable; regional outage rosters are useful fleet analytics |
Every device always has the central model as its floor; FL is an additive personalisation/aggregation bonus, never a prerequisite.

## PART A — Central path (primary)
### A1. Telemetry schema (raw 1 Hz never leaves the device)
Never uploaded: raw V/I/T samples, raw ADC values, GPS, Wi-Fi SSIDs, sub-5-min timestamps, NILM event records or appliance labels (only per-appliance kWh aggregates if opted in).
**(i) Per-cycle summary (1–5/day)**, ≈ 48 B: device_pseudonym (16 B HMAC), cycle_id u32, ts_bucket (5-min), V_mean/min/max (u16 mV ×3), I_mean/max (u16 mA), T_mean/max (i8), throughput_Ah (u16, 0.01 Ah), DoD_hist[8] u8, SoC_start/end u8, charge/discharge_time_s u16, R_int_est u16 mΩ, fw/schema_version u8, crc16. **In practice this is the 36 B feature record of 02 §1.10 plus header** — one schema serves both training and fleet analytics.
**(ii) Per-day aggregate (1/day)**, ≈ 60–70 B: date_bucket, num_cycles, total_Ah, T_min/mean/max, SoC time-weighted mean, minutes below 20 % / above 90 %, outage_count, outage_total_min, on-device SoH_P50 and RUL_P10, model_version, schema_version, crc16.
**(iii) Events (sparse)**, ≈ 32–40 B: type (over-current, over-temp, deep-discharge, anomaly-alarm, fw-update, comm-fault), pseudonym, ts_bucket, severity, payload[≤16], crc16. Grid Shield PQEvents (07 §3) ride this channel.
**Bandwidth**: ≈ 400–600 B/day raw → **~1–1.5 KB/device/day with MQTT/TLS framing ≈ 30–45 KB/month.** Negligible on any Indian data plan.
### A2. On-device storage
Not NVS (Espressif: NVS is for infrequently-changing config, not logging). One **wear-levelled LittleFS data partition** (1 MB of the 8 MB flash) holds the telemetry queue, the 02 feature history, NILM event records and PQ events; NVS keeps only slow state (pseudonym salt, consent flag, credentials, model version, read-pointer advanced once per acked batch). At ~600 B/day the queue survives **> 800 days offline**; design target 90 days before FIFO overwrite, with day-aggregates prioritised over per-cycle detail under pressure.
### A3. Upload protocol
MQTT 5.0 over TLS 1.3 (1.2 fallback), QoS 1, persistent session (clean_session = false), topic `vguard/telemetry/{region}/{pseudonym}`. **Batched** (one publish per day of summaries, or immediately on Wi-Fi association if a backlog exists). **Windows**: Wi-Fi associated AND (idle-charging OR 02:00–04:00 local); never during an active discharge event (05 power policy: Wi-Fi off during outages). Exponential backoff with jitter (30 s base, 1 h cap). Keepalive 60 s (< 1 KB/day).
### A4. Pseudonymisation, consent, and the quasi-identifier problem (H33)
- `pseudonym = Trunc128(HMAC-SHA256(device_secret, rotating_salt ‖ epoch_id))`; device_secret in eFuse/ATECC608 (09), never transmitted; salt server-issued **quarterly** → breaks long-term linkability while keeping within-epoch cycle-to-cycle trends.
- **No GPS**; only an installer-entered coarse region (state / metro-vs-non-metro) at commissioning.
- **Consent**: explicit, itemised, DPDPA-compliant notice in the app (purpose, categories, retention, one-tap withdrawal), per the Digital Personal Data Protection Rules 2025 (notified 14 Nov 2025; obligations phase in to 13 May 2027). Withdrawal halts uploads and triggers server-side deletion of that pseudonym's history.
- **Honest admission**: a device's usage pattern — outage timing, charge cadence, DoD histogram — is a behavioural fingerprint that can re-identify a household when cross-referenced with public feeder-level outage schedules. Mitigations: 5-min bucketing and day-level aggregation before upload; pseudonym rotation; **k-anonymity (k = 20) on every released cohort/report cell**; **central DP** (Gaussian noise on published aggregates; per-example clipping + noise in central training, moments-accountant style) as a hardening knob.
### A5. Cloud pipeline
```
MQTT ingest (TLS-terminated) → CRC/schema/range validation; reject bad CRC, out-of-range V/I/T, replayed cycle_id; flag > 4σ outliers into an anomaly table (do not drop — may be real faults)
→ immutable, content-hashed dataset snapshots (DVC/Delta-style); every training run pinned to a dataset hash
→ training per model family → offline evaluation: GroupKFold by device pseudonym (never split within a device); drift checks vs a frozen golden slice (MAE/RMSE tolerance band, PSI/KL on input distributions)
→ model registry: signed TFLite flatbuffer + header (dataset hash, metrics, target profile, conformal offsets)
→ staged OTA (09): canary 1 % 48–72 h → 10 % 1 wk → 50 % 1 wk → 100 %; auto-rollback on crash-loop, fault-event rate rise, or on-device confidence-distribution regression
```

## PART B — Federated path (optional, opted-in connected homes)
### B1. Client
Runs on the **paired Android phone or a home gateway**, not the ESP32-S3 (no training headroom; TFLite on-device training targets Android, not MCUs). Sync: ESP32-S3 → BLE → app, transferring the on-device NILM cluster prototypes + labels (≈ 7 KB) and/or the 02 feature buffer. Training only while **charging + unmetered Wi-Fi + idle** (the Gboard trigger). Framework: **Flower** (Android client via TFLite; Python `flwr` client on an OpenWrt-class gateway). Local model = NILM rule-layer MLP (13-24-12, ~700 weights) / anomaly AE (3 k params); E = 1–5 epochs over a few hundred local examples → seconds per round.
### B2. Round protocol
| Parameter | Value | Rationale |
|---|---|---|
| Min cohort | **50 (pilot) / 200+ (scale)** | SecAgg masking hides individuals only in large cohorts; DP sensitivity assumes one client is a small perturbation; SecAgg+ needs headroom above its t-of-n reconstruction threshold |
| Local epochs / batch / lr | 1–5 / 16–32 / 1e-3–1e-2 | small local sets |
| ΔW | W_local − W_global, **L2-clipped to C = 1.0** (normalised) before leaving the client | DP sensitivity bound |
| Secure aggregation | Bonawitz et al. pairwise masking as **Flower SecAgg+** (Shamir shares, dropout-tolerant, honest-but-curious, 4 comm rounds, sub-linear overhead) | server sees only the cohort sum |
| Noise | Gaussian σ added **server-side after SecAgg** (`DifferentialPrivacyServerSideFixedClipping`) | SecAgg protects individuals from the server; DP protects the aggregate from everyone downstream |
| Aggregation algorithm | **DP-FTRL, not amplified DP-FedAvg** | DP-FedAvg's proof leans on uniform, verifiable client sampling; participation here is gated by Wi-Fi/charging habits and cannot be enforced. DP-FTRL (Kairouz et al. 2021) needs no amplification, tolerates irregular participation via tree aggregation, and beats un-amplified DP-SGD at all privacy levels |
| Local optimiser | **FedProx** (proximal term) | stable under statistical and systems heterogeneity; allows variable local work |
| Cadence / payload | ~daily / **80–160 KB** ΔW + SecAgg overhead | matches the report's "tens–hundreds of KB" |
### B3. DP accounting — reaching ε ≈ 4, δ = 1e-5 per user-year
Gaussian mechanism, sensitivity C, composed by RDP (moments accountant). Illustrative closed form for k participations/year with noise multiplier z = σ/C:
```
ε(σ, k) ≈ k/(2σ²) + √(2k·ln(1/δ))/σ,   ln(1/δ) ≈ 11.51
```
| Regime | k/yr | σ for ε = 4 | Honest posture |
|---|---|---|---|
| Pilot, thin cohort | 30–50 | **≈ 7–9** | ε = 4 achievable but updates are noisy — real accuracy cost |
| Pilot, looser budget | 30–50 | ≈ 3–4 | ε ≈ 8–10 (typical of early production FL); disclose the trade-off |
| Scale, heavy participants | ~200 | **≈ 18–20** | accept the noise or **cap participation** once a device hits its annual budget |
Production numbers come from running the Flower/DP-FTRL `RdpAccountant` on the final config, not from this formula. DP noise at z ≈ 7–20 is a measurable quality cost; DP-FTRL narrows but does not remove it — which is why FL is supplementary to the central path.
### B4. Non-IID and participation bias
Well-connected urban homes over-contribute. Mitigations: FedProx; **inverse-participation weighting**; personalisation layers so a biased global head is only a starting point; a **held-out low-connectivity evaluation panel** (uploads via the central path only, never contributes gradients) to detect drift toward the connected subpopulation; versioning/rollback identical to A5.
### B5. Simulation plan (H38, the Phase-3/4 demo)
`flwr.simulation` with **5–50 virtual clients**, each on a partition of iAWE/UK-DALE-derived NILM events (and campaign feature windows for the AE), partitioned non-IID by (a) region/climate, (b) load archetype (frequent short vs rare long outages), (c) participation skew (simulate B4 directly). Validates: DP-FTRL/FedProx convergence under skew, SecAgg+ dropout tolerance (clients disconnect mid-round), ε vs (k, σ) at pilot cohort sizes, and whether the held-out panel detects injected bias. **Cannot validate**: real Android Doze/BLE/Wi-Fi behaviour, consent dynamics, or true re-identification risk — that needs a red-team exercise before production.
### B6. Sequence
```
ESP32-S3 ──BLE: cluster prototypes + labels / feature records──▶ Phone/Gateway (Flower client)
Phone ◀── global W (round start, cohort selected) ── Server
Phone: local train E epochs (FedProx) → ΔW → clip to C → SecAgg+ mask/share ──▶ Server
Server: reconstruct SUM(ΔW) only → add Gaussian σ (DP-FTRL tree) → update W ──▶ next round / OTA
Phone ──BLE: personalised NILM priors──▶ ESP32-S3 (optional)
```

## Six-step summary (judge-ready)
1. Every unit logs privacy-scrubbed per-cycle and per-day battery summaries locally and uploads ~1 KB/day opportunistically to V-Guard's central pipeline; this alone keeps every device's SoH model current.
2. For opted-in connected homes, the paired phone pulls the on-device appliance-classifier prototypes and user labels over BLE and, only while charging/Wi-Fi/idle, runs a short local round; the SoH model is **not** federated because devices have no SoH labels.
3. The weight delta is clipped and protected by SecAgg+ so the server only ever sees the cohort sum and tolerates drop-outs.
4. The server adds calibrated Gaussian noise via DP-FTRL — chosen because V-Guard cannot guarantee uniform client sampling — accounting to ε ≈ 4, δ = 1e-5 per user-year, with the quality cost stated.
5. Connectivity bias is countered by FedProx, participation weighting and a held-out low-connectivity panel; models ship through the same canary/rollback OTA rings as the central path.
6. A device that never participates is never disadvantaged; the moat is the pooled, consented, pseudonymised **dataset** and the campaign — not the federated protocol itself.

## References
Beutel et al., *Flower* (arXiv:2007.14390); Flower Android/TFLite blog; Flower SecAgg+ (arXiv:2205.06117); Flower DP how-to and FedProx baseline · Bonawitz et al., *Practical Secure Aggregation*, CCS 2017 · Kairouz et al., *DP-FTRL* (arXiv:2103.00039); google-research/DP-FTRL · Abadi et al., *Deep Learning with DP*, 2016 · Hard et al., *FL for mobile keyboard prediction*, 2018 · Li et al., *FedProx*, MLSys 2020 · FedKit (arXiv:2402.10464) · *Federated battery diagnosis and prognosis* (arXiv:2310.09628) · MQTT v5.0 OASIS · ESP-IDF NVS, wear-levelling, file-system considerations · DPDP Rules 2025 (PIB; IAPP).
