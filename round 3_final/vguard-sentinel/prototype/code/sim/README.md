# sim/ -- synthetic Indian tubular lead-acid duty-cycle simulator

Implements design `02-TinyML-SoH-RUL-Pipeline.md` SS4.3 (electrical/ageing model
grounded in `01-Battery-State-Estimation.md` SS1.3/SS1.5/SS2.1/SS2.5).

## What is implemented

- **Duty cycle**: Poisson outage arrivals with a seasonally-modulated rate (0.3-3/day,
  design 02 SS4.3), lognormal outage duration (median 1 h, clipped 0.2-6 h), a
  150-900 W appliance-switching household load through an 83-87% efficient inverter.
- **Charger**: CC at 10-15% of C10, CV holding 14.4 V (temperature-compensated, design
  01 SS5a coefficient), float at 13.7 V.
- **Electrical model**: 1-RC Thevenin (SoC, V1, R0), OCV(SoC) table (design 01 SS2.1),
  R0/R1 typical values scaled by SoC and temperature (design 01 SS1.5), Peukert
  n in [1.15, 1.35] (design 01 SS2.5). A Shepherd-style polarisation term
  (`sim/physics.py:r_polarization_ohm`) is added on top of R0 -- without it, a linear
  mΩ-scale R0 alone cannot produce the ~1.7 V rise from rest-OCV (~12.7 V) to the 14.4 V
  charge target, so CC would never reach the CV setpoint. This is exactly the
  "Shepherd/Thevenin" combination design 02 SS4.3 asks for.
- **Temperature**: synthetic Chennai/Delhi diurnal+seasonal ambient profile plus a
  first-order self-heating term from I^2*R0.
- **Ageing**: a Schiffer-style weighted-Ah-throughput model (design 02 SS1.3 weights,
  a=1.0, b=0.3) drives capacity fade and R0 growth once per cycle from that cycle's
  weighted Ah and Arrhenius-integrated thermal stress; a separate sulphation index
  (grown from Arrhenius-weighted low-SoC dwell time) drives coulombic-efficiency and
  charge-acceptance decline. All rate constants are domain-randomised per battery
  (`sim/physics.py:BatteryParams`) within ranges tuned so soh_true crosses the 80% EoL
  line for a meaningful (not all) fraction of a randomised fleet within the cycle
  budget -- see the sanity numbers in the final report.
- **Label noise**: `--label-noise-std` (points) optionally perturbs the reported
  `soh_true` per cycle (design spec: "±1.5 pt label noise option"); the internal state
  driving the dynamics stays clean regardless.

## How to run

```
python -m sim.battery_sim --n 24 --out data/sim_1hz/ --seed 0
python -m sim.battery_sim --n 8 --out data/sim_1hz/ --seed 0 --cycles 45
```

Key flags: `--cycles` (max outage/recharge cycles per battery, default 300),
`--cycle-hours-min/max` (default 8/12, design 02 SS4.3), `--float-cap-hours` (caps how
much float time is emitted at 1 Hz before the remaining calendar gap to the next
Poisson-drawn outage is fast-forwarded analytically -- see "accelerated mode" below).

Output per battery: `data/sim_1hz/battery_NNN.csv` with the exact CONTRACTS.md SS1
columns (`t, I, V, T, grid, P_load, soc_true, soh_true`), plus `manifest.csv` (one row
per battery: C_rated, R0/R1/C1, Peukert n, site, etc. -- needed by `features/` because
CONTRACTS SS1 does not carry C_rated in the stream itself) and `sim_cycle_debug.csv`
(sim's own internal per-cycle bookkeeping, not part of the contract, useful for
calibration/debugging only).

## Runtime and "accelerated mode"

The 1 Hz loop is a plain Python per-second state machine (no numba/JIT available under
the module's numpy/scipy/pandas-only constraint). After removing per-row function-call
overhead it runs at roughly 60-90k rows/sec on a laptop core. A literal simulation of
the full multi-day calendar gaps implied by a 0.3-3/day Poisson outage rate would be
far too slow, so "accelerated mode" emits the electrically interesting spans (the
outage, the recharge, and up to `--float-cap-hours` of float) at 1 Hz, and
analytically fast-forwards any remaining calendar gap before the next Poisson-drawn
outage (advancing the diurnal/seasonal clock and accumulating Arrhenius calendar
stress at the ambient average, without emitting rows). This keeps each emitted "cycle"
in the 8-12 h band design 02 SS4.3 asks for while staying tractable.

Measured on this machine: `--n 8 --cycles 45` (the numbers used for the delivered
`data/sim_1hz/` + `data/features_sim.csv`) completed in **~4 minutes**. The full
design-target `--cycles 300` (200-400 cycles/battery) is proportionally slower --
budget several tens of minutes for `--n 24 --cycles 300`; regenerate with a smaller
`--cycles` if you need a quick smoke test. The 1 Hz streams are regenerable from the
seed and are intentionally **not** committed to git; only `data/features_sim.csv` is.

## What this is not

- **Synthetic, not real tubular data.** No bench characterisation exists yet for R0/R1/C1,
  the Schiffer/sulphation rate constants, or the Shepherd polarisation coefficient --
  every one of those is a domain-randomised assumption, not a calibrated number. The
  aging campaign (design doc 04) is what would replace these.
- The g(SoC)/h(T) sag-normalisation tables and kappa_CA charge-acceptance temperature
  coefficient used downstream in `features/` are likewise uncharacterised assumptions.
- Rest-OCV conditions (design 01 SS5b: charger off, |I| very small, sustained hours)
  essentially never occur in this load model -- the household load is always
  150-900 W, well above the ~0.5-1% C threshold -- so the `ocv_err` feature is
  populated only rarely. This is a known, disclosed limitation of the synthetic duty
  cycle, not a bug in the detection logic itself.
- No hardware-in-the-loop, no firmware-compiled feature code (design 02 SS4.3 mentions
  running the *firmware* feature code on host data for Stage B fine-tuning; this
  prototype's `features/cycle_features.py` is a host Python re-implementation of the
  same algorithm, not the C firmware).
