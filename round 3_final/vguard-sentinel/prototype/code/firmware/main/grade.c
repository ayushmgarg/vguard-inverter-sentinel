/* firmware/main/grade.c -- see grade.h. Line-for-line port of model/grade.py where the
 * Python is authoritative; deviations (integer day-count vs Python's day float, no numpy)
 * are noted inline. C99, no malloc. */
#include "grade.h"

#include <math.h>
#include <stddef.h>

#define WEEKS_PER_YEAR 52.1775f

/* model/grade.py module constants */
#define HEALTHY_SOH_MIN 88.0f
#define HEALTHY_RUL_P10_MIN_WK 26.0f
#define HEALTHY_REENTRY_SOH_MIN 90.0f
#define HEALTHY_REENTRY_RUL_P10_MIN_WK 30.0f
#define DEGRADING_SOH_MIN 82.0f
#define DEGRADING_RUL_P10_MIN_WK 8.0f

#define HYSTERESIS_N_CONSECUTIVE 3
#define HYSTERESIS_MIN_SPAN_DAYS 5.0f
#define N_MAX_STEP_PER_WEEK 2.0f
#define N_MIN_UPDATE_INTERVAL_DAYS 7.0f

const char *grade_name(int grade) {
    switch (grade) {
        case GRADE_COLLECTING: return "COLLECTING";
        case GRADE_HEALTHY: return "HEALTHY";
        case GRADE_DEGRADING: return "DEGRADING";
        case GRADE_REPLACE: return "REPLACE";
        case GRADE_SERVICE_NOW: return "SERVICE_NOW";
        default: return "UNKNOWN";
    }
}

void usage_rate_ewma_init(usage_rate_ewma_t *u, float prior_rate_per_week, float prior_sigma_per_week) {
    u->alpha = 0.2f;
    u->prior_rate = prior_rate_per_week;
    u->prior_sigma = prior_sigma_per_week;
    u->r = prior_rate_per_week;
    u->var = prior_sigma_per_week * prior_sigma_per_week;
    u->n_updates = 0;
}

void usage_rate_ewma_update(usage_rate_ewma_t *u, float efc_delta, float days_elapsed) {
    if (days_elapsed <= 0.0f) return;
    float rate_sample = efc_delta / (days_elapsed / 7.0f);
    if (u->n_updates == 0) {
        u->r = rate_sample;
        u->var = u->prior_sigma * u->prior_sigma;
    } else {
        float prev_r = u->r;
        u->r = u->alpha * rate_sample + (1.0f - u->alpha) * u->r;
        u->var = u->alpha * (rate_sample - prev_r) * (rate_sample - prev_r) + (1.0f - u->alpha) * u->var;
    }
    u->n_updates++;
    if (u->n_updates < 4) {
        float blend = (float)u->n_updates / 4.0f;
        u->r = blend * u->r + (1.0f - blend) * u->prior_rate;
        u->var = blend * u->var + (1.0f - blend) * (u->prior_sigma * u->prior_sigma);
    }
}

float usage_rate_ewma_sigma(const usage_rate_ewma_t *u) {
    float v = u->var;
    if (v < 0.0f) v = 0.0f;
    return sqrtf(v);
}

float grade_calendar_bound_weeks(float age_years, float af_mean, float l_cal_years) {
    if (af_mean < 1e-6f) af_mean = 1e-6f;
    float bound = (l_cal_years / af_mean) - age_years;
    if (bound < 0.0f) bound = 0.0f;
    return bound * WEEKS_PER_YEAR;
}

static void sort3(float *a, float *b, float *c) {
    float v[3] = {*a, *b, *c};
    for (int i = 1; i < 3; i++) {
        float key = v[i];
        int j = i - 1;
        while (j >= 0 && v[j] > key) { v[j + 1] = v[j]; j--; }
        v[j + 1] = key;
    }
    *a = v[0]; *b = v[1]; *c = v[2];
}

void grade_rul_efc_to_weeks(float rul_efc_p10, float rul_efc_p50, float rul_efc_p90,
                             float r, float sigma_r, float age_years, float af_mean, float l_cal_years,
                             float *w_p10, float *w_p50, float *w_p90) {
    if (r < 1e-6f) r = 1e-6f;
    float denom_hi_rate = r + sigma_r;
    float denom_lo_rate = r - sigma_r;
    if (denom_lo_rate < 0.3f * r) denom_lo_rate = 0.3f * r;

    float p10 = rul_efc_p10 / (denom_hi_rate > 1e-6f ? denom_hi_rate : 1e-6f);
    float p50 = rul_efc_p50 / r;
    float p90 = rul_efc_p90 / (denom_lo_rate > 1e-6f ? denom_lo_rate : 1e-6f);

    float cal = grade_calendar_bound_weeks(age_years, af_mean, l_cal_years);
    if (p10 > cal) p10 = cal;
    if (p50 > cal) p50 = cal;
    if (p90 > cal) p90 = cal;

    sort3(&p10, &p50, &p90);
    *w_p10 = p10; *w_p50 = p50; *w_p90 = p90;
}

static int raw_grade(int current_grade, float soh_p50, float rul_weeks_p10) {
    int healthy_ok;
    if (current_grade == GRADE_HEALTHY) {
        healthy_ok = (soh_p50 >= HEALTHY_SOH_MIN) && (rul_weeks_p10 > HEALTHY_RUL_P10_MIN_WK);
    } else {
        healthy_ok = (soh_p50 >= HEALTHY_REENTRY_SOH_MIN) && (rul_weeks_p10 > HEALTHY_REENTRY_RUL_P10_MIN_WK);
    }
    if (healthy_ok) return GRADE_HEALTHY;
    if (soh_p50 >= DEGRADING_SOH_MIN && rul_weeks_p10 >= DEGRADING_RUL_P10_MIN_WK) return GRADE_DEGRADING;
    return GRADE_REPLACE;
}

void grade_sm_init(grade_state_machine_t *sm) {
    sm->current_grade = GRADE_COLLECTING;
    sm->pending_grade = -1;
    sm->pending_count = 0;
    sm->pending_first_day = 0.0f;
    sm->pre_anomaly_grade = GRADE_COLLECTING;
    sm->have_n_weeks = 0;
    sm->n_weeks = 0;
    sm->have_n_last_update_day = 0;
    sm->n_last_update_day = 0.0f;
}

static int update_n(grade_state_machine_t *sm, float day, bool have_rul, float rul_weeks_p10) {
    if (!have_rul) return sm->n_weeks; /* keep last published N */
    long raw_n = lroundf(rul_weeks_p10);
    if (raw_n < 1) raw_n = 1;
    if (!sm->have_n_weeks) {
        sm->n_weeks = (int)raw_n;
        sm->have_n_weeks = 1;
        sm->n_last_update_day = day;
        sm->have_n_last_update_day = 1;
        return sm->n_weeks;
    }
    if (!sm->have_n_last_update_day || (day - sm->n_last_update_day) >= N_MIN_UPDATE_INTERVAL_DAYS) {
        float step = (float)raw_n - (float)sm->n_weeks;
        if (step > N_MAX_STEP_PER_WEEK) step = N_MAX_STEP_PER_WEEK;
        if (step < -N_MAX_STEP_PER_WEEK) step = -N_MAX_STEP_PER_WEEK;
        long updated = lroundf((float)sm->n_weeks + step);
        if (updated < 1) updated = 1;
        sm->n_weeks = (int)updated;
        sm->n_last_update_day = day;
        sm->have_n_last_update_day = 1;
    }
    return sm->n_weeks;
}

int grade_sm_update(grade_state_machine_t *sm, float day, float soh_p50,
                     float rul_weeks_p10, float rul_weeks_p90,
                     bool have_enough_data, bool service_now,
                     int *out_have_n_weeks, int *out_n_weeks) {
    *out_have_n_weeks = 0;
    *out_n_weeks = 0;

    if (!have_enough_data) {
        sm->current_grade = GRADE_COLLECTING;
        sm->pending_grade = -1;
        sm->pending_count = 0;
        return sm->current_grade;
    }

    if (service_now) {
        if (sm->current_grade != GRADE_SERVICE_NOW) sm->pre_anomaly_grade = sm->current_grade;
        sm->current_grade = GRADE_SERVICE_NOW;
        sm->pending_grade = -1;
        sm->pending_count = 0;
        int n = update_n(sm, day, true, rul_weeks_p10);
        *out_have_n_weeks = 1; *out_n_weeks = n;
        return sm->current_grade;
    }

    int base_grade = sm->current_grade;
    if (base_grade == GRADE_SERVICE_NOW) {
        base_grade = sm->pre_anomaly_grade;
        sm->current_grade = base_grade;
        sm->pending_grade = -1;
        sm->pending_count = 0;
    }

    int target = raw_grade(sm->current_grade, soh_p50, rul_weeks_p10);

    if (target == sm->current_grade) {
        sm->pending_grade = -1;
        sm->pending_count = 0;
    } else {
        if (sm->pending_grade != target) {
            sm->pending_grade = target;
            sm->pending_count = 1;
            sm->pending_first_day = day;
        } else {
            sm->pending_count++;
        }
        float span = day - sm->pending_first_day;
        if (sm->pending_count >= HYSTERESIS_N_CONSECUTIVE && span >= HYSTERESIS_MIN_SPAN_DAYS) {
            sm->current_grade = target;
            sm->pending_grade = -1;
            sm->pending_count = 0;
        }
    }

    if (sm->current_grade == GRADE_REPLACE) {
        int n = update_n(sm, day, true, rul_weeks_p10);
        (void)rul_weeks_p90; /* published as the window's high end by the caller, not
                                 needed by the N-weeks step itself (mirrors grade.py) */
        *out_have_n_weeks = 1; *out_n_weeks = n;
    } else {
        sm->have_n_weeks = 0;
        sm->have_n_last_update_day = 0;
    }
    return sm->current_grade;
}
