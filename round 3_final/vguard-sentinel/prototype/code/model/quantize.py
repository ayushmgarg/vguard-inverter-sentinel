"""model/quantize.py — full-integer int8 PTQ (design 02 §5.1), pure numpy.

1. Run the float model over a ~500-window representative set to get
   per-tensor activation ranges (symmetric, zero-point 0).
2. Per-output-channel weight scales for every Conv1d/Linear.
3. Re-quantise (multiplier, shift) tables so model/int8_infer.py can run
   the whole graph in int8/int32 arithmetic.
4. Re-conformalise on the quantised model (design 02 §5.1: "coverage shift
   <= 2% -> re-conformalise ... so coverage is restored exactly").
5. Report delta-MAE / delta-PICP float vs int8.
6. Export model/artifacts/sentinel_model_int8.h (C header) and
   model/artifacts/sentinel_model_header.json.

Only the first ensemble seed (seed0) is quantised/exported here -- the
on-device ensemble would repeat this for all 3 seeds; doing one is enough
to validate the pipeline and keep the demo run fast (documented in
model/README.md).

CLI:
    python -m model.quantize --artifacts model/artifacts/ --data data/features_sim_dummy.csv
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

import numpy as np
import torch

torch.set_num_threads(min(4, max(1, torch.get_num_threads())))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.schema import (  # noqa: E402
    unscale_soh, RUL_LN_DIV, FEATURE_SCHEMA_VERSION,
    DYNAMIC_FEATURES as DYNAMIC_COLUMNS, STATIC_FEATURES as STATIC_COLUMNS,
)
from model.windowing import load_and_validate, build_windows, apply_standardizer  # noqa: E402
from model.metrics import mae_rmse, picp_pice_mpiw, split_conformal_offset  # noqa: E402
from model.int8_infer import run_int8_model, compute_multiplier_shift  # noqa: E402
from model.evaluate import load_ensemble, apply_conformal  # noqa: E402
from model.grade import (  # noqa: E402
    HEALTHY_SOH_MIN, HEALTHY_RUL_P10_MIN_WK, HEALTHY_REENTRY_SOH_MIN,
    HEALTHY_REENTRY_RUL_P10_MIN_WK, DEGRADING_SOH_MIN, DEGRADING_RUL_P10_MIN_WK,
)

LAYER_IO = [
    ("conv1", "input_dyn", "a1"),
    ("conv2", "a1", "a2"),
    ("conv3", "a2", "a3"),
    ("dense1", "concat", "d1"),
    ("dense2", "d1", "d2"),
    ("head_soh", "d2", "soh_raw"),
    ("head_rul", "d2", "rul_raw"),
]


def manual_forward_track(model, x_dyn, x_static):
    x = x_dyn.transpose(1, 2)
    a1 = torch.relu(model.conv1(x))
    a2 = torch.relu(model.conv2(a1))
    a3 = torch.relu(model.conv3(a2))
    flat = a3.flatten(1)
    concat = torch.cat([flat, x_static], dim=1)
    d1 = torch.relu(model.dense1(concat))
    d2 = torch.relu(model.dense2(d1))
    soh_raw = model.head_soh.fc(d2)
    rul_raw = model.head_rul.fc(d2)
    return {"x": x, "a1": a1, "a2": a2, "a3": a3, "flat": flat, "x_static": x_static,
            "concat": concat, "d1": d1, "d2": d2, "soh_raw": soh_raw, "rul_raw": rul_raw}


def tensor_scale(t):
    m = float(t.detach().abs().max())
    if m < 1e-9:
        m = 1e-9
    return m / 127.0


def quantize_weight_per_channel(weight):
    w = weight.detach().numpy()
    cout = w.shape[0]
    flat = w.reshape(cout, -1)
    scale = np.max(np.abs(flat), axis=1) / 127.0
    scale = np.where(scale < 1e-9, 1e-9, scale)
    bshape = (-1,) + (1,) * (w.ndim - 1)
    w_int8 = np.clip(np.round(w / scale.reshape(bshape)), -127, 127).astype(np.int8)
    return w_int8, scale.astype(np.float64)


def quantize_bias(bias, input_scale, weight_scale):
    b = bias.detach().numpy()
    bias_scale = input_scale * weight_scale
    return np.round(b / bias_scale).astype(np.int32)


def quantize_model(model, X_dyn_std_repr, X_stat_std_repr):
    model.train(False)
    with torch.no_grad():
        Xd = torch.tensor(X_dyn_std_repr)
        Xs = torch.tensor(X_stat_std_repr)
        acts = manual_forward_track(model, Xd, Xs)

    scales = {
        "input_dyn": tensor_scale(acts["x"]), "input_static": tensor_scale(Xs),
        "a1": tensor_scale(acts["a1"]), "a2": tensor_scale(acts["a2"]), "a3": tensor_scale(acts["a3"]),
        "concat": tensor_scale(acts["concat"]), "d1": tensor_scale(acts["d1"]), "d2": tensor_scale(acts["d2"]),
        "soh_raw": tensor_scale(acts["soh_raw"]), "rul_raw": tensor_scale(acts["rul_raw"]),
    }

    weights_int8, bias_int32 = {}, {}
    layer_params = [
        ("conv1", model.conv1, "input_dyn"), ("conv2", model.conv2, "a1"), ("conv3", model.conv3, "a2"),
        ("dense1", model.dense1, "concat"), ("dense2", model.dense2, "d1"),
        ("head_soh", model.head_soh.fc, "d2"), ("head_rul", model.head_rul.fc, "d2"),
    ]
    for name, layer, in_scale_key in layer_params:
        w_int8, w_scale = quantize_weight_per_channel(layer.weight)
        b_int32 = quantize_bias(layer.bias, scales[in_scale_key], w_scale)
        weights_int8[name] = w_int8
        bias_int32[name] = b_int32
        scales[name + "_w"] = w_scale

    return {"scales": scales, "weights_int8": weights_int8, "bias_int32": bias_int32}


def int8_predict_real(q, X_dyn_std, X_stat_std):
    out = run_int8_model(q, X_dyn_std, X_stat_std)
    return {
        "soh_p10": unscale_soh(out["soh"]["p10"]), "soh_q50": unscale_soh(out["soh"]["q50"]),
        "soh_p90": unscale_soh(out["soh"]["p90"]),
        "rul_ln_p10": out["rul"]["p10"] * RUL_LN_DIV, "rul_ln_q50": out["rul"]["q50"] * RUL_LN_DIV,
        "rul_ln_p90": out["rul"]["p90"] * RUL_LN_DIV,
    }


def fit_conformal_int8(q, stats, calib_windows):
    Xd, Xs = apply_standardizer(calib_windows.X_dyn, calib_windows.X_stat, stats)
    real = int8_predict_real(q, Xd, Xs)
    soh_true = calib_windows.soh_true
    rul_ln_true = np.log1p(calib_windows.rul_true)
    c_lo_soh, c_hi_soh = split_conformal_offset(real["soh_p10"], real["soh_p90"], soh_true)
    c_lo_rul, c_hi_rul = split_conformal_offset(real["rul_ln_p10"], real["rul_ln_p90"], rul_ln_true)
    offsets = {"c_lo_soh": c_lo_soh, "c_hi_soh": c_hi_soh, "c_lo_rul": c_lo_rul, "c_hi_rul": c_hi_rul}
    return offsets, real


def evaluate_soh_mae_picp(soh_true, pred_after):
    mae, _ = mae_rmse(pred_after["soh_q50"], soh_true)
    picp, pice, mpiw = picp_pice_mpiw(soh_true, pred_after["soh_p10"], pred_after["soh_p90"], 0.80)
    return mae, picp, pice, mpiw


# --------------------------------------------------------------------------- #
# C header export
# --------------------------------------------------------------------------- #

def _c_array(name, ctype, values, per_line=20):
    flat = np.asarray(values).flatten().tolist()
    body = ", ".join(str(int(v)) for v in flat)
    wrapped = "\n".join(textwrap.wrap(body, width=100))
    return "static const %s %s[%d] = {\n%s\n};\n" % (ctype, name, len(flat), wrapped)


def export_c_header(q, path, feature_schema_version=FEATURE_SCHEMA_VERSION):
    lines = [
        "/* AUTO-GENERATED by model/quantize.py -- do not hand-edit.",
        " * Full-integer int8 SentinelNet, design 02 SS2.2/SS5.1.",
        " * feature_schema_version=%d must match features/schema.py before loading (design 02 SS5.4)."
        % feature_schema_version,
        " */",
        "#ifndef SENTINEL_MODEL_INT8_H",
        "#define SENTINEL_MODEL_INT8_H",
        "",
        "#include <stdint.h>",
        "",
        "#define SENTINEL_FEATURE_SCHEMA_VERSION %d" % feature_schema_version,
        "",
    ]
    s = q["scales"]
    w = q["weights_int8"]
    b = q["bias_int32"]

    for name, in_key, out_key in LAYER_IO:
        lines.append("/* -- %s: in=%s (scale=%.8g) out=%s (scale=%.8g) -- */" %
                      (name, in_key, s[in_key], out_key, s[out_key]))
        lines.append(_c_array("%s_weight" % name, "int8_t", w[name]))
        lines.append(_c_array("%s_bias" % name, "int32_t", b[name]))
        multipliers, shifts = [], []
        for c in range(len(s[name + "_w"])):
            mult, shift = compute_multiplier_shift(s[in_key] * s[name + "_w"][c] / s[out_key])
            multipliers.append(mult)
            shifts.append(shift)
        lines.append(_c_array("%s_out_multiplier" % name, "int32_t", multipliers))
        lines.append(_c_array("%s_out_shift" % name, "int32_t", shifts))
        lines.append("")

    lines.append("/* activation/input scales (symmetric int8, zero_point=0) */")
    for key in ("input_dyn", "input_static", "a1", "a2", "a3", "concat", "d1", "d2", "soh_raw", "rul_raw"):
        lines.append("#define SENTINEL_SCALE_%s %.10ff" % (key.upper(), s[key]))

    lines.append("")
    lines.append("#endif /* SENTINEL_MODEL_INT8_H */")
    Path(path).write_text("\n".join(lines))


def export_json_header(mean_scale_stats, conformal_offsets_int8, out_path,
                        feature_schema_version=FEATURE_SCHEMA_VERSION):
    header = {
        "feature_schema_version": feature_schema_version,
        "dynamic_columns": DYNAMIC_COLUMNS,
        "static_columns": STATIC_COLUMNS,
        "mean_scale": mean_scale_stats,
        "conformal_offsets": conformal_offsets_int8,
        "grade_thresholds": {
            "healthy_soh_min": HEALTHY_SOH_MIN, "healthy_rul_p10_min_weeks": HEALTHY_RUL_P10_MIN_WK,
            "healthy_reentry_soh_min": HEALTHY_REENTRY_SOH_MIN,
            "healthy_reentry_rul_p10_min_weeks": HEALTHY_REENTRY_RUL_P10_MIN_WK,
            "degrading_soh_min": DEGRADING_SOH_MIN, "degrading_rul_p10_min_weeks": DEGRADING_RUL_P10_MIN_WK,
        },
    }
    with open(out_path, "w") as f:
        json.dump(header, f, indent=2)
    return header


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifacts", default="model/artifacts/")
    ap.add_argument("--data", required=True)
    ap.add_argument("--n-representative", type=int, default=500)
    args = ap.parse_args()

    artifacts_dir = Path(args.artifacts)
    models, stats, split_info = load_ensemble(artifacts_dir)
    seed0 = models[0]

    df = load_and_validate(args.data)
    windows = build_windows(df)
    calib_mask = np.isin(windows.battery_id, split_info["calibration_batteries"])
    calib_windows = windows.subset(np.where(calib_mask)[0])
    pool_mask = np.isin(windows.battery_id, split_info["train_pool_batteries"])
    pool_windows = windows.subset(np.where(pool_mask)[0])

    rng = np.random.default_rng(0)
    n_repr = min(args.n_representative, len(pool_windows))
    repr_idx = rng.choice(len(pool_windows), size=n_repr, replace=False)
    repr_windows = pool_windows.subset(repr_idx)
    Xd_repr, Xs_repr = apply_standardizer(repr_windows.X_dyn, repr_windows.X_stat, stats)
    print("Quantising seed0 on %d representative windows (healthy->near-EoL span: SoH %.1f-%.1f%%)" %
          (n_repr, repr_windows.soh_true.min(), repr_windows.soh_true.max()))

    q = quantize_model(seed0, Xd_repr, Xs_repr)

    # -- float (seed0 only, for a fair single-model comparison) on calib set --
    from model.evaluate import fit_conformal as fit_conformal_float, raw_to_real  # local import, avoids cycle at module load
    offsets_float, raw_float, real_float = fit_conformal_float([seed0], stats, calib_windows)
    pred_float_after = apply_conformal(real_float, offsets_float)
    mae_f, picp_f, pice_f, mpiw_f = evaluate_soh_mae_picp(calib_windows.soh_true, pred_float_after)

    # -- int8, re-conformalised on its own quantised predictions (design 02 SS5.1) --
    offsets_int8, real_int8 = fit_conformal_int8(q, stats, calib_windows)
    pred_int8_after = apply_conformal(real_int8, offsets_int8)
    mae_i, picp_i, pice_i, mpiw_i = evaluate_soh_mae_picp(calib_windows.soh_true, pred_int8_after)

    delta_mae = mae_i - mae_f
    delta_picp = picp_i - picp_f

    report = {
        "n_representative": n_repr,
        "float_seed0": {"soh_mae_pt": mae_f, "picp_80": picp_f, "pice_80_pt": pice_f, "mpiw_80_pt": mpiw_f,
                         "conformal_offsets": offsets_float},
        "int8_seed0": {"soh_mae_pt": mae_i, "picp_80": picp_i, "pice_80_pt": pice_i, "mpiw_80_pt": mpiw_i,
                        "conformal_offsets": offsets_int8},
        "delta_mae_pt": delta_mae, "delta_picp_80": delta_picp,
        "target": "design 02 SS5.1: expected SoH MAE +0.1-0.3pt, coverage shift <=2% before re-conformalising",
    }
    with open(artifacts_dir / "quantization_report.json", "w") as f:
        json.dump(report, f, indent=2)

    export_c_header(q, artifacts_dir / "sentinel_model_int8.h")
    export_json_header(stats, offsets_int8, artifacts_dir / "sentinel_model_header.json")
    # the on-device ensemble needs every seed: export seed1..N as separate headers
    for k, m in enumerate(models[1:], start=1):
        qk = quantize_model(m, Xd_repr, Xs_repr)
        export_c_header(qk, artifacts_dir / ("sentinel_model_int8_seed%d.h" % k))
    report["n_seeds_exported"] = len(models)

    print(json.dumps(report, indent=2))
    print("Wrote sentinel_model_int8.h, sentinel_model_header.json, quantization_report.json to %s" % artifacts_dir)


if __name__ == "__main__":
    main()
