/* firmware/main/state_json.c -- see state_json.h. */
#include "state_json.h"

#include <stdio.h>
#include <string.h>

#include "grade.h"

static const char *confidence_name(sentinel_confidence_t c) {
    switch (c) {
        case SENTINEL_CONF_LOW: return "LOW";
        case SENTINEL_CONF_MED: return "MED";
        case SENTINEL_CONF_HIGH: return "HIGH";
        default: return "LOW";
    }
}

/* Coach/PQ sections are emitted as schema-conformant empty containers: this
 * firmware pass wires EKF -> SoH/RUL -> autopilot end to end (the deliverable in
 * scope), but does not also stand up the NILM appliance-labelling pipeline or the
 * PQ monthly rollup on top of a *synthetic* AC stream well enough to publish real
 * numbers here -- see firmware/README.md "honest limits". The nilm/ and pq/
 * components are compiled and available to main.c's afe_3hz/pq tasks; this
 * function just doesn't have populated data to report yet. */
static int append_coach_pq_stub(char *buf, size_t cap, int n) {
    n += snprintf(buf + n, (size_t)n < cap ? cap - (size_t)n : 0,
        "\"coach\":{\"appliances\":[],\"events\":[],\"unknown_clusters\":[]},"
        "\"pq\":{\"events\":[],\"monthly_rollup\":{}},");
    return n;
}

int state_json_build(const sentinel_state_t *st,
                      const state_json_channel_cfg_t channels[AP_N_CHANNELS],
                      const state_json_extra_t *extra,
                      char *buf, size_t buf_cap) {
    if (!st || !channels || !extra || !buf) return -1;
    int n = 0;
#define APP(...) do { n += snprintf(buf + n, (size_t)n < buf_cap ? buf_cap - (size_t)n : 0, __VA_ARGS__); } while (0)

    APP("{");

    APP("\"battery\":{\"soc\":%.4f,\"soc_raw_coulomb\":%.4f,\"v\":%.3f,\"i\":%.3f,"
        "\"t\":%.2f,\"r0_mohm\":%.3f,\"soh_r\":%.4f},",
        st->soc, st->soc_raw_coulomb, st->last_V, st->last_I,
        st->last_T, st->r0_ohm * 1000.0, st->soh_r);

    APP("\"model\":{\"soh_p10\":%.2f,\"soh_p50\":%.2f,\"soh_p90\":%.2f,"
        "\"rul_weeks_p10\":%.1f,\"rul_weeks_p50\":%.1f,\"rul_weeks_p90\":%.1f,"
        "\"grade\":\"%s\",\"n_weeks\":%d,\"confidence\":\"%s\",\"replay_banner\":",
        st->soh_p10, st->soh_p50, st->soh_p90,
        st->rul_weeks_p10, st->rul_weeks_p50, st->rul_weeks_p90,
        grade_name(st->grade), st->have_n_weeks ? st->n_weeks : 0,
        confidence_name(st->confidence));
    if (extra->replay_banner) APP("\"%s\"}," , extra->replay_banner);
    else APP("null},");

    int outage_vote = st->outage_active ? 1 : 0;
    APP("\"outage\":{\"grid\":%d,\"votes\":{\"rms\":%s,\"mode_pin\":%s,\"discharge\":%s},"
        "\"since_s\":%.1f},",
        st->outage_active ? 0 : 1,
        outage_vote ? "true" : "false", outage_vote ? "true" : "false", outage_vote ? "true" : "false",
        extra->outage_since_s);

    APP("\"autopilot\":{\"channels\":[");
    for (int i = 0; i < AP_N_CHANNELS; i++) {
        APP("%s{\"name\":\"%s\",\"tier\":\"%s\",\"state\":\"%s\",\"locked\":%s}",
            i ? "," : "",
            channels[i].name, channels[i].tier,
            st->channel_state[i] == AP_CH_SHED ? "SHED" : "ON",
            (st->override_channel == i) ? "true" : "false");
    }
    APP("],\"est_backup_min\":%.1f,\"reasons\":[",
        st->have_est_backup_min ? st->est_backup_min : 0.0f);
    for (int i = 0; i < st->reasons_n && i < 8; i++) {
        APP("%s\"%s\"", i ? "," : "", st->reasons[i]);
    }
    APP("]},");

    n = append_coach_pq_stub(buf, buf_cap, n);

    APP("\"healthlog\":{\"n_records\":%u,\"last_verify_ok\":",
        (unsigned)st->healthlog_records);
    if (extra->have_healthlog_verify) APP("%s}", extra->healthlog_last_verify_ok ? "true" : "false");
    else APP("null}");

    APP("}");
#undef APP

    if ((size_t)n >= buf_cap) return -1;
    return n;
}

int state_json_write_file(const char *path, const sentinel_state_t *st,
                           const state_json_channel_cfg_t channels[AP_N_CHANNELS],
                           const state_json_extra_t *extra) {
    static char buf[8192];
    int n = state_json_build(st, channels, extra, buf, sizeof(buf));
    if (n < 0) return -1;

    char tmp_path[512];
    snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", path);

    FILE *f = fopen(tmp_path, "w");
    if (!f) return -2;
    size_t written = fwrite(buf, 1, (size_t)n, f);
    int close_rc = fclose(f);
    if (written != (size_t)n || close_rc != 0) return -3;

    if (rename(tmp_path, path) != 0) return -4;
    return 0;
}
