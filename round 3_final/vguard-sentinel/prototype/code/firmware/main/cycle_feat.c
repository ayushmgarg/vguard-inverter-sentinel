/* firmware/main/cycle_feat.c -- see cycle_feat.h for the honesty note on scope. */
#include "cycle_feat.h"

#include <math.h>

/* Fixed neutral placeholders for the channels this simplified extractor does
 * not compute (see cycle_feat.h doc comment). Chosen to be the physically
 * "no information" value for each channel's semantics (ratio=1 == baseline,
 * shift=0 == no shift, frac=0 == none observed, stale=1 == always stale),
 * not a copy of the training-set mean (which would misleadingly imply these
 * were measured and happened to land near the dataset average). */
#define PLACEHOLDER_SAG_RATIO   1.0f
#define PLACEHOLDER_CA_RATIO    1.0f
#define PLACEHOLDER_CV_FRAC     0.0f
#define PLACEHOLDER_IC_PEAK_H   1.0f
#define PLACEHOLDER_IC_PEAK_V   0.0f
#define PLACEHOLDER_ICA_STALE   1.0f
#define PLACEHOLDER_OCV_ERR     0.0f
#define PLACEHOLDER_LN_TFULL    0.35f  /* ln(1 + 30min/24h): typical CV-dwell-based
                                           proxy, not a measured time-to-full */
#define PLACEHOLDER_ST_TOTAL_PER_DAY 1.0f
#define PLACEHOLDER_ST_FLOAT         0.0f

#define STALE_MAX 30.0f
#define LOW_SOC_THRESH 0.30f
#define DOD50_THRESH 0.50f
#define SECONDS_PER_YEAR (365.25 * 86400.0)

void cycle_feat_init(cycle_feat_ctx_t *c, float q_rated_ah, float dt_s) {
    c->ah_out_cycle = 0.0f;
    c->ah_in_cycle = 0.0f;
    c->t_sum = 0.0;
    c->t_n = 0;
    c->eta_stale_count = 0;
    c->eta_c_last = 1.0f;      /* neutral prior: perfect coulombic efficiency */
    c->eta_c_have_ever = 0;
    c->life_total_samples = 0;
    c->life_low_soc_samples = 0;
    c->life_cycles_total = 0;
    c->life_cycles_dod50 = 0;
    c->efc_cumulative = 0.0f;
    c->q_rated_ah = q_rated_ah;
    c->dt_s = dt_s;
}

void cycle_feat_on_sample(cycle_feat_ctx_t *c, float I_discharge_pos, float T, float soc_estimate) {
    if (I_discharge_pos >= 0.0f) c->ah_out_cycle += I_discharge_pos * c->dt_s / 3600.0f;
    else c->ah_in_cycle += -I_discharge_pos * c->dt_s / 3600.0f;

    c->t_sum += T;
    c->t_n++;

    c->life_total_samples++;
    if (soc_estimate < LOW_SOC_THRESH) c->life_low_soc_samples++;
}

float cycle_feat_on_cycle_close(cycle_feat_ctx_t *c, const ekf_t *e,
                                 float out_dyn[CYCLE_FEAT_N_DYNAMIC],
                                 float out_static[CYCLE_FEAT_N_STATIC]) {
    float dod = c->ah_out_cycle / c->q_rated_ah;
    if (dod < 0.0f) dod = 0.0f;

    /* q_dis_norm: design 02 §1.3 normalises the EKF's capacity-measured figure
     * by rated capacity; ekf_t doesn't expose capacity_measured_ah/valid via the
     * frozen CONTRACTS §6 API, so our own Ah accumulator (already used for dod)
     * is the only signal this module has access to without widening the API --
     * both channels therefore carry the same value here, a documented
     * simplification (see cycle_feat.h doc comment). */
    float q_dis_norm = dod;

    float eta_c;
    if (c->ah_in_cycle > 0.0f) {
        eta_c = c->ah_out_cycle / c->ah_in_cycle;
        c->eta_c_last = eta_c;
        c->eta_c_have_ever = 1;
        c->eta_stale_count = 0;
    } else {
        eta_c = c->eta_c_last;
        if (c->eta_stale_count < (int)STALE_MAX) c->eta_stale_count++;
    }
    float eta_stale = c->eta_stale_count / STALE_MAX;
    if (eta_stale > 1.0f) eta_stale = 1.0f;

    float t_mean = (c->t_n > 0) ? (float)(c->t_sum / (double)c->t_n) : 0.0f;

    float r_ratio = ekf_soh_r(e);
    if (!(r_ratio > 0.0f) || isnan(r_ratio)) r_ratio = 1.0f; /* SS EKF hasn't
                                                                  observed an R0
                                                                  event yet */

    out_dyn[0] = r_ratio;
    out_dyn[1] = PLACEHOLDER_SAG_RATIO;
    out_dyn[2] = q_dis_norm;
    out_dyn[3] = dod;
    out_dyn[4] = eta_c;
    out_dyn[5] = eta_stale;
    out_dyn[6] = PLACEHOLDER_CA_RATIO;
    out_dyn[7] = PLACEHOLDER_CV_FRAC;
    out_dyn[8] = PLACEHOLDER_IC_PEAK_H;
    out_dyn[9] = PLACEHOLDER_IC_PEAK_V;
    out_dyn[10] = PLACEHOLDER_ICA_STALE;
    out_dyn[11] = t_mean;
    out_dyn[12] = PLACEHOLDER_LN_TFULL;
    out_dyn[13] = PLACEHOLDER_OCV_ERR;

    /* life-time static aggregates */
    c->life_cycles_total++;
    if (dod >= DOD50_THRESH) c->life_cycles_dod50++;
    c->efc_cumulative += dod;

    float f_dod50 = (c->life_cycles_total > 0)
        ? (float)c->life_cycles_dod50 / (float)c->life_cycles_total : 0.0f;
    float f_lowsoc = (c->life_total_samples > 0)
        ? (float)c->life_low_soc_samples / (float)c->life_total_samples : 0.0f;
    float age_years = (float)((double)c->life_total_samples * c->dt_s / SECONDS_PER_YEAR);

    out_static[0] = c->efc_cumulative;
    out_static[1] = PLACEHOLDER_ST_TOTAL_PER_DAY;
    out_static[2] = PLACEHOLDER_ST_FLOAT;
    out_static[3] = f_dod50;
    out_static[4] = f_lowsoc;
    out_static[5] = age_years;

    /* reset per-cycle accumulators (mirrors ekf_t's own ah_out_cycle/ah_in_cycle
     * reset in ekf_step's close_cycle block) */
    c->ah_out_cycle = 0.0f;
    c->ah_in_cycle = 0.0f;
    c->t_sum = 0.0;
    c->t_n = 0;

    return dod;
}
