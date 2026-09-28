/* nilm/event_detector_main.c -- host CLI used by tests/test_nilm.py to check
 * that the C detector+pairing emit the same events as the Python port on an
 * identical stream.
 *
 * stdin:  CSV lines "t,P,Q,V" (no header), one row per frame.
 * stdout: CSV lines "t0,t_off,dP,dQ,t_settle_s,A_tr,dur_s,paired,kind" for
 *         every emitted event, after ON/OFF pairing.
 *
 * Build: `make` in nilm/ (see Makefile). gcc -std=c99 -O2 -lm.
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "event_detector.h"

static ev_event_t g_events[EV_MAX_EVENTS];

int main(int argc, char **argv) {
    float rate_hz = 3.125f;
    if (argc > 1) rate_hz = (float)atof(argv[1]);

    ev_det_t det;
    ev_init(&det, rate_hz);

    int n_events = 0;
    float t, P, Q, V;
    char line[256];
    while (fgets(line, sizeof(line), stdin)) {
        if (sscanf(line, "%f,%f,%f,%f", &t, &P, &Q, &V) != 4) continue;
        ev_event_t ev;
        if (ev_push(&det, t, P, Q, V, &ev)) {
            if (n_events < EV_MAX_EVENTS) {
                g_events[n_events++] = ev;
            }
        }
    }

    ev_pair(g_events, n_events, 24.0f * 3600.0f);

    for (int i = 0; i < n_events; i++) {
        ev_event_t *e = &g_events[i];
        printf("%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%d,%d\n",
               e->t0, isnan(e->t_off) ? -1.0f : e->t_off, e->dP, e->dQ,
               e->t_settle_s, e->A_tr, isnan(e->dur_s) ? -1.0f : e->dur_s,
               e->paired, e->kind);
    }
    return 0;
}
