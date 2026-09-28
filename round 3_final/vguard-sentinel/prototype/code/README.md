# Sentinel prototype code — what runs, what it proves

Every module below was **executed on this machine** (Python 3.9 + gcc host builds) on synthetic data unless stated otherwise. Nothing has been flashed to an ESP32 yet; nothing has seen a real tubular battery yet. `CONTRACTS.md` defines the interfaces; `../00-Status-Crosswalk.md` maps each report claim to the evidence here.

| Module | Implements (design doc) | Run | Tests |
|---|---|---|---|
| `sim/` | synthetic Indian tubular duty-cycle simulator (02 §4.3, 01 §1–2) | `python -m sim.battery_sim --n 8 --cycles 110 --out data/sim_1hz/` | `tests/test_sim.py` |
| `features/` | 14+6 per-cycle feature pipeline (02 §1) | `python -m features.cycle_features --in data/sim_1hz/ --out data/features_sim.csv` | `tests/test_features.py` |
| `ekf/` | 3-state EKF, corrected anchoring, R_int events (01) — Python + C | `pytest tests/test_ekf.py`; `make -C ekf` | `tests/test_ekf.py` |
| `model/` | 1-D CNN quantile SoH/RUL, GroupKFold CV, conformal calibration, int8 PTQ, TFLite export (02 §2–5) | `python -m model.train … && python -m model.evaluate … && python -m model.quantize … && python -m model.export_tflite …` | `tests/test_model.py` |
| `autopilot/` | EWMA habit tables, outage forecast, tiered shedding with hysteresis, 2-of-3 outage vote (05) — Python + C | `make -C autopilot && ./autopilot/test_autopilot_host` | `tests/test_autopilot.py` |
| `nilm/` | event detector, k-NN appliance library, PZEM parser (06) — Python + C | `make -C nilm` | `tests/test_nilm.py` |
| `pq/` | half-cycle RMS, IEEE 1159, THD (07) — Python + C | `make -C pq` | `tests/test_pq.py` |
| `healthlog/` | hash-chained ECDSA-P256 health log + verifier (09 §4) — Python + C | `make -C healthlog` | `tests/test_healthlog.py` |
| `charger/` | charging policy state machine, UART frame codec, simulated charger (03) — Python + C | `pytest tests/test_charger.py`; `make -C charger` | `tests/test_charger.py` |
| `model/datasets/`, `model/stages.py`, `model/ablation.py` | NASA/CALCE/synthetic loaders with manifests; Stage A/B/C; transfer ablation (02 §4) | `python -m model.ablation …` | `tests/test_datasets.py` |
| `dashboard/` | Flask demo dashboard, fixture + file providers (05 §4 script) | `python -m dashboard.app --provider fixture` | `tests/test_dashboard.py` |
| `firmware/` | ESP-IDF project + host simulation binary linking all C modules | `make -C firmware/host` (ESP build needs idf.py) | `tests/test_firmware_host.py` |

Run everything: `bash run_all.sh` (tests + C builds + model pipeline on `data/features_sim.csv`).
