/* pq/pq.h -- C99 port of the Grid Shield power-quality analyser (design 07).
 *
 * API per CONTRACTS.md Sec 6:
 *   void pq_push_sample(pq_t*, float v_sample);   // 4 kS/s
 *   int  pq_poll_event(pq_t*, pq_event_t* out);
 *
 * Static buffers only (no malloc); host- and MCU-buildable (gcc -std=c99).
 * Mirrors pq/pq.py's PQProcessor sample-for-sample so the two can be
 * cross-checked on the same waveform (tests/test_pq.py).
 */
#ifndef PQ_H
#define PQ_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PQ_TYPE_SAG            0
#define PQ_TYPE_SWELL          1
#define PQ_TYPE_INTERRUPTION   2
#define PQ_TYPE_FREQ_DEV       3
#define PQ_TYPE_THD_EXCURSION  4

/* design 07 Sec 3 record (measured sizeof ~28 B under standard alignment;
 * the design doc's "~32 B" is an approximation -- see pq/README.md). */
typedef struct {
    uint32_t ts_epoch_ms;
    uint8_t  type;
    float    magnitude_pu;
    uint32_t duration_ms;
    float    pre_event_rms_V;
    float    post_event_rms_V;
    float    thd_pct;
} pq_event_t;

#define PQ_HALF_CYCLE_BUF_LEN   128
#define PQ_THD_BLOCK_N          320   /* 4 cycles @ 50 Hz, 4 kS/s */
#define PQ_MAX_HARMONIC         39    /* 40th is exactly Nyquist at 4kS/s/50Hz */
#define PQ_FREQ_HIST_LEN        16
#define PQ_EVENT_QUEUE_LEN      64
#define PQ_RING_CAPACITY        1000

typedef struct {
    /* parameters (design 07 Sec 1/2) */
    float fs_hz, f_nominal, v_nominal;
    float sag_pu, swell_pu, interruption_pu, hysteresis_pu;
    int   freq_window_cycles;
    float freq_dev_frac;
    float freq_hysteresis_frac;
    int   thd_window_cycles;
    float thd_excursion_pct;

    float dt_ms, t_ms;
    float prev_sample;
    int   started;

    /* half-cycle RMS */
    float half_cycle_buf[PQ_HALF_CYCLE_BUF_LEN];
    int   half_cycle_n;
    float urms_half;
    float urms_half_ts_ms;

    /* frequency (rolling rising-edge timestamps) */
    float rising_ts[PQ_FREQ_HIST_LEN];
    int   rising_n;     /* number valid, <= freq_window_cycles+1 */
    int   rising_head;  /* circular index of most recent */
    float freq_hz;

    /* THD block */
    float thd_buf[PQ_THD_BLOCK_N];
    int   thd_n;
    float thd_pct;

    /* sag/swell/interruption state machine */
    int   in_event;
    int   event_type;
    float event_start_ms;
    float event_extreme_pu;
    float pre_event_rms;

    /* frequency-deviation state machine */
    int   in_freq_event;
    float freq_event_start_ms;
    float freq_event_extreme;

    /* emitted-event FIFO */
    pq_event_t event_queue[PQ_EVENT_QUEUE_LEN];
    int   eq_head, eq_count;

    /* 1000-event circular history buffer (design 07 Sec 4) */
    pq_event_t ring[PQ_RING_CAPACITY];
    int   ring_count;
    int   ring_head;
} pq_t;

void pq_init(pq_t *pq, float fs_hz, float f_nominal, float v_nominal);
void pq_push_sample(pq_t *pq, float v_sample);
int  pq_poll_event(pq_t *pq, pq_event_t *out);

#ifdef __cplusplus
}
#endif
#endif
