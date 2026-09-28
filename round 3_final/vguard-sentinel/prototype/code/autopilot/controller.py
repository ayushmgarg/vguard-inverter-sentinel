"""Load-shedding controller for the V-Guard Sentinel autopilot (Engine 2).

Implements design doc 05 Sec.4 (60 s tier-shedding decision loop) and
Sec.7 / design doc 10 Sec.4 & Sec.7 (2-of-3 outage vote with debounce and
restore hysteresis). Mirrors the C API in CONTRACTS.md Sec.6
(`ap_init`/`ap_evaluate`) -- see autopilot/autopilot.c for the C99 port
that must agree with this module on the same scenario table
(tests/test_autopilot.py).

Two clocks, matching the real architecture (design 11 Sec.2 FreeRTOS task
table): outage detection is a FAST vote (debounce ~0.1-4 s) that produces
a `grid_ok` boolean; the tier-shedding decision (`evaluate`) runs every
60 s and consumes that boolean plus SoC/load/forecast inputs. In
firmware these are two functions in the `autopilot` task; here they are
`outage_step()` and `evaluate()`.

Every function is pure: it returns a NEW state object and never mutates
its arguments (project coding-style: immutability). The C port
necessarily mutates `ap_t*` in place -- that is the CONTRACTS-mandated
C function signature (`ap_evaluate(ap_t*, const ap_input_t*,
ap_output_t*)`), a normal and unavoidable embedded-firmware idiom; the
immutability discipline applies to the Python reference model.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
from typing import List, Optional, Tuple

# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class Tier(IntEnum):
    T1 = 1   # never shed
    T2 = 2   # defer
    T3 = 3   # shed


class ChState(IntEnum):
    ON = 0
    SHED = 1


class Mode(IntEnum):
    PREDICTIVE = 0
    CONSERVATIVE = 1


N_CHANNELS = 4

# --------------------------------------------------------------------------
# Config (design 05 Sec.3, Sec.4.2, Sec.7 / CONTRACTS Sec.5)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelConfig:
    tier: Tier = Tier.T1
    hw_locked_t1: bool = False   # driver-board jumper/DIP -- app cannot override


@dataclass(frozen=True)
class ApConfig:
    channels: Tuple[ChannelConfig, ChannelConfig, ChannelConfig, ChannelConfig]
    configured: bool = False   # False (or CRC-invalid, per 05 Sec.3) -> fail-safe all-T1

    # SoC hysteresis ladder (05 Sec.4.2)
    shed_t3_soc_pct: float = 40.0
    restore_t3_soc_pct: float = 55.0
    defer_t2_soc_pct: float = 55.0
    restore_t2_soc_pct: float = 70.0

    # dwell (05 Sec.4.2)
    dwell_on_s: float = 300.0
    dwell_off_s: float = 180.0

    # override (05 Sec.4.4)
    override_timeout_default_s: float = 1800.0
    override_timeout_max_s: float = 14400.0

    # forecast-disagreement fallback (05 Sec.4.2 table)
    forecast_disagreement_ratio: float = 1.3
    forecast_disagreement_window_s: float = 300.0

    # essentials-at-risk hard floor (05 Sec.4.3)
    essentials_risk_margin: float = 1.2

    # Peukert / E_usable (05 Sec.4.1)
    peukert_n: float = 1.25          # flooded lead-acid default (1.2-1.4)
    c_rated_ah: float = 150.0
    v_nominal: float = 12.0
    t_rated_h: float = 20.0          # C20 rating

    charger_commandable: bool = False   # embedded SKU only (05 Sec.2.3)

    # pre-charge / pre-emption (05 Sec.2.3)
    pre_outage_prob_threshold: float = 0.55
    pre_outage_conf_threshold: float = 0.5
    pre_outage_soc_raise_pp: float = 15.0
    pre_outage_threshold_raise_pp: float = 10.0
    pre_outage_window_s: float = 3.0 * 3600.0   # matches the h=3 forecast horizon

    # outage detection (05 Sec.7 / 10 Sec.7)
    mains_sag_pu: float = 0.10
    mains_restore_pu: float = 0.90
    s1_debounce_s: float = 1.5        # 1-2 s
    s2_debounce_s: float = 0.15       # 100-200 ms
    s3_debounce_s: float = 1.5        # 1-2 s
    s1_alone_debounce_s: float = 4.0  # longer window, s1-alone (retrofit)
    restore_debounce_s: float = 20.0  # 10-30 s
    batt_idle_discharge_a: float = 1.0

    def effective_tier(self, i: int) -> Tier:
        ch = self.channels[i]
        if ch.hw_locked_t1:
            return Tier.T1
        if not self.configured:
            return Tier.T1
        return ch.tier


def default_config(**overrides) -> ApConfig:
    """All-T1 fail-safe default config (05 Sec.3: 'until configured, all
    channels = T1')."""
    base = ApConfig(channels=(ChannelConfig(), ChannelConfig(), ChannelConfig(), ChannelConfig()), configured=False)
    return replace(base, **overrides) if overrides else base


# --------------------------------------------------------------------------
# Outage detector state (design 05 Sec.7 / 10 Sec.7)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OutageDetState:
    s1_since: Optional[float] = None
    s2_since: Optional[float] = None
    s3_since: Optional[float] = None
    restore_since: Optional[float] = None
    active: bool = False


@dataclass(frozen=True)
class OutageInput:
    t: float                                  # monotonic seconds
    mains_rms_pu: float
    inverter_mode_pin: Optional[str]          # "BACKUP" / "NORMAL" / None (retrofit, unavailable)
    batt_discharge_a: float


def outage_step(state: OutageDetState, inp: OutageInput, config: ApConfig) -> Tuple[OutageDetState, bool]:
    """One tick of the 2-of-3 outage vote with debounce and restore
    hysteresis (design 05 Sec.7):
        s1 = mains under-voltage sustained >= N1 (1-2 s)
        s2 = inverter_mode_pin == BACKUP (embedded SKU only), debounced 100-200 ms
        s3 = battery net-discharge > idle threshold, debounced 1-2 s
        outage = (s1 AND (s2 OR s3)) OR (s1 alone for >= N2, longer debounce)
        restore = mains > 0.9 pu sustained 10-30 s
    Call at a FAST rate (sub-second) independent of the 60 s evaluate()
    loop. Returns (new_state, outage_active).
    """
    t = inp.t

    s1_now = inp.mains_rms_pu < config.mains_sag_pu
    s1_since = state.s1_since if s1_now else None
    if s1_now and s1_since is None:
        s1_since = t
    s1 = s1_now and s1_since is not None and (t - s1_since) >= config.s1_debounce_s
    s1_alone = s1_now and s1_since is not None and (t - s1_since) >= config.s1_alone_debounce_s

    s2_now = inp.inverter_mode_pin == "BACKUP"
    s2_since = state.s2_since if s2_now else None
    if s2_now and s2_since is None:
        s2_since = t
    s2 = s2_now and s2_since is not None and (t - s2_since) >= config.s2_debounce_s

    s3_now = inp.batt_discharge_a > config.batt_idle_discharge_a
    s3_since = state.s3_since if s3_now else None
    if s3_now and s3_since is None:
        s3_since = t
    s3 = s3_now and s3_since is not None and (t - s3_since) >= config.s3_debounce_s

    votes = int(s1) + int(s2) + int(s3)
    declare = (votes >= 2) or s1_alone

    if state.active:
        if inp.mains_rms_pu > config.mains_restore_pu:
            restore_since = state.restore_since if state.restore_since is not None else t
            if (t - restore_since) >= config.restore_debounce_s:
                new_active = False
                restore_since = None
            else:
                new_active = True
        else:
            new_active = True
            restore_since = None
    else:
        new_active = declare
        restore_since = None

    new_state = OutageDetState(
        s1_since=s1_since, s2_since=s2_since, s3_since=s3_since,
        restore_since=restore_since, active=new_active,
    )
    return new_state, new_active


def init_outage_state() -> OutageDetState:
    return OutageDetState()


# --------------------------------------------------------------------------
# Tier-shedding controller state / I/O (design 05 Sec.4)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelState:
    state: ChState = ChState.ON
    last_transition_s: float = 0.0


@dataclass(frozen=True)
class OverrideState:
    channel: Optional[int] = None
    expires_at_s: Optional[float] = None


@dataclass(frozen=True)
class ApState:
    t: float = 0.0
    channels: Tuple[ChannelState, ChannelState, ChannelState, ChannelState] = (
        ChannelState(), ChannelState(), ChannelState(), ChannelState(),
    )
    t3_target: ChState = ChState.ON
    t2_target: ChState = ChState.ON
    mode: Mode = Mode.PREDICTIVE
    disagreement_since: Optional[float] = None
    override: OverrideState = OverrideState()
    pre_outage_boost_until: Optional[float] = None


def init_state(t0: float = 0.0) -> ApState:
    ch = ChannelState(state=ChState.ON, last_transition_s=t0)
    return ApState(t=t0, channels=(ch, ch, ch, ch), t3_target=ChState.ON, t2_target=ChState.ON,
                   mode=Mode.PREDICTIVE, disagreement_since=None, override=OverrideState(), pre_outage_boost_until=None)


@dataclass(frozen=True)
class ApInput:
    t: float                                   # monotonic seconds since boot
    soc: float                                  # 0..1
    soh: float                                  # 0..1
    grid_ok: bool                               # mains present (from outage_step, or direct)
    load_w: float                               # current AC load, W
    hour: int                                   # 0-23, local hour-of-day
    dow: int                                    # 0-6, day-of-week
    temp_c: float = 25.0                        # battery temperature
    i_forecast_a: float = 1.0                   # forecast T1(+T2) discharge current, A
    fcst_t1_wh: float = 0.0                     # habit.forecast_total_demand_wh(...) x tier-fraction
    outage_prob_h3: Optional[float] = None      # habit.outage_forecast(...).prob
    outage_conf: Optional[float] = None         # habit.outage_forecast(...).confidence
    actual_decline_pct_per_min: Optional[float] = None
    forecast_decline_pct_per_min: Optional[float] = None
    override_request: Optional[int] = None      # channel id 0-3 the app wants kept ON
    override_timeout_s: Optional[float] = None
    override_clear: bool = False


@dataclass(frozen=True)
class ApOutput:
    channel_state: Tuple[ChState, ChState, ChState, ChState]
    reasons: Tuple[str, ...]
    est_backup_min: Optional[float]
    mode: Mode
    e_usable_wh: float
    outage_active: bool                # == not grid_ok, echoed for convenience
    pre_outage_active: bool
    charger_command_active: bool       # advisory-vs-active per 05 Sec.2.3


# --------------------------------------------------------------------------
# Peukert-corrected usable energy (design 05 Sec.4.1)
# --------------------------------------------------------------------------


def _f_temp(temp_c: float) -> float:
    """Approximate lead-acid capacity temperature derating (illustrative,
    NOT sourced from a manufacturer curve for this specific chemistry --
    see autopilot/README.md honest limits). ~100% at 25 C, ~0.8%/C below
    25 C, clipped to a sane range."""
    f = 1.0 + 0.008 * (temp_c - 25.0)
    return max(0.5, min(1.05, f))


def peukert_capacity_ah(c_rated_ah: float, i_forecast_a: float, temp_c: float, n: float, t_rated_h: float) -> float:
    """design 05 Sec.4.1:
    C_usable(I,T) = C_rated * (C_rated/(I_fcst*t_rated))^(n-1) * f_temp(T)
    """
    i = max(i_forecast_a, 1e-6)
    ratio = c_rated_ah / (i * t_rated_h)
    c_usable = c_rated_ah * (ratio ** (n - 1.0)) * _f_temp(temp_c)
    return max(c_usable, 0.0)


def usable_energy_wh(soh: float, soc: float, config: ApConfig, i_forecast_a: float, temp_c: float) -> float:
    c_usable = peukert_capacity_ah(config.c_rated_ah, i_forecast_a, temp_c, config.peukert_n, config.t_rated_h)
    return soh * soc * c_usable * config.v_nominal


# --------------------------------------------------------------------------
# Tier-shedding evaluate() -- design 05 Sec.4.3 pseudocode
# --------------------------------------------------------------------------


def _threshold(base_pct: float, boost_active: bool, raise_pp: float) -> float:
    return base_pct + (raise_pp if boost_active else 0.0)


def evaluate(state: ApState, inp: ApInput, config: ApConfig) -> Tuple[ApState, ApOutput]:
    """One 60 s re-evaluation cycle (design 05 Sec.4.3). Pure: returns a
    new ApState and an ApOutput; `state`/`inp`/`config` are untouched."""
    t = inp.t
    reasons: List[str] = []

    # -- 1. forecast-disagreement escalation -> CONSERVATIVE (05 Sec.4.2 table)
    disagree_now = False
    if inp.actual_decline_pct_per_min is not None and inp.forecast_decline_pct_per_min is not None:
        fr = inp.forecast_decline_pct_per_min
        if fr > 0:
            disagree_now = (inp.actual_decline_pct_per_min > config.forecast_disagreement_ratio * fr)
    disagreement_since = state.disagreement_since
    if disagree_now:
        if disagreement_since is None:
            disagreement_since = t
    else:
        disagreement_since = None
    if disagreement_since is not None and (t - disagreement_since) >= config.forecast_disagreement_window_s:
        mode = Mode.CONSERVATIVE
        reasons.append("forecast disagreement >1.3x actual decline for >=5min -> CONSERVATIVE")
    else:
        mode = Mode.PREDICTIVE

    # -- 2. E_usable with Peukert correction (05 Sec.4.1)
    e_usable_wh = usable_energy_wh(inp.soh, inp.soc, config, inp.i_forecast_a, inp.temp_c)

    # -- 3. essentials-at-risk hard floor (always active, 05 Sec.4.3)
    hard_floor_shed_t3 = False
    if (not inp.grid_ok) and e_usable_wh < config.essentials_risk_margin * inp.fcst_t1_wh:
        hard_floor_shed_t3 = True
        reasons.append("hard floor: T1 endurance at risk (E_usable=%.1fWh < %.2fx fcst=%.1fWh)" % (
            e_usable_wh, config.essentials_risk_margin, inp.fcst_t1_wh))

    # -- 4. predictive pre-emption window (05 Sec.2.3) -- computed before the
    #       ladder so its threshold tightening applies this same cycle.
    pre_outage_boost_until = state.pre_outage_boost_until
    if (mode == Mode.PREDICTIVE and inp.grid_ok and inp.outage_prob_h3 is not None
            and inp.outage_prob_h3 > config.pre_outage_prob_threshold
            and inp.outage_conf is not None and inp.outage_conf > config.pre_outage_conf_threshold):
        pre_outage_boost_until = t + config.pre_outage_window_s
        reasons.append("pre-charge window: SoC target +%.0fpp, shed thresholds +%.0fpp (P=%.2f conf=%.2f)" % (
            config.pre_outage_soc_raise_pp, config.pre_outage_threshold_raise_pp, inp.outage_prob_h3, inp.outage_conf))
    boost_active = pre_outage_boost_until is not None and t < pre_outage_boost_until
    if pre_outage_boost_until is not None and not boost_active:
        pre_outage_boost_until = None

    charger_command_active = bool(boost_active and config.charger_commandable and inp.grid_ok)
    if boost_active:
        if config.charger_commandable:
            reasons.append("charger commanded to bulk/absorption now (pre-charge, embedded SKU)")
        else:
            reasons.append("advisory: scheduled-outage pattern likely soon -- limit heavy loads now (retrofit SKU)")

    # -- 5. SoC hysteresis ladder (05 Sec.4.2), thresholds tightened +10pp during a pre-charge window
    soc_pct = inp.soc * 100.0
    shed_t3_th = _threshold(config.shed_t3_soc_pct, boost_active, config.pre_outage_threshold_raise_pp)
    restore_t3_th = _threshold(config.restore_t3_soc_pct, boost_active, config.pre_outage_threshold_raise_pp)
    defer_t2_th = _threshold(config.defer_t2_soc_pct, boost_active, config.pre_outage_threshold_raise_pp)
    restore_t2_th = _threshold(config.restore_t2_soc_pct, boost_active, config.pre_outage_threshold_raise_pp)

    t3_target = state.t3_target
    ladder_shed_t3 = soc_pct <= shed_t3_th
    ladder_restore_t3 = soc_pct >= restore_t3_th
    if ladder_shed_t3:
        t3_target = ChState.SHED
    elif ladder_restore_t3:
        t3_target = ChState.ON

    if t3_target == ChState.SHED and state.t3_target != ChState.SHED and ladder_shed_t3:
        reasons.append("T3 shed target: SoC %.1f%% <= %.1f%%" % (soc_pct, shed_t3_th))
    if t3_target == ChState.ON and state.t3_target != ChState.ON:
        reasons.append("T3 restore target: SoC %.1f%% >= %.1f%%" % (soc_pct, restore_t3_th))

    if hard_floor_shed_t3:
        t3_target = ChState.SHED

    t2_target = state.t2_target
    if soc_pct <= defer_t2_th:
        t2_target = ChState.SHED
    elif soc_pct >= restore_t2_th:
        t2_target = ChState.ON

    if t2_target == ChState.SHED and state.t2_target != ChState.SHED:
        reasons.append("T2 defer target: SoC %.1f%% <= %.1f%%" % (soc_pct, defer_t2_th))
    if t2_target == ChState.ON and state.t2_target != ChState.ON:
        reasons.append("T2 restore target: SoC %.1f%% >= %.1f%%" % (soc_pct, restore_t2_th))

    # -- 6. user override (05 Sec.4.4): SoC-ladder tiers only, cannot beat the hard floor, 30 min timeout
    override = state.override
    if inp.override_request is not None:
        timeout = inp.override_timeout_s if inp.override_timeout_s is not None else config.override_timeout_default_s
        timeout = max(0.0, min(timeout, config.override_timeout_max_s))
        override = OverrideState(channel=inp.override_request, expires_at_s=t + timeout)
        reasons.append("user override armed: channel %d for %.0fs" % (inp.override_request, timeout))
    if inp.override_clear:
        if override.channel is not None:
            reasons.append("user override cleared: channel %d" % override.channel)
        override = OverrideState(None, None)
    if override.channel is not None and override.expires_at_s is not None and t >= override.expires_at_s:
        reasons.append("user override timed out: channel %d" % override.channel)
        override = OverrideState(None, None)

    # -- 7. per-channel desired state + override + dwell-gated actuation
    new_channels: List[ChannelState] = []
    for i in range(N_CHANNELS):
        tier = config.effective_tier(i)
        if tier == Tier.T1:
            desired = ChState.ON
        elif tier == Tier.T2:
            desired = t2_target
        else:
            desired = t3_target

        overridden = False
        if (override.channel == i and override.expires_at_s is not None and desired == ChState.SHED
                and not (tier == Tier.T3 and hard_floor_shed_t3)):
            desired = ChState.ON
            overridden = True
            reasons.append("channel %d kept ON by user override" % i)

        ch = state.channels[i]
        elapsed = t - ch.last_transition_s
        if desired != ch.state:
            min_dwell = config.dwell_on_s if ch.state == ChState.ON else config.dwell_off_s
            if elapsed >= min_dwell:
                new_channels.append(ChannelState(state=desired, last_transition_s=t))
                reasons.append("channel %d (%s) -> %s" % (i, tier.name, desired.name))
            else:
                new_channels.append(ch)  # requeued: dwell not satisfied yet
                if not overridden:
                    reasons.append("channel %d (%s) desired %s deferred: dwell %.0f/%.0fs" % (
                        i, tier.name, desired.name, elapsed, min_dwell))
        else:
            new_channels.append(ch)

    # -- invariant: T1 is never shed or deferred (05 Sec.4.3 assert)
    for i in range(N_CHANNELS):
        if config.effective_tier(i) == Tier.T1:
            assert new_channels[i].state == ChState.ON, "invariant violated: T1 channel %d shed" % i

    # -- est_backup_min: runway at the CURRENT metered load if grid drops now
    est_backup_min: Optional[float] = None
    if inp.load_w > 1e-6:
        est_backup_min = 60.0 * e_usable_wh / inp.load_w

    new_state = ApState(
        t=t, channels=tuple(new_channels), t3_target=t3_target, t2_target=t2_target,
        mode=mode, disagreement_since=disagreement_since, override=override,
        pre_outage_boost_until=pre_outage_boost_until,
    )
    output = ApOutput(
        channel_state=tuple(c.state for c in new_channels),
        reasons=tuple(reasons),
        est_backup_min=est_backup_min,
        mode=mode,
        e_usable_wh=e_usable_wh,
        outage_active=not inp.grid_ok,
        pre_outage_active=boost_active,
        charger_command_active=charger_command_active,
    )
    return new_state, output
