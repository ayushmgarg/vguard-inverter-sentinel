# 04 — In-House Lead-Acid Aging Campaign (worked out to a T)

**Resolves Gap Register:** H9 (aging-campaign matrix). This is the "dataset acceptance" validation gate in the report roadmap and the source of every "characterise-in-lab" parameter in 01, 02 and 03.

## 0. Why it exists
No public dataset covers Indian tubular flooded inverter batteries under partial-cycle duty. Li-ion sets (NASA/CALCE/Sandia/Severson) provide shape priors only (02 §4.2). Without this campaign the SoH/RUL claim is unsupported. The campaign has **four deliverables**: (1) the EKF tables (OCV(SoC,T), R0/R1/C1(SoC,T), f_temp, η_charge); (2) labelled SoH trajectories for Stage-C fine-tuning; (3) fault exemplars for the anomaly detector; (4) the controlled comparison behind the "15–30 % life extension" claim (03 §3.3).

## 1. Test matrix
| Factor | Levels | Rationale |
|---|---|---|
| Brand / plate | 2 brands (V-Guard-sourced OEM + one market leader, e.g. Exide/Amaron) | plate design changes R0/OCV/ICA |
| Size | 100 / 150 / 200 Ah (C10) | covers the range; R ∝ 1/C |
| Temperature | 27 °C (IS reference), 40 °C (Indian summer enclosure), 50 °C (accelerated) | Arrhenius spread for the AF LUT |
| DoD | 30 / 50 / 80 % | Schiffer weighting a; life vs DoD |
| Regime | full recharge every cycle vs **partial-SoC (PSoC)** (recharge to 85 % only, full charge every 7th cycle) | sulphation driver, t_full feature |
| Charging | fixed-profile (SG3525 defaults) vs temperature-compensated + scheduled equalisation | the 15–30 % comparison |
**Minimum viable: 24 batteries; recommended: 36**, assigned by a fractional-factorial design (not full factorial — 2×3×3×3×2×2 = 216 cells is not needed). Suggested allocation (36): 12 at 27 °C, 12 at 40 °C, 12 at 50 °C; within each, DoD 30/50/80 × regime full/PSoC × brand, sizes rotated; 6 units at 40 °C form the charging comparison (3 fixed vs 3 compensated, same DoD 50 %, full recharge). Plus **6 field units** in employee homes on real inverters (real duty, real telemetry) and **3 fault units** (deliberately shorted cell, deliberately sulphated by 60-day PSoC dwell, chamber over-temperature run).

## 2. Protocols
### 2.1 Beginning-of-life characterisation (every battery, before cycling)
1. Three conditioning cycles per IS 13369 / IEC 61427 practice; C10 reference test at 27 °C to 10.5 V → C_BoL.
2. **OCV(SoC,T)**: from full, discharge 5 % steps at C/20, rest ≥ 24 h, log OCV; also charge-direction (hysteresis, 01 §2.3). Repeat at 0, 25, 45 °C.
3. **HPPC** (01 §1.6): at 100…10 % SoC in 10 % steps × {0, 25, 45 °C}: C/5 10 s discharge pulse, 40 min rest, C/5 10 s charge pulse, 40 min rest → R0, R1, C1 tables.
4. **η_charge(SoC,T)** from the Ah-in/Ah-out of the stepped cycles.
5. **IRCA-style charge acceptance** (02 §1.8) and a **rest-OCV vs SG** cross-check (hydrometer) for stratification reference.
### 2.2 Cycling
- Cycle = discharge at the profile's rate (I10 nominal; a subset at I5 to exercise Peukert) to the target DoD, then recharge per regime. 8–12 h per cycle → 2–3 cycles/day.
- **Reference test every 25 cycles**: C10 at 27 °C (ground-truth SoH), IRCA, rest-OCV, HPPC at 50 % SoC (R0 trend), SG per cell, water top-up log (mass).
- **Termination**: SoH ≤ 80 % (EoL) or 300 cycles or a fault. At 50 °C/80 % DoD EoL arrives at ~150–300 cycles ≈ 2–4 months; at 27 °C/30 % DoD it may not arrive within the campaign — that is fine, those units bound the "healthy" region and calibrate calendar aging.
- **Post-mortem** on ≥ 6 EoL units: teardown, plate inspection (corrosion/shedding/sulphation), ties each trajectory to a Ruetschi mode label.
### 2.3 Instrumentation (per channel)
The **Sentinel board itself** (INA228 + NTC + ESP32-S3) logs every unit at 1 Hz exactly as in the field — so the campaign trains on the production sensor chain, not on lab-grade instruments — **plus** the cycler's reference channel (0.1 % class) for cross-validation of the coulomb counter. Data: raw 1 Hz I/V/T + cycler logs + reference-test results, in a versioned dataset (08 §A4).

## 3. Equipment and cost (order-of-magnitude, to be quoted)
| Item | Qty | Est. |
|---|---|---|
| Tubular batteries 100–200 Ah | 36 + 6 field + 3 fault | ₹14–18 k each → ~₹6–8 lakh |
| Programmable charge/discharge cyclers (bidirectional, 0–30 A, 0–16 V), 12 channels | 3 | ₹8–15 lakh (regenerative units) or resistive load banks + programmable chargers at lower cost |
| Climate chambers (0–60 °C, ~1 m³) | 2 (27/40 °C ambient room + 50 °C chamber; 0 °C for BoL only) | ₹6–10 lakh |
| Hydrometer, thermal camera, teardown tooling | — | < ₹1 lakh |
| Sentinel logging boards | 45 | ~₹800 each |
| **Duration** | 6–8 months (2 setup, 3–5 cycling, 1 analysis) | — |
This sits naturally in the Kochi Innovation Campus reliability lab already cited in the report.

## 4. Acceptance criteria (the roadmap "dataset gate")
- ≥ 20 batteries reach EoL or ≥ 200 cycles with < 5 % missing 1 Hz data.
- EKF tables produced for every brand × size; SoC error vs cycler-integrated Ah ≤ 3 % RMS on the 40 °C group (11 §1).
- Stage-C model, GroupKFold by battery: SoH MAE ≤ 3 pt; RUL-window hit-rate ≥ 75 %; leave-one-condition-out MAE ≤ 5 pt (02 §7).
- Charging comparison: compensated group shows a statistically significant (p < 0.05, n = 3 vs 3 — accept this is weak; extend if inconclusive) increase in cycles-to-80 % at 40 °C. Report the measured ratio; **replace the "15–30 %" claim with the measured number.**
- Anomaly detector: all 3 fault units flagged ≥ 5 cycles before their terminal event; false-positive rate < 1 per 1,000 healthy cycles.

## 5. Also request from battery suppliers
IEC 61427 / IS 13369 endurance-test logs and float-life data — free EoL points at nominal conditions; and their published temperature derating curves (f_temp) and Peukert data.

## References
IS 13369 (tubular lead-acid for inverters/UPS) · IEC 61427 (secondary cells for PV energy systems — endurance) · Schiffer et al. 2007 · Ruetschi 2004 · Plett/INL HPPC methodology · Battery University BU-903/BU-804c · Batteries 11(4):131, 2025 (IRCA).
