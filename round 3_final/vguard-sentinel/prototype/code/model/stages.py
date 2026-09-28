"""model/stages.py -- Stage A/B/C training CLI (design 02 SS4.2-4.4).

    Stage A: pre-train from scratch on a Li-ion (or any) feature CSV (SS4.2).
    Stage B: continue from Stage-A weights on the synthetic Indian-duty
             bridge CSV (SS4.3) -- plain fine-tune, nothing frozen.
    Stage C: fine-tune on a target CSV in two phases (SS4.4):
             C1 freeze conv1-3, train dense1/dense2/heads only, no L2-SP;
             C2 unfreeze everything, train with a lower LR on the conv
             layers, and an L2-SP penalty (beta * sum((theta-theta_init)^2))
             toward the *Stage-C input* weights ("Stage-B weights" in design
             02's running example) so a small target set cannot drag the
             filters far from what pre-training learned.

This module is a thin orchestration layer: every numerical building block --
the model (model/net.py), the loss (model/losses.py), the window/standardiser
builders (model/windowing.py), the battery-level split logic (model/splits.py),
the scale/unscale helpers (features/schema.py), and even the inner batching
loop and validation-metric computation (model/train.py's `_batches`,
`_forward_batch`, `compute_val_metrics`, `_battery_val_split`) -- is imported
from those modules, not re-implemented. The only genuinely new code here is
the outer training loop that model/train.py's `train_one_seed` has no hook
for: selecting which parameters are trainable (conv frozen or not) and adding
the L2-SP penalty term. That loop's *shape* necessarily resembles
`train_one_seed`'s (same epoch/batch/early-stop structure) because it is
doing the same job with two extra knobs -- but every reusable piece inside it
is a direct call into model/train.py, not a copy of its body.

CLI:
    python -m model.stages --stage A --data data/features_sim.csv \
        --init none --out model/artifacts_ablation/stageA

    python -m model.stages --stage B --data data/features_sim_b.csv \
        --init model/artifacts_ablation/stageA --out model/artifacts_ablation/stageB

    python -m model.stages --stage C --data data/features_sim_b.csv \
        --init model/artifacts_ablation/stageB --out model/artifacts_ablation/stageC \
        --freeze-conv --l2sp 1e-3

Output artifacts (same file names as model/train.py, so model/evaluate.py and
model/quantize.py work unmodified against a stages.py output directory):
    seed*.pt, mean_scale.json, split_info.json, training_summary.json
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

torch.set_num_threads(min(4, max(1, torch.get_num_threads())))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.schema import scale_soh, scale_rul, unscale_soh, FEATURE_SCHEMA_VERSION  # noqa: E402
from model.net import build_model  # noqa: E402
from model.losses import SentinelLoss  # noqa: E402
from model.splits import split_calibration_batteries  # noqa: E402
from model.windowing import (  # noqa: E402
    load_and_validate, build_windows, fit_standardizer, apply_standardizer,
    compute_sample_weights,
)
# Reused verbatim from model/train.py -- see module docstring.
from model.train import (  # noqa: E402
    _battery_val_split, _batches, _forward_batch, compute_val_metrics,
)

CONV_LAYER_NAMES = ("conv1", "conv2", "conv3")
STAGES = ("A", "B", "C")


# --------------------------------------------------------------------------- #
# Transfer-aware single-seed training loop (the one piece not in model/train.py)
# --------------------------------------------------------------------------- #

def _set_conv_trainable(model, trainable):
    for name in CONV_LAYER_NAMES:
        for p in getattr(model, name).parameters():
            p.requires_grad = trainable


def _l2sp_penalty(model, ref_state, beta):
    if beta <= 0 or ref_state is None:
        return torch.tensor(0.0)
    terms = []
    for name, p in model.named_parameters():
        if p.requires_grad and name in ref_state:
            terms.append(((p - ref_state[name]) ** 2).sum())
    if not terms:
        return torch.tensor(0.0)
    return beta * torch.stack(terms).sum()


def train_one_seed_transfer(seed, X_dyn_std, X_stat_std, soh_scaled, rul_scaled, weight,
                             adjacent_pairs, train_idx, val_idx,
                             init_state_dict=None, freeze_conv=False, l2sp_beta=0.0,
                             l2sp_anchor_state=None, conv_lr_mult=1.0, epochs=15,
                             batch_size=64, lr=1e-3, patience=6, lambda_R=1.0,
                             lambda_mono=1.0, lambda_cross=1.0, verbose=True, log_prefix=""):
    """Same epoch/batch/early-stop shape as model.train.train_one_seed, plus:
      - optional initialisation from `init_state_dict` (a prior stage's/phase's weights)
      - optional freezing of the three conv layers (`freeze_conv`)
      - optional L2-SP penalty (`l2sp_beta`) toward `l2sp_anchor_state` (falls
        back to `init_state_dict` if not given separately -- Stage C's C2
        phase passes these differently: it *starts* from C1's weights but
        the L2-SP *anchor* is the Stage-C input weights, design 02 SS4.4)
      - a separate (lower) LR multiplier on the conv params (`conv_lr_mult`),
        design 02 SS4.4's "lr 1e-4 conv / 5e-4 dense" split.
    `_batches`, `_forward_batch`, `compute_val_metrics` are imported from
    model/train.py unchanged."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)

    model = build_model()
    if init_state_dict is not None:
        model.load_state_dict(init_state_dict)
    anchor = l2sp_anchor_state if l2sp_anchor_state is not None else init_state_dict
    ref_state = None if anchor is None else {k: v.clone().detach() for k, v in anchor.items()}
    _set_conv_trainable(model, not freeze_conv)
    model.train(True)

    conv_params, other_params = [], []
    for name in CONV_LAYER_NAMES:
        conv_params += [p for p in getattr(model, name).parameters() if p.requires_grad]
    for name, p in model.named_parameters():
        if not name.split(".")[0] in CONV_LAYER_NAMES and p.requires_grad:
            other_params.append(p)
    param_groups = []
    if conv_params:
        param_groups.append({"params": conv_params, "lr": lr * conv_lr_mult})
    if other_params:
        param_groups.append({"params": other_params, "lr": lr})
    if not param_groups:
        raise ValueError("no trainable parameters (freeze_conv=True leaves nothing to train "
                          "if the dense/head layers were also frozen elsewhere)")

    opt = torch.optim.AdamW(param_groups)
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
            loss = loss + _l2sp_penalty(model, ref_state, l2sp_beta)
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()

        val_parts = compute_val_metrics(model, loss_fn, X_dyn_std, X_stat_std,
                                         soh_scaled, rul_scaled, weight, val_idx)
        history.append({"epoch": epoch, **val_parts})
        if verbose:
            print("  %sseed=%d epoch=%d val_total=%.4f soh_mae=%.3fpt" %
                  (log_prefix, seed, epoch, val_parts["total"], val_parts["soh_mae_pt"]))

        if val_parts["total"] < best_val - 1e-5:
            best_val = val_parts["total"]
            best_state = copy.deepcopy(model.state_dict())
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                if verbose:
                    print("  %sseed=%d early stop at epoch %d (best val=%.4f)" %
                          (log_prefix, seed, epoch, best_val))
                break

    model.load_state_dict(best_state)
    model.train(False)
    _set_conv_trainable(model, True)  # restore for any downstream re-use
    return model, best_val, history


def train_stage_c_seed(seed, X_dyn_std, X_stat_std, soh_scaled, rul_scaled, weight,
                        adjacent_pairs, train_idx, val_idx, init_state_dict,
                        freeze_epochs, epochs, l2sp_beta, conv_lr_mult=0.2, **kw):
    """C1 (frozen conv, no L2-SP) then C2 (unfrozen, L2-SP toward the
    ORIGINAL init_state_dict -- design 02 SS4.4: "a small set cannot drag the
    filters far" from what pre-training learned, not from wherever C1 left
    the dense layers)."""
    verbose = kw.pop("verbose", True)
    model_c1, val_c1, hist_c1 = train_one_seed_transfer(
        seed, X_dyn_std, X_stat_std, soh_scaled, rul_scaled, weight,
        adjacent_pairs, train_idx, val_idx, init_state_dict=init_state_dict,
        freeze_conv=True, l2sp_beta=0.0, epochs=freeze_epochs, verbose=verbose,
        log_prefix="C1 ", **kw)
    c1_state = model_c1.state_dict()
    # C2 *starts* from C1's weights (conv unchanged, dense/heads re-adapted)
    # but the L2-SP *anchor* is the original Stage-C input weights -- design
    # 02 SS4.4: "a small [target] set cannot drag the filters far" from what
    # pre-training learned, not from wherever the frozen-conv phase left the
    # dense layers.
    model_c2, val_c2, hist_c2 = train_one_seed_transfer(
        seed, X_dyn_std, X_stat_std, soh_scaled, rul_scaled, weight,
        adjacent_pairs, train_idx, val_idx, init_state_dict=c1_state,
        l2sp_anchor_state=init_state_dict, freeze_conv=False, l2sp_beta=l2sp_beta,
        conv_lr_mult=conv_lr_mult, epochs=epochs, verbose=verbose, log_prefix="C2 ", **kw)
    return model_c2, val_c2, {"c1": hist_c1, "c2": hist_c2}


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def _load_init(init_arg, seed_idx):
    """--init none -> None. --init <dir> -> that dir's seed{seed_idx}.pt if
    present, else its seed0.pt (so a 1-seed Stage A can still seed a
    multi-seed Stage B/C)."""
    if init_arg is None or str(init_arg).lower() == "none":
        return None, None
    d = Path(init_arg)
    cand = d / ("seed%d.pt" % seed_idx)
    if not cand.exists():
        cand = d / "seed0.pt"
    if not cand.exists():
        raise FileNotFoundError("--init %s has no seed*.pt files" % init_arg)
    return torch.load(cand, map_location="cpu", weights_only=True), str(cand)


def run_stage(stage, data_path, init_arg, out_dir, freeze_conv=False, l2sp=None,
              seeds=3, seed_base=0, epochs=15, freeze_epochs=8, n_calib=2, n_test=2,
              val_frac=0.2, batch_size=64, lr=1e-3, patience=6, conv_lr_mult=0.2,
              lambda_R=1.0, lambda_mono=1.0, lambda_cross=1.0, verbose=True):
    assert stage in STAGES, "stage must be one of %s" % (STAGES,)
    t_start = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_and_validate(data_path)
    windows = build_windows(df)
    if verbose:
        print("Stage %s: loaded %s -- %d rows, %d batteries, %d windows" %
              (stage, data_path, len(df), df["battery_id"].nunique(), len(windows)))

    all_ids = windows.battery_id
    test_ids = []
    remaining = all_ids
    if n_test > 0:
        rest_ids, test_ids = split_calibration_batteries(all_ids, n_calib=n_test, seed=1)
        remaining = all_ids[np.isin(all_ids, rest_ids)]
    train_pool_ids, calib_ids = split_calibration_batteries(remaining, n_calib=n_calib, seed=0)
    pool_mask = np.isin(windows.battery_id, train_pool_ids)
    windows_pool = windows.subset(np.where(pool_mask)[0])

    split_info = {
        "stage": stage, "data": str(data_path), "init": str(init_arg),
        "n_calib": n_calib, "n_test": n_test, "split_seed": 0,
        "train_pool_batteries": train_pool_ids, "calibration_batteries": calib_ids,
        "test_batteries": test_ids, "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "freeze_conv": bool(freeze_conv or stage == "C"),
        "l2sp_beta": (l2sp if l2sp is not None else (1e-3 if stage == "C" else 0.0)),
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

    final_train_idx, final_val_idx = _battery_val_split(
        windows_pool.battery_id, val_frac=val_frac, seed=0)

    effective_freeze = bool(freeze_conv or stage == "C")
    effective_l2sp = l2sp if l2sp is not None else (1e-3 if stage == "C" else 0.0)

    seed_results = []
    for s in range(seeds):
        seed = seed_base + s
        init_state, init_path = _load_init(init_arg, s)
        if init_state is None and stage != "A" and str(init_arg).lower() != "none":
            raise FileNotFoundError("Stage %s needs --init weights (got %r)" % (stage, init_arg))
        kw = dict(batch_size=batch_size, lr=lr, patience=patience,
                  lambda_R=lambda_R, lambda_mono=lambda_mono, lambda_cross=lambda_cross,
                  verbose=verbose)
        if stage == "C":
            model, best_val, history = train_stage_c_seed(
                seed, X_dyn_std, X_stat_std, soh_scaled, rul_scaled, weight,
                windows_pool.adjacent_pairs, final_train_idx, final_val_idx,
                init_state_dict=init_state, freeze_epochs=freeze_epochs, epochs=epochs,
                l2sp_beta=effective_l2sp, conv_lr_mult=conv_lr_mult, **kw)
        else:
            model, best_val, history = train_one_seed_transfer(
                seed, X_dyn_std, X_stat_std, soh_scaled, rul_scaled, weight,
                windows_pool.adjacent_pairs, final_train_idx, final_val_idx,
                init_state_dict=init_state, freeze_conv=effective_freeze,
                l2sp_beta=effective_l2sp, conv_lr_mult=conv_lr_mult, epochs=epochs, **kw)
        torch.save(model.state_dict(), out_dir / ("seed%d.pt" % s))
        seed_results.append({"seed": seed, "best_val_pinball_total": best_val,
                              "init_from": init_path})

    summary = {
        "stage": stage, "data": str(data_path), "init": str(init_arg),
        "freeze_conv": effective_freeze, "l2sp_beta": effective_l2sp,
        "n_windows_pool": int(len(windows_pool)), "n_train_pool_batteries": len(train_pool_ids),
        "n_calib_batteries": len(calib_ids), "n_test_batteries": len(test_ids),
        "seed_results": seed_results, "wall_seconds": time.time() - t_start,
    }
    with open(out_dir / "training_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    if verbose:
        print("Stage %s done in %.1fs -> %s" % (stage, summary["wall_seconds"], out_dir))
    return out_dir, split_info, summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=list(STAGES))
    ap.add_argument("--data", required=True)
    ap.add_argument("--init", default="none", help="artifacts dir with seed*.pt, or 'none' for from-scratch")
    ap.add_argument("--out", required=True)
    ap.add_argument("--freeze-conv", action="store_true",
                     help="freeze conv1-3 while training (implied by --stage C)")
    ap.add_argument("--l2sp", type=float, default=None,
                     help="L2-SP beta toward --init weights (default 1e-3 for stage C, 0 otherwise)")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--freeze-epochs", type=int, default=8, help="stage C phase C1 epoch count")
    ap.add_argument("--n-calib", type=int, default=2)
    ap.add_argument("--n-test", type=int, default=2)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--conv-lr-mult", type=float, default=0.2,
                     help="conv LR = lr * this (design 02 SS4.4: ~1e-4 conv / 5e-4 dense)")
    ap.add_argument("--patience", type=int, default=6)
    ap.add_argument("--lambda-R", dest="lambda_R", type=float, default=1.0)
    ap.add_argument("--lambda-mono", type=float, default=1.0)
    ap.add_argument("--lambda-cross", type=float, default=1.0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    run_stage(args.stage, args.data, args.init, args.out,
              freeze_conv=args.freeze_conv, l2sp=args.l2sp, seeds=args.seeds,
              seed_base=args.seed_base, epochs=args.epochs, freeze_epochs=args.freeze_epochs,
              n_calib=args.n_calib, n_test=args.n_test, val_frac=args.val_frac,
              batch_size=args.batch_size, lr=args.lr, patience=args.patience,
              conv_lr_mult=args.conv_lr_mult, lambda_R=args.lambda_R,
              lambda_mono=args.lambda_mono, lambda_cross=args.lambda_cross,
              verbose=not args.quiet)


if __name__ == "__main__":
    main()
