/* firmware/host/sentinel_host_sim.c -- host build of the V-Guard Sentinel control
 * loop: real EKF + cycle segmentation + int8 CNN inference + autopilot + health
 * log, run for real over a CSV replay (CONTRACTS.md §1 columns), with stub
 * "drivers" that just read the CSV instead of I2C/UART/ADC.
 *
 * This links the SAME sentinel_core.c the ESP32 firmware's main.c calls -- see
 * sentinel_core.h's doc comment. The only things genuinely different from the
 * real device here are: (1) samples come from a CSV instead of ina2xx.c/ntc.c,
 * (2) the health-log signer is an OpenSSL software key instead of an ATECC608
 * (exactly test_healthlog_host.c's pattern -- see healthlog_signer below), (3)
 * state.json is written straight to a host path instead of via storage.c's
 * LittleFS. Everything else -- ekf_step, cycle_feat, sentinel_int8_infer,
 * ap_evaluate, hl_append -- is the production algorithm code.
 *
 * Usage:
 *   ./sentinel_host_sim --csv PATH [--manifest PATH] [--out state.json]
 *                        [--max-rows N] [--json-every-s N]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include <openssl/bn.h>
#include <openssl/ec.h>
#include <openssl/ecdsa.h>
#include <openssl/obj_mac.h>

#include "sentinel_core.h"
#include "state_json.h"
#include "grade.h"

#define MAX_LINE 1024
#define SECONDS_PER_DAY 86400.0
#define MAX_TRANSITIONS 64

/* ---- OpenSSL software signer, mirrors healthlog/test_healthlog_host.c exactly
 * (see that file's doc comment: "standing in for the ATECC608 in production") --- */
static int openssl_sign_cb(const uint8_t hash32[HL_HASH_SIZE], uint8_t sig64[HL_SIG_SIZE], void *ctx_) {
    EC_KEY *key = (EC_KEY *)ctx_;
    ECDSA_SIG *sig = ECDSA_do_sign(hash32, (int)HL_HASH_SIZE, key);
    if (!sig) return 1;
    const BIGNUM *r = NULL, *s = NULL;
    ECDSA_SIG_get0(sig, &r, &s);
    memset(sig64, 0, HL_SIG_SIZE);
    BN_bn2binpad(r, sig64, 32);
    BN_bn2binpad(s, sig64 + 32, 32);
    ECDSA_SIG_free(sig);
    return 0;
}

static int export_pubkey_raw(EC_KEY *key, uint8_t out[HL_PUBKEY_SIZE]) {
    const EC_GROUP *group = EC_KEY_get0_group(key);
    const EC_POINT *point = EC_KEY_get0_public_key(key);
    uint8_t buf[65];
    size_t n = EC_POINT_point2oct(group, point, POINT_CONVERSION_UNCOMPRESSED, buf, sizeof(buf), NULL);
    if (n != 65 || buf[0] != 0x04) return -1;
    memcpy(out, buf + 1, HL_PUBKEY_SIZE);
    return 0;
}

/* ---- CSV reading ---------------------------------------------------------- */
typedef struct {
    int idx_t, idx_I, idx_V, idx_T, idx_grid, idx_P_load;
} csv_cols_t;

static int parse_header(char *line, csv_cols_t *c) {
    memset(c, -1, sizeof(*c));
    int i = 0;
    char *tok = strtok(line, ",\r\n");
    while (tok) {
        if (!strcmp(tok, "t")) c->idx_t = i;
        else if (!strcmp(tok, "I")) c->idx_I = i;
        else if (!strcmp(tok, "V")) c->idx_V = i;
        else if (!strcmp(tok, "T")) c->idx_T = i;
        else if (!strcmp(tok, "grid")) c->idx_grid = i;
        else if (!strcmp(tok, "P_load")) c->idx_P_load = i;
        i++;
        tok = strtok(NULL, ",\r\n");
    }
    return (c->idx_t >= 0 && c->idx_I >= 0 && c->idx_V >= 0 && c->idx_T >= 0 && c->idx_grid >= 0) ? 0 : -1;
}

/* Reads C_rated_Ah for `battery_id` out of manifest.csv (CONTRACTS §1 sim data
 * layout, data/sim_1hz/manifest.csv: battery_id,C_rated_Ah,...). Returns 0 on
 * success (fills *out_ah), negative if not found/unreadable -- caller falls
 * back to a documented default rather than failing the whole run. */
static int lookup_c_rated_ah(const char *manifest_path, int battery_id, float *out_ah) {
    FILE *f = fopen(manifest_path, "r");
    if (!f) return -1;
    char line[MAX_LINE];
    if (!fgets(line, sizeof(line), f)) { fclose(f); return -1; }
    int idx_id = -1, idx_ah = -1, i = 0;
    char *tok = strtok(line, ",\r\n");
    while (tok) {
        if (!strcmp(tok, "battery_id")) idx_id = i;
        else if (!strcmp(tok, "C_rated_Ah")) idx_ah = i;
        i++;
        tok = strtok(NULL, ",\r\n");
    }
    if (idx_id < 0 || idx_ah < 0) { fclose(f); return -1; }
    while (fgets(line, sizeof(line), f)) {
        char fields[16][64];
        int n = 0;
        char *t = strtok(line, ",\r\n");
        while (t && n < 16) { strncpy(fields[n], t, 63); fields[n][63] = 0; n++; t = strtok(NULL, ",\r\n"); }
        if (n <= idx_id || n <= idx_ah) continue;
        if (atoi(fields[idx_id]) == battery_id) {
            *out_ah = (float)atof(fields[idx_ah]);
            fclose(f);
            return 0;
        }
    }
    fclose(f);
    return -1;
}

static int extract_battery_id(const char *csv_path) {
    const char *base = strrchr(csv_path, '/');
    base = base ? base + 1 : csv_path;
    int id = -1;
    if (sscanf(base, "battery_%d", &id) == 1) return id;
    return -1;
}

int main(int argc, char **argv) {
    const char *csv_path = NULL;
    const char *manifest_path = NULL;
    const char *out_path = "firmware/host/state.json";
    long max_rows = -1;
    double json_every_s = 60.0; /* "every simulated minute" per the task spec */
    const char *dump_healthlog_path = NULL;
    const char *dump_pubkey_path = NULL;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--csv") && i + 1 < argc) csv_path = argv[++i];
        else if (!strcmp(argv[i], "--manifest") && i + 1 < argc) manifest_path = argv[++i];
        else if (!strcmp(argv[i], "--out") && i + 1 < argc) out_path = argv[++i];
        else if (!strcmp(argv[i], "--max-rows") && i + 1 < argc) max_rows = atol(argv[++i]);
        else if (!strcmp(argv[i], "--json-every-s") && i + 1 < argc) json_every_s = atof(argv[++i]);
        else if (!strcmp(argv[i], "--dump-healthlog") && i + 1 < argc) dump_healthlog_path = argv[++i];
        else if (!strcmp(argv[i], "--dump-pubkey") && i + 1 < argc) dump_pubkey_path = argv[++i];
        else { fprintf(stderr, "unknown arg: %s\n", argv[i]); return 2; }
    }
    if (!csv_path) {
        fprintf(stderr, "usage: %s --csv PATH [--manifest PATH] [--out state.json] [--max-rows N]\n"
                         "          [--dump-healthlog PATH] [--dump-pubkey PATH]\n", argv[0]);
        return 2;
    }

    FILE *f = fopen(csv_path, "r");
    if (!f) { fprintf(stderr, "cannot open %s\n", csv_path); return 1; }
    char line[MAX_LINE];
    if (!fgets(line, sizeof(line), f)) { fprintf(stderr, "empty CSV\n"); return 1; }
    csv_cols_t cols;
    if (parse_header(line, &cols) != 0) { fprintf(stderr, "CSV missing required CONTRACTS §1 columns\n"); return 1; }

    float q_rated_ah = 150.0f; /* documented default if manifest lookup fails */
    int battery_id = extract_battery_id(csv_path);
    if (manifest_path && battery_id >= 0) {
        float ah;
        if (lookup_c_rated_ah(manifest_path, battery_id, &ah) == 0) q_rated_ah = ah;
        else fprintf(stderr, "warning: battery_id %d not found in %s, using default q_rated_ah=%.1f\n", battery_id, manifest_path, q_rated_ah);
    } else {
        fprintf(stderr, "note: no --manifest given or battery id not parseable from filename; using default q_rated_ah=%.1f\n", q_rated_ah);
    }

    /* --- health-log signer: OpenSSL software key, see doc comment above --- */
    EC_KEY *key = EC_KEY_new_by_curve_name(NID_X9_62_prime256v1);
    if (!key || EC_KEY_generate_key(key) != 1) { fprintf(stderr, "EC key generation failed\n"); return 1; }
    uint8_t pubkey[HL_PUBKEY_SIZE];
    if (export_pubkey_raw(key, pubkey) != 0) { fprintf(stderr, "pubkey export failed\n"); return 1; }

    sentinel_config_t cfg;
    sentinel_config_default(&cfg, q_rated_ah);

    sentinel_ctx_t ctx;
    static uint8_t hl_buf[4 * 1024 * 1024]; /* generous for a full CSV replay's worth
                                                of health-log records (host RAM is not
                                                the constrained resource here) */
    if (sentinel_core_init(&ctx, &cfg, openssl_sign_cb, key, hl_buf, sizeof(hl_buf)) != 0) {
        fprintf(stderr, "sentinel_core_init failed\n");
        return 1;
    }

    int selftest_ok = sentinel_core_selftest(&ctx);
    printf("sentinel_int8 golden self-test: %s\n", selftest_ok ? "PASS" : "FAIL");
    if (!selftest_ok) {
        fprintf(stderr, "golden self-test FAILED -- aborting (design 04 §4 step 3: never trust an inference after a failed self-test)\n");
        return 1;
    }

    /* --- summary accumulators --- */
    double soc_min = 1e9, soc_max = -1e9, soc_sum = 0.0;
    long n_soc = 0;
    int last_grade = -2;
    long n_grade_transitions = 0;
    char grade_seq[MAX_TRANSITIONS][16];
    double grade_seq_day[MAX_TRANSITIONS];

    double next_json_t = 0.0;
    double next_minute_t = 0.0;
    long row = 0;

    while (fgets(line, sizeof(line), f)) {
        if (max_rows >= 0 && row >= max_rows) break;
        char *fields[16];
        int nf = 0;
        char *tok = strtok(line, ",\r\n");
        while (tok && nf < 16) { fields[nf++] = tok; tok = strtok(NULL, ",\r\n"); }
        int need = cols.idx_P_load >= 0 ? cols.idx_P_load + 1 : cols.idx_grid + 1;
        if (nf < need) continue;

        sentinel_sample_t s;
        memset(&s, 0, sizeof(s));
        s.t = atof(fields[cols.idx_t]);
        s.I = (float)atof(fields[cols.idx_I]);
        s.V = (float)atof(fields[cols.idx_V]);
        s.T = (float)atof(fields[cols.idx_T]);
        s.grid = atoi(fields[cols.idx_grid]);
        s.P_load = (cols.idx_P_load >= 0 && nf > cols.idx_P_load) ? (float)atof(fields[cols.idx_P_load]) : 0.0f;

        sentinel_core_on_sample(&ctx, &s);

        double soc = ekf_soc(&ctx.ekf);
        if (soc < soc_min) soc_min = soc;
        if (soc > soc_max) soc_max = soc;
        soc_sum += soc;
        n_soc++;

        if (s.t >= next_minute_t) {
            int hour = (int)fmod(s.t / 3600.0, 24.0);
            int dow = (int)fmod(s.t / 86400.0, 7.0);
            sentinel_core_on_minute(&ctx, hour, dow, s.P_load);
            next_minute_t = s.t + 60.0;
        }

        if (ctx.state.grade != last_grade && n_grade_transitions < MAX_TRANSITIONS) {
            snprintf(grade_seq[n_grade_transitions], sizeof(grade_seq[0]), "%s", grade_name(ctx.state.grade));
            grade_seq_day[n_grade_transitions] = s.t / SECONDS_PER_DAY;
            n_grade_transitions++;
            last_grade = ctx.state.grade;
        }

        if (s.t >= next_json_t) {
            state_json_channel_cfg_t channels[AP_N_CHANNELS] = {
                {"Lights & Router", "T1"}, {"Fridge", "T1"}, {"Fan & TV", "T2"}, {"Iron/Heater", "T3"},
            };
            sentinel_state_t st;
            sentinel_core_get_state(&ctx, &st);
            state_json_extra_t extra;
            memset(&extra, 0, sizeof(extra));
            extra.outage_since_s = 0.0;
            extra.replay_active = false;
            extra.replay_banner = NULL;
            extra.have_healthlog_verify = false;
            if (state_json_write_file(out_path, &st, channels, &extra) != 0) {
                fprintf(stderr, "warning: state_json_write_file(%s) failed at t=%.0f\n", out_path, s.t);
            }
            next_json_t = s.t + json_every_s;
        }

        row++;
    }
    fclose(f);

    sentinel_state_t final_st;
    sentinel_core_get_state(&ctx, &final_st);

    int chain_ok = hl_verify_chain(ctx.hl.buf, ctx.hl.len, pubkey);

    /* Optional raw dump for cross-verification from Python (healthlog/healthlog.py's
     * verify_chain(), CONTRACTS §7 "cross-verified between the C and Python
     * implementations" pattern) -- used by tests/test_firmware_host.py. */
    if (dump_healthlog_path) {
        FILE *hf = fopen(dump_healthlog_path, "wb");
        if (hf) { fwrite(ctx.hl.buf, 1, ctx.hl.len, hf); fclose(hf); }
        else fprintf(stderr, "warning: could not write %s\n", dump_healthlog_path);
    }
    if (dump_pubkey_path) {
        FILE *pf = fopen(dump_pubkey_path, "wb");
        if (pf) { fwrite(pubkey, 1, sizeof(pubkey), pf); fclose(pf); }
        else fprintf(stderr, "warning: could not write %s\n", dump_pubkey_path);
    }

    printf("\n=== sentinel_host_sim summary ===\n");
    printf("csv: %s (battery_id=%d, q_rated_ah=%.1f)\n", csv_path, battery_id, q_rated_ah);
    printf("rows processed: %ld\n", row);
    printf("SoC trace: min=%.4f max=%.4f mean=%.4f (n=%ld)\n",
           soc_min, soc_max, n_soc ? soc_sum / n_soc : 0.0, n_soc);
    printf("cycles detected: %ld\n", final_st.n_cycles);
    printf("grade sequence (%ld transitions):\n", n_grade_transitions);
    for (long i = 0; i < n_grade_transitions; i++) {
        printf("  day %8.2f -> %s\n", grade_seq_day[i], grade_seq[i]);
    }
    printf("final: grade=%s soh_p50=%.2f%% rul_weeks_p50=%.1f confidence=%d\n",
           grade_name(final_st.grade), final_st.soh_p50, final_st.rul_weeks_p50, (int)final_st.confidence);
    printf("health-log: %u records, %zu bytes, hl_verify_chain=%s\n",
           final_st.healthlog_records, final_st.healthlog_bytes, chain_ok ? "OK" : "FAILED");
    printf("state.json written to: %s\n", out_path);
    printf("self-test: %s\n", selftest_ok ? "PASS" : "FAIL");

    EC_KEY_free(key);

    if (!selftest_ok || !chain_ok) return 1;
    return 0;
}
