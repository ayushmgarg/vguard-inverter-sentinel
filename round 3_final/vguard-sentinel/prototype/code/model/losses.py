"""model/losses.py — pinball + monotonicity + cross penalties, design 02 §4.1.

    L = sum_{tau in .1,.5,.9} pinball_tau(SoH) + lambda_R * sum_tau pinball_tau(ln(1+RUL))
      + lambda_mono * mean(ReLU(SoH50(k) - SoH50(k-1) - 0.5))
      + lambda_cross * (ReLU(-d_lo) + ReLU(-d_hi))
    sample weight w = 1 + 3*exp(-RUL_EFC/100)

lambda_R = 1 is given explicitly in the design doc. lambda_mono and
lambda_cross are not given numeric values in the text (only named) -- this
module defaults both to 1.0, order-matched to the pinball terms, and exposes
them as constructor args so they are easy to retune; that assumption is
called out in model/README.md.
"""

from __future__ import annotations

import torch

TAUS = (0.1, 0.5, 0.9)


def pinball_elementwise(pred, target, tau):
    diff = target - pred
    return torch.maximum(tau * diff, (tau - 1.0) * diff)


def quantile_pinball(head_out, target, weight=None):
    """Sum of pinball losses at tau=.1/.5/.9 using a QuantileHead's
    (p10, q50, p90) outputs directly as the three quantile predictions."""
    l10 = pinball_elementwise(head_out["p10"], target, 0.1)
    l50 = pinball_elementwise(head_out["q50"], target, 0.5)
    l90 = pinball_elementwise(head_out["p90"], target, 0.9)
    per_sample = l10 + l50 + l90
    if weight is not None:
        per_sample = per_sample * weight
    # Labels can be NaN (e.g. rul_efc_true for a battery that never reached
    # 80 % SoH in the data): mask them out instead of poisoning the mean.
    valid = torch.isfinite(target)
    per_sample = torch.where(valid, per_sample, torch.zeros_like(per_sample))
    n_valid = valid.sum().clamp(min=1)
    return per_sample.sum() / n_valid, per_sample


class SentinelLoss:
    def __init__(self, lambda_R=1.0, lambda_mono=1.0, lambda_cross=1.0, mono_margin=0.5):
        self.lambda_R = lambda_R
        self.lambda_mono = lambda_mono
        self.lambda_cross = lambda_cross
        self.mono_margin = mono_margin

    def __call__(self, model_out, soh_target, rul_target, weight,
                 soh50_k=None, soh50_km1=None):
        """soh_target, rul_target are in SCALED units (schema.scale_soh /
        schema.scale_rul). `soh50_k`/`soh50_km1` (SCALED, real units after
        unscale inside) are optional adjacent-cycle SoH-q50 pairs sampled
        from the same battery, for the monotonicity penalty."""
        loss_soh, _ = quantile_pinball(model_out["soh"], soh_target, weight)
        loss_rul, _ = quantile_pinball(model_out["rul"], rul_target, weight)

        cross = (torch.relu(-model_out["soh"]["raw_d_lo"]) + torch.relu(-model_out["soh"]["raw_d_hi"]) +
                 torch.relu(-model_out["rul"]["raw_d_lo"]) + torch.relu(-model_out["rul"]["raw_d_hi"]))
        loss_cross = cross.mean()

        loss_mono = torch.tensor(0.0, dtype=loss_soh.dtype, device=loss_soh.device)
        if soh50_k is not None and soh50_km1 is not None and len(soh50_k) > 0:
            # both are SCALED (SoH-60)/40 -> real points: *40 to compare
            # against the 0.5-percentage-point/cycle margin.
            delta_pts = (soh50_k - soh50_km1) * 40.0
            loss_mono = torch.relu(delta_pts - self.mono_margin).mean()

        total = (loss_soh + self.lambda_R * loss_rul +
                 self.lambda_mono * loss_mono + self.lambda_cross * loss_cross)
        return total, {
            "soh": float(loss_soh.detach()),
            "rul": float(loss_rul.detach()),
            "mono": float(loss_mono.detach()) if torch.is_tensor(loss_mono) else float(loss_mono),
            "cross": float(loss_cross.detach()),
            "total": float(total.detach()),
        }
