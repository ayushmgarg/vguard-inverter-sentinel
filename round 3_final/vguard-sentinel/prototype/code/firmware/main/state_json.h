/* firmware/main/state_json.h -- serialises sentinel_state_t to the dashboard's JSON
 * schema (dashboard/state_provider.py module docstring; CONTRACTS.md §3/§5).
 *
 * Hand-rolled (no JSON library -- keeps the control-path no-malloc rule and avoids a
 * new firmware dependency for six object literals). Portable C99, no ESP-IDF
 * dependency -- both main.c (writing to LittleFS) and host/sentinel_host_sim.c
 * (writing state.json for `python -m dashboard.app --provider file`) use this.
 */
#ifndef SENTINEL_STATE_JSON_H
#define SENTINEL_STATE_JSON_H

#include <stdbool.h>
#include <stddef.h>

#include "sentinel_core.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const char *name;   /* e.g. "Lights & Router", matches dashboard/fixtures/channels.json style */
    const char *tier;    /* "T1" / "T2" / "T3" */
} state_json_channel_cfg_t;

typedef struct {
    double outage_since_s;
    bool   replay_active;
    const char *replay_banner;    /* NULL -> JSON null */
    bool   healthlog_last_verify_ok;
    bool   have_healthlog_verify;  /* false -> "last_verify_ok": null */
} state_json_extra_t;

/* Renders the full dashboard state object into buf (NUL-terminated). Returns the
 * number of bytes written (excluding the NUL), or -1 if buf_cap was too small
 * (nothing partial is left relied-upon in that case -- caller should retry with a
 * bigger buffer; no truncated JSON is ever written to a file by
 * state_json_write_file). */
int state_json_build(const sentinel_state_t *st,
                      const state_json_channel_cfg_t channels[AP_N_CHANNELS],
                      const state_json_extra_t *extra,
                      char *buf, size_t buf_cap);

/* Writes state_json_build()'s output to `path` atomically-ish (write to
 * "<path>.tmp" then rename -- avoids the dashboard's FileProvider ever reading a
 * half-written file). Returns 0 on success. Host-only convenience (uses
 * stdio/POSIX rename); the ESP32 target writes via storage.c's LittleFS calls
 * instead (see main/storage.h). */
int state_json_write_file(const char *path, const sentinel_state_t *st,
                           const state_json_channel_cfg_t channels[AP_N_CHANNELS],
                           const state_json_extra_t *extra);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_STATE_JSON_H */
