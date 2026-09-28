# SoH/RUL model evaluation -- float (PyTorch)

**DUMMY synthetic data (model/make_dummy_features.py) -- numbers are placeholders** -- see model/README.md for full honesty labelling.

- Calibration/eval set: 1099 windows across 6 held-out batteries

## SoH point accuracy
| metric | value |
|---|---|
| MAE (pt) | 0.516 |
| RMSE (pt) | 0.667 |

## Coverage (split-conformal, before -> after)
| interval | nominal | PICP before | PICP after | PICE after (pt) | MPIW after |
|---|---|---|---|---|---|
| SoH 80% | 0.80 | 0.749 | 0.893 | 9.26 | 2.166 pt |
| SoH 50% (approx) | 0.50 | -- | 0.648 | 14.79 | 1.140 pt |

RUL normalised MPIW: 0.948

## RUL relative error at SoH checkpoints (n=18 battery-checkpoint pairs)
| SoH checkpoint | mean rel. err | median rel. err | n |
|---|---|---|---|
| 95.0% | 0.221 | 0.180 | 6 |
| 90.0% | 0.177 | 0.162 | 6 |
| 85.0% | 0.245 | 0.222 | 6 |

RUL-window hit-rate (EoL_true in [P10,P90]): **0.889**

## Warning lead time and grade-machine alarms
- median lead time: 11.1 weeks
- P10 lead time: 7.6 weeks
- batteries reaching a persistent REPLACE grade: 6 / 6
- false-alarm rate: 0.000, miss rate: 0.000

Conformal offsets: {"c_lo_soh": 0.4140304565429689, "c_hi_soh": 0.0, "c_lo_rul": 0.1641042709350586, "c_hi_rul": 0.0}
