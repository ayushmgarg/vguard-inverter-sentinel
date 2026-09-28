"""model/grade.py — RUL(EFC) -> weeks conversion and the grade state machine.

Design 02 §3 exactly:
  §3.1 usage-rate EWMA (r, sigma_r) converts RUL_EFC quantiles to RUL_weeks,
       capped by a calendar bound.
  §3.3 grade thresholds (Healthy / Degrading / Replace / Service now).
  §3.4 hysteresis: 3 consecutive inferences on distinct cycles spanning >=5
       days before a grade changes; upgrading to Healthy needs a harder bar
       than staying Healthy; N (weeks-to-replace) moves at most +/-2/week.

This module is pure Python/numpy, no torch dependency, so it can run
standalone on-device-equivalent logic on host, and is unit-tested in
tests/test_model.py without needing a trained model.
"""

from __future__ import annotations
import numpy as np

import math

GRADES = ("COLLECTING", "HEALTHY", "DEGRADING", "REPLACE", "SERVICE_NOW")

WEEKS_PER_YEAR = 52.1775

# design 02 §3.3 thresholds
HEALTHY_SOH_MIN = 88.0
HEALTHY_RUL_P10_MIN_WK = 26.0
HEALTHY_REENTRY_SOH_MIN = 90.0     # §3.4: harder bar to (re)enter Healthy
HEALTHY_REENTRY_RUL_P10_MIN_WK = 30.0
DEGRADING_SOH_MIN = 82.0
DEGRADING_RUL_P10_MIN_WK = 8.0

HYSTERESIS_N_CONSECUTIVE = 3
HYSTERESIS_MIN_SPAN_DAYS = 5.0
N_MAX_STEP_PER_WEEK = 2.0
N_MIN_UPDATE_INTERVAL_DAYS = 7.0


# --------------------------------------------------------------------------- #
# §3.1 usage-rate EWMA and weeks conversion
# --------------------------------------------------------------------------- #

class UsageRateEWMA:
    """EWMA(alpha=0.2, ~8-week window) of EFC/week with a variance estimate.

    Blends toward `prior_rate_per_week` while fewer than 4 weekly samples
    have been observed (design 02 §3.1: "blend a per-region prior when
    < 4 weeks of history").
    """

    def __init__(self, alpha=0.2, prior_rate_per_week=3.5, prior_sigma_per_week=1.0):
        self.alpha = alpha
        self.prior_rate = prior_rate_per_week
        self.prior_sigma = prior_sigma_per_week
        self.r = prior_rate_per_week
        self.var = prior_sigma_per_week ** 2
        self.n_updates = 0

    def update(self, efc_delta, days_elapsed):
        """Feed one observed (EFC consumed, days elapsed) sample."""
        if days_elapsed <= 0:
            return
        rate_sample = efc_delta / (days_elapsed / 7.0)
        if self.n_updates == 0:
            self.r = rate_sample
            self.var = self.prior_sigma ** 2
        else:
            prev_r = self.r
            self.r = self.alpha * rate_sample + (1 - self.alpha) * self.r
            self.var = self.alpha * (rate_sample - prev_r) ** 2 + (1 - self.alpha) * self.var
        self.n_updates += 1
        if self.n_updates < 4:
            # blend toward the prior while history is thin
            blend = self.n_updates / 4.0
            self.r = blend * self.r + (1 - blend) * self.prior_rate
            self.var = blend * self.var + (1 - blend) * self.prior_sigma ** 2

    @property
    def sigma(self):
        return math.sqrt(max(self.var, 0.0))


def calendar_bound_weeks(age_years, af_mean=1.0, l_cal_years=5.0):
    """RUL_cal = max(0, L_cal/AF_mean - age), design 02 §3.1."""
    af_mean = max(af_mean, 1e-6)
    return max(0.0, (l_cal_years / af_mean - age_years)) * WEEKS_PER_YEAR


def rul_efc_to_weeks(rul_efc_p10, rul_efc_p50, rul_efc_p90, r, sigma_r,
                      age_years=0.0, af_mean=1.0, l_cal_years=5.0):
    """design 02 §3.1 exact formulas, then per-quantile min with the
    calendar bound, then a defensive ascending-sort clamp (not in the spec
    text but keeps the published band ordered even under EWMA noise)."""
    r = max(r, 1e-6)
    denom_hi_rate = r + sigma_r          # used for P10 (fastest plausible usage)
    denom_lo_rate = max(r - sigma_r, 0.3 * r)  # used for P90 (slowest plausible usage)

    w_p10 = rul_efc_p10 / max(denom_hi_rate, 1e-6)
    w_p50 = rul_efc_p50 / r
    w_p90 = rul_efc_p90 / max(denom_lo_rate, 1e-6)

    cal = calendar_bound_weeks(age_years, af_mean, l_cal_years)
    w_p10, w_p50, w_p90 = min(w_p10, cal), min(w_p50, cal), min(w_p90, cal)

    lo, mid, hi = sorted([w_p10, w_p50, w_p90])
    return lo, mid, hi


# --------------------------------------------------------------------------- #
# §3.3 / §3.4 grade state machine with hysteresis
# --------------------------------------------------------------------------- #

def _raw_grade(current_grade, soh_p50, rul_weeks_p10):
    if current_grade == "HEALTHY":
        healthy_ok = soh_p50 >= HEALTHY_SOH_MIN and rul_weeks_p10 > HEALTHY_RUL_P10_MIN_WK
    else:
        healthy_ok = (soh_p50 >= HEALTHY_REENTRY_SOH_MIN and
                      rul_weeks_p10 > HEALTHY_REENTRY_RUL_P10_MIN_WK)
    if healthy_ok:
        return "HEALTHY"
    if soh_p50 >= DEGRADING_SOH_MIN and rul_weeks_p10 >= DEGRADING_RUL_P10_MIN_WK:
        return "DEGRADING"
    return "REPLACE"


class GradeStateMachine:
    """One instance per battery. Call `update(...)` once per inference."""

    def __init__(self):
        self.current_grade = "COLLECTING"
        self._pending_grade = None
        self._pending_count = 0
        self._pending_first_day = None
        self._pre_anomaly_grade = "COLLECTING"  # restored when SERVICE_NOW clears
        self.n_weeks = None
        self._n_last_update_day = None

    def update(self, day, soh_p50, rul_weeks_p10, rul_weeks_p90,
               have_enough_data=True, service_now=False):
        """Advance the state machine by one inference.

        `day` is a monotonically increasing day-count (float ok) used for
        the >=5-day hysteresis span and the weekly N-update cadence.
        Returns dict(grade=..., n_weeks=..., window=(p10,p90) or None).
        """
        if not have_enough_data:
            self.current_grade = "COLLECTING"
            self._pending_grade = None
            self._pending_count = 0
            return self._publish(None, None)

        if service_now:
            if self.current_grade != "SERVICE_NOW":
                self._pre_anomaly_grade = self.current_grade
            self.current_grade = "SERVICE_NOW"
            self._pending_grade = None
            self._pending_count = 0
            n = self._update_n(day, rul_weeks_p10)
            return self._publish(n, (None, None))

        # anomaly just cleared: resume from whatever grade held before it
        base_grade = self.current_grade
        if base_grade == "SERVICE_NOW":
            base_grade = self._pre_anomaly_grade
            self.current_grade = base_grade
            self._pending_grade = None
            self._pending_count = 0

        target = _raw_grade(self.current_grade, soh_p50, rul_weeks_p10)

        if target == self.current_grade:
            self._pending_grade = None
            self._pending_count = 0
        else:
            if self._pending_grade != target:
                self._pending_grade = target
                self._pending_count = 1
                self._pending_first_day = day
            else:
                self._pending_count += 1
            span = day - self._pending_first_day
            if (self._pending_count >= HYSTERESIS_N_CONSECUTIVE and
                    span >= HYSTERESIS_MIN_SPAN_DAYS):
                self.current_grade = target
                self._pending_grade = None
                self._pending_count = 0

        n = None
        window = None
        if self.current_grade == "REPLACE":
            n = self._update_n(day, rul_weeks_p10)
            window = (rul_weeks_p10, rul_weeks_p90)
        else:
            self.n_weeks = None
            self._n_last_update_day = None

        return self._publish(n, window)

    def _update_n(self, day, rul_weeks_p10):
        if rul_weeks_p10 is None or not np.isfinite(rul_weeks_p10):
            return self.n_weeks  # unknown RUL: keep the last published N (or None)
        raw_n = max(1, round(rul_weeks_p10))
        if self.n_weeks is None:
            self.n_weeks = raw_n
            self._n_last_update_day = day
            return self.n_weeks
        if (self._n_last_update_day is None or
                day - self._n_last_update_day >= N_MIN_UPDATE_INTERVAL_DAYS):
            step = max(-N_MAX_STEP_PER_WEEK, min(N_MAX_STEP_PER_WEEK, raw_n - self.n_weeks))
            self.n_weeks = max(1, round(self.n_weeks + step))
            self._n_last_update_day = day
        return self.n_weeks

    def _publish(self, n_weeks, window):
        return {"grade": self.current_grade, "n_weeks": n_weeks, "window": window}
