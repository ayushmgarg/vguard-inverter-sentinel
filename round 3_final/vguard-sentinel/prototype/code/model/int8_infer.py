"""model/int8_infer.py — pure-numpy int8 inference reference.

Mimics TFLM/ESP-NN full-integer arithmetic: int8 weights (per-output-channel
scale) and int8 activations (per-tensor scale), int32 accumulation, and
requantisation between layers via a fixed-point (multiplier, shift) pair --
the same mechanism TFLite's `MultiplyByQuantizedMultiplier` uses, computed
here with numpy int64 arithmetic (exact for our value ranges, see
`requantize`) rather than the bit-exact saturating-rounding SIMD op ESP-NN
runs on-device. That is a documented simplification, not a different
algorithm: the layer sequence, the per-channel weight scales, and the
multiplier+shift requantisation are the real mechanism (design 02 §5.1).

All functions here take plain dicts/arrays (produced by model/quantize.py)
so this module has no torch dependency -- it is the thing that *would* run
on the MCU, standing in for a C port.
"""

from __future__ import annotations

import math

import numpy as np

MANTISSA_BITS = 31
INT8_MIN, INT8_MAX = -127, 127  # symmetric range (matches TFLite's symmetric int8 weight/activation convention)


def compute_multiplier_shift(real_multiplier):
    """real_multiplier = q_multiplier * 2^(shift - MANTISSA_BITS), q_multiplier
    in [2^(MANTISSA_BITS-1), 2^MANTISSA_BITS). Standard TFLite QuantizeMultiplier."""
    if real_multiplier == 0:
        return 0, 0
    mantissa, exponent = math.frexp(real_multiplier)  # real_multiplier = mantissa * 2**exponent, mantissa in [0.5,1)
    q_multiplier = int(round(mantissa * (1 << MANTISSA_BITS)))
    if q_multiplier == (1 << MANTISSA_BITS):
        q_multiplier //= 2
        exponent += 1
    return q_multiplier, exponent


def requantize(acc_int, multiplier, shift):
    """acc_int: int64 ndarray. Returns int64 ndarray = round(acc * real_multiplier),
    real_multiplier defined by (multiplier, shift) per compute_multiplier_shift."""
    acc = acc_int.astype(np.int64)
    scaled = acc * np.int64(multiplier)
    total_shift = MANTISSA_BITS - shift
    if total_shift >= 0:
        rounding = (1 << (total_shift - 1)) if total_shift > 0 else 0
        result = (scaled + rounding) >> total_shift
    else:
        result = scaled << (-total_shift)
    return result


def clip_int8(x, relu=False):
    lo = 0 if relu else INT8_MIN
    return np.clip(x, lo, INT8_MAX).astype(np.int32)  # kept as int32 container, values within int8 range


def quantize_tensor(x_float, scale):
    return clip_int8(np.round(x_float / scale))


def dequantize_tensor(x_int, scale):
    return x_int.astype(np.float64) * scale


def conv1d_int8(x_int8, w_int8, b_int32, in_scale, w_scale_per_out, out_scale, stride, relu):
    """x_int8: (N, Cin, Lin). w_int8: (Cout, Cin, K). b_int32: (Cout,).
    Returns int8 activations (N, Cout, Lout)."""
    N, Cin, Lin = x_int8.shape
    Cout, _, K = w_int8.shape
    Lout = (Lin - K) // stride + 1
    x64 = x_int8.astype(np.int64)
    w64 = w_int8.astype(np.int64)

    out_int8 = np.zeros((N, Cout, Lout), dtype=np.int32)
    multipliers = [compute_multiplier_shift(in_scale * w_scale_per_out[c] / out_scale) for c in range(Cout)]

    for t in range(Lout):
        patch = x64[:, :, t * stride: t * stride + K]              # (N, Cin, K)
        acc = np.einsum("nck,ock->no", patch, w64) + b_int32.astype(np.int64)  # (N, Cout)
        for c in range(Cout):
            mult, shift = multipliers[c]
            req = requantize(acc[:, c], mult, shift)
            out_int8[:, c, t] = clip_int8(req, relu=relu)
    return out_int8


def dense_int8(x_int8, w_int8, b_int32, in_scale, w_scale_per_out, out_scale, relu):
    """x_int8: (N, Cin). w_int8: (Cout, Cin). Returns int8 (N, Cout)."""
    N, Cin = x_int8.shape
    Cout = w_int8.shape[0]
    x64 = x_int8.astype(np.int64)
    w64 = w_int8.astype(np.int64)
    acc = x64 @ w64.T + b_int32.astype(np.int64)[None, :]   # (N, Cout) int64

    out = np.zeros((N, Cout), dtype=np.int32)
    for c in range(Cout):
        mult, shift = compute_multiplier_shift(in_scale * w_scale_per_out[c] / out_scale)
        out[:, c] = clip_int8(requantize(acc[:, c], mult, shift), relu=relu)
    return out


def rescale_int8(x_int8, in_scale, out_scale):
    """Identity affine requantisation used to bring two differently-scaled
    int8 tensors onto a common scale before CONCATENATION (TFLite behaviour)."""
    mult, shift = compute_multiplier_shift(in_scale / out_scale)
    return clip_int8(requantize(x_int8.astype(np.int64), mult, shift))


def run_int8_model(q, x_dyn_std, x_static_std):
    """q: the dict produced by model/quantize.py's `quantize_model`.
    x_dyn_std/x_static_std: float, already standardised to [-1,1] (same
    preprocessing as the float model -- quantisation starts at the model's
    own input, not the raw features)."""
    s = q["scales"]
    w = q["weights_int8"]
    b = q["bias_int32"]

    x = x_dyn_std.transpose(0, 2, 1)  # (N, 14, 30)
    x_int8 = quantize_tensor(x, s["input_dyn"])
    xs_int8 = quantize_tensor(x_static_std, s["input_static"])

    a1 = conv1d_int8(x_int8, w["conv1"], b["conv1"], s["input_dyn"], s["conv1_w"], s["a1"], stride=1, relu=True)
    a2 = conv1d_int8(a1, w["conv2"], b["conv2"], s["a1"], s["conv2_w"], s["a2"], stride=2, relu=True)
    a3 = conv1d_int8(a2, w["conv3"], b["conv3"], s["a2"], s["conv3_w"], s["a3"], stride=1, relu=True)

    N = a3.shape[0]
    flat = a3.reshape(N, -1)
    flat_rescaled = rescale_int8(flat, s["a3"], s["concat"])
    static_rescaled = rescale_int8(xs_int8, s["input_static"], s["concat"])
    concat = np.concatenate([flat_rescaled, static_rescaled], axis=1)

    d1 = dense_int8(concat, w["dense1"], b["dense1"], s["concat"], s["dense1_w"], s["d1"], relu=True)
    d2 = dense_int8(d1, w["dense2"], b["dense2"], s["d1"], s["dense2_w"], s["d2"], relu=True)

    soh_raw_int8 = dense_int8(d2, w["head_soh"], b["head_soh"], s["d2"], s["head_soh_w"], s["soh_raw"], relu=False)
    rul_raw_int8 = dense_int8(d2, w["head_rul"], b["head_rul"], s["d2"], s["head_rul_w"], s["rul_raw"], relu=False)

    soh_raw = dequantize_tensor(soh_raw_int8, s["soh_raw"])
    rul_raw = dequantize_tensor(rul_raw_int8, s["rul_raw"])

    def head_quantiles(raw):
        q50 = raw[:, 0]
        d_lo = np.maximum(raw[:, 1], 0.0)
        d_hi = np.maximum(raw[:, 2], 0.0)
        return {"q50": q50, "p10": q50 - d_lo, "p90": q50 + d_hi}

    return {"soh": head_quantiles(soh_raw), "rul": head_quantiles(rul_raw)}
