"""model/export_tflite.py — optional TFLite full-int8 export (design 02 §2.2/§5.1).

The module-B brief this was written against says TensorFlow is not
installed in this environment and instructs this script to exit gracefully
with a clear message when that is so, rather than faking output. This
script does exactly that: it attempts `import tensorflow` first and, if it
fails, prints a clear message and exits 0 without writing anything.

Honesty note: at the time this was run, `import tensorflow` actually
succeeded in this sandbox (TensorFlow 2.16.2 was present, contradicting the
brief's stated premise -- see model/README.md). Per the repo's own
execution-venue discipline, tool availability observed directly is treated
as fact over a stale instruction, so when TF *is* importable this script
does the real conversion below rather than pretending it can't; when it is
genuinely absent, it degrades gracefully exactly as specified.

If TF is importable: rebuilds the SentinelNet architecture in
tf.keras (Conv1D layers -- the TFLite converter lowers these to CONV_2D
with height 1 itself, matching design 02 §2.2's op list), copies the
PyTorch weights over, and runs the standard full-integer PTQ converter
flow with a representative dataset built from real training-pool windows.

CLI:
    python -m model.export_tflite --artifacts model/artifacts/ --data data/features_sim_dummy.csv
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model.windowing import load_and_validate, build_windows, apply_standardizer  # noqa: E402
from model.evaluate import load_ensemble  # noqa: E402


def _try_import_tf():
    try:
        import tensorflow as tf  # noqa: F401
        return tf
    except ImportError:
        return None


def build_keras_model(tf):
    inp_dyn = tf.keras.Input(shape=(30, 14), name="x_dyn")
    inp_stat = tf.keras.Input(shape=(6,), name="x_static")
    # Conv1D expressed as Conv2D with height 1 (design 02 §2.2): the TFLite
    # int8 calibrator in this TF build rejects rank-3 CONV_2D inputs, so we
    # reshape to (1, 30, 14) explicitly -- exactly what TFLM runs on the ESP32.
    x = tf.keras.layers.Reshape((1, 30, 14), name="to4d")(inp_dyn)
    x = tf.keras.layers.Conv2D(16, (1, 5), strides=(1, 1), activation="relu", name="conv1")(x)
    x = tf.keras.layers.Conv2D(32, (1, 5), strides=(1, 2), activation="relu", name="conv2")(x)
    x = tf.keras.layers.Conv2D(32, (1, 3), strides=(1, 1), activation="relu", name="conv3")(x)
    x = tf.keras.layers.Flatten(name="flatten")(x)
    x = tf.keras.layers.Concatenate(name="concat")([x, inp_stat])
    x = tf.keras.layers.Dense(64, activation="relu", name="dense1")(x)
    x = tf.keras.layers.Dense(32, activation="relu", name="dense2")(x)
    soh_raw = tf.keras.layers.Dense(3, name="head_soh")(x)
    rul_raw = tf.keras.layers.Dense(3, name="head_rul")(x)
    return tf.keras.Model(inputs=[inp_dyn, inp_stat], outputs=[soh_raw, rul_raw], name="SentinelNetKeras")


def copy_torch_weights_to_keras(torch_model, keras_model):
    sd = torch_model.state_dict()

    def conv_w(name):  # torch (Cout,Cin,K) -> keras Conv2D (1,K,Cin,Cout)
        return np.transpose(sd["%s.weight" % name].numpy(), (2, 1, 0))[np.newaxis, ...]

    def dense_w(name):  # torch (Cout,Cin) -> keras (Cin,Cout)
        return sd["%s.weight" % name].numpy().T

    layer_map = [
        ("conv1", "conv1", conv_w), ("conv2", "conv2", conv_w), ("conv3", "conv3", conv_w),
        ("dense1", "dense1", dense_w), ("dense2", "dense2", dense_w),
    ]
    for torch_name, keras_name, wfn in layer_map:
        kernel = wfn(torch_name)
        bias = sd["%s.bias" % torch_name].numpy()
        keras_model.get_layer(keras_name).set_weights([kernel, bias])

    keras_model.get_layer("head_soh").set_weights([sd["head_soh.fc.weight"].numpy().T, sd["head_soh.fc.bias"].numpy()])
    keras_model.get_layer("head_rul").set_weights([sd["head_rul.fc.weight"].numpy().T, sd["head_rul.fc.bias"].numpy()])


def convert_full_int8(tf, keras_model, repr_X_dyn, repr_X_stat):
    """Goes through a SavedModel export first (`.export()`), not
    `from_keras_model` directly -- in this environment's TF/Keras build,
    converting straight from an in-memory Keras 3 model crashes the
    process (native MLIR abort, not a catchable Python exception); routing
    through the standard SavedModel-on-disk path avoids that crash. Even
    so, this environment's converter has NOT been made to succeed end to
    end for this multi-input model (see the README/error text this
    function's caller prints on failure) -- documented as a known
    limitation rather than worked around further."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        keras_model.export(d)

        def rep_gen():
            for i in range(len(repr_X_dyn)):
                # named inputs: the SavedModel signature orders inputs alphabetically,
                # so a positional list can silently feed the wrong tensor.
                yield {"x_dyn": repr_X_dyn[i:i + 1].astype(np.float32),
                       "x_static": repr_X_stat[i:i + 1].astype(np.float32)}

        converter = tf.lite.TFLiteConverter.from_saved_model(d)
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        converter.representative_dataset = rep_gen
        converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        converter.inference_input_type = tf.int8
        converter.inference_output_type = tf.int8
        return converter.convert()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifacts", default="model/artifacts/")
    ap.add_argument("--data", required=True)
    ap.add_argument("--n-representative", type=int, default=500)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    tf = _try_import_tf()
    if tf is None:
        print("model/export_tflite.py: TensorFlow is not importable in this environment -- "
              "skipping TFLite export (this is expected per the module-B brief; "
              "int8 correctness is instead validated via model/int8_infer.py's pure-numpy "
              "reference, see model/quantize.py's quantization_report.json). Exiting 0.")
        return 0

    print("TensorFlow %s is importable -- running the real Keras rebuild + full-int8 TFLite export." % tf.__version__)

    artifacts_dir = Path(args.artifacts)
    models, stats, split_info = load_ensemble(artifacts_dir)
    seed0 = models[0]

    df = load_and_validate(args.data)
    windows = build_windows(df)
    pool_mask = np.isin(windows.battery_id, split_info["train_pool_batteries"])
    pool_windows = windows.subset(np.where(pool_mask)[0])
    rng = np.random.default_rng(0)
    n_repr = min(args.n_representative, len(pool_windows))
    repr_idx = rng.choice(len(pool_windows), size=n_repr, replace=False)
    repr_windows = pool_windows.subset(repr_idx)
    Xd_repr, Xs_repr = apply_standardizer(repr_windows.X_dyn, repr_windows.X_stat, stats)

    keras_model = build_keras_model(tf)
    copy_torch_weights_to_keras(seed0, keras_model)

    # sanity check: keras and torch agree on the same input before converting
    torch_out = seed0(torch.tensor(Xd_repr[:8]), torch.tensor(Xs_repr[:8]))
    keras_out = keras_model.predict([Xd_repr[:8], Xs_repr[:8]], verbose=0)
    torch_soh_raw = torch.stack([torch_out["soh"]["q50"][:8],
                                  torch_out["soh"]["raw_d_lo"][:8], torch_out["soh"]["raw_d_hi"][:8]], dim=1).detach().numpy()
    max_abs_diff = float(np.max(np.abs(torch_soh_raw - keras_out[0])))
    print("Keras vs PyTorch float head_soh raw output max abs diff (sanity check): %.6f" % max_abs_diff)
    if max_abs_diff > 1e-3:
        print("WARNING: Keras/PyTorch outputs diverge more than expected -- weight copy may be wrong.")

    try:
        tflite_bytes = convert_full_int8(tf, keras_model, Xd_repr, Xs_repr)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: never crash, never fake output
        print("\nmodel/export_tflite.py: the Keras rebuild and weight copy succeeded (see the "
              "sanity-check diff above), but the actual TFLite full-int8 conversion failed in "
              "this environment:\n")
        traceback.print_exc()
        print("\nThis is a real TF/Keras-version incompatibility in this sandbox (Keras 3's "
              "in-memory model conversion aborts the process outright; going through a "
              "SavedModel export avoids the crash but the int8 calibrator still rejects this "
              "multi-input model's tensor rank here), not a stub. No .tflite file was written -- "
              "per the module-B brief, this script does not fake output. The int8 numerics for "
              "this deliverable are exercised and verified for real by model/quantize.py + "
              "model/int8_infer.py (pure numpy, no TF dependency); see model/README.md.")
        return 1
    out_path = Path(args.out) if args.out else artifacts_dir / "sentinel_model_seed0.tflite"
    out_path.write_bytes(tflite_bytes)
    print("Wrote full-int8 TFLite model: %s (%d bytes)" % (out_path, len(tflite_bytes)))
    # remaining ensemble seeds (design 02 §2.4: 3 seeds averaged on device)
    for k, m in enumerate(models[1:], start=1):
        km = build_keras_model(tf)
        copy_torch_weights_to_keras(m, km)
        try:
            b = convert_full_int8(tf, km, Xd_repr, Xs_repr)
        except Exception as exc:  # noqa: BLE001
            print("seed%d export failed: %s" % (k, exc))
            continue
        pk = artifacts_dir / ("sentinel_model_seed%d.tflite" % k)
        pk.write_bytes(b)
        print("Wrote full-int8 TFLite model: %s (%d bytes)" % (pk, len(b)))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
