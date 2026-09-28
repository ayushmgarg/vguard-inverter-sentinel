/* firmware/main/cycle_feat.h -- simplified per-cycle feature extractor.
 *
 * IMPORTANT / honesty note (see firmware/README.md "honest limits" and
 * CONTRACTS.md §7): this is a *simplified* on-device port, not a bit-exact
 * port of features/cycle_features.py (581 lines of Python implementing the
 * full state machine: CC/CV/FLOAT/DISCHARGE tracking, incremental
 * capacity/ICA peak extraction, rest-OCV SoC error, etc). Reproducing that
 * exactly in C was out of scope for this firmware-glue pass. Instead:
 *
 *   - 10 of the 14 dynamic channels and all but 2 of the 6 static channels
 *     ARE genuinely computed on-device from real EKF/sample signals:
 *     r_ratio (ekf_soh_r), q_dis_norm/dod (ekf capacity_measured_ah or a
 *     locally-tracked Ah accumulator), eta_c/eta_stale (ekf eta_measured),
 *     t_mean (mean battery T over the cycle), efc/age_years/f_dod50/f_lowsoc
 *     (running life-time counters).
 *   - The remaining channels (sag_ratio, ca_ratio, cv_frac, ic_peak_h,
 *     ic_peak_v, ica_stale, ocv_err, ln_tfull, st_total_per_day, st_float)
 *     have no cheap on-device proxy in this pass and are held at documented
 *     fixed neutral constants (see cycle_feat.c CYCLE_FEAT_PLACEHOLDER_*).
 *     A real port would compute these per design 02 §1.1/§1.7/§1.8/§1.9.
 *
 * Cycle boundary = the EKF's own full-charge lock event (ekf_t.last_anchor
 * == 1 after ekf_step, design 01 §5a/§7) -- the same "close_cycle" event
 * features/cycle_features.py's tail-current FULL_CHARGE detector targets,
 * just read off the EKF instead of independently re-detected.
 *
 * C99, no malloc, no ESP-IDF/FreeRTOS dependency -- host- and MCU-buildable.
 */
#ifndef SENTINEL_CYCLE_FEAT_H
#define SENTINEL_CYCLE_FEAT_H

#include "ekf.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CYCLE_FEAT_N_DYNAMIC 14
#define CYCLE_FEAT_N_STATIC  6

typedef struct {
    /* per-cycle accumulators (reset at each cycle close) */
    float  ah_out_cycle, ah_in_cycle;
    double t_sum;
    long   t_n;
    int    eta_stale_count;
    float  eta_c_last;
    int    eta_c_have_ever;

    /* life-time running counters (never reset) */
    long   life_total_samples;
    long   life_low_soc_samples;   /* SoC < 0.3 */
    long   life_cycles_total;
    long   life_cycles_dod50;      /* cycles with dod >= 0.5 */
    float  efc_cumulative;

    float  q_rated_ah;
    float  dt_s;
} cycle_feat_ctx_t;

void cycle_feat_init(cycle_feat_ctx_t *c, float q_rated_ah, float dt_s);

/* Call once per 1 Hz sample, BEFORE ekf_step (uses I_discharge_pos, matching
 * ekf's own sign convention so the locally-tracked ah_out/ah_in accumulator
 * mirrors ekf_t's internal one exactly -- CONTRACTS §6). */
void cycle_feat_on_sample(cycle_feat_ctx_t *c, float I_discharge_pos, float T, float soc_estimate);

/* Call after ekf_step when e->last_anchor == 1 (cycle just closed). Fills
 * out_dyn[14] / out_static[6] (raw, NOT standardised -- caller applies the
 * header's mean/scale) and resets the per-cycle accumulators. Returns the
 * dod computed for this cycle (0..1+), useful for the caller's own logging. */
float cycle_feat_on_cycle_close(cycle_feat_ctx_t *c, const ekf_t *e,
                                 float out_dyn[CYCLE_FEAT_N_DYNAMIC],
                                 float out_static[CYCLE_FEAT_N_STATIC]);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_CYCLE_FEAT_H */
