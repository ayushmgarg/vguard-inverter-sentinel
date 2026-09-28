"""ekf/ekf.py — 3-state EKF [SoC, V1, R0] for lead-acid, design 01.

Sign convention (CONTRACTS.md §1): callers of `EKF.step` pass current in the
**+charge / -discharge** convention used by the 1 Hz sim/feature stream.
Internally this module converts to the **+discharge / -charge** convention
used throughout design doc 01's equations (01 §1.3), so every formula below
matches the design doc literally. The C port (ekf.c / CONTRACTS §6) instead
takes discharge-positive current directly at its API boundary -- callers of
the C API must do the sign flip themselves (see ekf/test_ekf_host.c).

Implements per design 01:
  - 1-RC Thevenin, exact ZOH discretisation (§1.3)
  - OCV(SoC,T) bilinear LUT (§2.1-2.2), coulombic efficiency on charge (§1.3)
  - Peukert-corrected usable capacity, n=1.25 default (§2.5)
  - EKF Jacobians (§3.1), Q/R defaults incl. event-gated Q_R0 (§3.2)
  - Initialisation rules: persisted state / rest-OCV / humble 50% (§3.3)
  - Divergence guards: chi^2 innovation gate, hard bounds, P floor/ceiling,
    raw-coulomb cross-check, R0 sanity vs 3x LUT envelope (§3.4)
  - Full detection by charge-current taper -> SoC=1, close cycle, eta and
    measured capacity, latch (§5a, §7)
  - True rest-OCV anchor, charger verifiably OFF only -- the H30 fix (§5b)
  - R_int event estimator from |dI|>=5-10% C20 with charger-transition
    rejection, median filter over 20-50 events, T/SoC normalisation,
    SoH_R proxy (§6)
  - Zero-current auto-calibration of the current-sensor offset (§4)

Honest limitation: at 1 Hz (no burst/ALERT capture), the R_int estimator
uses consecutive-sample deltaI/deltaV instead of a sub-second burst fit, per
the documented "honest 1 Hz limitation" in 01 §6.1.

Deliberate deviation from §9's literal pseudocode: the generic per-tick
OCV-I*R0-V1 measurement correction only runs while charger_on is False (see
the comment in `step()`). §9's pseudocode runs it unconditionally every
tick; §0/§10 point 4 describe *why* that is unsafe under charge (real
flooded lead-acid absorption/float voltage sits far above what a few-mOhm
R0 can explain at realistic currents -- charger regulation overhead, not
IR drop). Running it unconditionally lets that overhead leak into the
fused SoC one small, individually chi^2-plausible innovation at a time,
which the gate cannot catch because no single tick is an outlier -- only
the accumulated bias is. Restricting it to charger-off ticks keeps §9's
literal per-tick correction where the model is actually valid, and leaves
SoC-while-charging to the coulomb-count predict step plus the two
explicit, physically-gated anchors (§5a/§5b), matching §10's own summary.
"""

from __future__ import annotations

import statistics
from typing import Deque, List, Optional
from collections import deque

from . import lut
from .params import EKFParams


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


class EKF:
    """3-state EKF: x = [SoC, V1 (V), R0 (ohm)]."""

    def __init__(self, params: Optional[EKFParams] = None,
                 initial_state: Optional[dict] = None):
        self.p = params or EKFParams()

        self.x = None  # type: Optional[List[float]]
        self.P = None  # type: Optional[List[List[float]]]
        self._initialized = False
        self._persisted_init = None
        if initial_state is not None:
            # 01 §3.3 rule 1: prefer persisted state over any re-anchor.
            self._persisted_init = initial_state

        # raw-coulomb cross-check counter (01 §3.4 item 4) -- corrected
        # (offset-cal'd + Peukert + temp + eta) but never anchor-corrected.
        self.soc_counter = 0.5
        # fully naive counter (no corrections at all) -- diagnostic only,
        # demonstrates the raw drift described in 01 §4.
        self.soc_raw_naive = 0.5

        self.i_offset_est_a = 0.0  # 01 §4 zero-current auto-cal

        self.full_timer_s = 0.0
        self.full_locked = False
        self.rest_timer_s = 0.0

        self.ah_out_cycle = 0.0
        self.ah_in_cycle = 0.0
        self.eta_measured: Optional[float] = None
        self.capacity_measured_ah: Optional[float] = None
        self.capacity_bol_ah: Optional[float] = None
        self.soh_capacity: Optional[float] = None

        self._r0_buf: Deque[float] = deque(maxlen=self.p.r0_max_buffer)
        self._r0_bol_ref: Optional[float] = None
        self.soh_r: float = 1.0
        self.n_r0_events = 0
        self.median_r0_ohm: Optional[float] = None

        self._prev_sample = None  # (I_discharge, V, charger_on)
        self._cross_check_bad_s = 0.0
        self.fault_cross_check = False

        self.t_s = 0.0
        self.last_innovation_rejected = False
        self.last_anchor = "none"

    # ------------------------------------------------------------------
    # initialisation
    # ------------------------------------------------------------------
    def _lazy_init(self, i_charge_pos: float, v: float, t: float,
                    charger_on: bool) -> None:
        p = self.p
        if self._persisted_init is not None:
            st = self._persisted_init
            soc0 = st["soc"]
            v10 = st.get("v1", 0.0)
            r00 = st.get("r0_ohm", lut.r0(soc0, t))
            p_diag = st.get("p_diag", (p.p0_soc_var, p.p0_v1_var,
                                        (r00 * p.p0_r0_var_frac) ** 2))
        elif (not charger_on) and abs(i_charge_pos) < p.i_rest_frac_c20 * p.c20_a:
            # 01 §3.3 rule 2: rest criteria hold right now -> anchor at init.
            soc0 = lut.ocv_inverse(v, t)
            v10 = 0.0
            r00 = lut.r0(soc0, t)
            p_diag = (0.02 ** 2, p.p0_v1_var, (r00 * p.p0_r0_var_frac) ** 2)
        else:
            # 01 §3.3 rule 3: humble 50%, wide P, converges at first anchor.
            soc0 = 0.5
            v10 = 0.0
            r00 = lut.r0(soc0, t)
            p_diag = (p.p0_soc_var, p.p0_v1_var, (r00 * p.p0_r0_var_frac) ** 2)

        self.x = [soc0, v10, r00]
        self.P = [[p_diag[0], 0.0, 0.0],
                  [0.0, p_diag[1], 0.0],
                  [0.0, 0.0, p_diag[2]]]
        self.soc_counter = soc0
        self.soc_raw_naive = soc0
        self.capacity_bol_ah = p.q_rated_ah
        self._initialized = True

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def step(self, I_charge_pos: float, V: float, T: float, charger_on: bool,
              dt: float = 1.0) -> dict:
        """One 1 Hz tick. I_charge_pos: +charge/-discharge amps (CONTRACTS §1)."""
        if not self._initialized:
            self._lazy_init(I_charge_pos, V, T, bool(charger_on))
            self.t_s += dt
            return self._state_dict()

        p = self.p
        charger_on = bool(charger_on)
        self.last_anchor = "none"

        i_charge_corr = self._auto_cal_offset(I_charge_pos, charger_on)
        I = -i_charge_corr  # design-doc convention: I>0 discharge (01 §1.3)

        self._update_naive_counters(I_charge_pos, i_charge_corr, I, T, dt)

        x_pred, P_pred = self._predict(I, T, dt)
        if charger_on:
            # 01 §0/H30: "float is not rest" -- under charge, terminal
            # voltage is OCV + I*R0 + V_pol *plus* the charger's own
            # absorption/float regulation overhead (real flooded lead-acid
            # sits ~0.8-1.7 V above rest OCV there, not explainable by a
            # few-mOhm R0 at realistic charge currents). Running the
            # generic OCV-branch correction unconditionally would silently
            # re-introduce exactly the H30 bug (voltage-implied SoC runs
            # away toward 100% over the whole absorption/float dwell, one
            # small-looking innovation at a time -- individually inside the
            # chi^2 gate, cumulatively not). So: while charging, trust the
            # coulomb-count predict step (design 01 §10 point 2-3) and the
            # two explicit, physically-gated anchors (§5a/§5b) only; the
            # generic per-tick voltage correction is restricted to when the
            # simple R0 branch is actually a good approximation -- discharge
            # and true rest (charger off).
            x_upd, P_upd = list(x_pred), [row[:] for row in P_pred]
            self.last_innovation_rejected = False
        else:
            x_upd, P_upd, y, S = self._measurement_update(x_pred, P_pred, I, V, T)
        x_upd, P_upd = self._clamp_state(x_upd, P_upd)

        x_upd, P_upd = self._full_detection(x_upd, P_upd, i_charge_corr, V, T,
                                             charger_on, dt)
        x_upd, P_upd = self._rest_anchor(x_upd, P_upd, i_charge_corr, V, T,
                                          charger_on, dt)
        self.P = P_upd
        self._last_T_for_event = T
        x_upd = self._r0_event(x_upd, i_charge_corr, I, V, charger_on)
        P_upd = self.P
        x_upd, P_upd = self._clamp_state(x_upd, P_upd)

        self._cross_check(x_upd[0])

        if I >= 0:
            self.ah_out_cycle += I * dt / 3600.0
        else:
            self.ah_in_cycle += -I * dt / 3600.0

        self.x, self.P = x_upd, P_upd
        self.t_s += dt
        return self._state_dict()

    # ------------------------------------------------------------------
    # zero-current auto-cal (01 §4)
    # ------------------------------------------------------------------
    def _auto_cal_offset(self, i_charge_raw: float, charger_on: bool) -> float:
        p = self.p
        i_corr = i_charge_raw - self.i_offset_est_a
        if (not charger_on) and abs(i_corr) < p.zero_cal_i_thresh_a:
            self.i_offset_est_a += p.zero_cal_alpha * (i_charge_raw - self.i_offset_est_a)
            i_corr = i_charge_raw - self.i_offset_est_a
        return i_corr

    def _update_naive_counters(self, i_charge_raw: float, i_charge_corr: float,
                                I_discharge: float, T: float, dt: float) -> None:
        p = self.p
        # fully naive: no offset cal, no Peukert, no eta -- pure Ah/Q_rated.
        self.soc_raw_naive += i_charge_raw * dt / (3600.0 * p.q_rated_ah)

        # corrected-but-unanchored cross-check counter (01 §3.4 item 4).
        Qu = self._q_usable(I_discharge, T)
        eta = 1.0 if I_discharge >= 0 else lut.eta_charge(self.soc_counter, T)
        self.soc_counter -= eta * I_discharge * dt / (3600.0 * Qu)
        self.soc_counter = _clip(self.soc_counter, 0.0, 1.0)

    # ------------------------------------------------------------------
    # predict (01 §1.3, §3.1)
    # ------------------------------------------------------------------
    def _q_usable(self, I_discharge: float, T: float) -> float:
        p = self.p
        return p.q_rated_ah * lut.f_temp(T) * lut.peukert_multiplier(
            I_discharge, p.c20_a, p.peukert_n)

    def _predict(self, I: float, T: float, dt: float):
        p = self.p
        soc, v1, r0 = self.x
        Qu = self._q_usable(I, T)
        eta = 1.0 if I >= 0 else lut.eta_charge(soc, T)
        tau = lut.tau(soc, T)
        R1 = lut.r1(soc, T)
        decay = pow(2.718281828459045, -dt / tau)

        # I*dt is in coulombs (A*s); /3600 converts to Ah to match Qu (Ah).
        soc_p = soc - eta * I * dt / (3600.0 * Qu)
        v1_p = v1 * decay + R1 * (1.0 - decay) * I
        r0_p = r0

        F = [[1.0, 0.0, 0.0],
             [0.0, decay, 0.0],
             [0.0, 0.0, 1.0]]
        # Q_R0 stays at the idle (near-zero) value here; the event-gated
        # inflation to (0.5 mOhm)^2 (01 §3.2) is applied directly to P[2][2]
        # inside _r0_event, around that single correction only.
        Q = (p.q_soc, p.q_v1, p.q_r0_idle)

        P = self.P
        # P_pred = F P F^T + Q  (F is diagonal-structured except decay term)
        P_pred = [[P[0][0], P[0][1] * decay, P[0][2]],
                  [P[1][0] * decay, P[1][1] * decay * decay, P[1][2] * decay],
                  [P[2][0], P[2][1] * decay, P[2][2]]]
        P_pred[0][0] += Q[0]
        P_pred[1][1] += Q[1]
        P_pred[2][2] += Q[2]
        return [soc_p, v1_p, r0_p], P_pred

    # ------------------------------------------------------------------
    # measurement update (01 §1.4, §3.1, §3.4 item 1)
    # ------------------------------------------------------------------
    def _measurement_update(self, x_pred, P_pred, I: float, V: float, T: float):
        p = self.p
        soc, v1, r0 = x_pred
        ocv = lut.ocv(soc, T)
        docv = lut.docv_dsoc(soc, T)
        y = V - (ocv - I * r0 - v1)
        H = [docv, -1.0, -I]

        S = self._HPHt(H, P_pred) + p.r_v
        if S <= 0:
            S = p.r_v
        gate = (y * y) / S
        self.last_innovation_rejected = gate >= p.chi2_gate
        if self.last_innovation_rejected:
            return list(x_pred), [row[:] for row in P_pred], y, S

        x_upd, P_upd = self._kalman_update(x_pred, P_pred, H, S, y)
        return x_upd, P_upd, y, S

    @staticmethod
    def _HPHt(H, P) -> float:
        # H P H^T for 1x3 H, 3x3 P
        v = [sum(H[j] * P[j][i] for j in range(3)) for i in range(3)]
        return sum(H[i] * v[i] for i in range(3))

    @staticmethod
    def _kalman_update(x, P, H, S, y):
        # K = P H^T / S (3x1); x' = x + K y; P' = (I - K H) P, symmetrised.
        PHt = [sum(P[i][j] * H[j] for j in range(3)) for i in range(3)]
        K = [PHt[i] / S for i in range(3)]
        x_new = [x[i] + K[i] * y for i in range(3)]
        # P' = (I - K H) P, computed directly:
        P_new = [[0.0, 0.0, 0.0] for _ in range(3)]
        KH = [[K[i] * H[j] for j in range(3)] for i in range(3)]
        for i in range(3):
            for j in range(3):
                acc = P[i][j]
                for k in range(3):
                    acc -= KH[i][k] * P[k][j]
                P_new[i][j] = acc
        # symmetrise
        for i in range(3):
            for j in range(i + 1, 3):
                m = 0.5 * (P_new[i][j] + P_new[j][i])
                P_new[i][j] = m
                P_new[j][i] = m
        return x_new, P_new

    # ------------------------------------------------------------------
    # divergence guards: hard bounds + covariance floor/ceiling (01 §3.4 2-3)
    # ------------------------------------------------------------------
    def _clamp_state(self, x, P):
        p = self.p
        x = list(x)
        x[0] = _clip(x[0], p.soc_bounds[0], p.soc_bounds[1])
        x[2] = _clip(x[2], p.r0_bounds_ohm[0], p.r0_bounds_ohm[1])
        P = [row[:] for row in P]
        for i in range(3):
            P[i][i] = _clip(P[i][i], p.p_floor[i], p.p_ceiling[i])
        for i in range(3):
            for j in range(i + 1, 3):
                m = 0.5 * (P[i][j] + P[j][i])
                P[i][j] = m
                P[j][i] = m
        return x, P

    def _cross_check(self, soc_fused: float) -> None:
        p = self.p
        if abs(soc_fused - self.soc_counter) > p.cross_check_thresh:
            self._cross_check_bad_s += 1.0
        else:
            self._cross_check_bad_s = 0.0
        self.fault_cross_check = self._cross_check_bad_s >= p.cross_check_dwell_s

    # ------------------------------------------------------------------
    # full detection by charge-current taper, charger ON (01 §5a, §7)
    # ------------------------------------------------------------------
    def _v_full(self, T: float) -> float:
        p = self.p
        return p.v_full_25c + p.v_full_tempco_v_per_c * (T - 25.0)

    def _full_detection(self, x, P, i_charge_corr: float, V: float, T: float,
                         charger_on: bool, dt: float):
        p = self.p
        i_tail = p.i_tail_frac_c20 * p.c20_a
        v_full = self._v_full(T)
        tapering = charger_on and (V >= v_full) and (abs(i_charge_corr) < i_tail)
        if tapering:
            self.full_timer_s += dt
            if self.full_timer_s >= p.t_full_dwell_s and not self.full_locked:
                self._close_cycle()
                x = list(x)
                x[0] = 1.0
                P = [row[:] for row in P]
                P[0][0] = min(P[0][0], 0.005 ** 2)
                self.full_locked = True
                self.last_anchor = "full"
        else:
            self.full_timer_s = 0.0
            if i_charge_corr < 0:  # discharging again -> arm for next full cycle
                self.full_locked = False
        return x, P

    def _close_cycle(self) -> None:
        p = self.p
        if self.ah_in_cycle > 0:
            self.eta_measured = self.ah_out_cycle / self.ah_in_cycle
        dod = self.ah_out_cycle / p.q_rated_ah
        if dod >= p.min_dod_for_capacity_cycle:
            self.capacity_measured_ah = self.ah_out_cycle
            if self.capacity_bol_ah:
                self.soh_capacity = self.capacity_measured_ah / self.capacity_bol_ah
        self.ah_out_cycle = 0.0
        self.ah_in_cycle = 0.0

    # ------------------------------------------------------------------
    # true rest-OCV anchor, charger verifiably OFF only -- H30 fix (01 §5b)
    # ------------------------------------------------------------------
    def _rest_anchor(self, x, P, i_charge_corr: float, V: float, T: float,
                      charger_on: bool, dt: float):
        p = self.p
        i_rest = p.i_rest_frac_c20 * p.c20_a
        resting = (not charger_on) and (abs(i_charge_corr) < i_rest)
        if resting:
            self.rest_timer_s += dt
        else:
            self.rest_timer_s = 0.0
            return x, P

        if self.rest_timer_s < p.t_rest_prov_s:
            return x, P

        r_ocv = p.r_rest_high if self.rest_timer_s >= p.t_rest_high_s else p.r_rest_med
        self.last_anchor = "rest_high" if self.rest_timer_s >= p.t_rest_high_s else "rest_prov"

        soc, v1, r0 = x
        ocv = lut.ocv(soc, T)
        docv = lut.docv_dsoc(soc, T)
        y = V - ocv
        H = [docv, -1.0, 0.0]  # I~0 at rest -> dV/dR0 term negligible

        S = self._HPHt(H, P) + r_ocv
        if S <= 0:
            return x, P
        x_upd, P_upd = self._kalman_update(x, P, H, S, y)
        return x_upd, P_upd

    # ------------------------------------------------------------------
    # R_int event estimator (01 §6)
    # ------------------------------------------------------------------
    def _r0_event(self, x, i_charge_corr: float, I_discharge: float, V: float,
                  charger_on: bool):
        p = self.p
        prev = self._prev_sample
        self._prev_sample = (I_discharge, V, charger_on)
        if prev is None:
            return x
        i_prev, v_prev, chg_prev = prev
        dI = I_discharge - i_prev
        if abs(dI) < p.di_thresh_frac_c20 * p.c20_a:
            return x
        if charger_on != chg_prev:
            return x  # 01 §6.1: reject charger-transition-coincident events

        r_meas = (v_prev - V) / dI  # 01 §6.1: (V_before-V_after)/(I_after-I_before)
        if r_meas <= 0:
            return x

        soc_now, _v1, _r0 = x
        r0_lut_now = lut.r0(soc_now, self._last_T_for_event or 25.0)
        r0_lut_ref = lut.r0(1.0, 25.0)
        if r0_lut_now <= 0:
            return x
        r_norm = r_meas * r0_lut_ref / r0_lut_now  # T/SoC normalisation, 01 §6.2

        envelope_hi = r0_lut_ref * p.r0_sanity_envelope_mult
        if not (0.0 < r_norm <= envelope_hi):
            return x  # 01 §3.4 item 5: misclassified charger transition, discard

        self._r0_buf.append(r_norm)
        self.n_r0_events += 1
        if len(self._r0_buf) < p.r0_min_events:
            return x

        median_r0 = statistics.median(self._r0_buf)
        self.median_r0_ohm = median_r0
        if self._r0_bol_ref is None:
            self._r0_bol_ref = median_r0  # first stable estimate = "as-new" ref
        self.soh_r = self._r0_bol_ref / median_r0 if median_r0 > 0 else self.soh_r

        # event-gated Q_R0: "open" (inflate P[2,2]) then correct then "close"
        # (the correction itself shrinks P again) -- 01 §3.2/§9.
        P = self.P
        P = [row[:] for row in P]
        P[2][2] += p.q_r0_event
        H = [0.0, 0.0, 1.0]
        S = P[2][2] + p.r0_event_meas_var
        y = median_r0 - x[2]
        x_upd, P_upd = self._kalman_update(x, P, H, S, y)
        self.P = P_upd
        return x_upd

    # track T for the event normaliser without threading it through every call
    _last_T_for_event: Optional[float] = None

    # ------------------------------------------------------------------
    # output
    # ------------------------------------------------------------------
    def _state_dict(self) -> dict:
        soc, v1, r0 = self.x
        return {
            "t_s": self.t_s,
            "soc": soc,
            "v1": v1,
            "r0_ohm": r0,
            "r0_mohm": r0 * 1000.0,
            "p_soc_var": self.P[0][0],
            "p_v1_var": self.P[1][1],
            "p_r0_var": self.P[2][2],
            "soc_counter": self.soc_counter,
            "soc_raw_naive": self.soc_raw_naive,
            "i_offset_est_a": self.i_offset_est_a,
            "full_locked": self.full_locked,
            "full_timer_s": self.full_timer_s,
            "rest_timer_s": self.rest_timer_s,
            "anchor": self.last_anchor,
            "innovation_rejected": self.last_innovation_rejected,
            "fault_cross_check": self.fault_cross_check,
            "n_r0_events": self.n_r0_events,
            "median_r0_ohm": self.median_r0_ohm,
            "soh_r": self.soh_r,
            "soh_capacity": self.soh_capacity,
            "eta_measured": self.eta_measured,
            "capacity_measured_ah": self.capacity_measured_ah,
        }
