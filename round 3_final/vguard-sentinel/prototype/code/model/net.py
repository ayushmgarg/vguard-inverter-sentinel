"""model/net.py — the 1-D temporal CNN, design 02 §2.2 exactly.

Input:
    x_dyn:    (B, WINDOW_LEN=30, N_DYNAMIC=14) float tensor, standardised.
    x_static: (B, N_STATIC=6) float tensor, standardised.

Architecture (design 02 §2.2 table):
    Conv1D-1: k=5, 14->16, ReLU              -> (B,16,26)   1,136 params
    Conv1D-2: k=5, 16->32, stride=2, ReLU    -> (B,32,11)   2,592 params
    Conv1D-3: k=3, 32->32, ReLU              -> (B,32,9)    3,104 params
    flatten (288) concat statics (6) -> 294
    Dense-1: 294->64, ReLU                                 18,880 params
    Dense-2: 64->32, ReLU                                   2,080 params
    Head-SoH: 32->3 [q50, d_lo, d_hi]                          99 params
    Head-RUL: 32->3 [q50, d_lo, d_hi] on ln(1+RUL_EFC)          99 params
    total ~= 27,990 (~28.0k), ~106k MACs.

Non-crossing quantiles (design 02 §2.2): each head emits q50 plus two
non-negative deltas via ReLU. P10 = q50 - d_lo, P90 = q50 + d_hi -- ordering
is structural, no sort/softplus needed.

Conv1D is exported as Conv2D with height 1 for TFLM (design 02 §2.2); this
PyTorch module uses nn.Conv1d directly since TFLM export is a separate,
optional step (model/export_tflite.py) done only if TensorFlow is present.
"""

from __future__ import annotations

import sys
from pathlib import Path

import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.schema import N_DYNAMIC, N_STATIC, WINDOW_CYCLES as WINDOW_LEN  # noqa: E402

N_QUANTILE_OUT = 3  # [q50_raw, d_lo_raw, d_hi_raw]


class QuantileHead(nn.Module):
    """32 -> 3, producing non-crossing (q10, q50, q90) via ReLU deltas."""

    def __init__(self, in_features):
        super().__init__()
        self.fc = nn.Linear(in_features, N_QUANTILE_OUT)

    def forward(self, x):
        raw = self.fc(x)                       # (B, 3): [q50_raw, dlo_raw, dhi_raw]
        q50 = raw[:, 0]
        d_lo = torch.relu(raw[:, 1])
        d_hi = torch.relu(raw[:, 2])
        p10 = q50 - d_lo
        p90 = q50 + d_hi
        # also return the pre-ReLU raw deltas so the loss can apply the
        # (structurally redundant, but spec'd) lambda_cross penalty (02 §4.1)
        return {
            "q50": q50, "p10": p10, "p90": p90,
            "d_lo": d_lo, "d_hi": d_hi,
            "raw_d_lo": raw[:, 1], "raw_d_hi": raw[:, 2],
        }


class SentinelNet(nn.Module):
    def __init__(self, n_dynamic=N_DYNAMIC, n_static=N_STATIC, window_len=WINDOW_LEN):
        super().__init__()
        self.n_dynamic = n_dynamic
        self.n_static = n_static
        self.window_len = window_len

        self.conv1 = nn.Conv1d(n_dynamic, 16, kernel_size=5, stride=1)
        self.conv2 = nn.Conv1d(16, 32, kernel_size=5, stride=2)
        self.conv3 = nn.Conv1d(32, 32, kernel_size=3, stride=1)
        self.relu = nn.ReLU()

        conv_out_len = self._conv_out_len(window_len)
        flat_dim = 32 * conv_out_len
        self.flat_dim = flat_dim
        self.dense1 = nn.Linear(flat_dim + n_static, 64)
        self.dense2 = nn.Linear(64, 32)

        self.head_soh = QuantileHead(32)
        self.head_rul = QuantileHead(32)

    @staticmethod
    def _conv_out_len(window_len):
        l1 = window_len - 5 + 1          # k=5 s=1
        l2 = (l1 - 5) // 2 + 1           # k=5 s=2
        l3 = l2 - 3 + 1                  # k=3 s=1
        return l3

    def forward(self, x_dyn, x_static):
        # x_dyn: (B, T, C) -> conv1d wants (B, C, T)
        x = x_dyn.transpose(1, 2)
        x = self.relu(self.conv1(x))
        x = self.relu(self.conv2(x))
        x = self.relu(self.conv3(x))
        x = x.flatten(1)
        x = torch.cat([x, x_static], dim=1)
        x = self.relu(self.dense1(x))
        x = self.relu(self.dense2(x))
        soh = self.head_soh(x)
        rul = self.head_rul(x)
        return {"soh": soh, "rul": rul}

    def param_count(self):
        return sum(p.numel() for p in self.parameters())

    def mac_count(self):
        """Multiply-accumulate count matching design 02 §2.2's table."""
        l1 = self.window_len - 5 + 1
        l2 = (l1 - 5) // 2 + 1
        l3 = l2 - 3 + 1
        macs = 0
        macs += (5 * self.n_dynamic) * 16 * l1        # conv1
        macs += (5 * 16) * 32 * l2                    # conv2
        macs += (3 * 32) * 32 * l3                    # conv3
        flat = 32 * l3
        macs += flat * 64                              # dense1 (bias excl.)
        macs += 64 * 32                                # dense2
        macs += 32 * 3 * 2                              # two heads
        return macs


def build_model():
    return SentinelNet()


if __name__ == "__main__":
    net = build_model()
    n_params = net.param_count()
    n_macs = net.mac_count()
    print("SentinelNet parameter count: %d (~%.1fk)" % (n_params, n_params / 1000.0))
    print("SentinelNet MAC count:       %d (~%.1fk)" % (n_macs, n_macs / 1000.0))

    xb, xs = torch.randn(4, WINDOW_LEN, N_DYNAMIC), torch.randn(4, N_STATIC)
    out = net(xb, xs)
    print("soh p10/p50/p90 shapes:", out["soh"]["p10"].shape, out["soh"]["q50"].shape, out["soh"]["p90"].shape)
    print("rul p10/p50/p90 shapes:", out["rul"]["p10"].shape, out["rul"]["q50"].shape, out["rul"]["p90"].shape)
    non_crossing = bool(torch.all(out["soh"]["p10"] <= out["soh"]["q50"]) and
                         torch.all(out["soh"]["q50"] <= out["soh"]["p90"]))
    print("non-crossing quantiles (untrained sanity check):", non_crossing)
