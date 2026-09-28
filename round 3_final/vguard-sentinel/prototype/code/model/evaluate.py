"""model/evaluate.py — ensemble inference, split-conformal calibration, and
the metric suite from design 02 §7 / 11 §1.2.

Honesty note (see model/README.md): with only 24 synthetic batteries, the
same 6 batteries held out by model/train.py for split-conformal calibration
are also used here to report point metrics (MAE, hit-rate, PICP...). That
demonstrates the calibration *mechanism* faithfully but is not an
independent generalisation test -- a real run (Stage C, design 02 §4.4)
would use more batteries and/or nested splits. Said plainly in the output
markdown, not hidden.

CLI:
    python -m model.evaluate --artifacts model/artifacts/ --data data/features_sim_dummy.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

torch.set_num_threads(min(4, max(1, torch.get_num_threads())))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.schema import unscale_soh, RUL_LN_DIV, EOL_SOH_PCT  # noqa: E402
from model.net import build_model  # noqa: E402
from model.windowing import load_and_validate, build_windows, apply_standardizer  # noqa: E402
from model.metrics import (  # noqa: E402
    mae_rmse, picp_pice_mpiw, normalized_mpiw, approx_50pct_interval,
    split_conformal_offset, relative_error, hit_rate,
)
from model.grade import UsageRateEWMA, GradeStateMachine, rul_efc_to_weeks  # noqa: E402

CHECKPOINTS = (95.0, 90.0, 85.0)


# --------------------------------------------------------------------------- #
# Ensemble inference
# --------------------------------------------------------------------------- #

def load_ensemble(artifacts_dir):
    artifacts_dir = Path(artifacts_dir)
    with open(artifacts_dir / "mean_scale.json") as f:
        stats = json.load(f)
    with open(artifacts_dir / "split_info.json") as f:
        split_info = json.load(f)
    models = []
    for p in sorted(artifacts_dir.glob("seed*.pt")):
        m = build_model()
        m.load_state_dict(torch.load(p, map_location="cpu", weights_only=True))
        m.train(False)
        models.append(m)
    if not models:
        raise FileNotFoundError("no seed*.pt files found in %s -- run model/train.py first" % artifacts_dir)
    return models, stats, split_info


def ensemble_forward(models, X_dyn_std, X_stat_std):
    """Mean across seeds of each head's (p10,q50,p90) in the model's raw
    (scaled) output space -- design 02 §7 pseudocode order-of-operations."""
    Xd = torch.tensor(X_dyn_std)
    Xs = torch.tensor(X_stat_std)
    collected = {"soh": defaultdict(list), "rul": defaultdict(list)}
    with torch.no_grad():
        for m in models:
            out = m(Xd, Xs)
            for head in ("soh", "rul"):
                for k in ("p10", "q50", "p90"):
                    collected[head][k].append(out[head][k].numpy())
    result = {}
    for head in ("soh", "rul"):
        for k in ("p10", "q50", "p90"):
            result["%s_%s_s" % (head, k)] = np.mean(collected[head][k], axis=0)
    # ensemble spread (design 02 §2.4 OOD flag): std-dev across seeds of
    # SoH q50, in real percentage points (affine unscale -> std scales by 40).
    result["soh_q50_spread_pt"] = np.std(collected["soh"]["q50"], axis=0) * 40.0
    return result


def raw_to_real(raw):
    return {
        "soh_p10": unscale_soh(raw["soh_p10_s"]), "soh_q50": unscale_soh(raw["soh_q50_s"]),
        "soh_p90": unscale_soh(raw["soh_p90_s"]),
        "rul_ln_p10": raw["rul_p10_s"] * RUL_LN_DIV, "rul_ln_q50": raw["rul_q50_s"] * RUL_LN_DIV,
        "rul_ln_p90": raw["rul_p90_s"] * RUL_LN_DIV,
    }


def fit_conformal(models, stats, calib_windows):
    Xd, Xs = apply_standardizer(calib_windows.X_dyn, calib_windows.X_stat, stats)
    raw = ensemble_forward(models, Xd, Xs)
    real = raw_to_real(raw)
    soh_true = calib_windows.soh_true
    rul_ln_true = np.log1p(calib_windows.rul_true)
    c_lo_soh, c_hi_soh = split_conformal_offset(real["soh_p10"], real["soh_p90"], soh_true)
    c_lo_rul, c_hi_rul = split_conformal_offset(real["rul_ln_p10"], real["rul_ln_p90"], rul_ln_true)
    offsets = {"c_lo_soh": c_lo_soh, "c_hi_soh": c_hi_soh, "c_lo_rul": c_lo_rul, "c_hi_rul": c_hi_rul}
    return offsets, raw, real


def apply_conformal(real, offsets):
    soh_p10 = real["soh_p10"] - offsets["c_lo_soh"]
    soh_p90 = real["soh_p90"] + offsets["c_hi_soh"]
    rul_ln_p10 = real["rul_ln_p10"] - offsets["c_lo_rul"]
    rul_ln_p90 = real["rul_ln_p90"] + offsets["c_hi_rul"]
    return {
        "soh_p10": soh_p10, "soh_q50": real["soh_q50"], "soh_p90": soh_p90,
        "rul_efc_p10": np.clip(np.expm1(rul_ln_p10), 0.0, None),
        "rul_efc_p50": np.clip(np.expm1(real["rul_ln_q50"]), 0.0, None),
        "rul_efc_p90": np.clip(np.expm1(rul_ln_p90), 0.0, None),
    }


def raw_no_conformal(real):
    return {
        "soh_p10": real["soh_p10"], "soh_q50": real["soh_q50"], "soh_p90": real["soh_p90"],
        "rul_efc_p10": np.clip(np.expm1(real["rul_ln_p10"]), 0.0, None),
        "rul_efc_p50": np.clip(np.expm1(real["rul_ln_q50"]), 0.0, None),
        "rul_efc_p90": np.clip(np.expm1(real["rul_ln_p90"]), 0.0, None),
    }


# --------------------------------------------------------------------------- #
# SoH-checkpoint metrics: RUL relative error, RUL-window hit-rate
# --------------------------------------------------------------------------- #

def find_checkpoints(windows, checkpoints=CHECKPOINTS):
    records = []
    for bid in sorted(set(windows.battery_id.tolist())):
        idxs = np.where(windows.battery_id == bid)[0]
        idxs = idxs[np.argsort(windows.cycle_idx[idxs])]
        soh_seq = windows.soh_true[idxs]
        for c in checkpoints:
            below = np.where(soh_seq <= c)[0]
            if len(below) == 0:
                continue
            records.append({"battery_id": bid, "checkpoint": c, "idx": int(idxs[below[0]])})
    return records


def checkpoint_metrics(records, windows, pred):
    rel_err_by_cp = defaultdict(list)
    hits = []
    for r in records:
        i = r["idx"]
        true = windows.rul_true[i]
        rel_err_by_cp[r["checkpoint"]].append(float(relative_error(pred["rul_efc_p50"][i], true)))
        hits.append(bool(true >= pred["rul_efc_p10"][i] and true <= pred["rul_efc_p90"][i]))
    summary = {
        str(cp): {"mean_rel_err": float(np.mean(v)), "median_rel_err": float(np.median(v)), "n": len(v)}
        for cp, v in rel_err_by_cp.items()
    }
    hit_rate_val = float(np.mean(hits)) if hits else float("nan")
    return summary, hit_rate_val, len(records)


# --------------------------------------------------------------------------- #
# Grade-sequence simulation: warning lead time, false-alarm / miss rates
# --------------------------------------------------------------------------- #

def simulate_grades(windows, pred, days_per_cycle=1.0):
    """1 cycle ~= 1 day is the dummy generator's convention (~1 outage/day,
    typical Indian household per design 02 §0); documented assumption."""
    results = {}
    for bid in sorted(set(windows.battery_id.tolist())):
        idxs = np.where(windows.battery_id == bid)[0]
        idxs = idxs[np.argsort(windows.cycle_idx[idxs])]
        ewma = UsageRateEWMA()
        gsm = GradeStateMachine()
        prev_efc, prev_day = None, None
        seq = []
        for i in idxs:
            if getattr(windows, "t_end_s", None) is not None and np.isfinite(windows.t_end_s[i]):
                day = float(windows.t_end_s[i]) / 86400.0   # real elapsed time from the data
            else:
                day = float(windows.cycle_idx[i]) * days_per_cycle   # fallback assumption, documented
            efc_now = float(windows.efc[i])
            if prev_efc is not None:
                ewma.update(efc_now - prev_efc, day - prev_day)
            prev_efc, prev_day = efc_now, day
            r = ewma.r
            age_y = float(windows.X_stat[i][5])  # age_years is static column index 5
            w_p10, w_p50, w_p90 = rul_efc_to_weeks(
                pred["rul_efc_p10"][i], pred["rul_efc_p50"][i], pred["rul_efc_p90"][i],
                r=r, sigma_r=ewma.sigma, age_years=age_y)
            out = gsm.update(day, float(pred["soh_q50"][i]), w_p10, w_p90, have_enough_data=True)
            seq.append({"day": day, "cycle_idx": int(windows.cycle_idx[i]), "grade": out["grade"],
                        "n_weeks": out["n_weeks"], "soh_true": float(windows.soh_true[i])})
        results[bid] = seq
    return results


def lead_time_and_alarms(grade_sequences):
    lead_times_weeks = []
    false_alarms, misses, n_batteries, n_censored = 0, 0, 0, 0
    for bid, seq in grade_sequences.items():
        n_batteries += 1
        days = np.array([r["day"] for r in seq])
        sohs = np.array([r["soh_true"] for r in seq])
        below = np.where(sohs <= EOL_SOH_PCT)[0]
        if len(below) == 0:
            # CENSORED: this battery never reached EoL in the data. Its true lead
            # time is unknown, so it must not count as a miss or a hit.
            n_censored += 1
            continue
        elif below[0] == 0:
            eol_day = float(days[0])
        else:
            i1 = below[0]
            i0 = i1 - 1
            s0, s1 = sohs[i0], sohs[i1]
            t = (s0 - EOL_SOH_PCT) / max(s0 - s1, 1e-6)
            eol_day = float(days[i0] + t * (days[i1] - days[i0]))

        replace_rows = [r for r in seq if r["grade"] == "REPLACE"]
        if replace_rows:
            first = replace_rows[0]
            lead_weeks = (eol_day - first["day"]) / 7.0
            lead_times_weeks.append(lead_weeks)
            if lead_weeks < 4.0:
                misses += 1
            remaining_weeks_true = (eol_day - first["day"]) / 7.0
            if remaining_weeks_true > 26.0:
                false_alarms += 1
        else:
            misses += 1

    lead_arr = np.array(lead_times_weeks)
    return {
        "median_lead_weeks": float(np.median(lead_arr)) if len(lead_arr) else None,
        "p10_lead_weeks": float(np.percentile(lead_arr, 10)) if len(lead_arr) else None,
        "n_batteries": n_batteries,
        "n_censored_no_eol": n_censored,
        "n_with_replace_grade": len(lead_times_weeks),
        "false_alarm_rate": false_alarms / max(n_batteries - n_censored, 1),
        "miss_rate": misses / max(n_batteries - n_censored, 1),
    }


# --------------------------------------------------------------------------- #
# Top-level report
# --------------------------------------------------------------------------- #

def build_report(models, stats, calib_windows, label="float", eval_windows=None):
    """Conformal offsets are fitted on `calib_windows`; every metric is computed on
    `eval_windows` (an INDEPENDENT final-test set when train.py was run with --n-test).
    If eval_windows is None the calibration set is reused and the report says so."""
    offsets, _raw_c, _real_c = fit_conformal(models, stats, calib_windows)
    if eval_windows is None:
        eval_windows = calib_windows
    calib_windows = eval_windows  # every metric below is on the evaluation set
    Xd_e, Xs_e = apply_standardizer(eval_windows.X_dyn, eval_windows.X_stat, stats)
    raw = ensemble_forward(models, Xd_e, Xs_e)
    real = raw_to_real(raw)
    pred_before = raw_no_conformal(real)
    pred_after = apply_conformal(real, offsets)

    soh_mae, soh_rmse = mae_rmse(pred_after["soh_q50"], calib_windows.soh_true)

    picp80_before, pice80_before, mpiw80_before = picp_pice_mpiw(
        calib_windows.soh_true, pred_before["soh_p10"], pred_before["soh_p90"], 0.80)
    picp80_after, pice80_after, mpiw80_after = picp_pice_mpiw(
        calib_windows.soh_true, pred_after["soh_p10"], pred_after["soh_p90"], 0.80)

    p25_a, p75_a = approx_50pct_interval(pred_after["soh_p10"], pred_after["soh_q50"], pred_after["soh_p90"])
    picp50_after, pice50_after, mpiw50_after = picp_pice_mpiw(calib_windows.soh_true, p25_a, p75_a, 0.50)

    nmpiw_rul = normalized_mpiw(pred_after["rul_efc_p10"], pred_after["rul_efc_p90"], calib_windows.rul_true)

    records = find_checkpoints(calib_windows)
    rel_err_summary, window_hit_rate, n_checkpoint_pairs = checkpoint_metrics(records, calib_windows, pred_after)

    grade_sequences = simulate_grades(calib_windows, pred_after)
    lead_alarm = lead_time_and_alarms(grade_sequences)

    return {
        "label": label,
        "n_calib_windows": int(len(calib_windows)),
        "n_calib_batteries": int(len(set(calib_windows.battery_id.tolist()))),
        "conformal_offsets": offsets,
        "soh_mae_pt": soh_mae, "soh_rmse_pt": soh_rmse,
        "picp_80": {"before": picp80_before, "after": picp80_after,
                    "pice_before_pt": pice80_before, "pice_after_pt": pice80_after,
                    "mpiw_before_pt": mpiw80_before, "mpiw_after_pt": mpiw80_after},
        "picp_50_approx": {"after": picp50_after, "pice_after_pt": pice50_after,
                            "mpiw_after_pt": mpiw50_after,
                            "note": "P25/P75 approximated from P10/P50/P90 (Z50/Z80 scaling) -- "
                                    "the architecture's quantile heads are fixed at tau=.1/.5/.9."},
        "rul_nmpiw": nmpiw_rul,
        "rul_relative_error_at_checkpoints": rel_err_summary,
        "rul_window_hit_rate": window_hit_rate,
        "n_checkpoint_pairs": n_checkpoint_pairs,
        "warning_lead_time": lead_alarm,
    }


def markdown_summary(report, dummy_label):
    lines = []
    lines.append("# SoH/RUL model evaluation -- %s\n" % report["label"])
    lines.append("**%s** -- see model/README.md for full honesty labelling.\n" % dummy_label)
    lines.append("- Calibration/eval set: %d windows across %d held-out batteries\n" %
                  (report["n_calib_windows"], report["n_calib_batteries"]))
    lines.append("## SoH point accuracy")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append("| MAE (pt) | %.3f |" % report["soh_mae_pt"])
    lines.append("| RMSE (pt) | %.3f |\n" % report["soh_rmse_pt"])
    lines.append("## Coverage (split-conformal, before -> after)")
    p80 = report["picp_80"]
    lines.append("| interval | nominal | PICP before | PICP after | PICE after (pt) | MPIW after |")
    lines.append("|---|---|---|---|---|---|")
    lines.append("| SoH 80%% | 0.80 | %.3f | %.3f | %.2f | %.3f pt |" %
                  (p80["before"], p80["after"], p80["pice_after_pt"], p80["mpiw_after_pt"]))
    p50 = report["picp_50_approx"]
    lines.append("| SoH 50%% (approx) | 0.50 | -- | %.3f | %.2f | %.3f pt |\n" %
                  (p50["after"], p50["pice_after_pt"], p50["mpiw_after_pt"]))
    lines.append("RUL normalised MPIW: %.3f\n" % report["rul_nmpiw"])
    lines.append("## RUL relative error at SoH checkpoints (n=%d battery-checkpoint pairs)" %
                  report["n_checkpoint_pairs"])
    lines.append("| SoH checkpoint | mean rel. err | median rel. err | n |")
    lines.append("|---|---|---|---|")
    for cp, v in sorted(report["rul_relative_error_at_checkpoints"].items(), key=lambda kv: -float(kv[0])):
        lines.append("| %s%% | %.3f | %.3f | %d |" % (cp, v["mean_rel_err"], v["median_rel_err"], v["n"]))
    lines.append("\nRUL-window hit-rate (EoL_true in [P10,P90]): **%.3f**\n" % report["rul_window_hit_rate"])
    la = report["warning_lead_time"]
    lines.append("## Warning lead time and grade-machine alarms")
    lines.append("- median lead time: %s weeks" % ("%.1f" % la["median_lead_weeks"] if la["median_lead_weeks"] is not None else "n/a"))
    lines.append("- P10 lead time: %s weeks" % ("%.1f" % la["p10_lead_weeks"] if la["p10_lead_weeks"] is not None else "n/a"))
    lines.append("- batteries reaching a persistent REPLACE grade: %d / %d" %
                  (la["n_with_replace_grade"], la["n_batteries"]))
    lines.append("- false-alarm rate: %.3f, miss rate: %.3f (censored batteries without observed EoL excluded: %d)\n" % (la["false_alarm_rate"], la["miss_rate"], la.get("n_censored_no_eol", 0)))
    lines.append("Conformal offsets: %s\n" % json.dumps(report["conformal_offsets"]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifacts", default="model/artifacts/")
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default=None, help="defaults to --artifacts")
    args = ap.parse_args()
    out_dir = Path(args.out or args.artifacts)
    out_dir.mkdir(parents=True, exist_ok=True)

    models, stats, split_info = load_ensemble(args.artifacts)
    df = load_and_validate(args.data)
    windows = build_windows(df)
    calib_mask = np.isin(windows.battery_id, split_info["calibration_batteries"])
    calib_windows = windows.subset(np.where(calib_mask)[0])
    test_ids = split_info.get("test_batteries", []) or []
    if test_ids:
        test_windows = windows.subset(np.where(np.isin(windows.battery_id, test_ids))[0])
        print("Conformal offsets from %d calibration batteries; metrics on %d INDEPENDENT test batteries %s (%d windows)" %
              (len(split_info["calibration_batteries"]), len(test_ids), test_ids, len(test_windows)))
        eval_note = "independent final-test batteries %s (never used for training, selection or calibration)" % test_ids
    else:
        test_windows = None
        print("Evaluating on %d calibration windows / %d batteries (no --n-test hold-out: NOT an independent test)" %
              (len(calib_windows), len(split_info["calibration_batteries"])))
        eval_note = "calibration batteries reused for metrics (no independent test set)"

    report = build_report(models, stats, calib_windows, label="float (PyTorch)", eval_windows=test_windows)
    report["evaluation_set"] = eval_note
    report["units"] = {"soh": "percentage points of rated capacity", "rul": "equivalent full cycles (EFC) to 80 % SoH; weeks via usage-rate EWMA", "time": "days from t_end_s timestamps when present, else cycle index"}

    with open(out_dir / "metrics.json", "w") as f:
        json.dump(report, f, indent=2)
    md = markdown_summary(report, "data: %s; evaluation set: %s" % (args.data, eval_note))
    with open(out_dir / "metrics_summary.md", "w") as f:
        f.write(md)

    print(md)
    print("Wrote %s and %s" % (out_dir / "metrics.json", out_dir / "metrics_summary.md"))


if __name__ == "__main__":
    main()
