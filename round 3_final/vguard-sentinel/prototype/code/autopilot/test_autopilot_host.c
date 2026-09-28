/* test_autopilot_host.c -- host-buildable C test harness for autopilot.c.
 *
 * Two modes:
 *   (no args)       run a scripted 50-scenario table (design 11 Sec.1.3
 *                   style: varying SoC, load mix, durations, grid state,
 *                   hw-lock, config, override, pre-charge) and print a
 *                   pass/fail line per scenario plus a summary. Exit code
 *                   0 iff all scenarios pass.
 *   --parity FILE   replay the shared CFG/STEP scenario file (see
 *                   parity_scenarios.txt) and print one CSV line per STEP
 *                   ("ch0,ch1,ch2,ch3,mode") for tests/test_autopilot.py
 *                   to diff against controller.py on the same table.
 *
 * Honesty label: this is a HOST SIMULATION of the scripted-scenario bench
 * described in design 11 Sec.1.3 ("hardware-in-the-loop bench:
 * programmable AC source, 4 contactors, load bank, battery simulator").
 * No hardware is exercised here -- see autopilot/README.md.
 */
#include "autopilot.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

/* ------------------------------------------------------------------ */
/* Shared CFG/STEP parity-file replay                                  */
/* ------------------------------------------------------------------ */

static int run_parity(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        return 2;
    }
    ap_t ap;
    ap_config_t cfg = ap_default_config();
    int have_cfg = 0;
    char line[512];
    while (fgets(line, sizeof(line), f)) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\0') continue;
        if (strncmp(line, "CFG", 3) == 0) {
            int t0, hw0, t1, hw1, t2, hw2, t3, hw3, configured, charger;
            float c_rated, v_nom, peukert_n;
            int n = sscanf(line + 3, "%d %d %d %d %d %d %d %d %d %d %f %f %f",
                            &t0, &hw0, &t1, &hw1, &t2, &hw2, &t3, &hw3,
                            &configured, &charger, &c_rated, &v_nom, &peukert_n);
            if (n != 13) { fprintf(stderr, "bad CFG line: %s", line); fclose(f); return 2; }
            cfg = ap_default_config();
            cfg.channels[0].tier = (ap_tier_t)t0; cfg.channels[0].hw_locked_t1 = hw0;
            cfg.channels[1].tier = (ap_tier_t)t1; cfg.channels[1].hw_locked_t1 = hw1;
            cfg.channels[2].tier = (ap_tier_t)t2; cfg.channels[2].hw_locked_t1 = hw2;
            cfg.channels[3].tier = (ap_tier_t)t3; cfg.channels[3].hw_locked_t1 = hw3;
            cfg.configured = configured;
            cfg.charger_commandable = charger;
            cfg.c_rated_ah = c_rated;
            cfg.v_nominal = v_nom;
            cfg.peukert_n = peukert_n;
            ap_init(&ap, &cfg);
            have_cfg = 1;
        } else if (strncmp(line, "STEP", 4) == 0) {
            if (!have_cfg) { fprintf(stderr, "STEP before CFG\n"); fclose(f); return 2; }
            ap_input_t in;
            memset(&in, 0, sizeof(in));
            float t, soc, soh, load_w, temp_c, i_fcst, fcst_t1_wh;
            int grid_ok, hour, dow;
            float outage_prob, outage_conf, actual_decline, forecast_decline;
            int override_req;
            float override_timeout_s;
            int override_clear;
            int n = sscanf(line + 4, "%f %f %f %d %f %d %d %f %f %f %f %f %f %f %d %f %d",
                            &t, &soc, &soh, &grid_ok, &load_w, &hour, &dow, &temp_c,
                            &i_fcst, &fcst_t1_wh, &outage_prob, &outage_conf,
                            &actual_decline, &forecast_decline, &override_req,
                            &override_timeout_s, &override_clear);
            if (n != 17) { fprintf(stderr, "bad STEP line: %s", line); fclose(f); return 2; }
            in.t = t; in.soc = soc; in.soh = soh; in.grid_ok = grid_ok;
            in.load_w = load_w; in.hour = hour; in.dow = dow; in.temp_c = temp_c;
            in.i_forecast_a = i_fcst; in.fcst_t1_wh = fcst_t1_wh;
            in.have_outage_forecast = (outage_prob >= 0.0f && outage_conf >= 0.0f);
            in.outage_prob_h3 = outage_prob; in.outage_conf = outage_conf;
            in.have_decline_rates = (actual_decline > -1e8f && forecast_decline > -1e8f);
            in.actual_decline_pct_per_min = actual_decline;
            in.forecast_decline_pct_per_min = forecast_decline;
            in.override_request = override_req;
            in.have_override_timeout = (override_timeout_s >= 0.0f);
            in.override_timeout_s = override_timeout_s;
            in.override_clear = override_clear;

            ap_output_t out;
            ap_evaluate(&ap, &in, &out);
            printf("%d,%d,%d,%d,%d\n",
                   (int)out.channel_state[0], (int)out.channel_state[1],
                   (int)out.channel_state[2], (int)out.channel_state[3], (int)out.mode);
        }
    }
    fclose(f);
    return 0;
}

/* ------------------------------------------------------------------ */
/* Scripted 50-scenario table                                          */
/* ------------------------------------------------------------------ */

#define MAX_STEPS 40
#define MAX_TRANSITIONS 40

typedef struct {
    char name[64];
    ap_config_t cfg;
    ap_input_t steps[MAX_STEPS];
    int n_steps;
    int check_ladder_exact;   /* enforce the strict 40%/55% T3 shed/restore check */
} scenario_t;

static ap_input_t mk_input(float t, float soc, float soh, int grid_ok, float load_w,
                            int hour, int dow, int override_req) {
    ap_input_t in;
    memset(&in, 0, sizeof(in));
    in.t = t; in.soc = soc; in.soh = soh; in.grid_ok = grid_ok; in.load_w = load_w;
    in.hour = hour; in.dow = dow; in.temp_c = 25.0f; in.i_forecast_a = 5.0f;
    in.fcst_t1_wh = 30.0f;
    in.override_request = override_req;
    in.override_timeout_s = -1.0f; in.have_override_timeout = false;
    return in;
}

/* Group A: pure SoC-ladder drain+recover arcs (grid connected, low fcst so
 * the hard floor never fires) -- checks the exact 40%/55% ladder. */
static void build_group_a(scenario_t *arr, int base_idx, int count) {
    for (int i = 0; i < count; i++) {
        scenario_t *s = &arr[base_idx + i];
        snprintf(s->name, sizeof(s->name), "A%02d ladder-drain-recover start=%.0f%%", i, 90.0f - i * 2.0f);
        s->cfg = ap_default_config();
        s->cfg.configured = true;
        s->cfg.channels[0].tier = AP_TIER_T1;
        s->cfg.channels[1].tier = AP_TIER_T2;
        s->cfg.channels[2].tier = AP_TIER_T3;
        s->cfg.channels[3].tier = AP_TIER_T3;
        s->cfg.c_rated_ah = 100.0f + i * 2.0f;

        float start_soc = (90.0f - i * 2.0f) / 100.0f;   /* 90% down to ~52% across i */
        float end_soc = 0.35f;
        float recover_soc = 0.60f;
        int n = 0;
        float t = 0.0f;
        /* drain phase: 6 steps, 60 s apart until dwell (300s) then held long enough to shed */
        int drain_steps = 8;
        for (int k = 0; k < drain_steps; k++) {
            float frac = (float)k / (float)(drain_steps - 1);
            float soc = start_soc + (end_soc - start_soc) * frac;
            s->steps[n++] = mk_input(t, soc, 0.95f, 1 /* grid ok */, 80.0f + i, 12, i % 7, -1);
            t += 60.0f;
        }
        /* hold at end_soc long enough for dwell (300s) to clear so T3 actually sheds */
        for (int k = 0; k < 4; k++) {
            s->steps[n++] = mk_input(t, end_soc, 0.95f, 1, 80.0f + i, 12, i % 7, -1);
            t += 90.0f;
        }
        /* recover phase: climb back to restore threshold and hold past OFF dwell (180s) */
        int recover_steps = 6;
        for (int k = 0; k < recover_steps; k++) {
            float frac = (float)k / (float)(recover_steps - 1);
            float soc = end_soc + (recover_soc - end_soc) * frac;
            s->steps[n++] = mk_input(t, soc, 0.95f, 1, 80.0f + i, 12, i % 7, -1);
            t += 60.0f;
        }
        for (int k = 0; k < 3; k++) {
            s->steps[n++] = mk_input(t, recover_soc, 0.95f, 1, 80.0f + i, 12, i % 7, -1);
            t += 90.0f;
        }
        s->n_steps = n;
        s->check_ladder_exact = 1;
    }
}

/* Group B: real-outage / hard-floor scenarios (grid down, high forecast
 * demand relative to capacity) -- T1-never-shed and dwell/chatter checks
 * still apply, but not the strict 40/55 ladder check (hard floor may shed
 * above 40%). */
static void build_group_b(scenario_t *arr, int base_idx, int count) {
    for (int i = 0; i < count; i++) {
        scenario_t *s = &arr[base_idx + i];
        snprintf(s->name, sizeof(s->name), "B%02d outage-hard-floor cap=%.0fAh", i, 60.0f + i * 5.0f);
        s->cfg = ap_default_config();
        s->cfg.configured = true;
        s->cfg.channels[0].tier = AP_TIER_T1;
        s->cfg.channels[1].tier = AP_TIER_T2;
        s->cfg.channels[2].tier = AP_TIER_T3;
        s->cfg.channels[3].tier = AP_TIER_T3;
        s->cfg.c_rated_ah = 60.0f + i * 5.0f;   /* smaller battery -> hard floor bites sooner */

        int n = 0;
        float t = 0.0f;
        float soc = 0.85f - (i % 5) * 0.05f;
        for (int k = 0; k < 6; k++) {
            s->steps[n++] = mk_input(t, soc, 0.90f, 0 /* grid out */, 300.0f + i * 10.0f, 19, i % 7, -1);
            s->steps[n - 1].fcst_t1_wh = 400.0f + i * 20.0f;  /* high demand vs capacity -> hard floor */
            t += 90.0f;
            soc -= 0.01f;
        }
        s->n_steps = n;
        s->check_ladder_exact = 0;
    }
}

/* Group C: override, hw-lock, unconfigured -- T1-never-shed, dwell/chatter
 * checks apply; ladder check disabled since override intentionally defeats it. */
static void build_group_c(scenario_t *arr, int base_idx, int count) {
    for (int i = 0; i < count; i++) {
        scenario_t *s = &arr[base_idx + i];
        int mode = i % 3;  /* 0=override, 1=hw-lock, 2=unconfigured */
        snprintf(s->name, sizeof(s->name), "C%02d %s", i,
                 mode == 0 ? "override" : (mode == 1 ? "hw-lock" : "unconfigured"));
        s->cfg = ap_default_config();
        s->cfg.channels[0].tier = AP_TIER_T1;
        s->cfg.channels[1].tier = AP_TIER_T2;
        s->cfg.channels[2].tier = AP_TIER_T3;
        s->cfg.channels[3].tier = AP_TIER_T3;

        int n = 0;
        float t = 0.0f;
        if (mode == 0) {
            s->cfg.configured = true;
            s->steps[n++] = mk_input(t, 0.30f, 0.90f, 1, 80.0f, 12, i % 7, 2);
            t += 1.0f;
            s->steps[n++] = mk_input(t, 0.30f, 0.90f, 1, 80.0f, 12, i % 7, -1);
            t += 1800.0f + 5.0f;
            s->steps[n++] = mk_input(t, 0.30f, 0.90f, 1, 80.0f, 12, i % 7, -1);
        } else if (mode == 1) {
            s->cfg.configured = true;
            s->cfg.channels[2].hw_locked_t1 = true;  /* forced T1 despite T3 config */
            for (int k = 0; k < 3; k++) {
                s->steps[n++] = mk_input(t, 0.10f - k * 0.01f, 0.90f, 1, 80.0f, 12, i % 7, -1);
                t += 60.0f;
            }
        } else {
            s->cfg.configured = false;   /* fail-safe: all T1 */
            for (int k = 0; k < 3; k++) {
                s->steps[n++] = mk_input(t, 0.05f, 0.90f, 0, 80.0f, 12, i % 7, -1);
                t += 60.0f;
            }
        }
        s->n_steps = n;
        s->check_ladder_exact = 0;
    }
}

static int build_scenarios(scenario_t *arr, int max_count) {
    int n = 0;
    int n_a = 20, n_b = 15, n_c = 15;
    if (n_a + n_b + n_c > max_count) { fprintf(stderr, "scenario table too big\n"); exit(2); }
    build_group_a(arr, n, n_a); n += n_a;
    build_group_b(arr, n, n_b); n += n_b;
    build_group_c(arr, n, n_c); n += n_c;
    return n;
}

/* ------------------------------------------------------------------ */
/* Scenario runner + invariant checks                                  */
/* ------------------------------------------------------------------ */

static int run_scenario(const scenario_t *s, char *fail_reason, size_t fail_reason_sz) {
    ap_t ap;
    ap_init(&ap, &s->cfg);

    float last_transition[AP_N_CHANNELS];
    float transition_times[AP_N_CHANNELS][MAX_TRANSITIONS];
    int n_transitions[AP_N_CHANNELS];
    ap_chstate_t prev_state[AP_N_CHANNELS];
    for (int c = 0; c < AP_N_CHANNELS; c++) {
        last_transition[c] = s->n_steps > 0 ? s->steps[0].t : 0.0f;
        n_transitions[c] = 0;
        prev_state[c] = AP_CH_ON;
    }

    for (int i = 0; i < s->n_steps; i++) {
        ap_output_t out;
        ap_evaluate(&ap, &s->steps[i], &out);
        float soc_pct = s->steps[i].soc * 100.0f;

        for (int c = 0; c < AP_N_CHANNELS; c++) {
            ap_tier_t tier = s->cfg.channels[c].hw_locked_t1 ? AP_TIER_T1 :
                              (!s->cfg.configured ? AP_TIER_T1 : s->cfg.channels[c].tier);

            /* (a) T1 never shed while E_avail > 0 */
            if (tier == AP_TIER_T1 && out.e_usable_wh > 0.0f && out.channel_state[c] != AP_CH_ON) {
                snprintf(fail_reason, fail_reason_sz, "T1 channel %d shed at step %d (E_usable=%.1fWh)", c, i, out.e_usable_wh);
                return 0;
            }

            if (out.channel_state[c] != prev_state[c]) {
                /* (c) dwell: gap since last transition must satisfy min dwell */
                float min_dwell = (prev_state[c] == AP_CH_ON) ? s->cfg.dwell_on_s : s->cfg.dwell_off_s;
                float gap = s->steps[i].t - last_transition[c];
                if (gap < min_dwell - 1e-3f) {
                    snprintf(fail_reason, fail_reason_sz, "dwell violation channel %d at step %d: gap=%.1fs < %.1fs", c, i, gap, min_dwell);
                    return 0;
                }
                /* (b) strict ladder check for group A: T3 transitions must occur at the threshold */
                if (s->check_ladder_exact && tier == AP_TIER_T3) {
                    if (out.channel_state[c] == AP_CH_SHED && soc_pct > s->cfg.shed_t3_soc_pct + 0.5f) {
                        snprintf(fail_reason, fail_reason_sz, "T3 channel %d shed above threshold at step %d: SoC=%.1f%%", c, i, soc_pct);
                        return 0;
                    }
                    if (out.channel_state[c] == AP_CH_ON && soc_pct < s->cfg.restore_t3_soc_pct - 0.5f) {
                        snprintf(fail_reason, fail_reason_sz, "T3 channel %d restored below threshold at step %d: SoC=%.1f%%", c, i, soc_pct);
                        return 0;
                    }
                }
                if (n_transitions[c] < MAX_TRANSITIONS) {
                    transition_times[c][n_transitions[c]] = s->steps[i].t;
                    n_transitions[c]++;
                }
                last_transition[c] = s->steps[i].t;
                prev_state[c] = out.channel_state[c];
            }
        }
    }

    /* (d) no chatter: > 2 transitions/channel/10 min (600 s) sliding window */
    for (int c = 0; c < AP_N_CHANNELS; c++) {
        for (int a = 0; a < n_transitions[c]; a++) {
            int count = 0;
            for (int b = 0; b < n_transitions[c]; b++) {
                if (transition_times[c][b] >= transition_times[c][a] &&
                    transition_times[c][b] < transition_times[c][a] + 600.0f) {
                    count++;
                }
            }
            if (count > 2) {
                snprintf(fail_reason, fail_reason_sz, "chatter on channel %d: %d transitions within 10 min starting at t=%.0f", c, count, transition_times[c][a]);
                return 0;
            }
        }
    }

    fail_reason[0] = '\0';
    return 1;
}

static int run_all_scenarios(void) {
    scenario_t scenarios[50];
    int n = build_scenarios(scenarios, 50);
    int n_pass = 0;
    char reason[256];
    for (int i = 0; i < n; i++) {
        int ok = run_scenario(&scenarios[i], reason, sizeof(reason));
        printf("[%s] %-46s %s\n", ok ? "PASS" : "FAIL", scenarios[i].name, ok ? "" : reason);
        if (ok) n_pass++;
    }
    printf("---\n%d/%d scenarios passed\n", n_pass, n);
    return (n_pass == n) ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc >= 3 && strcmp(argv[1], "--parity") == 0) {
        return run_parity(argv[2]);
    }
    return run_all_scenarios();
}
