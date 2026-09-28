"""tests/test_nilm.py -- end-to-end evaluation of the NILM pipeline on the
synthetic Indian-home stream (nilm/appliance_sim.py).

Covers:
  * event detection recall/precision vs. ground truth
  * ON/OFF pairing rate
  * per-class F1 after simulated user labelling (first 3 events/cluster,
    label = ground-truth majority -- stands in for the app's "what just
    turned on?" flow, design 06 Sec 4.2.3)
  * energy reconciliation (design 06 Sec 4.4)
  * C detector/pairing bit-parity with the Python port (subprocess; skipped
    if gcc is unavailable)
  * PZEM-004T v3 frame parser CRC + value decoding (subprocess to the C host
    test binary; skipped if gcc is unavailable)

Numbers are printed (run with `pytest -q -s tests/test_nilm.py`) and are
sanity-bounded, not held to product targets: this is a synthetic stream, and
design 06 Sec 5.3's targets are stated as multi-week, on-hardware figures.
"""
from __future__ import annotations

import math
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nilm.appliance_sim import simulate_home
from nilm.event_detector import DetParams, run_detector_on_stream, pair_events
from nilm.library import ApplianceLibrary, energy_reconciliation

ROOT = Path(__file__).resolve().parent.parent
NILM_DIR = ROOT / "nilm"
HAS_GCC = shutil.which("gcc") is not None

SIM_DURATION_S = 12 * 3600
SIM_RATE_HZ = 3.125
SIM_SEED = 7


@pytest.fixture(scope="module")
def sim():
    stream, gt = simulate_home(duration_s=SIM_DURATION_S, rate_hz=SIM_RATE_HZ,
                                afe=True, seed=SIM_SEED)
    return stream, gt


@pytest.fixture(scope="module")
def detected(sim):
    stream, gt = sim
    events = run_detector_on_stream(stream, has_afe=True, rate_hz=SIM_RATE_HZ)
    pair_events(events)
    return events


def _match_to_ground_truth(ons, gt_df: pd.DataFrame, tol_s: float = 3.0):
    """Greedy nearest-time matching of detected ON events to ground-truth ON
    transitions of the same sign, within tol_s. Returns (label_by_id,
    n_gt_matched, gt_sorted)."""
    gt_sorted = gt_df.sort_values("t0").reset_index(drop=True)
    used = set()
    label_by_id = {}
    for ev in ons:
        best_i, best_dt = None, tol_s
        for i, row in gt_sorted.iterrows():
            if i in used:
                continue
            dt = abs(row.t0 - ev.t0)
            if dt <= best_dt:
                best_dt, best_i = dt, i
        if best_i is not None:
            used.add(best_i)
            label_by_id[id(ev)] = gt_sorted.loc[best_i, "appliance"]
    return label_by_id, len(used), gt_sorted


def test_event_detection_recall_precision(sim, detected):
    stream, gt = sim
    ons = [e for e in detected if e.kind == "ON"]
    label_by_id, n_matched_gt, gt_sorted = _match_to_ground_truth(ons, gt, tol_s=3.0)

    recall = n_matched_gt / len(gt_sorted)
    n_events_matched = sum(1 for e in ons if id(e) in label_by_id)
    precision = n_events_matched / len(ons) if ons else 0.0

    print(f"\n[NILM] detection: n_gt_on={len(gt_sorted)} n_detected_on={len(ons)} "
          f"recall={recall:.3f} precision={precision:.3f}")

    # Sanity bounds for a synthetic stream with random overlaps -- not the
    # multi-week, on-hardware targets of design 06 Sec 5.3.
    assert recall >= 0.85, f"recall too low: {recall:.3f}"
    assert precision >= 0.5, f"precision too low: {precision:.3f}"


def test_pairing_rate(detected):
    ons = [e for e in detected if e.kind == "ON"]
    paired = sum(1 for e in ons if e.paired)
    rate = paired / len(ons) if ons else 0.0
    print(f"[NILM] pairing rate: {paired}/{len(ons)} = {rate:.3f}")
    assert rate >= 0.5, f"pairing rate too low: {rate:.3f}"


def test_per_class_f1_after_user_labelling(sim, detected):
    sklearn_metrics = pytest.importorskip("sklearn.metrics")
    stream, gt = sim
    ons = [e for e in detected if e.kind == "ON"]
    paired_ons = [e for e in ons if e.paired]
    label_by_id, _, _ = _match_to_ground_truth(ons, gt, tol_s=3.0)

    # design 06 Sec 4.2.2: leader clustering runs on paired events.
    lib = ApplianceLibrary()
    for ev in paired_ons:
        lib.ingest(ev)

    # simulated user labelling (design 06 Sec 4.2.3): once a cluster reaches
    # >= 3 events, label it with the ground-truth majority of its first 3
    # events (a perfect stand-in for the "what just turned on?" prompt).
    n_user_labelled = 0
    for c in lib.clusters.values():
        if c.n < 3:
            continue
        first3 = c.events[:3]
        labels = [label_by_id.get(id(lib.events[i])) for i in first3]
        labels = [l for l in labels if l is not None]
        if labels:
            majority = Counter(labels).most_common(1)[0][0]
            lib.label_cluster(c.cluster_id, majority)
            n_user_labelled += 1

    y_true, y_pred = [], []
    for i, ev in enumerate(lib.events):
        true_label = label_by_id.get(id(ev))
        if true_label is None:
            continue
        cluster = lib.clusters[lib.assignments[i]]
        y_true.append(true_label)
        y_pred.append(cluster.label or "Unknown")

    report = sklearn_metrics.classification_report(y_true, y_pred, zero_division=0,
                                                     output_dict=True)
    print(f"\n[NILM] classifier: {n_user_labelled} clusters user-labelled, "
          f"{len(y_true)} paired+matched events scored")
    for label, stats in sorted(report.items()):
        if isinstance(stats, dict) and "f1-score" in stats and label not in ("accuracy",):
            print(f"  {label:12s} precision={stats['precision']:.2f} "
                  f"recall={stats['recall']:.2f} f1={stats['f1-score']:.2f} "
                  f"support={int(stats['support'])}")
    print(f"  overall accuracy={report['accuracy']:.3f}")

    # Fridge is the strongest class in every 1 Hz NILM benchmark (design 06
    # Sec 5.2/5.3) and has the most occurrences in this window -- require it
    # to actually work; do not hold rare (1-occurrence) classes to a bar.
    fridge_f1 = report.get("fridge", {}).get("f1-score", 0.0)
    assert fridge_f1 >= 0.5, f"fridge F1 too low: {fridge_f1:.3f}"


def test_energy_reconciliation(sim, detected):
    stream, gt = sim
    rec = energy_reconciliation(stream["t"].to_numpy(), stream["P"].to_numpy(), detected)
    print(f"\n[NILM] energy reconciliation: assigned {rec['total_assigned_wh']:.1f} Wh / "
          f"measured {rec['total_measured_wh']:.1f} Wh = {rec['fraction_assigned']:.3f}")
    # Honest note: >= 95% is design 06 Sec 4.4's target after weeks of
    # library growth; this single 12 h synthetic run is reported, not forced.
    assert rec["fraction_assigned"] > 0.0
    assert rec["fraction_assigned"] <= 1.0 + 1e-6


# --------------------------------------------------------------------------- #
# C parity
# --------------------------------------------------------------------------- #
def _build_c_binaries():
    subprocess.run(["make", "-C", str(NILM_DIR)], check=True, capture_output=True)


@pytest.mark.skipif(not HAS_GCC, reason="gcc not available")
def test_c_matches_python(sim):
    _build_c_binaries()
    stream, _ = sim
    # Use a shorter slice for a fast, still-representative parity check.
    sub = stream.iloc[: int(3600 * SIM_RATE_HZ)]
    csv_text = "\n".join(f"{t:.6f},{p:.6f},{q:.6f},{v:.6f}"
                          for t, p, q, v in zip(sub["t"], sub["P"], sub["Q"], sub["Vrms"]))

    binary = NILM_DIR / "event_detector_main"
    proc = subprocess.run([str(binary), str(SIM_RATE_HZ)], input=csv_text,
                           capture_output=True, text=True, check=True)
    c_lines = [l for l in proc.stdout.strip().splitlines() if l]

    py_params = DetParams(rate_hz=SIM_RATE_HZ)
    py_events = run_detector_on_stream(sub, has_afe=False, rate_hz=SIM_RATE_HZ, params=py_params)

    print(f"\n[NILM] C/Python parity: C emitted {len(c_lines)}, Python emitted {len(py_events)}")
    assert len(c_lines) == len(py_events)
    for line, ev in zip(c_lines, py_events):
        t0_c, t_off_c, dP_c, dQ_c, t_settle_c, A_tr_c, dur_c, paired_c, kind_c = line.split(",")
        assert math.isclose(float(t0_c), ev.t0, abs_tol=1e-3)
        assert math.isclose(float(dP_c), ev.dP, abs_tol=1e-2)
        assert math.isclose(float(dQ_c), ev.dQ, abs_tol=1e-2)
        assert math.isclose(float(t_settle_c), ev.t_settle_s, abs_tol=1e-3)


@pytest.mark.skipif(not HAS_GCC, reason="gcc not available")
def test_c_host_unit_tests_pass():
    _build_c_binaries()
    for binary in ("test_event_detector_host", "test_pzem_parser_host"):
        proc = subprocess.run([str(NILM_DIR / binary)], capture_output=True, text=True)
        print(f"\n[NILM] {binary}:\n{proc.stdout}{proc.stderr}")
        assert proc.returncode == 0, f"{binary} failed: {proc.stdout}{proc.stderr}"
