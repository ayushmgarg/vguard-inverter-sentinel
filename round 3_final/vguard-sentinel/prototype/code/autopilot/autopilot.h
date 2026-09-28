/* autopilot.h -- C99 port of the V-Guard Sentinel Engine-2 controller.
 *
 * Mirrors documentation/prototype/code/autopilot/controller.py. Both must
 * agree on the same scenario table (tests/test_autopilot.py calls this via
 * autopilot/test_autopilot_host.c as a subprocess and diffs the outputs).
 *
 * Design refs: 05-Habit-Autopilot-and-Load-Prioritisation.md Sec.4 & Sec.7,
 * 10-Hardware-Interfaces-and-Power.md Sec.4 & Sec.7. CONTRACTS.md Sec.5/6
 * fixes the function names (ap_init, ap_evaluate) and the SHED/ON channel
 * semantics (SHED = coil energised on an NC contactor, i.e. load OFF).
 *
 * Static allocation only: no malloc/free anywhere in this module.
 */
#ifndef AUTOPILOT_H
#define AUTOPILOT_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define AP_N_CHANNELS 4

typedef enum { AP_TIER_T1 = 1, AP_TIER_T2 = 2, AP_TIER_T3 = 3 } ap_tier_t;
typedef enum { AP_CH_ON = 0, AP_CH_SHED = 1 } ap_chstate_t;
typedef enum { AP_MODE_PREDICTIVE = 0, AP_MODE_CONSERVATIVE = 1 } ap_mode_t;

/* mains inverter-mode pin: not every SKU exposes it (10 Sec.1: retrofit
 * only if physically accessible). AP_INV_UNKNOWN means "no reading". */
typedef enum { AP_INV_UNKNOWN = 0, AP_INV_NORMAL = 1, AP_INV_BACKUP = 2 } ap_inv_mode_t;

typedef struct {
    ap_tier_t tier;
    bool hw_locked_t1;   /* driver-board jumper/DIP -- forces T1, app cannot override */
} ap_channel_config_t;

typedef struct {
    ap_channel_config_t channels[AP_N_CHANNELS];
    bool configured;     /* false (or CRC-invalid) -> fail-safe: every channel forced T1 */

    /* SoC hysteresis ladder (05 Sec.4.2) */
    float shed_t3_soc_pct;
    float restore_t3_soc_pct;
    float defer_t2_soc_pct;
    float restore_t2_soc_pct;

    /* dwell */
    float dwell_on_s;
    float dwell_off_s;

    /* override */
    float override_timeout_default_s;
    float override_timeout_max_s;

    /* forecast-disagreement fallback */
    float forecast_disagreement_ratio;
    float forecast_disagreement_window_s;

    /* essentials-at-risk hard floor */
    float essentials_risk_margin;

    /* Peukert / E_usable */
    float peukert_n;
    float c_rated_ah;
    float v_nominal;
    float t_rated_h;

    bool charger_commandable;

    /* pre-charge / pre-emption */
    float pre_outage_prob_threshold;
    float pre_outage_conf_threshold;
    float pre_outage_soc_raise_pp;
    float pre_outage_threshold_raise_pp;
    float pre_outage_window_s;

    /* outage detection (05 Sec.7 / 10 Sec.7) */
    float mains_sag_pu;
    float mains_restore_pu;
    float s1_debounce_s;
    float s2_debounce_s;
    float s3_debounce_s;
    float s1_alone_debounce_s;
    float restore_debounce_s;
    float batt_idle_discharge_a;
} ap_config_t;

typedef struct {
    ap_chstate_t state;
    float last_transition_s;
} ap_channel_state_t;

typedef struct {
    bool active;
    float s1_since;      /* -1 means "not currently timing" */
    float s2_since;
    float s3_since;
    float restore_since;
} ap_outage_state_t;

typedef struct {
    ap_config_t config;
    ap_channel_state_t channels[AP_N_CHANNELS];
    ap_chstate_t t3_target;
    ap_chstate_t t2_target;
    ap_mode_t mode;
    float disagreement_since;   /* -1 = not timing */
    int override_channel;       /* -1 = no active override */
    float override_expires_at_s;
    float pre_outage_boost_until; /* -1 = none active */
    ap_outage_state_t outage;
} ap_t;

typedef struct {
    float t;                    /* monotonic seconds since boot */
    float soc;                  /* 0..1 */
    float soh;                  /* 0..1 */
    bool grid_ok;                /* mains present (post outage-vote) */
    float load_w;
    int hour;                   /* 0-23 */
    int dow;                    /* 0-6 */
    float temp_c;
    float i_forecast_a;
    float fcst_t1_wh;
    bool have_outage_forecast;
    float outage_prob_h3;
    float outage_conf;
    bool have_decline_rates;
    float actual_decline_pct_per_min;
    float forecast_decline_pct_per_min;
    int override_request;       /* -1 = none, else channel id 0-3 */
    bool have_override_timeout;
    float override_timeout_s;
    bool override_clear;
} ap_input_t;

typedef struct {
    ap_chstate_t channel_state[AP_N_CHANNELS];
    char reasons[8][128];        /* up to 8 reason strings, NUL-terminated; reasons_n gives the count actually used */
    int reasons_n;
    bool have_est_backup_min;
    float est_backup_min;
    ap_mode_t mode;
    float e_usable_wh;
    bool outage_active;
    bool pre_outage_active;
    bool charger_command_active;
} ap_output_t;

typedef struct {
    float t;
    float mains_rms_pu;
    ap_inv_mode_t inverter_mode_pin;
    float batt_discharge_a;
} ap_outage_input_t;

/* --- CONTRACTS.md Sec.6 mandated API --- */
void ap_init(ap_t *ap, const ap_config_t *config);
void ap_evaluate(ap_t *ap, const ap_input_t *in, ap_output_t *out);

/* --- additional helpers (not in CONTRACTS.md, needed for outage-vote
 * timing that runs faster than the 60 s ap_evaluate cycle) --- */
void ap_outage_step(ap_t *ap, const ap_outage_input_t *in);
ap_config_t ap_default_config(void);
float ap_peukert_capacity_ah(float c_rated_ah, float i_forecast_a, float temp_c, float n, float t_rated_h);
float ap_usable_energy_wh(float soh, float soc, const ap_config_t *config, float i_forecast_a, float temp_c);

#ifdef __cplusplus
}
#endif

#endif /* AUTOPILOT_H */
