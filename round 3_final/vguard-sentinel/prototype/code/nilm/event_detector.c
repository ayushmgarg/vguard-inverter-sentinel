/* nilm/event_detector.c -- see event_detector.h.
 *
 * Mirrors nilm/event_detector.py's EventDetector.push() frame-for-frame
 * (design 06 Sec 2.3 pseudocode) so tests/test_nilm.py can cross-check the
 * two implementations on the same stream.
 */
#include "event_detector.h"
#include <math.h>
#include <string.h>

#define V_NORM_REF 230.0f

static void ring_push(ev_det_t *d, float t, float Pn, float Q) {
    d->head = (d->head + 1) % EV_RING_LEN;
    d->t[d->head] = t;
    d->Pn[d->head] = Pn;
    d->Q[d->head] = Q;
    if (d->count < EV_RING_LEN) d->count++;
}

/* back=0 -> most recent sample, back=1 -> previous, ... */
static float ring_at(const float *buf, int head, int back) {
    int idx = head - back;
    while (idx < 0) idx += EV_RING_LEN;
    return buf[idx % EV_RING_LEN];
}

static float ring_mean(const ev_det_t *d, const float *buf, int back_lo, int back_hi) {
    double s = 0.0;
    int n = 0;
    for (int b = back_lo; b <= back_hi; b++) {
        s += ring_at(buf, d->head, b);
        n++;
    }
    return n > 0 ? (float)(s / n) : 0.0f;
}

static float ring_std(const ev_det_t *d, const float *buf, int win) {
    float mean = ring_mean(d, buf, 0, win - 1);
    double s = 0.0;
    for (int b = 0; b < win; b++) {
        float v = ring_at(buf, d->head, b) - mean;
        s += (double)v * v;
    }
    return (float)sqrt(s / win);
}

static float ring_max_abs_diff(const ev_det_t *d, const float *buf, int win) {
    float maxd = 0.0f;
    for (int b = 0; b < win - 1; b++) {
        float a = ring_at(buf, d->head, b);
        float bb = ring_at(buf, d->head, b + 1);
        float diff = fabsf(a - bb);
        if (diff > maxd) maxd = diff;
    }
    return maxd;
}

void ev_init(ev_det_t *d, float rate_hz) {
    memset(d, 0, sizeof(*d));
    d->N_pre = 4;
    d->N_post = 4;
    d->P_th_abs = 25.0f;
    d->P_th_rel = 0.02f;
    d->Q_th = 25.0f;
    d->T_merge = 2;
    d->SS_win = 5;
    d->T_max_transient_s = 15.0f;
    d->eps_deriv = 15.0f;
    d->rate_hz = rate_hz;
    d->mode = 0;
    d->k = -1;
    d->t0_idx = -1;
    d->suppress_until = -1;
    d->head = -1;
    d->count = 0;
}

int ev_push(ev_det_t *d, float t, float P, float Q, float V, ev_event_t *out) {
    d->k += 1;
    float Pn = (V > 1e-6f) ? P * (V_NORM_REF / V) * (V_NORM_REF / V) : P;
    ring_push(d, t, Pn, Q);

    int emitted = 0;
    int need = d->N_pre + d->N_post;

    if (d->mode == 0) { /* STEADY */
        if (d->count >= need && d->k >= d->suppress_until) {
            float m_pre = ring_mean(d, d->Pn, d->N_post, need - 1);
            float m_post = ring_mean(d, d->Pn, 0, d->N_post - 1);
            float q_pre = ring_mean(d, d->Q, d->N_post, need - 1);
            float q_post = ring_mean(d, d->Q, 0, d->N_post - 1);
            float thresh = fmaxf(d->P_th_abs, d->P_th_rel * fabsf(m_pre));
            if (fabsf(m_post - m_pre) > thresh || fabsf(q_post - q_pre) > d->Q_th) {
                d->mode = 1; /* TRANSIENT */
                d->t0_idx = d->k - d->N_post;
                d->ss_ref_P = m_pre;
                d->ss_ref_Q = q_pre;
            }
        }
    } else { /* TRANSIENT */
        long elapsed_frames = d->k - d->t0_idx;
        float elapsed_s = elapsed_frames / d->rate_hz;
        int settled = 0;
        if (d->count >= d->SS_win) {
            float std_p = ring_std(d, d->Pn, d->SS_win);
            float mean_p = ring_mean(d, d->Pn, 0, d->SS_win - 1);
            float max_diff = ring_max_abs_diff(d, d->Pn, d->SS_win);
            settled = (std_p < fmaxf(8.0f, 0.01f * fabsf(mean_p))) && (max_diff < d->eps_deriv);
        }
        if (settled || elapsed_s > d->T_max_transient_s) {
            int ss_win = d->SS_win;
            float P_ss_new = ring_mean(d, d->Pn, 0, ss_win - 1);
            float Q_ss_new = ring_mean(d, d->Q, 0, ss_win - 1);
            float dP = P_ss_new - d->ss_ref_P;
            float dQ = Q_ss_new - d->ss_ref_Q;
            float discard_thresh = fmaxf(d->P_th_abs, d->P_th_rel * fabsf(d->ss_ref_P));
            if (!(fabsf(dP) < discard_thresh && fabsf(dQ) < d->Q_th)) {
                long back_span = d->k - d->t0_idx; /* frames from t0 to k inclusive: back_span+1 */
                if (back_span > d->count - 1) back_span = d->count - 1;
                double A_tr = 0.0;
                float dt = 1.0f / d->rate_hz;
                for (long b = 0; b <= back_span; b++) {
                    float v = ring_at(d->Pn, d->head, (int)b);
                    A_tr += (v - P_ss_new) * dt;
                }
                float t_settle_s = (float)(d->k - d->t0_idx) / d->rate_hz;
                float t0_time = ring_at(d->t, d->head, (int)back_span);

                if (out) {
                    out->t0 = t0_time;
                    out->t_off = NAN;
                    out->dP = dP;
                    out->dQ = dQ;
                    out->r_pk = NAN;   /* no Ipk channel in this API */
                    out->t_settle_s = t_settle_s;
                    out->A_tr = (float)A_tr;
                    out->h = NAN;      /* no Pf/Ph channel in this API */
                    out->dur_s = NAN;
                    out->paired = 0;
                    out->kind = (dP > 0.0f) ? 1 : 0;
                }
                emitted = 1;
            }
            d->ss_ref_P = P_ss_new;
            d->ss_ref_Q = Q_ss_new;
            d->mode = 0;
            d->suppress_until = d->k + d->T_merge;
        }
    }
    return emitted;
}

void ev_pair(ev_event_t *events, int n_events, float max_gap_s) {
    /* design 06 Sec 2.4: OFF pairs with the most recent unpaired ON within
     * tolerance, searching back <= max_gap_s. Host-array implementation
     * (firmware equivalent operates over the flash event log). */
    int open_on[EV_MAX_EVENTS];
    int open_count = 0;

    for (int i = 0; i < n_events; i++) {
        events[i].kind = (events[i].dP > 0.0f) ? 1 : 0;
    }

    for (int i = 0; i < n_events; i++) {
        if (events[i].kind == 1) {
            if (open_count < EV_MAX_EVENTS) open_on[open_count++] = i;
            continue;
        }
        /* OFF: search back through open ONs, most recent first */
        int match = -1;
        for (int oi = open_count - 1; oi >= 0; oi--) {
            int j = open_on[oi];
            if (events[i].t0 - events[j].t0 > max_gap_s) break;
            float dP_sum = events[j].dP + events[i].dP;
            float dQ_sum = events[j].dQ + events[i].dQ;
            float dP_tol = fmaxf(15.0f, 0.10f * fabsf(events[j].dP));
            float dQ_tol = (fabsf(events[j].dQ) > 1e-6f) ? fmaxf(15.0f, 0.15f * fabsf(events[j].dQ)) : 15.0f;
            if (fabsf(dP_sum) <= dP_tol && fabsf(dQ_sum) <= dQ_tol) {
                match = oi;
                break;
            }
        }
        if (match >= 0) {
            int j = open_on[match];
            events[j].t_off = events[i].t0;
            events[j].dur_s = events[i].t0 - events[j].t0;
            events[j].paired = 1;
            events[i].paired = 1;
            for (int m = match; m < open_count - 1; m++) open_on[m] = open_on[m + 1];
            open_count--;
        }
    }
}
