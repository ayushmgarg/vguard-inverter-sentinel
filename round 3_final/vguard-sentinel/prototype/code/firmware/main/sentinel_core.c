/* firmware/main/sentinel_core.c -- see sentinel_core.h. */
#include "sentinel_core.h"
#include "sentinel_model_stats.h"

#include <math.h>
#include <string.h>

#define SECONDS_PER_DAY 86400.0

void sentinel_config_default(sentinel_config_t *cfg, float q_rated_ah) {
    memset(cfg, 0, sizeof(*cfg));
    cfg->q_rated_ah = q_rated_ah;
    cfg->c_rated_ah = q_rated_ah;
    cfg->dt_s = 1.0f;
    cfg->prior_rate_per_week = 3.5f;     /* model/grade.py UsageRateEWMA default */
    cfg->prior_sigma_per_week = 1.0f;
    cfg->af_mean = 1.0f;
    cfg->l_cal_years = 5.0f;
    ekf_params_default(&cfg->ekf_params, q_rated_ah);
    /* Calibration override, found while integrating against data/sim_1hz/ (see
     * firmware/host/sentinel_host_sim.c): ekf_params_default()'s tail-current
     * threshold (1.5% of C20) is tuned for ekf/sim_battery_for_ekf.py's own
     * synthetic charge profile, NOT sim/battery_sim.py's (the generator behind
     * data/sim_1hz's CSVs, a separate module's simulator with a different
     * charger float-current floor -- observed empirically at ~6% of C20 for
     * battery_000, never lower, across the whole 15-day trace). At 1.5% the
     * EKF's full-charge tapering detector (design 01 §5a/§7) never latches on
     * this dataset -- zero cycles ever close. 10% comfortably clears the
     * observed floor with margin while still being tighter than the charger's
     * bulk/absorption current, so real cycle boundaries are still detected
     * (verified: >1200 s continuous dwell is reached on battery_000). A real
     * per-SKU deployment would calibrate this from the actual charger's
     * datasheet tail-current spec, not empirically like this. */
    cfg->ekf_params.i_tail_frac_c20 = 0.10f;
    cfg->ap_config = ap_default_config();
    cfg->ap_config.c_rated_ah = q_rated_ah;
    cfg->ap_config.configured = true;
    /* channel 0: T1 essentials, 1: T2, 2: T3, 3: T1 medical/never-shed --
     * 03-Parts-Placement-and-Roles.md §2 X7 channel map. */
    cfg->ap_config.channels[0].tier = AP_TIER_T1;
    cfg->ap_config.channels[1].tier = AP_TIER_T2;
    cfg->ap_config.channels[2].tier = AP_TIER_T3;
    cfg->ap_config.channels[3].tier = AP_TIER_T1;
    cfg->ap_config.channels[3].hw_locked_t1 = true; /* 03 §1 C9: medical jumper JP1 */
}

int sentinel_core_init(sentinel_ctx_t *ctx, const sentinel_config_t *cfg,
                        hl_sign_cb sign_cb, void *sign_ctx,
                        uint8_t *hl_buf, size_t hl_cap) {
    if (!ctx || !cfg || !hl_buf) return -1;
    memset(ctx, 0, sizeof(*ctx));
    ctx->cfg = *cfg;

    ekf_init(&ctx->ekf, &ctx->cfg.ekf_params);
    cycle_feat_init(&ctx->cf, ctx->cfg.q_rated_ah, ctx->cfg.dt_s);
    ap_init(&ctx->ap, &ctx->cfg.ap_config);

    usage_rate_ewma_init(&ctx->usage_rate, ctx->cfg.prior_rate_per_week, ctx->cfg.prior_sigma_per_week);
    grade_sm_init(&ctx->grade_sm);
    ctx->prev_efc = 0.0f;
    ctx->have_last_cycle_close_t = false;

    if (hl_init(&ctx->hl, hl_buf, hl_cap, sign_cb, sign_ctx) != HL_OK) return -2;

    ctx->window_len = 0;
    ctx->window_head = 0;
    memset(ctx->window_static, 0, sizeof(ctx->window_static));

    ctx->state.grade = GRADE_COLLECTING;
    ctx->state.confidence = SENTINEL_CONF_LOW;
    ctx->state.override_channel = -1;
    ctx->charger_on_prev = false;
    ctx->selftest_pass = false;
    ctx->last_logged_grade = -1;
    return 0;
}

int sentinel_core_selftest(sentinel_ctx_t *ctx) {
    int ok = sentinel_int8_selftest();
    ctx->selftest_pass = ok ? true : false;
    ctx->state.selftest_pass = ctx->selftest_pass;
    return ok;
}

static void standardize_window(const float win[SENTINEL_WINDOW_CYCLES][CYCLE_FEAT_N_DYNAMIC],
                                const float statics[CYCLE_FEAT_N_STATIC],
                                float out_dyn[SENTINEL_WINDOW_CYCLES][SENTINEL_N_DYNAMIC],
                                float out_static[SENTINEL_N_STATIC]) {
    for (int t = 0; t < SENTINEL_WINDOW_CYCLES; t++) {
        for (int c = 0; c < CYCLE_FEAT_N_DYNAMIC; c++) {
            float z = (win[t][c] - sentinel_mean_dyn[c]) / sentinel_scale_dyn[c];
            if (z > 3.0f) z = 3.0f;
            if (z < -3.0f) z = -3.0f;
            out_dyn[t][c] = z;
        }
    }
    for (int c = 0; c < CYCLE_FEAT_N_STATIC; c++) {
        float z = (statics[c] - sentinel_mean_stat[c]) / sentinel_scale_stat[c];
        if (z > 3.0f) z = 3.0f;
        if (z < -3.0f) z = -3.0f;
        out_static[c] = z;
    }
}

/* design 02 §2.2: unscale_soh(y) = y*40+60 ; RUL_EFC = expm1(y*8) */
static float unscale_soh(float y) { return y * 40.0f + 60.0f; }
static float unscale_rul_ln(float y) { return y * 8.0f; }

static float nan0(float v) { return isnan(v) ? 0.0f : v; }

typedef struct { uint8_t grade; float soh_p50; float rul_weeks_p50; } hl_grade_payload_t;
typedef struct { float soh_p50; float rul_efc_p50; } hl_capacity_payload_t;

static void run_inference_and_postprocess(sentinel_ctx_t *ctx) {
    float x_dyn_std[SENTINEL_WINDOW_CYCLES][SENTINEL_N_DYNAMIC];
    float x_static_std[SENTINEL_N_STATIC];

    /* window_dyn is a ring once full; present it to the model oldest-first
     * (matches model/windowing.py's "last WINDOW_CYCLES cycles in order").
     * If fewer than 30 cycles have been seen, the unfilled (zero-initialised)
     * rows stand in for "no data yet" -- the grade state machine gates on
     * n_cycles >= SENTINEL_MIN_CYCLES_FOR_GRADE separately, so a short
     * window never reaches a user-visible grade before then. */
    float ordered[SENTINEL_WINDOW_CYCLES][CYCLE_FEAT_N_DYNAMIC];
    if (ctx->window_len < SENTINEL_WINDOW_CYCLES) {
        memset(ordered, 0, sizeof(ordered));
        for (int i = 0; i < ctx->window_len; i++) memcpy(ordered[SENTINEL_WINDOW_CYCLES - ctx->window_len + i],
                                                           ctx->window_dyn[i], sizeof(ordered[0]));
    } else {
        for (int i = 0; i < SENTINEL_WINDOW_CYCLES; i++) {
            int src = (ctx->window_head + i) % SENTINEL_WINDOW_CYCLES;
            memcpy(ordered[i], ctx->window_dyn[src], sizeof(ordered[0]));
        }
    }

    standardize_window(ordered, ctx->window_static, x_dyn_std, x_static_std);

    sentinel_head_raw_t soh_raw, rul_raw;
    sentinel_int8_infer(x_dyn_std, x_static_std, &soh_raw, &rul_raw);

    /* head_quantiles: q50 = raw[0]; p10 = q50 - relu(raw[1]); p90 = q50 + relu(raw[2]) */
    float soh_q50_s = soh_raw.raw[0];
    float soh_p10_s = soh_q50_s - fmaxf(soh_raw.raw[1], 0.0f);
    float soh_p90_s = soh_q50_s + fmaxf(soh_raw.raw[2], 0.0f);
    float rul_q50_s = rul_raw.raw[0];
    float rul_p10_s = rul_q50_s - fmaxf(rul_raw.raw[1], 0.0f);
    float rul_p90_s = rul_q50_s + fmaxf(rul_raw.raw[2], 0.0f);

    float soh_p10 = unscale_soh(soh_p10_s), soh_p50 = unscale_soh(soh_q50_s), soh_p90 = unscale_soh(soh_p90_s);
    float rul_ln_p10 = unscale_rul_ln(rul_p10_s), rul_ln_q50 = unscale_rul_ln(rul_q50_s), rul_ln_p90 = unscale_rul_ln(rul_p90_s);

    /* conformal widening, model/evaluate.py:apply_conformal (NaN offsets -> 0, see
     * main/sentinel_model_stats.h doc comment) */
    soh_p10 -= nan0(SENTINEL_C_LO_SOH);
    soh_p90 += nan0(SENTINEL_C_HI_SOH);
    rul_ln_p10 -= nan0(SENTINEL_C_LO_RUL);
    rul_ln_p90 += nan0(SENTINEL_C_HI_RUL);

    float rul_efc_p10 = fmaxf(expm1f(rul_ln_p10), 0.0f);
    float rul_efc_p50 = fmaxf(expm1f(rul_ln_q50), 0.0f);
    float rul_efc_p90 = fmaxf(expm1f(rul_ln_p90), 0.0f);

    float day = (float)(ctx->state.n_samples * (double)ctx->cfg.dt_s / SECONDS_PER_DAY);
    float w_p10, w_p50, w_p90;
    grade_rul_efc_to_weeks(rul_efc_p10, rul_efc_p50, rul_efc_p90,
                            ctx->usage_rate.r, usage_rate_ewma_sigma(&ctx->usage_rate),
                            ctx->window_static[5] /* age_years */, ctx->cfg.af_mean, ctx->cfg.l_cal_years,
                            &w_p10, &w_p50, &w_p90);

    bool have_enough_data = ctx->state.n_cycles >= SENTINEL_MIN_CYCLES_FOR_GRADE;
    bool service_now = false; /* design 04 §4.6: the anomaly autoencoder gates this;
                                  no AE port exists in this prototype pass (see
                                  firmware/README.md honest limits) -- always false. */
    int have_n, n_weeks;
    int grade = grade_sm_update(&ctx->grade_sm, day, soh_p50, w_p10, w_p90,
                                 have_enough_data, service_now, &have_n, &n_weeks);

    ctx->state.soh_p10 = soh_p10; ctx->state.soh_p50 = soh_p50; ctx->state.soh_p90 = soh_p90;
    ctx->state.rul_efc_p10 = rul_efc_p10; ctx->state.rul_efc_p50 = rul_efc_p50; ctx->state.rul_efc_p90 = rul_efc_p90;
    ctx->state.rul_weeks_p10 = w_p10; ctx->state.rul_weeks_p50 = w_p50; ctx->state.rul_weeks_p90 = w_p90;
    ctx->state.grade = grade;
    ctx->state.have_n_weeks = have_n;
    ctx->state.n_weeks = n_weeks;
    ctx->state.confidence = (ctx->state.n_cycles < SENTINEL_MIN_CYCLES_FOR_GRADE) ? SENTINEL_CONF_LOW
                             : (ctx->state.n_cycles < SENTINEL_MED_CYCLES_FOR_HIGH_CONF) ? SENTINEL_CONF_MED
                             : SENTINEL_CONF_HIGH;

    /* health log: grade change + a periodic capacity sample (design 09 §4 event
     * types HL_EVT_GRADE_CHANGE / HL_EVT_CAPACITY_SAMPLE) */
    if (grade != ctx->last_logged_grade) {
        hl_grade_payload_t p = { (uint8_t)grade, soh_p50, w_p50 };
        hl_append(&ctx->hl, HL_EVT_GRADE_CHANGE, (const uint8_t *)&p, sizeof(p));
        ctx->last_logged_grade = grade;
    }
    hl_capacity_payload_t cp = { soh_p50, rul_efc_p50 };
    hl_append(&ctx->hl, HL_EVT_CAPACITY_SAMPLE, (const uint8_t *)&cp, sizeof(cp));

    ctx->state.healthlog_bytes = hl_length(&ctx->hl);
    ctx->state.healthlog_records = ctx->hl.next_counter;
}

static void push_cycle_row(sentinel_ctx_t *ctx, const float dyn_row[CYCLE_FEAT_N_DYNAMIC],
                            const float static_row[CYCLE_FEAT_N_STATIC]) {
    if (ctx->window_len < SENTINEL_WINDOW_CYCLES) {
        memcpy(ctx->window_dyn[ctx->window_len], dyn_row, sizeof(ctx->window_dyn[0]));
        ctx->window_len++;
    } else {
        memcpy(ctx->window_dyn[ctx->window_head], dyn_row, sizeof(ctx->window_dyn[0]));
        ctx->window_head = (ctx->window_head + 1) % SENTINEL_WINDOW_CYCLES;
    }
    memcpy(ctx->window_static, static_row, sizeof(ctx->window_static));
    ctx->state.n_cycles++;

    memcpy(ctx->state.last_closed_dyn_row, dyn_row, sizeof(ctx->state.last_closed_dyn_row));
    memcpy(ctx->state.last_closed_static_row, static_row, sizeof(ctx->state.last_closed_static_row));
    ctx->state.have_new_closed_row = true;
}

void sentinel_core_inject_cycle_and_infer(sentinel_ctx_t *ctx,
                                           const float dyn_row[CYCLE_FEAT_N_DYNAMIC],
                                           const float static_row[CYCLE_FEAT_N_STATIC]) {
    push_cycle_row(ctx, dyn_row, static_row);
    if (ctx->selftest_pass) run_inference_and_postprocess(ctx);
}

void sentinel_core_on_sample(sentinel_ctx_t *ctx, const sentinel_sample_t *s) {
    /* CONTRACTS §1 -> §6 sign-flip boundary, exactly like ekf/test_ekf_host.c */
    float I_discharge_pos = -s->I;

    /* charger_on inference: the CONTRACTS §1 stream has no ground-truth charger
     * relay flag (only ekf/sim_battery_for_ekf.py's *separate* EKF-only test
     * stream does) -- a real device doesn't have that ground truth either, so
     * this mirrors what firmware glue actually has to do: infer it. A
     * current-threshold test (charging current above a noise floor) was tried
     * first and is WRONG: it flips charger_on to false exactly during the
     * float/tail-current phase (small current, charger still engaged) that
     * ekf_step's full-charge tapering detector needs charger_on=true to see
     * (design 01 §5a/§7) -- with that test, no cycle ever closes. The
     * available CONTRACTS §1 signal that actually tracks the charger relay is
     * `grid` (mains present): while mains is present the inverter's charger is
     * assumed active (bulk/absorption/float all count); on an outage (grid=0)
     * the battery only ever discharges. Documented simplification, see
     * firmware/README.md -- a real install would read this off the DC-DC
     * charger's own enable line rather than assuming from grid. */
    bool charger_on = s->grid != 0;

    ekf_step(&ctx->ekf, I_discharge_pos, s->V, s->T, charger_on ? 1 : 0);
    ctx->charger_on_prev = charger_on;

    cycle_feat_on_sample(&ctx->cf, I_discharge_pos, s->T, ekf_soc(&ctx->ekf));

    ctx->state.n_samples++;
    ctx->state.t = s->t;
    ctx->state.soc = ekf_soc(&ctx->ekf);
    ctx->state.soc_raw_coulomb = ctx->ekf.soc_raw_naive;
    ctx->state.r0_ohm = ekf_r0(&ctx->ekf);
    ctx->state.soh_r = ekf_soh_r(&ctx->ekf);
    ctx->state.last_V = s->V;
    ctx->state.last_I = s->I;
    ctx->state.last_T = s->T;

    if (ctx->ekf.last_anchor == 1) {
        float dyn_row[CYCLE_FEAT_N_DYNAMIC];
        float static_row[CYCLE_FEAT_N_STATIC];
        cycle_feat_on_cycle_close(&ctx->cf, &ctx->ekf, dyn_row, static_row);
        push_cycle_row(ctx, dyn_row, static_row);

        /* usage-rate EWMA: feed the EFC delta since the previous cycle close */
        float efc_now = static_row[0];
        double days_elapsed = ctx->have_last_cycle_close_t
            ? (s->t - ctx->last_cycle_close_t) / SECONDS_PER_DAY
            : (double)ctx->cfg.dt_s / SECONDS_PER_DAY;
        usage_rate_ewma_update(&ctx->usage_rate, efc_now - ctx->prev_efc, (float)days_elapsed);
        ctx->prev_efc = efc_now;
        ctx->last_cycle_close_t = s->t;
        ctx->have_last_cycle_close_t = true;

        if (ctx->selftest_pass) {
            run_inference_and_postprocess(ctx);
        }
    }
}

void sentinel_core_on_minute(sentinel_ctx_t *ctx, int hour, int dow, float load_w) {
    ap_input_t in;
    memset(&in, 0, sizeof(in));
    in.t = (float)ctx->state.t;
    in.soc = ekf_soc(&ctx->ekf);
    in.soh = ctx->state.soh_p50 > 0.0f ? (ctx->state.soh_p50 / 100.0f) : 1.0f;
    in.grid_ok = !ctx->state.outage_active;
    in.load_w = load_w;
    in.hour = hour;
    in.dow = dow;
    in.temp_c = 25.0f; /* ambient not separately sensed in this prototype; battery T
                           (ekf's T input) stands in where autopilot needs *a* value --
                           documented simplification. */
    in.override_request = -1;

    ap_output_t out;
    ap_evaluate(&ctx->ap, &in, &out);

    for (int i = 0; i < AP_N_CHANNELS; i++) ctx->state.channel_state[i] = out.channel_state[i];
    ctx->state.reasons_n = out.reasons_n;
    for (int i = 0; i < out.reasons_n && i < 8; i++) {
        strncpy(ctx->state.reasons[i], out.reasons[i], sizeof(ctx->state.reasons[i]) - 1);
        ctx->state.reasons[i][sizeof(ctx->state.reasons[i]) - 1] = '\0';
    }
    ctx->state.have_est_backup_min = out.have_est_backup_min;
    ctx->state.est_backup_min = out.est_backup_min;
    ctx->state.outage_active = out.outage_active;
    ctx->state.pre_outage_active = out.pre_outage_active;
    ctx->state.override_channel = ctx->ap.override_channel;
}

void sentinel_core_on_outage_vote(sentinel_ctx_t *ctx, float t, float mains_rms_pu,
                                   ap_inv_mode_t inverter_mode_pin, float batt_discharge_a) {
    ap_outage_input_t in = { t, mains_rms_pu, inverter_mode_pin, batt_discharge_a };
    ap_outage_step(&ctx->ap, &in);
}

void sentinel_core_get_state(const sentinel_ctx_t *ctx, sentinel_state_t *out) {
    *out = ctx->state;
}
