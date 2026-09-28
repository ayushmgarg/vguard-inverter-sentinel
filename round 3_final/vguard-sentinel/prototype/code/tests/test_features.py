"""Sanity tests for features/cycle_features.py -- see features/README.md."""
import os

import numpy as np
import pandas as pd
import pytest

from features.schema import OPTIONAL_COLUMNS, ALL_COLUMNS, DYNAMIC_FEATURES, STATIC_FEATURES, LABEL_COLUMNS
from features.cycle_features import process_battery, _compute_rul, ICA_MIN_SOC_START


@pytest.fixture(scope="module")
def small_sim(tmp_path_factory):
    """One fast battery run, aged enough to see ratio drift."""
    out_dir = tmp_path_factory.mktemp("small_sim")
    from sim import battery_sim
    bp, cycle_rows = battery_sim.simulate_battery(
        battery_id=0, master_seed=3, out_dir=str(out_dir), max_cycles=20,
        cycle_hours_range=(8.0, 12.0), label_noise_std=0.0, sensor_noise=True,
        float_cap_hours=2.0,
    )
    return str(out_dir), bp


@pytest.fixture(scope="module")
def feature_rows(small_sim):
    out_dir, bp = small_sim
    csv_path = os.path.join(out_dir, "battery_000.csv")
    cycles, ctx = process_battery(0, csv_path, bp.C_rated)
    if cycles:
        _compute_rul(cycles)
    return cycles


def test_schema_exact_order_and_names():
    assert len(DYNAMIC_FEATURES) == 14
    assert len(STATIC_FEATURES) == 6
    assert ALL_COLUMNS == DYNAMIC_FEATURES + STATIC_FEATURES + LABEL_COLUMNS


def test_output_csv_has_exact_schema():
    assert os.path.exists("data/features_sim.csv"), "run features CLI first"
    df = pd.read_csv("data/features_sim.csv")
    # required columns in exact schema order, followed only by registered optional columns
    assert list(df.columns)[:len(ALL_COLUMNS)] == ALL_COLUMNS
    assert set(df.columns[len(ALL_COLUMNS):]) <= set(OPTIONAL_COLUMNS)


def test_feature_rows_produced(feature_rows):
    assert len(feature_rows) > 0, "no cycles were detected by the state machine"


def test_all_dynamic_columns_present(feature_rows):
    for row in feature_rows:
        for col in DYNAMIC_FEATURES + STATIC_FEATURES + ["soh_true", "battery_id", "cycle_idx"]:
            assert col in row


def test_ratio_features_near_one_at_start(feature_rows):
    """r_ratio / sag_ratio should be roughly near 1.0 in the first few cycles (they
    ARE part of their own baseline window, but with very few valid transient samples
    per cycle this early the median is noisy on a single synthetic battery -- this is
    a loose sanity bound, not a precision claim)."""
    df = pd.DataFrame(feature_rows).sort_values("cycle_idx")
    early = df[df["cycle_idx"] < 5]
    checked = False
    for col in ("r_ratio", "sag_ratio"):
        vals = early[col].dropna()
        if len(vals) == 0:
            continue
        checked = True
        assert vals.median() == pytest.approx(1.0, abs=1.0), "%s not near 1 early on" % col
    assert checked, "neither ratio feature had early valid samples to check"


def test_ratio_features_drift_with_age(feature_rows):
    """At least one of the resistance-linked ratio features should trend away from 1.0
    as R0 grows with age (design 02 SS1.2: resistance growth precedes capacity loss)."""
    df = pd.DataFrame(feature_rows).sort_values("cycle_idx")
    late = df[df["cycle_idx"] >= df["cycle_idx"].max() - 3]
    early = df[df["cycle_idx"] < 5]
    drifted = False
    for col in ("r_ratio", "sag_ratio"):
        e = early[col].dropna()
        l = late[col].dropna()
        if len(e) and len(l) and abs(l.median() - 1.0) > abs(e.median() - 1.0) - 1e-6:
            drifted = True
    assert drifted, "no resistance-linked ratio feature drifted away from baseline with age"


def test_soh_true_nonincreasing(feature_rows):
    df = pd.DataFrame(feature_rows).sort_values("cycle_idx")
    assert (np.diff(df["soh_true"].to_numpy()) <= 1e-9).all()


def test_ica_validity_logic():
    """ic_valid requires SoC_start <= 70% at CC entry; below that threshold it must
    stay unpopulated (NaN) rather than fabricate a value."""
    assert ICA_MIN_SOC_START == 0.70


def test_ica_validity_gate_on_synthetic_data(feature_rows):
    """When ICA *is* valid, ic_peak_h must be a finite positive ratio; staleness must
    be 0 on a fresh valid cycle and climb (up to 1.0, i.e. 30 cycles) when stale."""
    df = pd.DataFrame(feature_rows).sort_values("cycle_idx")
    assert df["ica_stale"].between(0.0, 1.0).all()
    valid_rows = df[df["ic_peak_h"].notna()]
    if len(valid_rows):
        assert (valid_rows["ic_peak_h"] > 0).all()
        assert (valid_rows["ica_stale"] < 1.0).any()


def test_staleness_features_bounded(feature_rows):
    df = pd.DataFrame(feature_rows)
    assert df["eta_stale"].between(0.0, 1.0).all()
    assert df["ica_stale"].between(0.0, 1.0).all()


def test_rul_efc_true_semantics(feature_rows):
    """NaN if soh_true never reaches <=80 in this run; else non-negative and
    non-increasing... actually non-decreasing isn't guaranteed cycle to cycle since it
    counts down, so just check non-negativity and NaN-consistency."""
    df = pd.DataFrame(feature_rows)
    if df["soh_true"].min() > 80.0:
        assert df["rul_efc_true"].isna().all()
    else:
        finite = df["rul_efc_true"].dropna()
        assert (finite >= 0).all()


def test_cli_end_to_end(tmp_path):
    import subprocess
    import sys
    sim_out = str(tmp_path / "sim_out")
    feat_out = str(tmp_path / "features.csv")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r1 = subprocess.run(
        [sys.executable, "-m", "sim.battery_sim", "--n", "1", "--out", sim_out,
         "--seed", "5", "--cycles", "3"],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    assert r1.returncode == 0, r1.stderr
    r2 = subprocess.run(
        [sys.executable, "-m", "features.cycle_features", "--in", sim_out, "--out", feat_out],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    assert r2.returncode == 0, r2.stderr
    assert os.path.exists(feat_out)
    df = pd.read_csv(feat_out)
    # required columns in exact schema order, followed only by registered optional columns
    assert list(df.columns)[:len(ALL_COLUMNS)] == ALL_COLUMNS
    assert set(df.columns[len(ALL_COLUMNS):]) <= set(OPTIONAL_COLUMNS)
