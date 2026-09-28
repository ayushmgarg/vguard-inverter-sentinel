#!/usr/bin/env python3
"""firmware/tools/make_golden.py -- generate the golden int8 self-test vector
embedded in components/sentinel_int8/sentinel_int8_golden.h.

Parses model/artifacts_sim/sentinel_model_int8.h (the *actual* shipped
weights) back into numpy arrays, builds a deterministic synthetic 30x14 +
6-static input, and runs it through the real model/int8_infer.py reference
pipeline (the same module model/quantize.py used to prove the exported
header is correct). The resulting int8 intermediate/ final values are the
ground truth the C port (sentinel_int8.c) must reproduce bit-exactly --
int8 arithmetic with fixed-point (multiplier,shift) requantisation is
deterministic integer math, so an exact int8 match is the right bar (not a
float tolerance).

Not part of the build; run once by hand (or by tests/test_firmware_host.py)
to regenerate the golden header if the model artifacts ever change:
    python3 firmware/tools/make_golden.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from model.int8_infer import run_int8_model  # noqa: E402

ARTIFACTS = ROOT / "model" / "artifacts_sim"
HEADER_C = ARTIFACTS / "sentinel_model_int8.h"
HEADER_JSON = ARTIFACTS / "sentinel_model_header.json"
OUT = Path(__file__).resolve().parents[1] / "components" / "sentinel_int8" / "include" / "sentinel_int8_golden.h"

LAYERS = {
    "conv1": {"cout": 16, "cin": 14, "k": 5},
    "conv2": {"cout": 32, "cin": 16, "k": 5},
    "conv3": {"cout": 32, "cin": 32, "k": 3},
    "dense1": {"cout": 64, "cin": 294},
    "dense2": {"cout": 32, "cin": 64},
    "head_soh": {"cout": 3, "cin": 32},
    "head_rul": {"cout": 3, "cin": 32},
}


def _parse_array(text, name):
    m = re.search(r"static const \w+_t %s\[\d+\] = \{(.*?)\};" % re.escape(name), text, re.S)
    if not m:
        raise ValueError("array %s not found" % name)
    nums = [int(x) for x in re.split(r"[,\s]+", m.group(1).strip()) if x]
    return np.array(nums)


def load_q():
    text = HEADER_C.read_text()
    weights, biases, mults, shifts = {}, {}, {}, {}
    for layer, shape in LAYERS.items():
        w = _parse_array(text, "%s_weight" % layer)
        if "k" in shape:
            w = w.reshape(shape["cout"], shape["cin"], shape["k"])
        else:
            w = w.reshape(shape["cout"], shape["cin"])
        weights[layer] = w.astype(np.int8)
        biases[layer] = _parse_array(text, "%s_bias" % layer).astype(np.int32)
        mults[layer] = _parse_array(text, "%s_out_multiplier" % layer).astype(np.int32)
        shifts[layer] = _parse_array(text, "%s_out_shift" % layer).astype(np.int32)

    def scale(name):
        m = re.search(r"#define SENTINEL_SCALE_%s ([0-9.eE+-]+)f" % name, text)
        return float(m.group(1))

    scales = {
        "input_dyn": scale("INPUT_DYN"), "input_static": scale("INPUT_STATIC"),
        "a1": scale("A1"), "a2": scale("A2"), "a3": scale("A3"), "concat": scale("CONCAT"),
        "d1": scale("D1"), "d2": scale("D2"), "soh_raw": scale("SOH_RAW"), "rul_raw": scale("RUL_RAW"),
    }
    # int8_infer expects per-layer weight scale vectors too, but conv/dense
    # here use a fixed (multiplier,shift) pair per output channel that was
    # already folded from (in_scale*w_scale/out_scale) -- run_int8_model
    # recomputes multiplier/shift itself from scales, so we monkeypatch a
    # thin variant that consumes the *exported* multiplier/shift directly
    # (bit-exact with what the C port reads) instead of recomputing them.
    return weights, biases, mults, shifts, scales


def run_with_exported_multipliers(weights, biases, mults, shifts, scales, x_dyn_std, x_static_std):
    """Re-implements model.int8_infer.run_int8_model's control flow but uses
    the *exported* multiplier/shift tables verbatim (what the C port reads)
    rather than recomputing them from scale ratios -- this is the exact
    computation sentinel_int8.c performs."""
    from model.int8_infer import quantize_tensor, requantize, clip_int8, dequantize_tensor

    def conv1d(x_int8, layer, in_scale, out_scale, stride, relu):
        w = weights[layer]
        b = biases[layer]
        Cout, Cin, K = w.shape
        N, _, Lin = x_int8.shape
        Lout = (Lin - K) // stride + 1
        x64 = x_int8.astype(np.int64)
        w64 = w.astype(np.int64)
        out = np.zeros((N, Cout, Lout), dtype=np.int32)
        for t in range(Lout):
            patch = x64[:, :, t * stride: t * stride + K]
            acc = np.einsum("nck,ock->no", patch, w64) + b.astype(np.int64)
            for c in range(Cout):
                req = requantize(acc[:, c], mults[layer][c], shifts[layer][c])
                out[:, c, t] = clip_int8(req, relu=relu)
        return out

    def dense(x_int8, layer, relu):
        w = weights[layer]
        b = biases[layer]
        Cout = w.shape[0]
        x64 = x_int8.astype(np.int64)
        w64 = w.astype(np.int64)
        acc = x64 @ w64.T + b.astype(np.int64)[None, :]
        out = np.zeros((x_int8.shape[0], Cout), dtype=np.int32)
        for c in range(Cout):
            req = requantize(acc[:, c], mults[layer][c], shifts[layer][c])
            out[:, c] = clip_int8(req, relu=relu)
        return out

    x = x_dyn_std.transpose(0, 2, 1)
    x_int8 = quantize_tensor(x, scales["input_dyn"])
    xs_int8 = quantize_tensor(x_static_std, scales["input_static"])

    a1 = conv1d(x_int8, "conv1", scales["input_dyn"], scales["a1"], 1, True)
    a2 = conv1d(a1, "conv2", scales["a1"], scales["a2"], 2, True)
    a3 = conv1d(a2, "conv3", scales["a2"], scales["a3"], 1, True)

    N = a3.shape[0]
    flat = a3.reshape(N, -1)
    # rescale flat(a3 scale) and static(input_static scale) onto concat scale
    from model.int8_infer import compute_multiplier_shift
    m, s = compute_multiplier_shift(scales["a3"] / scales["concat"])
    flat_r = clip_int8(requantize(flat.astype(np.int64), m, s))
    m, s = compute_multiplier_shift(scales["input_static"] / scales["concat"])
    static_r = clip_int8(requantize(xs_int8.astype(np.int64), m, s))
    concat = np.concatenate([flat_r, static_r], axis=1)

    d1 = dense(concat, "dense1", True)
    d2 = dense(d1, "dense2", True)
    soh_raw_int8 = dense(d2, "head_soh", False)
    rul_raw_int8 = dense(d2, "head_rul", False)

    soh_raw = dequantize_tensor(soh_raw_int8, scales["soh_raw"])
    rul_raw = dequantize_tensor(rul_raw_int8, scales["rul_raw"])
    return {
        "x_int8": x_int8, "xs_int8": xs_int8, "a1": a1, "a2": a2, "a3": a3,
        "concat": concat, "d1": d1, "d2": d2,
        "soh_raw_int8": soh_raw_int8, "rul_raw_int8": rul_raw_int8,
        "soh_raw": soh_raw, "rul_raw": rul_raw,
    }


def main():
    weights, biases, mults, shifts, scales = load_q()
    hdr = json.loads(HEADER_JSON.read_text())
    mean_dyn = np.array(hdr["mean_scale"]["mean_dyn"])
    scale_dyn = np.array(hdr["mean_scale"]["scale_dyn"])
    mean_stat = np.array(hdr["mean_scale"]["mean_stat"])
    scale_stat = np.array(hdr["mean_scale"]["scale_stat"])

    rng = np.random.RandomState(20260922)  # fixed seed: reproducible golden vector
    # deterministic synthetic *raw* feature window, spread across a
    # realistic-ish range so every weight lane gets exercised (not all-zero)
    x_dyn_raw = mean_dyn[None, :] + scale_dyn[None, :] * np.sin(
        np.arange(30)[:, None] * 0.37 + np.arange(14)[None, :] * 0.91)
    x_static_raw = mean_stat + scale_stat * np.array([0.4, -0.6, 0.2, 0.9, -0.3, 0.1])

    x_dyn_std = np.clip((x_dyn_raw - mean_dyn) / scale_dyn, -3, 3)[None, :, :].astype(np.float32)
    x_static_std = np.clip((x_static_raw - mean_stat) / scale_stat, -3, 3)[None, :].astype(np.float32)

    out = run_with_exported_multipliers(weights, biases, mults, shifts, scales, x_dyn_std, x_static_std)

    soh_raw = out["soh_raw"][0]
    rul_raw = out["rul_raw"][0]

    lines = []
    lines.append("/* AUTO-GENERATED by firmware/tools/make_golden.py -- do not hand-edit. */")
    lines.append("#ifndef SENTINEL_INT8_GOLDEN_H")
    lines.append("#define SENTINEL_INT8_GOLDEN_H")
    lines.append("")
    lines.append("#include <stdint.h>")
    lines.append("")
    lines.append("#define SENTINEL_GOLDEN_WINDOW 30")
    lines.append("#define SENTINEL_GOLDEN_DYN 14")
    lines.append("#define SENTINEL_GOLDEN_STATIC 6")
    lines.append("")

    def emit_2d(name, arr):
        lines.append("static const float %s[%d][%d] = {" % (name, arr.shape[0], arr.shape[1]))
        for row in arr:
            lines.append("  {" + ", ".join("%.9ff" % v for v in row) + "},")
        lines.append("};")

    def emit_1d(name, arr, cast="float", fmt="%.9ff"):
        lines.append("static const %s %s[%d] = {" % (cast, name, len(arr)))
        lines.append("  " + ", ".join(fmt % v for v in arr) + "")
        lines.append("};")

    emit_2d("sentinel_golden_x_dyn_std", x_dyn_std[0])
    emit_1d("sentinel_golden_x_static_std", x_static_std[0])
    lines.append("")
    emit_1d("sentinel_golden_soh_raw_int8", out["soh_raw_int8"][0].astype(np.int32), cast="int32_t", fmt="%d")
    emit_1d("sentinel_golden_rul_raw_int8", out["rul_raw_int8"][0].astype(np.int32), cast="int32_t", fmt="%d")
    emit_1d("sentinel_golden_soh_raw_f", soh_raw, fmt="%.9ff")
    emit_1d("sentinel_golden_rul_raw_f", rul_raw, fmt="%.9ff")
    lines.append("")
    lines.append("#endif /* SENTINEL_INT8_GOLDEN_H */")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines))
    print("wrote", OUT)
    print("soh_raw (q50,d_lo,d_hi) =", soh_raw)
    print("rul_raw (q50,d_lo,d_hi) =", rul_raw)
    print("soh_raw_int8 =", out["soh_raw_int8"][0], " rul_raw_int8 =", out["rul_raw_int8"][0])


if __name__ == "__main__":
    main()
