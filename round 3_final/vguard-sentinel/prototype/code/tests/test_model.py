"""tests/test_model.py — module B (TinyML SoH/RUL) unit tests.

Run: pytest -q tests/test_model.py   (or `pytest -q` from the repo root)

Covers: net shapes/param-count/non-crossing quantiles, windowing (incl.
oldest-cycle padding), the int8 reference vs float model, and the grade
state machine's hysteresis rules. Uses small synthetic data generated
on the fly (model/make_dummy_features.py) -- no dependency on the real
data/features_sim.csv landing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.schema import (  # noqa: E402
    WINDOW_CYCLES as WINDOW_LEN, N_DYNAMIC, N_STATIC, MIN_REAL_CYCLES,
)
from model.net import build_model  # noqa: E402
from model.make_dummy_features import generate as generate_dummy  # noqa: E402
from model.windowing import build_windows, fit_standardizer, apply_standardizer  # noqa: E402
from model.grade import (  # noqa: E402
    GradeStateMachine, UsageRateEWMA, rul_efc_to_weeks, calendar_bound_weeks,
)
from model.metrics import mae_rmse, picp_pice_mpiw, split_conformal_offset, hit_rate  # noqa: E402
from model.quantize import quantize_model  # noqa: E402
from model.int8_infer import run_int8_model  # noqa: E402

torch.manual_seed(0)


# --------------------------------------------------------------------------- #
# net.py
# --------------------------------------------------------------------------- #

def test_param_count_matches_design_budget():
    net = build_model()
    n_params = net.param_count()
    # design 02 SS2.2 table: total ~= 28.0k
    assert 27000 <= n_params <= 29000
    assert n_params == 27990  # exact, from the table's per-layer params


def test_mac_count_matches_design_budget():
    net = build_model()
    n_macs = net.mac_count()
    # design 02 SS2.2 table: total ~= 106k
    assert 100000 <= n_macs <= 112000


def test_forward_shapes():
    net = build_model()
    xb = torch.randn(5, WINDOW_LEN, N_DYNAMIC)
    xs = torch.randn(5, N_STATIC)
    out = net(xb, xs)
    for head in ("soh", "rul"):
        for k in ("p10", "q50", "p90", "d_lo", "d_hi"):
            assert out[head][k].shape == (5,)


def test_non_crossing_quantiles_random_weights():
    """Structural guarantee (ReLU deltas), not a trained-model property --
    must hold for arbitrary weights, so re-init a few times."""
    for seed in range(5):
        torch.manual_seed(seed)
        net = build_model()
        xb = torch.randn(32, WINDOW_LEN, N_DYNAMIC) * 5.0  # wide range, stresses the heads
        xs = torch.randn(32, N_STATIC) * 5.0
        out = net(xb, xs)
        for head in ("soh", "rul"):
            p10, q50, p90 = out[head]["p10"], out[head]["q50"], out[head]["p90"]
            assert torch.all(p10 <= q50 + 1e-5)
            assert torch.all(q50 <= p90 + 1e-5)


# --------------------------------------------------------------------------- #
# windowing.py
# --------------------------------------------------------------------------- #

def _tiny_df():
    return generate_dummy(n_batteries=3, cycles_mean=25, cycles_sd=2, seed=1)


def test_build_windows_shapes_and_min_cycles():
    df = _tiny_df()
    windows = build_windows(df)
    assert windows.X_dyn.shape[1:] == (WINDOW_LEN, N_DYNAMIC)
    assert windows.X_stat.shape[1:] == (N_STATIC,)
    assert len(windows) == len(windows.soh_true) == len(windows.rul_true)
    # every battery contributes (n_cycles - MIN_REAL_CYCLES + 1) windows
    for bid in set(windows.battery_id.tolist()):
        n_cycles_battery = (df["battery_id"] == bid).sum()
        expected = max(0, n_cycles_battery - MIN_REAL_CYCLES + 1)
        assert int((windows.battery_id == bid).sum()) == expected


def test_padding_repeats_oldest_cycle():
    """First window of a battery (exactly MIN_REAL_CYCLES real cycles) must
    have its leading (WINDOW_LEN - MIN_REAL_CYCLES) rows all equal to the
    battery's very first cycle's dynamic feature row (design 02 SS2.1)."""
    df = _tiny_df()
    bid = df["battery_id"].iloc[0]
    g = df[df["battery_id"] == bid].sort_values("cycle_idx").reset_index(drop=True)
    windows = build_windows(df)
    first_idx = np.where(windows.battery_id == bid)[0][0]
    first_window = windows.X_dyn[first_idx]
    n_pad = WINDOW_LEN - MIN_REAL_CYCLES
    from features.schema import DYNAMIC_FEATURES as DYNAMIC_COLUMNS
    oldest_row = g.loc[0, DYNAMIC_COLUMNS].to_numpy(dtype=np.float32)
    for i in range(n_pad):
        assert np.allclose(first_window[i], oldest_row)
    # the (n_pad)-th row onward should be the battery's real cycles 0..9
    for i in range(MIN_REAL_CYCLES):
        assert np.allclose(first_window[n_pad + i], g.loc[i, DYNAMIC_COLUMNS].to_numpy(dtype=np.float32))


def test_standardizer_roundtrip_clips_to_unit_range():
    df = _tiny_df()
    windows = build_windows(df)
    stats = fit_standardizer(windows.X_dyn, windows.X_stat)
    zd, zs = apply_standardizer(windows.X_dyn, windows.X_stat, stats)
    assert np.all(zd >= -1.0 - 1e-6) and np.all(zd <= 1.0 + 1e-6)
    assert np.all(zs >= -1.0 - 1e-6) and np.all(zs <= 1.0 + 1e-6)


# --------------------------------------------------------------------------- #
# metrics.py
# --------------------------------------------------------------------------- #

def test_mae_rmse_basic():
    pred = np.array([1.0, 2.0, 3.0])
    true = np.array([1.0, 2.0, 5.0])
    mae, rmse = mae_rmse(pred, true)
    assert mae == pytest.approx(2.0 / 3.0)
    assert rmse >= mae  # RMSE >= MAE always


def test_picp_full_coverage():
    true = np.array([1.0, 2.0, 3.0])
    lo = true - 1.0
    hi = true + 1.0
    picp, pice, mpiw = picp_pice_mpiw(true, lo, hi, nominal=0.8)
    assert picp == 1.0
    assert mpiw == pytest.approx(2.0)


def test_split_conformal_offset_widens_undercovering_interval():
    rng = np.random.default_rng(0)
    y = rng.normal(0, 1, 1000)
    lo = np.full_like(y, -0.5)  # deliberately too narrow
    hi = np.full_like(y, 0.5)
    c_lo, c_hi = split_conformal_offset(lo, hi, y)
    assert c_lo > 0
    assert c_hi > 0
    new_picp, _, _ = picp_pice_mpiw(y, lo - c_lo, hi + c_hi, nominal=0.8)
    old_picp, _, _ = picp_pice_mpiw(y, lo, hi, nominal=0.8)
    assert new_picp > old_picp


def test_hit_rate():
    assert hit_rate(np.array([1, 2, 3]), np.array([0, 0, 0]), np.array([5, 1, 5])) == pytest.approx(2 / 3)


# --------------------------------------------------------------------------- #
# int8_infer.py vs net.py (float) -- design 02 SS5.1 expects small deltas
# --------------------------------------------------------------------------- #

def test_int8_matches_float_within_tolerance():
    df = generate_dummy(n_batteries=4, cycles_mean=30, cycles_sd=2, seed=2)
    windows = build_windows(df)
    stats = fit_standardizer(windows.X_dyn, windows.X_stat)
    Xd, Xs = apply_standardizer(windows.X_dyn, windows.X_stat, stats)

    net = build_model()
    net.train(False)

    rng = np.random.default_rng(0)
    n_repr = min(60, len(windows))
    repr_idx = rng.choice(len(windows), size=n_repr, replace=False)
    q = quantize_model(net, Xd[repr_idx], Xs[repr_idx])

    test_idx = np.arange(min(20, len(windows)))
    with torch.no_grad():
        float_out = net(torch.tensor(Xd[test_idx]), torch.tensor(Xs[test_idx]))
    int8_out = run_int8_model(q, Xd[test_idx], Xs[test_idx])

    for head in ("soh", "rul"):
        float_q50 = float_out[head]["q50"].numpy()
        int8_q50 = int8_out[head]["q50"]
        # both still in the model's own SCALED units here (not pt/EFC) --
        # tolerance is generous because this is an untrained, randomly
        # initialised network (wide activation ranges stress quantisation
        # much harder than a trained model would); design 02 SS5.1's
        # +0.1-0.3pt SoH MAE budget applies to a *trained* model evaluated
        # in real units (see model/quantize.py's quantization_report.json
        # for that number on the actual trained ensemble).
        assert np.max(np.abs(float_q50 - int8_q50)) < 0.25

    # non-crossing must survive quantisation too
    for head in ("soh", "rul"):
        assert np.all(int8_out[head]["p10"] <= int8_out[head]["q50"] + 1e-6)
        assert np.all(int8_out[head]["q50"] <= int8_out[head]["p90"] + 1e-6)


# --------------------------------------------------------------------------- #
# grade.py -- hysteresis, upgrade-hardening, N rate-limiting
# --------------------------------------------------------------------------- #

def test_collecting_to_replace_needs_persistence_too():
    """Even the very first grade (leaving COLLECTING) must satisfy the same
    3-consecutive/>=5-day hysteresis, not jump straight to a bad grade."""
    gsm = GradeStateMachine()
    r1 = gsm.update(day=0, soh_p50=70.0, rul_weeks_p10=2.0, rul_weeks_p90=10.0)
    assert r1["grade"] == "COLLECTING"  # 1st pending sample, not yet confirmed
    r2 = gsm.update(day=2, soh_p50=70.0, rul_weeks_p10=2.0, rul_weeks_p90=10.0)
    assert r2["grade"] == "COLLECTING"  # 2nd consecutive, span still < 5 days
    r3 = gsm.update(day=6, soh_p50=70.0, rul_weeks_p10=2.0, rul_weeks_p90=10.0)
    assert r3["grade"] == "REPLACE"  # 3rd consecutive, span (6 days) >= 5


def test_healthy_to_replace_needs_persistence():
    gsm = GradeStateMachine()
    # get to HEALTHY first (bypass hysteresis-from-COLLECTING using the harder re-entry bar)
    for day in (0, 6, 12):
        out = gsm.update(day=day, soh_p50=95.0, rul_weeks_p10=40.0, rul_weeks_p90=60.0)
    assert out["grade"] == "HEALTHY"

    # now push clearly-REPLACE readings, but only for 2 consecutive inferences -- must NOT flip yet
    out = gsm.update(day=20, soh_p50=70.0, rul_weeks_p10=2.0, rul_weeks_p90=5.0)
    assert out["grade"] == "HEALTHY"
    out = gsm.update(day=22, soh_p50=70.0, rul_weeks_p10=2.0, rul_weeks_p90=5.0)
    assert out["grade"] == "HEALTHY"
    # 3rd consecutive, but span since first pending sample (day 20) is only 4 days (<5) -> still must not flip
    out = gsm.update(day=24, soh_p50=70.0, rul_weeks_p10=2.0, rul_weeks_p90=5.0)
    assert out["grade"] == "HEALTHY"
    # 4th consecutive, now span >= 5 days from the first pending sample (day 20) -> flips
    out = gsm.update(day=26, soh_p50=70.0, rul_weeks_p10=2.0, rul_weeks_p90=5.0)
    assert out["grade"] == "REPLACE"


def test_upgrade_to_healthy_needs_harder_bar():
    gsm = GradeStateMachine()
    # drive to REPLACE quickly via 3 consecutive samples spanning >=5 days
    for day in (0, 3, 6):
        out = gsm.update(day=day, soh_p50=70.0, rul_weeks_p10=2.0, rul_weeks_p90=5.0)
    assert out["grade"] == "REPLACE"

    # base Healthy bar (soh>=88, rul_p10>26) met but NOT the harder re-entry
    # bar (soh>=90, rul_p10>30) -- must stay non-Healthy
    for day in (10, 16, 22):
        out = gsm.update(day=day, soh_p50=88.5, rul_weeks_p10=27.0, rul_weeks_p90=35.0)
    assert out["grade"] != "HEALTHY"

    # now clear the harder bar persistently -> should reach HEALTHY
    for day in (30, 36, 42):
        out = gsm.update(day=day, soh_p50=91.0, rul_weeks_p10=31.0, rul_weeks_p90=40.0)
    assert out["grade"] == "HEALTHY"


def test_service_now_overrides_immediately_and_restores_prior_grade():
    gsm = GradeStateMachine()
    for day in (0, 6, 12):
        out = gsm.update(day=day, soh_p50=95.0, rul_weeks_p10=40.0, rul_weeks_p90=60.0)
    assert out["grade"] == "HEALTHY"

    out = gsm.update(day=13, soh_p50=95.0, rul_weeks_p10=40.0, rul_weeks_p90=60.0, service_now=True)
    assert out["grade"] == "SERVICE_NOW"

    # once the anomaly clears, resumes from HEALTHY (not from COLLECTING/REPLACE)
    out = gsm.update(day=14, soh_p50=95.0, rul_weeks_p10=40.0, rul_weeks_p90=60.0, service_now=False)
    assert out["grade"] == "HEALTHY"


def test_n_weeks_moves_at_most_two_per_week():
    gsm = GradeStateMachine()
    for day in (0, 3, 6):
        gsm.update(day=day, soh_p50=70.0, rul_weeks_p10=20.0, rul_weeks_p90=30.0)
    n0 = gsm.n_weeks
    assert n0 == 20
    # a week later, true P10 jumps a lot -- N may move by at most 2
    out = gsm.update(day=13, soh_p50=70.0, rul_weeks_p10=2.0, rul_weeks_p90=5.0)
    assert out["n_weeks"] >= n0 - 2


def test_collecting_state_when_not_enough_data():
    gsm = GradeStateMachine()
    out = gsm.update(day=0, soh_p50=50.0, rul_weeks_p10=1.0, rul_weeks_p90=2.0, have_enough_data=False)
    assert out["grade"] == "COLLECTING"


# --------------------------------------------------------------------------- #
# grade.py -- usage-rate EWMA and weeks conversion
# --------------------------------------------------------------------------- #

def test_usage_rate_ewma_converges_toward_observed_rate():
    ewma = UsageRateEWMA(prior_rate_per_week=1.0)
    for _ in range(30):
        ewma.update(efc_delta=1.0, days_elapsed=7.0)  # steady 1 EFC/week
    assert ewma.r == pytest.approx(1.0, abs=0.05)


def test_calendar_bound_decreases_with_age():
    young = calendar_bound_weeks(age_years=0.5, af_mean=1.0, l_cal_years=5.0)
    old = calendar_bound_weeks(age_years=4.5, af_mean=1.0, l_cal_years=5.0)
    assert young > old >= 0.0


def test_rul_weeks_capped_by_calendar_bound():
    # huge RUL_EFC but the battery is already 4.9 years old against a 5y calendar life
    lo, mid, hi = rul_efc_to_weeks(rul_efc_p10=1000, rul_efc_p50=1000, rul_efc_p90=1000,
                                    r=1.0, sigma_r=0.1, age_years=4.9, l_cal_years=5.0)
    cal = calendar_bound_weeks(4.9, 1.0, 5.0)
    assert hi <= cal + 1e-6


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
