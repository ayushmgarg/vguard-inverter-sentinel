/* firmware/main/sentinel_types.h -- shared, portable (no ESP-IDF, no FreeRTOS) types
 * used by both the ESP32 firmware (main.c + FreeRTOS tasks) and the host simulator
 * (host/sentinel_host_sim.c). C99 only.
 */
#ifndef SENTINEL_TYPES_H
#define SENTINEL_TYPES_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* One immutable sample per second, CONTRACTS.md §1 columns (sim-only fields kept for
 * host replay against ground truth; a real device never populates soc_true/soh_true).
 * "Immutable" per the coding-style rule: producers publish a *new* Sample into the
 * ring by index; nothing here is ever mutated in place after being written. */
typedef struct {
    double t;          /* epoch seconds */
    float  I;           /* A, +charge/-discharge (CONTRACTS §1 convention) */
    float  V;           /* V terminal */
    float  T;           /* deg C battery */
    int    grid;         /* 0/1 mains present */
    float  P_load;      /* W, AC load (0 if no AFE) */
    float  soc_true;     /* NAN on real hardware; sim ground truth only */
    float  soh_true;     /* NAN on real hardware; sim ground truth only */
} sentinel_sample_t;

#define SENTINEL_RING_LEN 8   /* small ring: tasks consume by index within the same
                                  1 s tick window, design 04 §2 "one Sample per
                                  second on a ring; tasks read by index" */

typedef struct {
    sentinel_sample_t buf[SENTINEL_RING_LEN];
    uint32_t head;      /* index of the next slot to write */
} sentinel_sample_ring_t;

static inline void sentinel_ring_init(sentinel_sample_ring_t *r) {
    r->head = 0;
}

/* Publish a new immutable Sample (copy-in; never mutates a slot that a reader may
 * still be looking at from the *previous* tick -- readers must finish within one
 * tick period, matching the task priority ordering in main/task_config.h). */
static inline void sentinel_ring_push(sentinel_sample_ring_t *r, const sentinel_sample_t *s) {
    r->buf[r->head % SENTINEL_RING_LEN] = *s;
    r->head++;
}

static inline const sentinel_sample_t *sentinel_ring_latest(const sentinel_sample_ring_t *r) {
    if (r->head == 0) return NULL;
    return &r->buf[(r->head - 1) % SENTINEL_RING_LEN];
}

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_TYPES_H */
