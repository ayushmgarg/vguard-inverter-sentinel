"""model/datasets/calce.py -- CALCE CS2/CX2 (Li-ion pouch cell) loader,
design 02 SS4.2 (Stage A pre-training source).

Source format: one .xlsx (older files: .csv) per test date, columns (names
vary slightly by export but always contain these substrings, matched
case-insensitively so small header variations don't break parsing):
    Date_Time, Test_Time(s), Step_Time(s), Step_Index, Cycle_Index,
    Current(A), Voltage(V), Charge_Capacity(Ah), Discharge_Capacity(Ah)
and, when present, a Temperature column (CALCE sometimes omits it -- treated
as not-derivable when absent, not invented). Sign convention assumed (Arbin
cycler, CALCE's standard rig): Current(A) > 0 charge, < 0 discharge --
already CONTRACTS.md SS1's convention, so unlike nasa_pcoe.py no sign flip is
needed here; documented explicitly since it is an assumption about a cycler
convention, not something the file header states.

A battery's raw data is however many dated files exist for it; this loader
concatenates them in filename order (CALCE's own naming embeds the test
date) using Date_Time to build one real elapsed-time axis, offsets
Cycle_Index across files so cycle numbers stay monotonic, then groups by
(global) Cycle_Index and splits each cycle into its charge segment (I>0) and
discharge segment (I<0) to compute the same physics features as
nasa_pcoe.py, via the same shared primitives in model/datasets/_common.py.

What is genuinely derived vs. left NaN -- same list and same reasoning as
nasa_pcoe.py's module docstring, substituting "Charge_Capacity(Ah)/
Discharge_Capacity(Ah) columns" for "the Capacity struct field", except:
    t_mean is NaN, reason: "no Temperature column in this file" whenever a
    given battery's files don't carry one (common for CALCE; documented
    per-battery in the printed run log, not silently dropped).

CLI:
    python -m model.datasets.calce --raw-dir data/raw_calce/CS2_35 --battery-id CS2_35 --out data/features_calce.csv
    python -m model.datasets.calce --download CS2_35 --raw-dir data/raw_calce --out data/features_calce.csv
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from features.schema import DYNAMIC_FEATURES, STATIC_FEATURES, LABEL_COLUMNS, EOL_SOH_PCT  # noqa: E402
from model.datasets._common import (  # noqa: E402
    COMMON_NONDERIVABLE, DownloadError, arrhenius_factor, carry_forward_with_staleness,
    cc_cv_transition, dqdv_curve, download_file, find_ica_peak, sha256_file, trapz_ah,
    write_manifest,
)

CALCE_BASE_URL = "https://web.calce.umd.edu/batteries/data/%s.zip"
CALCE_MANUAL_URL_TEMPLATE = "https://web.calce.umd.edu/batteries/data/%s.zip"
CALCE_DATA_PAGE = "https://calce.umd.edu/battery-data"

# CALCE-published nominal rated capacities (Ah), by cell family prefix.
C_RATED_BY_PREFIX = {"CS2": 1.10, "CX2": 1.35}
DEFAULT_C_RATED_AH = 1.10

CALCE_NONDERIVABLE = dict(COMMON_NONDERIVABLE)


def rated_capacity_for(battery_id):
    for prefix, cap in C_RATED_BY_PREFIX.items():
        if battery_id.upper().startswith(prefix):
            return cap
    return DEFAULT_C_RATED_AH


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #

def download_battery_zip(battery_id, raw_dir, timeout=60, max_bytes=200 << 20):
    """CALCE hosts one zip per battery id directly (no nested-archive trick
    needed -- these are already small, e.g. CS2_35.zip ~= 37 MB). Extracts
    into raw_dir/<battery_id>/. Raises DownloadError (never fabricates data)
    on any failure."""
    raw_dir = Path(raw_dir)
    battery_dir = raw_dir / battery_id
    zip_path = raw_dir / (battery_id + ".zip")
    url = CALCE_BASE_URL % battery_id
    download_file(url, zip_path, timeout=timeout, max_bytes=max_bytes)
    try:
        battery_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(battery_dir)
    except zipfile.BadZipFile as e:
        raise DownloadError("%s did not unzip cleanly: %s" % (zip_path, e)) from e
    return battery_dir


# --------------------------------------------------------------------------- #
# Raw file parsing
# --------------------------------------------------------------------------- #

def _find_col(columns, *substrings):
    """First column whose lowercased name contains ALL of `substrings`."""
    for c in columns:
        lc = str(c).lower()
        if all(s in lc for s in substrings):
            return c
    return None


def _read_data_sheet(path):
    """Return the sheet/file's raw DataFrame with columns renamed to the
    canonical set this loader uses. Picks, among an .xlsx's sheets, the one
    containing both a Cycle_Index-like and a Current-like column (skips
    'Statistics_*' summary sheets, which lack per-sample current/voltage)."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        candidates = {"csv": pd.read_csv(path)}
    else:
        sheets = pd.read_excel(path, sheet_name=None)
        candidates = sheets
    best = None
    for name, df in candidates.items():
        if _find_col(df.columns, "cycle", "index") and _find_col(df.columns, "current"):
            if best is None or len(df) > len(best):
                best = df
    if best is None:
        return None
    df = best
    colmap = {
        _find_col(df.columns, "cycle", "index"): "cycle_index",
        _find_col(df.columns, "current"): "current",
        _find_col(df.columns, "voltage"): "voltage",
        _find_col(df.columns, "charge_capacity") or _find_col(df.columns, "charge", "cap"): "charge_capacity",
        _find_col(df.columns, "discharge_capacity") or _find_col(df.columns, "discharge", "cap"): "discharge_capacity",
        _find_col(df.columns, "test_time"): "test_time_s",
        _find_col(df.columns, "date_time"): "date_time",
        _find_col(df.columns, "temp"): "temperature",
    }
    colmap = {k: v for k, v in colmap.items() if k is not None}
    df = df.rename(columns=colmap)
    keep = [c for c in ["cycle_index", "current", "voltage", "charge_capacity",
                         "discharge_capacity", "test_time_s", "date_time", "temperature"]
            if c in df.columns]
    df = df[keep].copy()
    if "cycle_index" not in df.columns or "current" not in df.columns or "voltage" not in df.columns:
        return None
    return df


def load_battery_files(raw_dir, battery_id):
    """Glob raw_dir for every .xlsx/.csv belonging to `battery_id` (filename
    contains the id), sorted by filename (CALCE embeds the test date in the
    filename so lexicographic order == chronological order for a given
    battery's own naming scheme), concatenated into one continuous frame
    with a monotonic elapsed-time axis and global cycle numbering."""
    raw_dir = Path(raw_dir)
    files = sorted(
        p for p in raw_dir.rglob("*")
        if p.suffix.lower() in (".xlsx", ".xls", ".csv") and battery_id in p.stem
    )
    frames = []
    t_offset = 0.0
    cyc_offset = 0
    for f in files:
        try:
            df = _read_data_sheet(f)
        except Exception:
            df = None
        if df is None or df.empty:
            continue
        if "test_time_s" in df.columns:
            t = pd.to_numeric(df["test_time_s"], errors="coerce").to_numpy(dtype=np.float64)
        else:
            t = np.arange(len(df), dtype=np.float64)
        df = df.copy()
        df["t_s"] = t + t_offset
        df["cycle_index"] = pd.to_numeric(df["cycle_index"], errors="coerce").ffill().astype(int) + cyc_offset
        if "date_time" in df.columns:
            df["date_time"] = pd.to_datetime(df["date_time"], errors="coerce")
        frames.append(df)
        t_offset = float(df["t_s"].max()) + 1.0
        cyc_offset = int(df["cycle_index"].max())
    if not frames:
        return None
    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["cycle_index", "t_s"]).reset_index(drop=True)
    return out


# --------------------------------------------------------------------------- #
# Feature derivation (mirrors nasa_pcoe.py's per-segment helpers, operating
# on a continuous-time DataFrame grouped by cycle_index instead of separate
# .mat cycle structs)
# --------------------------------------------------------------------------- #

def _segment(cycle_df, sign):
    """Rows of one polarity (charge: current>0, discharge: current<0),
    contiguous run only (first such run in the cycle -- CALCE cycles are a
    single CC/CV charge then a single discharge, occasional rest samples at
    ~0 A are excluded by the sign threshold)."""
    cur = cycle_df["current"].to_numpy(dtype=np.float64)
    mask = cur > 0.02 if sign > 0 else cur < -0.02
    if not mask.any():
        return None
    idx = np.where(mask)[0]
    # contiguous block starting at the first True
    start = idx[0]
    end = start
    for i in idx:
        if i == end or i == end + 1:
            end = i
        else:
            break
    seg = cycle_df.iloc[start:end + 1]
    return seg


def build_battery_dataframe(battery_id, raw, c_rated_ah):
    """raw: output of load_battery_files. One row per discharge cycle."""
    has_temp = "temperature" in raw.columns and raw["temperature"].notna().any()
    has_date = "date_time" in raw.columns and raw["date_time"].notna().any()

    cycle_ids = sorted(raw["cycle_index"].unique())
    records = []
    prev_v_end, prev_i_end = None, 0.0
    last_full_charge_end = None

    for cyc in cycle_ids:
        g = raw[raw["cycle_index"] == cyc].sort_values("t_s")
        dis = _segment(g, sign=-1)
        chg = _segment(g, sign=+1)
        if dis is None or len(dis) < 2:
            # nothing to discharge-label this cycle with; still track the
            # last raw sample for the next cycle's step feature
            if len(g):
                prev_v_end = float(g["voltage"].iloc[-1])
                prev_i_end = float(g["current"].iloc[-1])
            continue

        t_d = dis["t_s"].to_numpy(dtype=np.float64)
        V_d = dis["voltage"].to_numpy(dtype=np.float64)
        I_d = dis["current"].to_numpy(dtype=np.float64)

        if "discharge_capacity" in dis.columns and dis["discharge_capacity"].notna().any():
            q_dis_ah = float(pd.to_numeric(dis["discharge_capacity"], errors="coerce").max())
        else:
            q_dis_ah = trapz_ah(t_d, I_d)

        # --- r_ratio / sag_ratio from the step into this discharge segment ---
        if prev_v_end is not None:
            d_i = I_d[0] - prev_i_end
            d_v = V_d[0] - prev_v_end
            r_step = -d_v / d_i if abs(d_i) > 1e-6 else np.nan
            n_win = min(5, len(V_d))
            v_win_mean = float(np.mean(V_d[:n_win]))
            i_win_mean = float(np.mean(np.abs(I_d[:n_win])))
            sag = -(v_win_mean - prev_v_end) / i_win_mean if i_win_mean > 1e-6 else np.nan
        else:
            r_step, sag = np.nan, np.nan

        t_mean = float(np.mean(pd.to_numeric(dis["temperature"], errors="coerce"))) if has_temp else np.nan
        ts_end = dis["date_time"].iloc[-1] if has_date else None

        q_chg_ah, ca_raw, cv_frac, ic_h_raw, ic_v_raw = (np.nan,) * 5
        if chg is not None and len(chg) >= 3:
            t_c = chg["t_s"].to_numpy(dtype=np.float64)
            V_c = chg["voltage"].to_numpy(dtype=np.float64)
            I_c = np.abs(chg["current"].to_numpy(dtype=np.float64))
            if "charge_capacity" in chg.columns and chg["charge_capacity"].notna().any():
                q_chg_ah = float(pd.to_numeric(chg["charge_capacity"], errors="coerce").max())
            else:
                q_chg_ah = trapz_ah(t_c, I_c)

            idx_t = cc_cv_transition(I_c)
            if 1 <= idx_t < len(t_c) - 1:
                t_cv0 = t_c[idx_t]
                after = np.where(t_c >= t_cv0 + 60.0)[0]
                ca_raw = float(I_c[after[0]]) if len(after) else float(I_c[-1])
                q_cc = trapz_ah(t_c[: idx_t + 1], I_c[: idx_t + 1])
                q_cv = trapz_ah(t_c[idx_t:], I_c[idx_t:])
                cv_frac = q_cv / (q_cc + q_cv) if (q_cc + q_cv) > 1e-9 else np.nan

                q_cum = np.concatenate([[0.0], np.cumsum(
                    np.abs(np.diff(t_c[:idx_t])) *
                    (I_c[:idx_t][:-1] + I_c[:idx_t][1:]) / 2.0 / 3600.0)]) if idx_t >= 3 else np.array([])
                if len(q_cum):
                    centers, qbin = dqdv_curve(V_c[:idx_t], q_cum, float(np.min(V_c[:idx_t])),
                                                float(np.max(V_c[:idx_t])), n_bins=60)
                    ic_h_raw, ic_v_raw = find_ica_peak(centers, qbin)
            if has_date and chg["date_time"].notna().any():
                last_full_charge_end = chg["date_time"].iloc[-1]

        hours_since_full = np.nan
        if has_date and ts_end is not None and last_full_charge_end is not None and pd.notna(ts_end):
            hours_since_full = max((ts_end - last_full_charge_end).total_seconds() / 3600.0, 0.0)

        dod = min(1.0, q_dis_ah / c_rated_ah) if c_rated_ah > 0 else np.nan

        # low-SoC time within this discharge segment, Ah-integrated from 100%
        dt = np.diff(t_d, prepend=t_d[0])
        dq_ah = np.abs(I_d) * np.clip(dt, 0, None) / 3600.0
        soc = 1.0 - np.cumsum(dq_ah) / c_rated_ah
        low_s = float(np.sum(np.clip(dt, 0, None)[soc < 0.5]))
        tot_s = float(np.sum(np.clip(dt, 0, None)))

        records.append(dict(
            r_step=r_step, sag=sag, q_dis_ah=q_dis_ah, q_chg_ah=q_chg_ah, dod=dod,
            ca_raw=ca_raw, cv_frac=cv_frac, ic_h_raw=ic_h_raw, ic_v_raw=ic_v_raw,
            t_mean=t_mean, hours_since_full=hours_since_full, timestamp=ts_end,
            low_s=low_s, tot_s=tot_s,
        ))
        prev_v_end = float(g["voltage"].iloc[-1])
        prev_i_end = float(g["current"].iloc[-1])

    if not records:
        return pd.DataFrame(columns=DYNAMIC_FEATURES + STATIC_FEATURES + LABEL_COLUMNS)

    n = len(records)
    r_steps = np.array([r["r_step"] for r in records])
    sags = np.array([r["sag"] for r in records])
    r_base = next((v for v in r_steps if np.isfinite(v)), np.nan)
    sag_base = next((v for v in sags if np.isfinite(v)), np.nan)
    r_ratio = r_steps / r_base if np.isfinite(r_base) and r_base != 0 else np.full(n, np.nan)
    sag_ratio = sags / sag_base if np.isfinite(sag_base) and sag_base != 0 else np.full(n, np.nan)

    q_dis_ah = np.array([r["q_dis_ah"] for r in records])
    q_chg_ah = np.array([r["q_chg_ah"] for r in records])
    dod = np.array([r["dod"] for r in records])
    t_mean = np.array([r["t_mean"] for r in records])
    hours_since_full = np.array([r["hours_since_full"] for r in records])
    timestamps = [r["timestamp"] for r in records]
    low_s = np.array([r["low_s"] for r in records])
    tot_s = np.array([r["tot_s"] for r in records])

    eta_c_raw = q_dis_ah / q_chg_ah
    eta_c_raw = np.where(np.isfinite(eta_c_raw) & (q_dis_ah >= 0.1 * c_rated_ah), eta_c_raw, np.nan)
    eta_c, eta_stale = carry_forward_with_staleness(eta_c_raw, np.isfinite(eta_c_raw))

    ca_raw = np.array([r["ca_raw"] for r in records])
    ca_base = next((v for v in ca_raw if np.isfinite(v)), np.nan)
    ca_ratio_raw = ca_raw / ca_base if np.isfinite(ca_base) and ca_base != 0 else np.full(n, np.nan)
    ca_ratio, _ = carry_forward_with_staleness(ca_ratio_raw, np.isfinite(ca_ratio_raw))
    cv_frac = np.array([r["cv_frac"] for r in records])

    ic_h_raw = np.array([r["ic_h_raw"] for r in records])
    ic_v_raw = np.array([r["ic_v_raw"] for r in records])
    ic_h_base = next((v for v in ic_h_raw if np.isfinite(v)), np.nan)
    ic_h_ratio_raw = ic_h_raw / ic_h_base if np.isfinite(ic_h_base) and ic_h_base != 0 else np.full(n, np.nan)
    ic_v_base = next((v for v in ic_v_raw if np.isfinite(v)), np.nan)
    ic_v_shift_raw = ic_v_raw - ic_v_base if np.isfinite(ic_v_base) else np.full(n, np.nan)
    ica_valid = np.isfinite(ic_h_ratio_raw)
    ic_peak_h, ica_stale = carry_forward_with_staleness(ic_h_ratio_raw, ica_valid)
    ic_peak_v, _ = carry_forward_with_staleness(ic_v_shift_raw, ica_valid)

    q_dis_norm = q_dis_ah / c_rated_ah
    ln_tfull = np.log1p(np.nan_to_num(hours_since_full, nan=0.0) / 24.0)

    t0 = next((ts for ts in timestamps if ts is not None and pd.notna(ts)), None)
    age_years = np.array([
        (ts - t0).total_seconds() / (86400.0 * 365.0)
        if (ts is not None and t0 is not None and pd.notna(ts)) else np.nan
        for ts in timestamps
    ])
    efc = np.cumsum(np.nan_to_num(q_dis_ah, nan=0.0)) / c_rated_ah

    ambient_for_af = np.nan_to_num(t_mean, nan=25.0)
    af = arrhenius_factor(ambient_for_af)
    st_total_cum = np.zeros(n)
    for k in range(n):
        if k == 0:
            dt_days = 0.0
        elif timestamps[k] is not None and timestamps[k - 1] is not None and pd.notna(timestamps[k]) and pd.notna(timestamps[k - 1]):
            dt_days = max((timestamps[k] - timestamps[k - 1]).total_seconds() / 86400.0, 0.0)
        else:
            dt_days = 1.0
        st_total_cum[k] = (st_total_cum[k - 1] if k > 0 else 0.0) + af[k] * dt_days
    age_days = np.where(np.isfinite(age_years), age_years * 365.0, np.arange(1, n + 1))
    st_total_per_day = st_total_cum / np.maximum(age_days, 1e-6)

    dod50_cum = np.cumsum(np.where(dod > 0.5, np.nan_to_num(q_dis_ah, nan=0.0), 0.0))
    f_dod50 = dod50_cum / np.maximum(np.cumsum(np.nan_to_num(q_dis_ah, nan=0.0)), 1e-9)
    f_lowsoc = np.where(tot_s > 0, low_s / np.maximum(tot_s, 1e-9), np.nan)

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
        "ocv_err": np.full(n, np.nan),
        "efc": efc, "st_total_per_day": st_total_per_day,
        "st_float": np.full(n, np.nan),
        "f_dod50": f_dod50, "f_lowsoc": f_lowsoc, "age_years": age_years,
        "soh_true": soh_true, "rul_efc_true": rul_efc_true,
        "battery_id": battery_id, "cycle_idx": np.arange(n),
    })
    assert list(df.columns) == DYNAMIC_FEATURES + STATIC_FEATURES + LABEL_COLUMNS
    return df, has_temp


def process_battery(raw_dir, battery_id, c_rated_ah=None):
    c_rated_ah = c_rated_ah if c_rated_ah is not None else rated_capacity_for(battery_id)
    raw = load_battery_files(raw_dir, battery_id)
    if raw is None:
        raise ValueError("no CALCE data files found for %s under %s" % (battery_id, raw_dir))
    df, has_temp = build_battery_dataframe(battery_id, raw, c_rated_ah)
    if not has_temp:
        print("  %s: no temperature column found in raw files -- t_mean is NaN "
          "(this battery's cycler log did not record it)" % battery_id)
    return df


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", default="data/raw_calce")
    ap.add_argument("--out", default="data/features_calce.csv")
    ap.add_argument("--battery-id", action="append", dest="battery_ids", default=None,
                     help="repeatable; battery id(s) to process (folder/filename must contain it)")
    ap.add_argument("--download", metavar="BATTERY_ID", default=None,
                     help="download+extract one CALCE battery zip (e.g. CS2_35) before processing")
    ap.add_argument("--max-download-seconds", type=int, default=280)
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    if args.download:
        print("Downloading CALCE %s ..." % args.download)
        try:
            battery_dir = download_battery_zip(args.download, raw_dir,
                                                timeout=args.max_download_seconds)
            print("Extracted -> %s" % battery_dir)
        except DownloadError as e:
            print("Download FAILED (no data fabricated). %s" % e)
            print("Fetch manually from:\n  %s" % (CALCE_MANUAL_URL_TEMPLATE % args.download))
            return

    battery_ids = args.battery_ids
    if not battery_ids:
        if args.download:
            battery_ids = [args.download]
        else:
            print("No --battery-id given and no --download requested; nothing to do.")
            return

    frames, manifest_rows = [], []
    for bid in battery_ids:
        print("Processing %s from %s ..." % (bid, raw_dir))
        try:
            df = process_battery(raw_dir, bid)
        except Exception as e:
            print("  SKIPPED %s: %s" % (bid, e))
            continue
        if df.empty:
            print("  SKIPPED %s: no discharge cycles parsed" % bid)
            continue
        frames.append(df)
        src_files = sorted(p for p in raw_dir.rglob("*") if p.suffix.lower() in (".xlsx", ".xls", ".csv") and bid in p.stem)
        sha = sha256_file(src_files[0]) if src_files else ""
        manifest_rows.append({
            "battery_id": bid,
            "chemistry": "Li-ion pouch (CALCE %s, %.2f Ah nominal)" % (bid.split("_")[0], rated_capacity_for(bid)),
            "n_cycles": int(len(df)), "capacity_bol": float(df["soh_true"].iloc[0]),
            "capacity_eol": float(df["soh_true"].iloc[-1]),
            "source_file": "; ".join(str(p) for p in src_files) or str(raw_dir),
            "sha256": sha,
        })
        print("  %s: %d discharge cycles, SoH %.1f%% -> %.1f%%" %
              (bid, len(df), df["soh_true"].iloc[0], df["soh_true"].iloc[-1]))

    if not frames:
        print("Nothing parsed -- no output written.")
        return

    out = pd.concat(frames, ignore_index=True)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    manifest_path = write_manifest(manifest_rows, Path("data/manifests") / "calce_manifest.csv")
    print("Wrote %d rows (%d batteries) -> %s" % (len(out), len(frames), out_path))
    print("Wrote manifest -> %s" % manifest_path)
    for ch, reason in CALCE_NONDERIVABLE.items():
        print("NaN channel '%s': %s" % (ch, reason))


if __name__ == "__main__":
    main()
