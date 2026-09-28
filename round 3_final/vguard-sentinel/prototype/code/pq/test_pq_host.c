/* pq/test_pq_host.c -- standalone host unit test for the C PQ analyser.
 * Build & run via `make test` (see Makefile). No framework dependency.
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "pq.h"

static int g_failures = 0;
#define CHECK(cond, msg) do { \
    if (!(cond)) { fprintf(stderr, "FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); g_failures++; } \
} while (0)

#define PI 3.14159265358979323846

/* 230 V / 50 Hz, 40% dip (0.4 pu) for 5 cycles starting at 0.5 s. */
static void test_sag(void) {
    float fs = 4000.0f, f0 = 50.0f, vnom = 230.0f;
    pq_t pq;
    pq_init(&pq, fs, f0, vnom);

    double vpk = vnom * sqrt(2.0);
    int n = (int)(1.5 * fs);
    int n_events = 0;
    pq_event_t got;
    for (int i = 0; i < n; i++) {
        double t = i / (double)fs;
        double scale = (t >= 0.5 && t < 0.5 + 5.0 / 50.0) ? 0.4 : 1.0;
        float v = (float)(vpk * scale * sin(2 * PI * f0 * t));
        pq_push_sample(&pq, v);
        pq_event_t ev;
        while (pq_poll_event(&pq, &ev)) { got = ev; n_events++; }
    }
    CHECK(n_events == 1, "expected exactly one SAG event");
    if (n_events == 1) {
        CHECK(got.type == PQ_TYPE_SAG, "event type should be SAG");
        CHECK(fabsf(got.magnitude_pu - 0.4f) < 0.03f, "magnitude should be ~0.4 pu");
        CHECK(abs((int)got.duration_ms - 100) <= 5, "duration should be ~100 ms (5 cycles)");
    }
}

/* THD: fundamental + 5th harmonic at 5% amplitude -> THD should read ~5%. */
static void test_thd(void) {
    float fs = 4000.0f, f0 = 50.0f, vnom = 230.0f;
    pq_t pq;
    pq_init(&pq, fs, f0, vnom);
    pq.thd_excursion_pct = 1000.0f; /* disable event emission, just check the reading */

    double vpk = vnom * sqrt(2.0);
    int n = (int)(0.5 * fs);
    for (int i = 0; i < n; i++) {
        double t = i / (double)fs;
        float v = (float)(vpk * sin(2 * PI * f0 * t) + 0.05 * vpk * sin(2 * PI * 5 * f0 * t));
        pq_push_sample(&pq, v);
    }
    CHECK(fabsf(pq.thd_pct - 5.0f) < 0.5f, "THD should read ~5%");
}

/* A clean waveform must never emit any event. */
static void test_no_false_positive(void) {
    float fs = 4000.0f, f0 = 50.0f, vnom = 230.0f;
    pq_t pq;
    pq_init(&pq, fs, f0, vnom);
    double vpk = vnom * sqrt(2.0);
    int n = (int)(2.0 * fs);
    int n_events = 0;
    for (int i = 0; i < n; i++) {
        double t = i / (double)fs;
        float v = (float)(vpk * sin(2 * PI * f0 * t));
        pq_push_sample(&pq, v);
        pq_event_t ev;
        while (pq_poll_event(&pq, &ev)) n_events++;
    }
    CHECK(n_events == 0, "a clean 230V/50Hz sine must not emit any PQ event");
}

int main(void) {
    test_sag();
    test_thd();
    test_no_false_positive();
    if (g_failures == 0) {
        printf("OK: all pq host tests passed\n");
        return 0;
    }
    printf("FAILED: %d check(s)\n", g_failures);
    return 1;
}
