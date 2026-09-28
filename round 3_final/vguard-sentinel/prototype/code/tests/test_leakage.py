"""Guard against synthetic-only hidden variables leaking into model inputs."""
import numpy as np
import pandas as pd
from features.schema import DYNAMIC_FEATURES, STATIC_FEATURES, LABEL_COLUMNS
from model.windowing import build_windows

FORBIDDEN = {"soc_true", "soh_true", "rul_efc_true", "capacity_true", "aging_rate", "battery_id", "cycle_idx"}


def test_feature_names_contain_no_labels():
    assert not (set(DYNAMIC_FEATURES) | set(STATIC_FEATURES)) & FORBIDDEN
    assert "soh_true" in LABEL_COLUMNS and "rul_efc_true" in LABEL_COLUMNS


def test_windows_do_not_carry_label_values():
    rng = np.random.default_rng(0)
    n = 40
    df = pd.DataFrame({c: rng.normal(size=n) for c in DYNAMIC_FEATURES + STATIC_FEATURES})
    df["soh_true"] = np.linspace(100, 70, n)
    df["rul_efc_true"] = np.linspace(50, 0, n)
    df["battery_id"] = "b0"
    df["cycle_idx"] = np.arange(n)
    w = build_windows(df)
    # no column of X_dyn/X_stat should equal (or be a scaled copy of) the label sequence
    lab = w.soh_true
    for arr in (w.X_dyn[:, -1, :], w.X_stat):
        for j in range(arr.shape[1]):
            col = arr[:, j]
            if np.std(col) < 1e-9:
                continue
            r = abs(np.corrcoef(col, lab)[0, 1])
            assert r < 0.999, "feature column %d is a copy of the label" % j
