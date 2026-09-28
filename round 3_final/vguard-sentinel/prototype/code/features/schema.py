"""Single source of truth for the per-cycle feature schema (CONTRACTS.md SS2).

14 dynamic channels (float32) in exactly this order, design 02 SS1.10:
    1 R_ref ratio (SS1.2)                -> r_ratio
    2 sag_ref ratio (SS1.1)              -> sag_ratio
    3 Q_dis/C_rated (SS1.3)              -> q_dis_norm
    4 DoD_k (SS1.4)                      -> dod
    5 eta_c, last valid (SS1.6)          -> eta_c
    6 staleness(eta_c)/30 (SS1.6)        -> eta_stale
    7 CA_ref ratio (SS1.8)               -> ca_ratio
    8 cv_frac (SS1.8)                    -> cv_frac
    9 ic_peak_h ratio, last valid (SS1.7)-> ic_peak_h
   10 ic_peak_v shift, last valid (SS1.7)-> ic_peak_v
   11 staleness(ICA)/30 (SS1.7)          -> ica_stale
   12 mean T in cycle, raw               -> t_mean
   13 ln(1+t_full/24h) (SS1.3)           -> ln_tfull
   14 rest-OCV-implied SoC error (SS1.9) -> ocv_err

then 6 static channels (design 02 SS1.10): EFC, S_T,total/age, S_T,float, f_DoD50,
f_lowSoC, age_days/365, then labels.
"""

DYNAMIC_FEATURES = [
    "r_ratio",
    "sag_ratio",
    "q_dis_norm",
    "dod",
    "eta_c",
    "eta_stale",
    "ca_ratio",
    "cv_frac",
    "ic_peak_h",
    "ic_peak_v",
    "ica_stale",
    "t_mean",
    "ln_tfull",
    "ocv_err",
]

STATIC_FEATURES = [
    "efc",
    "st_total_per_day",
    "st_float",
    "f_dod50",
    "f_lowsoc",
    "age_years",
]

LABEL_COLUMNS = [
    "soh_true",
    "rul_efc_true",
    "battery_id",
    "cycle_idx",
]

ALL_COLUMNS = DYNAMIC_FEATURES + STATIC_FEATURES + LABEL_COLUMNS

assert len(DYNAMIC_FEATURES) == 14, "CONTRACTS.md SS2 requires exactly 14 dynamic channels"
assert len(STATIC_FEATURES) == 6, "CONTRACTS.md SS2 requires exactly 6 static channels"

# model window size, design 02 SS1.10 / SS2.1
WINDOW_CYCLES = 30

# --------------------------------------------------------------------------- #
# Additions below by model/ (TinyML SoH/RUL pipeline) -- pure additions on
# top of the column lists/order above, which are unchanged. Nothing above
# this line was touched; model/*.py import DYNAMIC_FEATURES/STATIC_FEATURES/
# WINDOW_CYCLES directly (aliased at the import site where convenient) and
# only relies on the extra constants/helpers added here.
# --------------------------------------------------------------------------- #

# Bump whenever a column is added/removed/reordered. Firmware refuses a
# model whose feature_schema_version != its own (design 02 SS5.4).
FEATURE_SCHEMA_VERSION = 1

N_DYNAMIC = len(DYNAMIC_FEATURES)  # 14
N_STATIC = len(STATIC_FEATURES)    # 6

# First inference requires >= this many real (unpadded) cycles; earlier
# windows are padded by repeating the oldest cycle (design 02 SS2.1).
MIN_REAL_CYCLES = 10

# SoH end-of-life definition (design 02 SS0).
EOL_SOH_PCT = 80.0

# Target scaling (design 02 SS5.1): SoH head trained on (SoH-60)/40,
# RUL head trained on ln(1+RUL_EFC)/8.
SOH_SCALE_OFFSET = 60.0
SOH_SCALE_DIV = 40.0
RUL_LN_DIV = 8.0


def scale_soh(soh_pct):
    return (soh_pct - SOH_SCALE_OFFSET) / SOH_SCALE_DIV


def unscale_soh(scaled):
    return scaled * SOH_SCALE_DIV + SOH_SCALE_OFFSET


def scale_rul(rul_efc):
    import numpy as np
    return np.log1p(rul_efc) / RUL_LN_DIV


def unscale_rul(scaled):
    import numpy as np
    return np.expm1(scaled * RUL_LN_DIV)


# Optional column: present only when the source generator tags an
# operating condition (e.g. "nominal"/"hot"/"psoc"); used for
# leave-one-condition-out CV in model/train.py when available.
OPTIONAL_COLUMNS = ["condition", "t_end_s"]  # t_end_s: end-of-cycle epoch seconds, carried through when present

REQUIRED_COLUMNS = ALL_COLUMNS


def validate_columns(columns):
    """Raise ValueError listing every missing required column, else return True."""
    have = set(columns)
    missing = [c for c in REQUIRED_COLUMNS if c not in have]
    if missing:
        raise ValueError(
            "features CSV is missing required columns per features/schema.py "
            "(FEATURE_SCHEMA_VERSION=%d): %s" % (FEATURE_SCHEMA_VERSION, missing)
        )
    return True


def has_condition(columns):
    return "condition" in set(columns)
