# Transfer-learning ablation (design 02 SS4.2-4.4)

**SYNTHETIC-TO-SYNTHETIC TRANSFER; Li-ion source pending download.** Source = `data/features_sim.csv` (sim/ run A), target = `data/features_sim_b.csv` (sim/ run B). `model/datasets/nasa_pcoe.py` and `model/datasets/calce.py` exist and are unit-tested (`tests/test_datasets.py`) but no real Li-ion .mat/.xlsx files have been downloaded into this repo as of this run -- see model/README.md's download-outcome section. This ablation demonstrates the Stage A -> Stage C (frozen-conv then L2-SP) transfer MECHANISM faithfully; it makes no claim about real cross-chemistry transfer.

Both arms trained/fine-tuned on the SAME target CSV with the SAME GroupKFold-by-battery split parameters (`--n-calib 2 --n-test 2`), so `model/splits.py`'s seeded determinism gives both arms the IDENTICAL held-out final-test battery set (confirmed below) -- point accuracy is reported on that independent test set, never on the calibration batteries used to fit the conformal offsets.

| arm | SoH MAE (pt) | SoH RMSE (pt) | PICP@80 (after conformal) | RUL-window hit-rate |
|---|---|---|---|---|
| target-only | 16.383 | 17.197 | 0.865 | 1.000 |
| source-pretrain -> target fine-tune | 10.454 | 11.564 | 0.865 | 0.333 |

- target-only test batteries: [0, 5]
- transfer (source->target) test batteries: [0, 5]
- same test set: **True**

Evaluated on: target-only -> independent test batteries; transfer -> independent test batteries

## Full reports

### (i) target-only
```json
{
  "label": "target-only",
  "n_calib_windows": 96,
  "n_calib_batteries": 2,
  "conformal_offsets": {
    "c_lo_soh": 0.0,
    "c_hi_soh": 10.053783416748047,
    "c_lo_rul": 0.05649496167898177,
    "c_hi_rul": 0.0
  },
  "soh_mae_pt": 16.383153915405273,
  "soh_rmse_pt": 17.19671058654785,
  "picp_80": {
    "before": 0.3229166666666667,
    "after": 0.8645833333333334,
    "pice_before_pt": 47.708333333333336,
    "pice_after_pt": 6.458333333333332,
    "mpiw_before_pt": 16.700101852416992,
    "mpiw_after_pt": 26.753889083862305
  },
  "picp_50_approx": {
    "after": 0.2708333333333333,
    "pice_after_pt": 22.916666666666668,
    "mpiw_after_pt": 14.0804443359375,
    "note": "P25/P75 approximated from P10/P50/P90 (Z50/Z80 scaling) -- the architecture's quantile heads are fixed at tau=.1/.5/.9."
  },
  "rul_nmpiw": 5.95009183883667,
  "rul_relative_error_at_checkpoints": {
    "95.0": {
      "mean_rel_err": 0.9343122030329374,
      "median_rel_err": 0.9343122030329374,
      "n": 2
    },
    "90.0": {
      "mean_rel_err": 0.906027690578673,
      "median_rel_err": 0.906027690578673,
      "n": 2
    },
    "85.0": {
      "mean_rel_err": 0.7819233006381868,
      "median_rel_err": 0.7819233006381868,
      "n": 2
    }
  },
  "rul_window_hit_rate": 1.0,
  "n_checkpoint_pairs": 6,
  "warning_lead_time": {
    "median_lead_weeks": 5.185660120817656,
    "p10_lead_weeks": 4.647138939511535,
    "n_batteries": 2,
    "n_censored_no_eol": 0,
    "n_with_replace_grade": 2,
    "false_alarm_rate": 0.0,
    "miss_rate": 0.0
  }
}
```

### (ii) source-pretrain -> target fine-tune (Stage A -> Stage C)
```json
{
  "label": "source-pretrain -> target fine-tune",
  "n_calib_windows": 96,
  "n_calib_batteries": 2,
  "conformal_offsets": {
    "c_lo_soh": 0.0,
    "c_hi_soh": 0.0,
    "c_lo_rul": 0.08922707438468931,
    "c_hi_rul": 0.0
  },
  "soh_mae_pt": 10.45438289642334,
  "soh_rmse_pt": 11.564077377319336,
  "picp_80": {
    "before": 0.8645833333333334,
    "after": 0.8645833333333334,
    "pice_before_pt": 6.458333333333332,
    "pice_after_pt": 6.458333333333332,
    "mpiw_before_pt": 19.296804428100586,
    "mpiw_after_pt": 19.296804428100586
  },
  "picp_50_approx": {
    "after": 0.4166666666666667,
    "pice_after_pt": 8.333333333333332,
    "mpiw_after_pt": 10.155816078186035,
    "note": "P25/P75 approximated from P10/P50/P90 (Z50/Z80 scaling) -- the architecture's quantile heads are fixed at tau=.1/.5/.9."
  },
  "rul_nmpiw": 2.3550145626068115,
  "rul_relative_error_at_checkpoints": {
    "95.0": {
      "mean_rel_err": 0.9669159817528494,
      "median_rel_err": 0.9669159817528494,
      "n": 2
    },
    "90.0": {
      "mean_rel_err": 0.9504171904801633,
      "median_rel_err": 0.9504171904801633,
      "n": 2
    },
    "85.0": {
      "mean_rel_err": 0.8844167277813944,
      "median_rel_err": 0.8844167277813944,
      "n": 2
    }
  },
  "rul_window_hit_rate": 0.3333333333333333,
  "n_checkpoint_pairs": 6,
  "warning_lead_time": {
    "median_lead_weeks": 5.185660120817656,
    "p10_lead_weeks": 4.647138939511535,
    "n_batteries": 2,
    "n_censored_no_eol": 0,
    "n_with_replace_grade": 2,
    "false_alarm_rate": 0.0,
    "miss_rate": 0.0
  }
}
```

Wall time: 13.8s.
