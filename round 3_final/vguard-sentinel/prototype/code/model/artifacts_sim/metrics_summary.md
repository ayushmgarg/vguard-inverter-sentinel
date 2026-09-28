# SoH/RUL model evaluation -- float (PyTorch)

**data: data/features_sim_all.csv; evaluation set: independent final-test batteries ['0_b', '3_b', '6_a'] (never used for training, selection or calibration)** -- see model/README.md for full honesty labelling.

- Calibration/eval set: 104 windows across 3 held-out batteries

## SoH point accuracy
| metric | value |
|---|---|
| MAE (pt) | 8.245 |
| RMSE (pt) | 9.606 |

## Coverage (split-conformal, before -> after)
| interval | nominal | PICP before | PICP after | PICE after (pt) | MPIW after |
|---|---|---|---|---|---|
| SoH 80% | 0.80 | 0.663 | 0.990 | 19.04 | 34.199 pt |
| SoH 50% (approx) | 0.50 | -- | 0.529 | 2.88 | 17.999 pt |

RUL normalised MPIW: 17.978

## RUL relative error at SoH checkpoints (n=9 battery-checkpoint pairs)
| SoH checkpoint | mean rel. err | median rel. err | n |
|---|---|---|---|
| 95.0% | 1.782 | 0.727 | 3 |
| 90.0% | 1.822 | 0.619 | 3 |
| 85.0% | 3.921 | 1.268 | 3 |

RUL-window hit-rate (EoL_true in [P10,P90]): **1.000**

## Warning lead time and grade-machine alarms
- median lead time: 4.4 weeks
- P10 lead time: 1.4 weeks
- batteries reaching a persistent REPLACE grade: 3 / 3
- false-alarm rate: 0.000, miss rate: 0.333 (censored batteries without observed EoL excluded: 0)

Conformal offsets: {"c_lo_soh": 13.133037567138672, "c_hi_soh": 0.0, "c_lo_rul": 0.1292993664741516, "c_hi_rul": 0.0}
