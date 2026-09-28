/* firmware/components/tflm_wrapper/tflm_wrapper.cpp
 *
 * esp-tflite-micro glue: loads sentinel_model_seed0.tflite, registers the
 * minimal MicroMutableOpResolver, runs Invoke(). Entirely behind
 * CONFIG_SENTINEL_USE_TFLM (off by default -- see README.md in this
 * directory: this file has never been compiled or linked in this
 * environment because esp-tflite-micro and ESP-IDF are not installed
 * here; it is written against the esp-tflite-micro v1.x API surface as
 * documented upstream, but has NOT been build-verified).
 *
 * The op list below is exactly design 02 §2.2's lowering of SentinelNet:
 * Conv1D is exported as Conv2D with height 1 (model/export_tflite.py),
 * flatten/concat use RESHAPE + EXPAND_DIMS + CONCATENATION, and every
 * activation is RELU. FULLY_CONNECTED covers dense1/dense2/head_soh/head_rul.
 */
#ifdef CONFIG_SENTINEL_USE_TFLM

#include "tflm_wrapper.h"

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_log.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include "sentinel_int8_golden.h"

#include <cmath>
#include <cstring>

namespace {

/* design 04 §3: "TFLM arena 16 KB + interpreter 4 KB" -- the arena below is
 * the 16 KB figure; the interpreter object itself is stack/static, not
 * counted against this buffer. */
constexpr int kArenaSize = 16 * 1024;
alignas(16) uint8_t g_arena[kArenaSize];

/* RESHAPE, EXPAND_DIMS, CONV_2D, FULLY_CONNECTED, CONCATENATION, RELU --
 * exactly the six ops design 04 §4 step 3 specifies, nothing more (keeps
 * the resolver's flash footprint and the attack surface minimal). */
tflite::MicroMutableOpResolver<6> g_resolver;

const tflite::Model *g_model = nullptr;
tflite::MicroInterpreter *g_interpreter = nullptr;
bool g_ready = false;

} // namespace

extern "C" int tflm_wrapper_init(const uint8_t *model_data, uint32_t model_len) {
    (void)model_len; /* the flatbuffer is self-describing; length is only used by the
                         caller's CRC/signature check before this function is called
                         (design 04 §4 step 3, done in main/model_loader before init) */
    g_model = tflite::GetModel(model_data);
    if (g_model->version() != TFLITE_SCHEMA_VERSION) {
        return -1;
    }

    if (g_resolver.AddReshape() != kTfLiteOk) return -2;
    if (g_resolver.AddExpandDims() != kTfLiteOk) return -2;
    if (g_resolver.AddConv2D() != kTfLiteOk) return -2;
    if (g_resolver.AddFullyConnected() != kTfLiteOk) return -2;
    if (g_resolver.AddConcatenation() != kTfLiteOk) return -2;
    if (g_resolver.AddRelu() != kTfLiteOk) return -2;

    static tflite::MicroInterpreter static_interpreter(
        g_model, g_resolver, g_arena, kArenaSize);
    g_interpreter = &static_interpreter;

    if (g_interpreter->AllocateTensors() != kTfLiteOk) {
        return -3;
    }
    g_ready = true;
    return 0;
}

extern "C" int tflm_wrapper_infer(const float x_dyn_std[TFLM_WINDOW_CYCLES][TFLM_N_DYNAMIC],
                                   const float x_static_std[TFLM_N_STATIC],
                                   tflm_head_raw_t *out_soh, tflm_head_raw_t *out_rul) {
    if (!g_ready) return -1;

    TfLiteTensor *in_dyn = g_interpreter->input(0);
    TfLiteTensor *in_static = g_interpreter->input(1);

    /* Quantise into the input tensors' own int8 scale/zero_point -- this
     * mirrors sentinel_int8.c's quantize_scalar but reads the scale out of
     * the flatbuffer instead of the exported #define, so this path is
     * correct even if a future model export changes scales without
     * regenerating sentinel_model_int8.h. */
    const float dyn_scale = in_dyn->params.scale;
    const int dyn_zp = in_dyn->params.zero_point;
    for (int t = 0; t < TFLM_WINDOW_CYCLES; t++) {
        for (int c = 0; c < TFLM_N_DYNAMIC; c++) {
            long q = lroundf(x_dyn_std[t][c] / dyn_scale) + dyn_zp;
            if (q < -128) q = -128;
            if (q > 127) q = 127;
            in_dyn->data.int8[t * TFLM_N_DYNAMIC + c] = (int8_t)q;
        }
    }
    const float stat_scale = in_static->params.scale;
    const int stat_zp = in_static->params.zero_point;
    for (int i = 0; i < TFLM_N_STATIC; i++) {
        long q = lroundf(x_static_std[i] / stat_scale) + stat_zp;
        if (q < -128) q = -128;
        if (q > 127) q = 127;
        in_static->data.int8[i] = (int8_t)q;
    }

    if (g_interpreter->Invoke() != kTfLiteOk) {
        return -2;
    }

    TfLiteTensor *out_soh_t = g_interpreter->output(0);
    TfLiteTensor *out_rul_t = g_interpreter->output(1);
    for (int i = 0; i < TFLM_N_QUANTILE; i++) {
        out_soh->raw[i] = (out_soh_t->data.int8[i] - out_soh_t->params.zero_point) * out_soh_t->params.scale;
        out_rul->raw[i] = (out_rul_t->data.int8[i] - out_rul_t->params.zero_point) * out_rul_t->params.scale;
    }
    return 0;
}

extern "C" int tflm_wrapper_selftest(void) {
    /* Golden vector shared with sentinel_int8_selftest() (see
     * firmware/host/gen_golden.py). */
    tflm_head_raw_t soh, rul;
    if (tflm_wrapper_infer(sentinel_golden_x_dyn_std, sentinel_golden_x_static_std, &soh, &rul) != 0) {
        return 0;
    }
    for (int i = 0; i < TFLM_N_QUANTILE; i++) {
        /* TFLM's actual .tflite quantisation is independently derived from
         * the float model (model/export_tflite.py), not required to be
         * bit-identical to the hand-quantised sentinel_model_int8.h -- a
         * loose tolerance is the correct bar here, unlike
         * sentinel_int8_selftest()'s exact-int8 check. */
        if (fabsf(soh.raw[i] - sentinel_golden_soh_raw_f[i]) > 0.05f) return 0;
        if (fabsf(rul.raw[i] - sentinel_golden_rul_raw_f[i]) > 0.05f) return 0;
    }
    return 1;
}

#endif /* CONFIG_SENTINEL_USE_TFLM */
