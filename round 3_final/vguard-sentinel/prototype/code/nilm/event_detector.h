/* nilm/event_detector.h -- C99 port of the Lu & Li moving-average change
 * detector (design 06 Sec 2) and ON/OFF pairing (Sec 2.4).
 *
 * API per CONTRACTS.md Sec 6:
 *   int ev_push(ev_det_t*, float t, float P, float Q, float V, ev_event_t* out);
 * ev_push takes only {t,P,Q,V} -- the fixed C API has no Ipk/Pf/Ph channel,
 * so this port always represents a Tier-0 PZEM stream: r_pk and h are always
 * NAN in emitted events (honesty note: see nilm/README.md).
 *
 * Static ring buffers only: no malloc, host- and MCU-buildable (gcc -std=c99).
 */
#ifndef NILM_EVENT_DETECTOR_H
#define NILM_EVENT_DETECTOR_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define EV_RING_LEN      96   /* frames of history (>= T_max_transient*rate + margin) */
#define EV_MAX_EVENTS   4096  /* host-test event log capacity */

typedef struct {
    float t0;
    float t_off;       /* NAN until paired */
    float dP;
    float dQ;
    float r_pk;         /* always NAN: no Ipk channel in this port */
    float t_settle_s;
    float A_tr;
    float h;            /* always NAN: no Pf/Ph channel in this port */
    float dur_s;         /* NAN until paired */
    int   paired;        /* 0/1 */
    int   kind;           /* 1 = ON (dP>0), 0 = OFF */
} ev_event_t;

typedef struct {
    /* parameters, design 06 Sec 2.2 */
    int   N_pre, N_post, T_merge, SS_win;
    float P_th_abs, P_th_rel, Q_th, T_max_transient_s, eps_deriv, rate_hz;

    /* ring buffers (circular, `head` = index of most recent sample) */
    float t[EV_RING_LEN];
    float Pn[EV_RING_LEN];
    float Q[EV_RING_LEN];
    int   count;
    int   head;

    int   mode;            /* 0 = STEADY, 1 = TRANSIENT */
    long  k;
    long  t0_idx;
    float ss_ref_P, ss_ref_Q;
    long  suppress_until;
} ev_det_t;

void ev_init(ev_det_t *d, float rate_hz);
int  ev_push(ev_det_t *d, float t, float P, float Q, float V, ev_event_t *out);

/* ON/OFF pairing over a captured event log (design 06 Sec 2.4). Mutates
 * events[] in place (t_off/dur_s/paired). Not part of the fixed ev_push API;
 * called by the host test / firmware event-log task after ev_push. */
void ev_pair(ev_event_t *events, int n_events, float max_gap_s);

#ifdef __cplusplus
}
#endif
#endif
