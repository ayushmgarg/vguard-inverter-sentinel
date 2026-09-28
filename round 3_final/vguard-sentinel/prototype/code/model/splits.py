"""model/splits.py — shared battery-level split logic (train.py / evaluate.py).

Splitting must always be by battery_id, never within a cell (CONTRACTS /
design 02 §4.4: GroupKFold by battery ID -- autocorrelated cycles leak).
This module is the single place that decides which batteries are held out
for split-conformal calibration, so train.py (which must exclude them from
gradient training) and evaluate.py (which uses them for calibration/
coverage reporting) never disagree.
"""

from __future__ import annotations

import numpy as np
from sklearn.model_selection import GroupKFold


def split_calibration_batteries(battery_ids, n_calib=6, seed=0):
    """Deterministically split unique battery ids into (train_pool, calibration).

    `battery_ids` may be a Series/array with repeats (one row per cycle);
    only the unique set matters.
    """
    ids = np.array(sorted(set(battery_ids)))
    if n_calib >= len(ids):
        raise ValueError("n_calib=%d >= number of batteries=%d" % (n_calib, len(ids)))
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(ids))
    calib = sorted(ids[perm[:n_calib]].tolist())
    train_pool = sorted(ids[perm[n_calib:]].tolist())
    return train_pool, calib


def group_kfold_battery_splits(battery_ids_array, n_folds=6):
    """Yield (train_idx, val_idx) over row indices of `battery_ids_array`,
    grouped so a battery never appears in both train and val of a fold."""
    gkf = GroupKFold(n_splits=n_folds)
    X_dummy = np.zeros(len(battery_ids_array))
    for train_idx, val_idx in gkf.split(X_dummy, groups=battery_ids_array):
        yield train_idx, val_idx


def leave_one_condition_out_splits(battery_ids_array, condition_array):
    """Yield (train_idx, val_idx, held_out_condition) for each distinct
    condition value, val_idx = all rows whose condition == held-out value.
    Requires a `condition` column (features/schema.py OPTIONAL_COLUMNS)."""
    conditions = sorted(set(condition_array))
    idx = np.arange(len(condition_array))
    for cond in conditions:
        val_idx = idx[condition_array == cond]
        train_idx = idx[condition_array != cond]
        yield train_idx, val_idx, cond
