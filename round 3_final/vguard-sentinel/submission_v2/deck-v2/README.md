# Finale deck v2 — sources

- `../VGuard-Sentinel-Finale-Deck-v2.pptx` (20 slides: 16 main + 4 Q&A appendix) and its PDF.
- Speaker notes on every slide carry the talk track with timings (≈ 6 min slides + ≈ 4 min live demo on slide 12).
- Rebuild: `python build_v2.py out.pptx` (needs python-pptx, Pillow, lxml; reads `assets/` and `trace.json`).
- `trace.json`: Home 1 vs Home 6 SoC traces exported from `../sentinel-live/src/sim/engine.js` (slide 7 native chart).
- `cad.py`: enclosure/PCB drawing from prototype/02–03 (90 × 70 × 35 mm, PCB 80 × 60). `sketch.py`: Tier-0 bench wiring sketch (prototype/05).
- `shoot.js`: headless Edge screenshots of `../Sentinel-Live.html` (puppeteer-core).
- `nilm_events.png` / `pq_dip.png` regenerated with the team's own `prototype/code/nilm` and `pq` modules.

Corrections vs the v1 deck:
- Autopilot chart: v1 used a hand-drawn curve that got steeper after T2 was deferred, which is physically backwards. v2 plots the real simulation (Home 1 flattens after shedding; Home 6 hits cut-off at 22:03).
- NILM chart: v1 was labelled "at the inverter output" but showed up to 6 kW. That is whole-home power (the optional mains CT), because the inverter is rated ≈ 800 W.
- PQ chart: v1 claimed "magnitude error < 1 %". The detector actually measures the swell at 1.165 pu vs 1.15, so v2 states the measured values.
- Cost title: v1 said "single-digit % of a ₹15 k battery". ₹2,050 is 14 %, so v2 says 5–14 %.
- Problem stat: the v1 figure "~10 y → ~3.3 y" was sourced to VRLA design life, not tubular batteries. v2 states the Arrhenius halving per +10 °C instead.
- Removed v1's unverified "₹300 microcontroller" line.
- Firmware figure: v1's "RAM for ML ≈ 32 KB" didn't match doc 04 (arena 16 KB + interpreter 4 KB).
- CAD: v1 reused the R2 AutoCAD shot ("MCU + NPU", 2 relay drivers). That conflicts with D16 and the 4-channel design, so v2 redraws it from the round-3 spec.
