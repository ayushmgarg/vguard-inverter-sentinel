/* pq/pq_main.c -- host CLI used by tests/test_pq.py to check that the C
 * analyser emits the same events as the Python port on an identical
 * waveform.
 *
 * stdin:  one float voltage sample per line.
 * argv:   [fs_hz] [f_nominal] [v_nominal]  (defaults 4000 50 230)
 * stdout: CSV "ts_epoch_ms,type,magnitude_pu,duration_ms,pre_V,post_V,thd_pct"
 *         for every emitted event.
 *
 * Build: `make` in pq/ (see Makefile). gcc -std=c99 -O2 -lm.
 */
#include <stdio.h>
#include <stdlib.h>
#include "pq.h"

int main(int argc, char **argv) {
    float fs = 4000.0f, f0 = 50.0f, vnom = 230.0f;
    if (argc > 1) fs = (float)atof(argv[1]);
    if (argc > 2) f0 = (float)atof(argv[2]);
    if (argc > 3) vnom = (float)atof(argv[3]);

    pq_t pq;
    pq_init(&pq, fs, f0, vnom);

    char line[128];
    while (fgets(line, sizeof(line), stdin)) {
        float v;
        if (sscanf(line, "%f", &v) != 1) continue;
        pq_push_sample(&pq, v);
        pq_event_t ev;
        while (pq_poll_event(&pq, &ev)) {
            printf("%u,%u,%.6f,%u,%.4f,%.4f,%.4f\n",
                   ev.ts_epoch_ms, (unsigned)ev.type, ev.magnitude_pu, ev.duration_ms,
                   ev.pre_event_rms_V, ev.post_event_rms_V, ev.thd_pct);
        }
    }
    return 0;
}
