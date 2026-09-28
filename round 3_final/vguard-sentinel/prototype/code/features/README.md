# features/ -- per-cycle feature pipeline

Implements design `02-TinyML-SoH-RUL-Pipeline.md` SS1.0-1.10: streaming cycle
segmentation and the 14 dynamic + 6 static feature channels, `features/schema.py`
(the single source of truth for names/order per CONTRACTS.md SS2).

## What is implemented

- **Cycle segmentation state machine** (design 02 SS1.0): FLOAT->DISCHARGE /
  DISCHARGE->CC / CC->CV / CV->FLOAT on the same current/voltage thresholds as the
  design doc, working in CONTRACTS.md's `I` sign convention (+charge, -discharge --
  note the doc's own pseudocode is written in design 01's opposite convention, so
  every current-sign threshold and the `R_step = -dV/dI` formula had to be re-derived
  with the sign flipped for this module).
- **FULL_CHARGE / full-charge dwell** (design 01 SS5a): implemented as an independent
  V>=13.5V AND |I|<tail dwell tracked across CC/CV/FLOAT, *not* gated to remaining
  labelled "CV" for the full 30 min -- a real charger's (and this sim's) target
  voltage moves from 14.4V to 13.7V the instant tail current is reached, so requiring
  the dwell to complete before that label change would almost never fire.
- **sag_ref** (SS1.1), **R_int proxy** (SS1.2, from the same dV/dI transient estimate
  since the EKF module is separate) with a hook: if `battery_NNN_rint.csv`
  (columns `t,r_int_ohm`) exists next to a stream, it is used instead of the proxy.
- **Ah throughput / Schiffer weight, DoD** (SS1.3-1.4), **Arrhenius stress
  integrals** (SS1.5, same 6400 K/86400s form as sim), **coulombic efficiency with
  staleness** (SS1.6), **ICA dQ/dV on the CC leg with validity+staleness** (SS1.7),
  **charge acceptance CA_60/cv_frac** (SS1.8), **rest-OCV-implied SoC error** (SS1.9,
  see limitation below), **baselines from the first 10 cycles** driving every
  ratio/shift feature (SS1.10).
- Its own simple coulomb-counting SoC proxy (anchored to 1.0 at each detected
  FULL_CHARGE), since the EKF (design 01) is a separate module.
- Labels: `soh_true` passed through from the stream; `rul_efc_true` = EFC remaining
  to the first cycle where `soh_true <= 80`, NaN for a battery that never reaches EoL
  in the recorded data (CONTRACTS.md SS2).

## How to run

```
python -m features.cycle_features --in data/sim_1hz/ --out data/features_sim.csv
```

Reads `manifest.csv` (for `C_rated_Ah` per battery -- not carried in the 1 Hz stream
itself) and every `battery_NNN.csv`, writes one row per detected cycle across all
batteries to a single CSV with the exact `features/schema.py:ALL_COLUMNS` order.

Runtime: roughly comparable to the sim run that produced the input (a few minutes for
the delivered 8-battery dataset).

## Assumed / uncharacterised constants (documented, not fabricated precision)

Several design-doc quantities are described qualitatively but not given bench-fit
values. This module makes an explicit, documented choice for each rather than
guessing silently:
- `_sag_g_soc` (the "8-entry SoC->70% table" of SS1.1): implemented as the inverse of
  the same R0(SoC) shape used in `sim/physics.py`, normalised to 1.0 at 70% SoC.
- `_sag_h_temp` kappa_R = 0.015 /degC (SS1.1 gives a 0.01-0.02 range).
- `kappa_CA` (SS1.8 charge-acceptance temperature correction) = 0.01 /degC, and the
  SoC correction `c(SoC)` is treated as identity (1.0) -- SS1.8 does not specify it.

## What this is not

- **Not validated against real hardware or the firmware feature code** -- this is a
  host Python re-implementation of the algorithm in design 02, not the C module that
  will eventually run on the ESP32-S3.
- **`ocv_err` is rarely populated on this synthetic dataset.** Design 02 SS1.9's rest
  condition needs the charger off AND |I| <~0.5% of C sustained for a long time; the
  sim's household load (150-900 W) never gets that quiet, so true rest almost never
  occurs. The detection logic is implemented and correct; it just rarely fires here.
  A real household with genuinely idle overnight stretches would populate it far more.
- **R_int proxy is a simple dV/dI transient estimate, not the EKF's Kalman-filtered
  R0.** The `external_r_int` hook exists precisely so a real EKF output (or a future
  `ekf/` module run over the same stream) can be substituted without changing this
  module's segmentation or feature logic.
- Segmentation naturally does not map 1:1 to sim's own internal cycle bookkeeping
  (`sim_cycle_debug.csv`) -- by design, this module re-derives cycles purely from the
  I/V stream, the way a real device with no access to sim internals would have to.
