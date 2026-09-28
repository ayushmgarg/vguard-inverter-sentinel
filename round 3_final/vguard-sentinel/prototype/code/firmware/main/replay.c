/* firmware/main/replay.c -- see replay.h. */
#include "replay.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define REPLAY_LINE_MAX 512
#define REPLAY_N_FIELDS (CYCLE_FEAT_N_DYNAMIC + CYCLE_FEAT_N_STATIC)

long replay_run(sentinel_ctx_t *ctx, replay_state_t *state, const char *path) {
    if (!ctx || !state || !path) return -1;

    FILE *f = fopen(path, "r");
    if (!f) return -2;

    state->active = true;
    long ok = 0, skipped = 0;

    char line[REPLAY_LINE_MAX];
    while (fgets(line, sizeof(line), f)) {
        float vals[REPLAY_N_FIELDS];
        int n = 0;
        char *save = NULL;
        char *tok = strtok_r(line, ",\r\n", &save);
        while (tok && n < REPLAY_N_FIELDS) {
            char *endptr = NULL;
            vals[n] = strtof(tok, &endptr);
            if (endptr == tok) break; /* not a number -- malformed line */
            n++;
            tok = strtok_r(NULL, ",\r\n", &save);
        }
        if (n != REPLAY_N_FIELDS) {
            skipped++;
            continue;
        }
        sentinel_core_inject_cycle_and_infer(ctx, &vals[0], &vals[CYCLE_FEAT_N_DYNAMIC]);
        ok++;
    }
    fclose(f);

    state->cycles_replayed += ok;
    (void)skipped; /* logged by the caller if it wants to surface a warning --
                       this module keeps no logging dependency of its own */
    return ok;
}
