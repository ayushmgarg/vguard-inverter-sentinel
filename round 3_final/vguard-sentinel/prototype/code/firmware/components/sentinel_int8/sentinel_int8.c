/* firmware/components/sentinel_int8/sentinel_int8.c
 *
 * See sentinel_int8.h for the contract. This is a line-for-line C99 port
 * of model/int8_infer.py's conv1d_int8/dense_int8/rescale_int8/requantize,
 * operating on the exact weight/scale tables exported into
 * model/artifacts_sim/sentinel_model_int8.h (included below by relative
 * path -- read-only, never modified by firmware/).
 *
 * No malloc, no float in the integer path (float only for
 * standardisation input and final dequantisation, matching
 * model/int8_infer.py's own float64 dequantize_tensor step).
 */
#include "sentinel_int8.h"
#include "sentinel_int8_golden.h"

#include <math.h>
#include <stdint.h>
#include <string.h>

/* model/artifacts_sim/sentinel_model_int8.h -- the real exported weights.
 * Firmware only reads this file (CONTRACTS.md: algorithm/model artifacts
 * live outside firmware/); the include path is set by
 * components/sentinel_int8/CMakeLists.txt and host/Makefile. */
#include "sentinel_model_int8.h"

#define MANTISSA_BITS 31
#define INT8_LO (-127)
#define INT8_HI 127

/* ---- shapes, must match model/net.py SentinelNet exactly ---- */
#define C1_CIN 14
#define C1_COUT 16
#define C1_K 5
#define C1_LOUT 26   /* (30-5)/1+1 */

#define C2_CIN 16
#define C2_COUT 32
#define C2_K 5
#define C2_STRIDE 2
#define C2_LOUT 11   /* (26-5)/2+1 */

#define C3_CIN 32
#define C3_COUT 32
#define C3_K 3
#define C3_LOUT 9    /* (11-3)/1+1 */

#define FLAT_DIM (C3_COUT * C3_LOUT)          /* 288 */
#define CONCAT_DIM (FLAT_DIM + SENTINEL_N_STATIC) /* 294 */
#define D1_OUT 64
#define D2_OUT 32

/* ---- fixed-point requantisation, exactly model/int8_infer.py:requantize --- */
static int64_t requantize_i64(int64_t acc, int32_t multiplier, int32_t shift) {
    int64_t scaled = acc * (int64_t)multiplier;
    int32_t total_shift = MANTISSA_BITS - shift;
    if (total_shift >= 0) {
        int64_t rounding = (total_shift > 0) ? ((int64_t)1 << (total_shift - 1)) : 0;
        return (scaled + rounding) >> total_shift;
    } else {
        return scaled << (-total_shift);
    }
}

static int8_t clip_int8_i64(int64_t x, int relu) {
    int64_t lo = relu ? 0 : INT8_LO;
    if (x < lo) x = lo;
    if (x > INT8_HI) x = INT8_HI;
    return (int8_t)x;
}

static int8_t quantize_scalar(float x, float scale, int relu) {
    long r = lroundf(x / scale);
    int64_t lo = relu ? 0 : INT8_LO;
    if (r < lo) r = (long)lo;
    if (r > INT8_HI) r = INT8_HI;
    return (int8_t)r;
}

/* ---- conv1d: x[Cin][Lin] int8, w[Cout][Cin][K] int8, b[Cout] int32 ---- */
static void conv1d_int8(const int8_t *x, int cin, int lin,
                         const int8_t *w, const int32_t *b,
                         const int32_t *mult, const int32_t *shift,
                         int cout, int k, int stride, int relu,
                         int8_t *out /* [cout][lout] */, int lout) {
    for (int t = 0; t < lout; t++) {
        int base = t * stride;
        for (int c = 0; c < cout; c++) {
            int64_t acc = b[c];
            for (int ci = 0; ci < cin; ci++) {
                const int8_t *xrow = x + ci * lin + base;
                const int8_t *wrow = w + (size_t)c * cin * k + (size_t)ci * k;
                for (int kk = 0; kk < k; kk++) {
                    acc += (int64_t)xrow[kk] * (int64_t)wrow[kk];
                }
            }
            int64_t req = requantize_i64(acc, mult[c], shift[c]);
            out[(size_t)c * lout + t] = clip_int8_i64(req, relu);
        }
    }
}

/* ---- dense: x[Cin] int8, w[Cout][Cin] int8, b[Cout] int32 ---- */
static void dense_int8(const int8_t *x, int cin,
                        const int8_t *w, const int32_t *b,
                        const int32_t *mult, const int32_t *shift,
                        int cout, int relu, int8_t *out /* [cout] */) {
    for (int c = 0; c < cout; c++) {
        int64_t acc = b[c];
        const int8_t *wrow = w + (size_t)c * cin;
        for (int i = 0; i < cin; i++) {
            acc += (int64_t)x[i] * (int64_t)wrow[i];
        }
        int64_t req = requantize_i64(acc, mult[c], shift[c]);
        out[c] = clip_int8_i64(req, relu);
    }
}

/* ---- identity affine requantisation onto a different scale (used before
 * CONCATENATION, exactly model/int8_infer.py:rescale_int8) ---- */
static void rescale_int8(const int8_t *x, int n, float in_scale, float out_scale, int8_t *out) {
    /* multiplier/shift for in_scale/out_scale computed at runtime with the
     * same frexp-based QuantizeMultiplier algorithm int8_infer.py uses --
     * this ratio is a build-time constant in practice (fixed scales), but
     * computing it here keeps this file self-contained/host-testable
     * without a code-generation step for the two rescale ops. */
    double real_multiplier = (double)in_scale / (double)out_scale;
    int32_t q_multiplier = 0, exponent = 0;
    if (real_multiplier != 0.0) {
        int exp2;
        double mantissa = frexp(real_multiplier, &exp2);
        q_multiplier = (int32_t)lround(mantissa * (double)(1LL << MANTISSA_BITS));
        exponent = exp2;
        if (q_multiplier == (1 << MANTISSA_BITS)) {
            q_multiplier /= 2;
            exponent += 1;
        }
    }
    for (int i = 0; i < n; i++) {
        int64_t req = requantize_i64((int64_t)x[i], q_multiplier, exponent);
        out[i] = clip_int8_i64(req, 0);
    }
}

int sentinel_int8_infer(const float x_dyn_std[SENTINEL_WINDOW_CYCLES][SENTINEL_N_DYNAMIC],
                         const float x_static_std[SENTINEL_N_STATIC],
                         sentinel_head_raw_t *out_soh,
                         sentinel_head_raw_t *out_rul) {
    /* transpose (30,14) -> (14,30) to match Cin-major layout used by conv1d
     * (model/int8_infer.py: x_dyn_std.transpose(0,2,1)) */
    int8_t x_dyn_t[C1_CIN][SENTINEL_WINDOW_CYCLES];
    for (int c = 0; c < C1_CIN; c++) {
        for (int t = 0; t < SENTINEL_WINDOW_CYCLES; t++) {
            x_dyn_t[c][t] = quantize_scalar(x_dyn_std[t][c], SENTINEL_SCALE_INPUT_DYN, 0);
        }
    }
    int8_t x_static_q[SENTINEL_N_STATIC];
    for (int i = 0; i < SENTINEL_N_STATIC; i++) {
        x_static_q[i] = quantize_scalar(x_static_std[i], SENTINEL_SCALE_INPUT_STATIC, 0);
    }

    int8_t a1[C1_COUT][C1_LOUT];
    conv1d_int8(&x_dyn_t[0][0], C1_CIN, SENTINEL_WINDOW_CYCLES,
                conv1_weight, conv1_bias, conv1_out_multiplier, conv1_out_shift,
                C1_COUT, C1_K, 1, 1, &a1[0][0], C1_LOUT);

    int8_t a2[C2_COUT][C2_LOUT];
    conv1d_int8(&a1[0][0], C2_CIN, C1_LOUT,
                conv2_weight, conv2_bias, conv2_out_multiplier, conv2_out_shift,
                C2_COUT, C2_K, C2_STRIDE, 1, &a2[0][0], C2_LOUT);

    int8_t a3[C3_COUT][C3_LOUT];
    conv1d_int8(&a2[0][0], C3_CIN, C2_LOUT,
                conv3_weight, conv3_bias, conv3_out_multiplier, conv3_out_shift,
                C3_COUT, C3_K, 1, 1, &a3[0][0], C3_LOUT);

    /* flatten a3 [Cout][Lout] -> [Cout*Lout] row-major, matches numpy's
     * a3.reshape(N,-1) on an (N,Cout,Lout) array */
    int8_t flat_r[FLAT_DIM];
    rescale_int8(&a3[0][0], FLAT_DIM, SENTINEL_SCALE_A3, SENTINEL_SCALE_CONCAT, flat_r);
    int8_t static_r[SENTINEL_N_STATIC];
    rescale_int8(x_static_q, SENTINEL_N_STATIC, SENTINEL_SCALE_INPUT_STATIC, SENTINEL_SCALE_CONCAT, static_r);

    int8_t concat[CONCAT_DIM];
    memcpy(concat, flat_r, FLAT_DIM);
    memcpy(concat + FLAT_DIM, static_r, SENTINEL_N_STATIC);

    int8_t d1[D1_OUT];
    dense_int8(concat, CONCAT_DIM, dense1_weight, dense1_bias,
               dense1_out_multiplier, dense1_out_shift, D1_OUT, 1, d1);

    int8_t d2[D2_OUT];
    dense_int8(d1, D1_OUT, dense2_weight, dense2_bias,
               dense2_out_multiplier, dense2_out_shift, D2_OUT, 1, d2);

    int8_t soh_raw_i8[SENTINEL_N_QUANTILE];
    dense_int8(d2, D2_OUT, head_soh_weight, head_soh_bias,
               head_soh_out_multiplier, head_soh_out_shift, SENTINEL_N_QUANTILE, 0, soh_raw_i8);

    int8_t rul_raw_i8[SENTINEL_N_QUANTILE];
    dense_int8(d2, D2_OUT, head_rul_weight, head_rul_bias,
               head_rul_out_multiplier, head_rul_out_shift, SENTINEL_N_QUANTILE, 0, rul_raw_i8);

    for (int i = 0; i < SENTINEL_N_QUANTILE; i++) {
        out_soh->raw[i] = (float)soh_raw_i8[i] * SENTINEL_SCALE_SOH_RAW;
        out_rul->raw[i] = (float)rul_raw_i8[i] * SENTINEL_SCALE_RUL_RAW;
    }
    return 0;
}

int sentinel_int8_selftest(void) {
    sentinel_head_raw_t soh, rul;
    sentinel_int8_infer(sentinel_golden_x_dyn_std, sentinel_golden_x_static_std, &soh, &rul);

    for (int i = 0; i < SENTINEL_N_QUANTILE; i++) {
        float expect_soh = sentinel_golden_soh_raw_f[i];
        float expect_rul = sentinel_golden_rul_raw_f[i];
        /* int8 arithmetic is deterministic: golden values were dequantised
         * from the same int8 ints this C code must produce, so an exact
         * (to float rounding of the multiply) match is the right bar. */
        if (fabsf(soh.raw[i] - expect_soh) > 1e-6f) return 0;
        if (fabsf(rul.raw[i] - expect_rul) > 1e-6f) return 0;
    }
    return 1;
}
