# 03 — Engine 1c: Adaptive Charging Policy & Charger-Control Interface (worked out to a T)

**Resolves Gap Register:** H7 (adaptive charge policy + interface), H26 (charger-control feasibility). Feeds design change D2 in 12.

## 0. The load-bearing finding
Indian 600 VA–1.5 kVA home inverters are built around an **analog PWM controller (SG3525 / TL494)** whose float/boost setpoints are fixed by resistor dividers and a factory trim pot. **There is no microcontroller in the charge loop** on most of them, and where an 8-bit MCU exists (display/beeper/mode logic) it is not exposed on any documented bus. Only solar-hybrid PCUs carry RS-485 Modbus, with vendor-proprietary, partner-only register maps. What every unit exposes: a **battery-type selector** (tubular / SMF / Li) that switches between fixed profiles, and an eco/UPS mode toggle that only changes the transfer window.

**Consequence (must be stated everywhere):**
- **Sentinel-Embedded** (new V-Guard inverter): V-Guard owns the charger board and can add a control path → adaptive charging is real.
- **Sentinel-Retrofit** (module on an existing inverter): **no setpoint control is possible**. The module is **advisory-only** on the source side and acts on the **load side** via the contactors.
- The report's blanket **"15–30 % battery-life extension via smart charge/thermal profiles" is supportable only for the Embedded SKU**. For Retrofit the honest claim is "diagnostic visibility, correct-profile advice, and load-side protection".

## 1. Embedded interface — proposed design
### 1.1 Hardware path (preferred): DAC injection into the existing PWM feedback node
An I²C DAC (MCP4725, < ₹50) injects a programmable offset into the SG3525/TL494 error-amplifier feedback divider. Zero change to the vendor's charger firmware (there may be none); the Sentinel Core owns the whole policy. Alternative: if the main board already carries an MCU, expose a UART and implement §1.2 there.

**Hardware safety ceiling, independent of any software:** a comparator/zener clamp on battery voltage disables the charger drive above **15.5 V** (12 V nominal) and an NTC-fed thermal cut-out above **55–60 °C** — a Sentinel firmware bug cannot cook the battery.

### 1.2 UART command set (Sentinel Core ↔ charger MCU or DAC bridge), 115200-8N1, byte-stuffed, CRC-16/CCITT
```
[SOF 0xAA][CMD][LEN][PAYLOAD…][CRC16_L][CRC16_H][EOF 0x55]
```
| CMD | Name | Payload | Function |
|---|---|---|---|
| 0x10 | SET_FLOAT | uint16 (mV/cell ×100) | float setpoint |
| 0x11 | SET_ABSORPTION | uint16 mV/cell, uint16 timeout_min | absorption setpoint + max hold |
| 0x12 | SET_EQUALISE | uint16 mV/cell, uint16 duration_min, uint8 enable | scheduled equalisation |
| 0x13 | SET_CURRENT_LIMIT_PCT | uint8 0–100 | derate charge current (thermal) |
| 0x14 | SET_TEMP_COMP | int16 µV/°C/cell | optional; preferred: Sentinel pre-computes and sends 0x10/0x11 |
| 0x20 | GET_STATUS | — | mode (float/boost/equalise/off), fault flags, V_batt, I_batt if sensed |
| 0x30 | HEARTBEAT | uint32 seq | **≤ 2 s period; on loss the charger reverts to factory defaults** |
| 0x7F | NACK | uint8 code | range/CRC error |
The charger side enforces absolute limits in its own firmware/hardware regardless of what 0x10/0x11 request — defence in depth.

**Charger-state signal** (GET_STATUS mode, or a dedicated GPIO) is also what the EKF needs for the rest-OCV guard (01 §5b) and transient rejection (01 §6.1).

## 2. Retrofit — honest capability
1. **Advisory**: compute ideal temperature-compensated setpoints and the correct battery-type profile; tell the user/installer ("battery is 6 °C above reference; set selector to tubular profile; consider shade/ventilation").
2. **One relay-mediated intervention, model-specific**: some budget units bring the battery-type selector out as a dry-contact header. A Sentinel relay can then toggle between two *factory* profiles — a coarse 2-state approximation, only where verified per model; never claimed universally.
3. **Load-side protection** (fully available): shed T2/T3 at high battery temperature or deep discharge (05), which does reduce wear even without charger control.
4. **Pre-charge before predicted outage** becomes an advisory notification (05 §2.3).

## 3. The charging policy (both SKUs compute it; only Embedded applies it)
### 3.1 Setpoints for tubular flooded lead-acid (per 2 V cell, 25 °C)
| Parameter | per cell | 12 V pack | Source |
|---|---|---|---|
| Float | 2.23–2.30 V | 13.4–13.8 V | Amara Raja FCBC (27.0 V on 24 V = 2.25 V/cell); Wikipedia float-voltage summary |
| Absorption / boost | 2.40–2.47 V | 14.4–14.8 V | Rolls/Trojan flooded guidance; Amara Raja boost |
| Temperature coefficient | −3 to −5 mV/°C | −18 to −30 mV/°C | Victron default −4 mV/°C/cell (−24 mV/°C per 12 V); Rolls/Trojan −5 |
| Equalisation | 2.50–2.58 V, monthly, 2–4 h | 15.0–15.5 V | Rolls guide (3–4 h or 50–75 % of absorption time) |
| Current derating | begin > 40–45 °C, stop ~55–60 °C | — | industry consensus; configurable table, not a constant |
### 3.2 Policy loop (every 60 s)
```
V_target(T) = V_25 + coeff·(T_batt − 25), clamped to the hardware ceiling
if T_batt > 45: current_limit = 100 − 4·(T_batt − 45) %   (→ 60 % at 55 °C);  if T_batt ≥ 58: charger OFF, alert
absorption timeout: adaptive — end when tail current < 1–2 % C20 (01 §5a) or after t_abs,max (2–4 h at 25 °C, longer when cold)
equalisation: schedule when (a) ≥ 30 days since last, AND (b) SoH pipeline shows η_c falling or IC peak shifting up (sulphation signature, 02 §1.6–1.7), AND (c) T_batt < 40 °C, AND (d) no outage predicted in the next 6 h (05 §2). Duration 2–3 h, monitor gassing (V rise + T rise) and abort on T > 50 °C
pre-charge (05 §2.3): raise SoC target / hold absorption when P(outage, 3 h) > 0.55 with confidence ≥ 0.5
water-loss guard: cap cumulative equalisation hours per quarter (flooded cells lose water); prompt topping-up
```
### 3.3 Where the "15–30 %" comes from and how it is bounded
Life halves per ≈ +10 °C (02 §1.5); un-compensated fixed setpoints overcharge in summer (water loss, corrosion) and undercharge in winter (sulphation). Temperature compensation + timely equalisation + avoiding partial-SoC dwell address the two dominant Indian failure modes (sulphation, water loss). The 15–30 % figure is a **target to be validated in the aging campaign (04) as a controlled comparison: compensated vs fixed-profile charging at 40 °C**; it is not a shipped guarantee. It applies to the Embedded SKU only.

## 4. Summary for the judge
"On a new V-Guard inverter, Sentinel sets float, absorption, equalisation and charge-current limits through a small DAC on the charger's PWM feedback node, with a hardware voltage/thermal ceiling the software cannot exceed and a 2-second heartbeat that returns the charger to factory defaults if the Core dies. On an existing inverter there is no such control path in the industry — Sentinel is advisory on the charger and protective on the loads. We claim charge-profile life extension only for the embedded variant, and we measure it in the aging campaign."

## References
how2electronics / Tahmid (SG3525 inverter designs) · microcontrollerslab (SG3525 solar inverter) · zbotic.in (ESP32 + Modbus inverter monitor) · Schneider Conext TL Modbus app note · Amara Raja FCBC technical package · Wikipedia, *Float voltage* · Rolls Battery, *Calculating proper charge settings for flooded lead-acid* · Victron community, *MultiPlus charge-voltage temperature correction*; Victron blog, *Lead-acid charging in cold weather* · Microchip MCP4725 datasheet.
