"""nilm/appliance_sim.py -- synthetic aggregate AC power stream for an Indian home.

Implements the factory-prior appliance table of design doc
``06-NILM-Appliance-Disaggregation.md`` Sec 3.2: fixed-speed fridge (5-6x inrush,
20-40 min periodicity), fixed-speed 1.5 t AC (~13 s settle), storage geyser
(resistive), a 0.5-1 HP pump, an iron that cycles while in use, a mixer-grinder
that runs in short bursts, ceiling fans, LED lighting, an LED TV, and an
always-on baseline (router/chargers/standby).

Produces the CONTRACTS.md Sec 4 AC power stream:
    t, Vrms, Irms, P, Q, PF, f   (+ Ipk, Pf, Ph when the AFE variant is requested,
                                    NaN otherwise -- a Tier-0 PZEM has no AFE)
plus a ground-truth event log (one row per ON and one per OFF transition) used
by tests/test_nilm.py to score the detector and classifier.

Honesty note: this is a *synthetic* testbed. Per-appliance transient shapes are
first-order exponential approximations of inrush/settle behaviour, not captured
waveforms. Mains voltage and frequency follow bounded mean-reverting random
walks, not a physical grid model. See nilm/README.md Sec "Limits".
"""
from __future__ import annotations

import dataclasses
import math
from typing import Callable, List, Optional, Tuple

import numpy as np
import pandas as pd

V_NOM = 230.0
F_NOM = 50.0


# --------------------------------------------------------------------------- #
# Appliance profile definitions (design 06 Sec 3.2)
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class ApplianceSpec:
    name: str
    physics_class: str          # RESISTIVE / MOTOR / ELECTRONIC (rule layer, Sec 4.1)
    dP_range: Tuple[float, float]        # steady-state active power step, W
    pf_range: Tuple[float, float]        # power factor range -> derives Q
    r_pk_range: Tuple[float, float]      # inrush current ratio Ipk/Irms_step
    t_settle_range: Tuple[float, float]  # s, settling time
    h_range: Tuple[float, float]         # harmonic share dP_harm/dP_fund
    circuit: int                          # 0 = inverter output CT, 1 = mains CT
    schedule: str                         # which schedule generator to use
    schedule_kwargs: dict


APPLIANCES: List[ApplianceSpec] = [
    ApplianceSpec(
        "fridge", "MOTOR", (80, 200), (0.6, 0.8), (5.0, 6.0), (1.0, 1.8), (0.0, 0.08),
        circuit=0, schedule="cycle",
        schedule_kwargs=dict(on_range=(5 * 60, 20 * 60), off_range=(15 * 60, 25 * 60)),
    ),
    ApplianceSpec(
        "ac_fixed", "MOTOR", (1400, 1800), (0.8, 0.9), (5.0, 7.0), (11.0, 15.0), (0.0, 0.10),
        circuit=1, schedule="cycle_windowed",
        schedule_kwargs=dict(
            on_range=(10 * 60, 25 * 60), off_range=(5 * 60, 15 * 60),
            n_windows=(1, 2), window_dur=(3600, 3 * 3600),
        ),
    ),
    ApplianceSpec(
        "geyser", "RESISTIVE", (2000, 3000), (0.97, 1.0), (1.0, 1.05), (0.1, 0.4), (0.0, 0.02),
        circuit=1, schedule="cycle",
        schedule_kwargs=dict(on_range=(10 * 60, 45 * 60), off_range=(20 * 60, 90 * 60)),
    ),
    ApplianceSpec(
        "pump", "MOTOR", (375, 900), (0.70, 0.85), (4.0, 6.0), (1.0, 3.0), (0.0, 0.05),
        circuit=1, schedule="sessions",
        schedule_kwargs=dict(n_sessions=(1, 2), session_dur=(5 * 60, 25 * 60)),
    ),
    ApplianceSpec(
        "iron", "RESISTIVE", (750, 1500), (0.98, 1.0), (1.0, 1.1), (0.1, 0.5), (0.0, 0.02),
        circuit=0, schedule="burst_session",
        schedule_kwargs=dict(
            n_sessions=(0, 2), session_dur=(5 * 60, 15 * 60),
            burst_on=(20, 60), burst_off=(15, 40),
        ),
    ),
    ApplianceSpec(
        "mixer", "MOTOR", (400, 750), (0.8, 0.9), (2.0, 3.0), (0.3, 1.0), (0.10, 0.20),
        circuit=0, schedule="standalone_bursts",
        schedule_kwargs=dict(n_bursts=(2, 4), burst_dur=(30, 180)),
    ),
    ApplianceSpec(
        "fan", "ELECTRONIC", (40, 75), (0.85, 0.92), (1.4, 1.7), (0.3, 0.8), (0.02, 0.08),
        circuit=0, schedule="window",
        schedule_kwargs=dict(n_windows=(1, 1), window_dur=(2 * 3600, 8 * 3600)),
    ),
    ApplianceSpec(
        "led_lights", "ELECTRONIC", (30, 90), (0.5, 0.9), (1.5, 3.0), (0.05, 0.3), (0.20, 0.40),
        circuit=0, schedule="window",
        schedule_kwargs=dict(n_windows=(1, 1), window_dur=(3 * 3600, 6 * 3600)),
    ),
    ApplianceSpec(
        "tv", "ELECTRONIC", (40, 120), (0.5, 0.9), (2.0, 3.0), (0.1, 0.5), (0.20, 0.40),
        circuit=0, schedule="window",
        schedule_kwargs=dict(n_windows=(1, 1), window_dur=(1 * 3600, 4 * 3600)),
    ),
]

ALWAYS_ON_P_RANGE = (5.0, 30.0)
ALWAYS_ON_PF_RANGE = (0.5, 0.8)  # leading (SMPS-ish); modelled as small -Q


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #
def _pf_to_q_ratio(pf: float) -> float:
    pf = min(max(pf, 1e-3), 1.0)
    return math.tan(math.acos(pf))


def _schedule_cycle(rng, duration_s, on_range, off_range, windows=None):
    """Periodic ON/OFF duty cycle (thermostat-like). windows restricts activity."""
    out = []
    t = rng.uniform(0, off_range[1])  # random phase
    active = True
    while t < duration_s:
        dur = rng.uniform(*(on_range if active else off_range))
        t_next = min(t + dur, duration_s)
        if active and t_next > t:
            if windows is None or _in_any_window(t, windows):
                out.append((t, t_next))
        t = t_next
        active = not active
    return out


def _in_any_window(t, windows):
    return any(w0 <= t < w1 for w0, w1 in windows)


def _make_windows(rng, duration_s, n_windows, window_dur):
    n = rng.integers(n_windows[0], n_windows[1] + 1)
    windows = []
    for _ in range(n):
        dur = min(rng.uniform(*window_dur), duration_s)
        start = rng.uniform(0, max(duration_s - dur, 0.0))
        windows.append((start, start + dur))
    return windows


def _schedule_cycle_windowed(rng, duration_s, on_range, off_range, n_windows, window_dur):
    windows = _make_windows(rng, duration_s, n_windows, window_dur)
    if not windows:
        return []
    return _schedule_cycle(rng, duration_s, on_range, off_range, windows=windows)


def _schedule_sessions(rng, duration_s, n_sessions, session_dur):
    n = rng.integers(n_sessions[0], n_sessions[1] + 1)
    out = []
    for _ in range(n):
        dur = min(rng.uniform(*session_dur), duration_s)
        start = rng.uniform(0, max(duration_s - dur, 0.0))
        out.append((start, start + dur))
    out.sort()
    return out


def _schedule_burst_session(rng, duration_s, n_sessions, session_dur, burst_on, burst_off):
    """A session in which the load cycles on/off repeatedly (iron use)."""
    sessions = _schedule_sessions(rng, duration_s, n_sessions, session_dur)
    out = []
    for s0, s1 in sessions:
        t = s0
        while t < s1:
            on_dur = min(rng.uniform(*burst_on), s1 - t)
            if on_dur > 1.0:
                out.append((t, t + on_dur))
            t += on_dur
            t += rng.uniform(*burst_off)
    return out


def _schedule_standalone_bursts(rng, duration_s, n_bursts, burst_dur):
    n = rng.integers(n_bursts[0], n_bursts[1] + 1)
    out = []
    for _ in range(n):
        dur = min(rng.uniform(*burst_dur), duration_s)
        start = rng.uniform(0, max(duration_s - dur, 0.0))
        out.append((start, start + dur))
    out.sort()
    return out


def _schedule_window(rng, duration_s, n_windows, window_dur):
    return _make_windows(rng, duration_s, n_windows, window_dur)


_SCHEDULERS: dict = {
    "cycle": _schedule_cycle,
    "cycle_windowed": _schedule_cycle_windowed,
    "sessions": _schedule_sessions,
    "burst_session": _schedule_burst_session,
    "standalone_bursts": _schedule_standalone_bursts,
    "window": _schedule_window,
}


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class GTEvent:
    appliance: str
    physics_class: str
    circuit: int
    t_on: float
    t_off: float
    dP: float
    dQ: float
    r_pk: float
    t_settle_s: float
    h: float

    @property
    def dur_s(self) -> float:
        return self.t_off - self.t_on

    @property
    def phi_deg(self) -> float:
        return math.degrees(math.atan2(self.dQ, self.dP))


def _sample_instance_nominal(rng, spec: ApplianceSpec):
    """One fixed 'home profile' value per appliance instance (device-to-device
    consistency is what makes clustering possible)."""
    dP = rng.uniform(*spec.dP_range)
    pf = rng.uniform(*spec.pf_range)
    r_pk = rng.uniform(*spec.r_pk_range)
    t_settle = rng.uniform(*spec.t_settle_range)
    h = rng.uniform(*spec.h_range)
    return dict(dP=dP, pf=pf, r_pk=r_pk, t_settle=t_settle, h=h)


def _jitter(rng, x, frac):
    return x * (1.0 + rng.normal(0, frac))


def build_ground_truth(rng, duration_s) -> List[GTEvent]:
    events: List[GTEvent] = []
    for spec in APPLIANCES:
        nominal = _sample_instance_nominal(rng, spec)
        sched_fn = _SCHEDULERS[spec.schedule]
        intervals = sched_fn(rng, duration_s, **spec.schedule_kwargs)
        for (t0, t1) in intervals:
            if t1 - t0 < 0.5:
                continue
            dP = max(_jitter(rng, nominal["dP"], 0.04), 1.0)
            pf = min(max(_jitter(rng, nominal["pf"], 0.03), 0.05), 1.0)
            dQ = dP * _pf_to_q_ratio(pf)
            r_pk = max(_jitter(rng, nominal["r_pk"], 0.05), 1.0)
            t_settle = max(_jitter(rng, nominal["t_settle"], 0.10), 0.05)
            h = min(max(_jitter(rng, nominal["h"], 0.15), 0.0), 0.9)
            events.append(GTEvent(spec.name, spec.physics_class, spec.circuit,
                                   t0, t1, dP, dQ, r_pk, t_settle, h))
    events.sort(key=lambda e: e.t_on)
    return events


def _render_contribution(t_grid, dt, ev: GTEvent):
    """Returns (P, Q, Ipk_extra) contribution arrays over the whole grid
    (nonzero only within [t_on, t_off))."""
    n = len(t_grid)
    P = np.zeros(n)
    Q = np.zeros(n)
    Ipk_extra = np.zeros(n)
    i0 = int(np.searchsorted(t_grid, ev.t_on))
    i1 = int(np.searchsorted(t_grid, ev.t_off))
    i1 = max(i1, min(i0 + 1, n))
    if i0 >= n:
        return P, Q, Ipk_extra
    i1 = min(i1, n)
    rel = t_grid[i0:i1] - ev.t_on

    if ev.physics_class == "RESISTIVE":
        tau = min(max(ev.t_settle_s / 3.0, 0.02), 0.2)
        env = 1.0 - np.exp(-rel / tau)
        P[i0:i1] = ev.dP * env
        Q[i0:i1] = ev.dQ * env
        tau_inrush = tau
        surge = (ev.r_pk - 1.0) * np.exp(-rel / max(tau_inrush, 0.02))
    else:  # MOTOR / ELECTRONIC: exponential approach + inrush current surge
        # tau chosen so the envelope is essentially settled (>98%) by t_settle,
        # consistent with t_settle being defined (design 06 Sec 3.1 #5) as the
        # elapsed time to reach the settled steady state, not a time constant.
        tau = max(ev.t_settle_s / 4.0, 0.05)
        env = 1.0 - np.exp(-rel / tau)
        tau_inrush = max(ev.t_settle_s / 5.0, 0.03)
        surge = (ev.r_pk - 1.0) * np.exp(-rel / tau_inrush)
        q_extra = ev.dQ * 0.6 * surge if ev.physics_class == "MOTOR" else ev.dQ * 0.2 * surge
        P[i0:i1] = ev.dP * env
        Q[i0:i1] = ev.dQ * env + np.clip(q_extra, 0, None)

    i_rms_step = math.hypot(ev.dP, ev.dQ) / V_NOM
    ipk_baseline = math.sqrt(2.0) * i_rms_step
    Ipk_extra[i0:i1] = ipk_baseline * (ev.r_pk / math.sqrt(2.0) - 1.0) * np.exp(-rel / tau_inrush)
    return P, Q, Ipk_extra


def _ou_process(rng, n, dt, x0, mean, theta, sigma, lo, hi):
    x = np.empty(n)
    x[0] = x0
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (mean - x[i - 1]) * dt + sigma * math.sqrt(dt) * rng.normal()
        x[i] = min(max(x[i], lo), hi)
    return x


def simulate_home(duration_s: float = 6 * 3600, rate_hz: float = 1.0, afe: bool = False,
                   seed: int = 0, meas_noise_w: float = 1.5) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate one Indian home's aggregate AC power stream.

    Parameters
    ----------
    duration_s : simulated span, seconds
    rate_hz    : sample rate. Design 06 Sec 1.3 fast stream is 3.125 Hz; the
                 basic PZEM stream is 1 Hz.
    afe        : if True, populate Ipk/Pf/Ph (AFE variant, design 06 Sec 1.4);
                 otherwise they are NaN (Tier-0 PZEM has no AFE).
    seed       : RNG seed for reproducibility.

    Returns
    -------
    (stream_df, ground_truth_df)
    """
    rng = np.random.default_rng(seed)
    n = int(round(duration_s * rate_hz))
    dt = 1.0 / rate_hz
    t_grid = np.arange(n) * dt

    events = build_ground_truth(rng, duration_s)

    P = np.zeros(n)
    Q = np.zeros(n)
    Ipk_extra = np.zeros(n)
    for ev in events:
        p, q, ipk = _render_contribution(t_grid, dt, ev)
        P += p
        Q += q
        Ipk_extra += ipk

    # always-on baseline, present for the whole stream (no toggling -> no events)
    p_always = rng.uniform(*ALWAYS_ON_P_RANGE)
    pf_always = rng.uniform(*ALWAYS_ON_PF_RANGE)
    P += p_always
    Q += -p_always * _pf_to_q_ratio(pf_always)  # leading (SMPS-like)

    # sigma chosen so the OU stationary std ~6 V (gentle mains wander within
    # 200-250 V, design 06 Sec 2.2 V_norm rationale) -- large enough to
    # exercise voltage normalisation, small enough not to itself trip the
    # detector's P_th on constant-power (non-impedance) synthetic loads.
    Vrms = _ou_process(rng, n, dt, x0=230.0, mean=230.0, theta=1.0 / 1800.0, sigma=0.2,
                        lo=200.0, hi=250.0)
    f = _ou_process(rng, n, dt, x0=F_NOM, mean=F_NOM, theta=1.0 / 600.0, sigma=0.01,
                     lo=49.5, hi=50.5)

    P = P + rng.normal(0, meas_noise_w, n)
    Q = Q + rng.normal(0, meas_noise_w, n)
    S = np.sqrt(P ** 2 + Q ** 2)
    Irms = S / Vrms
    with np.errstate(divide="ignore", invalid="ignore"):
        PF = np.where(S > 1e-6, np.clip(P / np.maximum(S, 1e-6), -1.0, 1.0), 1.0)

    df = pd.DataFrame({
        "t": t_grid,
        "Vrms": Vrms,
        "Irms": Irms,
        "P": P,
        "Q": Q,
        "PF": PF,
        "f": f,
    })

    if afe:
        Ipk = math.sqrt(2.0) * Irms + Ipk_extra + rng.normal(0, 0.01, n)
        Ipk = np.clip(Ipk, 0, None)
        # harmonic split: aggregate h approximated as a power-weighted mix of
        # the per-appliance h of whichever loads are active (bounded proxy).
        h_series = _approx_aggregate_h(t_grid, events, P, p_always)
        Ph = P * h_series / (1.0 + h_series)
        Pf_fund = P - Ph
        df["Ipk"] = Ipk
        df["Pf"] = Pf_fund
        df["Ph"] = Ph
    else:
        df["Ipk"] = np.nan
        df["Pf"] = np.nan
        df["Ph"] = np.nan

    gt_rows = []
    for ev in events:
        gt_rows.append(dict(
            appliance=ev.appliance, physics_class=ev.physics_class, circuit=ev.circuit,
            t0=ev.t_on, t1=ev.t_off, dP=ev.dP, dQ=ev.dQ, phi_deg=ev.phi_deg,
            r_pk=ev.r_pk, t_settle_s=ev.t_settle_s, h=ev.h, dur_s=ev.dur_s,
        ))
    gt_df = pd.DataFrame(gt_rows).sort_values("t0").reset_index(drop=True)
    return df, gt_df


def _approx_aggregate_h(t_grid, events, P_total, p_always, h_always=0.5):
    """Power-weighted average harmonic ratio h(t) across active loads (proxy;
    real metrology derives this from the fundamental/harmonic register split,
    which this synthetic stream constructs to be self-consistent)."""
    n = len(t_grid)
    num = np.full(n, p_always * h_always)
    den = np.full(n, p_always)
    for ev in events:
        i0 = int(np.searchsorted(t_grid, ev.t_on))
        i1 = int(np.searchsorted(t_grid, ev.t_off))
        i1 = max(i1, min(i0 + 1, n))
        i1 = min(i1, n)
        if i0 >= n:
            continue
        num[i0:i1] += ev.dP * ev.h
        den[i0:i1] += ev.dP
    with np.errstate(divide="ignore", invalid="ignore"):
        h = np.where(den > 1e-6, num / np.maximum(den, 1e-6), 0.0)
    return np.clip(h, 0.0, 0.9)


if __name__ == "__main__":
    stream, gt = simulate_home(duration_s=3600, rate_hz=3.125, afe=True, seed=1)
    print(stream.head())
    print(gt.head())
    print(f"{len(gt)} ground-truth events over {stream['t'].iloc[-1]:.0f} s")
