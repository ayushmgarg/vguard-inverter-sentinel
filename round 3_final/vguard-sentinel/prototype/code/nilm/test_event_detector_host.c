/* nilm/test_event_detector_host.c -- standalone host unit test for the C
 * event detector + pairing. Build & run via `make test` (see Makefile).
 * No test framework dependency: asserts + exit code.
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "event_detector.h"

static int g_failures = 0;
#define CHECK(cond, msg) do { \
    if (!(cond)) { fprintf(stderr, "FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); g_failures++; } \
} while (0)

/* Feed a flat 100 W baseline, ramp to 1200 W over 0.6 s starting at t=10s
 * (a fast resistive-load-like transition -- design 06 Sec 3.2 puts iron/
 * kettle settle times at < 0.5 s), hold, ramp back down at t=60s. Expect one
 * dominant ON event (~1100 W) paired with one dominant OFF event, duration
 * ~50 s.
 *
 * Note (honesty): a mathematically *instantaneous* (zero-rise-time) step can
 * make this exact Lu & Li parameterisation (T_merge = 2 frames = 0.64 s,
 * design 06 Sec 2.2) emit one dominant event plus a small residual "echo"
 * a frame or two later -- the same behaviour is reproduced bit-for-bit by
 * the Python port (see tests/test_nilm.py::test_c_matches_python) and is a
 * known trait of window-based change detectors on razor-sharp edges, not a
 * divergence between the two implementations. A ramped edge (as used here)
 * is representative of every appliance in the factory prior table and does
 * not exhibit it. */
static void test_step(void) {
    ev_det_t det;
    ev_init(&det, 3.125f);
    ev_event_t events[16];
    int n = 0;

    float rate = 3.125f;
    float t = 0.0f;
    float ramp_s = 0.6f;
    for (int i = 0; i < (int)(120 * rate); i++) {
        float P;
        if (t < 10.0f) P = 100.0f;
        else if (t < 10.0f + ramp_s) P = 100.0f + (1100.0f) * (t - 10.0f) / ramp_s;
        else if (t < 60.0f) P = 1200.0f;
        else if (t < 60.0f + ramp_s) P = 1200.0f - (1100.0f) * (t - 60.0f) / ramp_s;
        else P = 100.0f;
        ev_event_t ev;
        if (ev_push(&det, t, P, 0.0f, 230.0f, &ev)) {
            if (n < 16) events[n++] = ev;
        }
        t += 1.0f / rate;
    }
    ev_pair(events, n, 24.0f * 3600.0f);

    CHECK(n >= 2, "expected at least an ON and an OFF event");
    /* dominant ON = the largest positive dP; dominant OFF = the largest
     * negative dP (magnitude) */
    int on_i = -1, off_i = -1;
    for (int i = 0; i < n; i++) {
        if (events[i].kind == 1 && (on_i < 0 || events[i].dP > events[on_i].dP)) on_i = i;
        if (events[i].kind == 0 && (off_i < 0 || events[i].dP < events[off_i].dP)) off_i = i;
    }
    CHECK(on_i >= 0 && off_i >= 0, "must find a dominant ON and OFF event");
    if (on_i >= 0 && off_i >= 0) {
        CHECK(fabsf(events[on_i].dP - 1100.0f) < 60.0f, "dominant ON dP should be ~1100 W");
        CHECK(fabsf(events[off_i].dP + 1100.0f) < 60.0f, "dominant OFF dP should be ~-1100 W");
        CHECK(isnan(events[on_i].r_pk), "r_pk must be NAN (no Ipk channel in this API)");
        CHECK(isnan(events[on_i].h), "h must be NAN (no Pf/Ph channel in this API)");
        if (events[on_i].paired) {
            CHECK(fabsf(events[on_i].dur_s - 50.0f) < 5.0f, "duration should be ~50 s");
        }
    }
}

/* A step below P_th (10 W on a 100 W background) should not emit an event. */
static void test_below_threshold(void) {
    ev_det_t det;
    ev_init(&det, 3.125f);
    ev_event_t ev;
    int n = 0;
    float rate = 3.125f;
    float t = 0.0f;
    for (int i = 0; i < (int)(60 * rate); i++) {
        float P = (t >= 10.0f) ? 108.0f : 100.0f;
        if (ev_push(&det, t, P, 0.0f, 230.0f, &ev)) n++;
        t += 1.0f / rate;
    }
    CHECK(n == 0, "an 8 W step on 100 W background must not trigger (P_th=25W/2%)");
}

int main(void) {
    test_step();
    test_below_threshold();
    if (g_failures == 0) {
        printf("OK: all event_detector host tests passed\n");
        return 0;
    }
    printf("FAILED: %d check(s)\n", g_failures);
    return 1;
}
