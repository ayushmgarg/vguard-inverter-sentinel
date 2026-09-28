/* firmware/components/sentinel_int8/include/sentinel_int8.h
 *
 * C99 int8 inference of SentinelNet (design 02 SS2.2), mirroring
 * model/int8_infer.py exactly: int8 weights/activations (symmetric,
 * zero_point=0), int32 accumulation, fixed-point (multiplier,shift)
 * requantisation between layers (TFLite's MultiplyByQuantizedMultiplier).
 *
 * Weights/scales come from model/artifacts_sim/sentinel_model_int8.h,
 * included by sentinel_int8.c -- this module does not duplicate the
 * weight data, only the arithmetic that walks it. No malloc; all buffers
 * are stack/caller-owned, sized for the fixed architecture:
 *   conv1: 14->16 (k=5,s=1)  conv2: 16->32 (k=5,s=2)  conv3: 32->32 (k=3,s=1)
 *   flatten(288)+static(6)=294 -> dense1(64) -> dense2(32) -> head_soh(3), head_rul(3)
 *
 * Host- and MCU-buildable (gcc -std=c99 -O2 -lm; ESP-IDF component.
 * See firmware/README.md for why this hand-written path exists alongside
 * (not instead of) the optional TFLM path in tflm_wrapper.
 */
#ifndef SENTINEL_INT8_H
#define SENTINEL_INT8_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SENTINEL_WINDOW_CYCLES 30
#define SENTINEL_N_DYNAMIC     14
#define SENTINEL_N_STATIC      6
#define SENTINEL_N_QUANTILE    3   /* [q50_raw, d_lo_raw, d_hi_raw] */

/* Three raw (still-scaled, i.e. "y" model-output space) quantile values per
 * head: index 0 = q50_raw, 1 = d_lo_raw (>=0 after ReLU semantics already
 * applied structurally? no -- these are the pre-combination raw outputs,
 * caller must do q50=[0], p10=q50-max([1],0), p90=q50+max([2],0), exactly
 * like model/net.py's QuantileHead and model/int8_infer.py's head_quantiles). */
typedef struct {
    float raw[SENTINEL_N_QUANTILE];
} sentinel_head_raw_t;

/* Runs the full int8 forward pass.
 * x_dyn_std:    [SENTINEL_WINDOW_CYCLES][SENTINEL_N_DYNAMIC], already
 *               standardised ((x-mean)/scale) and clipped to +/-3, exactly
 *               as model/windowing.py's apply_standardizer does.
 * x_static_std: [SENTINEL_N_STATIC], same standardisation.
 * out_soh / out_rul: dequantised raw (still-scaled) quantile outputs.
 * Returns 0 on success. No failure modes today (fixed-size static
 * buffers only) but the return code is reserved for future range checks. */
int sentinel_int8_infer(const float x_dyn_std[SENTINEL_WINDOW_CYCLES][SENTINEL_N_DYNAMIC],
                         const float x_static_std[SENTINEL_N_STATIC],
                         sentinel_head_raw_t *out_soh,
                         sentinel_head_raw_t *out_rul);

/* Golden self-test: runs sentinel_int8_infer on the fixed vector generated
 * by firmware/host/gen_golden.py (from the real exported model weights)
 * and checks the int8 intermediate/final results bit-exactly (integer
 * math is deterministic -- there is no "close enough" for this test).
 * Returns 1 on PASS, 0 on FAIL (prints nothing; caller logs/prints). */
int sentinel_int8_selftest(void);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_INT8_H */
