# autopilot -- Engine 2: habit-learning autopilot & load-shedding controller

Implements design doc **05 -- Habit-Autopilot-and-Load-Prioritisation** in
full, plus the hardware-side outage-detection debounce numbers from
**10 -- Hardware-Interfaces-and-Power.md Sec.4 & Sec.7**. Interfaces conform
to `../CONTRACTS.md` Sec.5 (I/O) and Sec.6 (`ap_init`/`ap_evaluate` C
names).

## Files

| File | What it is | Design ref |
|---|---|---|
| `habit.py` | 7x24 EWMA load table (4 seasonal grids) + 7x24 Beta-smoothed outage table | 05 Sec.1-2 |
| `controller.py` | 60 s tier-shedding decision loop + 2-of-3 outage vote | 05 Sec.4, Sec.7 / 10 Sec.4, Sec.7 |
| `autopilot.h` / `autopilot.c` | C99 port of `controller.py`, static allocation, `ap_init`/`ap_evaluate` per CONTRACTS Sec.6 | same |
| `test_autopilot_host.c` | host test harness: 50-scenario scripted table (pass/fail) + `--parity` mode for the Python/C cross-check | 11 Sec.1.3 |
| `parity_scenarios.txt` | shared CFG/STEP scenario table both languages replay, for the parity test | -- |
| `Makefile` | host build (`gcc -std=c99 -O2 -lm`), no ESP-IDF dependency | CONTRACTS Sec.0 |
| `../tests/test_autopilot.py` | pytest suite: habit tables, controller scenarios, C-port parity | 11 Sec.1.3 |

## Commands

```sh
# Python controller + habit table
python3 -c "import sys; sys.path.insert(0,'..'); from autopilot import habit, controller"

# C host build + the 50-scenario scripted table
cd autopilot
make            # builds ./test_autopilot_host
./test_autopilot_host                          # runs the 50-scenario table, prints PASS/FAIL + summary
./test_autopilot_host --parity parity_scenarios.txt   # CSV output for the Python parity test

# full test suite (from documentation/prototype/code/, per CONTRACTS.md)
pytest -q tests/test_autopilot.py
```

## Scenario results (last run in this environment)

**C host scenario table** (`./test_autopilot_host`, design 11 Sec.1.3 style):

```
50/50 scenarios passed
```
20 Group-A (pure SoC-ladder drain/recover, strict 40%/55% T3 check), 15
Group-B (real outage + essentials-at-risk hard floor), 15 Group-C
(override / hw-lock / unconfigured). Every scenario checks, throughout its
whole run: (a) T1 never shed while `E_usable > 0`, (c) zero dwell
violations, (d) zero chatter (>2 transitions/channel/10 min); Group-A
additionally checks (b) T3 sheds only at SoC <= 40 % and restores only at
SoC >= 55 % (+-0.5 pt tolerance).

**pytest** (`pytest -q tests/test_autopilot.py`):

```
65 passed in <1s
```

| Property (design 11 Sec.1.3 / task spec) | Test(s) | Result |
|---|---|---|
| T1 never shed while `E_avail > 0` | `test_ladder_drain_recover` x10, `test_unconfigured_never_sheds` x4, `test_hardware_lock_forces_t1` x2 | PASS |
| T3 shed exactly at <=40 %, restore at >=55 % | `test_ladder_drain_recover` x10 | PASS |
| No dwell violations | `test_dwell_on_boundary` x3, `test_dwell_off_boundary` x3, `test_dwell_on_boundary_from_boot_uses_boot_time` | PASS |
| No chatter (>2 transitions/channel/10 min) | `test_ladder_drain_recover` x10, `test_no_chatter_under_soc_noise_at_threshold` x3 | PASS |
| Override cannot beat the hard floor; override times out | `test_override_defeats_soc_ladder_shed`, `test_override_cannot_defeat_hard_floor`, `test_override_times_out` x3 | PASS |
| Unconfigured -> nothing shed | `test_unconfigured_never_sheds` x4 | PASS |
| Hardware lock respected | `test_hardware_lock_forces_t1` x2, `test_hardware_lock_survives_app_attempting_t3_config` | PASS |
| Outage declared 2-of-3 within 2 s, not on a 200 ms sag | `test_outage_declared_within_2s_two_of_three` x3, `test_no_outage_declared_on_short_sag` x3, `test_outage_declared_s1_alone_longer_window_retrofit`, `test_no_outage_declared_single_weak_sensor_short_of_alone_window` | PASS |
| Restore only after >0.9 pu for 10-30 s | `test_restore_hysteresis_10_to_30s` x3, `test_restore_resets_if_mains_dips_again_mid_debounce` | PASS |
| CONSERVATIVE fallback on forecast disagreement | `test_forecast_disagreement_fallback` x4, `test_conservative_mode_clears_when_forecast_agrees_again` | PASS |
| Pre-charge advisory vs active | `test_pre_charge_advisory_when_not_charger_commandable`, `test_pre_charge_active_when_charger_commandable`, `test_pre_charge_not_triggered_below_confidence` | PASS |
| habit.py: EWMA, cold start, seasonal seeding, outage stats, memory footprint | 9 tests | PASS |
| C host 50-scenario table runs clean | `test_c_host_scenario_table_all_pass` | PASS (skipped if `gcc` missing) |
| C matches Python on the shared scenario table | `test_c_matches_python_parity` | PASS (skipped if `gcc` missing) |

Re-run any time with `pytest -q tests/test_autopilot.py -v` for the full
per-case breakdown; counts above will match unless the scenario tables are
edited.

## Honest limits (CONTRACTS.md Sec.7)

- **No hardware.** Everything above is a host simulation (synthetic
  scenario tables run against pure Python / host-compiled C99). The
  design 11 Sec.1.3 bench ("programmable AC source, 4 contactors, load
  bank, battery simulator") does not exist here; "50 scenarios" means a
  scripted, in-process table, not a wired rig.
- **Relay/contactor fail-safe (NC wiring, coil-off = load-on, the
  independent supervisory timer gating the coil-enable line) is a wiring
  and driver-board property** (design 05 Sec.6 / 10 Sec.4). Nothing in
  this module drives real coils; `SHED`/`ON` are logical decisions only.
  The 100/100-trial "pull MCU reset -> all NC contacts close within 2 s"
  claim in design 11 Sec.1.3 needs the actual driver board and cannot be
  exercised here.
- **Per-tier load forecast is a proxy.** `habit.forecast_total_demand_wh`
  sums the WHOLE connected-load channel (one shunt feeds the habit table,
  same channel as the EKF -- design 05 Sec.1.1); there is no per-tier CT
  metering in this prototype. `ApInput.fcst_t1_wh` (the pseudocode's
  `fcst_T1_Wh`) must be supplied by the caller, e.g. the total forecast
  scaled by an installer-entered T1(+T2) nameplate fraction. True
  per-appliance/per-tier disaggregation needs NILM (Engine 3a, design 06)
  or per-channel CT metering, neither of which this module has.
- **Season boundaries are this implementation's interpretive choice.**
  Design 05 Sec.1.1 names four seasonal grids (Winter/Summer/Monsoon/
  Pre-monsoon) but does not give month boundaries. `habit.py`'s
  `season_for_month` uses: Winter = Dec-Feb, Summer = Mar-Jun, Monsoon =
  Jul-Sep, Pre-monsoon = Oct-Nov (documented in `habit.Season`'s
  docstring). A different, equally defensible mapping is possible; this
  is not a measured or IMD-sourced boundary.
- **The generic double-peak cold-start curve (`generic_double_peak_w`) and
  the lead-acid temperature-derating curve (`_f_temp`/`ap_f_temp`) are
  illustrative shapes**, not fit to measured Indian household data or a
  specific battery manufacturer's datasheet. They only matter while
  `n_obs` is small (cold start) or as a Peukert temperature correction;
  both are called out honestly at their definition sites and should be
  replaced with campaign-measured curves before field use (see design 04,
  the aging-campaign doc).
- **Dwell is applied uniformly to all 4 channels**, not gated by an
  explicit "is this a compressor" flag (the pseudocode's "compressor
  channels" wording). No compressor/non-compressor distinction exists in
  `ChannelConfig` in this prototype; applying the anti-short-cycle dwell
  to every channel is strictly more conservative (it can only prevent
  transitions, never allow a disallowed one), so it cannot cause a dwell
  violation on an actual compressor channel -- but it may be more
  cautious than necessary on a purely resistive T3 load. A future
  `is_compressor: bool` field would relax that.
- **Outage forecasting is honestly scoped per design 05 Sec.2.2**: this
  module predicts repeating scheduled-outage patterns from the unit's own
  history only. It cannot and does not claim to predict unscheduled
  faults (transformer trips, storms, cable faults) -- Grid Shield (Engine
  3b) reacts to those, it does not predict them. The Brier-score-vs-
  climatology validation required before the pre-charge feature can ship
  as "active" rather than "advisory" (design 11 Sec.1.3) needs >=8 weeks
  of real field logs, which do not exist in this prototype.
- **Peukert/temperature-corrected `E_usable`** uses the design's own
  formula (05 Sec.4.1) verbatim; the Peukert exponent (`n`) and the
  temperature-derating curve are configurable but default to illustrative
  flooded-lead-acid values, not values measured for a specific battery
  under test (see design 01 and the aging campaign, design 04).
- **Reason strings differ in wording between the Python and C
  implementations** (they are independent format-string calls); only the
  underlying `channel_state`/`mode` DECISIONS are contractually required
  to agree, and `test_c_matches_python_parity` checks exactly that, not
  string equality.
