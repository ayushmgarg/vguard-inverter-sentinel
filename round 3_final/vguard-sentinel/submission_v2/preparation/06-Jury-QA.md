# 06 · Jury Q&A: prepared for this panel

> **The panel is V-Guard's own leadership.** They know inverters, batteries, costs and the market better than we do. Don't lecture them on inverters. Show that we understood *their* product, found its gaps, and built something they could ship.
> Roles below are from public professional profiles; confirm on the day if possible.

| Panelist | Role (public profile) | What they will probe | Who answers |
|---|---|---|---|
| **Narendra (Narender) Singh Negi** | VP R&D, Electronics / Power Products | inverter internals, charger control, sensing accuracy, safety, thermal | our hardware/firmware person |
| **Arif Mohammad (Kooliyat)** | VP New Product Development | BOM, manufacturability, integration, certification, time to market | hardware + product person |
| **Prasad Sudhakar Teni** | Senior GM, Home Appliances | consumer value, installation, service, other appliances | product/business person |
| **Anoop Singh** | technology / R&D leader (role unconfirmed) | ML validity, data, IoT, OTA, security, privacy, scale | ML person |

---

## Golden rules for this jury
1. **Respect their expertise.** Say "on Prime-class units…", not "an inverter is a device that…".
2. **Separate three things every time:** proven in code · synthetic only · needs hardware/data.
3. **Frame everything as V-Guard's advantage.** They own the battery factory, the Kochi lab, the Smart platform and the dealer network. We need them; they need the idea.
4. **Short answer first (≤ 15 s), then stop.** If they want depth, they'll ask.
5. **Never say** "AI decides everything", "we guarantee 30 % longer life", "it runs on the ESP32 today", or "certified". **Say** "designed to", "target", "measured on synthetic data".

---

## 1 · Narender Singh Negi: R&D Electronics (the inverter owner)
*He knows the SG3525 board, the changeover relay and the charger better than anyone in the room. Expect precise technical probing.*

**Q1. How will you control our charger? Our charge loop is analog.**
Only the Embedded version controls it. An MCP4725 DAC injects a small offset into the SG3525 feedback divider node, which shifts the regulated voltage. A hardware clamp limits how far it can move, and a 2-second heartbeat returns it to factory setpoints if Sentinel dies. The Retrofit version doesn't touch the charger; it only advises. We'd need your charger schematic to size the injection resistor and the clamp. That's our ask.

**Q2. What exactly does it change in charging?**
Temperature compensation of −24 mV/°C per 12 V from 25 °C (at 31 °C, absorption 14.40 → 14.26 V). Current derating above 45 °C and a stop around 58 °C. Equalisation only when due, below 40 °C, with no outage predicted.

**Q3. You claim longer battery life. Proof?**
None yet, and we don't claim it as a result. It's a target of 15–30 %, Embedded only, to be measured in a controlled aging comparison: compensated vs fixed charging at 40 °C, same depth of discharge. That's Gate 1.

**Q4. How do you measure battery current? Our units don't all have a shunt.**
Retrofit: an external 500 A / 50–75 mV busbar shunt in the negative lead, read by an INA228 (Kelvin sense; only millivolts reach our PCB). It adds < 0.2 mΩ, so your low-battery sensing isn't affected. Embedded: we Kelvin-tap your internal shunt where one exists, and use the same external-shunt input where it doesn't.

**Q5. How do you detect mains failure? Your relay already switches in < 10 ms.**
We don't replace your transfer. We detect the outage for *our* decisions with a 2-of-3 vote:
- mains RMS < 0.1 pu, sustained 1–2 s (AMC1311 isolated tap)
- your mode line via an opto (Embedded)
- battery current turning to discharge

It confirms in about 1.5 s, which is fine because shedding decisions happen on a 60 s cycle.

**Q6. What happens if your board fails while loads are shed?**
Everything comes back on. The contactors are normally closed.
- **Reset:** the pull-downs drop the coils.
- **Firmware hang:** an independent supervisory timer cuts the coil rail after 2 s without a heartbeat.
- **Dead board:** the NC contacts are physically closed.

Latching relays were rejected. The medical channel is hardware-locked with a jumper.

**Q7. How accurate is your state of charge?**
A 3-state Kalman filter (charge, polarisation, internal resistance) on a 1-RC model, about 3 % RMS in simulation, vs 7.2 %/week drift for plain coulomb counting. It re-anchors to 100 % on charge-current taper, and to the OCV table only after a real rest with the charger off. Float voltage isn't OCV; we fixed that error in our own design.

**Q8. Isolation and safety on the mains side?**
Mains sensing goes through an AMC1311 reinforced isolated amplifier and a PC817 opto across an isolation moat on the PCB; the CT is isolated by construction. TVS on every line. UL94 V-0 enclosure. We design to IS 13252 / IEC 62368-1 and IEC 61000; it's not certified yet.

**Q9. Power draw from the battery?**
About 2.6 mA average: a design estimate to be measured, under a twentieth of the battery's self-discharge. In an outage Wi-Fi is off, BLE is slowed and the metering chip is paused. Each shed coil holds 60–100 mA, still far less than the load it cut.

**Q10. Thermal: where is your temperature sensor?**
On the battery's negative post, because your inverter NTC is on the heatsink and says nothing about battery aging. The post tracks the electrolyte within about 2 °C.

---

## 2 · Arif Mohammad: New Product Development (can we build and ship it?)

**Q1. What's the BOM?**
Component cost at prototype prices:
- **Retrofit:** ₹1,050 (battery health + autopilot), ₹1,650–2,050 with Energy Coach + Grid Shield.
- **Embedded:** ₹450–700, or ₹850–1,300 with the Coach. It's cheaper because it reuses your shunt, 12 V rail, enclosure and mains signal.
- Contactors are extra.

**Q2. How hard is integration into our existing inverter?**
It's a daughter-board on standoffs with five taps:
- the internal shunt
- the mode/mains line
- the SG3525 feedback node
- the AC-OUT rail
- 4 coil outputs to a contactor panel

No change to your transfer or bridge. The Smart Pro family already has Wi-Fi/BLE and the Smart 2.0 app, so connectivity is solved.

**Q3. Board size and mechanicals?**
PCB 80 × 60 mm, enclosure 90 × 70 × 35 mm, PC/ABS UL94 V-0, 4× M3, DIN or screw mount. The high-voltage zone is behind a moat.

**Q4. Supply-chain risks?**
- **INA228 and ATM90E32AS breakout boards** aren't stocked in India. We used INA226 and PZEM-004T on the bench. On the production PCB, the bare chips are available through DigiKey India and similar.
- **ESP32-S3** is widely available.
- **Contactors** are standard DIN parts.

**Q5. How long to a pilot?**
- **Bench (Tier 0):** days, about ₹25–35 k including a battery and inverter.
- **Custom PCB (Tier 1):** 4–6 weeks.
- **Aging campaign (Gate 1):** 6–8 months in your Kochi reliability lab.
- **Field pilot:** 100 homes × 6 months.

**Q6. Installation for the Retrofit?**
An electrician, 30–45 minutes: cut the battery negative lead for the shunt, clip the CT on AC-OUT, fit the contactors in the DB on the inverter-group circuits, commission in about 10 minutes over BLE/USB. It includes a mandatory "power off = loads on" test.

**Q7. What would you need from us?**
One opened Prime-series inverter plus the charger schematic, the bench parts, and batteries plus cycler time in the Kochi lab.

**Q8. Certification path?**
Design to IS 13252 / IEC 62368-1 (the BIS gate), IEC 62040 for UPS, IEC 61000 for EMC. Certify after the Tier-1 PCB.

**Q9. Firmware updates in the field?**
A/B slots for firmware *and* models, separately. Signed images and Secure Boot V2, with automatic rollback. New models must pass a golden self-test. Rollout in rings: 1 % → 10 % → 50 % → 100 %.

---

## 3 · Prasad Teni: Home Appliances (does the customer care?)

**Q1. Why would a customer pay for this?**
Three reasons a family feels immediately:
- The fridge and Wi-Fi don't die at 10 pm.
- They get weeks of warning before a ₹15,000 battery fails, instead of a surprise.
- They have proof when a voltage fluctuation damages an appliance.

**Q2. Who is the first buyer?**
Homes with long daily cuts, elderly or medical users (a CPAP on a never-shed channel), work-from-home families, and owners of a 2–4-year-old battery.

**Q3. Isn't it annoying if it switches off my fan?**
The family chooses what is essential at installation, and can override for 30 minutes (up to 4 h). It never cuts the fridge, router or medical socket. The alternative, as our Home 6 shows, is losing *everything* at 10 pm.

**Q4. What does the customer see?**
- In the app: battery charge, backup time left, a health grade ("Healthy" / "Replace within 6–14 weeks"), which appliances used what, and grid events.
- On the unit: status LEDs.
- It works with no internet; the app syncs when available.

**Q5. How does this help service and dealers?**
The warning window becomes a planned replacement sale and a booked service visit (water top-up, terminal cleaning) instead of an emergency call. Warranty claims are settled with a signed log instead of an argument.

**Q6. Can it go beyond inverters?**
Yes, it's the same core with different models:
- **Pumps:** dry-run and bearing health from current signatures.
- **Stabilisers:** voltage-event logging.
- **Water heaters:** predictive heating from habits.

That's the roadmap, not built.

**Q7. What about the environment?**
60–80 % of India's used lead-acid batteries are recycled informally. The replacement warning is a natural take-back moment for authorised recycling, and longer life means about 42,000 fewer batteries per lakh homes per decade (at +20 %, a target).

**Q8. What if the prediction is wrong?**
It gives a window ("6–14 weeks, plan for 6"), never a date, so a wrong single date never misleads the customer. If the model is unsure, it says "collecting data" instead of guessing. Worst case: the family replaces a little early, never a surprise failure.

---

## 4 · Anoop Singh: technology (is the ML real and is it safe at scale?)

**Q1. What is the model actually trained on?**
Today: a lead-acid physics simulator we wrote, with 16 virtual tubular batteries and 624 cycles. It covers Indian outage patterns, heat, sulphation and aging models, and runs through the same feature code the chip uses. It is **not** extrapolated from Li-ion. Public Li-ion data (NASA, CALCE) is planned only for pre-training; the loaders are built, but it isn't used yet. Real accuracy needs your aging campaign.

**Q2. Accuracy?**
State-of-health error of 8.2 points on 3 test batteries the model never saw, synthetic. The calibrated band covers the truth 99 % of the time, but it's wide. The target after real data is ≤ 3 points. We show the weak number on purpose.

**Q3. Why a small CNN and not something bigger?**
Our limit is data, not model size, so a bigger net would memorise. The input is 20 engineered physics features per cycle. It has to run offline on an ESP32. int8 is 4× smaller and cost us only 0.013 points. We use three seeds, which tell us when the model is unsure.

**Q4. How do you avoid data leakage?**
Splits are by battery, never by cycle. There's an independent test set never used for tuning or calibration, and a leakage test in the codebase. An external reviewer flagged our earlier evaluator, and we fixed all six points.

**Q5. What runs on the device vs the cloud?**
Everything critical runs on the device, with zero internet: the Kalman filter, the CNN, shedding, grid logging and the signed log. The cloud adds OTA updates, fleet analytics and central retraining on consented summaries.

**Q6. Privacy?**
Raw 1 Hz data never leaves the home. Only about 48-byte per-cycle summaries are sent, pseudonymised, with consent (DPDPA), in 5-minute time buckets. No appliance event logs are sent, only optional per-appliance kWh.

**Q7. Security?**
- **Boot:** Secure Boot V2 + flash encryption.
- **Connection:** TLS 1.3 with mutual authentication.
- **Keys:** an ATECC608 secure element whose private key never leaves the chip.
- **Health log:** SHA-256 hash-chained and ECDSA-signed, so tampering, deletion, replay and truncation are all detectable.

**Q8. Federated learning?**
Designed (Flower, secure aggregation, differential privacy), but deliberately not in this prototype. When enabled, we'd federate the appliance model (users label it on the device), not battery health (no labels on the device).

**Q9. What's tested today?**
245 automated tests. The C modules match the Python references. A firmware host build links the real C code and passes a bit-exact int8 self-test. **Not yet flashed on an ESP32; that's the next step.**

---

## 5 · Questions any of them may ask (have one owner each)

| Question | 15-second answer |
|---|---|
| **What's new vs Smart Pro?** | Smart Pro shows *now* (charge, load, mode). Sentinel adds the *future* (a remaining-life window), *decisions* (autonomous shedding), *evidence* (a signed log, grid events), and works offline. The Embedded version slots into Smart Pro. |
| **Why can't a competitor copy it?** | The hardware can be copied. The moat is tubular aging data from your own batteries and lab, plus fleet data from your installed base. A third party has neither. |
| **What's the business case for V-Guard?** | Replacements captured in the warning window, a premium tier, service visits, evidence-based warranty (≈1.5 % of revenue today). Break-even: winning 48 % of replacements in the window offsets longer battery life. |
| **Biggest risk?** | Real tubular aging may be harder to predict than our simulator. That's why Gate 1 comes first, and why shedding, safety, grid logging and the signed log don't depend on the ML. |
| **What have you actually built?** | A tested codebase for every engine, a firmware host build, the live 3D simulation you saw, a CAD drawing and a priced bench design. Not yet: hardware on a real battery. |
| **Why should we fund this?** | Low cost to test (one inverter, bench parts, lab time), clear pass/fail gates, and it uses assets only V-Guard has. |
| **If you had one more month?** | Flash the ESP32, wire the bench with a real Prime inverter and battery, and show the outage → shed → reset on real hardware. |

---

## 6 · Tough follow-ups and calm answers
- **"8 points error is useless."** → "On synthetic data, yes, it's weak. It proves the pipeline. Your aging data is what makes it accurate, and we've defined ≤ 3 points as the bar to ship."
- **"We already have water-topping reminders."** → "Those are timer-based. Sentinel measures charge acceptance, efficiency and heat stress, so it warns because of the battery's condition, not the calendar."
- **"Customers won't allow circuits to be cut."** → "They choose the tiers, can override, and the essentials are never cut. It's opt-in load management, not a black box."
- **"Why not just a bigger battery?"** → "That costs ₹5–10 k more and still dies without warning. Sentinel costs a fraction of that and makes any battery last longer where it matters."
- **"Is 2.6 mA measured?"** → "No, it's a design estimate from datasheets; measuring it is on our Tier-0 list."

---

## 7 · Closing line if asked "anything else?"
> *"Sentinel turns V-Guard's inverter from a fast switch into a system that knows its battery, protects what matters in an outage, and gives V-Guard data no competitor can buy. It's designed around assets only V-Guard has: the battery factory, the Kochi lab and the dealer network. We'd love to take it to Gate 1 with you."*
