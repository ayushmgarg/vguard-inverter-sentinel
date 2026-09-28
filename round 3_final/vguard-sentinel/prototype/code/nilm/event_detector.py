"""nilm/event_detector.py -- Lu & Li moving-average change detector (design 06 Sec 2).

Implements the exact parameters of design 06 Sec 2.2 (frames at the AFE's
3.125 Hz fast-stream rate unless overridden), the pseudocode of Sec 2.3
(steady/transient state machine, voltage normalisation, settle test), the
ON/OFF pairing rule of Sec 2.4, and the 13-feature signature of Sec 3.1
(features that require AFE-only fields -- r_pk, h -- are NaN when the input
stream has no Ipk/Pf/Ph, i.e. a Tier-0 PZEM).

This module is deliberately mirrored (not code-generated) in
nilm/event_detector.c so the two can be cross-checked on the same stream
(tests/test_nilm.py::test_c_matches_python).
"""
from __future__ import annotations

import dataclasses
import math
from collections import OrderedDict
from typing import List, Optional

import numpy as np
import pandas as pd

V_NORM_REF = 230.0


@dataclasses.dataclass
class DetParams:
    N_pre: int = 4                    # frames (design: 4 @ 3.125 Hz = 1.28 s)
    N_post: int = 4
    P_th_abs: float = 25.0            # W
    P_th_rel: float = 0.02            # fraction of pre-event P
    Q_th: float = 25.0                # var
    T_merge: int = 2                  # frames, alarm-suppression after an emit
    SS_win: int = 5                   # frames, steady-state window
    T_max_transient_s: float = 15.0   # s
    eps_deriv: float = 15.0           # W/frame
    rate_hz: float = 3.125


@dataclasses.dataclass
class Event:
    t0: float
    t_off: Optional[float] = None
    dP: float = 0.0
    dQ: float = 0.0
    r_pk: float = float("nan")
    t_settle_s: float = 0.0
    A_tr: float = 0.0
    h: float = float("nan")
    dur_s: float = float("nan")
    label: Optional[str] = None
    confidence: float = 0.0
    tod_sin: float = 0.0
    tod_cos: float = 0.0
    src: int = 0
    ch: int = 0
    period_s: float = float("nan")
    cluster_id: Optional[int] = None
    kind: str = "ON"
    paired: bool = False

    @property
    def phi_deg(self) -> float:
        return math.degrees(math.atan2(self.dQ, self.dP)) if self.dP or self.dQ else 0.0

    def signature(self) -> "OrderedDict[str, float]":
        """The 13-row feature table of design 06 Sec 3.1 (tod expands to 2
        scalars: sin/cos of hour-of-day)."""
        return OrderedDict([
            ("dP", self.dP), ("dQ", self.dQ), ("phi_deg", self.phi_deg),
            ("r_pk", self.r_pk), ("t_settle_s", self.t_settle_s), ("A_tr", self.A_tr),
            ("h", self.h), ("dTHD_I", float("nan")), ("dur_s", self.dur_s),
            ("period_s", self.period_s), ("tod_sin", self.tod_sin), ("tod_cos", self.tod_cos),
            ("src", float(self.src)), ("ch", float(self.ch)),
        ])


def _tod(t: float):
    hour = (t % 86400.0) / 3600.0
    ang = 2 * math.pi * hour / 24.0
    return math.sin(ang), math.cos(ang)


class EventDetector:
    """Streaming Lu & Li detector. Call push() once per frame."""

    def __init__(self, params: Optional[DetParams] = None, has_afe: bool = False, ch: int = 0):
        self.p = params or DetParams()
        self.has_afe = has_afe
        self.ch = ch
        maxlen = int(self.p.T_max_transient_s * self.p.rate_hz) + \
            2 * (self.p.N_pre + self.p.N_post) + self.p.SS_win + 8
        self._maxlen = maxlen
        self.buf_t: List[float] = []
        self.buf_Pn: List[float] = []
        self.buf_Q: List[float] = []
        self.buf_Ipk: List[float] = []
        self.buf_Pf: List[float] = []
        self.buf_Ph: List[float] = []

        self.mode = "STEADY"
        self.k = -1
        self.t0_idx = None
        self.ipk_max = 0.0
        self.ipk_pre = float("nan")
        self.ss_ref_P = 0.0
        self.ss_ref_Q = 0.0
        self.ss_ref_Pf = float("nan")
        self.ss_ref_Ph = float("nan")
        self.suppress_until = -1
        self.events: List[Event] = []

    def _trim(self):
        excess = len(self.buf_t) - self._maxlen
        if excess > 0:
            del self.buf_t[:excess]
            del self.buf_Pn[:excess]
            del self.buf_Q[:excess]
            del self.buf_Ipk[:excess]
            del self.buf_Pf[:excess]
            del self.buf_Ph[:excess]

    def push(self, t: float, P: float, Q: float, V: float,
              Ipk: float = float("nan"), Pf: float = float("nan"), Ph: float = float("nan")) -> Optional[Event]:
        self.k += 1
        Pn = P * (V_NORM_REF / V) ** 2 if V and V > 1e-6 else P
        self.buf_t.append(t)
        self.buf_Pn.append(Pn)
        self.buf_Q.append(Q)
        self.buf_Ipk.append(Ipk)
        self.buf_Pf.append(Pf)
        self.buf_Ph.append(Ph)

        p = self.p
        emitted = None

        if self.mode == "STEADY":
            need = p.N_pre + p.N_post
            if len(self.buf_Pn) >= need and self.k >= self.suppress_until:
                pre_P = self.buf_Pn[-need:-p.N_post]
                post_P = self.buf_Pn[-p.N_post:]
                pre_Q = self.buf_Q[-need:-p.N_post]
                post_Q = self.buf_Q[-p.N_post:]
                m_pre, m_post = float(np.mean(pre_P)), float(np.mean(post_P))
                q_pre, q_post = float(np.mean(pre_Q)), float(np.mean(post_Q))
                thresh = max(p.P_th_abs, p.P_th_rel * abs(m_pre))
                if abs(m_post - m_pre) > thresh or abs(q_post - q_pre) > p.Q_th:
                    self.mode = "TRANSIENT"
                    self.t0_idx = self.k - p.N_post
                    pre_ipk = [v for v in self.buf_Ipk[-need:-p.N_post] if not math.isnan(v)]
                    self.ipk_pre = float(np.mean(pre_ipk)) if pre_ipk else float("nan")
                    self.ipk_max = self.ipk_pre if not math.isnan(self.ipk_pre) else 0.0
                    self.ss_ref_P = m_pre
                    self.ss_ref_Q = q_pre
        else:
            if not math.isnan(Ipk):
                self.ipk_max = max(self.ipk_max, Ipk)
            elapsed_frames = self.k - self.t0_idx
            elapsed_s = elapsed_frames / p.rate_hz
            settled = False
            if len(self.buf_Pn) >= p.SS_win:
                win = self.buf_Pn[-p.SS_win:]
                std_p = float(np.std(win))
                mean_p = float(np.mean(win))
                diffs = np.abs(np.diff(win))
                max_diff = float(np.max(diffs)) if len(diffs) else 0.0
                settled = std_p < max(8.0, 0.01 * abs(mean_p)) and max_diff < p.eps_deriv
            if settled or elapsed_s > p.T_max_transient_s:
                ss_win = p.SS_win
                P_ss_new = float(np.mean(self.buf_Pn[-ss_win:]))
                Q_ss_new = float(np.mean(self.buf_Q[-ss_win:]))
                Pf_new = float(np.nanmean(self.buf_Pf[-ss_win:])) if self.has_afe else float("nan")
                Ph_new = float(np.nanmean(self.buf_Ph[-ss_win:])) if self.has_afe else float("nan")

                dP = P_ss_new - self.ss_ref_P
                dQ = Q_ss_new - self.ss_ref_Q
                if abs(dP) < max(p.P_th_abs, p.P_th_rel * abs(self.ss_ref_P)) and abs(dQ) < p.Q_th:
                    pass  # discard per pseudocode
                else:
                    start = max(0, len(self.buf_t) - (self.k - self.t0_idx + 1))
                    transient_Pn = self.buf_Pn[start:]
                    dt = 1.0 / p.rate_hz
                    A_tr = float(sum((v - P_ss_new) * dt for v in transient_Pn))
                    t_settle_s = (self.k - self.t0_idx) / p.rate_hz

                    if self.has_afe and not math.isnan(self.ipk_max) and not math.isnan(self.ipk_pre):
                        i_step = math.hypot(dP, dQ) / V_NORM_REF
                        extra_ipk = max(self.ipk_max - self.ipk_pre, 0.0)
                        r_pk = 1.0 + extra_ipk / i_step if i_step > 1e-6 else float("nan")
                    else:
                        r_pk = float("nan")

                    if self.has_afe and not math.isnan(Pf_new) and not math.isnan(self.ss_ref_Pf):
                        dPf = Pf_new - self.ss_ref_Pf
                        dPh = Ph_new - self.ss_ref_Ph
                        h = dPh / dPf if abs(dPf) > 1e-6 else float("nan")
                    else:
                        h = float("nan")

                    t0_time = self.buf_t[start]
                    tod_sin, tod_cos = _tod(t0_time)
                    ev = Event(t0=t0_time, dP=dP, dQ=dQ, r_pk=r_pk, t_settle_s=t_settle_s,
                               A_tr=A_tr, h=h, tod_sin=tod_sin, tod_cos=tod_cos, ch=self.ch)
                    self.events.append(ev)
                    emitted = ev

                self.ss_ref_P, self.ss_ref_Q = P_ss_new, Q_ss_new
                self.ss_ref_Pf, self.ss_ref_Ph = Pf_new, Ph_new
                self.mode = "STEADY"
                self.suppress_until = self.k + p.T_merge

        self._trim()
        return emitted


def run_detector_on_stream(df: pd.DataFrame, has_afe: bool, rate_hz: float,
                            params: Optional[DetParams] = None, ch: int = 0) -> List[Event]:
    p = params or DetParams(rate_hz=rate_hz)
    p.rate_hz = rate_hz
    det = EventDetector(p, has_afe=has_afe, ch=ch)
    for row in df.itertuples(index=False):
        det.push(row.t, row.P, row.Q, row.Vrms,
                  Ipk=getattr(row, "Ipk", float("nan")),
                  Pf=getattr(row, "Pf", float("nan")),
                  Ph=getattr(row, "Ph", float("nan")))
    return det.events


def pair_events(events: List[Event], max_gap_s: float = 24 * 3600.0) -> List[Event]:
    """ON/OFF pairing, design 06 Sec 2.4. Mutates dur_s/t_off/paired in place
    and returns the same list."""
    for ev in events:
        ev.kind = "ON" if ev.dP > 0 else "OFF"

    open_ons: List[int] = []  # indices into `events`, chronological
    for i, ev in enumerate(events):
        if ev.kind == "OFF":
            match = None
            for j in reversed(open_ons):
                on_ev = events[j]
                if ev.t0 - on_ev.t0 > max_gap_s:
                    break
                dP_sum = on_ev.dP + ev.dP
                dQ_sum = on_ev.dQ + ev.dQ
                dP_ok = abs(dP_sum) <= max(15.0, 0.10 * abs(on_ev.dP))
                dQ_tol = max(15.0, 0.15 * abs(on_ev.dQ)) if abs(on_ev.dQ) > 1e-6 else 15.0
                dQ_ok = abs(dQ_sum) <= dQ_tol
                if dP_ok and dQ_ok:
                    match = j
                    break
            if match is not None:
                on_ev = events[match]
                on_ev.t_off = ev.t0
                on_ev.dur_s = ev.t0 - on_ev.t0
                on_ev.paired = True
                ev.paired = True
                open_ons.remove(match)
        else:
            open_ons.append(i)
    return events
