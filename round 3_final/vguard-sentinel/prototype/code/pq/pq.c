/* pq/pq.c -- see pq.h. Mirrors pq/pq.py's PQProcessor. */
#include "pq.h"
#include <math.h>
#include <string.h>

#define PQ_PI 3.14159265358979323846f

static float ring_at_f(const float *buf, int head, int len, int cap, int back) {
    (void)len;
    int idx = head - back;
    while (idx < 0) idx += cap;
    return buf[idx % cap];
}

/* -------------------------------------------------------------------- */
/* Goertzel single-bin magnitude, scaled to sinusoid amplitude. Matches
 * pq.py's compute_thd() (np.fft.rfft on the same block), since a harmonic
 * bin's Goertzel output is the same DFT coefficient the FFT would produce.
 */
static float goertzel_mag(const float *x, int n, float fs, float freq_hz) {
    float w = 2.0f * PQ_PI * freq_hz / fs;
    float coeff = 2.0f * cosf(w);
    float s_prev = 0.0f, s_prev2 = 0.0f;
    for (int i = 0; i < n; i++) {
        float s = x[i] + coeff * s_prev - s_prev2;
        s_prev2 = s_prev;
        s_prev = s;
    }
    float real = s_prev - s_prev2 * cosf(w);
    float imag = s_prev2 * sinf(w);
    return sqrtf(real * real + imag * imag) * (2.0f / (float)n);
}

static float compute_thd(const float *x, int n, float fs, float f0, int max_harmonic) {
    float fundamental = goertzel_mag(x, n, fs, f0);
    if (fundamental < 1e-6f) return 0.0f;
    double harmonics_sq = 0.0;
    for (int h = 2; h <= max_harmonic; h++) {
        float mag = goertzel_mag(x, n, fs, f0 * (float)h);
        harmonics_sq += (double)mag * (double)mag;
    }
    return 100.0f * (float)sqrt(harmonics_sq) / fundamental;
}

/* -------------------------------------------------------------------- */
void pq_init(pq_t *pq, float fs_hz, float f_nominal, float v_nominal) {
    memset(pq, 0, sizeof(*pq));
    pq->fs_hz = fs_hz;
    pq->f_nominal = f_nominal;
    pq->v_nominal = v_nominal;
    pq->sag_pu = 0.9f;
    pq->swell_pu = 1.1f;
    pq->interruption_pu = 0.1f;
    pq->hysteresis_pu = 0.02f;
    pq->freq_window_cycles = 10;
    pq->freq_dev_frac = 0.03f;
    pq->freq_hysteresis_frac = 0.005f;
    pq->thd_window_cycles = 4;
    pq->thd_excursion_pct = 8.0f;

    pq->dt_ms = 1000.0f / fs_hz;
    pq->urms_half = v_nominal;
    pq->freq_hz = f_nominal;
    pq->pre_event_rms = v_nominal;
    pq->freq_event_extreme = f_nominal;
    pq->rising_head = -1;
}

static void pq_push_event(pq_t *pq, const pq_event_t *ev) {
    if (pq->eq_count < PQ_EVENT_QUEUE_LEN) {
        int idx = (pq->eq_head + pq->eq_count) % PQ_EVENT_QUEUE_LEN;
        pq->event_queue[idx] = *ev;
        pq->eq_count++;
    }
    pq->ring_head = (pq->ring_head + 1) % PQ_RING_CAPACITY;
    pq->ring[pq->ring_head] = *ev;
    if (pq->ring_count < PQ_RING_CAPACITY) pq->ring_count++;
}

static void pq_end_event(pq_t *pq, float post_rms) {
    pq_event_t ev;
    memset(&ev, 0, sizeof(ev));
    long duration_ms = (long)(pq->urms_half_ts_ms - pq->event_start_ms + 0.5f);
    if (duration_ms < 0) duration_ms = 0;
    ev.ts_epoch_ms = (uint32_t)(pq->event_start_ms + 0.5f);
    ev.type = (uint8_t)pq->event_type;
    ev.magnitude_pu = pq->event_extreme_pu;
    ev.duration_ms = (uint32_t)duration_ms;
    ev.pre_event_rms_V = pq->pre_event_rms;
    ev.post_event_rms_V = post_rms;
    ev.thd_pct = NAN;
    pq_push_event(pq, &ev);
    pq->in_event = 0;
    pq->pre_event_rms = post_rms;
}

static void pq_start_event(pq_t *pq, int etype, float pu) {
    pq->in_event = 1;
    pq->event_type = etype;
    pq->event_start_ms = pq->urms_half_ts_ms;
    pq->event_extreme_pu = pu;
}

static void check_magnitude_event(pq_t *pq) {
    float pu = pq->urms_half / pq->v_nominal;
    if (!pq->in_event) {
        if (pu < pq->interruption_pu) {
            pq_start_event(pq, PQ_TYPE_INTERRUPTION, pu);
        } else if (pu < pq->sag_pu) {
            pq_start_event(pq, PQ_TYPE_SAG, pu);
        } else if (pu > pq->swell_pu) {
            pq_start_event(pq, PQ_TYPE_SWELL, pu);
        } else {
            pq->pre_event_rms = pq->urms_half;
        }
        return;
    }
    if (pq->event_type == PQ_TYPE_INTERRUPTION && pu >= pq->interruption_pu && pu < pq->sag_pu) {
        pq->event_type = PQ_TYPE_SAG;
        if (pu < pq->event_extreme_pu) pq->event_extreme_pu = pu;
        return;
    }
    if (pq->event_type == PQ_TYPE_SAG && pu < pq->interruption_pu) {
        pq->event_type = PQ_TYPE_INTERRUPTION;
    }
    if (pq->event_type == PQ_TYPE_SAG || pq->event_type == PQ_TYPE_INTERRUPTION) {
        if (pu < pq->event_extreme_pu) pq->event_extreme_pu = pu;
    } else {
        if (pu > pq->event_extreme_pu) pq->event_extreme_pu = pu;
    }
    int recovered = (pu >= pq->sag_pu + pq->hysteresis_pu) && (pu <= pq->swell_pu - pq->hysteresis_pu);
    if (recovered) pq_end_event(pq, pq->urms_half);
}

static void update_half_cycle_rms(pq_t *pq, float v) {
    int crossed = (pq->prev_sample <= 0.0f && v > 0.0f) || (pq->prev_sample >= 0.0f && v < 0.0f);
    if (pq->half_cycle_n < PQ_HALF_CYCLE_BUF_LEN) {
        pq->half_cycle_buf[pq->half_cycle_n++] = v;
    }
    float half_cycle_n_f = pq->fs_hz / (2.0f * pq->f_nominal);
    int min_len = (int)(0.3f * half_cycle_n_f);
    if (min_len < 4) min_len = 4;
    int max_len = (int)(2.0f * half_cycle_n_f);
    if (max_len >= PQ_HALF_CYCLE_BUF_LEN) max_len = PQ_HALF_CYCLE_BUF_LEN - 1;

    if (crossed && pq->half_cycle_n > min_len) {
        double s = 0.0;
        int seg_n = pq->half_cycle_n - 1;
        for (int i = 0; i < seg_n; i++) s += (double)pq->half_cycle_buf[i] * pq->half_cycle_buf[i];
        pq->urms_half = (float)sqrt(s / seg_n);
        pq->urms_half_ts_ms = pq->t_ms;
        pq->half_cycle_buf[0] = v;
        pq->half_cycle_n = 1;
        check_magnitude_event(pq);
    } else if (pq->half_cycle_n > max_len) {
        /* Stall watchdog: a full interruption (V ~ 0) never crosses zero, so
         * force-evaluate a segment after ~2x the nominal half-cycle length
         * with no crossing (see pq.py for the matching rationale). */
        double s = 0.0;
        int seg_n = pq->half_cycle_n;
        for (int i = 0; i < seg_n; i++) s += (double)pq->half_cycle_buf[i] * pq->half_cycle_buf[i];
        pq->urms_half = (float)sqrt(s / seg_n);
        pq->urms_half_ts_ms = pq->t_ms;
        pq->half_cycle_n = 0;
        check_magnitude_event(pq);
    } else if (pq->half_cycle_n >= PQ_HALF_CYCLE_BUF_LEN) {
        /* safety valve: should not happen at valid frequencies, but never overflow */
        pq->half_cycle_buf[0] = v;
        pq->half_cycle_n = 1;
    }
}

static void check_frequency_event(pq_t *pq) {
    float dev = fabsf(pq->freq_hz - pq->f_nominal) / pq->f_nominal;
    if (!pq->in_freq_event) {
        if (dev > pq->freq_dev_frac) {
            pq->in_freq_event = 1;
            pq->freq_event_start_ms = pq->t_ms;
            pq->freq_event_extreme = pq->freq_hz;
        }
        return;
    }
    if (fabsf(pq->freq_hz - pq->f_nominal) > fabsf(pq->freq_event_extreme - pq->f_nominal)) {
        pq->freq_event_extreme = pq->freq_hz;
    }
    if (dev <= pq->freq_dev_frac - pq->freq_hysteresis_frac) {
        pq_event_t ev;
        memset(&ev, 0, sizeof(ev));
        long duration_ms = (long)(pq->t_ms - pq->freq_event_start_ms + 0.5f);
        if (duration_ms < 0) duration_ms = 0;
        ev.ts_epoch_ms = (uint32_t)(pq->freq_event_start_ms + 0.5f);
        ev.type = PQ_TYPE_FREQ_DEV;
        ev.magnitude_pu = pq->freq_event_extreme / pq->f_nominal;
        ev.duration_ms = (uint32_t)duration_ms;
        ev.pre_event_rms_V = pq->f_nominal;
        ev.post_event_rms_V = pq->freq_hz;
        ev.thd_pct = NAN;
        pq_push_event(pq, &ev);
        pq->in_freq_event = 0;
    }
}

static void update_frequency(pq_t *pq, float v) {
    int rising = (pq->prev_sample <= 0.0f && v > 0.0f);
    if (!rising) return;
    pq->rising_head = (pq->rising_head + 1) % PQ_FREQ_HIST_LEN;
    pq->rising_ts[pq->rising_head] = pq->t_ms;
    if (pq->rising_n < PQ_FREQ_HIST_LEN) pq->rising_n++;

    int window = pq->freq_window_cycles + 1;
    int use_n = (pq->rising_n < window) ? pq->rising_n : window;
    if (use_n < 2) return;
    float newest = ring_at_f(pq->rising_ts, pq->rising_head, pq->rising_n, PQ_FREQ_HIST_LEN, 0);
    float oldest = ring_at_f(pq->rising_ts, pq->rising_head, pq->rising_n, PQ_FREQ_HIST_LEN, use_n - 1);
    float avg_period_ms = (newest - oldest) / (float)(use_n - 1);
    if (avg_period_ms > 1e-6f) {
        pq->freq_hz = 1000.0f / avg_period_ms;
        check_frequency_event(pq);
    }
}

static void check_thd_event(pq_t *pq) {
    if (pq->thd_pct > pq->thd_excursion_pct) {
        pq_event_t ev;
        memset(&ev, 0, sizeof(ev));
        ev.ts_epoch_ms = (uint32_t)(pq->t_ms + 0.5f);
        ev.type = PQ_TYPE_THD_EXCURSION;
        ev.magnitude_pu = pq->urms_half / pq->v_nominal;
        ev.duration_ms = (uint32_t)(1000.0f * (float)pq->thd_window_cycles / pq->f_nominal + 0.5f);
        ev.pre_event_rms_V = pq->urms_half;
        ev.post_event_rms_V = pq->urms_half;
        ev.thd_pct = pq->thd_pct;
        pq_push_event(pq, &ev);
    }
}

static void update_thd(pq_t *pq, float v) {
    if (pq->thd_n < PQ_THD_BLOCK_N) {
        pq->thd_buf[pq->thd_n++] = v;
    }
    if (pq->thd_n >= PQ_THD_BLOCK_N) {
        float thd = compute_thd(pq->thd_buf, PQ_THD_BLOCK_N, pq->fs_hz, pq->f_nominal, PQ_MAX_HARMONIC);
        if (!isnan(thd)) {
            pq->thd_pct = thd;
            check_thd_event(pq);
        }
        pq->thd_n = 0;
    }
}

void pq_push_sample(pq_t *pq, float v_sample) {
    if (!pq->started) {
        pq->started = 1;
        pq->half_cycle_buf[0] = v_sample;
        pq->half_cycle_n = 1;
        pq->thd_buf[0] = v_sample;
        pq->thd_n = 1;
        pq->prev_sample = v_sample;
        pq->t_ms += pq->dt_ms;
        return;
    }
    update_half_cycle_rms(pq, v_sample);
    update_frequency(pq, v_sample);
    update_thd(pq, v_sample);
    pq->prev_sample = v_sample;
    pq->t_ms += pq->dt_ms;
}

int pq_poll_event(pq_t *pq, pq_event_t *out) {
    if (pq->eq_count == 0) return 0;
    if (out) *out = pq->event_queue[pq->eq_head];
    pq->eq_head = (pq->eq_head + 1) % PQ_EVENT_QUEUE_LEN;
    pq->eq_count--;
    return 1;
}
