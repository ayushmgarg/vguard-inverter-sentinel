"""model/make_dummy_features.py — synthetic per-cycle feature CSV generator.

Purpose: module B (the TinyML SoH/RUL model) needs a features CSV matching
`features/schema.py` to develop and test against *before* the real
`data/features_sim.csv` lands from the feature-pipeline module. This script
fabricates a plausible one: 24 batteries, ~200 cycles each, SoH fading
monotonically-ish from ~100% to ~80% (EoL, design 02 §0) with noise, and the
14 dynamic channels drifting with wear the way design 02 §1 describes
(resistance and sag ratios rise, coulombic/charge-acceptance ratios fall,
ICA peak shifts, etc). Three synthetic "conditions" (nominal / hot / psoc)
are tagged so `model/train.py --loco` has something to leave out.

This is NOT a physics simulator (that is `sim/`'s job) and produces NO
claim about real lead-acid behaviour — see model/README.md's honesty
section. It exists solely so the rest of module B has *something* with the
right shape to train, evaluate, and quantise against.

CLI:
    python -m model.make_dummy_features --out data/features_sim_dummy.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.schema import (  # noqa: E402
    DYNAMIC_FEATURES as DYNAMIC_COLUMNS, STATIC_FEATURES as STATIC_COLUMNS,
)

# LABEL_COLUMNS in this schema already bundles battery_id/cycle_idx in with
# soh_true/rul_efc_true; split them back out for this generator's own use.
LABEL_COLUMNS = ["soh_true", "rul_efc_true"]
ID_COLUMNS = ["battery_id", "cycle_idx"]

CONDITIONS = ["nominal", "hot", "psoc"]
# roughly 14/5/5 batteries across 24 -> weighted draw
CONDITION_WEIGHTS = [0.58, 0.21, 0.21]


def _clip01(x):
    return np.clip(x, 0.0, 1.0)


def _simulate_battery(battery_id, rng, n_cycles):
    condition = rng.choice(CONDITIONS, p=CONDITION_WEIGHTS)

    # --- SoH trajectory: concave-ish fade from ~100 to ~80, plus noise ---
    gamma = rng.uniform(1.0, 1.9)  # fade shape: >1 = accelerating (knee) toward EoL
    total_fade = rng.uniform(18.0, 23.0)  # reach ~78-82% by the last cycle
    k = np.arange(n_cycles)
    frac = (k / max(n_cycles - 1, 1)) ** gamma
    base_soh = 100.0 - total_fade * frac
    noise_sigma = rng.uniform(0.15, 0.35)
    soh_true = base_soh + rng.normal(0, noise_sigma, size=n_cycles)
    soh_true = np.clip(soh_true, 55.0, 101.5)

    # --- per-cycle depth of discharge, condition-dependent ---
    if condition == "psoc":
        dod_mean, dod_sd = 0.22, 0.08
    elif condition == "hot":
        dod_mean, dod_sd = 0.42, 0.13
    else:
        dod_mean, dod_sd = 0.40, 0.12
    dod_k = np.clip(rng.normal(dod_mean, dod_sd, size=n_cycles), 0.03, 0.95)

    efc = np.cumsum(dod_k)  # equivalent full cycles, running total

    # EFC at which SoH crosses 80% (EoL), by linear interpolation on the
    # *true* curve -> defines rul_efc_true honestly relative to this series.
    below = np.where(soh_true <= 80.0)[0]
    if len(below) > 0:
        i1 = below[0]
        if i1 == 0:
            efc_eol = efc[0]
        else:
            i0 = i1 - 1
            # interpolate EFC at the crossing between i0 (>80) and i1 (<=80)
            s0, s1 = soh_true[i0], soh_true[i1]
            t = (s0 - 80.0) / max(s0 - s1, 1e-6)
            efc_eol = efc[i0] + t * (efc[i1] - efc[i0])
    else:
        # never reached EoL in the window: extrapolate the fade linearly
        rate = (100.0 - soh_true[-1]) / max(efc[-1], 1e-6) if efc[-1] > 0 else 0.0
        rate = max(rate, 1e-4)
        efc_eol = efc[-1] + (soh_true[-1] - 80.0) / rate

    rul_efc_true = np.clip(efc_eol - efc, 0.0, None)

    # --- wear fraction driving all dynamic-feature drift ---
    s = _clip01((100.0 - soh_true) / 20.0)

    r_ratio = 1.0 + 0.6 * s + rng.normal(0, 0.03, n_cycles)
    sag_ratio = 1.0 + 0.5 * s + rng.normal(0, 0.04, n_cycles)
    q_dis_norm = np.clip(dod_k * (soh_true / 100.0) + rng.normal(0, 0.01, n_cycles), 0.01, 1.0)
    dod = np.clip(dod_k + rng.normal(0, 0.01, n_cycles), 0.01, 1.0)

    # eta_c: valid ~88% of cycles, else carry-last + staleness
    eta_true = np.clip(0.95 - 0.08 * s + rng.normal(0, 0.01, n_cycles), 0.55, 0.99)
    eta_valid = rng.random(n_cycles) < 0.88
    eta_c = np.empty(n_cycles)
    eta_stale = np.empty(n_cycles)
    last, stale_ct = eta_true[0], 0
    for i in range(n_cycles):
        if eta_valid[i]:
            last, stale_ct = eta_true[i], 0
        else:
            stale_ct = min(stale_ct + 1, 30)
        eta_c[i] = last
        eta_stale[i] = stale_ct / 30.0

    ca_ratio = np.clip(1.0 - 0.35 * s + rng.normal(0, 0.03, n_cycles), 0.2, 1.15)
    cv_frac = _clip01(0.30 + 0.25 * s + rng.normal(0, 0.03, n_cycles))

    ica_valid = rng.random(n_cycles) < 0.75
    ic_h_true = np.clip(1.0 - 0.4 * s + rng.normal(0, 0.03, n_cycles), 0.1, 1.1)
    ic_v_true = np.clip(0.15 * s + rng.normal(0, 0.01, n_cycles), 0.0, 0.3)
    ic_peak_h = np.empty(n_cycles)
    ic_peak_v = np.empty(n_cycles)
    ica_stale = np.empty(n_cycles)
    last_h, last_v, stale_ct = ic_h_true[0], ic_v_true[0], 0
    for i in range(n_cycles):
        if ica_valid[i]:
            last_h, last_v, stale_ct = ic_h_true[i], ic_v_true[i], 0
        else:
            stale_ct = min(stale_ct + 1, 30)
        ic_peak_h[i] = last_h
        ic_peak_v[i] = last_v
        ica_stale[i] = stale_ct / 30.0

    t_base = {"nominal": 28.0, "hot": 45.0, "psoc": 30.0}[condition]
    season = 4.0 * np.sin(2 * np.pi * k / 365.0 + rng.uniform(0, 2 * np.pi))
    t_mean = t_base + season + rng.normal(0, 1.5, n_cycles)

    tfull_mean_h = {"nominal": 20.0, "hot": 18.0, "psoc": 48.0}[condition]
    hours_since_full = rng.exponential(tfull_mean_h, n_cycles)
    ln_tfull = np.log1p(hours_since_full / 24.0)

    ocv_err = rng.normal(0, 0.01 + 0.02 * s, n_cycles)

    # --- statics: lifetime integrals, monotone-ish running quantities ---
    af = {"nominal": 1.0, "hot": 2.6, "psoc": 1.15}[condition]  # Arrhenius factor proxy
    days_per_cycle = {"nominal": 1.0, "hot": 0.9, "psoc": 1.3}[condition]
    age_days = (k + 1) * days_per_cycle
    st_total_per_day = np.full(n_cycles, af) + rng.normal(0, 0.05, n_cycles)
    st_float = st_total_per_day * rng.uniform(0.3, 0.5)
    dod50_cum = np.cumsum(np.where(dod_k > 0.5, dod_k, 0.0))
    f_dod50 = dod50_cum / np.maximum(efc, 1e-6)
    lowsoc_frac_base = {"nominal": 0.15, "hot": 0.15, "psoc": 0.35}[condition]
    f_lowsoc = _clip01(lowsoc_frac_base + rng.normal(0, 0.03, n_cycles))
    age_years = age_days / 365.0

    df = pd.DataFrame({
        "r_ratio": r_ratio, "sag_ratio": sag_ratio, "q_dis_norm": q_dis_norm, "dod": dod,
        "eta_c": eta_c, "eta_stale": eta_stale, "ca_ratio": ca_ratio, "cv_frac": cv_frac,
        "ic_peak_h": ic_peak_h, "ic_peak_v": ic_peak_v, "ica_stale": ica_stale,
        "t_mean": t_mean, "ln_tfull": ln_tfull, "ocv_err": ocv_err,
        "efc": efc, "st_total_per_day": st_total_per_day, "st_float": st_float,
        "f_dod50": f_dod50, "f_lowsoc": f_lowsoc, "age_years": age_years,
        "soh_true": soh_true, "rul_efc_true": rul_efc_true,
        "battery_id": battery_id, "cycle_idx": k,
        "condition": condition,
    })
    assert list(df.columns[:14]) == DYNAMIC_COLUMNS
    return df


def generate(n_batteries=24, cycles_mean=200, cycles_sd=15, seed=0):
    rng = np.random.default_rng(seed)
    frames = []
    for b in range(n_batteries):
        n_cycles = int(np.clip(rng.normal(cycles_mean, cycles_sd), 120, 260))
        bid = "B%02d" % b
        frames.append(_simulate_battery(bid, rng, n_cycles))
    out = pd.concat(frames, ignore_index=True)
    ordered = DYNAMIC_COLUMNS + STATIC_COLUMNS + LABEL_COLUMNS + ID_COLUMNS + ["condition"]
    return out[ordered]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/features_sim_dummy.csv")
    ap.add_argument("--n-batteries", type=int, default=24)
    ap.add_argument("--cycles-mean", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    df = generate(n_batteries=args.n_batteries, cycles_mean=args.cycles_mean, seed=args.seed)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print("wrote %d rows, %d batteries -> %s" % (len(df), df["battery_id"].nunique(), out_path))
    print(df.groupby("battery_id")["soh_true"].agg(["first", "last", "count"]).describe())


if __name__ == "__main__":
    main()
