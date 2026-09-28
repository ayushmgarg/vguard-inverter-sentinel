/* firmware/main/sentinel_core.h -- the portable control-loop "engine".
 *
 * This is the one place the whole pipeline (EKF -> cycle segmentation -> int8
 * inference -> conformal/grade post-processing -> autopilot -> health log ->
 * dashboard state) is wired together. Both the ESP32 firmware (main.c's
 * FreeRTOS tasks) and the host simulator (host/sentinel_host_sim.c) call the
 * same functions here -- this is deliberate: it is the only way the host
 * build can be said to "run the whole control loop" rather than a
 * reimplementation of it (see firmware/README.md).
 *
 * C99, no ESP-IDF/FreeRTOS dependency, no malloc (everything is fixed-size
 * and either caller-owned or embedded in sentinel_ctx_t).
 */
#ifndef SENTINEL_CORE_H
#define SENTINEL_CORE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ekf.h"
#include "autopilot.h"
#include "healthlog.h"

#include "sentinel_types.h"
#include "cycle_feat.h"
#include "grade.h"
#include "sentinel_int8.h"

#ifdef __cplusplus
extern "C" {
#endif

#define SENTINEL_MIN_CYCLES_FOR_GRADE 10   /* design 04 §6: "collecting data (needs >= 10 cycles)" */
#define SENTINEL_MED_CYCLES_FOR_HIGH_CONF 30

typedef enum { SENTINEL_CONF_LOW = 0, SENTINEL_CONF_MED = 1, SENTINEL_CONF_HIGH = 2 } sentinel_confidence_t;

typedef struct {
    float q_rated_ah;
    float c_rated_ah;         /* autopilot Peukert capacity, usually == q_rated_ah */
    float dt_s;                /* sample period, 1.0 for the 1 Hz stream */
    float prior_rate_per_week; /* usage-rate EWMA prior, EFC/week */
    float prior_sigma_per_week;
    float af_mean;              /* calendar-aging acceleration factor, 1.0 = nominal */
    float l_cal_years;          /* calendar-life bound, design 02 §3.1 default 5.0 */
    ekf_params_t ekf_params;
    ap_config_t ap_config;
} sentinel_config_t;

void sentinel_config_default(sentinel_config_t *cfg, float q_rated_ah);

/* Dashboard-facing state, CONTRACTS.md §3 (model outputs) + §5 (autopilot) +
 * a handful of housekeeping fields state_json.c also serialises. */
typedef struct {
    /* §3 model outputs */
    float soh_p10, soh_p50, soh_p90;
    float rul_efc_p10, rul_efc_p50, rul_efc_p90;
    float rul_weeks_p10, rul_weeks_p50, rul_weeks_p90;
    int   grade;                 /* GRADE_* from grade.h */
    int   have_n_weeks;
    int   n_weeks;
    sentinel_confidence_t confidence;

    /* EKF-derived */
    float soc;
    float soc_raw_coulomb;
    float r0_ohm;
    float soh_r;
    float last_V, last_I, last_T;

    /* §5 autopilot outputs */
    ap_chstate_t channel_state[AP_N_CHANNELS];
    int   reasons_n;
    char  reasons[8][128];
    bool  have_est_backup_min;
    float est_backup_min;
    bool  outage_active;
    bool  pre_outage_active;
    int   override_channel;      /* -1 = no active user override, else channel id 0-3 */

    /* housekeeping */
    long  n_cycles;
    long  n_samples;
    double t;
    size_t healthlog_bytes;
    uint32_t healthlog_records;
    bool  selftest_pass;
    bool  replay_active;         /* replay.c demo-mode banner, design 04 §6 */

    /* set true by sentinel_core_on_sample()/sentinel_core_inject_cycle_and_infer()
     * whenever a cycle just closed this call; main.c's logger task consumes this
     * (persists dyn_row/static_row to LittleFS "features.bin") and clears it --
     * see main.c doc comment on why this replaces a dedicated cycle_feat-owned
     * persistence task in this prototype pass. */
    bool  have_new_closed_row;
    float last_closed_dyn_row[CYCLE_FEAT_N_DYNAMIC];
    float last_closed_static_row[CYCLE_FEAT_N_STATIC];
} sentinel_state_t;

typedef struct {
    sentinel_config_t cfg;

    ekf_t ekf;
    cycle_feat_ctx_t cf;
    ap_t ap;

    /* rolling window of the last <=30 cycles' dynamic features (raw, not yet
     * standardised) + the most recent static vector -- exactly the model's
     * input shape (30,14)+(6,), design 02 §1.10/§2.1. */
    float window_dyn[SENTINEL_WINDOW_CYCLES][CYCLE_FEAT_N_DYNAMIC];
    float window_static[CYCLE_FEAT_N_STATIC];
    int   window_len;    /* number of valid rows in window_dyn, saturates at 30 */
    int   window_head;   /* next row to overwrite once full (ring) */

    usage_rate_ewma_t usage_rate;
    grade_state_machine_t grade_sm;
    float prev_efc;
    double last_cycle_close_t;
    bool  have_last_cycle_close_t;

    hl_t hl;

    sentinel_state_t state;

    bool  charger_on_prev;
    bool  selftest_pass;
    int   last_logged_grade;   /* -1 = none logged yet; drives HL_EVT_GRADE_CHANGE dedup */
} sentinel_ctx_t;

/* hl_buf must stay valid for the lifetime of ctx (caller-owned static/NVS-backed
 * buffer, per healthlog.h's "no heap pointers" contract). Returns 0 on success. */
int sentinel_core_init(sentinel_ctx_t *ctx, const sentinel_config_t *cfg,
                        hl_sign_cb sign_cb, void *sign_ctx,
                        uint8_t *hl_buf, size_t hl_cap);

/* Runs the golden self-test (sentinel_int8_selftest) and records the result
 * in ctx->selftest_pass / ctx->state.selftest_pass. Returns 1 PASS / 0 FAIL.
 * Call once at boot before trusting any inference (design 04 §4 step 3). */
int sentinel_core_selftest(sentinel_ctx_t *ctx);

/* 1 Hz tick: EKF step, cycle-feature accumulation, and -- on a cycle
 * boundary -- window update, int8 inference, conformal + grade
 * post-processing, and a health-log append. */
void sentinel_core_on_sample(sentinel_ctx_t *ctx, const sentinel_sample_t *s);

/* 60 s tick: autopilot evaluation (design 05). `hour`/`dow` are wall-clock
 * (DS3231-backed on real hardware, CONTRACTS §1 has no clock column so the
 * host sim derives them from `t`). */
void sentinel_core_on_minute(sentinel_ctx_t *ctx, int hour, int dow, float load_w);

/* Feeds the outage-detection vote (design 05 §7 / CONTRACTS §5) -- call
 * faster than the 60 s autopilot cycle whenever a new mains-sense sample is
 * available. */
void sentinel_core_on_outage_vote(sentinel_ctx_t *ctx, float t, float mains_rms_pu,
                                   ap_inv_mode_t inverter_mode_pin, float batt_discharge_a);

void sentinel_core_get_state(const sentinel_ctx_t *ctx, sentinel_state_t *out);

/* Injects one pre-computed cycle-feature row directly into the model window and
 * runs inference/postprocessing on it, bypassing the EKF/cycle_feat pipeline --
 * used only by main/replay.c's demo mode (design 04 §6: "feeds ml_infer as if
 * cycles had happened"). Does NOT touch the EKF, healthlog cycle-close
 * bookkeeping beyond the usual grade/healthlog append, or n_samples. */
void sentinel_core_inject_cycle_and_infer(sentinel_ctx_t *ctx,
                                           const float dyn_row[CYCLE_FEAT_N_DYNAMIC],
                                           const float static_row[CYCLE_FEAT_N_STATIC]);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_CORE_H */
