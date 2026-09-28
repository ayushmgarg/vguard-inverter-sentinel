/* firmware/components/tflm_wrapper/include/tflm_wrapper.h
 *
 * Optional esp-tflite-micro path for running the *actual* .tflite flatbuffer
 * (model/artifacts_sim/sentinel_model_seed0.tflite) instead of the
 * hand-written int8 port in components/sentinel_int8. Only built when
 * CONFIG_SENTINEL_USE_TFLM=y (default n). See README.md in this directory.
 */
#ifndef TFLM_WRAPPER_H
#define TFLM_WRAPPER_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Mirrors sentinel_int8.h's shapes exactly so main/ can call either backend
 * behind the same interface. */
#define TFLM_WINDOW_CYCLES 30
#define TFLM_N_DYNAMIC     14
#define TFLM_N_STATIC      6
#define TFLM_N_QUANTILE    3

typedef struct {
    float raw[TFLM_N_QUANTILE];
} tflm_head_raw_t;

/* Loads the flatbuffer from `model_data` (mapped from the model_a/model_b
 * flash partition, design 04 §4 step 3), builds a MicroMutableOpResolver
 * registering exactly RESHAPE, EXPAND_DIMS, CONV_2D, FULLY_CONNECTED,
 * CONCATENATION, RELU (the op set model/net.py's graph lowers to, per
 * design 02 §2.2), and calls AllocateTensors() against a static 16 KB
 * arena. Returns 0 on success. */
int tflm_wrapper_init(const uint8_t *model_data, uint32_t model_len);

/* Runs one inference. Requires a prior successful tflm_wrapper_init(). */
int tflm_wrapper_infer(const float x_dyn_std[TFLM_WINDOW_CYCLES][TFLM_N_DYNAMIC],
                        const float x_static_std[TFLM_N_STATIC],
                        tflm_head_raw_t *out_soh, tflm_head_raw_t *out_rul);

/* Golden self-test against the same vector sentinel_int8_selftest() uses
 * (firmware/host/gen_golden.py), run once after AllocateTensors() per
 * design 04 §4 step 3 ("A golden self-test runs a built-in window and
 * compares outputs to expected values; failure -> fall back to the other
 * slot"). Returns 1 PASS / 0 FAIL. */
int tflm_wrapper_selftest(void);

#ifdef __cplusplus
}
#endif

#endif /* TFLM_WRAPPER_H */
