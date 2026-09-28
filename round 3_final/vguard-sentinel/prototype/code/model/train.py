"""model/train.py — train the SentinelNet ensemble (design 02 §4).

Pipeline:
  1. load + validate features CSV (features/schema.py)
  2. build 30x14 + 6 windows (model/windowing.py), >= 10 real cycles required
  3. hold out `--n-calib` batteries entirely (never trained on) for
     split-conformal calibration in model/evaluate.py
  4. GroupKFold-by-battery CV (+ leave-one-condition-out if a `condition`
     column exists) over the remaining batteries, for diagnostic metrics
  5. train `--seeds` models (different init) on all non-calibration
     batteries, early-stopped on a battery-grouped validation split
  6. save each seed's weights, the standardiser, the calibration/CV split,
     and a training summary to `--out`

CLI:
    python -m model.train --data data/features_sim_dummy.csv --out model/artifacts/
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

# This is a ~28k-param model trained on a few thousand small windows --
# torch's default all-cores thread pool spends more time on thread
# scheduling than on the tiny matmuls themselves. A couple of threads is
# faster in practice and keeps CPU headroom free on a shared machine.
torch.set_num_threads(min(4, max(1, torch.get_num_threads())))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.schema import scale_soh, scale_rul, unscale_soh, FEATURE_SCHEMA_VERSION  # noqa: E402
from model.net import build_model  # noqa: E402
from model.losses import SentinelLoss  # noqa: E402
from model.splits import (  # noqa: E402
    split_calibration_batteries, group_kfold_battery_splits, leave_one_condition_out_splits,
)
from model.windowing import (  # noqa: E402
    load_and_validate, build_windows, fit_standardizer, apply_standardizer,
    compute_sample_weights,
)


def _battery_val_split(battery_ids, val_frac=0.2, seed=0):
    ids = np.array(sorted(set(battery_ids)))
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(ids))
    n_val = max(1, int(round(val_frac * len(ids))))
    val_ids = set(ids[perm[:n_val]].tolist())
    train_idx = np.where(~np.isin(battery_ids, list(val_ids)))[0]
    val_idx = np.where(np.isin(battery_ids, list(val_ids)))[0]
    return train_idx, val_idx


def _batches(n, batch_size, rng):
    order = rng.permutation(n)
    for start in range(0, n, batch_size):
        yield order[start:start + batch_size]


def _forward_batch(model, X_dyn_std, X_stat_std, idx):
    Xd = torch.tensor(X_dyn_std[idx])
    Xs = torch.tensor(X_stat_std[idx])
    return model(Xd, Xs)


def compute_val_metrics(model, loss_fn, X_dyn_std, X_stat_std, soh_scaled, rul_scaled, weight, val_idx):
    """Forward pass in inference mode (dropout/batchnorm off -- this net has
    neither, but keep the mode switch for correctness/future-proofing)."""
    was_training = model.training
    model.train(False)
    with torch.no_grad():
        out = _forward_batch(model, X_dyn_std, X_stat_std, val_idx)
        soh_t = torch.tensor(soh_scaled[val_idx])
        rul_t = torch.tensor(rul_scaled[val_idx])
        w_t = torch.tensor(weight[val_idx])
        _, parts = loss_fn(out, soh_t, rul_t, w_t)
        soh_mae = float(np.mean(np.abs(unscale_soh(out["soh"]["q50"].numpy()) -
                                        unscale_soh(soh_scaled[val_idx]))))
    model.train(was_training)
    parts["soh_mae_pt"] = soh_mae
    return parts


def train_one_seed(seed, X_dyn_std, X_stat_std, soh_scaled, rul_scaled, weight,
                    adjacent_pairs, train_idx, val_idx,
                    epochs=15, batch_size=64, lr=1e-3, patience=6,
                    lambda_R=1.0, lambda_mono=1.0, lambda_cross=1.0, verbose=True):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)

    model = build_model()
    model.train(True)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(epochs, 1))
    loss_fn = SentinelLoss(lambda_R=lambda_R, lambda_mono=lambda_mono, lambda_cross=lambda_cross)

    train_set = set(train_idx.tolist())
    train_pairs = [(i, j) for i, j in adjacent_pairs if i in train_set and j in train_set]

    best_val = float("inf")
    best_state = copy.deepcopy(model.state_dict())
    bad_epochs = 0
    history = []

    for epoch in range(epochs):
        for batch_idx in _batches(len(train_idx), batch_size, rng):
            idx = train_idx[batch_idx]
            out = _forward_batch(model, X_dyn_std, X_stat_std, idx)
            soh_t = torch.tensor(soh_scaled[idx])
            rul_t = torch.tensor(rul_scaled[idx])
            w_t = torch.tensor(weight[idx])

            soh50_k = soh50_km1 = None
            if train_pairs:
                k = min(len(idx), len(train_pairs))
                pair_sel = rng.choice(len(train_pairs), size=k, replace=(k > len(train_pairs)))
                pi = np.array([train_pairs[t][0] for t in pair_sel])
                pj = np.array([train_pairs[t][1] for t in pair_sel])
                out_i = _forward_batch(model, X_dyn_std, X_stat_std, pi)
                out_j = _forward_batch(model, X_dyn_std, X_stat_std, pj)
                soh50_km1, soh50_k = out_i["soh"]["q50"], out_j["soh"]["q50"]

            loss, _ = loss_fn(out, soh_t, rul_t, w_t, soh50_k, soh50_km1)
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()

        val_parts = compute_val_metrics(model, loss_fn, X_dyn_std, X_stat_std,
                                         soh_scaled, rul_scaled, weight, val_idx)
        history.append({"epoch": epoch, **val_parts})
        if verbose:
            print("  seed=%d epoch=%d val_total=%.4f soh_mae=%.3fpt" %
                  (seed, epoch, val_parts["total"], val_parts["soh_mae_pt"]))

        if val_parts["total"] < best_val - 1e-5:
            best_val = val_parts["total"]
            best_state = copy.deepcopy(model.state_dict())
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                if verbose:
                    print("  seed=%d early stop at epoch %d (best val=%.4f)" % (seed, epoch, best_val))
                break

    model.load_state_dict(best_state)
    model.train(False)
    return model, best_val, history


def run_group_kfold_cv(windows, X_dyn_std, X_stat_std, soh_scaled, rul_scaled, weight,
                        n_folds, epochs, seed=0, **train_kwargs):
    results = []
    fold_i = 0
    for train_idx, val_idx in group_kfold_battery_splits(windows.battery_id, n_folds=n_folds):
        t0 = time.time()
        _, best_val, _ = train_one_seed(
            seed=1000 + seed + fold_i, X_dyn_std=X_dyn_std, X_stat_std=X_stat_std,
            soh_scaled=soh_scaled, rul_scaled=rul_scaled, weight=weight,
            adjacent_pairs=windows.adjacent_pairs, train_idx=train_idx, val_idx=val_idx,
            epochs=epochs, verbose=False, **train_kwargs,
        )
        results.append({
            "fold": fold_i, "n_train": int(len(train_idx)), "n_val": int(len(val_idx)),
            "val_pinball_total": best_val, "seconds": time.time() - t0,
            "val_batteries": sorted(set(windows.battery_id[val_idx].tolist())),
        })
        fold_i += 1
        print("  CV fold %d/%d done: val_total=%.4f (%.1fs)" % (fold_i, n_folds, best_val, results[-1]["seconds"]))
    return results


def run_leave_one_condition_out(windows, X_dyn_std, X_stat_std, soh_scaled, rul_scaled, weight,
                                 epochs, **train_kwargs):
    if windows.condition is None:
        return None
    results = []
    for train_idx, val_idx, cond in leave_one_condition_out_splits(
            np.arange(len(windows)), windows.condition):
        t0 = time.time()
        _, best_val, _ = train_one_seed(
            seed=2000, X_dyn_std=X_dyn_std, X_stat_std=X_stat_std,
            soh_scaled=soh_scaled, rul_scaled=rul_scaled, weight=weight,
            adjacent_pairs=windows.adjacent_pairs, train_idx=train_idx, val_idx=val_idx,
            epochs=epochs, verbose=False, **train_kwargs,
        )
        results.append({
            "held_out_condition": str(cond), "n_train": int(len(train_idx)),
            "n_val": int(len(val_idx)), "val_pinball_total": best_val,
            "seconds": time.time() - t0,
        })
        print("  LOCO held-out=%s: val_total=%.4f (%.1fs)" % (cond, best_val, results[-1]["seconds"]))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="model/artifacts/")
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--cv-epochs", type=int, default=8)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--cv-folds", type=int, default=6)
    ap.add_argument("--n-calib", type=int, default=6)
    ap.add_argument("--n-test", type=int, default=0,
                    help="batteries held out as an independent FINAL TEST set (never seen by training, model selection or conformal calibration)")
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--patience", type=int, default=6)
    ap.add_argument("--lambda-R", dest="lambda_R", type=float, default=1.0)
    ap.add_argument("--lambda-mono", type=float, default=1.0)
    ap.add_argument("--lambda-cross", type=float, default=1.0)
    ap.add_argument("--no-cv", action="store_true", help="skip GroupKFold CV (faster)")
    ap.add_argument("--loco", action="store_true", help="also run leave-one-condition-out CV")
    args = ap.parse_args()

    t_start = time.time()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading %s ..." % args.data)
    df = load_and_validate(args.data)
    print("  %d rows, %d batteries" % (len(df), df["battery_id"].nunique()))

    windows = build_windows(df)
    print("Built %d windows (>= 10 real cycles each)" % len(windows))

    # split order: test (independent) -> calibration -> training pool; seed 0 keeps it reproducible
    test_ids = []
    remaining_ids = windows.battery_id
    if args.n_test > 0:
        rest_ids, test_ids = split_calibration_batteries(windows.battery_id, n_calib=args.n_test, seed=1)
        remaining_ids = windows.battery_id[np.isin(windows.battery_id, rest_ids)]
    train_pool_ids, calib_ids = split_calibration_batteries(
        remaining_ids, n_calib=args.n_calib, seed=0)
    if test_ids:
        print("Held out %d FINAL-TEST batteries (untouched until evaluate): %s" % (len(test_ids), test_ids))
    pool_mask = np.isin(windows.battery_id, train_pool_ids)
    windows_pool = windows.subset(np.where(pool_mask)[0])
    print("Held out %d calibration batteries: %s" % (len(calib_ids), calib_ids))
    print("Training pool: %d batteries, %d windows" % (len(train_pool_ids), len(windows_pool)))

    split_info = {
        "n_calib": args.n_calib, "split_seed": 0,
        "train_pool_batteries": train_pool_ids, "calibration_batteries": calib_ids,
        "test_batteries": test_ids,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
    }
    with open(out_dir / "split_info.json", "w") as f:
        json.dump(split_info, f, indent=2)

    stats = fit_standardizer(windows_pool.X_dyn, windows_pool.X_stat)
    with open(out_dir / "mean_scale.json", "w") as f:
        json.dump(stats, f, indent=2)

    X_dyn_std, X_stat_std = apply_standardizer(windows_pool.X_dyn, windows_pool.X_stat, stats)
    soh_scaled = scale_soh(windows_pool.soh_true)
    rul_scaled = scale_rul(windows_pool.rul_true)
    weight = compute_sample_weights(windows_pool.rul_true)

    train_kwargs = dict(batch_size=args.batch_size, lr=args.lr, patience=args.patience,
                         lambda_R=args.lambda_R, lambda_mono=args.lambda_mono,
                         lambda_cross=args.lambda_cross)

    cv_metrics = None
    if not args.no_cv:
        print("Running %d-fold GroupKFold CV (cv-epochs=%d) ..." % (args.cv_folds, args.cv_epochs))
        cv_metrics = run_group_kfold_cv(windows_pool, X_dyn_std, X_stat_std, soh_scaled,
                                         rul_scaled, weight, n_folds=args.cv_folds,
                                         epochs=args.cv_epochs, **train_kwargs)
        with open(out_dir / "cv_metrics.json", "w") as f:
            json.dump(cv_metrics, f, indent=2)

    loco_metrics = None
    if args.loco:
        print("Running leave-one-condition-out CV ...")
        loco_metrics = run_leave_one_condition_out(windows_pool, X_dyn_std, X_stat_std,
                                                     soh_scaled, rul_scaled, weight,
                                                     epochs=args.cv_epochs, **train_kwargs)
        if loco_metrics is not None:
            with open(out_dir / "loco_metrics.json", "w") as f:
                json.dump(loco_metrics, f, indent=2)
        else:
            print("  no `condition` column present -- LOCO skipped")

    final_train_idx, final_val_idx = _battery_val_split(
        windows_pool.battery_id, val_frac=args.val_frac, seed=0)
    print("Final ensemble: %d train windows, %d val windows" %
          (len(final_train_idx), len(final_val_idx)))

    seed_results = []
    for s in range(args.seeds):
        seed = args.seed_base + s
        print("Training seed %d/%d (seed value=%d) ..." % (s + 1, args.seeds, seed))
        model, best_val, history = train_one_seed(
            seed=seed, X_dyn_std=X_dyn_std, X_stat_std=X_stat_std,
            soh_scaled=soh_scaled, rul_scaled=rul_scaled, weight=weight,
            adjacent_pairs=windows_pool.adjacent_pairs,
            train_idx=final_train_idx, val_idx=final_val_idx,
            epochs=args.epochs, **train_kwargs,
        )
        torch.save(model.state_dict(), out_dir / ("seed%d.pt" % s))
        seed_results.append({"seed": seed, "best_val_pinball_total": best_val,
                              "n_epochs_run": len(history)})

    n_params = build_model().param_count()
    n_macs = build_model().mac_count()
    summary = {
        "args": vars(args),
        "n_windows_total": int(len(windows)),
        "n_windows_pool": int(len(windows_pool)),
        "n_calib_batteries": len(calib_ids),
        "n_train_pool_batteries": len(train_pool_ids),
        "param_count": n_params,
        "mac_count": n_macs,
        "seed_results": seed_results,
        "cv_summary": ({"n_folds": args.cv_folds,
                         "mean_val_pinball_total": float(np.mean([r["val_pinball_total"] for r in cv_metrics]))}
                        if cv_metrics else None),
        "wall_seconds": time.time() - t_start,
    }
    with open(out_dir / "training_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("Done in %.1fs. Artifacts in %s" % (summary["wall_seconds"], out_dir))


if __name__ == "__main__":
    main()
