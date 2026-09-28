#!/usr/bin/env bash
# Reproduces every number quoted in ../00-Status-Crosswalk.md. Runs on a laptop in ~10 min (excluding the 1 Hz simulation).
set -euo pipefail; cd "$(dirname "$0")"
FEAT=${1:-data/features_sim_all.csv}
for m in ekf autopilot nilm pq healthlog; do make -s -C $m >/dev/null; done
python3 -m pytest -q
python3 -m model.train --data "$FEAT" --out model/artifacts_sim/ --n-test 3 --n-calib 3 --cv-folds 4 --epochs 400 --cv-epochs 150 --seeds 3 --patience 60 --lr 5e-4 --batch-size 32
python3 -m model.evaluate --artifacts model/artifacts_sim/ --data "$FEAT"
python3 -m model.quantize --artifacts model/artifacts_sim/ --data "$FEAT"
python3 -m model.export_tflite --artifacts model/artifacts_sim/ --data "$FEAT" || echo "tflite export needs tensorflow"
# the firmware int8 self-test vector must be regenerated whenever the model is retrained
python3 firmware/tools/make_model_stats.py && python3 firmware/tools/make_golden.py
make -s -C firmware/host clean >/dev/null 2>&1 || true; make -s -C firmware/host && echo "host firmware built"
python3 -m pytest -q firmware/tests
echo "DONE — see model/artifacts_sim/metrics_summary.md"
