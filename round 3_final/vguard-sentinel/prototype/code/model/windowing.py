"""model/windowing.py — build (30 cycles x 14 dyn) + 6 static windows from a
features CSV, and the standardisation (mean/scale) that goes with them.

Design 02 §1.10/§2.1: window = last 30 cycles x 14 dynamic + 6 statics at the
most recent cycle. First inference requires >= 10 real cycles; earlier
positions are padded by repeating the oldest cycle (design 02 §2.1).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from features.schema import (
    DYNAMIC_FEATURES as DYNAMIC_COLUMNS, STATIC_FEATURES as STATIC_COLUMNS,
    WINDOW_CYCLES as WINDOW_LEN, MIN_REAL_CYCLES,
    validate_columns, has_condition,
)


def load_and_validate(path):
    df = pd.read_csv(path)
    validate_columns(df.columns)
    return df


class Windows:
    """Container for the built window arrays. Plain attributes, no behaviour,
    so downstream code (train/evaluate/quantize) can slice/index freely."""

    def __init__(self, X_dyn, X_stat, soh_true, rul_true, battery_id, cycle_idx,
                 efc, n_real_cycles, condition, adjacent_pairs, t_end_s=None):
        self.X_dyn = X_dyn                  # (N, 30, 14) float32, raw units
        self.X_stat = X_stat                # (N, 6) float32, raw units
        self.soh_true = soh_true            # (N,) percent
        self.rul_true = rul_true            # (N,) EFC
        self.battery_id = battery_id        # (N,) object/str
        self.cycle_idx = cycle_idx          # (N,) int
        self.efc = efc                      # (N,) float, EFC at this cycle
        self.n_real_cycles = n_real_cycles  # (N,) int, real (unpadded) cycles in window
        self.condition = condition          # (N,) object/str or None
        self.adjacent_pairs = adjacent_pairs  # list[(i, j)] same-battery consecutive windows
        self.t_end_s = t_end_s              # (N,) float epoch s or None (optional column)

    def __len__(self):
        return len(self.soh_true)

    def subset(self, idx):
        idx = np.asarray(idx)
        keep = set(idx.tolist())
        old_to_new = {old: new for new, old in enumerate(idx.tolist())}
        new_pairs = [(old_to_new[i], old_to_new[j]) for i, j in self.adjacent_pairs
                     if i in keep and j in keep]
        return Windows(
            self.X_dyn[idx], self.X_stat[idx], self.soh_true[idx], self.rul_true[idx],
            self.battery_id[idx], self.cycle_idx[idx], self.efc[idx],
            self.n_real_cycles[idx],
            None if self.condition is None else self.condition[idx],
            new_pairs,
            None if self.t_end_s is None else self.t_end_s[idx],
        )


def build_windows(df):
    """Build all valid windows (>= MIN_REAL_CYCLES real cycles) from a
    validated features DataFrame. One window per (battery, cycle) once that
    cycle is the MIN_REAL_CYCLES-th or later real cycle for its battery."""
    dyn_mat_cols = DYNAMIC_COLUMNS
    stat_mat_cols = STATIC_COLUMNS
    cond_present = has_condition(df.columns)

    X_dyn_list, X_stat_list = [], []
    soh_list, rul_list, bid_list, cyc_list, efc_list, nreal_list, cond_list = ([] for _ in range(7))
    tend_list = []
    tend_present = "t_end_s" in df.columns
    adjacent_pairs = []

    for bid, g in df.groupby("battery_id", sort=False):
        g = g.sort_values("cycle_idx").reset_index(drop=True)
        # Missing-value policy (design 02 §1.6–1.7): carry the last valid
        # value forward within the battery (the staleness channels tell the
        # model how old it is); anything still missing (never observed yet)
        # falls back to the column median of the whole file, then 0.
        dyn_df = g[dyn_mat_cols].ffill().fillna(df[dyn_mat_cols].median()).fillna(0.0)
        stat_df = g[stat_mat_cols].ffill().fillna(df[stat_mat_cols].median()).fillna(0.0)
        dyn_vals = dyn_df.to_numpy(dtype=np.float32)               # (n_cycles, 14)
        stat_vals = stat_df.to_numpy(dtype=np.float32)             # (n_cycles, 6)
        soh_vals = g["soh_true"].to_numpy(dtype=np.float32)
        rul_vals = g["rul_efc_true"].to_numpy(dtype=np.float32)
        efc_vals = g["efc"].to_numpy(dtype=np.float32)
        cyc_vals = g["cycle_idx"].to_numpy()
        cond_vals = g["condition"].to_numpy() if cond_present else None
        tend_vals = g["t_end_s"].to_numpy(dtype=np.float64) if tend_present else None

        n_cycles = len(g)
        first_window_idx_for_battery = None
        for p in range(n_cycles):
            n_real = min(p + 1, WINDOW_LEN)
            if n_real < MIN_REAL_CYCLES:
                continue
            if p + 1 >= WINDOW_LEN:
                window = dyn_vals[p - WINDOW_LEN + 1: p + 1]
            else:
                pad_n = WINDOW_LEN - (p + 1)
                pad = np.repeat(dyn_vals[0:1], pad_n, axis=0)
                window = np.concatenate([pad, dyn_vals[0:p + 1]], axis=0)
            assert window.shape == (WINDOW_LEN, len(dyn_mat_cols))

            cur_global_idx = len(soh_list)
            if first_window_idx_for_battery is not None:
                adjacent_pairs.append((first_window_idx_for_battery, cur_global_idx))
            first_window_idx_for_battery = cur_global_idx

            X_dyn_list.append(window)
            X_stat_list.append(stat_vals[p])
            soh_list.append(soh_vals[p])
            rul_list.append(rul_vals[p])
            bid_list.append(bid)
            cyc_list.append(cyc_vals[p])
            efc_list.append(efc_vals[p])
            nreal_list.append(n_real)
            cond_list.append(cond_vals[p] if cond_present else None)
            tend_list.append(tend_vals[p] if tend_present else np.nan)

    return Windows(
        X_dyn=np.stack(X_dyn_list).astype(np.float32),
        X_stat=np.stack(X_stat_list).astype(np.float32),
        soh_true=np.array(soh_list, dtype=np.float32),
        rul_true=np.array(rul_list, dtype=np.float32),
        battery_id=np.array(bid_list, dtype=object),
        cycle_idx=np.array(cyc_list),
        efc=np.array(efc_list, dtype=np.float32),
        n_real_cycles=np.array(nreal_list, dtype=np.int32),
        condition=np.array(cond_list, dtype=object) if cond_present else None,
        adjacent_pairs=adjacent_pairs,
        t_end_s=np.array(tend_list, dtype=np.float64) if tend_present else None,
    )


# --------------------------------------------------------------------------- #
# Standardisation: zero-mean/unit-variance then clip +/-3 sigma and divide by
# 3 -> inputs in [-1, 1] (design 02 §5.1).
# --------------------------------------------------------------------------- #

def fit_standardizer(X_dyn, X_stat):
    dyn_flat = X_dyn.reshape(-1, X_dyn.shape[-1])
    mean_dyn = dyn_flat.mean(axis=0)
    scale_dyn = dyn_flat.std(axis=0)
    scale_dyn = np.where(scale_dyn < 1e-6, 1.0, scale_dyn)
    mean_stat = X_stat.mean(axis=0)
    scale_stat = X_stat.std(axis=0)
    scale_stat = np.where(scale_stat < 1e-6, 1.0, scale_stat)
    return {
        "mean_dyn": mean_dyn.astype(np.float64).tolist(),
        "scale_dyn": scale_dyn.astype(np.float64).tolist(),
        "mean_stat": mean_stat.astype(np.float64).tolist(),
        "scale_stat": scale_stat.astype(np.float64).tolist(),
    }


def apply_standardizer(X_dyn, X_stat, stats):
    mean_dyn = np.asarray(stats["mean_dyn"], dtype=np.float32)
    scale_dyn = np.asarray(stats["scale_dyn"], dtype=np.float32)
    mean_stat = np.asarray(stats["mean_stat"], dtype=np.float32)
    scale_stat = np.asarray(stats["scale_stat"], dtype=np.float32)

    z_dyn = (X_dyn - mean_dyn) / scale_dyn
    z_dyn = np.clip(z_dyn, -3.0, 3.0) / 3.0
    z_stat = (X_stat - mean_stat) / scale_stat
    z_stat = np.clip(z_stat, -3.0, 3.0) / 3.0
    return z_dyn.astype(np.float32), z_stat.astype(np.float32)


def compute_sample_weights(rul_true):
    """w = 1 + 3*exp(-RUL_EFC/100), design 02 §4.1 (near-EoL windows matter most)."""
    rul = np.nan_to_num(np.asarray(rul_true, dtype=np.float64), nan=1e6)  # unknown EoL -> treat as far away
    return (1.0 + 3.0 * np.exp(-rul / 100.0)).astype(np.float32)
