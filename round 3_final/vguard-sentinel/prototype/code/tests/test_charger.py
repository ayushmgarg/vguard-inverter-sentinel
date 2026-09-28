"""pytest suite for the V-Guard Sentinel adaptive charging policy + charger
UART interface (module I).

Covers:
  * temperature-compensated setpoints at 10/25/40 C (design 03 Sec.3.1/3.2)
  * hardware ceiling clamp (15.5 V) and floor
  * current-limit derating curve above 45 C, OFF at 58 C
  * adaptive absorption termination: tail current AND timeout paths
  * equalisation scheduler: all four gate conditions individually required,
    quarterly water-loss cap respected
  * pre-charge holds/extends absorption only when charger_commandable
    (Embedded); Retrofit produces advice strings and zero frames
  * fault fallback (NaN/out-of-range sensor, missing heartbeat ack)
  * simulated charger: NACK on over-ceiling setpoint, reverts to factory
    defaults on heartbeat loss, GET_STATUS reply
  * frame codec: round-trip, CRC corruption + resync
  * C/Python codec byte-parity (subprocess to test_frames_host; skipped if
    gcc is unavailable)

Run: `pytest -q` from documentation/prototype/code/ (CONTRACTS.md Sec.0).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(_THIS_DIR)
_CHARGER_DIR = os.path.join(_CODE_ROOT, "charger")
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from charger import frames  # noqa: E402
from charger import policy  # noqa: E402
from charger import sim_charger  # noqa: E402


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _cfg(**overrides) -> policy.ChargerConfig:
    return policy.ChargerConfig(**overrides)


def _input(**overrides) -> policy.PolicyInput:
    defaults = dict(
        t_s=0.0, v_batt=13.0, i_batt=5.0, t_batt_c=25.0,
        grid_ok=True, charging_requested=True, soc=0.5,
    )
    defaults.update(overrides)
    return policy.PolicyInput(**defaults)


def _run_ticks(cfg, inputs):
    """inputs: list of PolicyInput (t_s must be increasing). Returns list of PolicyOutput."""
    state = policy.PolicyState.initial(inputs[0].t_s)
    outs = []
    for inp in inputs:
        out = policy.evaluate(inp, state, cfg)
        outs.append(out)
        state = out.state
    return outs


# --------------------------------------------------------------------------
# Temperature-compensated setpoints (design 03 Sec.3.1/3.2)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("t_c", [10.0, 25.0, 40.0])
def test_temp_compensation_matches_formula(t_c):
    cfg = _cfg()
    expected_float = cfg.cells_per_pack * (cfg.float_v_cell_25 + cfg.temp_coeff_v_per_c_cell * (t_c - 25.0))
    expected_abs = cfg.cells_per_pack * (cfg.absorption_v_cell_25 + cfg.temp_coeff_v_per_c_cell * (t_c - 25.0))
    expected_eq = cfg.cells_per_pack * (cfg.equalise_v_cell_25 + cfg.temp_coeff_v_per_c_cell * (t_c - 25.0))

    got_float = policy.temp_compensated_v(cfg.float_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                           cfg.cells_per_pack, t_c, cfg.ceiling_v, cfg.floor_v)
    got_abs = policy.temp_compensated_v(cfg.absorption_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                         cfg.cells_per_pack, t_c, cfg.ceiling_v, cfg.floor_v)
    got_eq = policy.temp_compensated_v(cfg.equalise_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                        cfg.cells_per_pack, t_c, cfg.ceiling_v, cfg.floor_v)

    assert got_float == pytest.approx(min(max(expected_float, cfg.floor_v), cfg.ceiling_v), abs=1e-6)
    assert got_abs == pytest.approx(min(max(expected_abs, cfg.floor_v), cfg.ceiling_v), abs=1e-6)
    assert got_eq == pytest.approx(min(max(expected_eq, cfg.floor_v), cfg.ceiling_v), abs=1e-6)


def test_temp_compensation_at_25c_matches_nominal_per_cell_times_six():
    cfg = _cfg()
    v = policy.temp_compensated_v(cfg.float_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                   cfg.cells_per_pack, 25.0, cfg.ceiling_v, cfg.floor_v)
    assert v == pytest.approx(cfg.float_v_cell_25 * 6, abs=1e-9)


def test_colder_temperature_raises_setpoint_hotter_lowers_it():
    cfg = _cfg()
    v10 = policy.temp_compensated_v(cfg.float_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                     cfg.cells_per_pack, 10.0, cfg.ceiling_v, cfg.floor_v)
    v25 = policy.temp_compensated_v(cfg.float_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                     cfg.cells_per_pack, 25.0, cfg.ceiling_v, cfg.floor_v)
    v40 = policy.temp_compensated_v(cfg.float_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                     cfg.cells_per_pack, 40.0, cfg.ceiling_v, cfg.floor_v)
    assert v10 > v25 > v40  # negative temp coeff (03 Sec.3.1)


# --------------------------------------------------------------------------
# Ceiling / floor clamp
# --------------------------------------------------------------------------

def test_ceiling_clamp_at_extreme_cold():
    cfg = _cfg()
    v = policy.temp_compensated_v(cfg.equalise_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                   cfg.cells_per_pack, -30.0, cfg.ceiling_v, cfg.floor_v)
    assert v == pytest.approx(cfg.ceiling_v)


def test_floor_clamp_at_extreme_heat():
    cfg = _cfg()
    v = policy.temp_compensated_v(cfg.float_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                   cfg.cells_per_pack, 150.0, cfg.ceiling_v, cfg.floor_v)
    assert v == pytest.approx(cfg.floor_v)


def test_never_exceeds_hardware_ceiling_across_temp_sweep():
    cfg = _cfg()
    for t_c in range(-40, 90, 2):
        for v25 in (cfg.float_v_cell_25, cfg.absorption_v_cell_25, cfg.equalise_v_cell_25):
            v = policy.temp_compensated_v(v25, cfg.temp_coeff_v_per_c_cell, cfg.cells_per_pack,
                                           float(t_c), cfg.ceiling_v, cfg.floor_v)
            assert v <= cfg.ceiling_v + 1e-9
            assert v >= cfg.floor_v - 1e-9


# --------------------------------------------------------------------------
# Current-limit derating + thermal OFF
# --------------------------------------------------------------------------

def test_derating_curve_matches_formula_above_45c():
    cfg = _cfg()
    for t_c in (46.0, 50.0, 55.0, 57.9):
        expected = max(0.0, min(100.0, 100.0 - 4.0 * (t_c - 45.0)))
        assert policy.current_limit_pct(t_c, cfg) == pytest.approx(expected)


def test_full_current_limit_at_or_below_45c():
    cfg = _cfg()
    for t_c in (-10.0, 0.0, 25.0, 45.0):
        assert policy.current_limit_pct(t_c, cfg) == 100.0


def test_derating_at_55c_is_60pct():
    cfg = _cfg()
    assert policy.current_limit_pct(55.0, cfg) == pytest.approx(60.0)


def test_charger_off_at_58c_and_above():
    cfg = _cfg()
    assert policy.current_limit_pct(58.0, cfg) == 0.0
    assert policy.current_limit_pct(65.0, cfg) == 0.0

    inp = _input(t_batt_c=58.0)
    out = policy.evaluate(inp, policy.PolicyState.initial(0.0), cfg)
    assert out.phase == policy.ChargePhase.OFF_THERMAL
    assert out.charger_should_be_off is True
    assert out.current_limit_pct == 0.0
    assert any("OFF" in a for a in out.alerts)


def test_charger_stays_on_just_below_58c():
    cfg = _cfg()
    inp = _input(t_batt_c=57.9)
    out = policy.evaluate(inp, policy.PolicyState.initial(0.0), cfg)
    assert out.phase != policy.ChargePhase.OFF_THERMAL
    assert out.charger_should_be_off is False


# --------------------------------------------------------------------------
# Adaptive absorption termination
# --------------------------------------------------------------------------

def test_absorption_terminates_on_tail_current():
    cfg = _cfg(c20_ah=150.0, tail_current_pct_c20=1.5)  # tail threshold = 1.5%*7.5A = 0.1125A
    tail_a = policy.tail_current_threshold_a(cfg)
    assert tail_a == pytest.approx(0.1125, abs=1e-6)

    t0 = 0.0
    inputs = [
        _input(t_s=t0, i_batt=10.0, soc=0.5),           # enters absorption, high current
        _input(t_s=t0 + 60.0, i_batt=8.0, soc=0.6),      # still tapering, above tail
        _input(t_s=t0 + 120.0, i_batt=0.05, soc=0.9),    # below tail threshold -> terminate
    ]
    outs = _run_ticks(cfg, inputs)
    assert outs[0].phase == policy.ChargePhase.ABSORPTION
    assert outs[1].phase == policy.ChargePhase.ABSORPTION
    assert outs[2].phase == policy.ChargePhase.FLOAT
    assert any("tail current" in a for a in outs[2].alerts)


def test_absorption_terminates_on_timeout_when_current_never_tapers():
    cfg = _cfg(absorption_timeout_nominal_h=1.0)  # short timeout to keep the test fast
    t0 = 0.0
    inputs = [_input(t_s=t0, i_batt=20.0, soc=0.2)]
    # keep current high (never reaches tail threshold) for > 1h in 60s steps
    n_steps = int(1.2 * 3600 / 60)
    for i in range(1, n_steps + 1):
        inputs.append(_input(t_s=t0 + i * 60.0, i_batt=20.0, soc=0.2))
    outs = _run_ticks(cfg, inputs)
    assert outs[0].phase == policy.ChargePhase.ABSORPTION
    # eventually terminates on timeout despite current never tapering
    terminated = [o for o in outs if o.phase == policy.ChargePhase.FLOAT]
    assert terminated, "absorption never timed out"
    assert any("timeout" in a for o in terminated for a in o.alerts)


def test_absorption_timeout_is_longer_when_cold():
    cfg = _cfg()
    warm = policy.absorption_timeout_hours(25.0, cfg)
    cold = policy.absorption_timeout_hours(0.0, cfg)
    assert cold > warm
    assert warm == pytest.approx(cfg.absorption_timeout_nominal_h)
    assert cold <= cfg.absorption_timeout_cold_max_h + 1e-9


# --------------------------------------------------------------------------
# Equalisation scheduler: all four gate conditions required
# --------------------------------------------------------------------------

def _eq_input(**overrides):
    defaults = dict(
        t_s=31 * 86400.0,  # > 30 days since epoch/last-equalise
        v_batt=13.5, i_batt=2.0, t_batt_c=25.0,
        grid_ok=True, charging_requested=True, soc=0.9,
        sulphation_signature=True,
    )
    defaults.update(overrides)
    return policy.PolicyInput(**defaults)


def test_equalisation_starts_when_all_four_conditions_met():
    cfg = _cfg()
    state = policy.PolicyState.initial(0.0)
    inp = _eq_input()
    out = policy.evaluate(inp, state, cfg)
    assert out.phase == policy.ChargePhase.EQUALISE


@pytest.mark.parametrize("field,value", [
    ("sulphation_signature", False),      # condition (b) fails
    ("t_batt_c", 45.0),                   # condition (c) fails (>= 40C)
])
def test_equalisation_blocked_when_single_flag_condition_fails(field, value):
    cfg = _cfg()
    state = policy.PolicyState.initial(0.0)
    inp = _eq_input(**{field: value})
    out = policy.evaluate(inp, state, cfg)
    assert out.phase != policy.ChargePhase.EQUALISE


def test_equalisation_blocked_before_30_days_since_last():
    cfg = _cfg()
    state = replace_state(policy.PolicyState.initial(0.0), last_equalise_end_s=0.0)
    inp = _eq_input(t_s=20 * 86400.0)  # only 20 days since last
    out = policy.evaluate(inp, state, cfg)
    assert out.phase != policy.ChargePhase.EQUALISE


def test_equalisation_blocked_when_outage_predicted_within_6h():
    cfg = _cfg()
    state = policy.PolicyState.initial(0.0)
    inp = _eq_input(outage_prob_h6=0.9, outage_forecast_confidence=0.9)
    out = policy.evaluate(inp, state, cfg)
    assert out.phase != policy.ChargePhase.EQUALISE


def test_equalisation_allowed_when_outage_forecast_low_confidence():
    cfg = _cfg()
    state = policy.PolicyState.initial(0.0)
    # high probability but confidence below threshold -> gate condition (d) still true
    inp = _eq_input(outage_prob_h6=0.9, outage_forecast_confidence=0.1)
    out = policy.evaluate(inp, state, cfg)
    assert out.phase == policy.ChargePhase.EQUALISE


def test_equalisation_aborts_above_50c():
    cfg = _cfg(equalise_duration_h=1.0)
    state = policy.PolicyState.initial(0.0)
    out0 = policy.evaluate(_eq_input(t_s=0.0), state, cfg)
    assert out0.phase == policy.ChargePhase.EQUALISE

    out1 = policy.evaluate(_eq_input(t_s=60.0, t_batt_c=51.0), out0.state, cfg)
    assert out1.phase == policy.ChargePhase.FLOAT
    assert any("aborted" in a for a in out1.alerts)


def test_equalisation_quarterly_cap_blocks_further_sessions():
    cfg = _cfg(equalise_quarterly_cap_h=2.0, equalise_duration_h=3.0, equalise_min_interval_days=0.0)
    state = policy.PolicyState.initial(0.0)

    # first session runs to completion (3h planned, but cap will only count actual hours)
    t = 0.0
    out = policy.evaluate(_eq_input(t_s=t, sulphation_signature=True), state, cfg)
    assert out.phase == policy.ChargePhase.EQUALISE
    state = out.state
    # advance past planned duration to end it
    t += 3.1 * 3600.0
    out = policy.evaluate(_eq_input(t_s=t, sulphation_signature=True), state, cfg)
    assert out.phase == policy.ChargePhase.FLOAT
    state = out.state
    assert state.quarter_equalise_hours >= 2.0

    # immediately try again (0-day interval configured) -- cap should now block it
    t += 60.0
    out2 = policy.evaluate(_eq_input(t_s=t, sulphation_signature=True), state, cfg)
    assert out2.phase != policy.ChargePhase.EQUALISE


def replace_state(state, **kw):
    from dataclasses import replace as _r
    return _r(state, **kw)


# --------------------------------------------------------------------------
# Pre-charge: raises/holds target only when commandable
# --------------------------------------------------------------------------

def test_precharge_holds_absorption_when_commandable():
    cfg = _cfg(sku_commandable=True, absorption_timeout_nominal_h=0.5, tail_current_pct_c20=50.0)
    state = policy.PolicyState.initial(0.0)
    # enter absorption
    out = policy.evaluate(_input(t_s=0.0, i_batt=10.0, soc=0.2), state, cfg)
    assert out.phase == policy.ChargePhase.ABSORPTION
    state = out.state
    # advance well past the (short) timeout, but with pre-charge forecast active
    out2 = policy.evaluate(
        _input(t_s=3600.0, i_batt=10.0, soc=0.2, outage_prob_h3=0.9, outage_forecast_confidence=0.9),
        state, cfg,
    )
    assert out2.phase == policy.ChargePhase.ABSORPTION
    assert any("pre-charge" in a for a in out2.alerts)
    assert out2.commands  # Embedded: commands emitted


def test_precharge_is_advisory_only_and_emits_no_commands_when_not_commandable():
    cfg = _cfg(sku_commandable=False)
    state = policy.PolicyState.initial(0.0)
    inp = _input(t_s=0.0, outage_prob_h3=0.9, outage_forecast_confidence=0.9, soc=0.2)
    out = policy.evaluate(inp, state, cfg)
    assert out.commands == ()
    assert out.advice != ()


# --------------------------------------------------------------------------
# Retrofit SKU: advice strings, zero frames, but the same setpoints
# --------------------------------------------------------------------------

def test_retrofit_produces_advice_and_zero_commands():
    embedded_cfg = _cfg(sku_commandable=True)
    retrofit_cfg = _cfg(sku_commandable=False)
    state_e = policy.PolicyState.initial(0.0)
    state_r = policy.PolicyState.initial(0.0)
    inp_e = _input(t_s=0.0)
    inp_r = _input(t_s=0.0)

    out_e = policy.evaluate(inp_e, state_e, embedded_cfg)
    out_r = policy.evaluate(inp_r, state_r, retrofit_cfg)

    assert out_e.commands != ()
    assert out_r.commands == ()
    assert out_r.advice != ()
    # same underlying setpoints regardless of SKU (03 Sec.3: "both SKUs compute it")
    assert out_e.float_v == pytest.approx(out_r.float_v)
    assert out_e.absorption_v == pytest.approx(out_r.absorption_v)
    assert out_e.equalise_v == pytest.approx(out_r.equalise_v)
    assert out_e.phase == out_r.phase


def test_retrofit_never_emits_any_command_across_all_phases():
    cfg = _cfg(sku_commandable=False, equalise_min_interval_days=0.0)
    state = policy.PolicyState.initial(0.0)
    scenarios = [
        _input(t_s=0.0, t_batt_c=58.0),                                     # thermal off
        _eq_input(t_s=0.0, sulphation_signature=True),                      # equalise start
        _input(t_s=0.0, v_batt=float("nan")),                               # fault
        _input(t_s=0.0, grid_ok=False, charging_requested=False),           # idle
        _input(t_s=0.0, soc=0.2),                                           # absorption
    ]
    for inp in scenarios:
        out = policy.evaluate(inp, state, cfg)
        assert out.commands == (), "retrofit must never emit wire commands"


# --------------------------------------------------------------------------
# Fault fallback
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad_field,bad_value", [
    ("v_batt", float("nan")),
    ("i_batt", float("nan")),
    ("t_batt_c", float("nan")),
    ("v_batt", 999.0),
    ("t_batt_c", -999.0),
])
def test_fault_fallback_on_bad_sensor(bad_field, bad_value):
    cfg = _cfg(sku_commandable=True)
    state = policy.PolicyState.initial(0.0)
    inp = _input(t_s=0.0, **{bad_field: bad_value})
    out = policy.evaluate(inp, state, cfg)
    assert out.fault is True
    assert out.phase == policy.ChargePhase.FAULT
    assert out.commands  # factory defaults ARE commanded (Embedded)
    # factory defaults: nominal 25C setpoints, full current limit
    assert out.current_limit_pct == 100.0


def test_fault_fallback_on_missing_heartbeat_ack():
    cfg = _cfg(heartbeat_max_age_s=2.0)
    state = policy.PolicyState.initial(0.0)
    inp = _input(t_s=0.0, heartbeat_ack_age_s=5.0)
    out = policy.evaluate(inp, state, cfg)
    assert out.fault is True
    assert out.phase == policy.ChargePhase.FAULT


def test_no_fault_with_fresh_heartbeat_and_valid_sensors():
    cfg = _cfg()
    state = policy.PolicyState.initial(0.0)
    inp = _input(t_s=0.0, heartbeat_ack_age_s=0.5)
    out = policy.evaluate(inp, state, cfg)
    assert out.fault is False


# --------------------------------------------------------------------------
# Simulated charger: NACK, heartbeat-loss revert, GET_STATUS
# --------------------------------------------------------------------------

def test_sim_charger_nacks_over_ceiling_setpoint():
    dev = sim_charger.SimCharger(t0=0.0)
    # 2600 mV/cell * 6 = 15.6 V > 15.5 V ceiling
    resp = dev.feed_bytes(frames.encode_set_float(2600))
    assert len(resp) == 1
    cmd, payload = frames.parse_all(resp[0])[0]
    assert cmd == frames.CMD_NACK
    assert frames.decode_nack(payload) == frames.NACK_RANGE_ERROR


def test_sim_charger_accepts_within_ceiling_setpoint_silently():
    dev = sim_charger.SimCharger(t0=0.0)
    resp = dev.feed_bytes(frames.encode_set_float(2270))
    assert resp == []
    assert dev.float_mv == 2270


def test_sim_charger_reverts_to_factory_defaults_on_heartbeat_loss():
    dev = sim_charger.SimCharger(t0=0.0)
    dev.feed_bytes(frames.encode_set_absorption(2450, 200))
    dev.feed_bytes(frames.encode_heartbeat(1))
    assert dev.absorption_mv == 2450
    assert dev.mode == frames.STATUS_MODE_ABSORPTION

    dev.tick(0.5, 0.5)
    assert dev.mode == frames.STATUS_MODE_ABSORPTION  # still within 2s, no revert yet

    dev.tick(2.6, 2.1)  # > 2s since last heartbeat ack
    assert dev.mode == frames.STATUS_MODE_FLOAT
    assert dev.float_mv == int(round(sim_charger.FACTORY_FLOAT_V_CELL * 1000))
    assert dev.fault_flags & frames.FAULT_FLAG_HEARTBEAT_LOST


def test_sim_charger_get_status_round_trip():
    dev = sim_charger.SimCharger(t0=0.0, t_batt_c=30.0)
    dev.feed_bytes(frames.encode_heartbeat(1))
    dev.tick(0.0, 1.0)
    resp = dev.feed_bytes(frames.encode_get_status())
    assert len(resp) == 1
    cmd, payload = frames.parse_all(resp[0])[0]
    assert cmd == frames.CMD_GET_STATUS
    decoded = frames.decode_status(payload)
    assert decoded["t_batt_c"] == pytest.approx(30.0, abs=0.1)
    assert decoded["mode"] == dev.mode


# --------------------------------------------------------------------------
# Frame codec: round-trip, CRC corruption + resync
# --------------------------------------------------------------------------

def test_codec_round_trip_all_commands():
    cases = [
        (frames.CMD_SET_FLOAT, frames.encode_set_float(2270)),
        (frames.CMD_SET_ABSORPTION, frames.encode_set_absorption(2435, 180)),
        (frames.CMD_SET_EQUALISE, frames.encode_set_equalise(2540, 150, True)),
        (frames.CMD_SET_CURRENT_LIMIT_PCT, frames.encode_set_current_limit_pct(76)),
        (frames.CMD_SET_TEMP_COMP, frames.encode_set_temp_comp(-4000)),
        (frames.CMD_GET_STATUS, frames.encode_get_status()),
        (frames.CMD_HEARTBEAT, frames.encode_heartbeat(0x12345678)),
        (frames.CMD_NACK, frames.encode_nack(frames.NACK_CRC_ERROR)),
    ]
    for expected_cmd, frame in cases:
        assert frame[0] == frames.SOF
        assert frame[-1] == frames.EOF
        parsed = frames.parse_all(frame)
        assert len(parsed) == 1
        cmd, payload = parsed[0]
        assert cmd == expected_cmd


def test_codec_round_trip_value_fidelity():
    cmd, payload = frames.parse_all(frames.encode_set_float(2270))[0]
    assert frames.decode_set_float(payload) == 2270

    cmd, payload = frames.parse_all(frames.encode_set_absorption(2435, 180))[0]
    assert frames.decode_set_absorption(payload) == (2435, 180)

    cmd, payload = frames.parse_all(frames.encode_set_equalise(2540, 150, True))[0]
    assert frames.decode_set_equalise(payload) == (2540, 150, True)

    cmd, payload = frames.parse_all(frames.encode_heartbeat(0xDEADBEEF))[0]
    assert frames.decode_heartbeat(payload) == 0xDEADBEEF


def test_codec_handles_payload_needing_byte_stuffing():
    # 0xAAAA -> LE bytes 0xAA 0xAA, both equal to SOF and must be stuffed
    frame = frames.encode_set_float(0xAAAA)
    assert frame.count(frames.SOF) == 1  # only the literal framing SOF remains unescaped
    assert frame.count(frames.EOF) == 1
    cmd, payload = frames.parse_all(frame)[0]
    assert frames.decode_set_float(payload) == 0xAAAA


def test_codec_crc_corruption_then_resync():
    good1 = bytearray(frames.encode_set_float(2270))
    good2 = frames.encode_heartbeat(42)
    # corrupt a payload byte (index 3, inside CMD/LEN/PAYLOAD, not SOF/EOF)
    good1[3] ^= 0xFF

    parser = frames.FrameParser()
    out1 = parser.feed(bytes(good1))
    assert out1 == []  # corrupted frame silently dropped

    out2 = parser.feed(good2)
    assert len(out2) == 1
    cmd, payload = out2[0]
    assert cmd == frames.CMD_HEARTBEAT
    assert frames.decode_heartbeat(payload) == 42


def test_codec_resync_on_stray_sof_mid_frame():
    frame1 = frames.encode_set_float(2270)
    frame2 = frames.encode_heartbeat(7)
    stream = frame1[:-2] + frame2  # frame1 truncated (no CRC/EOF), then a full frame2

    parser = frames.FrameParser()
    out = parser.feed(stream)
    assert len(out) == 1
    cmd, payload = out[0]
    assert cmd == frames.CMD_HEARTBEAT


def test_codec_garbage_before_first_sof_is_ignored():
    garbage = bytes([0x00, 0x01, 0xFF, 0x02])
    frame = frames.encode_heartbeat(99)
    parser = frames.FrameParser()
    out = parser.feed(garbage + frame)
    assert len(out) == 1
    assert out[0][0] == frames.CMD_HEARTBEAT


def test_codec_streaming_byte_at_a_time():
    frame = frames.encode_set_absorption(2435, 180)
    parser = frames.FrameParser()
    got = []
    for b in frame:
        got.extend(parser.feed(bytes([b])))
    assert len(got) == 1
    assert got[0][0] == frames.CMD_SET_ABSORPTION


# --------------------------------------------------------------------------
# C port parity (skipped if gcc is not available)
# --------------------------------------------------------------------------

def _gcc_available():
    return shutil.which("gcc") is not None


def _build_c_binary():
    subprocess.run(["make", "-s"], cwd=_CHARGER_DIR, check=True)
    return os.path.join(_CHARGER_DIR, "test_frames_host")


@pytest.mark.skipif(not _gcc_available(), reason="gcc not on PATH")
def test_c_host_self_tests_pass():
    binary = _build_c_binary()
    result = subprocess.run([binary], cwd=_CHARGER_DIR, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL CHECKS PASSED" in result.stderr


def _parse_vector_file(path):
    """Mirror test_frames_host.c's --vectors parser: (name, args) per line."""
    vectors = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            vectors.append((parts[0], [int(x) for x in parts[1:]]))
    return vectors


def _encode_vector_python(name, args):
    if name == "SET_FLOAT":
        return frames.encode_set_float(args[0])
    if name == "SET_ABSORPTION":
        return frames.encode_set_absorption(args[0], args[1])
    if name == "SET_EQUALISE":
        return frames.encode_set_equalise(args[0], args[1], bool(args[2]))
    if name == "SET_CURRENT_LIMIT_PCT":
        return frames.encode_set_current_limit_pct(args[0])
    if name == "SET_TEMP_COMP":
        return frames.encode_set_temp_comp(args[0])
    if name == "GET_STATUS":
        return frames.encode_get_status()
    if name == "HEARTBEAT":
        return frames.encode_heartbeat(args[0])
    if name == "NACK":
        return frames.encode_nack(args[0])
    raise ValueError("unknown vector command: %s" % name)


@pytest.mark.skipif(not _gcc_available(), reason="gcc not on PATH")
def test_c_matches_python_byte_for_byte():
    _build_c_binary()
    vectors_path = os.path.join(_CHARGER_DIR, "parity_vectors.txt")
    result = subprocess.run(
        [os.path.join(_CHARGER_DIR, "test_frames_host"), "--vectors", vectors_path],
        cwd=_CHARGER_DIR, capture_output=True, text=True, check=True,
    )
    c_lines = [l for l in result.stdout.splitlines() if l.strip()]
    vectors = _parse_vector_file(vectors_path)
    assert len(c_lines) == len(vectors)

    for (name, args), c_line in zip(vectors, c_lines):
        c_name, c_hex = c_line.split(":", 1)
        assert c_name == name
        py_frame = _encode_vector_python(name, args)
        assert frames.frame_to_hex(py_frame) == c_hex, (
            "C/Python codec mismatch for %s%r: python=%s c=%s"
            % (name, args, frames.frame_to_hex(py_frame), c_hex)
        )
