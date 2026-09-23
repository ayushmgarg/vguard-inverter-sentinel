# Research Notes — AI Core Hardware & BOM (cited)

## MCU / edge-AI SoC
- **ESP32-S3 (RECOMMENDED, low-cost):** 2×LX7 @240 MHz + vector DSP (~2.5× INT8), 512 KB SRAM (+PSRAM), **Wi-Fi + BLE 5 on-chip**, ~₹250–450. Only option folding radio+NN core in one ~₹300 part (saves ₹200–400 radio BOM). Runs the small SoH/PQ/anomaly models here.
- Step-ups: **STM32N6** (M55+Helium + Neural-ART NPU ~600 GOPS, 3 TOPS/W, ~₹700–1200) for heavy models; **STM32H743** (M7@480, ~₹500–900, no radio); **Ambiq Apollo4 Blue** (M4F, **3 µA/MHz**, BLE, ~₹350–600) for always-on µA; NXP i.MX RT1060; Alif Ensemble E7 (2×Ethos-U55, overkill).

## Sensing front-end
- **Current (DC bus / coulomb counting):** INA226 (16-bit, ±0.1%, ~₹60 w/ 10 mΩ shunt) basic; **INA228 (20-bit ΔΣ + HW charge accumulator)** premium (offloads SoC integration).
- **AC / isolated current:** ACS712 (±20 A, ~1.5%, ~₹40); ACS758 (±50–200 A); **TMCS1100 (±600 V isolation, ±0.4%, ~₹210–330)** best-accuracy isolated.
- **Isolated voltage (150–300 V bus):** HV divider → **AMC1311** (reinforced 5 kV, high-Z input, gain=1) — the correct part. AMC1200 for isolated shunt.
- **Temp:** NTC 10 kΩ (~₹5–20); **TMP117** (±0.1 °C, ~₹200–350) premium.
- **Vibration/acoustic:** ADXL345 (±16 g, ~₹150–300); IIS3DWB (industrial ~6 kHz, ~₹800); I²S MEMS mic ICS-43434/SPH0645 (~₹100–250) for arc/corona/bearing acoustic CNN.
- **Coulomb-counting ADC:** ~15-bit/3 µV LSB pure; hybrid (CC + OCV correction) relaxes to 10–12-bit; INA226/228 satisfy. Offset > bit-depth in importance.

## Load control (16 A / 25 A)
- **Relay/contactor (recommended — cost + fail-safe galvanic open):** 16 A relay ~₹40–120; 25 A modular contactor ~₹250–600. Slower (100s ms — fine for shedding).
- **SSR:** 30 ms, no wear, but heat/leakage/cost, no true galvanic open.
- **Drivers:** ULN2003A (7-ch Darlington w/ flyback, ~₹15–30) or logic-level N-MOSFET + flyback.
- **Fail-safe:** de-energize = desired default on fault/power-loss; per-channel fusing; derate for inductive loads.

## Power / connectivity / mechanical
- **Power:** wide-Vin buck to 3.3 V — LM2596 (budget, ~5 mA Iq high) vs MP2315/MP1584 (µA-class Iq, preferred always-on) + LDO for clean ADC rail; reverse-polarity + input TVS.
- **Connectivity:** ESP32-S3 BLE (commissioning/app) + Wi-Fi (opportunistic sync); all AI offline; buffer to flash/PSRAM.
- **Mechanical:** PCB ~80×60 mm; module ~95×70×30–40 mm; **PC/ABS UL94 V-0**; **IP20** indoor; DIN-rail (EN 60715) clip or screw/3M-VHB; **4× M3 on ~72×52 mm**; screw/pluggable terminals (5.08 mm, Phoenix MSTB) for HV + JST-XH/PH for LV; segregate HV/LV for creepage.

## Standards (India) — the real gate
- **IS/IEC 62368-1:2023** (replacing IS 13252-1) — mandatory BIS electronics safety; a mains-connected module falls here (PRIMARY gate).
- **IEC 62040** — host UPS (module must not degrade host compliance).
- **IEC 61000** EMC/immunity: 61000-6-1 (residential immunity), -4-2 (ESD), -4-3 (radiated), -4-5 (surge) — needed for CE + noisy inverter coexistence; measure PQ per **IEC 61000-4-30 Class-S-like**.
- **IS 16046-2 / IEC 62133-2** — if any Li cell/coin cell onboard (BIS CRS).
- **IS 302-1** general appliance-safety baseline (accessory scope — confirm w/ BIS consultant). **RoHS/REACH; CE (LVD 62368-1 + EMC 61000).**
- Efficiency: home UPS/batteries/stabilisers have NO BEE star (open differentiation niche).

## Isolation (safety backbone)
Entire HV side (divider, shunt HV side, Hall primary) = hazardous zone; hard galvanic barrier (AMC1311/AMC1200 capacitive; opto/digital isolators for logic) to MCU 3.3 V; creepage/clearance for 300 V + transients (design 400 V+); PCB slot under barrier; fuse taps; TVS/MOV on HV node; prefer contactless Hall on AC legs.

## BOM (approx India, 1k vol) — HONEST framing
- **BASIC ≈ ₹600 standalone** (ESP32-S3 ₹250; INA226+shunt ₹60; ACS712 ₹40; 2×NTC ₹15; ADXL345 ₹30; 16 A relay+ULN2003 ₹55; buck ₹45; V-0 enclosure ₹60; connectors/passives ₹45).
- **PREMIUM ≈ ₹3,290 standalone** (adds INA228 ₹300; AMC1311+HV divider ₹350; TMCS1100 ₹300; TMP117 ₹250; **IIS3DWB ₹800** & isolation chain are the big drivers; 25 A contactor+opto ₹450; I²S mic ₹150; sync buck ₹120; DIN enclosure ₹120).
- **KEY HONESTY:** the ₹150–800 target is realistic only as **INCREMENTAL** cost over a metering-capable inverter (shunt/relay/MCU/power already present). Standalone board = ~₹600 (basic) to ~₹3,300 (full premium). To keep premium <₹800 standalone: drop IIS3DWB (use ADXL345), use ACS758 instead of TMCS1100+AMC1311, reuse host relay → ~₹750–850.
- Cost levers: reuse host shunt/relay/MCU (biggest); ADXL345 vs IIS3DWB (−₹770); INA226 vs INA228 (−₹240); Hall vs AMC1311 chain (−₹350).

Sources: Espressif ESP32-S3 datasheet; TI INA226/228, TMCS1100, AMC1311/1200, TMP117, ULN2003, LM2596; ADI ADXL345; ST IIS3DWB, STM32N6/H743; Ambiq Apollo4; BIS IS/IEC 62368-1 & IS 16046-2; IEC 62040 / 61000 / 61000-4-30; UL94; EN 60715.
