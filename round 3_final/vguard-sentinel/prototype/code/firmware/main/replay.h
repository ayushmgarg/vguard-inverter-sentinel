/* firmware/main/replay.h -- demo-mode replay: feeds ml_infer from a stored feature
 * trajectory file as if cycles had happened, design 04 §6 / CONFIG_SENTINEL_DEMO_REPLAY.
 *
 * File format: plain text, one cycle per line, CSV of the 14 dynamic + 6 static raw
 * (not standardised) feature values in schema order (features/schema.py
 * DYNAMIC_FEATURES then STATIC_FEATURES), e.g.:
 *   1.02,1.01,0.37,0.23,0.57,0.14,1.01,0.55,0.97,0.0,0.82,36.3,0.18,-0.45,6.8,0.88,5.2,0.05,0.0,0.13
 *
 * Portable C99 (plain stdio) -- works unmodified against ESP-IDF's LittleFS VFS
 * (which exposes standard fopen/fread once storage_init() has mounted it) and
 * against a host filesystem path, so this file needs no #ifdef ESP_PLATFORM
 * branching, unlike the sensor/GPIO drivers in this directory.
 */
#ifndef SENTINEL_REPLAY_H
#define SENTINEL_REPLAY_H

#include <stdbool.h>

#include "sentinel_core.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    bool active;
    long cycles_replayed;
} replay_state_t;

/* Reads `path` line by line, injecting each row into ctx via
 * sentinel_core_inject_cycle_and_infer(). Sets state->active=true for the
 * duration (and leaves it true afterwards -- CONTRACTS' dashboard
 * "model.replay_banner" should stay up until the caller explicitly resets it,
 * so a demo audience knows the numbers they are looking at came from a replay
 * file, not the live battery). Returns the number of cycles replayed (>=0), or
 * negative on a file-open/parse error (a malformed line is skipped with a
 * count of skipped lines logged, not treated as fatal -- explicit error
 * handling without aborting a whole demo over one bad line). */
long replay_run(sentinel_ctx_t *ctx, replay_state_t *state, const char *path);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_REPLAY_H */
