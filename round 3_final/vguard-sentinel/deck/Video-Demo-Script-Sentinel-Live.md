# Sentinel-Live — step-by-step video demonstration script

Source app: `~/Downloads/Sentinel-Live/Sentinel-Live.html` (single offline file). Open in Chrome, press F11, window ≥ 1600×900. Record at 1080p60 with system audio off; add voice-over afterwards. Target length 3:30–4:00. Every threshold shown comes from `src/sim/params.js`, which mirrors design 05/03/07.

## Before recording (2 min)
1. Open the HTML, wait for the 3D scene to settle (particles flowing gold = mains present).
2. Click the **Village Live** tab; set speed **60×**; confirm the clock reads about 18:40 and the pill says **MAINS**.
3. Do one dry run of every click below so the reboots and camera moves are familiar. Hide the mouse cursor in your recorder if it offers that.

## Act 1 — The village (≈ 80 s)  · tab: Village Live
| # | Do | Watch for | Say |
|---|---|---|---|
| 1 | Hold on the wide village shot for 5 s at 60× | six homes, one feeder, gold flow | "Six Kerala homes on one DISCOM feeder. Home 1 and Home 6 are identical — same 150 Ah battery, same loads — except Home 6 has no Sentinel." |
| 2 | Click **⏭ 18:58**, then wait | at 19:00 the feeder drops, street lights go out, flow turns **cyan**, pill flips to **OUTAGE** | "19:00 — the scheduled roster outage. Every inverter transfers in under 10 milliseconds. The inverter is fast; the battery is blind." |
| 3 | Click **Home 1**, then toggle **Power corner** on | battery, shunt, Sentinel Core, CT, inverter, DB contactors; panel shows the outage vote **s1 + s3** | "Sentinel confirmed the outage by a two-of-three vote — mains RMS and discharge onset — within two seconds. Nothing here needs the internet." |
| 4 | Click **⏭ 20:20**; keep Home 1 selected | Home 5 defers T2 at 55 % and sheds T3 on the endurance floor; Home 1 defers T2 at ~20:23: bedroom dark, fans stop; fridge, router, hall light stay | "Home 5 has an ageing battery — 68 % state of health. Sentinel already sheds its heavy loads. Home 1 defers the bedroom at 55 %. The essentials never move." |
| 5 | Click **⏭ 21:55**; switch speed to **180×** and wait ~10 s | at **22:03 Home 6 goes DARK**; Home 1 still lit | "22:03. Home 6 — the identical home without Sentinel — is dark. Fridge, router, lights, all gone. Home 1 still has its fridge, router and hall light. Same battery. Different intelligence." |
| 6 | With a Sentinel home selected, press **Reset MCU** | every coil drops, all loads come back; ~6 s later reboot, outage re-detected, T2/T3 shed again | "Now the ugliest failure: the processor dies. Coil off means load on — everything comes back, then Sentinel re-detects the outage and sheds again." |
| 7 | Press **Freeze firmware** | 2 s later the supervisory timer drops the coils | "If the firmware hangs, an independent two-second supervisory timer on the driver board does the same thing. That is hardware, not code." |
| 8 | Press **Sag**, then **Swell**; open the log | Grid Shield entries with magnitude/duration | "Grid Shield logs sags and swells as dated evidence of what the utility did to your appliances." |
| 9 | Toggle **Sentinel OFF**, hold 5 s, toggle back; optionally **X-ray** | whole village without the product | "Same village, no Sentinel." |

## Act 2 — Inside the inverter (≈ 100 s)  · tab: Inverter + Sentinel
| # | Do | Watch for | Say |
|---|---|---|---|
| 10 | Camera **Overview**, then **Lid off**, then **Sentinel board**; hover **C3**, **C6**, **C8** | part IDs and roles (INA228, ATM90E32AS, supervisory timer), HV/SELV moat on the silkscreen | "A V-Guard Prime-class inverter, opened. The Sentinel-Embedded board sits inside: current monitor on the shunt, a metering front-end on the AC output, a secure element, a clock, and a supervisory timer — all on one 80-by-60 board." |
| 11 | Camera **Relay I2**; click **MAINS MCB** | slow-motion: armature swings, AC-OUT shows the **8 ms** gap and turns cyan; timeline stamps `+0.0 ms S2 → +8.0 ms S3`; Sentinel confirms at ~1.5 s from **s1 + s2 + s3** | "Mains lost. The changeover relay swings in eight milliseconds. Sentinel votes on three signals — including the inverter's own mode pin on the embedded board — and confirms in one and a half seconds." |
| 12 | Camera **Contactors + loads**; switch the **Iron** on | backup time falls | "Switch the iron on and the estimated backup time drops — that number comes from the Kalman-filtered state of charge, not from a voltage guess." |
| 13 | Drag the **SoC slider** below 55 %, pause; then below 40 % | fan (T2) deferred at 55 %; **CH3 clicks open**, iron goes cold at 40 %; lamp, router and CPAP untouched | "At 55 % the fan is deferred. At 40 % the iron's contactor opens. The lamp, the router and the CPAP on the hardware-locked medical channel never move." |
| 14 | Press **Reset MCU** | coils drop, iron and fan come back; charger link reverts to factory setpoints | "Reset the processor: every coil drops, every load returns, and the charger falls back to its factory profile. Fail-safe in both directions." |
| 15 | Close the **MCB** | after 5 s (S6) unit returns to S1; **gold** flow into the battery = bulk charge | "Mains is back. Five seconds of stable mains, then the charger runs bulk." |
| 16 | Camera **Battery**; move **Battery temp** to 40 °C, then 50 °C, then 58 °C | absorption/float track −24 mV/°C via the DAC; current derates above 45 °C to zero at 58 °C | "On the embedded board Sentinel owns the charger: set-points follow minus twenty-four millivolts per degree, current derates above 45 degrees and stops at 58. This is where the battery-life claim lives — and only here." |
| 17 | Step **SoH replay**: 2 → 40 → 70 → 95 weeks | grade walks Healthy → Degrading → "Replace in 6–14 wk"; replay banner visible | "State of health is replayed from a synthetic aging trajectory — say so on screen — a bench battery does not age in a week. The grade moves with hysteresis, and the answer is always a window, never a date." |
| 18 | **Verify chain** → **Alter one byte** → **Verify chain** | chain OK, then broken at the altered record | "Every event is hash-chained and signed. Change one byte and the warranty log fails verification." |

## Act 3 — Engineering tab (≈ 25 s)  · tab: Engineering
| 19 | Scroll slowly through the system boundary, the two SKUs, the shed ladder and the evidence ladder | figures generated by the prototype code | "Everything you saw is specified in seventeen design decisions and backed by a codebase with 245 tests. What is proven, what is synthetic, and what still needs hardware are listed separately — on purpose." |

## Closing line (5 s, back on the village at 22:03)
"Coil off means loads on. A window, never a date. Offline first, fleet second. V-Guard Sentinel."

## Say on camera, once (honesty)
The village and bench are simulations built from the team's design documents: an equivalent-circuit battery model (not the trained EKF), emulated appliance labels, a real SHA-256 chain with a represented signature, and code-generated 3D assets. The real algorithms live in the prototype repository and run on host hardware today; the ESP32 build has not yet been flashed.

## Recording tips
- Keep 60× for the village except step 5 (180×); never use 600× on camera — the flow particles smear.
- Pause the recording between tabs; cut on the tab click.
- Leave 1 s of stillness before and after every click so the edit has handles.
- If the reboot (6 s) or the mains-return wait (5 s) feels long, speed the clip 2× in the edit rather than in the app.
