/* autopilot.c -- C99 port of controller.py. See autopilot.h for design refs.
 *
 * Decision logic mirrors controller.py function-for-function so the two
 * agree on the shared scenario table (tests/test_autopilot.py). The
 * CONTRACTS-mandated API (ap_init/ap_evaluate) MUTATES ap_t in place --
 * a normal embedded idiom, unlike the Python reference model which
 * returns new state objects (project immutability rule applies to the
 * Python module; the C signature is fixed by CONTRACTS.md Sec.6).
 *
 * No dynamic allocation anywhere in this file.
 */
#include "autopilot.h"
#include <math.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>

#define AP_NOT_TIMING (-1.0f)

static float ap_fmaxf(float a, float b) { return a > b ? a : b; }
static float ap_fminf(float a, float b) { return a < b ? a : b; }
static float ap_clampf(float x, float lo, float hi) { return ap_fmaxf(lo, ap_fminf(hi, x)); }

static void ap_add_reason(ap_output_t *out, const char *fmt, ...) {
    if (out->reasons_n >= 8) return;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(out->reasons[out->reasons_n], sizeof(out->reasons[0]), fmt, ap);
    va_end(ap);
    out->reasons_n++;
}

ap_config_t ap_default_config(void) {
    ap_config_t c;
    memset(&c, 0, sizeof(c));
    for (int i = 0; i < AP_N_CHANNELS; i++) {
        c.channels[i].tier = AP_TIER_T1;
        c.channels[i].hw_locked_t1 = false;
    }
    c.configured = false;
    c.shed_t3_soc_pct = 40.0f;
    c.restore_t3_soc_pct = 55.0f;
    c.defer_t2_soc_pct = 55.0f;
    c.restore_t2_soc_pct = 70.0f;
    c.dwell_on_s = 300.0f;
    c.dwell_off_s = 180.0f;
    c.override_timeout_default_s = 1800.0f;
    c.override_timeout_max_s = 14400.0f;
    c.forecast_disagreement_ratio = 1.3f;
    c.forecast_disagreement_window_s = 300.0f;
    c.essentials_risk_margin = 1.2f;
    c.peukert_n = 1.25f;
    c.c_rated_ah = 150.0f;
    c.v_nominal = 12.0f;
    c.t_rated_h = 20.0f;
    c.charger_commandable = false;
    c.pre_outage_prob_threshold = 0.55f;
    c.pre_outage_conf_threshold = 0.5f;
    c.pre_outage_soc_raise_pp = 15.0f;
    c.pre_outage_threshold_raise_pp = 10.0f;
    c.pre_outage_window_s = 3.0f * 3600.0f;
    c.mains_sag_pu = 0.10f;
    c.mains_restore_pu = 0.90f;
    c.s1_debounce_s = 1.5f;
    c.s2_debounce_s = 0.15f;
    c.s3_debounce_s = 1.5f;
    c.s1_alone_debounce_s = 4.0f;
    c.restore_debounce_s = 20.0f;
    c.batt_idle_discharge_a = 1.0f;
    return c;
}

static ap_tier_t ap_effective_tier(const ap_config_t *cfg, int i) {
    const ap_channel_config_t *ch = &cfg->channels[i];
    if (ch->hw_locked_t1) return AP_TIER_T1;
    if (!cfg->configured) return AP_TIER_T1;
    return ch->tier;
}

void ap_init(ap_t *ap, const ap_config_t *config) {
    memset(ap, 0, sizeof(*ap));
    ap->config = *config;
    for (int i = 0; i < AP_N_CHANNELS; i++) {
        ap->channels[i].state = AP_CH_ON;
        ap->channels[i].last_transition_s = 0.0f;
    }
    ap->t3_target = AP_CH_ON;
    ap->t2_target = AP_CH_ON;
    ap->mode = AP_MODE_PREDICTIVE;
    ap->disagreement_since = AP_NOT_TIMING;
    ap->override_channel = -1;
    ap->override_expires_at_s = AP_NOT_TIMING;
    ap->pre_outage_boost_until = AP_NOT_TIMING;
    ap->outage.active = false;
    ap->outage.s1_since = AP_NOT_TIMING;
    ap->outage.s2_since = AP_NOT_TIMING;
    ap->outage.s3_since = AP_NOT_TIMING;
    ap->outage.restore_since = AP_NOT_TIMING;
}

/* ---- Peukert-corrected usable energy (05 Sec.4.1) ---- */

static float ap_f_temp(float temp_c) {
    float f = 1.0f + 0.008f * (temp_c - 25.0f);
    return ap_clampf(f, 0.5f, 1.05f);
}

float ap_peukert_capacity_ah(float c_rated_ah, float i_forecast_a, float temp_c, float n, float t_rated_h) {
    float i = ap_fmaxf(i_forecast_a, 1e-6f);
    float ratio = c_rated_ah / (i * t_rated_h);
    float c_usable = c_rated_ah * powf(ratio, n - 1.0f) * ap_f_temp(temp_c);
    return ap_fmaxf(c_usable, 0.0f);
}

float ap_usable_energy_wh(float soh, float soc, const ap_config_t *config, float i_forecast_a, float temp_c) {
    float c_usable = ap_peukert_capacity_ah(config->c_rated_ah, i_forecast_a, temp_c, config->peukert_n, config->t_rated_h);
    return soh * soc * c_usable * config->v_nominal;
}

/* ---- 2-of-3 outage vote with debounce and restore hysteresis (05 Sec.7) ---- */

void ap_outage_step(ap_t *ap, const ap_outage_input_t *in) {
    const ap_config_t *cfg = &ap->config;
    float t = in->t;
    ap_outage_state_t *st = &ap->outage;

    bool s1_now = in->mains_rms_pu < cfg->mains_sag_pu;
    float s1_since = s1_now ? (st->s1_since >= 0.0f ? st->s1_since : t) : AP_NOT_TIMING;
    bool s1 = s1_now && s1_since >= 0.0f && (t - s1_since) >= cfg->s1_debounce_s;
    bool s1_alone = s1_now && s1_since >= 0.0f && (t - s1_since) >= cfg->s1_alone_debounce_s;

    bool s2_now = (in->inverter_mode_pin == AP_INV_BACKUP);
    float s2_since = s2_now ? (st->s2_since >= 0.0f ? st->s2_since : t) : AP_NOT_TIMING;
    bool s2 = s2_now && s2_since >= 0.0f && (t - s2_since) >= cfg->s2_debounce_s;

    bool s3_now = in->batt_discharge_a > cfg->batt_idle_discharge_a;
    float s3_since = s3_now ? (st->s3_since >= 0.0f ? st->s3_since : t) : AP_NOT_TIMING;
    bool s3 = s3_now && s3_since >= 0.0f && (t - s3_since) >= cfg->s3_debounce_s;

    int votes = (s1 ? 1 : 0) + (s2 ? 1 : 0) + (s3 ? 1 : 0);
    bool declare = (votes >= 2) || s1_alone;

    bool new_active;
    float restore_since;
    if (st->active) {
        if (in->mains_rms_pu > cfg->mains_restore_pu) {
            restore_since = (st->restore_since >= 0.0f) ? st->restore_since : t;
            if ((t - restore_since) >= cfg->restore_debounce_s) {
                new_active = false;
                restore_since = AP_NOT_TIMING;
            } else {
                new_active = true;
            }
        } else {
            new_active = true;
            restore_since = AP_NOT_TIMING;
        }
    } else {
        new_active = declare;
        restore_since = AP_NOT_TIMING;
    }

    st->s1_since = s1_since;
    st->s2_since = s2_since;
    st->s3_since = s3_since;
    st->restore_since = restore_since;
    st->active = new_active;
}

/* ---- 60 s tier-shedding evaluate() (05 Sec.4.3) ---- */

static float ap_threshold(float base_pct, bool boost_active, float raise_pp) {
    return base_pct + (boost_active ? raise_pp : 0.0f);
}

void ap_evaluate(ap_t *ap, const ap_input_t *in, ap_output_t *out) {
    const ap_config_t *cfg = &ap->config;
    float t = in->t;
    memset(out, 0, sizeof(*out));

    /* 1. forecast-disagreement escalation -> CONSERVATIVE */
    bool disagree_now = false;
    if (in->have_decline_rates && in->forecast_decline_pct_per_min > 0.0f) {
        disagree_now = in->actual_decline_pct_per_min > cfg->forecast_disagreement_ratio * in->forecast_decline_pct_per_min;
    }
    if (disagree_now) {
        if (ap->disagreement_since < 0.0f) ap->disagreement_since = t;
    } else {
        ap->disagreement_since = AP_NOT_TIMING;
    }
    ap_mode_t mode;
    if (ap->disagreement_since >= 0.0f && (t - ap->disagreement_since) >= cfg->forecast_disagreement_window_s) {
        mode = AP_MODE_CONSERVATIVE;
        ap_add_reason(out, "forecast disagreement >1.3x actual decline for >=5min -> CONSERVATIVE");
    } else {
        mode = AP_MODE_PREDICTIVE;
    }

    /* 2. E_usable with Peukert correction */
    float e_usable_wh = ap_usable_energy_wh(in->soh, in->soc, cfg, in->i_forecast_a, in->temp_c);

    /* 3. essentials-at-risk hard floor (always active) */
    bool hard_floor_shed_t3 = false;
    if (!in->grid_ok && e_usable_wh < cfg->essentials_risk_margin * in->fcst_t1_wh) {
        hard_floor_shed_t3 = true;
        ap_add_reason(out, "hard floor: T1 endurance at risk (E_usable=%.1fWh < %.2fx fcst=%.1fWh)",
                      e_usable_wh, cfg->essentials_risk_margin, in->fcst_t1_wh);
    }

    /* 4. predictive pre-emption window */
    if (mode == AP_MODE_PREDICTIVE && in->grid_ok && in->have_outage_forecast &&
        in->outage_prob_h3 > cfg->pre_outage_prob_threshold && in->outage_conf > cfg->pre_outage_conf_threshold) {
        ap->pre_outage_boost_until = t + cfg->pre_outage_window_s;
        ap_add_reason(out, "pre-charge window: SoC target +%.0fpp, thresholds +%.0fpp (P=%.2f conf=%.2f)",
                      cfg->pre_outage_soc_raise_pp, cfg->pre_outage_threshold_raise_pp, in->outage_prob_h3, in->outage_conf);
    }
    bool boost_active = ap->pre_outage_boost_until >= 0.0f && t < ap->pre_outage_boost_until;
    if (ap->pre_outage_boost_until >= 0.0f && !boost_active) {
        ap->pre_outage_boost_until = AP_NOT_TIMING;
    }

    bool charger_command_active = boost_active && cfg->charger_commandable && in->grid_ok;
    if (boost_active) {
        if (cfg->charger_commandable) {
            ap_add_reason(out, "charger commanded to bulk/absorption now (pre-charge, embedded SKU)");
        } else {
            ap_add_reason(out, "advisory: scheduled-outage pattern likely soon -- limit heavy loads now (retrofit SKU)");
        }
    }

    /* 5. SoC hysteresis ladder, thresholds tightened +10pp during a pre-charge window */
    float soc_pct = in->soc * 100.0f;
    float shed_t3_th = ap_threshold(cfg->shed_t3_soc_pct, boost_active, cfg->pre_outage_threshold_raise_pp);
    float restore_t3_th = ap_threshold(cfg->restore_t3_soc_pct, boost_active, cfg->pre_outage_threshold_raise_pp);
    float defer_t2_th = ap_threshold(cfg->defer_t2_soc_pct, boost_active, cfg->pre_outage_threshold_raise_pp);
    float restore_t2_th = ap_threshold(cfg->restore_t2_soc_pct, boost_active, cfg->pre_outage_threshold_raise_pp);

    ap_chstate_t prev_t3_target = ap->t3_target;
    ap_chstate_t prev_t2_target = ap->t2_target;

    bool ladder_shed_t3 = soc_pct <= shed_t3_th;
    bool ladder_restore_t3 = soc_pct >= restore_t3_th;
    ap_chstate_t t3_target = ap->t3_target;
    if (ladder_shed_t3) t3_target = AP_CH_SHED;
    else if (ladder_restore_t3) t3_target = AP_CH_ON;

    if (t3_target == AP_CH_SHED && prev_t3_target != AP_CH_SHED && ladder_shed_t3)
        ap_add_reason(out, "T3 shed target: SoC %.1f%% <= %.1f%%", soc_pct, shed_t3_th);
    if (t3_target == AP_CH_ON && prev_t3_target != AP_CH_ON)
        ap_add_reason(out, "T3 restore target: SoC %.1f%% >= %.1f%%", soc_pct, restore_t3_th);

    if (hard_floor_shed_t3) t3_target = AP_CH_SHED;

    ap_chstate_t t2_target = ap->t2_target;
    if (soc_pct <= defer_t2_th) t2_target = AP_CH_SHED;
    else if (soc_pct >= restore_t2_th) t2_target = AP_CH_ON;

    if (t2_target == AP_CH_SHED && prev_t2_target != AP_CH_SHED)
        ap_add_reason(out, "T2 defer target: SoC %.1f%% <= %.1f%%", soc_pct, defer_t2_th);
    if (t2_target == AP_CH_ON && prev_t2_target != AP_CH_ON)
        ap_add_reason(out, "T2 restore target: SoC %.1f%% >= %.1f%%", soc_pct, restore_t2_th);

    ap->t3_target = t3_target;
    ap->t2_target = t2_target;

    /* 6. user override: SoC-ladder tiers only, cannot beat the hard floor, timeout */
    if (in->override_request >= 0) {
        float timeout = in->have_override_timeout ? in->override_timeout_s : cfg->override_timeout_default_s;
        timeout = ap_clampf(timeout, 0.0f, cfg->override_timeout_max_s);
        ap->override_channel = in->override_request;
        ap->override_expires_at_s = t + timeout;
        ap_add_reason(out, "user override armed: channel %d for %.0fs", in->override_request, timeout);
    }
    if (in->override_clear) {
        if (ap->override_channel >= 0)
            ap_add_reason(out, "user override cleared: channel %d", ap->override_channel);
        ap->override_channel = -1;
        ap->override_expires_at_s = AP_NOT_TIMING;
    }
    if (ap->override_channel >= 0 && ap->override_expires_at_s >= 0.0f && t >= ap->override_expires_at_s) {
        ap_add_reason(out, "user override timed out: channel %d", ap->override_channel);
        ap->override_channel = -1;
        ap->override_expires_at_s = AP_NOT_TIMING;
    }

    /* 7. per-channel desired state + override + dwell-gated actuation */
    for (int i = 0; i < AP_N_CHANNELS; i++) {
        ap_tier_t tier = ap_effective_tier(cfg, i);
        ap_chstate_t desired;
        if (tier == AP_TIER_T1) desired = AP_CH_ON;
        else if (tier == AP_TIER_T2) desired = t2_target;
        else desired = t3_target;

        bool overridden = false;
        if (ap->override_channel == i && ap->override_expires_at_s >= 0.0f && desired == AP_CH_SHED &&
            !(tier == AP_TIER_T3 && hard_floor_shed_t3)) {
            desired = AP_CH_ON;
            overridden = true;
            ap_add_reason(out, "channel %d kept ON by user override", i);
        }

        ap_channel_state_t *ch = &ap->channels[i];
        float elapsed = t - ch->last_transition_s;
        if (desired != ch->state) {
            float min_dwell = (ch->state == AP_CH_ON) ? cfg->dwell_on_s : cfg->dwell_off_s;
            if (elapsed >= min_dwell) {
                ch->state = desired;
                ch->last_transition_s = t;
                ap_add_reason(out, "channel %d (%d) -> %d", i, (int)tier, (int)desired);
            } else if (!overridden) {
                ap_add_reason(out, "channel %d (%d) desired %d deferred: dwell %.0f/%.0fs",
                              i, (int)tier, (int)desired, elapsed, min_dwell);
            }
        }
        out->channel_state[i] = ch->state;
    }

    /* invariant: T1 is never shed or deferred */
    for (int i = 0; i < AP_N_CHANNELS; i++) {
        if (ap_effective_tier(cfg, i) == AP_TIER_T1) {
            /* defensive: force back to ON if this invariant is ever violated,
             * matching the hard fail-safe philosophy of 05 Sec.6 (never shed
             * on unreliable logic either). Also flagged via assert in debug
             * builds (see test_autopilot_host.c which runs with NDEBUG unset). */
            if (out->channel_state[i] != AP_CH_ON) {
                out->channel_state[i] = AP_CH_ON;
                ap->channels[i].state = AP_CH_ON;
                ap_add_reason(out, "INVARIANT VIOLATION corrected: T1 channel %d forced ON", i);
            }
        }
    }

    float est_backup_min = 0.0f;
    bool have_backup = in->load_w > 1e-6f;
    if (have_backup) est_backup_min = 60.0f * e_usable_wh / in->load_w;

    out->have_est_backup_min = have_backup;
    out->est_backup_min = est_backup_min;
    out->mode = mode;
    out->e_usable_wh = e_usable_wh;
    out->outage_active = !in->grid_ok;
    out->pre_outage_active = boost_active;
    out->charger_command_active = charger_command_active;
    ap->mode = mode;
}
