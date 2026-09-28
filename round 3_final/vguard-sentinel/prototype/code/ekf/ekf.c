/* ekf/ekf.c -- C99 port of ekf/ekf.py. See ekf.h for the API and the sign
 * convention note. No malloc, no printf; float32 throughout (01 §3.5).
 * LUT grids/values are mirrored *exactly* from ekf/lut.py so the two
 * implementations agree on interpolation behaviour (checked by
 * tests/test_ekf.py::test_c_matches_python).
 */
#include "ekf.h"
#include <math.h>
#include <string.h>

/* ---------------------------------------------------------------------
 * LUTs (design 01 §1.5, §2.1-2.2) -- mirrors ekf/lut.py exactly.
 * ------------------------------------------------------------------- */

static const float SOC_GRID[EKF_SOC_GRID_N] = {0.0f, 0.10f, 0.25f, 0.50f, 0.75f, 0.90f, 1.00f};
static const float T_GRID[EKF_T_GRID_N] = {0.0f, 25.0f, 45.0f};

static const float OCV_TABLE[EKF_T_GRID_N][EKF_SOC_GRID_N] = {
    {11.8875f, 11.9875f, 12.1375f, 12.3875f, 12.5875f, 12.6875f, 12.7875f},
    {11.80f, 11.90f, 12.05f, 12.30f, 12.50f, 12.60f, 12.70f},
    {11.73f, 11.83f, 11.98f, 12.23f, 12.43f, 12.53f, 12.63f},
};

static const float R0_TABLE[EKF_T_GRID_N][EKF_SOC_GRID_N] = {
    {0.009450f, 0.008775f, 0.0077625f, 0.0070875f, 0.006885f, 0.006750f, 0.006750f},
    {0.006300f, 0.005850f, 0.0051750f, 0.0047250f, 0.004590f, 0.004500f, 0.004500f},
    {0.005355f, 0.004973f, 0.0043988f, 0.0040163f, 0.003902f, 0.003825f, 0.003825f},
};

static const float R1_TABLE[EKF_T_GRID_N][EKF_SOC_GRID_N] = {
    {0.01470f, 0.010780f, 0.006860f, 0.005390f, 0.004900f, 0.004900f, 0.004900f},
    {0.01050f, 0.007700f, 0.004900f, 0.003850f, 0.003500f, 0.003500f, 0.003500f},
    {0.00945f, 0.006930f, 0.004410f, 0.003465f, 0.003150f, 0.003150f, 0.003150f},
};

static const float TAU_TABLE[EKF_T_GRID_N][EKF_SOC_GRID_N] = {
    {120.0f, 114.4f, 85.8f, 71.5f, 64.35f, 60.775f, 60.775f},
    {110.0f, 88.0f, 66.0f, 55.0f, 49.5f, 46.75f, 46.75f},
    {88.0f, 70.4f, 52.8f, 44.0f, 39.6f, 37.4f, 37.4f},
};

static float clipf(float x, float lo, float hi) {
    return x < lo ? lo : (x > hi ? hi : x);
}

static void bracket(const float* grid, int n, float v, int* idx, float* frac) {
    v = clipf(v, grid[0], grid[n - 1]);
    int i = 0;
    while (i < n - 2 && grid[i + 1] <= v) i++;
    float lo = grid[i], hi = grid[i + 1];
    *idx = i;
    *frac = (hi == lo) ? 0.0f : (v - lo) / (hi - lo);
}

static float bilinear(const float table[EKF_T_GRID_N][EKF_SOC_GRID_N], float soc, float t) {
    int si, ti; float sf, tf;
    bracket(SOC_GRID, EKF_SOC_GRID_N, soc, &si, &sf);
    bracket(T_GRID, EKF_T_GRID_N, t, &ti, &tf);
    float v00 = table[ti][si], v01 = table[ti][si + 1];
    float v10 = table[ti + 1][si], v11 = table[ti + 1][si + 1];
    float v0 = v00 + (v01 - v00) * sf;
    float v1 = v10 + (v11 - v10) * sf;
    return v0 + (v1 - v0) * tf;
}

static float lut_ocv(float soc, float t) { return bilinear(OCV_TABLE, soc, t); }
static float lut_r0(float soc, float t) { return bilinear(R0_TABLE, soc, t); }
static float lut_r1(float soc, float t) { return bilinear(R1_TABLE, soc, t); }
static float lut_tau(float soc, float t) { return clipf(bilinear(TAU_TABLE, soc, t), 20.0f, 120.0f); }

static float lut_docv_dsoc(float soc, float t) {
    float eps = 0.01f;
    float lo = clipf(soc - eps, 0.0f, 1.0f);
    float hi = clipf(soc + eps, 0.0f, 1.0f);
    if (hi == lo) return 0.0f;
    return (lut_ocv(hi, t) - lut_ocv(lo, t)) / (hi - lo);
}

static float lut_ocv_inverse(float v, float t) {
    const int n = 200;
    float prev_soc = 0.0f, prev_ocv = lut_ocv(0.0f, t);
    v = clipf(v, lut_ocv(0.0f, t), lut_ocv(1.0f, t));
    for (int i = 1; i <= n; i++) {
        float soc = (float)i / (float)n;
        float ocv = lut_ocv(soc, t);
        if (prev_ocv <= v && v <= ocv) {
            float frac = (ocv == prev_ocv) ? 0.0f : (v - prev_ocv) / (ocv - prev_ocv);
            return prev_soc + frac * (soc - prev_soc);
        }
        prev_soc = soc; prev_ocv = ocv;
    }
    return 0.5f;
}

static float interp1d(float x, const float* breaks, const float* vals, int n) {
    x = clipf(x, breaks[0], breaks[n - 1]);
    for (int i = 0; i < n - 1; i++) {
        if (breaks[i] <= x && x <= breaks[i + 1]) {
            float frac = (breaks[i + 1] == breaks[i]) ? 0.0f
                : (x - breaks[i]) / (breaks[i + 1] - breaks[i]);
            return vals[i] + frac * (vals[i + 1] - vals[i]);
        }
    }
    return vals[n - 1];
}

static float lut_f_temp(float t) {
    static const float b[4] = {-10.0f, 0.0f, 25.0f, 45.0f};
    static const float v[4] = {0.75f, 0.85f, 1.00f, 1.00f};
    return interp1d(t, b, v, 4);
}

static float lut_eta_charge(float soc, float t) {
    (void)t;
    static const float b[4] = {0.0f, 0.70f, 0.90f, 1.00f};
    static const float v[4] = {0.98f, 0.98f, 0.90f, 0.77f};
    return interp1d(soc, b, v, 4);
}

static float lut_peukert_multiplier(float i_discharge_a, float c20_a, float n, float floor_) {
    float ia = fabsf(i_discharge_a);
    if (c20_a <= 0.0f || ia <= c20_a) return 1.0f;
    float mult = powf(c20_a / ia, n - 1.0f);
    return clipf(mult, floor_, 1.0f);
}

/* ---------------------------------------------------------------------
 * params / init
 * ------------------------------------------------------------------- */

void ekf_params_default(ekf_params_t* p, float q_rated_ah) {
    memset(p, 0, sizeof(*p));
    p->q_rated_ah = q_rated_ah;
    p->peukert_n = 1.25f;

    p->r_v = 0.004f * 0.004f;
    p->q_soc = 5e-5f * 5e-5f;
    p->q_v1 = 0.010f * 0.010f;
    p->q_r0_idle = 1e-10f;
    p->q_r0_event = 0.5e-3f * 0.5e-3f;
    p->r0_event_meas_var = 1.0e-3f * 1.0e-3f;
    p->chi2_gate = 9.0f;

    p->v_full_25c = 13.5f;
    p->v_full_tempco_v_per_c = -0.024f;
    p->i_tail_frac_c20 = 0.015f;
    p->t_full_dwell_s = 1200.0f;

    p->i_rest_frac_c20 = 0.0075f;
    p->t_rest_prov_s = 4500.0f;
    p->t_rest_high_s = 18000.0f;
    p->r_rest_med = 0.020f * 0.020f;
    p->r_rest_high = 0.004f * 0.004f;

    p->di_thresh_frac_c20 = 0.075f;
    p->r0_min_events = 20;
    p->r0_max_buffer = EKF_R0_BUF_CAP;
    p->r0_sanity_envelope_mult = 3.0f;

    p->soc_lo = 0.0f; p->soc_hi = 1.0f;
    p->r0_lo_ohm = 1e-3f; p->r0_hi_ohm = 50e-3f;
    p->p_floor[0] = 1e-9f; p->p_floor[1] = 1e-8f; p->p_floor[2] = 1e-13f;
    p->p_ceiling[0] = 0.25f; p->p_ceiling[1] = 0.01f; p->p_ceiling[2] = 0.02f * 0.02f;
    p->cross_check_thresh = 0.09f;
    p->cross_check_dwell_s = 300.0f;

    p->zero_cal_alpha = 0.02f;
    p->zero_cal_i_thresh_a = 0.05f;

    p->min_dod_for_capacity_cycle = 0.30f;

    p->p0_soc_var = 0.20f * 0.20f;
    p->p0_v1_var = 0.05f * 0.05f;
    p->p0_r0_var_frac = 0.30f;
}

void ekf_init(ekf_t* e, const ekf_params_t* params) {
    memset(e, 0, sizeof(*e));
    if (params) e->p = *params; else ekf_params_default(&e->p, 150.0f);
    if (e->p.r0_max_buffer > EKF_R0_BUF_CAP) e->p.r0_max_buffer = EKF_R0_BUF_CAP;
    e->c20_a = e->p.q_rated_ah / 20.0f;
    e->initialized = 0;
    e->soc_counter = 0.5f;
    e->soc_raw_naive = 0.5f;
    e->soh_r = 1.0f;
    e->capacity_bol_ah = e->p.q_rated_ah;
    e->last_anchor = 0;
}

/* ---------------------------------------------------------------------
 * lazy init (01 §3.3)
 * ------------------------------------------------------------------- */

static void lazy_init(ekf_t* e, float i_charge_pos, float v, float t, int charger_on) {
    ekf_params_t* p = &e->p;
    float soc0, v10, r00, p_soc, p_v1, p_r0;
    float i_rest = p->i_rest_frac_c20 * e->c20_a;
    if (!charger_on && fabsf(i_charge_pos) < i_rest) {
        soc0 = lut_ocv_inverse(v, t);
        v10 = 0.0f;
        r00 = lut_r0(soc0, t);
        p_soc = 0.02f * 0.02f;
    } else {
        soc0 = 0.5f;
        v10 = 0.0f;
        r00 = lut_r0(soc0, t);
        p_soc = p->p0_soc_var;
    }
    p_v1 = p->p0_v1_var;
    p_r0 = (r00 * p->p0_r0_var_frac) * (r00 * p->p0_r0_var_frac);

    e->x[0] = soc0; e->x[1] = v10; e->x[2] = r00;
    memset(e->P, 0, sizeof(e->P));
    e->P[0][0] = p_soc; e->P[1][1] = p_v1; e->P[2][2] = p_r0;
    e->soc_counter = soc0;
    e->soc_raw_naive = soc0;
    e->capacity_bol_ah = p->q_rated_ah;
    e->initialized = 1;
}

/* ---------------------------------------------------------------------
 * small 3x3 helpers
 * ------------------------------------------------------------------- */

static float hpht(const float H[3], const float P[3][3]) {
    float v[3];
    for (int i = 0; i < 3; i++) {
        v[i] = 0.0f;
        for (int j = 0; j < 3; j++) v[i] += H[j] * P[j][i];
    }
    float s = 0.0f;
    for (int i = 0; i < 3; i++) s += H[i] * v[i];
    return s;
}

static void kalman_update(float x[3], float P[3][3], const float H[3], float S, float y,
                           float x_out[3], float P_out[3][3]) {
    float PHt[3];
    for (int i = 0; i < 3; i++) {
        PHt[i] = 0.0f;
        for (int j = 0; j < 3; j++) PHt[i] += P[i][j] * H[j];
    }
    float K[3];
    for (int i = 0; i < 3; i++) K[i] = PHt[i] / S;
    for (int i = 0; i < 3; i++) x_out[i] = x[i] + K[i] * y;

    float KH[3][3];
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++) KH[i][j] = K[i] * H[j];

    float P_new[3][3];
    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) {
            float acc = P[i][j];
            for (int k = 0; k < 3; k++) acc -= KH[i][k] * P[k][j];
            P_new[i][j] = acc;
        }
    }
    for (int i = 0; i < 3; i++) {
        for (int j = i + 1; j < 3; j++) {
            float m = 0.5f * (P_new[i][j] + P_new[j][i]);
            P_new[i][j] = m; P_new[j][i] = m;
        }
    }
    memcpy(P_out, P_new, sizeof(P_new));
}

static void clamp_state(ekf_t* e) {
    ekf_params_t* p = &e->p;
    e->x[0] = clipf(e->x[0], p->soc_lo, p->soc_hi);
    e->x[2] = clipf(e->x[2], p->r0_lo_ohm, p->r0_hi_ohm);
    for (int i = 0; i < 3; i++) e->P[i][i] = clipf(e->P[i][i], p->p_floor[i], p->p_ceiling[i]);
    for (int i = 0; i < 3; i++) {
        for (int j = i + 1; j < 3; j++) {
            float m = 0.5f * (e->P[i][j] + e->P[j][i]);
            e->P[i][j] = m; e->P[j][i] = m;
        }
    }
}

/* ---------------------------------------------------------------------
 * median of a small float buffer (no malloc: fixed-size scratch copy)
 * ------------------------------------------------------------------- */

static float median_of(const float* buf, int n) {
    float tmp[EKF_R0_BUF_CAP];
    memcpy(tmp, buf, sizeof(float) * (size_t)n);
    for (int i = 1; i < n; i++) {
        float key = tmp[i];
        int j = i - 1;
        while (j >= 0 && tmp[j] > key) { tmp[j + 1] = tmp[j]; j--; }
        tmp[j + 1] = key;
    }
    if (n % 2 == 1) return tmp[n / 2];
    return 0.5f * (tmp[n / 2 - 1] + tmp[n / 2]);
}

/* ---------------------------------------------------------------------
 * ekf_step
 * ------------------------------------------------------------------- */

static float v_full_at(const ekf_params_t* p, float t) {
    return p->v_full_25c + p->v_full_tempco_v_per_c * (t - 25.0f);
}

void ekf_step(ekf_t* e, float I_discharge_pos, float V, float T, int charger_on) {
    const float dt = 1.0f;
    ekf_params_t* p = &e->p;

    /* CONTRACTS §6: this API is discharge-positive already; convert to the
     * charge-positive convention internally only where the offset/rest
     * logic (ported from the charge-positive Python API) needs it. */
    float i_charge_raw = -I_discharge_pos;

    if (!e->initialized) {
        lazy_init(e, i_charge_raw, V, T, charger_on);
        e->t_s += dt;
        return;
    }
    e->last_anchor = 0; /* reset each tick -- only set when actually applied */

    /* zero-current auto-cal (01 §4) */
    float i_charge_corr = i_charge_raw - e->i_offset_est_a;
    if (!charger_on && fabsf(i_charge_corr) < p->zero_cal_i_thresh_a) {
        e->i_offset_est_a += p->zero_cal_alpha * (i_charge_raw - e->i_offset_est_a);
        i_charge_corr = i_charge_raw - e->i_offset_est_a;
    }
    float I = -i_charge_corr; /* design-doc discharge-positive */

    /* naive + cross-check counters */
    e->soc_raw_naive += i_charge_raw * dt / (3600.0f * p->q_rated_ah);
    {
        float Qu = p->q_rated_ah * lut_f_temp(T) * lut_peukert_multiplier(I, e->c20_a, p->peukert_n, 0.55f);
        float eta = (I >= 0.0f) ? 1.0f : lut_eta_charge(e->soc_counter, T);
        e->soc_counter -= eta * I * dt / (3600.0f * Qu);
        e->soc_counter = clipf(e->soc_counter, 0.0f, 1.0f);
    }

    /* predict */
    float soc = e->x[0], v1 = e->x[1], r0s = e->x[2];
    float Qu = p->q_rated_ah * lut_f_temp(T) * lut_peukert_multiplier(I, e->c20_a, p->peukert_n, 0.55f);
    float eta = (I >= 0.0f) ? 1.0f : lut_eta_charge(soc, T);
    float tau = lut_tau(soc, T);
    float R1 = lut_r1(soc, T);
    float decay = expf(-dt / tau);

    float x_pred[3];
    x_pred[0] = soc - eta * I * dt / (3600.0f * Qu);
    x_pred[1] = v1 * decay + R1 * (1.0f - decay) * I;
    x_pred[2] = r0s;

    float P_pred[3][3];
    P_pred[0][0] = e->P[0][0];
    P_pred[0][1] = e->P[0][1] * decay;
    P_pred[0][2] = e->P[0][2];
    P_pred[1][0] = e->P[1][0] * decay;
    P_pred[1][1] = e->P[1][1] * decay * decay;
    P_pred[1][2] = e->P[1][2] * decay;
    P_pred[2][0] = e->P[2][0];
    P_pred[2][1] = e->P[2][1] * decay;
    P_pred[2][2] = e->P[2][2];
    P_pred[0][0] += p->q_soc;
    P_pred[1][1] += p->q_v1;
    P_pred[2][2] += p->q_r0_idle;

    /* measurement update -- charger OFF only (01 §0/H30, see ekf.py step()
     * for the full rationale: the generic OCV-I*R0-V1 branch is only a good
     * approximation off-charge; under charge the charger's own absorption/
     * float regulation overhead is not explainable by a few-mOhm R0, so
     * running this unconditionally would silently reintroduce H30 one
     * small, individually-plausible innovation at a time. */
    float x_upd[3]; float P_upd[3][3];
    if (charger_on) {
        memcpy(x_upd, x_pred, sizeof(x_upd));
        memcpy(P_upd, P_pred, sizeof(P_upd));
        e->last_innovation_rejected = 0;
    } else {
        float ocv = lut_ocv(x_pred[0], T);
        float docv = lut_docv_dsoc(x_pred[0], T);
        float y = V - (ocv - I * x_pred[2] - x_pred[1]);
        float H[3] = {docv, -1.0f, -I};
        float S = hpht(H, P_pred) + p->r_v;
        if (S <= 0.0f) S = p->r_v;
        float gate = (y * y) / S;
        e->last_innovation_rejected = (gate >= p->chi2_gate);
        if (e->last_innovation_rejected) {
            memcpy(x_upd, x_pred, sizeof(x_upd));
            memcpy(P_upd, P_pred, sizeof(P_upd));
        } else {
            kalman_update(x_pred, P_pred, H, S, y, x_upd, P_upd);
        }
    }
    memcpy(e->x, x_upd, sizeof(e->x));
    memcpy(e->P, P_upd, sizeof(e->P));
    clamp_state(e);

    /* full detection (charger ON, taper) -- 01 §5a/§7 */
    {
        float i_tail = p->i_tail_frac_c20 * e->c20_a;
        float vfull = v_full_at(p, T);
        int tapering = charger_on && (V >= vfull) && (fabsf(i_charge_corr) < i_tail);
        if (tapering) {
            e->full_timer_s += dt;
            if (e->full_timer_s >= p->t_full_dwell_s && !e->full_locked) {
                /* close_cycle */
                if (e->ah_in_cycle > 0.0f) {
                    e->eta_measured = e->ah_out_cycle / e->ah_in_cycle;
                    e->eta_measured_valid = 1;
                }
                float dod = e->ah_out_cycle / p->q_rated_ah;
                if (dod >= p->min_dod_for_capacity_cycle) {
                    e->capacity_measured_ah = e->ah_out_cycle;
                    e->capacity_measured_valid = 1;
                    if (e->capacity_bol_ah > 0.0f) {
                        e->soh_capacity = e->capacity_measured_ah / e->capacity_bol_ah;
                        e->soh_capacity_valid = 1;
                    }
                }
                e->ah_out_cycle = 0.0f;
                e->ah_in_cycle = 0.0f;

                e->x[0] = 1.0f;
                e->P[0][0] = fminf(e->P[0][0], 0.005f * 0.005f);
                e->full_locked = 1;
                e->last_anchor = 1;
            }
        } else {
            e->full_timer_s = 0.0f;
            if (i_charge_corr < 0.0f) e->full_locked = 0;
        }
    }

    /* true rest-OCV anchor, charger OFF only -- 01 §5b (H30 fix) */
    {
        float i_rest = p->i_rest_frac_c20 * e->c20_a;
        int resting = (!charger_on) && (fabsf(i_charge_corr) < i_rest);
        if (resting) {
            e->rest_timer_s += dt;
        } else {
            e->rest_timer_s = 0.0f;
        }
        if (resting && e->rest_timer_s >= p->t_rest_prov_s) {
            int high = e->rest_timer_s >= p->t_rest_high_s;
            float r_ocv = high ? p->r_rest_high : p->r_rest_med;
            e->last_anchor = high ? 3 : 2;

            float soc2 = e->x[0];
            float ocv2 = lut_ocv(soc2, T);
            float docv2 = lut_docv_dsoc(soc2, T);
            float y2 = V - ocv2;
            float H2[3] = {docv2, -1.0f, 0.0f};
            float S2 = hpht(H2, e->P) + r_ocv;
            if (S2 > 0.0f) {
                float x2[3]; float P2[3][3];
                kalman_update(e->x, e->P, H2, S2, y2, x2, P2);
                memcpy(e->x, x2, sizeof(e->x));
                memcpy(e->P, P2, sizeof(e->P));
            }
        }
    }
    clamp_state(e);

    /* R_int event estimator (01 §6) -- honest 1 Hz limitation: consecutive
     * -sample deltaI/deltaV instead of a sub-second burst fit. */
    e->last_t_for_event = T;
    if (e->have_prev) {
        float dI = I - e->prev_i_discharge;
        if (fabsf(dI) >= p->di_thresh_frac_c20 * e->c20_a && charger_on == e->prev_charger_on) {
            float r_meas = (e->prev_v - V) / dI;
            if (r_meas > 0.0f) {
                float r0_now = lut_r0(e->x[0], T);
                float r0_ref = lut_r0(1.0f, 25.0f);
                if (r0_now > 0.0f) {
                    float r_norm = r_meas * r0_ref / r0_now;
                    float envelope_hi = r0_ref * p->r0_sanity_envelope_mult;
                    if (r_norm > 0.0f && r_norm <= envelope_hi) {
                        int cap = p->r0_max_buffer;
                        if (e->r0_buf_len < cap) {
                            e->r0_buf[e->r0_buf_len++] = r_norm;
                        } else {
                            e->r0_buf[e->r0_buf_head] = r_norm;
                            e->r0_buf_head = (e->r0_buf_head + 1) % cap;
                        }
                        e->n_r0_events++;
                        if (e->r0_buf_len >= p->r0_min_events) {
                            float med = median_of(e->r0_buf, e->r0_buf_len);
                            if (!e->r0_bol_ref_valid) {
                                e->r0_bol_ref = med;
                                e->r0_bol_ref_valid = 1;
                            }
                            if (med > 0.0f) e->soh_r = e->r0_bol_ref / med;

                            e->P[2][2] += p->q_r0_event;
                            float H3[3] = {0.0f, 0.0f, 1.0f};
                            float S3 = e->P[2][2] + p->r0_event_meas_var;
                            float y3 = med - e->x[2];
                            float x3[3]; float P3[3][3];
                            kalman_update(e->x, e->P, H3, S3, y3, x3, P3);
                            memcpy(e->x, x3, sizeof(e->x));
                            memcpy(e->P, P3, sizeof(e->P));
                        }
                    }
                }
            }
        }
    }
    e->prev_i_discharge = I;
    e->prev_v = V;
    e->prev_charger_on = charger_on;
    e->have_prev = 1;
    clamp_state(e);

    /* cross-check (01 §3.4 item 4) */
    if (fabsf(e->x[0] - e->soc_counter) > p->cross_check_thresh) {
        e->cross_check_bad_s += dt;
    } else {
        e->cross_check_bad_s = 0.0f;
    }
    e->fault_cross_check = e->cross_check_bad_s >= p->cross_check_dwell_s;

    /* accumulators */
    if (I >= 0.0f) e->ah_out_cycle += I * dt / 3600.0f;
    else e->ah_in_cycle += -I * dt / 3600.0f;

    e->t_s += dt;
}

float ekf_soc(const ekf_t* e) { return e->x[0]; }
float ekf_r0(const ekf_t* e) { return e->x[2]; }
float ekf_v1(const ekf_t* e) { return e->x[1]; }
float ekf_soh_r(const ekf_t* e) { return e->soh_r; }
