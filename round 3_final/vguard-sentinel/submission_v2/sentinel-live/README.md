# Sentinel Live — finale simulation + proof of concept

A 3D, animated simulation of V-Guard Sentinel built on the team's own design documents (`vguard-sentinel-main/prototype/01–05`, `design/03, 05, 06, 07, 12`, dashboard fixtures, household-simulation defaults). Every threshold in the simulation comes from those files. The single source for the numbers is `src/sim/params.js`.

## Open it
- **At the venue (offline):** double-click `../Sentinel-Live.html`. It is one self-contained file with no network calls. Use Chrome or Edge, full screen (F11), at 1600×900 or larger.
- **Dev:** `npm install` → `npm run dev` → http://localhost:5173. Rebuild the single file with `npm run build`, then copy `dist/index.html` to `../Sentinel-Live.html`.

## Tab 1 — Village Live
Six Kerala homes (hip Mangalore-tile roofs and flat roofs with water tanks) are fed from one DISCOM feeder and transformer. Each home has a real inverter, a tubular battery, a DB with NC contactors and appliances, all wired. Particles show the power: **gold** is mains, **cyan** is battery, **violet** is Sentinel sensing, and **red** is a contactor coil.
- **Home 1 and Home 6 are identical** (same 150 Ah battery, same loads). Home 6 has no Sentinel.
- **Home 2** has a CPAP on the jumper-locked medical channel. **Home 5** has an ageing battery (SoH 68 %, "Replace in 6–14 wk").
- The scheduled roster outage runs **19:00–23:00**, which is the 4 h default from the household simulation.

**Run-sheet (≈ 3 min at 60×–180×):**
1. Start at 18:40, then ⏭ 18:58. The feeder drops at 19:00. Every inverter transfers, the street lights go out and the flow turns cyan.
2. Click **Home 1** and switch **Power corner** on. You see the battery, shunt, Sentinel Core, CT, inverter and DB contactors, with the outage vote (s1 + s3) in the panel.
3. ⏭ 20:20. Home 5 defers T2 at 55 % and sheds T3 on the endurance hard floor. Home 1 defers T2 at 20:23, so the bedroom goes dark and its fans stop.
4. ⏭ 21:55. At **22:03 Home 6 goes DARK** (fridge, router and lights are all lost). The identical Home 1 still has its fridge, router and hall light.
5. In a Sentinel home, press **Reset MCU**. Every coil drops and all loads come back. After the reboot and outage re-detection, T2/T3 are shed again. **Freeze firmware** shows the 2 s supervisory-timer path.
6. **Sag** / **Swell** log Grid Shield events. **X-ray** lifts every roof. **Sentinel OFF** shows the whole village without the product.

## Tab 2 — Inverter + Sentinel (proof of concept)
This is a V-Guard Prime-class inverter cut open, with the **Sentinel-Embedded daughter-board** fitted inside. The board carries C1–C14 as in prototype/03, with the HV/SELV moat on the silkscreen. The bench is the Tier-0 layout from prototype/05: a 12 V 150 Ah tubular battery, a mains MCB, a 4-channel NC contactor panel and the loads (lamp + router T1, table fan T2, iron T3, CPAP MED).
- **Hover or click any part** to see its ID and role: I1–I11 for the inverter, C1–C14 for Sentinel, X2/X4/X7, B1 and the MCB.
- **Camera presets:** Overview · Inside · Sentinel board · Relay I2 · Contactors + loads · Battery. The casing can be set to Closed, Lid off or X-ray.

**Run-sheet (mirrors the prototype/05 finale script):**
1. Click **MAINS MCB** (the panel button or the 3D MCB). The scope drops to slow-motion: the relay armature swings, AC-OUT shows the 8 ms gap and changes from gold (mains) to cyan (bridge), and the timeline stamps `+0.0 ms S2 → +8.0 ms S3`. Sentinel confirms the outage at ~1.5 s from votes s1 + s2 (opto mode pin) + s3.
2. Switch the **Iron** on and watch the backup time fall. Move the **SoC slider** below 40 %: CH3 clicks open and the iron goes cold. Below 55 %, the fan is deferred.
3. Press **Reset MCU**. The coils drop and the iron and fan come back. The charger link reverts to factory setpoints.
4. Close the MCB. After S6 (5 s) the unit returns to S1 and the charger runs bulk (gold flow into the battery).
5. Move the **Battery temp** slider. Absorption and float follow −24 mV/°C through the DAC, and the charge current derates above 45 °C down to 0 at 58 °C.
6. Step the **SoH replay** (2 → 40 → 70 → 95 weeks). Then use **Verify chain** → **Alter one byte** → the chain breaks.

## Tab 3 — Engineering
This tab covers the system boundary, the two SKUs, the four engines, the shed ladder, the fail-safe chain, the executed evidence (from `prototype/00-Status-Crosswalk.md`) and the figures produced by the prototype code. Those figures are copied from `vguard-sentinel-main/deck/assets` into `src/assets/deck/`.

## What is simulated, stated plainly
- The battery uses an equivalent-circuit model (OCV + R_int), not the team's trained EKF. SoH grades step through `dashboard/fixtures/soh_replay_steps.json` (replayed synthetic aging).
- NILM labels are emulated from the known appliance (ΔP ≥ 25 W threshold, confidence by size). The real detector lives in `prototype/code/nilm`.
- The health-log chain uses real SHA-256. The ECDSA signature by the ATECC608 is represented, not computed.
- All 3D assets are generated in code (three.js / react-three-fiber). No inverter, tubular battery, DB or contactor models exist in CC0 libraries, and generating them keeps the file fully offline.

## Stack
React 19 · three.js 0.186 · @react-three/fiber 9 · drei 10 · @react-three/postprocessing 3 (bloom, vignette, ACES) · Vite 8 + vite-plugin-singlefile · Anton / DM Sans / JetBrains Mono (bundled via Fontsource, OFL).

```
src/sim/        params.js (all numbers + sources) · engine.js (inverter S1–S6, battery, charger, Sentinel firmware behaviour) · village.js · sha256.js
src/village/    VillageScene (sky, feeder, poles, lines, palms) · House (shell, x-ray, interior, wiring) · VillageTab (UI)
src/inverter/   InverterModel (I1–I11) · SentinelBoard (C1–C14) · BenchScene (battery, MCB, contactors, loads) · InverterTab (UI, scope)
src/three/      Appliances · Power (battery, inverter, Sentinel box, DB) · Flow (animated wires) · Nature · SkyRig
src/theory/     Engineering tab
```
