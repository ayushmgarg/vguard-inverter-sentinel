/* ekf/ekf.h -- 3-state EKF [SoC, V1, R0] for lead-acid, design doc 01.
 *
 * C99, host-buildable (gcc -std=c99 -O2 -lm), static allocation only (no
 * malloc, no printf in this library). float32 throughout (01 §3.5).
 *
 * Sign convention (CONTRACTS.md §6): ekf_step takes I_discharge_pos --
 * discharge-positive current, matching design doc 01's equations directly.
 * This differs from the Python EKF.step (+charge/-discharge, matching the
 * 1 Hz sim/feature stream, CONTRACTS §1) -- callers on the C side must
 * convert at their own boundary (see test_ekf_host.c for the CSV case).
 *
 * API mirrors CONTRACTS.md §6 exactly:
 *   void  ekf_init(ekf_t*, const ekf_params_t*);
 *   void  ekf_step(ekf_t*, float I_discharge_pos, float V, float T, int charger_on);
 *   float ekf_soc(const ekf_t*);
 *   float ekf_r0(const ekf_t*);
 */
#ifndef EKF_H
#define EKF_H

#ifdef __cplusplus
extern "C" {
#endif

#define EKF_SOC_GRID_N 7
#define EKF_T_GRID_N 3
#define EKF_R0_BUF_CAP 50

typedef struct {
    float q_rated_ah;
    float peukert_n;

    float r_v;
    float q_soc;
    float q_v1;
    float q_r0_idle;
    float q_r0_event;
    float r0_event_meas_var;
    float chi2_gate;

    float v_full_25c;
    float v_full_tempco_v_per_c;
    float i_tail_frac_c20;
    float t_full_dwell_s;

    float i_rest_frac_c20;
    float t_rest_prov_s;
    float t_rest_high_s;
    float r_rest_med;
    float r_rest_high;

    float di_thresh_frac_c20;
    int   r0_min_events;
    int   r0_max_buffer; /* <= EKF_R0_BUF_CAP */
    float r0_sanity_envelope_mult;

    float soc_lo, soc_hi;
    float r0_lo_ohm, r0_hi_ohm;
    float p_floor[3];
    float p_ceiling[3];
    float cross_check_thresh;
    float cross_check_dwell_s;

    float zero_cal_alpha;
    float zero_cal_i_thresh_a;

    float min_dod_for_capacity_cycle;

    float p0_soc_var;
    float p0_v1_var;
    float p0_r0_var_frac;
} ekf_params_t;

typedef struct {
    ekf_params_t p;
    float c20_a;

    int initialized;
    float x[3];   /* SoC, V1 (V), R0 (ohm) */
    float P[3][3];

    float soc_counter;
    float soc_raw_naive;
    float i_offset_est_a;

    float full_timer_s;
    int   full_locked;
    float rest_timer_s;

    float ah_out_cycle;
    float ah_in_cycle;
    float eta_measured;
    int   eta_measured_valid;
    float capacity_measured_ah;
    int   capacity_measured_valid;
    float capacity_bol_ah;
    float soh_capacity;
    int   soh_capacity_valid;

    float r0_buf[EKF_R0_BUF_CAP];
    int   r0_buf_len;
    int   r0_buf_head;
    float r0_bol_ref;
    int   r0_bol_ref_valid;
    float soh_r;
    int   n_r0_events;

    int   have_prev;
    float prev_i_discharge;
    float prev_v;
    int   prev_charger_on;
    float last_t_for_event;

    float cross_check_bad_s;
    int   fault_cross_check;

    float t_s;
    int   last_innovation_rejected;
    int   last_anchor; /* 0=none 1=full 2=rest_prov 3=rest_high */
} ekf_t;

void ekf_params_default(ekf_params_t* p, float q_rated_ah);
void ekf_init(ekf_t* e, const ekf_params_t* params);
void ekf_step(ekf_t* e, float I_discharge_pos, float V, float T, int charger_on);
float ekf_soc(const ekf_t* e);
float ekf_r0(const ekf_t* e);
float ekf_v1(const ekf_t* e);
float ekf_soh_r(const ekf_t* e);

#ifdef __cplusplus
}
#endif

#endif /* EKF_H */
