"""Streaming per-cycle feature pipeline, design 02-TinyML-SoH-RUL-Pipeline.md SS1.0-1.10.

Reads the 1 Hz stream produced by sim/battery_sim.py (or any file matching CONTRACTS.md
SS1) and reduces it to one feature row per outage/recharge cycle, matching
CONTRACTS.md SS2 / features/schema.py exactly.

This module does NOT have access to the EKF (design 01) SoC/R_int estimate -- that is
a separate module. Instead it:
  - runs its own simple coulomb-counting SoC proxy, anchored to 1.0 at each detected
    FULL_CHARGE event (tail-current criterion, design 01 SS5a / design 02 SS1.0);
  - computes an R_int proxy from the same median-filtered dV/dI transient estimate used
    for sag_ref (design 01 SS6.1 in miniature), UNLESS an external r_int series is
    supplied via `external_r_int` (the "hook" required by the module A brief) -- if a
    battery_XXX_rint.csv with columns t,r_int_ohm exists next to the stream, it is used.

See features/README.md for the full section-by-section mapping and honesty notes
(in particular: rest-OCV rarely fires on this synthetic load model, and several
uncharacterized constants -- kappa_CA, the sag g(SoC)/h(T) tables -- are documented
approximations, not bench-fit values).

CLI: python -m features.cycle_features --in data/sim_1hz/ --out data/features_sim.csv
"""
import argparse
import glob
import math
import os

import numpy as np
import pandas as pd

from features.schema import ALL_COLUMNS, DYNAMIC_FEATURES, LABEL_COLUMNS, OPTIONAL_COLUMNS, STATIC_FEATURES

# ---------------------------------------------------------------------------
# state machine thresholds, design 02 SS1.0 (I is contract convention: +charge -discharge)
# ---------------------------------------------------------------------------
V_BOOST = 14.4
CV_ENTRY_V = V_BOOST - 0.1
FLOAT_V_LO, FLOAT_V_HI = 13.6, 13.8
CHARGER_V_TEMP_COEF = -0.024  # V/degC per 12V pack; matches sim/physics.py, real chargers
# temperature-compensate the target (sim's charger does the same) so CC->CV / CV->FLOAT
# labelling tracks the real controller on hot days instead of getting stuck in CC.
DISCHARGE_TRIG_FRAC = 0.02
CHARGE_TRIG_FRAC = 0.01
TAIL_FRAC = 0.02
DEBOUNCE_S = 3
TAIL_DWELL_S = 30 * 60
V_FULL_THRESH = 13.5  # design 01 SS5a: V_term >= ~13.5V (12V flooded, 25C)

SAG_DI_FRAC = 0.05
SAG_MIN_T_IN_STATE = 60
RINT_DI_FRAC = 0.05
RINT_SOC_LO, RINT_SOC_HI = 0.4, 0.95

BASELINE_N_CYCLES = 10
STALE_MAX = 30

ICA_BINS = 120
ICA_V0 = 12.0
ICA_DV = 0.02
ICA_PEAK_LO_V, ICA_PEAK_HI_V = 12.9, 13.8
ICA_TEMP_LO, ICA_TEMP_HI = 15.0, 45.0
ICA_CC_TOL = 0.10
ICA_MIN_SOC_START = 0.70
ICA_MIN_Q_CC_FRAC = 0.15

CA_KAPPA_T = 0.01  # design 02 SS1.8 leaves this uncharacterized; documented assumption
MIN_ETA_C_DOD = 0.10  # eta_c valid only if Q_dis >= 0.1C (design 02 SS1.6)

REST_I_FRAC = 0.005  # |I| <= 0.005C, design 02 SS1.9
REST_PROVISIONAL_S = 60 * 60
DOD_MIN_CAPACITY_CYCLE = 0.30  # design 01 SS7 (not directly used here, kept for reference)

SOH_EOL = 80.0

STATE_FLOAT, STATE_DISCHARGE, STATE_CC, STATE_CV = 0, 1, 2, 3


def _ocv_lookup(soc):
    """Same table as sim/physics.py SOC_PTS/OCV_PTS (design 01 SS2.1), duplicated here
    since features must not depend on sim internals -- a real device ships this table."""
    pts_soc = (0.00, 0.10, 0.25, 0.50, 0.75, 0.90, 1.00)
    pts_ocv = (11.80, 11.90, 12.05, 12.30, 12.50, 12.60, 12.70)
    if soc <= 0.0:
        return pts_ocv[0]
    if soc >= 1.0:
        return pts_ocv[-1]
    for i in range(6):
        if soc <= pts_soc[i + 1]:
            frac = (soc - pts_soc[i]) / (pts_soc[i + 1] - pts_soc[i])
            return pts_ocv[i] + frac * (pts_ocv[i + 1] - pts_ocv[i])
    return pts_ocv[-1]


def _ocv_inv(v):
    """Inverse OCV lookup (V -> SoC), for rest-OCV re-anchoring (design 02 SS1.9)."""
    pts_soc = (0.00, 0.10, 0.25, 0.50, 0.75, 0.90, 1.00)
    pts_ocv = (11.80, 11.90, 12.05, 12.30, 12.50, 12.60, 12.70)
    if v <= pts_ocv[0]:
        return 0.0
    if v >= pts_ocv[-1]:
        return 1.0
    for i in range(6):
        if v <= pts_ocv[i + 1]:
            frac = (v - pts_ocv[i]) / (pts_ocv[i + 1] - pts_ocv[i])
            return pts_soc[i] + frac * (pts_soc[i + 1] - pts_soc[i])
    return 1.0


def _sag_g_soc(soc):
    """Normalises the resistance-vs-SoC rise to a 70% SoC reference (design 02 SS1.1:
    '8-entry SoC->70% table'). Bench-fit table not available; this uses the same
    shape as the R0(SoC) physics used in sim/physics.py, documented as an assumption."""
    ref = 1.0 + 0.40 * (1.0 - 0.70)
    return ref / (1.0 + 0.40 * (1.0 - soc))


def _sag_h_temp(temp_c, kappa_r=0.015):
    return 1.0 + kappa_r * (temp_c - 25.0)


def _median_or_nan(values):
    if not values:
        return float("nan")
    return float(np.median(np.asarray(values, dtype=np.float64)))


class _RunningBaseline:
    """Median of the first BASELINE_N_CYCLES cycles that produced a valid value."""

    def __init__(self, n=BASELINE_N_CYCLES):
        self.n = n
        self.buf = []
        self.locked_value = None

    def offer(self, value, cycle_idx):
        if self.locked_value is not None:
            return
        if cycle_idx < self.n and value is not None and not math.isnan(value):
            self.buf.append(value)
        if cycle_idx >= self.n - 1:
            self.locked_value = _median_or_nan(self.buf) if self.buf else float("nan")

    def ratio(self, value):
        base = self.value()
        if value is None or math.isnan(value) or base is None or math.isnan(base) or base == 0.0:
            return float("nan")
        return value / base

    def shift(self, value):
        base = self.value()
        if value is None or math.isnan(value) or base is None or math.isnan(base):
            return float("nan")
        return value - base

    def value(self):
        if self.locked_value is not None:
            return self.locked_value
        return _median_or_nan(self.buf) if self.buf else float("nan")


def process_battery(battery_id, csv_path, c_rated_ah, external_rint_path=None):
    df = pd.read_csv(csv_path)
    n = len(df)
    t = df["t"].to_numpy(dtype=np.int64)
    I = df["I"].to_numpy(dtype=np.float64)
    V = df["V"].to_numpy(dtype=np.float64)
    T = df["T"].to_numpy(dtype=np.float64)
    soh_true = df["soh_true"].to_numpy(dtype=np.float64)

    ext_rint = None
    if external_rint_path and os.path.exists(external_rint_path):
        rdf = pd.read_csv(external_rint_path)
        ext_rint = dict(zip(rdf["t"].to_numpy(dtype=np.int64), rdf["r_int_ohm"].to_numpy(dtype=np.float64)))

    # ---- vectorised precompute (design 02 SS1.1 ΔI/ΔV over the 2-sample window) ----
    dI = np.zeros(n)
    dV = np.zeros(n)
    if n > 2:
        dI[1:-1] = I[2:] - I[:-2]
        dV[1:-1] = V[2:] - V[:-2]
    with np.errstate(divide="ignore", invalid="ignore"):
        # NOTE: design 02 SS1.1 writes R_step = -dV/dI in design 01's internal sign
        # convention (I>0 = discharge). This module works in CONTRACTS.md's convention
        # (I: +charge, -discharge), which flips the sign: R_step = +dV/dI here.
        r_step_raw = np.where(np.abs(dI) > 1e-9, dV / dI, np.nan)
    di_valid_mask = np.abs(dI) >= SAG_DI_FRAC * c_rated_ah
    tail_a = TAIL_FRAC * c_rated_ah
    discharge_trig_a = DISCHARGE_TRIG_FRAC * c_rated_ah
    charge_trig_a = CHARGE_TRIG_FRAC * c_rated_ah
    rest_i_a = REST_I_FRAC * c_rated_ah

    I_list = I.tolist()
    V_list = V.tolist()
    T_list = T.tolist()
    t_list = t.tolist()
    rstep_list = r_step_raw.tolist()
    divalid_list = di_valid_mask.tolist()
    soh_list = soh_true.tolist()

    # ---- streaming state ----
    state = STATE_FLOAT
    t_in_state = 0
    cnt_dis_trig = 0
    cnt_chg_trig = 0
    full_dwell_cnt = 0
    awaiting_full_charge = False
    cnt_rest = 0

    soc_est = 1.0
    hours_since_full = 0.0
    ema_v = V_list[0] if n else 12.5
    ema_alpha = 1.0 - math.exp(-1.0 / 5.0)
    r_int_last = None

    cycles = []
    cycle_idx = 0

    # cross-cycle running statics
    efc_cum = 0.0
    s_total_cum = 0.0
    s_float_cum = 0.0
    s_disch_cum = 0.0
    q_dis_total = 0.0
    q_dis_dod50 = 0.0
    seconds_low_soc = 0
    seconds_total = 0

    eta_c_last = float("nan")
    eta_c_stale = STALE_MAX
    ic_h_last = float("nan")
    ic_v_last = float("nan")
    ic_stale = STALE_MAX

    base_r = _RunningBaseline()
    base_sag = _RunningBaseline()
    base_ca = _RunningBaseline()
    base_ic_h = _RunningBaseline()
    base_ic_v = _RunningBaseline()

    # in-progress cycle accumulators (reset at cycle boundaries, i.e. FLOAT->DISCHARGE)
    def new_cycle_acc():
        return dict(
            sag_vals=[], rint_vals=[], q_dis_ah=0.0, q_chg_ah=0.0, q_cv_ah=0.0, q_cc_ah=0.0,
            t_sum=0.0, t_n=0, soc_start=soc_est, soc_min=soc_est, t_full_h=hours_since_full,
            ca5=None, ca60=None, soc_at_cv0=None, cc_start_soc=None,
            qbin=[0.0] * ICA_BINS, ica_ok=False, t_cv_local=0, ocv_err_vals=[],
        )

    acc = new_cycle_acc()
    in_discharge_span = False  # true once we've entered DISCHARGE at least once (first real cycle)

    for i in range(n):
        cur_t = t_list[i]
        cur_I = I_list[i]
        cur_V = V_list[i]
        cur_T = T_list[i]

        ema_v = ema_v + ema_alpha * (cur_V - ema_v)

        # ---- R_int proxy / external hook ----
        r_int_now = None
        if ext_rint is not None:
            r_int_now = ext_rint.get(cur_t)
        if r_int_now is None and divalid_list[i]:
            rs = rstep_list[i]
            if rs is not None and not math.isnan(rs) and RINT_SOC_LO <= soc_est <= RINT_SOC_HI:
                r_int_now = rs * _sag_h_temp(cur_T)
        if r_int_now is not None and not math.isnan(r_int_now) and 0.0005 <= r_int_now <= 0.2:
            r_int_last = r_int_now
            acc["rint_vals"].append(r_int_now)

        # ---- sag_ref (design 02 SS1.1) ----
        if state == STATE_DISCHARGE and t_in_state >= SAG_MIN_T_IN_STATE and divalid_list[i]:
            rs = rstep_list[i]
            if rs is not None and not math.isnan(rs) and rs > 0:
                sag_norm = rs * (0.1 * c_rated_ah)
                sag_ref = sag_norm * _sag_g_soc(soc_est) * _sag_h_temp(cur_T)
                acc["sag_vals"].append(sag_ref)

        # ---- ICA dQ/dV accumulation during CC (design 02 SS1.7) ----
        if state == STATE_CC and ICA_TEMP_LO <= cur_T <= ICA_TEMP_HI:
            v_corr = ema_v - cur_I * (r_int_last if r_int_last is not None else 0.0)
            b = int(math.floor((v_corr - ICA_V0) / ICA_DV))
            if 0 <= b < ICA_BINS:
                acc["qbin"][b] += abs(cur_I)

        # ---- coulomb accumulation ----
        if state == STATE_DISCHARGE and cur_I < 0:
            acc["q_dis_ah"] += (-cur_I) / 3600.0
        if state in (STATE_CC, STATE_CV) and cur_I > 0:
            acc["q_chg_ah"] += cur_I / 3600.0
            if state == STATE_CC:
                acc["q_cc_ah"] += cur_I / 3600.0
            else:
                acc["q_cv_ah"] += cur_I / 3600.0

        # ---- CA_60 at CV entry (design 02 SS1.8) ----
        if state == STATE_CV:
            if acc["soc_at_cv0"] is None:
                acc["soc_at_cv0"] = soc_est
                acc["t_cv_local"] = 0
            if acc["t_cv_local"] == 5:
                acc["ca5"] = abs(cur_I)
            if acc["t_cv_local"] == 60:
                acc["ca60"] = abs(cur_I)
            acc["t_cv_local"] += 1

        # ---- rest-OCV (design 02 SS1.9); charger-off proxy = DISCHARGE state ----
        if state == STATE_DISCHARGE and abs(cur_I) <= rest_i_a:
            cnt_rest += 1
        else:
            cnt_rest = 0
        if cnt_rest >= REST_PROVISIONAL_S:
            ocv_base_est = cur_V + 0.0035 * (cur_T - 25.0)  # undo sim's temp offset (design 01 SS2.2)
            soc_implied = _ocv_inv(ocv_base_est)
            acc["ocv_err_vals"].append(soc_implied - soc_est)

        # ---- t_mean / soc extremes bookkeeping ----
        acc["t_sum"] += cur_T
        acc["t_n"] += 1
        acc["soc_min"] = min(acc["soc_min"], soc_est)

        # ---- statics bookkeeping ----
        af = math.exp(6400.0 * (1.0 / 298.15 - 1.0 / (cur_T + 273.15)))
        d_days = af / 86400.0
        s_total_cum += d_days
        if state == STATE_FLOAT:
            s_float_cum += d_days
        if soc_est < 0.5:
            s_disch_cum += d_days
            seconds_low_soc += 1
        seconds_total += 1

        # ---- soc_est coulomb count (own simple counter, no EKF) ----
        soc_est = min(1.2, max(-0.1, soc_est + cur_I * (1.0 / 3600.0) / c_rated_ah))
        hours_since_full += 1.0 / 3600.0

        # ================= state machine (design 02 SS1.0) =================
        t_in_state += 1
        if state == STATE_FLOAT:
            if cur_I < -discharge_trig_a:
                cnt_dis_trig += 1
            else:
                cnt_dis_trig = 0
            if cnt_dis_trig >= DEBOUNCE_S:
                state = STATE_DISCHARGE
                t_in_state = 0
                cnt_dis_trig = 0
                in_discharge_span = True
                awaiting_full_charge = True
                # t_full_k / soc_start must be captured at DISCHARGE START, not at
                # acc-creation time (which is right after the previous FULL_CHARGE,
                # when hours_since_full is always ~0) -- design 02 SS1.3.
                acc["t_full_h"] = hours_since_full
                acc["soc_start"] = soc_est
                acc["soc_min"] = soc_est

        elif state == STATE_DISCHARGE:
            if cur_I > charge_trig_a:
                cnt_chg_trig += 1
            else:
                cnt_chg_trig = 0
            if cnt_chg_trig >= DEBOUNCE_S:
                state = STATE_CC
                t_in_state = 0
                cnt_chg_trig = 0
                acc["cc_start_soc"] = soc_est  # SoC when CC charging begins (design 02 SS1.7)

        elif state == STATE_CC:
            if cur_V >= CV_ENTRY_V + CHARGER_V_TEMP_COEF * (cur_T - 25.0):
                state = STATE_CV
                t_in_state = 0
                # ICA validity (design 02 SS1.7): SoC_start <= 70%, >= 0.15C charged in CC
                acc["ica_ok"] = (acc["cc_start_soc"] is not None and acc["cc_start_soc"] <= ICA_MIN_SOC_START
                                  and acc["q_cc_ah"] >= ICA_MIN_Q_CC_FRAC * c_rated_ah)

        elif state == STATE_CV:
            comp = CHARGER_V_TEMP_COEF * (cur_T - 25.0)
            entered_float_via_vdrop = (FLOAT_V_LO + comp) <= cur_V <= (FLOAT_V_HI + comp)
            if entered_float_via_vdrop:
                state = STATE_FLOAT
                t_in_state = 0

        # ---- FULL_CHARGE detection (design 01 SS5a / design 02 SS1.0), decoupled
        # from the CC/CV/FLOAT *label* above: a real charger's tail-current dwell is
        # a joint V>=V_full AND I<tail condition, independent of which named
        # sub-phase it is nominally in (our sim's controller flips its target
        # voltage from 14.4V to 13.7V the instant tail current is reached, so
        # requiring the dwell to complete *while still labelled CV* would almost
        # never fire -- see features/README.md). ----
        if state in (STATE_CC, STATE_CV, STATE_FLOAT) and cur_V >= V_FULL_THRESH and abs(cur_I) < tail_a:
            full_dwell_cnt += 1
        else:
            full_dwell_cnt = 0
        if awaiting_full_charge and full_dwell_cnt >= TAIL_DWELL_S:
            # FULL_CHARGE event -> close out the cycle. Update the last-valid/
            # staleness trackers for THIS cycle's own eta_c and ICA result first,
            # then build the row from the fresh values.
            if acc["q_dis_ah"] >= MIN_ETA_C_DOD * c_rated_ah and acc["q_chg_ah"] > 1e-6:
                eta_c_last = acc["q_dis_ah"] / acc["q_chg_ah"]
                eta_c_stale = 0
            else:
                eta_c_stale = min(STALE_MAX, eta_c_stale + 1)

            if acc["ica_ok"]:
                qbin = np.asarray(acc["qbin"], dtype=np.float64)
                smooth = np.convolve(qbin, np.ones(5) / 5.0, mode="same")
                lo_bin = int((ICA_PEAK_LO_V - ICA_V0) / ICA_DV)
                hi_bin = int((ICA_PEAK_HI_V - ICA_V0) / ICA_DV)
                window = smooth[max(0, lo_bin):min(ICA_BINS, hi_bin)]
                if window.size and window.max() > 0:
                    peak_local = int(np.argmax(window))
                    peak_bin = max(0, lo_bin) + peak_local
                    ic_h_last = float(window[peak_local])
                    ic_v_last = ICA_V0 + (peak_bin + 0.5) * ICA_DV
                    ic_stale = 0
                else:
                    ic_stale = min(STALE_MAX, ic_stale + 1)
            else:
                ic_stale = min(STALE_MAX, ic_stale + 1)

            cycle_idx = _finish_cycle(
                cycles, cycle_idx, acc, battery_id, c_rated_ah, soh_list[i],
                efc_cum, s_total_cum, s_float_cum, s_disch_cum,
                q_dis_total, q_dis_dod50, seconds_low_soc, seconds_total,
                cur_t, base_r, base_sag, base_ca, base_ic_h, base_ic_v,
                eta_c_last, eta_c_stale, ic_h_last, ic_v_last, ic_stale,
            )
            efc_cum += acc["q_dis_ah"] / c_rated_ah
            q_dis_total += acc["q_dis_ah"]
            if (acc["soc_start"] - acc["soc_min"]) >= 0.5:
                q_dis_dod50 += acc["q_dis_ah"]

            base_r.offer(_median_or_nan(acc["rint_vals"]), cycle_idx - 1)
            base_sag.offer(_median_or_nan(acc["sag_vals"]), cycle_idx - 1)
            ca_ref = _ca_ref(acc, c_rated_ah)
            base_ca.offer(ca_ref, cycle_idx - 1)
            if acc["ica_ok"] and not math.isnan(ic_h_last):
                base_ic_h.offer(ic_h_last, cycle_idx - 1)
                base_ic_v.offer(ic_v_last, cycle_idx - 1)

            state = STATE_FLOAT
            t_in_state = 0
            full_dwell_cnt = 0
            awaiting_full_charge = False
            hours_since_full = 0.0
            acc = new_cycle_acc()

    _last_ctx = dict(
        eta_c_last=eta_c_last, eta_c_stale=eta_c_stale, ic_h_last=ic_h_last, ic_v_last=ic_v_last,
        ic_stale=ic_stale, base_r=base_r, base_sag=base_sag, base_ca=base_ca, base_ic_h=base_ic_h,
        base_ic_v=base_ic_v,
    )
    return cycles, _last_ctx


def _ca_ref(acc, c_rated_ah):
    if acc["ca60"] is None or acc["soc_at_cv0"] is None:
        return float("nan")
    ca60_norm = acc["ca60"] / c_rated_ah
    # kappa_CA and c(SoC) are not characterised in the design doc; documented assumption
    # (features/README.md): kappa_CA ~ 0.01 /degC, c(SoC) treated as identity.
    t_corr = 1.0  # no per-sample T stored at ca60 instant; correction folded into ratio-only use
    return ca60_norm * t_corr


def _finish_cycle(cycles, cycle_idx, acc, battery_id, c_rated_ah, soh_true_now,
                   efc_cum, s_total_cum, s_float_cum, s_disch_cum,
                   q_dis_total, q_dis_dod50, seconds_low_soc, seconds_total,
                   cur_t, base_r, base_sag, base_ca, base_ic_h, base_ic_v,
                   eta_c_last, eta_c_stale, ic_h_last, ic_v_last, ic_stale):
    """Builds and appends the feature row for the cycle that just closed."""
    row = {}
    sag_val = _median_or_nan(acc["sag_vals"])
    r_val = _median_or_nan(acc["rint_vals"])
    q_dis_ah = acc["q_dis_ah"]
    dod = max(0.0, acc["soc_start"] - acc["soc_min"])
    t_full_h = acc["t_full_h"]
    t_mean = acc["t_sum"] / acc["t_n"] if acc["t_n"] else float("nan")

    row["r_ratio"] = base_r.ratio(r_val)
    row["sag_ratio"] = base_sag.ratio(sag_val)
    row["q_dis_norm"] = q_dis_ah / c_rated_ah
    row["dod"] = dod
    row["cv_frac"] = (acc["q_cv_ah"] / (acc["q_cc_ah"] + acc["q_cv_ah"])
                       if (acc["q_cc_ah"] + acc["q_cv_ah"]) > 1e-9 else float("nan"))
    row["t_mean"] = t_mean
    row["ln_tfull"] = math.log1p(t_full_h / 24.0)
    # rest-OCV rarely observable on this load model (see features/README.md)
    row["ocv_err"] = _median_or_nan(acc["ocv_err_vals"])

    row["_ca_ref_raw"] = _ca_ref(acc, c_rated_ah)
    row["ca_ratio"] = base_ca.ratio(row["_ca_ref_raw"])
    del row["_ca_ref_raw"]

    row["battery_id"] = battery_id
    row["cycle_idx"] = cycle_idx
    row["t_end_s"] = float(cur_t)   # end-of-cycle epoch seconds (optional column, see schema.OPTIONAL_COLUMNS)
    row["soh_true"] = soh_true_now
    row["_efc_after"] = efc_cum + q_dis_ah / c_rated_ah  # temp, used for RUL pass
    row["st_total_per_day"] = float("nan")  # filled after age_years is known (see below)
    row["_s_total_cum"] = s_total_cum
    row["st_float"] = s_float_cum
    row["_q_dis_total_after"] = q_dis_total + q_dis_ah
    row["_q_dis_dod50_after"] = q_dis_dod50 + (q_dis_ah if dod >= 0.5 else 0.0)
    row["f_dod50"] = row["_q_dis_dod50_after"] / row["_q_dis_total_after"] if row["_q_dis_total_after"] > 0 else 0.0
    row["f_lowsoc"] = seconds_low_soc / seconds_total if seconds_total else 0.0
    row["age_years"] = cur_t / (86400.0 * 365.0)
    row["st_total_per_day"] = s_total_cum / max(1e-6, cur_t / 86400.0)
    row["efc"] = row["_efc_after"]

    row["eta_c"] = eta_c_last
    row["eta_stale"] = eta_c_stale / float(STALE_MAX)
    row["ic_peak_h"] = base_ic_h.ratio(ic_h_last)
    row["ic_peak_v"] = base_ic_v.shift(ic_v_last)
    row["ica_stale"] = ic_stale / float(STALE_MAX)

    for k in ("_efc_after", "_q_dis_total_after", "_q_dis_dod50_after", "_s_total_cum"):
        row.pop(k, None)

    cycles.append(row)
    return cycle_idx + 1


def _compute_rul(cycle_rows):
    """rul_efc_true(k) = EFC(at first soh_true<=80) - EFC(after cycle k), clipped >=0.
    NaN for every cycle of a battery that never reaches EoL in the recorded data
    (CONTRACTS.md SS2)."""
    soh = np.array([r["soh_true"] for r in cycle_rows], dtype=np.float64)
    efc = np.array([r["efc"] for r in cycle_rows], dtype=np.float64)
    below = np.where(soh <= SOH_EOL)[0]
    if below.size == 0:
        for r in cycle_rows:
            r["rul_efc_true"] = float("nan")
        return
    efc_at_eol = efc[below[0]]
    for r, e in zip(cycle_rows, efc):
        r["rul_efc_true"] = max(0.0, efc_at_eol - e)


def _process_one_battery(battery_id, csv_path, c_rated_ah, in_dir):
    ext_path = os.path.join(in_dir, "battery_%03d_rint.csv" % battery_id)
    cycles, ctx = process_battery(battery_id, csv_path, c_rated_ah,
                                   external_rint_path=ext_path if os.path.exists(ext_path) else None)
    if cycles:
        _compute_rul(cycles)
    return cycles


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="in_dir", type=str, default="data/sim_1hz/", help="input directory (sim output)")
    ap.add_argument("--out", type=str, default="data/features_sim.csv", help="output feature CSV")
    args = ap.parse_args(argv)

    manifest_path = os.path.join(args.in_dir, "manifest.csv")
    manifest = pd.read_csv(manifest_path)
    all_rows = []
    for _, row in manifest.iterrows():
        battery_id = int(row["battery_id"])
        c_rated_ah = float(row["C_rated_Ah"])
        csv_path = os.path.join(args.in_dir, "battery_%03d.csv" % battery_id)
        if not os.path.exists(csv_path):
            continue
        cycles = _process_one_battery(battery_id, csv_path, c_rated_ah, args.in_dir)
        print("battery %03d: %d cycles -> %d feature rows" % (battery_id, int(row.get("n_cycles", -1)), len(cycles)))
        all_rows.extend(cycles)

    out_df = pd.DataFrame(all_rows)
    for col in ALL_COLUMNS:
        if col not in out_df.columns:
            out_df[col] = float("nan")
    out_df = out_df[ALL_COLUMNS + [c for c in OPTIONAL_COLUMNS if c in out_df.columns]]
    for col in DYNAMIC_FEATURES:
        out_df[col] = out_df[col].astype("float32")
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    out_df.to_csv(args.out, index=False)
    print("wrote %d rows -> %s" % (len(out_df), args.out))


if __name__ == "__main__":
    main()
