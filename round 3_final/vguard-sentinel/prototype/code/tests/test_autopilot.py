"""pytest suite for the V-Guard Sentinel Engine-2 autopilot (module D).

Implements design doc 11 (Validation-Protocol) Sec.1.3 as scripted,
host-only scenarios (no hardware-in-the-loop bench here -- see
autopilot/README.md "Honest limits"):
    (a) T1 never de-energised while E_avail > 0
    (b) T3 shed exactly at SoC <= 40% and restored at >= 55% (+-1%)
    (c) zero dwell violations (compressor channel switched < 3 min after
        last switch)
    (d) zero chatter (> 2 transitions/channel/10 min)
    - override cannot defeat the hard floor and always times out
    - unconfigured -> nothing shed
    - hardware lock respected
    - outage declared on 2-of-3 within 2 s, not on a 200 ms sag
    - restore only after > 0.9 pu for 10-30 s
    - CONSERVATIVE fallback on forecast disagreement
    - the C port (autopilot.c) agrees with the Python reference
      (controller.py) on the same scenario table (subprocess; skipped if
      gcc is not on PATH)

Run: `pytest -q` from documentation/prototype/code/ (CONTRACTS.md Sec.0).
"""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys

import pytest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(_THIS_DIR)
_AUTOPILOT_DIR = os.path.join(_CODE_ROOT, "autopilot")
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from autopilot import habit  # noqa: E402
from autopilot import controller as ctrl  # noqa: E402


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _config(**overrides) -> ctrl.ApConfig:
    channels = overrides.pop("channels", (
        ctrl.ChannelConfig(ctrl.Tier.T1),
        ctrl.ChannelConfig(ctrl.Tier.T2),
        ctrl.ChannelConfig(ctrl.Tier.T3),
        ctrl.ChannelConfig(ctrl.Tier.T3),
    ))
    overrides.setdefault("configured", True)
    return ctrl.default_config(channels=channels, **overrides)


def _run(config: ctrl.ApConfig, steps):
    """steps: list of dicts of ApInput kwargs (t required). Returns list of
    (ApState, ApOutput) pairs, one per step. Does not mutate `steps`."""
    state = ctrl.init_state(t0=steps[0]["t"] if steps else 0.0)
    results = []
    for kw in steps:
        kw = dict(kw)  # never mutate the caller's scenario dicts
        inp = ctrl.ApInput(soc=kw.pop("soc", 0.8), soh=kw.pop("soh", 0.9),
                            grid_ok=kw.pop("grid_ok", True), load_w=kw.pop("load_w", 100.0),
                            hour=kw.pop("hour", 12), dow=kw.pop("dow", 2), **kw)
        state, out = ctrl.evaluate(state, inp, config)
        results.append((state, out))
    return results


def _drain_recover_steps(start_soc, end_soc, recover_soc, t0=0.0, **common):
    """A scripted battery-drain-then-recover arc, long enough to clear
    both the ON (300 s) and OFF (180 s) dwell windows."""
    steps = []
    t = t0
    for k in range(8):
        frac = k / 7.0
        soc = start_soc + (end_soc - start_soc) * frac
        steps.append(dict(t=t, soc=soc, **common))
        t += 60.0
    for _ in range(4):
        steps.append(dict(t=t, soc=end_soc, **common))
        t += 90.0
    for k in range(6):
        frac = k / 5.0
        soc = end_soc + (recover_soc - end_soc) * frac
        steps.append(dict(t=t, soc=soc, **common))
        t += 60.0
    for _ in range(3):
        steps.append(dict(t=t, soc=recover_soc, **common))
        t += 90.0
    return steps


def _transitions(results, channel):
    """[(t, from_state, to_state), ...] for one channel across a run."""
    out = []
    prev = ctrl.ChState.ON
    for state, output in results:
        cur = output.channel_state[channel]
        if cur != prev:
            out.append((state.t, prev, cur))
            prev = cur
    return out


def _assert_no_chatter(results, channel, window_s=600.0, max_transitions=2):
    trans = _transitions(results, channel)
    times = [t for t, _, _ in trans]
    for i, ti in enumerate(times):
        count = sum(1 for tj in times if ti <= tj < ti + window_s)
        assert count <= max_transitions, "chatter on channel %d: %d transitions within %ds starting at t=%s" % (
            channel, count, window_s, ti)


# --------------------------------------------------------------------------
# (a) T1 never shed, (b) T3 exact 40/55 ladder, (c) no dwell violation,
# (d) no chatter -- scripted drain/recover arcs, parametrized
# --------------------------------------------------------------------------

@pytest.mark.parametrize("start_pct", [90, 85, 80, 75, 70, 65, 60, 58, 56, 53])
def test_ladder_drain_recover(start_pct):
    cfg = _config()
    steps = _drain_recover_steps(start_pct / 100.0, 0.35, 0.60, grid_ok=True, fcst_t1_wh=5.0, i_forecast_a=3.0)
    results = _run(cfg, steps)

    # (a) T1 (channel 0) never shed
    for _, out in results:
        assert out.channel_state[0] == ctrl.ChState.ON

    # (b) T3 (channels 2, 3) shed only at <=40%, restore only at >=55%
    for ch in (2, 3):
        prev = ctrl.ChState.ON
        for (state, out), step_kw in zip(results, steps):
            cur = out.channel_state[ch]
            if cur != prev:
                soc_pct = step_kw["soc"] * 100.0
                if cur == ctrl.ChState.SHED:
                    assert soc_pct <= cfg.shed_t3_soc_pct + 0.5, "T3 shed above threshold: soc=%.1f" % soc_pct
                else:
                    assert soc_pct >= cfg.restore_t3_soc_pct - 0.5, "T3 restored below threshold: soc=%.1f" % soc_pct
                prev = cur

    # (d) no chatter on any channel
    for ch in range(4):
        _assert_no_chatter(results, ch)


@pytest.mark.parametrize("noisy_socs", [
    [0.42, 0.39, 0.42, 0.39, 0.42, 0.39, 0.42, 0.39],
    [0.41, 0.40, 0.41, 0.40, 0.41, 0.40, 0.41, 0.40],
    [0.56, 0.54, 0.56, 0.54, 0.56, 0.54, 0.56, 0.54],
])
def test_no_chatter_under_soc_noise_at_threshold(noisy_socs):
    """SoC oscillating right at a shed/restore threshold must not cause
    excess transitions: dwell + hysteresis together must hold it down."""
    cfg = _config()
    t = 0.0
    steps = []
    for soc in noisy_socs:
        steps.append(dict(t=t, soc=soc, grid_ok=True, fcst_t1_wh=5.0, i_forecast_a=3.0))
        t += 60.0
    results = _run(cfg, steps)
    for ch in range(4):
        _assert_no_chatter(results, ch)


# --------------------------------------------------------------------------
# Dwell: explicit gap bookkeeping
# --------------------------------------------------------------------------

@pytest.mark.parametrize("gap_s,should_transition", [
    (299.0, False),
    (300.0, True),
    (301.0, True),
])
def test_dwell_on_boundary(gap_s, should_transition):
    """A T3 channel just shed cannot restore before dwell_off_s; a channel
    ON cannot shed before dwell_on_s. Here: test the ON->SHED boundary."""
    cfg = _config()
    state = ctrl.init_state(t0=0.0)
    inp0 = ctrl.ApInput(t=0.0, soc=0.90, soh=0.9, grid_ok=True, load_w=100.0, hour=12, dow=2, fcst_t1_wh=5.0, i_forecast_a=3.0)
    state, _ = ctrl.evaluate(state, inp0, cfg)
    inp1 = ctrl.ApInput(t=gap_s, soc=0.30, soh=0.9, grid_ok=True, load_w=100.0, hour=12, dow=2, fcst_t1_wh=5.0, i_forecast_a=3.0)
    _, out1 = ctrl.evaluate(state, inp1, cfg)
    shed = out1.channel_state[2] == ctrl.ChState.SHED
    assert shed == should_transition


@pytest.mark.parametrize("gap_s,should_transition", [
    (179.0, False),
    (180.0, True),
    (181.0, True),
])
def test_dwell_off_boundary(gap_s, should_transition):
    """Start from a channel already SHED (last transition at t=0) and test
    whether a restore attempt at t=gap_s clears the OFF dwell (180 s)."""
    cfg = _config()
    from dataclasses import replace as _replace
    state = ctrl.init_state(t0=0.0)
    shed_ch = ctrl.ChannelState(state=ctrl.ChState.SHED, last_transition_s=0.0)
    state = _replace(state, channels=(state.channels[0], state.channels[1], shed_ch, state.channels[3]),
                      t3_target=ctrl.ChState.SHED)
    inp = ctrl.ApInput(t=gap_s, soc=0.90, soh=0.9, grid_ok=True, load_w=100.0, hour=12, dow=2, fcst_t1_wh=5.0, i_forecast_a=3.0)
    _, out = ctrl.evaluate(state, inp, cfg)
    restored = out.channel_state[2] == ctrl.ChState.ON
    assert restored == should_transition


def test_dwell_on_boundary_from_boot_uses_boot_time():
    """init_state(t0) seeds last_transition_s=t0, so the very first shed
    decision is still dwell-gated against boot time, not un-gated."""
    cfg = _config()
    state = ctrl.init_state(t0=0.0)
    inp = ctrl.ApInput(t=100.0, soc=0.10, soh=0.9, grid_ok=True, load_w=100.0, hour=12, dow=2, fcst_t1_wh=5.0, i_forecast_a=3.0)
    _, out = ctrl.evaluate(state, inp, cfg)
    assert out.channel_state[2] == ctrl.ChState.ON  # 100s < 300s dwell_on -> blocked


# --------------------------------------------------------------------------
# Override cannot defeat the hard floor; override times out
# --------------------------------------------------------------------------

def test_override_defeats_soc_ladder_shed():
    cfg = _config()
    state = ctrl.init_state(t0=0.0)
    state = ctrl_replace_all_channels_on(state, t=-1000.0)
    inp = ctrl.ApInput(t=5000.0, soc=0.30, soh=0.9, grid_ok=True, load_w=100.0, hour=12, dow=1,
                        fcst_t1_wh=5.0, i_forecast_a=3.0, override_request=2)
    state, out = ctrl.evaluate(state, inp, cfg)
    assert out.channel_state[2] == ctrl.ChState.ON  # kept on by override
    assert out.channel_state[3] == ctrl.ChState.SHED  # not overridden -> sheds normally


def test_override_cannot_defeat_hard_floor():
    cfg = _config()
    state = ctrl.init_state(t0=0.0)
    state = ctrl_replace_all_channels_on(state, t=-1000.0)
    # grid out + tiny E_usable vs a huge forecast -> hard floor demands T3 shed
    inp = ctrl.ApInput(t=5000.0, soc=0.90, soh=0.5, grid_ok=False, load_w=500.0, hour=20, dow=3,
                        fcst_t1_wh=2000.0, i_forecast_a=40.0, override_request=2)
    state, out = ctrl.evaluate(state, inp, cfg)
    assert out.channel_state[2] == ctrl.ChState.SHED  # hard floor wins despite override
    assert any("hard floor" in r for r in out.reasons)


@pytest.mark.parametrize("timeout_s,elapsed_s,still_active", [
    (1800.0, 1799.0, True),
    (1800.0, 1800.0, False),
    (600.0, 601.0, False),
])
def test_override_times_out(timeout_s, elapsed_s, still_active):
    cfg = _config()
    state = ctrl.init_state(t0=0.0)
    state = ctrl_replace_all_channels_on(state, t=-1000.0)
    inp0 = ctrl.ApInput(t=0.0, soc=0.30, soh=0.9, grid_ok=True, load_w=100.0, hour=12, dow=1,
                         fcst_t1_wh=5.0, i_forecast_a=3.0, override_request=2, override_timeout_s=timeout_s)
    state, out0 = ctrl.evaluate(state, inp0, cfg)
    assert out0.channel_state[2] == ctrl.ChState.ON
    inp1 = ctrl.ApInput(t=elapsed_s, soc=0.30, soh=0.9, grid_ok=True, load_w=100.0, hour=12, dow=1,
                         fcst_t1_wh=5.0, i_forecast_a=3.0)
    state, out1 = ctrl.evaluate(state, inp1, cfg)
    is_on = out1.channel_state[2] == ctrl.ChState.ON
    assert is_on == still_active


def ctrl_replace_all_channels_on(state, t):
    from dataclasses import replace as _replace
    ch = ctrl.ChannelState(state=ctrl.ChState.ON, last_transition_s=t)
    return _replace(state, channels=(ch, ch, ch, ch))


# --------------------------------------------------------------------------
# Unconfigured -> nothing shed; hardware lock respected
# --------------------------------------------------------------------------

@pytest.mark.parametrize("soc", [0.50, 0.30, 0.10, 0.02])
def test_unconfigured_never_sheds(soc):
    cfg = _config(configured=False)
    state = ctrl.init_state(t0=0.0)
    inp = ctrl.ApInput(t=1000.0, soc=soc, soh=0.9, grid_ok=False, load_w=500.0, hour=20, dow=3,
                        fcst_t1_wh=2000.0, i_forecast_a=40.0)
    _, out = ctrl.evaluate(state, inp, cfg)
    assert all(s == ctrl.ChState.ON for s in out.channel_state)


@pytest.mark.parametrize("locked_channel", [2, 3])
def test_hardware_lock_forces_t1(locked_channel):
    channels = [ctrl.ChannelConfig(ctrl.Tier.T1), ctrl.ChannelConfig(ctrl.Tier.T2),
                ctrl.ChannelConfig(ctrl.Tier.T3), ctrl.ChannelConfig(ctrl.Tier.T3)]
    channels[locked_channel] = ctrl.ChannelConfig(ctrl.Tier.T3, hw_locked_t1=True)
    cfg = _config(channels=tuple(channels))
    state = ctrl.init_state(t0=0.0)
    inp = ctrl.ApInput(t=1000.0, soc=0.05, soh=0.9, grid_ok=True, load_w=100.0, hour=12, dow=1,
                        fcst_t1_wh=5.0, i_forecast_a=3.0)
    _, out = ctrl.evaluate(state, inp, cfg)
    assert out.channel_state[locked_channel] == ctrl.ChState.ON  # hw lock forces T1, never shed


def test_hardware_lock_survives_app_attempting_t3_config():
    """Even though the channel is CONFIGURED T3, the hw jumper wins --
    'the app cannot override' (05 Sec.3)."""
    channels = (ctrl.ChannelConfig(ctrl.Tier.T1), ctrl.ChannelConfig(ctrl.Tier.T2),
                ctrl.ChannelConfig(ctrl.Tier.T3, hw_locked_t1=True), ctrl.ChannelConfig(ctrl.Tier.T3))
    cfg = _config(channels=channels)
    assert cfg.effective_tier(2) == ctrl.Tier.T1
    assert cfg.effective_tier(3) == ctrl.Tier.T3


# --------------------------------------------------------------------------
# Outage detection: 2-of-3 vote, debounce, restore hysteresis
# --------------------------------------------------------------------------

def _sag_run(mains_pu, duration_s, dt_s, inverter_mode=None, batt_a=0.0, config=None):
    cfg = config or _config()
    st = ctrl.init_outage_state()
    t = 0.0
    active = False
    while t < duration_s:
        t += dt_s
        st, active = ctrl.outage_step(st, ctrl.OutageInput(t=t, mains_rms_pu=mains_pu,
                                                             inverter_mode_pin=inverter_mode,
                                                             batt_discharge_a=batt_a), cfg)
    return st, active


@pytest.mark.parametrize("duration_s", [0.05, 0.1, 0.2])
def test_no_outage_declared_on_short_sag(duration_s):
    """A 200 ms sag (or shorter) must NOT declare an outage."""
    st, active = _sag_run(mains_pu=0.02, duration_s=duration_s, dt_s=0.02, inverter_mode="BACKUP", batt_a=5.0)
    assert active is False


@pytest.mark.parametrize("inverter_mode,batt_a", [("BACKUP", 5.0), (None, 5.0), ("BACKUP", 0.0)])
def test_outage_declared_within_2s_two_of_three(inverter_mode, batt_a):
    """s1 (mains sag) plus one of s2/s3 corroborating -> declare within 2 s."""
    cfg = _config()
    st = ctrl.init_outage_state()
    t = 0.0
    declared_at = None
    while t <= 2.0:
        t += 0.05
        st, active = ctrl.outage_step(st, ctrl.OutageInput(t=t, mains_rms_pu=0.02,
                                                             inverter_mode_pin=inverter_mode,
                                                             batt_discharge_a=batt_a), cfg)
        if active and declared_at is None:
            declared_at = t
    assert declared_at is not None
    assert declared_at <= 2.0 + 1e-6


def test_outage_declared_s1_alone_longer_window_retrofit():
    """Retrofit SKU: no inverter pin, low idle discharge -> s1-alone must
    still declare, just with a longer debounce than the 2-of-3 case."""
    cfg = _config()
    st = ctrl.init_outage_state()
    t = 0.0
    declared_at = None
    while t <= cfg.s1_alone_debounce_s + 1.0:
        t += 0.05
        st, active = ctrl.outage_step(st, ctrl.OutageInput(t=t, mains_rms_pu=0.02,
                                                             inverter_mode_pin=None, batt_discharge_a=0.0), cfg)
        if active and declared_at is None:
            declared_at = t
    assert declared_at is not None
    assert declared_at >= cfg.s1_debounce_s  # longer than the 2-of-3 debounce


def test_no_outage_declared_single_weak_sensor_short_of_alone_window():
    cfg = _config()
    st, active = _sag_run(mains_pu=0.02, duration_s=cfg.s1_alone_debounce_s - 0.5, dt_s=0.05,
                           inverter_mode=None, batt_a=0.0, config=cfg)
    assert active is False


@pytest.mark.parametrize("restore_hold_s,should_restore", [(9.0, False), (21.0, True), (30.0, True)])
def test_restore_hysteresis_10_to_30s(restore_hold_s, should_restore):
    cfg = _config()
    st = ctrl.init_outage_state()
    t = 0.0
    # first declare a real outage
    while t <= 3.0:
        t += 0.05
        st, active = ctrl.outage_step(st, ctrl.OutageInput(t=t, mains_rms_pu=0.02, inverter_mode_pin="BACKUP", batt_discharge_a=5.0), cfg)
    assert active is True
    # now mains recovers; hold for restore_hold_s
    t_recover_start = t
    while t <= t_recover_start + restore_hold_s:
        t += 0.05
        st, active = ctrl.outage_step(st, ctrl.OutageInput(t=t, mains_rms_pu=0.95, inverter_mode_pin="NORMAL", batt_discharge_a=0.2), cfg)
    assert (active is False) == should_restore


def test_restore_resets_if_mains_dips_again_mid_debounce():
    cfg = _config()
    st = ctrl.init_outage_state()
    t = 0.0
    while t <= 3.0:
        t += 0.05
        st, active = ctrl.outage_step(st, ctrl.OutageInput(t=t, mains_rms_pu=0.02, inverter_mode_pin="BACKUP", batt_discharge_a=5.0), cfg)
    assert active is True
    # mains looks restored for 15s (not yet enough) then dips again
    for _ in range(int(15.0 / 0.05)):
        t += 0.05
        st, active = ctrl.outage_step(st, ctrl.OutageInput(t=t, mains_rms_pu=0.95, inverter_mode_pin="NORMAL", batt_discharge_a=0.2), cfg)
    assert active is True  # not yet 20s+ of restore
    t += 0.05
    st, active = ctrl.outage_step(st, ctrl.OutageInput(t=t, mains_rms_pu=0.5, inverter_mode_pin="NORMAL", batt_discharge_a=3.0), cfg)
    assert active is True  # dipped mid-debounce: restore timer must have reset, still active


# --------------------------------------------------------------------------
# CONSERVATIVE fallback on forecast disagreement
# --------------------------------------------------------------------------

@pytest.mark.parametrize("actual,forecast,window_ok,expect_conservative", [
    (3.0, 1.0, True, True),     # 3x > 1.3x, held 5 min -> CONSERVATIVE
    (1.4, 1.0, True, True),     # 1.4x > 1.3x, held 5 min -> CONSERVATIVE
    (1.2, 1.0, True, False),    # 1.2x <= 1.3x -> stays PREDICTIVE
    (3.0, 1.0, False, False),   # disagreement present but not held 5 min
])
def test_forecast_disagreement_fallback(actual, forecast, window_ok, expect_conservative):
    cfg = _config()
    state = ctrl.init_state(t0=0.0)
    t = 0.0
    hold = 301.0 if window_ok else 60.0
    steps_n = 6 if window_ok else 2
    dt = hold / (steps_n - 1)
    mode = None
    for i in range(steps_n):
        inp = ctrl.ApInput(t=t, soc=0.8, soh=0.9, grid_ok=True, load_w=100.0, hour=12, dow=2,
                            fcst_t1_wh=5.0, i_forecast_a=3.0,
                            actual_decline_pct_per_min=actual, forecast_decline_pct_per_min=forecast)
        state, out = ctrl.evaluate(state, inp, cfg)
        mode = out.mode
        t += dt
    assert (mode == ctrl.Mode.CONSERVATIVE) == expect_conservative


def test_conservative_mode_clears_when_forecast_agrees_again():
    cfg = _config()
    state = ctrl.init_state(t0=0.0)
    t = 0.0
    for _ in range(6):
        inp = ctrl.ApInput(t=t, soc=0.8, soh=0.9, grid_ok=True, load_w=100.0, hour=12, dow=2,
                            fcst_t1_wh=5.0, i_forecast_a=3.0,
                            actual_decline_pct_per_min=3.0, forecast_decline_pct_per_min=1.0)
        state, out = ctrl.evaluate(state, inp, cfg)
        t += 60.0
    assert out.mode == ctrl.Mode.CONSERVATIVE
    inp = ctrl.ApInput(t=t, soc=0.8, soh=0.9, grid_ok=True, load_w=100.0, hour=12, dow=2,
                        fcst_t1_wh=5.0, i_forecast_a=3.0,
                        actual_decline_pct_per_min=1.0, forecast_decline_pct_per_min=1.0)
    state, out = ctrl.evaluate(state, inp, cfg)
    assert out.mode == ctrl.Mode.PREDICTIVE


# --------------------------------------------------------------------------
# Pre-charge / pre-emption
# --------------------------------------------------------------------------

def test_pre_charge_advisory_when_not_charger_commandable():
    cfg = _config(charger_commandable=False)
    state = ctrl.init_state(t0=0.0)
    inp = ctrl.ApInput(t=0.0, soc=0.60, soh=0.9, grid_ok=True, load_w=100.0, hour=8, dow=4,
                        fcst_t1_wh=5.0, i_forecast_a=3.0, outage_prob_h3=0.70, outage_conf=0.60)
    _, out = ctrl.evaluate(state, inp, cfg)
    assert out.pre_outage_active is True
    assert out.charger_command_active is False
    assert any("advisory" in r for r in out.reasons)


def test_pre_charge_active_when_charger_commandable():
    cfg = _config(charger_commandable=True)
    state = ctrl.init_state(t0=0.0)
    inp = ctrl.ApInput(t=0.0, soc=0.60, soh=0.9, grid_ok=True, load_w=100.0, hour=8, dow=4,
                        fcst_t1_wh=5.0, i_forecast_a=3.0, outage_prob_h3=0.70, outage_conf=0.60)
    _, out = ctrl.evaluate(state, inp, cfg)
    assert out.charger_command_active is True


def test_pre_charge_not_triggered_below_confidence():
    cfg = _config(charger_commandable=True)
    state = ctrl.init_state(t0=0.0)
    inp = ctrl.ApInput(t=0.0, soc=0.60, soh=0.9, grid_ok=True, load_w=100.0, hour=8, dow=4,
                        fcst_t1_wh=5.0, i_forecast_a=3.0, outage_prob_h3=0.70, outage_conf=0.30)
    _, out = ctrl.evaluate(state, inp, cfg)
    assert out.pre_outage_active is False


# --------------------------------------------------------------------------
# habit.py: EWMA table, cold start, seasonal seeding, outage stats
# --------------------------------------------------------------------------

def test_load_ewma_update_matches_formula():
    t = habit.LoadTable.new()
    t = habit.update_load_hour(t, 1, 7, 400.0, 100)
    t = habit.update_load_hour(t, 1, 7, 600.0, 200)
    b = t.bin(1, 7)
    expected_mean = 400.0 + habit.ALPHA_LOAD * (600.0 - 400.0)
    assert b.mean_w == pytest.approx(expected_mean)
    assert b.n_obs == 2


def test_load_table_update_is_pure_no_mutation():
    t0 = habit.LoadTable.new()
    t1 = habit.update_load_hour(t0, 2, 10, 300.0, 1)
    assert t0.bin(2, 10).n_obs == 0  # original untouched
    assert t1.bin(2, 10).n_obs == 1


@pytest.mark.parametrize("n_obs,expected_weight", [(0, 0.0), (14, 0.5), (14 * 13, 13.0 / 14.0)])
def test_cold_start_blend_weight(n_obs, expected_weight):
    b = habit.LoadBin(mean_w=100.0, n_obs=n_obs)
    assert b.blend_weight() == pytest.approx(expected_weight, rel=1e-6)


def test_cold_start_forecast_uses_generic_curve_when_unobserved():
    t = habit.LoadTable.new()
    w = habit.forecast_load_w(t, 3, 7, connected_load_nameplate_w=1000.0)
    assert w == pytest.approx(habit.generic_double_peak_w(7, 1000.0))


def test_season_transition_seeds_new_grid():
    t = habit.LoadTable.new()
    t = habit.update_load_hour(t, 1, 7, 500.0, 1)
    t2 = habit.transition_season(t, habit.Season.SUMMER)
    seeded = t2.bin(1, 7, habit.Season.SUMMER)
    assert seeded.mean_w == pytest.approx(500.0)
    assert seeded.n_obs > 0  # not a cold start


def test_outage_p_beta_smoothed_never_locks_to_one():
    ot = habit.OutageTable.new()
    ot = habit.observe_week(ot)
    ot = habit.record_outage_start(ot, 2, 18)
    p = ot.bin(2, 18).p_outage()
    assert p < 1.0
    assert p == pytest.approx(2.0 / 3.0)


def test_outage_confidence_grows_with_weeks_observed():
    ot = habit.OutageTable.new()
    for _ in range(20):
        ot = habit.observe_week(ot)
    assert ot.bin(0, 0).confidence() == pytest.approx(20.0 / 28.0)


def test_outage_prob_next_h_matches_survival_formula():
    ot = habit.OutageTable.new()
    ot = habit.observe_week(ot)
    ot = habit.record_outage_start(ot, 2, 18)
    fc = habit.outage_forecast(ot, 2, 18, horizon_h=1)
    assert fc.prob == pytest.approx(ot.bin(2, 18).p_outage())


def test_memory_footprint_within_5pct_of_4700_bytes():
    habit.assert_memory_footprint(tolerance=0.05)
    assert habit.resident_ram_bytes() == pytest.approx(4700, abs=250)


# --------------------------------------------------------------------------
# C port parity (skipped if gcc is not available)
# --------------------------------------------------------------------------

def _gcc_available():
    return shutil.which("gcc") is not None


def _build_c_binary():
    subprocess.run(["make", "-s"], cwd=_AUTOPILOT_DIR, check=True)
    return os.path.join(_AUTOPILOT_DIR, "test_autopilot_host")


@pytest.mark.skipif(not _gcc_available(), reason="gcc not on PATH")
def test_c_host_scenario_table_all_pass():
    binary = _build_c_binary()
    result = subprocess.run([binary], cwd=_AUTOPILOT_DIR, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "50/50 scenarios passed" in result.stdout


_TIER_MAP = {1: ctrl.Tier.T1, 2: ctrl.Tier.T2, 3: ctrl.Tier.T3}


def _replay_parity_file_python(path):
    """Returns a list of (channel_state tuple as 0/1 ints, mode int) per STEP."""
    results = []
    cfg = None
    state = None
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts[0] == "CFG":
                t0, hw0, t1, hw1, t2, hw2, t3, hw3, configured, charger, c_rated, v_nom, peukert_n = parts[1:14]
                channels = (
                    ctrl.ChannelConfig(_TIER_MAP[int(t0)], bool(int(hw0))),
                    ctrl.ChannelConfig(_TIER_MAP[int(t1)], bool(int(hw1))),
                    ctrl.ChannelConfig(_TIER_MAP[int(t2)], bool(int(hw2))),
                    ctrl.ChannelConfig(_TIER_MAP[int(t3)], bool(int(hw3))),
                )
                cfg = ctrl.default_config(channels=channels, configured=bool(int(configured)),
                                           charger_commandable=bool(int(charger)),
                                           c_rated_ah=float(c_rated), v_nominal=float(v_nom),
                                           peukert_n=float(peukert_n))
                state = ctrl.init_state(t0=0.0)
            elif parts[0] == "STEP":
                (t, soc, soh, grid_ok, load_w, hour, dow, temp_c, i_fcst, fcst_t1_wh,
                 outage_prob, outage_conf, actual_decline, forecast_decline,
                 override_req, override_timeout_s, override_clear) = parts[1:18]
                outage_prob = float(outage_prob)
                outage_conf = float(outage_conf)
                actual_decline = float(actual_decline)
                forecast_decline = float(forecast_decline)
                override_req = int(override_req)
                override_timeout_s = float(override_timeout_s)
                inp = ctrl.ApInput(
                    t=float(t), soc=float(soc), soh=float(soh), grid_ok=bool(int(grid_ok)),
                    load_w=float(load_w), hour=int(hour), dow=int(dow), temp_c=float(temp_c),
                    i_forecast_a=float(i_fcst), fcst_t1_wh=float(fcst_t1_wh),
                    outage_prob_h3=outage_prob if (outage_prob >= 0 and outage_conf >= 0) else None,
                    outage_conf=outage_conf if (outage_prob >= 0 and outage_conf >= 0) else None,
                    actual_decline_pct_per_min=actual_decline if actual_decline > -1e8 else None,
                    forecast_decline_pct_per_min=forecast_decline if forecast_decline > -1e8 else None,
                    override_request=override_req if override_req >= 0 else None,
                    override_timeout_s=override_timeout_s if override_timeout_s >= 0 else None,
                    override_clear=bool(int(override_clear)),
                )
                state, out = ctrl.evaluate(state, inp, cfg)
                results.append(tuple(int(s) for s in out.channel_state) + (int(out.mode),))
    return results


@pytest.mark.skipif(not _gcc_available(), reason="gcc not on PATH")
def test_c_matches_python_parity():
    binary = _build_c_binary()
    parity_file = os.path.join(_AUTOPILOT_DIR, "parity_scenarios.txt")
    result = subprocess.run([binary, "--parity", parity_file], cwd=_AUTOPILOT_DIR, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    c_rows = [tuple(int(x) for x in row) for row in csv.reader(result.stdout.strip().splitlines())]
    py_rows = _replay_parity_file_python(parity_file)
    assert len(c_rows) == len(py_rows) and len(c_rows) > 0
    for i, (c_row, py_row) in enumerate(zip(c_rows, py_rows)):
        assert c_row == py_row, "row %d mismatch: C=%s python=%s" % (i, c_row, py_row)
