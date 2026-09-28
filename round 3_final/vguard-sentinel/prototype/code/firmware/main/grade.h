/* firmware/main/grade.h -- C99 port of model/grade.py's UsageRateEWMA,
 * rul_efc_to_weeks() and GradeStateMachine (design 02 §3.1/§3.3/§3.4).
 *
 * Thresholds are copied from model/grade.py's module constants, cross-checked
 * against model/artifacts_sim/sentinel_model_header.json's "grade_thresholds"
 * block (both agree -- see gen_golden.py's header parse). Portable C99, no
 * ESP-IDF/FreeRTOS dependency, host- and MCU-buildable.
 */
#ifndef SENTINEL_GRADE_H
#define SENTINEL_GRADE_H

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define GRADE_COLLECTING 0
#define GRADE_HEALTHY    1
#define GRADE_DEGRADING  2
#define GRADE_REPLACE    3
#define GRADE_SERVICE_NOW 4

const char *grade_name(int grade);

/* ---- §3.1 usage-rate EWMA (EFC/week), alpha=0.2, blends to a prior while
 * fewer than 4 weekly samples exist ---- */
typedef struct {
    float alpha;
    float prior_rate;
    float prior_sigma;
    float r;
    float var;
    int   n_updates;
} usage_rate_ewma_t;

void  usage_rate_ewma_init(usage_rate_ewma_t *u, float prior_rate_per_week, float prior_sigma_per_week);
void  usage_rate_ewma_update(usage_rate_ewma_t *u, float efc_delta, float days_elapsed);
float usage_rate_ewma_sigma(const usage_rate_ewma_t *u);

/* design 02 §3.1: RUL_cal = max(0, L_cal/AF_mean - age) * weeks/year */
float grade_calendar_bound_weeks(float age_years, float af_mean, float l_cal_years);

/* Converts RUL_EFC quantiles to RUL_weeks quantiles (sorted ascending),
 * capped by the calendar bound -- exact formulas from model/grade.py. */
void grade_rul_efc_to_weeks(float rul_efc_p10, float rul_efc_p50, float rul_efc_p90,
                             float r, float sigma_r, float age_years, float af_mean, float l_cal_years,
                             float *w_p10, float *w_p50, float *w_p90);

/* ---- §3.3/§3.4 grade state machine with hysteresis ---- */
typedef struct {
    int   current_grade;
    int   pending_grade;      /* -1 = none */
    int   pending_count;
    float pending_first_day;
    int   pre_anomaly_grade;
    int   have_n_weeks;
    int   n_weeks;
    int   have_n_last_update_day;
    float n_last_update_day;
} grade_state_machine_t;

void grade_sm_init(grade_state_machine_t *sm);

/* Advance the state machine by one inference. `day` must be monotonically
 * increasing (float days since some epoch, e.g. sample_count/86400).
 * Returns the grade after this update; *out_n_weeks is set iff the grade is
 * REPLACE (have_n_weeks=1), else left at have_n_weeks=0. */
int grade_sm_update(grade_state_machine_t *sm, float day, float soh_p50,
                     float rul_weeks_p10, float rul_weeks_p90,
                     bool have_enough_data, bool service_now,
                     int *out_have_n_weeks, int *out_n_weeks);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_GRADE_H */
