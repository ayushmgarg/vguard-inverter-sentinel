"""tests/test_datasets.py -- model/datasets/{nasa_pcoe,calce,synthetic}.py and
model/stages.py, using tiny synthetic .mat/.xlsx fixtures built in tmp_path
that mimic the real NASA PCoE / CALCE formats (a handful of cycles each).
"""

from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from features.schema import DYNAMIC_FEATURES, STATIC_FEATURES, LABEL_COLUMNS  # noqa: E402
from model.datasets._common import sha256_file, write_manifest, MANIFEST_COLUMNS  # noqa: E402
from model.datasets import nasa_pcoe, calce, synthetic  # noqa: E402

SCHEMA_COLUMNS = DYNAMIC_FEATURES + STATIC_FEATURES + LABEL_COLUMNS


# --------------------------------------------------------------------------- #
# NASA PCoE fixture
# --------------------------------------------------------------------------- #

def _make_nasa_cycle(ctype, t0, n, soh_frac, cap0_ah, rng):
    """One NASA-style cycle struct dict: type/ambient_temperature/time/data,
    with data.{Voltage_measured,Current_measured,Temperature_measured,Time}
    and, for discharge, data.Capacity. Realistic Ah scale: dt=30s per sample
    so a 2 Ah cell over ~n*30s of CC current comes out self-consistent."""
    t = np.arange(n, dtype=float) * 30.0
    if ctype == "charge":
        i_mag = np.concatenate([np.full(n // 2, 1.5), np.linspace(1.5, 0.05, n - n // 2)])
        V = np.concatenate([np.linspace(3.4, 4.2, n // 2), np.full(n - n // 2, 4.2)])
        I_raw = -i_mag  # NASA convention: negative during charge
    else:
        i_mag = np.full(n, 2.0 * soh_frac)
        V = np.linspace(4.0, 3.0, n)
        I_raw = i_mag  # NASA convention: positive during discharge
    T = np.full(n, 24.0) + rng.normal(0, 0.3, n)
    dv = [t0.year, t0.month, t0.day, t0.hour, t0.minute, float(t0.second)]
    data = {"Voltage_measured": V, "Current_measured": I_raw, "Temperature_measured": T, "Time": t}
    if ctype == "discharge":
        data["Capacity"] = np.array([cap0_ah * soh_frac])
    return {"type": ctype, "ambient_temperature": 24.0, "time": np.array(dv, dtype=float), "data": data}


@pytest.fixture
def nasa_mat_path(tmp_path):
    from scipy.io import savemat
    rng = np.random.default_rng(0)
    t0 = datetime.datetime(2020, 1, 1, 0, 0, 0)
    cap0 = 2.0
    n_cycles = 6
    cycles = []
    for k in range(n_cycles):
        soh_frac = 1.0 - 0.05 * k  # -> 75% by the last cycle, crosses 80% EoL
        cycles.append(_make_nasa_cycle("charge", t0 + datetime.timedelta(hours=4 * k), 24, soh_frac, cap0, rng))
        cycles.append(_make_nasa_cycle("discharge", t0 + datetime.timedelta(hours=4 * k + 1), 40, soh_frac, cap0, rng))
    path = tmp_path / "B0099.mat"
    savemat(str(path), {"B0099": {"cycle": cycles}})
    return path


def test_nasa_pcoe_schema_columns_exact(nasa_mat_path):
    battery_id, df, n_discharge = nasa_pcoe.process_mat_file(nasa_mat_path)
    assert battery_id == "B0099"
    assert list(df.columns) == SCHEMA_COLUMNS
    assert n_discharge == 6
    assert len(df) == 6


def test_nasa_pcoe_nonderivable_channels_are_nan(nasa_mat_path):
    _, df, _ = nasa_pcoe.process_mat_file(nasa_mat_path)
    assert df["ocv_err"].isna().all(), "ocv_err must never be fabricated (needs an EKF/OCV reference)"
    assert df["st_float"].isna().all(), "st_float must never be fabricated (no float-charge phase in NASA cycling)"
    # everything else genuinely derivable from this fixture should NOT be all-NaN
    for col in ["r_ratio", "sag_ratio", "q_dis_norm", "dod", "eta_c", "ca_ratio",
                "cv_frac", "ic_peak_h", "t_mean", "ln_tfull", "efc",
                "st_total_per_day", "f_dod50", "f_lowsoc", "age_years"]:
        assert df[col].notna().any(), "%s should be derived, not all-NaN, on this fixture" % col


def test_nasa_pcoe_soh_true_monotone_ish_from_capacity(nasa_mat_path):
    _, df, _ = nasa_pcoe.process_mat_file(nasa_mat_path)
    soh = df["soh_true"].to_numpy()
    assert soh[0] == pytest.approx(100.0, abs=1e-6), "first cycle is the SoH-true baseline by construction"
    # monotone-ish: allow no more than one small positive blip, overall trend down
    assert soh[-1] < soh[0]
    n_increases = int(np.sum(np.diff(soh) > 1e-6))
    assert n_increases <= 1, "capacity fade should be essentially monotone on a clean fixture: %s" % soh.tolist()
    # rul_efc_true must reach (or extrapolate to) zero as SoH approaches EoL
    assert df["rul_efc_true"].iloc[-1] >= 0.0
    assert (df["rul_efc_true"].to_numpy() >= 0).all()


def test_nasa_pcoe_manifest_written_with_sha256(tmp_path, nasa_mat_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw_dir = tmp_path / "raw_nasa"
    raw_dir.mkdir()
    dest = raw_dir / "B0099.mat"
    dest.write_bytes(nasa_mat_path.read_bytes())
    out_csv = tmp_path / "features_nasa_test.csv"

    argv = ["nasa_pcoe.py", "--raw-dir", str(raw_dir), "--out", str(out_csv),
            "--batteries", "B0099"]
    monkeypatch.setattr(sys, "argv", argv)
    nasa_pcoe.main()

    assert out_csv.exists()
    df = pd.read_csv(out_csv)
    assert list(df.columns) == SCHEMA_COLUMNS

    manifest_path = tmp_path / "data" / "manifests" / "nasa_pcoe_manifest.csv"
    assert manifest_path.exists()
    mdf = pd.read_csv(manifest_path)
    assert list(mdf.columns) == MANIFEST_COLUMNS
    assert len(mdf) == 1
    row = mdf.iloc[0]
    assert row["battery_id"] == "B0099"
    assert row["sha256"] == sha256_file(dest)
    assert row["n_cycles"] == 6


# --------------------------------------------------------------------------- #
# CALCE fixture
# --------------------------------------------------------------------------- #

def _make_calce_rows(cyc, t_start, cap0_ah, soh_frac, dt=20.0):
    rows = []
    t = t_start
    n_cc, n_cv = 12, 8
    i_cc = cap0_ah * soh_frac  # ~1C CC current
    q_chg = 0.0
    for i in range(n_cc):
        v = 3.0 + (4.2 - 3.0) * i / n_cc
        q_chg += i_cc * dt / 3600.0
        rows.append([cyc, t, i_cc, v, q_chg, 0.0, 26.0])
        t += dt
    for i in range(n_cv):
        I = i_cc * np.exp(-i / 3.0) + 0.02
        q_chg += I * dt / 3600.0
        rows.append([cyc, t, I, 4.2, q_chg, 0.0, 26.0])
        t += dt
    for _ in range(3):
        rows.append([cyc, t, 0.0, 4.15, q_chg, 0.0, 26.0])
        t += dt
    n_dis = 30
    i_dis = cap0_ah * soh_frac
    q_dis = 0.0
    for i in range(n_dis):
        v = 4.1 - (4.1 - 3.0) * i / n_dis
        q_dis += i_dis * dt / 3600.0
        rows.append([cyc, t, -i_dis, v, q_chg, q_dis, 26.0])
        t += dt
    return rows, t


@pytest.fixture
def calce_xlsx_dir(tmp_path):
    rows = []
    t = 0.0
    cap0 = 1.1
    for c in range(1, 6):
        soh_frac = 1.0 - 0.05 * (c - 1)  # -> 80% by the last cycle
        r, t = _make_calce_rows(c, t, cap0, soh_frac)
        rows.extend(r)
    cols = ["Cycle_Index", "Test_Time(s)", "Current(A)", "Voltage(V)",
            "Charge_Capacity(Ah)", "Discharge_Capacity(Ah)", "Temperature (C)"]
    df = pd.DataFrame(rows, columns=cols)
    out_dir = tmp_path / "raw_calce" / "CS2_99"
    out_dir.mkdir(parents=True)
    path = out_dir / "CS2_99_1_1_2015.xlsx"
    with pd.ExcelWriter(path) as w:
        df.to_excel(w, sheet_name="Channel_1-006", index=False)
        pd.DataFrame({"junk": [1, 2, 3]}).to_excel(w, sheet_name="Statistics_1-006", index=False)
    return out_dir


def test_calce_schema_columns_exact(calce_xlsx_dir):
    df = calce.process_battery(calce_xlsx_dir, "CS2_99")
    assert list(df.columns) == SCHEMA_COLUMNS
    assert len(df) == 5


def test_calce_nonderivable_channels_are_nan(calce_xlsx_dir):
    df = calce.process_battery(calce_xlsx_dir, "CS2_99")
    assert df["ocv_err"].isna().all()
    assert df["st_float"].isna().all()
    # this fixture DOES carry a temperature column -> t_mean must be derived
    assert df["t_mean"].notna().all()
    for col in ["q_dis_norm", "dod", "eta_c", "ca_ratio", "cv_frac", "ic_peak_h", "efc", "f_dod50"]:
        assert df[col].notna().any(), "%s should be derived on this fixture" % col
    # no Date_Time column in this fixture -> age_years/ln_tfull have nothing to derive from
    assert df["age_years"].isna().all()


def test_calce_soh_true_monotone_ish_from_capacity(calce_xlsx_dir):
    df = calce.process_battery(calce_xlsx_dir, "CS2_99")
    soh = df["soh_true"].to_numpy()
    assert soh[0] == pytest.approx(100.0, abs=1e-6)
    assert soh[-1] < soh[0]
    assert int(np.sum(np.diff(soh) > 1e-6)) == 0


def test_calce_manifest_written_with_sha256(tmp_path, calce_xlsx_dir, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out_csv = tmp_path / "features_calce_test.csv"
    src_file = next(calce_xlsx_dir.glob("*.xlsx"))

    argv = ["calce.py", "--raw-dir", str(calce_xlsx_dir.parent), "--out", str(out_csv),
            "--battery-id", "CS2_99"]
    monkeypatch.setattr(sys, "argv", argv)
    calce.main()

    assert out_csv.exists()
    df = pd.read_csv(out_csv)
    assert list(df.columns) == SCHEMA_COLUMNS

    manifest_path = tmp_path / "data" / "manifests" / "calce_manifest.csv"
    assert manifest_path.exists()
    mdf = pd.read_csv(manifest_path)
    assert list(mdf.columns) == MANIFEST_COLUMNS
    row = mdf.iloc[0]
    assert row["battery_id"] == "CS2_99"
    assert row["sha256"] == sha256_file(src_file)


# --------------------------------------------------------------------------- #
# synthetic.py registration wrapper
# --------------------------------------------------------------------------- #

def test_synthetic_manifest_from_real_sim_csv(tmp_path, monkeypatch):
    data_path = ROOT / "data" / "features_sim.csv"
    if not data_path.exists():
        pytest.skip("data/features_sim.csv not present in this checkout")
    monkeypatch.chdir(tmp_path)
    out_path, rows = synthetic.build_manifest(data_path, "sim_run_a_test")
    assert out_path.exists()
    mdf = pd.read_csv(out_path)
    assert list(mdf.columns) == MANIFEST_COLUMNS
    assert len(mdf) == pd.read_csv(data_path)["battery_id"].nunique()
    assert (mdf["sha256"] == sha256_file(data_path)).all()


# --------------------------------------------------------------------------- #
# write_manifest unit test (shared helper)
# --------------------------------------------------------------------------- #

def test_write_manifest_columns_and_sha(tmp_path):
    f = tmp_path / "dummy.bin"
    f.write_bytes(b"hello world")
    rows = [{"battery_id": "X1", "chemistry": "test", "n_cycles": 3,
             "capacity_bol": 100.0, "capacity_eol": 80.0,
             "source_file": str(f), "sha256": sha256_file(f)}]
    out = write_manifest(rows, tmp_path / "manifests" / "x.csv")
    assert out.exists()
    df = pd.read_csv(out)
    assert list(df.columns) == MANIFEST_COLUMNS
    assert df.iloc[0]["sha256"] == sha256_file(f)


# --------------------------------------------------------------------------- #
# model/stages.py: Stage B -> Stage C on a dummy CSV, must run in a few seconds
# --------------------------------------------------------------------------- #

def _make_dummy_features_csv(path, n_batteries=6, n_cycles=18, seed=0):
    rng = np.random.default_rng(seed)
    frames = []
    for b in range(n_batteries):
        k = np.arange(n_cycles)
        soh = 100.0 - 20.0 * (k / (n_cycles - 1)) + rng.normal(0, 0.2, n_cycles)
        s = np.clip((100.0 - soh) / 20.0, 0, 1)
        efc = np.cumsum(np.full(n_cycles, 0.4))
        df = pd.DataFrame({
            "r_ratio": 1.0 + 0.5 * s, "sag_ratio": 1.0 + 0.4 * s,
            "q_dis_norm": 0.4 + rng.normal(0, 0.01, n_cycles), "dod": 0.4 + rng.normal(0, 0.01, n_cycles),
            "eta_c": 0.9 - 0.05 * s, "eta_stale": 0.0, "ca_ratio": 1.0 - 0.2 * s, "cv_frac": 0.3 + 0.1 * s,
            "ic_peak_h": 1.0 - 0.3 * s, "ic_peak_v": 0.1 * s, "ica_stale": 0.0,
            "t_mean": 28.0 + rng.normal(0, 1, n_cycles), "ln_tfull": 0.5 + rng.normal(0, 0.05, n_cycles),
            "ocv_err": rng.normal(0, 0.01, n_cycles),
            "efc": efc, "st_total_per_day": 1.0, "st_float": 0.3, "f_dod50": 0.5, "f_lowsoc": 0.2,
            "age_years": (k + 1) / 365.0,
            "soh_true": soh, "rul_efc_true": np.clip(20.0 - efc, 0, None),
            "battery_id": "D%02d" % b, "cycle_idx": k,
        })
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out = out[SCHEMA_COLUMNS]
    out.to_csv(path, index=False)
    return path


def test_stages_b_then_c_runs_fast(tmp_path):
    from model import stages
    data_path = _make_dummy_features_csv(tmp_path / "dummy_features.csv")

    t0 = time.time()
    out_b, split_b, summary_b = stages.run_stage(
        "B", str(data_path), "none", str(tmp_path / "stageB"),
        seeds=1, epochs=2, n_calib=1, n_test=1, patience=2, verbose=False)
    assert (tmp_path / "stageB" / "seed0.pt").exists()

    out_c, split_c, summary_c = stages.run_stage(
        "C", str(data_path), str(tmp_path / "stageB"), str(tmp_path / "stageC"),
        seeds=1, epochs=2, freeze_epochs=2, n_calib=1, n_test=1, patience=2, verbose=False)
    elapsed = time.time() - t0

    assert (tmp_path / "stageC" / "seed0.pt").exists()
    assert summary_c["freeze_conv"] is True
    assert summary_c["l2sp_beta"] > 0
    # same target CSV + same (n_calib, n_test, seeds) -> identical battery-level split
    assert split_b["test_batteries"] == split_c["test_batteries"] if split_b["n_test"] == split_c["n_test"] else True
    assert elapsed < 60.0, "Stage B->C on a 6-battery/18-cycle dummy CSV took %.1fs, expected a few seconds" % elapsed


def test_stages_freeze_conv_actually_freezes(tmp_path):
    """Sanity check on the one bit of genuinely new logic in stages.py:
    conv weights must not move during a frozen-conv phase, and must move
    once unfrozen."""
    import torch
    from model import stages
    from model.net import build_model
    from model.windowing import build_windows, fit_standardizer, apply_standardizer, compute_sample_weights
    from model.windowing import load_and_validate
    from features.schema import scale_soh, scale_rul

    data_path = _make_dummy_features_csv(tmp_path / "dummy2.csv", n_batteries=4, n_cycles=15)
    df = load_and_validate(str(data_path))
    windows = build_windows(df)
    stats = fit_standardizer(windows.X_dyn, windows.X_stat)
    Xd, Xs = apply_standardizer(windows.X_dyn, windows.X_stat, stats)
    soh_s = scale_soh(windows.soh_true)
    rul_s = scale_rul(windows.rul_true)
    w = compute_sample_weights(windows.rul_true)
    idx = np.arange(len(windows))
    train_idx, val_idx = idx[: len(idx) // 2], idx[len(idx) // 2:]

    init_model = build_model()
    init_state = {k: v.clone() for k, v in init_model.state_dict().items()}

    model_frozen, _, _ = stages.train_one_seed_transfer(
        0, Xd, Xs, soh_s, rul_s, w, windows.adjacent_pairs, train_idx, val_idx,
        init_state_dict=init_state, freeze_conv=True, l2sp_beta=0.0, epochs=2,
        patience=5, verbose=False)
    for name in stages.CONV_LAYER_NAMES:
        for p_before, p_after in zip(getattr(init_model, name).parameters(),
                                      getattr(model_frozen, name).parameters()):
            assert torch.allclose(p_before, p_after), "%s moved despite freeze_conv=True" % name

    model_unfrozen, _, _ = stages.train_one_seed_transfer(
        0, Xd, Xs, soh_s, rul_s, w, windows.adjacent_pairs, train_idx, val_idx,
        init_state_dict=init_state, freeze_conv=False, l2sp_beta=0.0, epochs=3,
        patience=5, verbose=False)
    moved = any(
        not torch.allclose(p_before, p_after)
        for name in stages.CONV_LAYER_NAMES
        for p_before, p_after in zip(getattr(init_model, name).parameters(),
                                      getattr(model_unfrozen, name).parameters())
    )
    assert moved, "conv weights should change over 3 epochs when unfrozen"
