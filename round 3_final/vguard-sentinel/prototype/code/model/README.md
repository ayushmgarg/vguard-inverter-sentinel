# model/ — TinyML SoH/RUL pipeline (design 02)

Training, evaluation, calibration and int8 quantisation for the 1-D temporal
CNN that produces SoH/RUL quantile forecasts (design 02 §2, §3, §4.1, §5.1,
§7; validation definitions from 11 §1.2). Python 3.9, PyTorch 2.5, numpy,
pandas, scikit-learn. No TensorFlow dependency anywhere except the optional,
`model/export_tflite.py` (TFLite export **now succeeds** — see the 'Real run' section at the end; the earlier failure notes below are kept as history and marked SUPERSEDED).

## What was actually run here (read this before trusting any number)

**Every number in `model/artifacts/*.json` and `metrics_summary.md` comes
from `model/make_dummy_features.py`'s synthetic data, not from real
lead-acid batteries.** The dummy generator fabricates 24 batteries x ~200
cycles with a plausible-looking monotone SoH fade to ~80% and dynamic
features that drift with wear in the direction design 02 §1 describes, but
it is not a physics simulator (that is `sim/`'s job) and encodes no
claim about real cell behaviour — it exists only so this module has
something with the right shape (`features/schema.py`) to develop, train,
and quantise against before the real feature pipeline's
`data/features_sim.csv` lands. **The CLI accepts any CSV with that schema**
— re-run everything below against the real file the moment it exists; no
code changes needed.

Honest limits, stated plainly:
- **No lead-acid ground truth.** Design 02 §4 describes a three-stage
  training curriculum (Li-ion pre-train -> synthetic Indian-duty bridge ->
  fine-tune on a 24-36-battery accelerated aging campaign, design 04). None
  of that data exists yet. This module trains directly on the dummy CSV in
  a single stage — there is no Stage A/B/C distinction here, no L2-SP, no
  transfer learning. That machinery (frozen-then-unfrozen fine-tuning,
  Li-ion pretraining) is not implemented because there is nothing real to
  transfer from or to yet.
- **Split-conformal calibration and evaluation share one battery split.**
  With only 24 synthetic batteries, `model/evaluate.py` computes the
  conformal offsets (c_lo/c_hi) *and* reports before/after coverage on the
  same 6 held-out calibration batteries (design 02 §4.4 point 4). That
  demonstrates the calibration mechanism faithfully — before-calibration
  coverage really is off nominal and after-calibration coverage really
  does move toward it — but it is not an independent generalisation test.
  A real run with more batteries would use nested splits.
- **CV metrics are diagnostic, not the deployed model.** `model/train.py`'s
  6-fold GroupKFold CV and leave-one-condition-out CV
  (`cv_metrics.json`, `loco_metrics.json`) train separate short-lived
  models per fold purely to report validation pinball loss; their weights
  are not saved or ensembled. The deployed ensemble (`seed0/1/2.pt`) is
  trained once on all 18 non-calibration batteries with its own internal
  battery-grouped validation split for early stopping.
- **Only one ensemble seed is quantised.** `model/quantize.py` quantises
  and exports `seed0` only. The real on-device ensemble (design 02 §2.4,
  3 seeds averaged) would repeat the same procedure for seed1/seed2; doing
  one seed is enough to validate the int8 pipeline's correctness
  end-to-end and keeps the demo run fast.
- **The int8 reference is numerically faithful, not bit-exact with
  ESP-NN/TFLM.** `model/int8_infer.py` does real int8 weights (per-output-
  channel scale), real int32 accumulation, and real fixed-point
  (multiplier, shift) requantisation between layers — the actual mechanism
  design 02 §5.1 describes — computed with numpy int64 arithmetic (exact
  for these value ranges) rather than the bit-exact saturating-rounding
  SIMD op the MCU runs. Also: the architecture's quantile heads are fixed
  at tau in {.1, .5, .9}, so the "50%-nominal" PICP/MPIW in
  `metrics_summary.md` is *approximated* from P10/P50/P90 via a normal-
  quantile-ratio scaling (`model/metrics.py::approx_50pct_interval`), not a
  trained P25/P75 quantile — flagged in the report's `note` field.
- **[SUPERSEDED 2026-09-22 — export now works via SavedModel + Conv2D(1×k); see 'Real run' below] TFLM export scripted, not executed.** `model/export_tflite.py` is
  written to exit 0 with a clear message if TensorFlow is unimportable, per
  this module's brief. In *this* sandbox, TensorFlow 2.16.2 turned out to
  actually be importable (contradicting the brief's stated premise) — so,
  per this repo's own execution-venue discipline (trust what you directly
  observe over a stale instruction, and never fake output either way), the
  script really does rebuild the architecture in Keras and copy the
  PyTorch weights over (verified: max abs diff on the raw head outputs
  between the two on the same input is < 1e-3, printed by the script). The
  actual TFLite int8 *conversion* step then fails in this environment with
  a real TF/Keras-3 x TFLite-converter incompatibility
  (`RuntimeError: ... input->dims->size != 4 ...` inside the int8
  calibrator, after the CONV_2D-lowered graph and a SavedModel round-trip
  — see the script's own comments for what was tried). The script reports
  that failure honestly and writes no `.tflite` file. **No TFLite artifact
  ships from this module** — the int8 correctness claim for this
  deliverable rests entirely on `model/quantize.py` +
  `model/int8_infer.py`, which are pure numpy, fully executed, and
  unit-tested (`tests/test_model.py`).
- **No anomaly autoencoder / rule fast path.** Design 02 §6 is out of scope
  for this module (not requested in the module-B brief); `SERVICE_NOW` is
  fully wired into `model/grade.py`'s state machine (see
  `test_service_now_overrides_immediately_and_restores_prior_grade`) but
  nothing here ever sets the flag — that is the anomaly detector's job.
- **lambda_mono / lambda_cross are not given numeric values in design 02
  §4.1** (only lambda_R = 1 is specified there). Both default to 1.0 in
  `model/losses.py::SentinelLoss`, order-matched to the pinball terms;
  they are constructor args, easy to retune once real data justifies it.
- **1 cycle ~= 1 day** is `model/make_dummy_features.py`'s and
  `model/evaluate.py`'s working assumption for converting cycles to
  calendar days (used for the grade-machine hysteresis span and the
  warning-lead-time-in-weeks calculation) — matches the dummy generator's
  own ~1-outage/day construction and design 02 §0's "0.5-3 partial
  cycles/day" for Indian homes, but is not derived from real timestamps
  (the schema's per-cycle records don't carry one).

## Files

| file | design section | what it does |
|---|---|---|
| `model/make_dummy_features.py` | -- | synthetic features CSV generator (see above) |
| `model/net.py` | 02 §2.2 | the 1-D CNN: 27,990 params (~28.0k), 105,600 MACs (~106k) |
| `model/windowing.py` | 02 §1.10/§2.1/§5.1 | 30x14+6 window builder (oldest-cycle padding), standardiser |
| `model/losses.py` | 02 §4.1 | pinball (tau=.1/.5/.9) x2 heads, monotonicity penalty, cross penalty |
| `model/splits.py` | 02 §4.4 | battery-level calibration hold-out, GroupKFold, leave-one-condition-out |
| `model/train.py` | 02 §4 | CLI: windowing -> CV -> 3-seed ensemble training, `python -m model.train` |
| `model/metrics.py` | 02 §7 / 11 §1.2 | MAE/RMSE, PICP/PICE/MPIW, split-conformal offset, hit-rate |
| `model/grade.py` | 02 §3 | usage-rate EWMA, EFC->weeks conversion, grade state machine w/ hysteresis |
| `model/evaluate.py` | 02 §7 / 11 §1.2 | ensemble inference, conformal calibration, full metric report |
| `model/quantize.py` | 02 §5.1 | full-integer PTQ, C header + JSON header export, float-vs-int8 report |
| `model/int8_infer.py` | 02 §5.1 | pure-numpy int8 inference reference (int32 accumulate + requantise) |
| `model/export_tflite.py` | 02 §2.2/§5.1 | full-int8 TFLite export, all ensemble seeds (executed here) |
| `tests/test_model.py` | -- | pytest: shapes, param count, non-crossing quantiles, int8-vs-float, grade hysteresis |
| `features/schema.py` | CONTRACTS §2 | shared column-order contract (owned jointly with the feature-pipeline module) |
| `model/datasets/_common.py` | -- | shared hashing/manifest/download (incl. HTTP-range zip access) and numeric helpers for the dataset loaders below |
| `model/datasets/nasa_pcoe.py` | 02 §4.2 | NASA PCoE `.mat` loader (B0005/6/7/18 etc.) -> features/schema.py CSV + manifest |
| `model/datasets/calce.py` | 02 §4.2 | CALCE CS2/CX2 `.xlsx`/`.csv` loader -> features/schema.py CSV + manifest |
| `model/datasets/synthetic.py` | -- | registers `data/features_sim.csv` / `features_sim_b.csv` as manifested datasets |
| `model/stages.py` | 02 §4.2-4.4 | Stage A/B/C CLI (pre-train / bridge fine-tune / frozen-conv+L2-SP fine-tune) |
| `model/ablation.py` | 02 §4.2-4.4 | target-only vs. pre-train-then-fine-tune ablation, same held-out test batteries |
| `tests/test_datasets.py` | -- | pytest: tiny synthetic NASA `.mat` / CALCE `.xlsx` fixtures, schema/NaN/manifest checks, Stage B->C smoke test |

## Exact commands run for this deliverable

```bash
cd documentation/prototype/code

# 1. synthetic data (24 batteries, ~200 cycles each)
python3 -m model.make_dummy_features --out data/features_sim_dummy.csv

# 2. train: 6-fold GroupKFold CV + leave-one-condition-out CV (diagnostic),
#    then a 3-seed ensemble trained on the 18 non-calibration batteries
#    (6 held out entirely for conformal calibration). Reduced epoch counts
#    vs. the code's own defaults so the whole run finishes in ~2 minutes
#    on a laptop CPU -- see "honest limits" above.
python3 -m model.train --data data/features_sim_dummy.csv --out model/artifacts/ \
    --epochs 12 --cv-epochs 4 --cv-folds 6 --seeds 3 --patience 5 --loco

# 3. evaluate: ensemble inference + split-conformal calibration + full metric report
python3 -m model.evaluate --artifacts model/artifacts/ --data data/features_sim_dummy.csv

# 4. quantize: int8 PTQ of seed0, C header + JSON header, float-vs-int8 report
python3 -m model.quantize --artifacts model/artifacts/ --data data/features_sim_dummy.csv

# 5. TFLite export (works with TensorFlow 2.16 installed; exits cleanly with a message if TF is absent)
python3 -m model.export_tflite --artifacts model/artifacts/ --data data/features_sim_dummy.csv

# 6. tests
pytest -q                      # whole repo, from documentation/prototype/code
pytest -q tests/test_model.py  # this module only
```

Wall time on this machine (12-core CPU, `torch.set_num_threads(4)` set in
`train.py`/`evaluate.py`/`quantize.py` -- the ~28k-param model is small
enough that torch's default all-core thread pool spends more time
scheduling than computing): training step ~130s, evaluate/quantize a few
seconds each.

## Results (DUMMY data -- see honesty section; not a real accuracy claim)

Parameter/MAC budget (`model/net.py`, printed by `python -m model.net` and
verified by `tests/test_model.py::test_param_count_matches_design_budget`):

| | value | design 02 §2.2 target |
|---|---|---|
| parameters | 27,990 | ~28.0k |
| MACs | 105,600 | ~106k |

Full pytest: **135 passed** (whole repo, incl. modules from other Sentinel
components); `tests/test_model.py` alone: **21 passed**.

SoH/RUL metrics on the 6 held-out calibration batteries
(`model/artifacts/metrics_summary.md`, `metrics.json` — full table):

| metric | value |
|---|---|
| SoH MAE | 0.516 pt |
| SoH RMSE | 0.667 pt |
| PICP @80% nominal, before conformal | 0.749 |
| PICP @80% nominal, after conformal | 0.893 (PICE 9.3 pt) |
| PICP @50% nominal (approx.), after conformal | 0.648 |
| RUL normalised MPIW | 0.948 |
| RUL relative error @ SoH 95/90/85% checkpoints | 0.221 / 0.177 / 0.245 |
| RUL-window hit-rate (EoL_true in [P10,P90]) | 0.889 |
| warning lead time, median / P10 | 11.1 / 7.6 weeks |
| false-alarm rate / miss rate | 0.000 / 0.000 |

int8 vs float (`model/artifacts/quantization_report.json`, seed0 only, both
re-conformalised on their own predictions per design 02 §5.1):

| | float (seed0) | int8 (seed0) | delta |
|---|---|---|---|
| SoH MAE | 0.593 pt | 0.578 pt | -0.015 pt |
| PICP @80% | 0.889 | 0.882 | -0.007 |

Both deltas are well inside design 02 §5.1's expected budget (SoH MAE
+0.1-0.3 pt, coverage shift <=2%) -- on this dummy data the int8 model is
essentially indistinguishable from float, which is expected: the
representative set (500 windows) spans the full healthy-to-near-EoL range
the calibration set is drawn from, so per-channel weight scales and
per-tensor activation scales have little dynamic range left unused.

**These numbers are placeholders.** They demonstrate the pipeline
end-to-end runs and the calibration/quantisation mechanisms behave as
designed on data with the right shape; they say nothing about a real
lead-acid battery's SoH/RUL predictability until `data/features_sim.csv`
(or campaign data, design 04) replaces the dummy CSV.

## Real run on the synthetic tubular feature set (2026-09-22, executed here — independent test set)
Data: `data/features_sim_all.csv` = two `sim/` runs merged (16 batteries, 624 cycles, 9 reach 80 % SoH), now with `t_end_s` timestamps. Split: **3 independent final-test batteries** (never used for training, model selection or calibration), 3 calibration batteries (conformal offsets only), 10 training batteries (4-fold GroupKFold). Command: `bash run_all.sh`.

| metric (units) | value | comment |
|---|---|---|
| params / MACs | 27,990 / 105,600 | as designed (02 §2.2) |
| SoH MAE / RMSE (percentage points) | 8.2 / 9.6 | weak; 10 synthetic training batteries; design target ≤3 pt needs the aging campaign |
| PICP@80 % before → after conformal | 0.66 → 0.99, **MPIW 34 pt** | over-wide after calibration on only 3 batteries — coverage is reported next to width on purpose |
| RUL-window hit-rate | 1.00 (n = 3 batteries) | too few EoL events to mean much |
| warning lead time median / P10 (weeks, from t_end_s timestamps) | 4.4 / 1.4 | accelerated synthetic duty |
| false-alarm / miss (censored excluded) | 0.00 / 0.33 | REPLACE fires late on one of three test batteries |
| int8 vs float ΔMAE | +0.01 pt | quantisation cost negligible |
| TFLite full-int8 | 3 seeds × 36,720 B (`sentinel_model_seed{0,1,2}.tflite`) + int8 C headers | the on-device ensemble as designed; **not yet run on an ESP32** |
What this proves: the pipeline (features → windows → CNN → quantiles → conformal band → grade → int8 → .tflite) runs end to end with an honest split. What it does not prove: accuracy on real tubular batteries — no such data exists until design 04 runs.

## Stage A/B/C and ablation (2026-09-22, executed here)

Extends the pipeline above with (1) real-dataset loaders for Stage A pre-training,
(2) a `model/stages.py` CLI implementing design 02 §4.2–4.4's curriculum, and
(3) a transfer-learning ablation. **Read the honesty labels below before
trusting any transfer number** — no real Li-ion source data is in this repo
yet; see "Download outcome".

### 1. Real-dataset loaders (`model/datasets/`)

- `model/datasets/nasa_pcoe.py` parses the NASA PCoE Battery Data Set's
  per-cycle `.mat` structs (B0005/6/7/18 etc.) into `features/schema.py`'s
  exact column order. Genuinely derived: `q_dis_norm`/`dod`/`soh_true`/`efc`
  from the `Capacity` field (2.0 Ah spec-sheet rated capacity); `r_ratio`/
  `sag_ratio` from the ΔV/ΔI voltage step at the charge→discharge cycle
  boundary; `eta_c` from paired charge/discharge Ah integrals; `ca_ratio`/
  `cv_frac` from the CC→CV transition of each charge cycle; `ic_peak_h`/
  `ic_peak_v` from the dQ/dV curve of the CC segment; `t_mean`/`ln_tfull`/
  `st_total_per_day`/`age_years` from `Temperature_measured` and the cycle
  `time` datevecs; `f_lowsoc` from an Ah-integrated within-cycle SoC
  estimate. **Left NaN, never fabricated**: `ocv_err` (needs an independent
  EKF SoC reference and a calibrated OCV-SoC curve this offline loader does
  not have) and `st_float` (NASA's CC-CV cycler protocol has no lead-acid-
  style float/trickle-charge phase for this channel to measure — see
  `model/datasets/_common.py::COMMON_NONDERIVABLE`).
- `model/datasets/calce.py` does the same for CALCE CS2/CX2 (per-test-date
  `.xlsx`/`.csv`, columns matched case-insensitively by substring so minor
  header variations don't break parsing), grouping the concatenated,
  real-time-ordered log by `Cycle_Index` and splitting each cycle into its
  charge/discharge segments. Same derived/NaN list as NASA, plus: `t_mean`
  is NaN per-battery when that battery's raw files carry no temperature
  column at all (common for CALCE exports) — logged explicitly, not
  silently dropped.
- `model/datasets/synthetic.py` registers the existing
  `data/features_sim.csv` / `features_sim_b.csv` as manifested datasets
  (no new derivation — they already conform to the schema).
- All three write a manifest CSV (`battery_id, chemistry, n_cycles,
  capacity_bol, capacity_eol, source_file, sha256`) under `data/manifests/`.
  Executed here: `sim_run_a_manifest.csv`, `sim_run_b_manifest.csv` (8
  batteries each, real `sha256` of the actual CSV files on disk). No
  `nasa_pcoe_manifest.csv` / `calce_manifest.csv` exist yet — no raw
  `.mat`/`.xlsx` files were successfully downloaded (see below); the code
  path that writes them is exercised end-to-end by `tests/test_datasets.py`
  against tiny synthetic fixtures instead.

### 2. `model/stages.py` — Stage A/B/C CLI

Thin orchestration over `model/train.py`/`net.py`/`losses.py`/`windowing.py`/
`splits.py` (imported, not copied — see the module docstring for exactly
which pieces are reused verbatim). Stage A trains from scratch; Stage B
continues from Stage-A weights with nothing frozen; Stage C runs two phases
internally — C1 freezes `conv1-3` and retrains dense/heads only, then C2
unfreezes everything with a lower conv learning rate and an L2-SP penalty
(`beta * sum((theta - theta_init)^2)`, default `beta=1e-3`) anchored to the
**Stage-C input** weights (design 02 §4.4: "a small [target] set cannot drag
the filters far" from what pre-training learned). `--n-test` (new in
`model/train.py`, reused here) holds out an independent final-test battery
set never touched by training, model selection, or conformal calibration;
`model/splits.py`'s seeded determinism means two stages run on the *same*
CSV with the same `--n-calib`/`--n-test` get the *same* held-out battery
IDs automatically, without any coordination file. Verified in
`tests/test_datasets.py::test_stages_freeze_conv_actually_freezes` (conv
weights provably unchanged under `--freeze-conv`, provably changed once
unfrozen) and `test_stages_b_then_c_runs_fast` (Stage B→C on a 6-battery
dummy CSV completes in well under a minute).

### 3. Ablation (`model/ablation.py`) — **synthetic-to-synthetic transfer; Li-ion source pending download**

Executed here exactly as specified, since no real Li-ion data is downloaded
yet: **source = `data/features_sim.csv`** (sim/ run A, 8 batteries, 222
rows), **target = `data/features_sim_b.csv`** (sim/ run B, 8 batteries, 402
rows). Both arms trained/fine-tuned on the target CSV with the identical
`--n-calib 2 --n-test 2` GroupKFold-by-battery split; the run confirmed both
arms land on the exact same held-out test batteries (`[0, 5]`) by
construction, not by coincidence.

Command:
```bash
python3 -m model.ablation --source data/features_sim.csv --target data/features_sim_b.csv \
    --out model/artifacts_ablation --seeds 3 --epochs 25 --source-epochs 25 \
    --freeze-epochs 10 --n-calib 2 --n-test 2 --patience 8
```

| arm | SoH MAE (pt) | SoH RMSE (pt) | PICP@80 (after conformal) | RUL-window hit-rate |
|---|---|---|---|---|
| (i) target-only | 16.383 | 17.197 | 0.865 | 1.000 |
| (ii) source-pretrain → target fine-tune (Stage A → Stage C) | 10.454 | 11.564 | 0.865 | 0.333 |

Full JSON reports, conformal offsets, and both battery-split lists:
`model/artifacts_ablation/ablation.md` / `ablation.json`. Wall time: 13.8 s.

**What this shows and does not show**: pre-training on run A before
fine-tuning on run B cut SoH MAE by ~36% here (16.4 → 10.5 pt) with
identical PICP@80 coverage — the Stage A→C mechanism (frozen-conv retrain,
then unfrozen+L2-SP) measurably helps *when the source and target share the
same underlying feature-generation process* (both are `sim/` runs of the
same simulator with different random seeds/conditions). The RUL-window
hit-rate move (1.00→0.33) is noise from only 2 test batteries, not a real
regression signal — both arms are evaluated on exactly 2 held-out batteries
here; do not read anything into a metric with that denominator. **This is
not evidence that Li-ion→lead-acid cross-chemistry transfer (design 02
§4.2's actual claim) works** — that requires Stage A trained on real NASA
PCoE/CALCE data, which is not in this repo (see below). Re-running
`model/ablation.py --source data/features_nasa.csv` (or `features_calce.csv`)
the moment either loader's `--download` succeeds requires no code changes.

### 4. Download outcome (bounded to ~5 minutes per the brief; actually took longer while diagnosing)

Both mirrors are real and reachable — confirmed directly, not assumed:
```
$ curl -sI https://phm-datasets.s3.amazonaws.com/NASA/5.+Battery+Data+Set.zip
HTTP/1.1 200 OK   Content-Length: 209708670
$ curl -sI https://web.calce.umd.edu/batteries/data/CS2_35.zip
HTTP/1.1 200 OK   Content-Length: 37056519
```
- **CALCE CS2_35**: `python -m model.datasets.calce --download CS2_35 --raw-dir data/raw_calce`
  actually transferred real bytes from the live mirror in this sandbox — one
  attempt reached 28.3 MB of the 37 MB zip (~190 KB/s) before its time
  budget expired; a second attempt stalled near 3 MB and made no further
  progress before being killed. Network throughput in this sandbox was
  inconsistent across attempts (confirmed reachable, confirmed slow/unstable),
  and no attempt completed within the combined download budget. No
  `data/raw_calce/CS2_35.zip` is left in the repo (partial files are deleted
  on failure, per `model/datasets/_common.py::download_file` and this run's
  cleanup — CONTRACTS §7: never leave fabricated or silently-partial data
  behind).
- **NASA PCoE (one file)**: `model/datasets/nasa_pcoe.py --download` uses a
  seekable HTTP-range file object (`model/datasets/_common.py::HTTPRangeFile`)
  so only the ~56 MB FY08Q4 group entry (containing B0005/6/7/18) is pulled
  out of the outer ~210 MB zip, never the whole archive — verified working
  early in this session (outer central directory read in ~6 s, group-entry
  byte offsets resolved correctly). A later attempt, within the download
  budget, could not even complete the outer zip's HTTP Range negotiation in
  25 s — the same network slowdown observed on the CALCE attempt. No
  `data/raw_nasa/*.mat` files are left in the repo.
- **Conclusion**: the download mechanism itself is verified correct
  (real HTTP 200s, real partial byte transfer, correct range-based
  partial-zip extraction logic exercised against the real S3-hosted
  archive), but neither dataset finished downloading in this sandbox within
  the time budget. `model/datasets/nasa_pcoe.py`/`calce.py` print the exact
  manual-fetch URLs on any download failure (`NASA_MANUAL_URLS`,
  `CALCE_MANUAL_URL_TEMPLATE`) — re-running either `--download` on a
  faster/more stable connection requires no code changes, and
  `model/ablation.py`/`model/stages.py --stage A` work unmodified against
  whatever `data/features_nasa.csv` / `data/features_calce.csv` that
  produces.

### Files added by this deliverable

`model/datasets/{__init__,_common,nasa_pcoe,calce,synthetic}.py`,
`model/stages.py`, `model/ablation.py`, `tests/test_datasets.py`,
`data/manifests/{sim_run_a,sim_run_b}_manifest.csv`,
`model/artifacts_ablation/{ablation.md,ablation.json,target_only/,
transfer_stageA_source/,transfer_stageC_target/}`.

Full repo test suite: `pytest -q` from `documentation/prototype/code` —
**245 passed** (12 of those in `tests/test_datasets.py`).
