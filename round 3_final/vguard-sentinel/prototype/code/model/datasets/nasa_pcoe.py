"""model/datasets/nasa_pcoe.py -- NASA PCoE "Battery Data Set" loader
(B0005/B0006/B0007/B0018 and friends), design 02 SS4.2 (Stage A pre-training
source).

Source format: one .mat file per battery, scipy.io.loadmat with a top-level
struct (variable name == battery id, e.g. "B0005") whose `.cycle` field is a
1-D struct array. Each cycle struct has `type` in {'charge','discharge',
'impedance'}, `ambient_temperature`, `time` (a 6-element MATLAB datevec
[Y,M,D,h,m,s]), and a `data` struct. For type=='discharge', `data` carries
Voltage_measured, Current_measured, Temperature_measured, Time (seconds since
cycle start) and a scalar Capacity (measured discharge capacity, Ah). For
type=='charge', `data` carries the same voltage/current/temperature/time
series (no Capacity field). We only use `type in {'charge','discharge'}`;
'impedance' cycles carry EIS data this loader does not use.

Sign convention: NASA's Current_measured is positive during discharge and
negative during charge in the raw files (i.e. the OPPOSITE of
CONTRACTS.md SS1's "+charge, -discharge"). This loader flips the sign at
parse time so every downstream helper in model/datasets/_common.py sees the
CONTRACTS convention (I>0 charge, I<0 discharge) -- see `_load_mat_battery`.

What is genuinely derived vs. left NaN (never fabricated, CONTRACTS SS7):
  derived directly from Capacity / rated 2.0 Ah spec-sheet capacity:
      q_dis_norm, dod, soh_true, efc, f_dod50
  derived from the charge/discharge voltage-current step at cycle boundaries:
      r_ratio, sag_ratio (see docstring on `_resistance_step_features`)
  derived from the paired charge/discharge Ah integrals:
      eta_c, eta_stale
  derived from the CC->CV transition of each charge cycle:
      ca_ratio, cv_frac
  derived from the dQ/dV curve of the CC segment of each charge cycle:
      ic_peak_h, ic_peak_v, ica_stale
  derived from Temperature_measured / cycle `time` datevecs:
      t_mean, ln_tfull, st_total_per_day, age_years
  derived from an Ah-integrated within-cycle SoC estimate:
      f_lowsoc
  NaN, documented reason (model/datasets/_common.py's COMMON_NONDERIVABLE,
  plus one loader-specific channel):
      ocv_err, st_float  (see _common.py)
      rul_efc_true is filled (interpolated/extrapolated EFC-to-80%-SoH from
        the observed capacity fade -- a real derived label, not invented,
        following model/make_dummy_features.py's own interpolation
        convention so the number means the same thing across this repo)

CLI:
    python -m model.datasets.nasa_pcoe --raw-dir data/raw_nasa --out data/features_nasa.csv
    python -m model.datasets.nasa_pcoe --download --raw-dir data/raw_nasa --out data/features_nasa.csv
"""

from __future__ import annotations

import argparse
import datetime
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from features.schema import (  # noqa: E402
    DYNAMIC_FEATURES, STATIC_FEATURES, LABEL_COLUMNS, EOL_SOH_PCT,
)
from model.datasets._common import (  # noqa: E402
    COMMON_NONDERIVABLE, DownloadError, HTTPRangeFile, arrhenius_factor,
    carry_forward_with_staleness, cc_cv_transition, dqdv_curve, find_ica_peak,
    sha256_file, trapz_ah, write_manifest,
)

C_RATED_AH = 2.0  # NASA PCoE spec-sheet rated capacity for B0005/6/7/18/... (18650, 2 Ah nominal)
NASA_NONDERIVABLE = dict(COMMON_NONDERIVABLE)  # nothing NASA-specific beyond the shared set

# Outer archive: a zip of per-batch-group zips (design note in _common.py's
# HTTPRangeFile docstring). Batch 1 (FY08Q4) is where B0005/6/7/18 live.
NASA_OUTER_ZIP_URL = "https://phm-datasets.s3.amazonaws.com/NASA/5.+Battery+Data+Set.zip"
NASA_GROUP1_ENTRY = "5. Battery Data Set/1. BatteryAgingARC-FY08Q4.zip"
# Kaggle mirrors require an authenticated API call (kaggle.json credentials),
# which this loader does not assume are configured; listed for the manual
# fallback message only.
NASA_MANUAL_URLS = [
    NASA_OUTER_ZIP_URL,
    "https://www.kaggle.com/datasets/patrickfleith/nasa-battery-dataset",
    "https://data.nasa.gov/dataset/Li-ion-Battery-Aging-Datasets",
]

DEFAULT_BATTERIES = ["B0005", "B0006", "B0007", "B0018"]


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #

def download_group1(raw_dir, timeout=60, max_seconds=280):
    """Fetch ONLY the FY08Q4 nested archive (the group holding B0005/6/7/18)
    out of the ~210 MB outer NASA zip, via HTTP range requests through
    zipfile -- see model/datasets/_common.py's HTTPRangeFile. Streams the
    decompressed entry straight to disk; never buffers the outer 210 MB.
    Raises DownloadError (never fabricates a local file) on any failure."""
    import time
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / "BatteryAgingARC-FY08Q4.zip"
    t0 = time.time()
    try:
        outer_file = HTTPRangeFile(NASA_OUTER_ZIP_URL, timeout=timeout)
        outer_zf = zipfile.ZipFile(outer_file)
        with outer_zf.open(NASA_GROUP1_ENTRY) as src, open(dest, "wb") as dst:
            while True:
                if time.time() - t0 > max_seconds:
                    raise DownloadError(
                        "NASA group1 download exceeded max_seconds=%d (got %d bytes); "
                        "partial file left at %s -- network too slow here, fetch manually "
                        "from %s" % (max_seconds, dst.tell(), dest, NASA_OUTER_ZIP_URL))
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                dst.write(chunk)
    except (zipfile.BadZipFile, OSError, TimeoutError) as e:
        if dest.exists():
            dest.unlink()
        raise DownloadError("NASA group1 fetch failed: %s" % e) from e
    return dest


def download_battery_mats(raw_dir, batteries=DEFAULT_BATTERIES, timeout=60, max_seconds=280):
    """Download the FY08Q4 group archive (if not already present) and
    extract just the requested B####.mat files into raw_dir. Returns the
    list of extracted .mat paths. Raises DownloadError with the manual URL
    list if every attempt fails -- never fakes a .mat file."""
    raw_dir = Path(raw_dir)
    group_zip = raw_dir / "BatteryAgingARC-FY08Q4.zip"
    if not group_zip.exists():
        group_zip = download_group1(raw_dir, timeout=timeout, max_seconds=max_seconds)
    extracted = []
    try:
        with zipfile.ZipFile(group_zip) as zf:
            names = zf.namelist()
            for bid in batteries:
                match = [n for n in names if n.endswith(bid + ".mat")]
                if not match:
                    continue
                target = raw_dir / (bid + ".mat")
                with zf.open(match[0]) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                extracted.append(target)
    except zipfile.BadZipFile as e:
        raise DownloadError("downloaded group archive is not a valid zip: %s" % e) from e
    if not extracted:
        raise DownloadError(
            "group archive downloaded but none of %s were found inside it. "
            "Fetch manually from one of:\n  %s" % (batteries, "\n  ".join(NASA_MANUAL_URLS)))
    return extracted


# --------------------------------------------------------------------------- #
# .mat parsing
# --------------------------------------------------------------------------- #

def _matlab_datevec_to_datetime(dv):
    dv = np.asarray(dv).ravel()
    y, mo, d, h, mi = (int(dv[0]), int(dv[1]), int(dv[2]), int(dv[3]), int(dv[4]))
    s = float(dv[5])
    return datetime.datetime(y, mo, d, h, mi, int(s)) + datetime.timedelta(seconds=s - int(s))


def load_mat_battery(mat_path):
    """Returns (battery_id, list-of-cycle-dicts). Each cycle dict:
        type: 'charge' | 'discharge' | 'impedance'
        t: seconds-from-cycle-start array
        V, I, T: numpy arrays (I already flipped to CONTRACTS +charge/-discharge)
        timestamp: datetime (cycle start) or None
        capacity_ah: float or None (discharge cycles only, NASA's own measured value)
    """
    from scipy.io import loadmat
    mat = loadmat(mat_path, struct_as_record=False, squeeze_me=True)
    keys = [k for k in mat.keys() if not k.startswith("__")]
    if not keys:
        raise ValueError("%s: no top-level struct found" % mat_path)
    battery_id = keys[0]
    top = mat[battery_id]
    cycles_raw = np.atleast_1d(top.cycle)

    cycles = []
    for c in cycles_raw:
        ctype = str(c.type)
        if ctype not in ("charge", "discharge"):
            continue
        d = c.data
        V = np.atleast_1d(np.asarray(d.Voltage_measured, dtype=np.float64))
        I_raw = np.atleast_1d(np.asarray(d.Current_measured, dtype=np.float64))
        T = np.atleast_1d(np.asarray(d.Temperature_measured, dtype=np.float64))
        t = np.atleast_1d(np.asarray(d.Time, dtype=np.float64))
        # NASA convention: I>0 during discharge, I<0 during charge -- flip to
        # CONTRACTS.md SS1 (+charge, -discharge).
        I = -I_raw
        capacity_ah = None
        if ctype == "discharge" and hasattr(d, "Capacity"):
            cap = np.asarray(d.Capacity, dtype=np.float64).ravel()
            if cap.size:
                capacity_ah = float(cap[0])
        try:
            timestamp = _matlab_datevec_to_datetime(c.time)
        except Exception:
            timestamp = None
        cycles.append({"type": ctype, "t": t, "V": V, "I": I, "T": T,
                        "timestamp": timestamp, "capacity_ah": capacity_ah})
    return battery_id, cycles


# --------------------------------------------------------------------------- #
# Feature derivation
# --------------------------------------------------------------------------- #

def _resistance_step_features(discharge_cycles_ctx):
    """r_ratio: instantaneous ohmic step at the charge/rest->discharge
    boundary, R_step = -dV/dI using the single sample immediately before and
    immediately after the transition (design 02 SS1.1's dV/dI formula,
    applied at the cycle boundary since NASA logs per-cycle segments rather
    than one continuous stream).
    sag_ratio: the fuller voltage sag over the first few seconds of
    discharge (mean V over the first min(5, n) samples minus the
    pre-transition V), normalised by the same-window mean discharge current
    -- captures polarisation on top of the pure ohmic step, distinct from
    r_ratio, design 02 SS1.1 vs SS1.2's stated distinction between the
    "16-slot buffer median under load" (sag) and the EKF-instantaneous R_int.
    Both ratio to this battery's first valid value (baseline)."""
    r_steps, sag_steps = [], []
    for ctx in discharge_cycles_ctx:
        v_prev, i_prev = ctx["v_prev"], ctx["i_prev"]
        V, I = ctx["V"], ctx["I"]
        if v_prev is None or len(V) < 2:
            r_steps.append(np.nan)
            sag_steps.append(np.nan)
            continue
        d_i = I[0] - i_prev
        d_v = V[0] - v_prev
        r_step = -d_v / d_i if abs(d_i) > 1e-6 else np.nan
        r_steps.append(r_step)

        n_win = min(5, len(V))
        v_win_mean = float(np.mean(V[:n_win]))
        i_win_mean = float(np.mean(np.abs(I[:n_win])))
        sag = -(v_win_mean - v_prev) / i_win_mean if i_win_mean > 1e-6 else np.nan
        sag_steps.append(sag)

    r_steps = np.array(r_steps)
    sag_steps = np.array(sag_steps)
    r_base = next((v for v in r_steps if np.isfinite(v)), np.nan)
    sag_base = next((v for v in sag_steps if np.isfinite(v)), np.nan)
    r_ratio = r_steps / r_base if np.isfinite(r_base) and r_base != 0 else np.full_like(r_steps, np.nan)
    sag_ratio = sag_steps / sag_base if np.isfinite(sag_base) and sag_base != 0 else np.full_like(sag_steps, np.nan)
    return r_ratio, sag_ratio


def _charge_acceptance_and_cv_frac(charge_cycle):
    """CC->CV transition via cc_cv_transition (_common.py); CA_ref = current
    60 s after entering CV (design 02 SS1.8's CA_60, adapted from lead-acid's
    14.4 V boost to whatever CC/CV split this charger protocol used -- Li-ion
    CC-CV to a voltage cutoff is structurally the same two-phase charge).
    cv_frac = Q_CV/(Q_CC+Q_CV) by direct Ah integration of each segment."""
    t, V, I = charge_cycle["t"], charge_cycle["V"], charge_cycle["I"]
    I_chg = np.abs(I)  # charge current, magnitude
    idx = cc_cv_transition(I_chg)
    if idx >= len(t) - 1 or idx < 1:
        return np.nan, np.nan
    t_cv0 = t[idx]
    after = np.where(t >= t_cv0 + 60.0)[0]
    ca60 = float(I_chg[after[0]]) if len(after) else float(I_chg[-1])
    q_cc = trapz_ah(t[: idx + 1], I_chg[: idx + 1])
    q_cv = trapz_ah(t[idx:], I_chg[idx:])
    cv_frac = q_cv / (q_cc + q_cv) if (q_cc + q_cv) > 1e-9 else np.nan
    return ca60, cv_frac


def _ica_from_cc(charge_cycle, v_lo=3.0, v_hi=4.2):
    """dQ/dV over the CC segment of the charge cycle (design 02 SS1.7,
    generalised voltage window for Li-ion instead of lead-acid's 12.0-14.4 V --
    see dqdv_curve's docstring)."""
    t, V, I = charge_cycle["t"], charge_cycle["V"], charge_cycle["I"]
    I_chg = np.abs(I)
    idx = cc_cv_transition(I_chg)
    if idx < 3:
        return np.nan, np.nan
    t_cc, V_cc, I_cc = t[:idx], V[:idx], I_chg[:idx]
    q_cum = np.concatenate([[0.0], np.cumsum(
        np.abs(np.diff(t_cc)) * (I_cc[:-1] + I_cc[1:]) / 2.0 / 3600.0)])
    centers, qbin = dqdv_curve(V_cc, q_cum, v_lo, v_hi, n_bins=60)
    return find_ica_peak(centers, qbin)


def _within_cycle_low_soc_seconds(discharge_cycle, soc_start, c_rated_ah):
    """Ah-integrate the discharge current forward from soc_start; count
    seconds where the running SoC estimate < 0.5. Pure bookkeeping on
    measured current -- no EKF/OCV needed."""
    t, I = discharge_cycle["t"], discharge_cycle["I"]
    if len(t) < 2:
        return 0.0, 0.0
    dt = np.diff(t, prepend=t[0])
    dq_ah = np.abs(I) * np.clip(dt, 0, None) / 3600.0
    soc = soc_start - np.cumsum(dq_ah) / c_rated_ah
    low = np.sum(np.clip(dt, 0, None)[soc < 0.5])
    return float(low), float(np.sum(np.clip(dt, 0, None)))


def build_battery_dataframe(battery_id, cycles, c_rated_ah=C_RATED_AH):
    """cycles: chronological list from load_mat_battery (charge+discharge
    interleaved). Returns a DataFrame with exactly features/schema.py's
    columns (NaN where undecidable), one row per discharge cycle."""
    discharge_idxs = [i for i, c in enumerate(cycles) if c["type"] == "discharge"]
    if not discharge_idxs:
        return pd.DataFrame(columns=DYNAMIC_FEATURES + STATIC_FEATURES + LABEL_COLUMNS)

    # --- context for resistance-step features: sample just before each discharge onset
    r_ctx = []
    for di in discharge_idxs:
        prev = cycles[di - 1] if di > 0 else None
        v_prev = float(prev["V"][-1]) if prev is not None and len(prev["V"]) else None
        i_prev = float(prev["I"][-1]) if prev is not None and len(prev["I"]) else 0.0
        r_ctx.append({"V": cycles[di]["V"], "I": cycles[di]["I"], "v_prev": v_prev, "i_prev": i_prev})
    r_ratio, sag_ratio = _resistance_step_features(r_ctx)

    # --- pair each discharge with the preceding charge cycle for eta_c/ca/cv/ica
    n = len(discharge_idxs)
    q_dis_ah = np.full(n, np.nan)
    q_chg_ah = np.full(n, np.nan)
    ca_raw = np.full(n, np.nan)
    cv_frac = np.full(n, np.nan)
    ic_h_raw = np.full(n, np.nan)
    ic_v_raw = np.full(n, np.nan)
    t_mean = np.full(n, np.nan)
    timestamps = [None] * n
    hours_since_full = np.full(n, np.nan)
    dod = np.full(n, np.nan)
    low_soc_s = np.full(n, 0.0)
    cycle_s = np.full(n, 0.0)
    ambient_t = np.full(n, np.nan)

    last_full_charge_end = None
    for k, di in enumerate(discharge_idxs):
        dc = cycles[di]
        t_mean[k] = float(np.mean(dc["T"])) if len(dc["T"]) else np.nan
        timestamps[k] = dc["timestamp"]
        ambient_t[k] = t_mean[k]

        cap = dc["capacity_ah"]
        q_dis_ah[k] = cap if cap is not None else trapz_ah(dc["t"], dc["I"])
        dod[k] = min(1.0, q_dis_ah[k] / c_rated_ah) if c_rated_ah > 0 else np.nan

        low_s, tot_s = _within_cycle_low_soc_seconds(dc, soc_start=1.0, c_rated_ah=c_rated_ah)
        low_soc_s[k] = low_s
        cycle_s[k] = tot_s

        # nearest preceding charge cycle (search backward from di)
        cj = next((j for j in range(di - 1, -1, -1) if cycles[j]["type"] == "charge"), None)
        if cj is not None:
            ch = cycles[cj]
            q_chg_ah[k] = trapz_ah(ch["t"], ch["I"])
            ca_raw[k], cv_frac[k] = _charge_acceptance_and_cv_frac(ch)
            ic_h_raw[k], ic_v_raw[k] = _ica_from_cc(ch)
            if ch["timestamp"] is not None:
                last_full_charge_end = ch["timestamp"]
        if dc["timestamp"] is not None and last_full_charge_end is not None:
            hours_since_full[k] = (dc["timestamp"] - last_full_charge_end).total_seconds() / 3600.0
            hours_since_full[k] = max(hours_since_full[k], 0.0)

    eta_c_raw = q_dis_ah / q_chg_ah
    eta_c_raw = np.where(np.isfinite(eta_c_raw) & (q_dis_ah >= 0.1 * c_rated_ah), eta_c_raw, np.nan)
    eta_c, eta_stale = carry_forward_with_staleness(eta_c_raw, np.isfinite(eta_c_raw))

    ca_base = next((v for v in ca_raw if np.isfinite(v)), np.nan)
    ca_ratio_raw = ca_raw / ca_base if np.isfinite(ca_base) and ca_base != 0 else np.full(n, np.nan)
    ca_ratio, _ = carry_forward_with_staleness(ca_ratio_raw, np.isfinite(ca_ratio_raw))

    ic_h_base = next((v for v in ic_h_raw if np.isfinite(v)), np.nan)
    ic_h_ratio_raw = ic_h_raw / ic_h_base if np.isfinite(ic_h_base) and ic_h_base != 0 else np.full(n, np.nan)
    ic_v_base = next((v for v in ic_v_raw if np.isfinite(v)), np.nan)
    ic_v_shift_raw = ic_v_raw - ic_v_base if np.isfinite(ic_v_base) else np.full(n, np.nan)
    ica_valid = np.isfinite(ic_h_ratio_raw)
    ic_peak_h, ica_stale = carry_forward_with_staleness(ic_h_ratio_raw, ica_valid)
    ic_peak_v, _ = carry_forward_with_staleness(ic_v_shift_raw, ica_valid)

    q_dis_norm = q_dis_ah / c_rated_ah
    ln_tfull = np.log1p(np.nan_to_num(hours_since_full, nan=0.0) / 24.0)

    # --- age / EFC / statics from timestamps ---
    t0 = next((ts for ts in timestamps if ts is not None), None)
    age_years = np.array([
        (ts - t0).total_seconds() / (86400.0 * 365.0) if (ts is not None and t0 is not None) else np.nan
        for ts in timestamps
    ])
    efc = np.cumsum(np.nan_to_num(q_dis_ah, nan=0.0)) / c_rated_ah

    # Arrhenius thermal-stress integral over real elapsed time (design 02 SS1.5),
    # using each interval's mean ambient temperature and the wall-clock gap
    # between consecutive discharge timestamps.
    af = arrhenius_factor(np.nan_to_num(ambient_t, nan=25.0))
    st_total_cum = np.zeros(n)
    for k in range(n):
        if k == 0:
            dt_days = 0.0
        elif timestamps[k] is not None and timestamps[k - 1] is not None:
            dt_days = max((timestamps[k] - timestamps[k - 1]).total_seconds() / 86400.0, 0.0)
        else:
            dt_days = 1.0  # unknown gap: assume 1 cycle/day, documented fallback
        st_total_cum[k] = (st_total_cum[k - 1] if k > 0 else 0.0) + af[k] * dt_days
    age_days = np.where(np.isfinite(age_years), age_years * 365.0, np.arange(1, n + 1))
    st_total_per_day = st_total_cum / np.maximum(age_days, 1e-6)

    dod50_cum = np.cumsum(np.where(dod > 0.5, np.nan_to_num(q_dis_ah, nan=0.0), 0.0))
    f_dod50 = dod50_cum / np.maximum(np.cumsum(np.nan_to_num(q_dis_ah, nan=0.0)), 1e-9)
    f_lowsoc = np.where(cycle_s > 0, low_soc_s / np.maximum(cycle_s, 1e-9), np.nan)

    # --- labels ---
    capacity_first = q_dis_ah[0] if np.isfinite(q_dis_ah[0]) else np.nanmax(q_dis_ah)
    soh_true = 100.0 * q_dis_ah / capacity_first

    below = np.where(soh_true <= EOL_SOH_PCT)[0]
    if len(below):
        i1 = int(below[0])
        if i1 == 0:
            efc_eol = efc[0]
        else:
            i0 = i1 - 1
            s0, s1 = soh_true[i0], soh_true[i1]
            frac = (s0 - EOL_SOH_PCT) / max(s0 - s1, 1e-6)
            efc_eol = efc[i0] + frac * (efc[i1] - efc[i0])
    else:
        rate = (100.0 - soh_true[-1]) / max(efc[-1], 1e-6) if efc[-1] > 0 else 0.0
        rate = max(rate, 1e-4)
        efc_eol = efc[-1] + (soh_true[-1] - EOL_SOH_PCT) / rate
    rul_efc_true = np.clip(efc_eol - efc, 0.0, None)

    df = pd.DataFrame({
        "r_ratio": r_ratio, "sag_ratio": sag_ratio, "q_dis_norm": q_dis_norm, "dod": dod,
        "eta_c": eta_c, "eta_stale": eta_stale, "ca_ratio": ca_ratio, "cv_frac": cv_frac,
        "ic_peak_h": ic_peak_h, "ic_peak_v": ic_peak_v, "ica_stale": ica_stale,
        "t_mean": t_mean, "ln_tfull": ln_tfull,
        "ocv_err": np.full(n, np.nan),  # COMMON_NONDERIVABLE
        "efc": efc, "st_total_per_day": st_total_per_day,
        "st_float": np.full(n, np.nan),  # COMMON_NONDERIVABLE
        "f_dod50": f_dod50, "f_lowsoc": f_lowsoc, "age_years": age_years,
        "soh_true": soh_true, "rul_efc_true": rul_efc_true,
        "battery_id": battery_id, "cycle_idx": np.arange(n),
    })
    assert list(df.columns) == DYNAMIC_FEATURES + STATIC_FEATURES + LABEL_COLUMNS
    return df


def process_mat_file(mat_path, c_rated_ah=C_RATED_AH):
    battery_id, cycles = load_mat_battery(mat_path)
    df = build_battery_dataframe(battery_id, cycles, c_rated_ah=c_rated_ah)
    n_discharge = int((pd.Series([c["type"] for c in cycles]) == "discharge").sum())
    return battery_id, df, n_discharge


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", default="data/raw_nasa")
    ap.add_argument("--out", default="data/features_nasa.csv")
    ap.add_argument("--batteries", nargs="+", default=DEFAULT_BATTERIES)
    ap.add_argument("--c-rated-ah", type=float, default=C_RATED_AH)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--max-download-seconds", type=int, default=280)
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    if args.download:
        print("Downloading NASA PCoE battery group (B0005/6/7/18 live in the FY08Q4 group) ...")
        try:
            paths = download_battery_mats(raw_dir, batteries=args.batteries,
                                           max_seconds=args.max_download_seconds)
            print("Downloaded/extracted: %s" % [str(p) for p in paths])
        except DownloadError as e:
            print("Download FAILED (no data fabricated). %s" % e)
            print("Fetch manually from:\n  %s" % "\n  ".join(NASA_MANUAL_URLS))
            return

    mat_files = sorted(raw_dir.glob("*.mat")) if raw_dir.exists() else []
    mat_files = [p for p in mat_files if p.stem in args.batteries] or mat_files
    if not mat_files:
        print("No .mat files found in %s. Run with --download, or fetch manually from:\n  %s" %
              (raw_dir, "\n  ".join(NASA_MANUAL_URLS)))
        return

    frames, manifest_rows = [], []
    for p in mat_files:
        print("Parsing %s ..." % p)
        try:
            battery_id, df, n_discharge = process_mat_file(p, c_rated_ah=args.c_rated_ah)
        except Exception as e:
            print("  SKIPPED %s: %s" % (p, e))
            continue
        if df.empty:
            print("  SKIPPED %s: no discharge cycles parsed" % p)
            continue
        frames.append(df)
        manifest_rows.append({
            "battery_id": battery_id, "chemistry": "Li-ion 18650 (NASA PCoE, 2.0 Ah nominal)",
            "n_cycles": int(len(df)), "capacity_bol": float(df["soh_true"].iloc[0]),
            "capacity_eol": float(df["soh_true"].iloc[-1]),
            "source_file": str(p), "sha256": sha256_file(p),
        })
        print("  %s: %d discharge cycles, SoH %.1f%% -> %.1f%%" %
              (battery_id, len(df), df["soh_true"].iloc[0], df["soh_true"].iloc[-1]))

    if not frames:
        print("Nothing parsed -- no output written.")
        return

    out = pd.concat(frames, ignore_index=True)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    manifest_path = write_manifest(manifest_rows, Path("data/manifests") / "nasa_pcoe_manifest.csv")
    print("Wrote %d rows (%d batteries) -> %s" % (len(out), len(frames), out_path))
    print("Wrote manifest -> %s" % manifest_path)
    for ch, reason in NASA_NONDERIVABLE.items():
        print("NaN channel '%s': %s" % (ch, reason))


if __name__ == "__main__":
    main()
