# 07 · Literature survey: the gap Sentinel fills

> **One line for the jury:** *"Research has solved each piece separately, mostly for lithium-ion in electric vehicles. We didn't find anyone combining them for a lead-acid home inverter, running offline on a ₹1,000 chip. That combination is Sentinel."*
>
> Every paper below is real and linked. When you cite one, say *"a 2019 Nature Energy paper from Stanford and MIT"*, not a page number. Never claim "nobody has done X". Say *"in the work we reviewed, we did not find X"*.

---

## At a glance

| # | What research has done | What's missing for Indian home inverters | What Sentinel does | Shown in our proof of concept by |
|---|---|---|---|---|
| G1 | ML battery-health prediction, almost all for **Li-ion** | little for **tubular lead-acid** under outage duty | lead-acid physics simulator + a health model trained on it | the simulator, CNN results, 245 tests |
| G2 | Kalman state of charge for lead-acid in **hybrid cars** | home inverters sit on **float** and in Indian heat, where float ≠ OCV | 3-state Kalman filter with taper anchor and rest-gated OCV | Kalman filter in C = Python reference; simulation |
| G3 | lifetime predictions as a **single number**; conformal bands mostly offline for Li-ion | families need a trustworthy window, **on the device** | int8 CNN + split-conformal window ("6–14 weeks") | calibrated band, bit-exact int8 self-test |
| G4 | TinyML on microcontrollers, mostly **charge (SoC)** for **EV / drone Li-ion** | no **health + remaining life** on a cheap MCU for lead-acid | ~28 k-parameter int8 CNN (~37 KB per model), targeting the ESP32-S3 | firmware host build |
| G5 | load shedding by **fixed priority**, mostly **off-grid PV microgrids** | not driven by battery health or the family's habits in a grid-tied inverter | habit autopilot + endurance floor + normally-closed fail-safe | Sentinel-Live Home 6 demo |
| G6 | NILM on the **mains meter**; Indian homes differ | not linked to backup decisions | NILM on the **inverter output** feeds the shedding choice | NILM tests, simulation |
| G7 | households value reliability highly; appliances damaged by outages | no **evidence** a consumer can use in a warranty claim | Grid Shield + signed, hash-chained log | log tamper tests |
| G8 | heat drives lead-acid aging | chargers regulate by heatsink or fixed voltage | battery-post NTC + temperature-compensated charging (Embedded) | design; Gate 1 to measure |

---

## G1 · Battery-health ML is a Li-ion story
- **Severson et al., "Data-driven prediction of battery cycle life before capacity degradation", *Nature Energy* 4, 383–391 (2019).**
  - 124 LFP/graphite Li-ion cells; lifetime predicted from early discharge curves; 9.1 % test error.
  - The landmark paper in the field, and it is Li-ion only. [Nature](https://www.nature.com/articles/s41560-019-0356-8)
- **Recent ML SoH reviews** (2025) are also almost entirely Li-ion. They name the big open problems:
  - the gap between lab and field data
  - reliable labels
  - dependence on large datasets
  - Sources: [review 1](https://www.sciencedirect.com/science/article/abs/pii/S1364032125007981), [review 2](https://www.sciencedirect.com/science/article/abs/pii/S259011682500116X)
- **Jiang & Song, "A review on the state of health estimation methods of lead-acid batteries", *Journal of Power Sources* 517 (2022).**
  - Lead-acid does have its own review. It groups methods as direct measurement, model-based, data-driven and other, and lists practical limitations of each. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0378775321012052)
- **Lead-acid ML papers exist, but they are small and single-method:**
  - an FFNN SoH estimate ([JCSC 2022](https://www.worldscientific.com/doi/abs/10.1142/S0218126622500815))
  - ML voltage and lifetime prediction ([Wang et al. 2020](https://journals.sagepub.com/doi/10.1177/0144598719881223))
  - a Wiener-process RUL model ([2025](https://www.sciencedirect.com/science/article/abs/pii/S0957582025002411))
  - model-based SoH from step response, with an automotive focus ([J. Energy Storage 2021](https://www.sciencedirect.com/science/article/abs/pii/S2352152X21001146))

**Gap:** we found no work predicting a tubular lead-acid battery's remaining life, with calibrated uncertainty, under Indian outage-and-float duty.
**Sentinel:** a lead-acid simulator (not Li-ion data rescaled) → 20 physics features → CNN.
**Be honest:** our 8.2-point SoH error is on synthetic data. Severson's 9.1 % is on real cells. That's why Gate 1 (the real aging campaign) exists.

## G2 · Kalman state of charge exists, but for cars
- **Plett, "Extended Kalman filtering for battery management systems of LiPB-based HEV battery packs", Parts 1–3, *Journal of Power Sources* 134 (2004).**
  - The foundational EKF-for-batteries series; Li-ion polymer, hybrid vehicles. [Semantic Scholar](https://www.semanticscholar.org/paper/Extended-Kalman-filtering-for-battery-management-of-Plett/7141188a801c843a9c2e7efb7068cfb6f62f577c)
- **Lead-acid EKF papers for hybrid electric vehicles:**
  - an EKF SoC predictor with a bulk/surface capacitor model ([Energy Conversion & Management](https://www.sciencedirect.com/science/article/abs/pii/S0196890407001550))
  - an adaptive EKF ([J. Power Sources](https://www.sciencedirect.com/science/article/abs/pii/S0378775308023525))
  - EKF under different temperatures ([ResearchGate](https://www.researchgate.net/publication/318326475_Lead_acid_battery_SoC_estimation_based_on_extended_Kalman_Filter_method_considering_different_temperature_conditions))

**Gap:** these target vehicle cycling. A home inverter battery sits on float for days and then deep-discharges in an outage. Float voltage is not OCV, so a naive voltage correction biases SoC upward.
**Sentinel:** a 3-state EKF (SoC, V1, R0). It re-anchors to 100 % on charge-current taper, and uses OCV only after a real rest with the charger off. About 3 % RMS vs 7.2 %/week drift for plain coulomb counting (simulation).

## G3 · Predictions without honest uncertainty
- **Javanmardi & Hüllermeier, "Conformal Prediction Intervals for Remaining Useful Lifetime Estimation", *Int. J. Prognostics & Health Management* (2023).**
  - Conformal prediction gives intervals with a guaranteed coverage for remaining useful life (RUL), tested on turbofan engines (not batteries). [arXiv](https://arxiv.org/abs/2212.14612) · [IJPHM](https://papers.phmsociety.org/index.php/ijphm/article/view/3417)
- **Conformal SoH/RUL for Li-ion** (2024), with tree and linear models. [ResearchGate](https://www.researchgate.net/publication/383565155_Uncertainty_Quantification_of_Lithium-ion_Battery_State_of_Health_and_Remaining_Useful_Life_Prediction_using_Conformal_Inference_Method)
- **Damage-adaptive conformal RUL** (Li-ion).
  - Its point: field telemetry drops out and drifts, so point error grows while prediction intervals "fail silently". [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7372428)

**Gap:** conformal battery work is Li-ion, runs offline or in the cloud, and isn't customer-facing.
**Sentinel:** split-conformal on quantile heads, shown as a *window*, never a date. If the model isn't sure, it says "collecting data". It runs on the device.

## G4 · TinyML for batteries: mostly SoC, mostly Li-ion
- **Mazzi et al., "State of charge estimation of an EV battery using tiny neural network embedded on small MCUs", *Int. J. Energy Research* (2022).**
  - int8 1-D CNN and GRU for **SoC**, on EV Li-ion. The closest match to our pipeline, but for charge, not health. [Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1002/er.7713)
- **TinyML SoC case study**, *Electronics* 13 (2024). [MDPI](https://doi.org/10.3390/electronics13101964)
- **TinyML RUL for UAV Li-polymer batteries** (2025).
  - An 8-bit model, < 2 KB RAM; drones, not lead-acid. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12196908/)

**Gap:** we did not find on-device **SoH + remaining-life window** for **lead-acid**.
**Sentinel:**
- int8 CNN × 3 seeds, ~28 k parameters (~37 KB per model file), targeting the ESP32-S3.
- int8 costs only 0.013 points of accuracy vs float.
- The C code is bit-exact against Python on a host build.
- Not yet flashed on a real board: say so.

## G5 · Load shedding is rule-based, and blind to the battery
- **Load-shedding strategies for battery management in PV rural off-grids** (demand-side management). [ResearchGate](https://www.researchgate.net/publication/282643014_Analysis_of_load_shedding_strategies_for_battery_management_in_PV-based_rural_off-grids)
- **User-defined High / Medium / Low load priorities** for islanded DC microgrids in emergencies (*Discover Energy*, 2025). [Springer](https://link.springer.com/article/10.1007/s43937-025-00107-2)
- **Dynamic-priority residential scheduling** for demand response. [arXiv](https://arxiv.org/pdf/1905.10846)

**Gap:** these use priorities set once, mostly for off-grid solar or grid demand response. They don't consider:
- the **battery's current health**
- **when the family usually needs power**
- a **fail-safe** if the controller dies

**Sentinel:**
- Tiered shedding driven by live SoC, predicted outage length and the family's weekly habits (168 bins).
- A 1.2× endurance floor, and the medical channel is never shed.
- NC contactors: if Sentinel dies, everything comes back on.
- **Shown in:** Sentinel-Live, Home 6 (essentials last past 10 pm).

## G6 · NILM: well studied, but on the mains meter
- **Hart, "Nonintrusive appliance load monitoring", *Proceedings of the IEEE* 80(12) (1992).** The origin of edge-based NILM, which is our approach: ΔP events + signatures.
- **Kelly & Knottenbelt, "Neural NILM", *ACM BuildSys* (2015).** Deep networks for disaggregation. [arXiv](https://arxiv.org/abs/1507.06594)
- **Batra et al., "It's Different: Insights into home energy consumption in India" (iAWE dataset, 2013).**
  - The first NILM dataset from a developing country (a Delhi home). Its title makes the point: Indian home energy use differs from the Western homes most NILM datasets come from. [ResearchGate](https://www.researchgate.net/publication/257527880_It's_Different_Insights_into_home_energy_consumption_in_India)

**Gap:** NILM is used for energy feedback. In the work we reviewed, it is not used to decide **which loads to keep during an outage on inverter power**.
**Sentinel:** event-based NILM (ΔP ≥ 25 W, 13-feature signature, k-NN) on the inverter output. It tells the autopilot what is actually running.

## G7 · Indian households pay heavily for unreliability, and have no proof
- **Khanna & Rowe, "The long-run value of electricity reliability in India", *Resource and Energy Economics* 77 (2024), Delhi, more than 1 million customers.**
  - One more hour of outage a month cut consumption by 4.8 %.
  - Households value lost power at about **25× the grid tariff**.
  - Nearly all backup units in the survey were **battery inverters**.
  - About **9 % reported appliance damage** from outages.
  - [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0928765524000010)
- **Willingness to pay to avoid outages, 1,043 urban Indian households, *Energy Policy* 184 (2024):** about $0.37 for a 2-hour outage up to $3.00 for 12 hours. [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0301421523004688)
- **LocalCircles survey:** 2 in 3 households faced outages in the heat; 1 in 3 had more than 2 hours a day. [LocalCircles](https://www.localcircles.com/a/press/page/india-electricity-outages)

**Gap:** people value backup highly and suffer appliance damage, but have no measured, tamper-proof record to support a claim.
**Sentinel:** Grid Shield (half-cycle RMS, IEEE 1159 event classes) + a SHA-256 hash-chained, ECDSA-signed log.

## G8 · Heat is the lead-acid killer
- **Ruetschi, "Aging mechanisms and service life of lead-acid batteries", *Journal of Power Sources* 127 (2004).**
  - Grid corrosion, sulphation, water loss. Corrosion and water loss both **rise with temperature**. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0378775303009340)
- **VRLA life at high ambient temperature**, *J. Power Sources* (1998). [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0378775398000287)

**Gap:** temperature compensation is well known. But it needs the **battery's** temperature, and it needs the charger to act on it.
**Sentinel:** an NTC on the battery's negative post; −24 mV/°C compensation; derating above 45 °C; equalisation only when due. The Embedded version only.
**Life gain:** a 15–30 % target, to be measured at Gate 1, not claimed.

---

## If they ask "what's your novelty?" (30 seconds)
> "No single piece is new: Kalman filters, CNNs, conformal bands, NILM and load shedding are all published. What we didn't find anywhere is all of it **together, for lead-acid, inside a home inverter, offline, on a ₹1,000 chip**, with a fail-safe. Each piece feeds the next:
> 1. the Kalman filter gives the CNN its inputs;
> 2. the CNN's window drives the autopilot;
> 3. NILM tells the autopilot what's running;
> 4. Grid Shield signs the evidence.
>
> Our simulation shows the loop working end to end, and the tests show the code matches."

## If they ask "then why hasn't anyone built it?"
> "Research mostly follows the EV money, which means Li-ion. Home inverters are an Indian and developing-world product, and real tubular aging data sits with manufacturers like V-Guard, not universities. That's exactly why it fits V-Guard."

## Where the literature is ahead of us (say it before they do)
- Severson's model is validated on **124 real cells**. Ours is on **synthetic** lead-acid data.
- Published TinyML work runs on **real MCUs**. Ours is a bit-exact **host build**, not yet flashed.
- Neural NILM beats k-NN on hard cases. We chose k-NN for **on-device** use and explainability.
