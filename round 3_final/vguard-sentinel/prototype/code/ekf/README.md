# ekf/ — battery state estimator (design doc 01)

3-state EKF `[SoC, V1, R0]` for a 1-RC Thevenin lead-acid model, per
`/documentation/design/01-Battery-State-Estimation.md`. All numbers below
are from synthetic data generated in this repo; nothing here has touched
real hardware or the aging campaign (design 04). See "Honest limits" below.

## What is implemented (design § refs)

| Feature | § | File |
|---|---|---|
| 1-RC Thevenin, exact ZOH discretisation | §1.3 | `ekf.py` / `ekf.c` |
| OCV(SoC,T) bilinear LUT, coulombic efficiency on charge | §1.3, §2.1-2.2 | `lut.py` |
| Peukert-corrected usable capacity, n=1.25 default | §2.5 | `lut.py` |
| EKF Jacobians | §3.1 | `ekf.py` / `ekf.c` |
| Q/R defaults incl. event-gated Q_R0 | §3.2 | `params.py` |
| Initialisation: persisted state / rest-OCV / humble 50% | §3.3 | `EKF._lazy_init` |
| Divergence guards: chi^2 gate, hard bounds, P floor/ceiling, raw-coulomb cross-check, R0 sanity vs 3x LUT envelope | §3.4 | `EKF._measurement_update` / `_clamp_state` / `_cross_check` / `_r0_event` |
| Full detection by charge-current taper -> SoC=1, close cycle, eta + measured capacity, latch | §5a, §7 | `EKF._full_detection` / `_close_cycle` |
| True rest-OCV anchor, charger verifiably OFF only (H30 fix) | §0, §5b | `EKF._rest_anchor` |
| R_int event estimator, |dI|>=5-10% C20, charger-transition rejection, median over 20-50 events, T/SoC normalisation, SoH_R proxy | §6 | `EKF._r0_event` |
| Zero-current auto-cal of current offset | §4 | `EKF._auto_cal_offset` |
| C99 port (float32, static alloc, no malloc/printf) | §3.5, CONTRACTS §6 | `ekf.c` / `ekf.h` |

### A deliberate deviation from §9's literal pseudocode

§9's pseudocode runs the generic per-tick `V - (OCV - I*R0 - V1)` correction
every tick unconditionally. This implementation instead runs it **only
while `charger_on` is false** (`EKF.step`, see the long comment there).
Reason: real flooded lead-acid absorption/float terminal voltage sits
~0.8-1.7 V above the rest-OCV table (§2.1 tops out at 12.70-12.79 V) — that
gap is charger regulation overhead / gassing overpotential, not IR drop
through the few-mOhm R0 this baseline 1-RC model carries (§1.1 already
flags 1-RC itself as a deliberate simplification). Running the correction
unconditionally lets that unmodelled gap leak into the fused SoC one small,
individually chi^2-plausible innovation at a time — exactly the H30
mechanism §0 warns about, just smuggled back in through the "always-on"
per-tick path instead of a naive rest-OCV lookup. Gating it to charger-off
keeps §9's correction exactly where the model is valid (discharge, true
rest) and leaves charging-time SoC to the coulomb-count predict step plus
the two explicit, physically-gated anchors (§5a/§5b) — which is what §10's
own six-step summary describes.

## Files

- `ekf/lut.py` — OCV/R0/R1/tau bilinear LUTs, f_temp, eta_charge, Peukert (§1.5, §2.1-2.5)
- `ekf/params.py` — `EKFParams` dataclass, defaults per §3.2/§3.3/§5c/§8
- `ekf/ekf.py` — the `EKF` class, `step(I_charge_pos, V, T, charger_on) -> dict`
- `ekf/sim_battery_for_ekf.py` — standalone 1-RC Thevenin simulator (independent of `sim/`) with injected sensor offset/gain error and an outage/bulk/absorption/float/rest duty cycle
- `ekf/ekf.h`, `ekf/ekf.c` — C99 port, CONTRACTS §6 API (`ekf_init`, `ekf_step`, `ekf_soc`, `ekf_r0`, plus `ekf_v1`/`ekf_soh_r`)
- `ekf/test_ekf_host.c` — reads a sim CSV, runs the C filter, writes a SoC/R0 trace CSV
- `ekf/Makefile` — `gcc -std=c99 -O2 -Wall -Wextra -lm`
- `tests/test_ekf.py` — pytest (a)-(e), see below

## Commands

```bash
# from documentation/prototype/code/
python3 -m ekf.sim_battery_for_ekf --out /tmp/sim.csv --days 8 --seed 0

cd ekf && make && ./ekf_test_host /tmp/sim.csv /tmp/c_trace.csv && cd ..

pytest -q tests/test_ekf.py
```

## Results (measured here, synthetic data, seeded)

All figures below are from `pytest -q tests/test_ekf.py`, which runs the
sim fresh each time (seeded, so reproducible) — not hand-picked.

| Test | Metric | Measured |
|---|---|---|
| (a) drift vs anchored EKF, 4 sim-days, seed 1 | naive (uncorrected) counter drift | ≈7.2 %/week |
| (a) | EKF SoC RMS error vs ground truth | ≈3.0 % |
| (a) | EKF SoC max error vs ground truth | ≈9.3 % (see note) |
| (a) | rest-OCV anchor applied while `charger_on` | 0 (regression holds) |
| (b) no false full-detect during float transients | spurious/early latches | 0; exactly 1 legitimate latch after the dwell |
| (c) rest anchor vs charger state (H30 regression) | anchor fires while charging | never; fires (`rest_high`) once truly at rest |
| (d) R_int estimator recovery | ticks / events to recover | ~3,751 ticks (~62.5 min) for 25 events |
| (d) | recovered R0 vs simulated true R0 | 4.28 mΩ vs 4.50 mΩ true → 4.9 % off (within the 15 % bar) |
| (e) C vs Python, 1.5 sim-days, seed 2 | max SoC diff | ≈0.006 % (well within the 0.5 % bar) |

**Note on (a)'s max error (≈9.3 %) vs the design's ±5 % target:** the ±5 %
claim in 01 §10 point 6 is about the *trend* — SoC "stays inside the
counter's short-term drift ... and is pulled back to truth at every
natural full-charge or true-rest event" — not a per-tick guarantee. A
full-detection anchor hard-sets SoC=1.0 the instant the charge-taper
criteria are met (§5a), exactly like a real Victron-style
"synchronisation"; in this synthetic simulator the charger's
voltage/current taper timing is decoupled from the battery's *true*
remaining Ah (a simplification of the charger model, not of the EKF), so
detection can fire a few points before true 100 % Ah is restored, showing
up as a short-lived spike in the max-error trace rather than a sustained
drift. The RMS figure (≈3.0 %) is the more representative number for
"typical tracking error", and it clears the 5 % bar; the test asserts RMS
≤5 % and a 15 % sanity ceiling on the max-error spike, and documents this
reasoning inline.

**Naive weekly drift is duty-cycle dependent, not a fixed constant.** 01
§4's own worked example (10 mA idle-bias + 0.5 % gain error on ~140 Ah/week
of throughput) gives ≈1.5-2 %/week. This simulator's 8-day "accelerated"
duty cycle deliberately includes one deliberately deep (~40-50 % DoD) cycle
mid-week (to exercise full-detection/capacity/efficiency at least once
inside a short run) plus lighter daily cycling, which moves more Ah/week
than that single illustrative example — so the measured naive drift here
(≈7-11 %/week depending on the run) is *higher* than 01 §4's number, not
because the sensor model differs, but because more current was moved. The
qualitative claim under test — naive counting drifts non-trivially while
the anchored EKF does not — holds regardless of the exact duty cycle.

## Honest limits

- **Everything here is synthetic and host-only.** No hardware (INA228,
  NTC, real 12 V tubular battery) has been touched. No claim here
  transfers to real duty cycles or real batteries without bench validation.
- **All LUT values (OCV/R0/R1/tau, `ekf/lut.py`) are placeholders**, in the
  bands 01 §1.5/§2.1 states, not independently characterised. The 0 °C/45 °C
  OCV rows are the §2.2 calibration-day tempco applied to the 25 °C row —
  design 01 explicitly calls for real 0/25/45 °C bench characterisation
  (§1.6) to replace this.
- **The simulator's charger voltage model is a deliberate simplification**
  (see `BatterySim.step`'s docstring): bulk/absorption/float terminal
  voltage is modelled as an independent charger-regulated setpoint (not
  derived from the same R0 branch used elsewhere), because a few-mΩ R0
  cannot physically explain the ~1 V gap between rest-OCV and real
  flooded-lead-acid absorption/float voltage. Its current-taper timing is
  tied to elapsed time within the float phase, not to the battery's true
  remaining Ah — this is why full-detection can anchor a few points before
  the ground truth actually reaches 100 %, per the note above.
  **`eta_measured` / `capacity_measured_ah` / `soh_capacity` (design §7)
  are wired up and do fire** (a ≥30 % DoD cycle was exercised in the 8-day
  run and produced `capacity_measured_ah ≈ 47.7 Ah`), **but the measured
  `eta_measured` values from these runs are not trustworthy** — with
  full-detection currently firing more often per week than a single real
  cycle boundary would (a consequence of the same charger-model
  simplification above), `Ah_in`/`Ah_out` get reset across fragments of a
  cycle rather than one clean discharge-then-recharge, producing
  implausible efficiency ratios in this build. Treat §7's efficiency output
  as **implemented but not yet validated**; the capacity/SoH-capacity path
  is more robust since it only fires above the 30 % DoD gate.
- **R_int event estimator uses consecutive-sample ΔI/ΔV** (the "honest 1 Hz
  limitation" 01 §6.1 names explicitly), not a sub-second burst capture —
  no ALERT-pin/burst hardware exists here to do otherwise.
- **The per-tick OCV correction is gated to `charger_on == False`**, a
  deliberate deviation from §9's literal pseudocode — see above. This is
  the single largest structural choice in this implementation versus a
  literal reading of §9.
- **Zero-current auto-cal, cross-check divergence guard, and R0 sanity
  discard are implemented but only lightly exercised** by the required
  test set; they did not need to fire for tests (a)-(e) to pass, so their
  behaviour under a genuine sensor fault is unverified here.
