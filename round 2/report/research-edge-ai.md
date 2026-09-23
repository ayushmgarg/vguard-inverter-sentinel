# Research Notes — Edge-AI Feasibility (honest, cited)

## 1. Federated Learning (FL) for embedded fleets
- **Frameworks:** Flower (deployment-realistic, framework-agnostic, Android+TFLite path, FedAvg etc.). TensorFlow Federated = **simulator only, not deployable** (Google docs).
- **On-MCU training?** Only constrained *sparse fine-tuning*, not general training. MIT MCUNetV3 "On-Device Training Under 256 KB" (NeurIPS 2022) trains on STM32F746 via Quantization-Aware Scaling + sparse layer update; graph compiled AOT for one fixed model; single dev-board research artifact.
- **Defensible architecture (CLAIM THIS):** (1) MCU runs quantized **inference** continuously; (2) optional light on-device sparse personalization; (3) **home gateway / paired phone runs the real FL training round** (has RAM/FPU/power); (4) **opportunistic upload of model deltas only** when power+connectivity allow; (5) server-side **FedAvg / DP-FTRL** aggregation → OTA new global model. DO NOT claim "train deep models directly on the inverter MCU across the fleet."
- **Privacy:** Secure Aggregation (Bonawitz 2017 — server sees only summed update) + **Differential Privacy** together. "Encrypted updates only" ≠ private (gradient-inversion). Gboard production DP-FTRL: ρ=0.81 zCDP (≈ single-digit ε); ε<1 at useful accuracy is hard. Privacy scales with cohort size — small pilot fleet = modest privacy claims only.
- **Comm/cadence:** update ≈ model size; TinyML model tens–hundreds of KB → tens-to-few-hundred-KB updates. Template: ~6,500 devices/round, ≤1 participation/device/24 h, opportunistic. FedS3A cuts comm >50%.
- **Precedent:** Google Gboard (>20 languages, 1.4 MB LSTM, DP at 6,500 devices/round). Apple FL+local DP since iOS 13. FL-on-IoT: FedDetect, FedS3A, ESP32-class FL intrusion detection.

## 2. NILM (energy disaggregation) on the edge
- Strongest edge NILM runs on **RPi4 / Coral Edge TPU, not bare MCU**. seq2point CNN ~40M params → 10.6 MB int8; ~3.6 ms/appliance on RPi4 — does NOT fit an MCU. True MCU NILM = TinyML classification demos, far less mature.
- **Sampling:** ≤1 Hz meter data works for high-power stable loads (AC, geyser, pump, fridge; ~6 MB/day). kHz needed to separate low-power/overlapping loads (~691 MB/day/channel).
- **Accuracy (published F1, Western datasets):** washing machine 0.88, kettle 0.74–0.85, fridge 0.65–0.74, microwave 0.64–0.74, dishwasher 0.51–0.67. Quantization costs little; spiky loads hard.
- **Limits:** low-power appliances buried in noise; overlapping loads; **cross-home generalization is the central weakness** (needs per-home calibration). Multi-state appliances harder.
- **India data:** iAWE = **1 Delhi house, 1 Hz, 73 days**; washing-machine F1=0.0 reported. India-generalizable claims rest on thin data. Others: REDD, UK-DALE, Pecan Street.
- **Defensible framing:** low-freq edge NILM for a few high-power Indian loads at ~0.65–0.89 F1 is feasible; per-home calibration, low-power blindness, MCU-only full disaggregation = R&D targets, not proven.

## 3. Power-quality / voltage-event on MCU
- IEC 61000-4-30: sag/swell RMS over 1 cycle, refreshed each half-cycle (~10 ms); sag <90%, swell >110%; freq over 10 s. PQ front-ends sample 128–256 samples/cycle (~6.4–12.8 kS/s) — trivial for MCU. CMSIS-DSP FFT ~0.1–1.5 ms/block, well under 10 ms budget.
- **CRITICAL — detect vs predict:** you **DETECT** sags fast (sub-cycle to ~1 cycle) but **cannot PREDICT** grid-origin sags (remote faults/motor starts propagate ~instantly; no local precursor). Only anticipatable cases: self-caused local motor start (if sensed/controlled) + statistical/seasonal risk. **Claim "fast detection + ride-through/response," NOT "prediction."**
- Target **IEC 61000-4-30 Class-S-like**, not certified Class A (needs ±0.1% traceable). Standards: IEEE 1159 (sag 0.1–0.9 pu), EN 50160, CBEMA/ITIC ride-through curve.

## 4. Autonomous load prioritisation / smart shedding
- **All commercial products are RULE-BASED** (SOC/voltage/frequency thresholds + priority tiers): Victron, Tesla Powerwall (essential-circuit shed; Storm Watch = weather-triggered pre-charge, externally triggered not learned), Sol-Ark/Deye Smart Load, Enphase IQ Controller, SPAN/Lumin smart panels (~40% runtime extension claim, static tiers).
- Indian brands (Luminous ConnectX, Microtek Luxe) = monitoring + **manual** only; autonomous per-load prioritisation in Indian home inverters is **open white space**.
- Microgrid logic: Under-Frequency Load Shedding (UFLS) staged tiers; IEEE 1547-2018 = DER grid trip/ride-through envelope (not household load prioritisation).
- **AI/RL is research-only:** headline "61% peak reduction" is simulation; realistic real-world ~8–20% peak, ~8% energy. RL sometimes loses to rule-based.
- **Defensible claim:** a *hybrid* — robust rule-based tiers + learned demand/outage forecasting — is genuinely novel for Indian home inverters; frame gains at ~8–20%, not 61%.

## Cross-cutting honesty (must reflect in report)
1. FL = inference on MCU + training on gateway/phone + server aggregation; SecAgg **and** DP; privacy scales with cohort.
2. NILM proven on Pi-class HW for high-power loads; MCU-only + cross-home = R&D.
3. Power quality: **detect fast, don't predict** grid sags; Class-S-like not Class A.
4. Load prioritisation: rule-based deployed; learning layer novel; gains ~8–20%.
