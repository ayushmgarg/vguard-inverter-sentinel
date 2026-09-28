"""model/ablation.py -- transfer-learning ablation (design 02 SS4.2-4.4),
executed here as SYNTHETIC-TO-SYNTHETIC transfer (source = data/features_sim.csv,
run A; target = data/features_sim_b.csv, run B). See the loud label this
script prints and writes into ablation.md: no Li-ion source data has been
downloaded into this repo yet (model/datasets/nasa_pcoe.py and
model/datasets/calce.py exist and are tested, but no real .mat/.xlsx files
have landed in data/raw_nasa or data/raw_calce as of this run -- see the
"download outcome" section of model/README.md). This ablation demonstrates
the pipeline mechanism (Stage A pre-train -> Stage C frozen-then-L2SP
fine-tune, vs. target-only) faithfully; it says nothing about real
cross-chemistry transfer until Stage A runs on NASA/CALCE data.

Two arms, both fine-tuned/trained on the SAME target CSV with the SAME
GroupKFold-by-battery split parameters (--n-calib, --n-test), so
`split_calibration_batteries`'s seeded determinism (model/splits.py) gives
both arms the *identical* held-out final-test battery set automatically:
  (i)  target-only:    model/stages.py --stage A --data <target> --init none
  (ii) source->target: model/stages.py --stage A --data <source> --init none
                        (source pre-train)
                        model/stages.py --stage C --data <target> --init <source-out>
                        --freeze-conv --l2sp <beta>  (frozen-conv then L2-SP fine-tune)

Both arms are then evaluated with model/evaluate.py's build_report on the
SAME independent test-battery set (never used for training, model selection,
or conformal calibration in either arm), reporting SoH MAE/RMSE, PICP@80,
and RUL-window hit-rate side by side in model/artifacts_ablation/ablation.md.

CLI:
    python -m model.ablation --source data/features_sim.csv --target data/features_sim_b.csv \
        --out model/artifacts_ablation --seeds 3 --epochs 15
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import stages  # noqa: E402
from model.windowing import load_and_validate, build_windows, apply_standardizer  # noqa: E402
from model.evaluate import load_ensemble, build_report  # noqa: E402


def _load_models_and_eval_windows(artifacts_dir, target_csv):
    models, stats, split_info = load_ensemble(artifacts_dir)
    df = load_and_validate(target_csv)
    windows = build_windows(df)
    calib_ids = split_info["calibration_batteries"]
    test_ids = split_info.get("test_batteries", []) or []
    calib_windows = windows.subset(np.where(np.isin(windows.battery_id, calib_ids))[0])
    test_windows = None
    if test_ids:
        test_windows = windows.subset(np.where(np.isin(windows.battery_id, test_ids))[0])
    return models, stats, split_info, calib_windows, test_windows


def run_arm_target_only(target_csv, out_dir, n_calib, n_test, seeds, epochs, patience, verbose):
    out = Path(out_dir) / "target_only"
    stages.run_stage("A", target_csv, "none", str(out), seeds=seeds, epochs=epochs,
                      n_calib=n_calib, n_test=n_test, patience=patience, verbose=verbose)
    return out


def run_arm_transfer(source_csv, target_csv, out_dir, n_calib, n_test, seeds,
                      epochs_source, epochs_target, freeze_epochs, l2sp_beta, patience, verbose):
    out_source = Path(out_dir) / "transfer_stageA_source"
    out_target = Path(out_dir) / "transfer_stageC_target"
    # Source-side split params don't need to match the target's (source
    # batteries are never evaluated on) -- keep them modest so a small
    # source CSV (8 batteries here) still has enough left to train on.
    stages.run_stage("A", source_csv, "none", str(out_source), seeds=seeds,
                      epochs=epochs_source, n_calib=1, n_test=0, patience=patience, verbose=verbose)
    stages.run_stage("C", target_csv, str(out_source), str(out_target), seeds=seeds,
                      epochs=epochs_target, freeze_epochs=freeze_epochs, l2sp=l2sp_beta,
                      n_calib=n_calib, n_test=n_test, patience=patience, verbose=verbose)
    return out_source, out_target


def summarize_arm(name, artifacts_dir, target_csv):
    models, stats, split_info, calib_windows, test_windows = _load_models_and_eval_windows(
        artifacts_dir, target_csv)
    report = build_report(models, stats, calib_windows, label=name, eval_windows=test_windows)
    report["_artifacts_dir"] = str(artifacts_dir)
    report["_test_batteries"] = split_info.get("test_batteries", [])
    report["_calibration_batteries"] = split_info.get("calibration_batteries", [])
    report["_train_pool_batteries"] = split_info.get("train_pool_batteries", [])
    report["_evaluated_on"] = ("independent test batteries" if test_windows is not None
                                else "calibration batteries (no --n-test hold-out)")
    return report


def write_ablation_md(out_path, target_only_report, transfer_report, source_csv, target_csv,
                       n_calib, n_test, wall_seconds):
    def row(r):
        return "| %s | %.3f | %.3f | %.3f | %.3f |" % (
            r["label"], r["soh_mae_pt"], r["soh_rmse_pt"],
            r["picp_80"]["after"], r["rul_window_hit_rate"])

    lines = []
    lines.append("# Transfer-learning ablation (design 02 SS4.2-4.4)\n")
    lines.append("**SYNTHETIC-TO-SYNTHETIC TRANSFER; Li-ion source pending download.** "
                  "Source = `%s` (sim/ run A), target = `%s` (sim/ run B). "
                  "`model/datasets/nasa_pcoe.py` and `model/datasets/calce.py` exist and are "
                  "unit-tested (`tests/test_datasets.py`) but no real Li-ion .mat/.xlsx files "
                  "have been downloaded into this repo as of this run -- see model/README.md's "
                  "download-outcome section. This ablation demonstrates the Stage A -> Stage C "
                  "(frozen-conv then L2-SP) transfer MECHANISM faithfully; it makes no claim "
                  "about real cross-chemistry transfer.\n" % (source_csv, target_csv))
    lines.append("Both arms trained/fine-tuned on the SAME target CSV with the SAME "
                  "GroupKFold-by-battery split parameters (`--n-calib %d --n-test %d`), so "
                  "`model/splits.py`'s seeded determinism gives both arms the IDENTICAL "
                  "held-out final-test battery set (confirmed below) -- point accuracy is "
                  "reported on that independent test set, never on the calibration batteries "
                  "used to fit the conformal offsets.\n" % (n_calib, n_test))
    lines.append("| arm | SoH MAE (pt) | SoH RMSE (pt) | PICP@80 (after conformal) | RUL-window hit-rate |")
    lines.append("|---|---|---|---|---|")
    lines.append(row(target_only_report))
    lines.append(row(transfer_report))
    lines.append("")
    lines.append("- target-only test batteries: %s" % target_only_report["_test_batteries"])
    lines.append("- transfer (source->target) test batteries: %s" % transfer_report["_test_batteries"])
    lines.append("- same test set: **%s**\n" % (target_only_report["_test_batteries"] == transfer_report["_test_batteries"]))
    lines.append("Evaluated on: target-only -> %s; transfer -> %s\n" %
                  (target_only_report["_evaluated_on"], transfer_report["_evaluated_on"]))
    lines.append("## Full reports\n")
    lines.append("### (i) target-only")
    lines.append("```json\n%s\n```\n" % json.dumps(
        {k: v for k, v in target_only_report.items() if not str(k).startswith("_")}, indent=2))
    lines.append("### (ii) source-pretrain -> target fine-tune (Stage A -> Stage C)")
    lines.append("```json\n%s\n```\n" % json.dumps(
        {k: v for k, v in transfer_report.items() if not str(k).startswith("_")}, indent=2))
    lines.append("Wall time: %.1fs.\n" % wall_seconds)
    Path(out_path).write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="data/features_sim.csv")
    ap.add_argument("--target", default="data/features_sim_b.csv")
    ap.add_argument("--out", default="model/artifacts_ablation")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--source-epochs", type=int, default=15)
    ap.add_argument("--freeze-epochs", type=int, default=8)
    ap.add_argument("--l2sp", type=float, default=1e-3)
    ap.add_argument("--n-calib", type=int, default=2)
    ap.add_argument("--n-test", type=int, default=2)
    ap.add_argument("--patience", type=int, default=6)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    verbose = not args.quiet

    print("=== Arm (i): target-only (%s) ===" % args.target)
    target_only_dir = run_arm_target_only(
        args.target, out_dir, n_calib=args.n_calib, n_test=args.n_test,
        seeds=args.seeds, epochs=args.epochs, patience=args.patience, verbose=verbose)

    print("=== Arm (ii): pre-train on %s, fine-tune on %s ===" % (args.source, args.target))
    _, transfer_target_dir = run_arm_transfer(
        args.source, args.target, out_dir, n_calib=args.n_calib, n_test=args.n_test,
        seeds=args.seeds, epochs_source=args.source_epochs, epochs_target=args.epochs,
        freeze_epochs=args.freeze_epochs, l2sp_beta=args.l2sp, patience=args.patience,
        verbose=verbose)

    print("=== Evaluating both arms on the target CSV's held-out test batteries ===")
    target_only_report = summarize_arm("target-only", target_only_dir, args.target)
    transfer_report = summarize_arm("source-pretrain -> target fine-tune", transfer_target_dir, args.target)

    wall = time.time() - t0
    md_path = out_dir / "ablation.md"
    write_ablation_md(md_path, target_only_report, transfer_report, args.source, args.target,
                       args.n_calib, args.n_test, wall)
    with open(out_dir / "ablation.json", "w") as f:
        json.dump({"target_only": target_only_report, "transfer": transfer_report,
                    "wall_seconds": wall}, f, indent=2)

    print("\n=== Summary ===")
    print("%-40s %10s %10s %10s %10s" % ("arm", "SoH MAE", "SoH RMSE", "PICP@80", "RUL hit"))
    for r in (target_only_report, transfer_report):
        print("%-40s %10.3f %10.3f %10.3f %10.3f" %
              (r["label"], r["soh_mae_pt"], r["soh_rmse_pt"], r["picp_80"]["after"], r["rul_window_hit_rate"]))
    print("\nWrote %s and %s (%.1fs total)" % (md_path, out_dir / "ablation.json", wall))


if __name__ == "__main__":
    main()
