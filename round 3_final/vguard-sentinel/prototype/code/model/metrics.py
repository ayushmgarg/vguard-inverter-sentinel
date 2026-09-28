"""model/metrics.py — pure statistical metric functions used by evaluate.py.

Definitions follow design 02 §7 and 11 §1.2. Kept dependency-free (numpy
only) and side-effect-free so they are directly unit-testable.
"""

from __future__ import annotations

import numpy as np

# z-quantile ratio used to approximate a 50%-nominal interval from the
# model's only fitted interval (P10/P90, i.e. 80% nominal), since the
# architecture's quantile heads are fixed at tau in {.1,.5,.9} and do not
# produce P25/P75 directly. NOT in the design doc -- documented here and in
# model/README.md as an approximation, not a trained quantile.
Z50_OVER_Z80 = 0.6745 / 1.2816  # ~= 0.5263


def mae_rmse(pred, true):
    err = np.asarray(pred) - np.asarray(true)
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    return mae, rmse


def picp_pice_mpiw(true, p_lo, p_hi, nominal):
    true, p_lo, p_hi = np.asarray(true), np.asarray(p_lo), np.asarray(p_hi)
    covered = (true >= p_lo) & (true <= p_hi)
    picp = float(np.mean(covered))
    pice = abs(picp - nominal) * 100.0  # points
    mpiw = float(np.mean(p_hi - p_lo))
    return picp, pice, mpiw


def normalized_mpiw(p_lo, p_hi, norm_by):
    p_lo, p_hi, norm_by = np.asarray(p_lo), np.asarray(p_hi), np.asarray(norm_by)
    valid = norm_by > 1e-6
    if not np.any(valid):
        return float("nan")
    return float(np.mean((p_hi[valid] - p_lo[valid]) / norm_by[valid]))


def approx_50pct_interval(p10, p50, p90):
    p10, p50, p90 = np.asarray(p10), np.asarray(p50), np.asarray(p90)
    p25 = p50 - Z50_OVER_Z80 * (p50 - p10)
    p75 = p50 + Z50_OVER_Z80 * (p90 - p50)
    return p25, p75


def split_conformal_offset(p_lo, p_hi, y_true, alpha_q=0.9, clip_nonneg=True):
    """design 02 §4.4 / §2.4: c_lo = q_alpha(p_lo - y), c_hi = q_alpha(y - p_hi).
    Returned offsets are applied as p_lo_final = p_lo - c_lo, p_hi_final = p_hi + c_hi.
    Clipped to >= 0 by default so calibration only ever widens the band
    (a negative offset would narrow it and could invert p_lo <= p_hi)."""
    p_lo, p_hi, y_true = np.asarray(p_lo, float), np.asarray(p_hi, float), np.asarray(y_true, float)
    ok = np.isfinite(p_lo) & np.isfinite(p_hi) & np.isfinite(y_true)
    if ok.sum() == 0:
        # no usable labels (e.g. RUL for batteries that never reached EoL):
        # offsets of 0 keep the raw band; the caller must report this honestly.
        return 0.0, 0.0
    c_lo = float(np.quantile(p_lo[ok] - y_true[ok], alpha_q))
    c_hi = float(np.quantile(y_true[ok] - p_hi[ok], alpha_q))
    if clip_nonneg:
        c_lo, c_hi = max(c_lo, 0.0), max(c_hi, 0.0)
    return c_lo, c_hi


def relative_error(pred, true, eps=1e-6):
    pred, true = np.asarray(pred), np.asarray(true)
    return np.abs(pred - true) / np.maximum(np.abs(true), eps)


def hit_rate(true, lo, hi):
    true, lo, hi = np.asarray(true), np.asarray(lo), np.asarray(hi)
    return float(np.mean((true >= lo) & (true <= hi)))
