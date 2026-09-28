"""Adaptive charging policy — pure-function state machine, design 03 Sec.3.

Implements design doc ``03-Adaptive-Charging-and-Charger-Interface.md``
Sec.3.1 (per-cell setpoints for tubular flooded lead-acid) and Sec.3.2 (the
60 s policy loop), plus the tail-current/rest-anchor numbers from
``01-Battery-State-Estimation.md`` Sec.5a. Mirrors the project's immutability
discipline (``~/.claude/rules/common/coding-style.md`` and the pattern
already used in ``autopilot/controller.py``): every function here is pure —
it takes a ``PolicyInput``/``PolicyState``/``ChargerConfig`` and returns a
NEW ``PolicyOutput`` (which carries the next ``PolicyState``); nothing is
mutated in place.

Per design 03 Sec.3 header: **"both SKUs compute it; only Embedded applies
it."** This module always runs the full phase state machine and setpoint
math regardless of ``ChargerConfig.sku_commandable``; the SKU flag only
changes whether the result comes out as ``commands`` (wire-ready
``charger.frames``-encodable dataclasses, Embedded) or ``advice`` (plain
strings describing the same numbers, Retrofit — 03 Sec.2.1, "no setpoint
control is possible... advisory-only").

Design-doc ambiguities resolved here, documented honestly (see also
``README.md`` "Honest limits"):

  * **Per-cell defaults** (03 Sec.3.1 gives ranges, not points): float
    2.27 V/cell (mid of 2.23-2.30), absorption 2.435 V/cell (mid of
    2.40-2.47), equalise 2.54 V/cell (mid of 2.50-2.58), temp coeff
    -4 mV/°C/cell (the doc's own cited Victron default). All are
    ``ChargerConfig`` fields — override with a manufacturer datasheet
    value; these are illustrative, not measured for a specific battery.
  * **Setpoint floor** (the task asks for "a floor" alongside the 15.5 V
    hardware ceiling; the design doc only gives the ceiling). Default
    12.0 V pack — low enough not to bind at any realistic temperature
    with the defaults above, high enough to refuse an absurd setpoint if
    a bad temperature reading were not caught by the fault gate first.
    Interpretive, configurable.
  * **Absorption timeout shape** (03 Sec.3.2: "2-4 h at 25 °C, longer when
    cold"): nominal 3.0 h at T >= 25 °C, extended below 25 °C by a
    configurable slope, capped at an absolute cold-weather ceiling.
  * **Equalisation-gate condition (d), "no outage predicted in the next
    6 h"**: reuses the same probability/confidence shape and default
    thresholds as the pre-charge trigger (P > 0.55, confidence >= 0.5,
    03 Sec.3.2), applied to a caller-supplied 6 h-horizon forecast field
    rather than the 3 h one — the design doc gives numbers for the 3 h
    pre-charge case only; no separate number is given for the 6 h gate.
  * **Quarterly water-loss cap**: "cap cumulative equalisation hours per
    quarter" (03 Sec.3.2) with no number given. Default 8 h/quarter
    (roughly 2-3 monthly 2.5-3 h sessions), and "quarter" is a rolling
    90-day window in the same monotonic-seconds clock as everything else
    in this prototype (there is no wall-clock/calendar dependency
    anywhere else in ``prototype/code/``), not a calendar quarter.
  * **Bulk-phase / CC ramp-up is out of scope.** This module issues
    supervisory setpoints (float/absorption/equalise voltage + current
    limit); it does not model or command the low-current bulk/CC ramp —
    that is the charger hardware's own closed loop under the absorption
    voltage cap ("defence in depth", 03 Sec.1.2). ``sim_charger.py``'s
    battery model implements that electrical behaviour; this module only
    decides *which* setpoint should currently be in effect and adaptively
    ends absorption.

Python 3.9 compatible: no ``match``, no ``X | Y`` union syntax.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import Optional, Tuple

from charger import frames

SECONDS_PER_DAY = 86400.0
SECONDS_PER_HOUR = 3600.0


class ChargePhase(IntEnum):
    IDLE = 0          # not charging (no grid, or not requested)
    ABSORPTION = 1
    FLOAT = 2
    EQUALISE = 3
    OFF_THERMAL = 4   # T >= off_temp_c: charger commanded off
    FAULT = 5         # sensor/heartbeat fault: factory defaults


# --------------------------------------------------------------------------
# Config (design 03 Sec.3.1 setpoints, Sec.3.2 loop constants)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChargerConfig:
    sku_commandable: bool = True  # True = Embedded (03 Sec.1), False = Retrofit (03 Sec.2)

    # --- 3.1 per-cell setpoints @ 25 C, tubular flooded lead-acid ---
    float_v_cell_25: float = 2.27
    absorption_v_cell_25: float = 2.435
    equalise_v_cell_25: float = 2.54
    cells_per_pack: int = 6  # 12 V pack = 6 x 2 V cells (task spec: "x6 for 12V")
    temp_coeff_v_per_c_cell: float = -0.004  # Victron default, -4 mV/C/cell (03 Sec.3.1)

    ceiling_v: float = 15.5   # hardware ceiling, 03 Sec.1.1 (comparator/zener clamp)
    floor_v: float = 12.0     # interpretive floor, see module docstring

    # --- current-limit derating (03 Sec.3.2) ---
    derate_start_c: float = 45.0
    derate_pct_per_c: float = 4.0
    off_temp_c: float = 58.0

    # --- absorption termination (01 Sec.5a tail current; 03 Sec.3.2 timeout) ---
    tail_current_pct_c20: float = 1.5   # within design's 1-2% C20
    c20_ah: float = 150.0  # nameplate Ah -- MUST come from the battery's own datasheet
    absorption_timeout_nominal_h: float = 3.0       # within 2-4h @ 25C
    absorption_cold_extension_h_per_c: float = 0.08  # "longer when cold"
    absorption_timeout_cold_max_h: float = 6.0

    # --- equalisation scheduler (03 Sec.3.1/3.2) ---
    equalise_min_interval_days: float = 30.0
    equalise_max_temp_c: float = 40.0    # gate condition (c)
    equalise_abort_temp_c: float = 50.0  # abort mid-session
    equalise_duration_h: float = 2.5     # within 2-3h
    equalise_quarter_days: float = 90.0
    equalise_quarterly_cap_h: float = 8.0  # water-loss guard, interpretive default

    # --- pre-charge (05 Sec.2.3 / 03 Sec.3.2) ---
    precharge_outage_prob_threshold: float = 0.55
    precharge_outage_conf_threshold: float = 0.5

    # --- sensor validity bounds (fault fallback) ---
    v_min_valid: float = 0.0
    v_max_valid: float = 20.0
    t_min_valid: float = -20.0
    t_max_valid: float = 80.0
    i_min_valid: float = -300.0
    i_max_valid: float = 300.0
    heartbeat_max_age_s: float = 2.0  # 03 Sec.1.2: "<=2s period; on loss -> factory defaults"

    # --- SoC full-enough-to-skip-absorption threshold ---
    soc_full_enough: float = 0.995


# --------------------------------------------------------------------------
# Input / State / Output (immutable dataclasses)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyInput:
    t_s: float                     # monotonic seconds since boot (matches autopilot's ApInput.t)
    v_batt: float                  # pack terminal voltage, V
    i_batt: float                  # + charge, - discharge (CONTRACTS.md Sec.1 battery convention)
    t_batt_c: float
    grid_ok: bool                  # mains present
    charging_requested: bool       # upstream (autopilot/charger relay) says a charge cycle is active
    soc: Optional[float] = None    # 0-1, from the EKF; None if unavailable
    sulphation_signature: bool = False  # SoH pipeline flag, 02 Sec.1.6-1.7
    outage_prob_h3: Optional[float] = None    # P(outage, 3h) -- pre-charge trigger, 05 Sec.2.3
    outage_prob_h6: Optional[float] = None    # P(outage, 6h) -- equalisation gate (d)
    outage_forecast_confidence: Optional[float] = None
    heartbeat_ack_age_s: float = 0.0  # seconds since the charger last ack'd a heartbeat


@dataclass(frozen=True)
class PolicyState:
    phase: ChargePhase = ChargePhase.IDLE
    phase_started_s: float = 0.0
    equalise_planned_duration_h: float = 0.0
    last_equalise_end_s: Optional[float] = None
    quarter_start_s: float = 0.0
    quarter_equalise_hours: float = 0.0

    @staticmethod
    def initial(t0: float = 0.0) -> "PolicyState":
        return PolicyState(phase_started_s=t0, quarter_start_s=t0)


# --- wire-encodable command dataclasses (Embedded SKU only) ---


@dataclass(frozen=True)
class SetFloatCmd:
    mv_per_cell: int

    def to_frame(self) -> bytes:
        return frames.encode_set_float(self.mv_per_cell)


@dataclass(frozen=True)
class SetAbsorptionCmd:
    mv_per_cell: int
    timeout_min: int

    def to_frame(self) -> bytes:
        return frames.encode_set_absorption(self.mv_per_cell, self.timeout_min)


@dataclass(frozen=True)
class SetEqualiseCmd:
    mv_per_cell: int
    duration_min: int
    enable: bool

    def to_frame(self) -> bytes:
        return frames.encode_set_equalise(self.mv_per_cell, self.duration_min, self.enable)


@dataclass(frozen=True)
class SetCurrentLimitCmd:
    pct: int

    def to_frame(self) -> bytes:
        return frames.encode_set_current_limit_pct(self.pct)


ChargerCommand = object  # union marker for readability; concrete types above


@dataclass(frozen=True)
class PolicyOutput:
    phase: ChargePhase
    float_v: float
    absorption_v: float
    equalise_v: float
    current_limit_pct: float
    charger_should_be_off: bool
    commands: Tuple[ChargerCommand, ...] = field(default_factory=tuple)
    advice: Tuple[str, ...] = field(default_factory=tuple)
    alerts: Tuple[str, ...] = field(default_factory=tuple)
    fault: bool = False
    state: PolicyState = field(default_factory=PolicyState)


# --------------------------------------------------------------------------
# Pure helper functions (unit-tested directly)
# --------------------------------------------------------------------------


def temp_compensated_v(v25_cell: float, coeff_cell_per_c: float, cells: int,
                        t_c: float, ceiling_v: float, floor_v: float) -> float:
    """V_target(T) = V_25 + coeff*(T-25), per cell, x cells, clamped."""
    v = cells * (v25_cell + coeff_cell_per_c * (t_c - 25.0))
    return min(max(v, floor_v), ceiling_v)


def current_limit_pct(t_c: float, cfg: ChargerConfig) -> float:
    """100 - 4*(T-45) % above 45C; 0 at/above the OFF threshold (58C)."""
    if t_c >= cfg.off_temp_c:
        return 0.0
    if t_c <= cfg.derate_start_c:
        return 100.0
    pct = 100.0 - cfg.derate_pct_per_c * (t_c - cfg.derate_start_c)
    return max(0.0, min(100.0, pct))


def absorption_timeout_hours(t_c: float, cfg: ChargerConfig) -> float:
    if t_c >= 25.0:
        return cfg.absorption_timeout_nominal_h
    extension = cfg.absorption_cold_extension_h_per_c * (25.0 - t_c)
    return min(cfg.absorption_timeout_nominal_h + extension, cfg.absorption_timeout_cold_max_h)


def c20_rate_a(cfg: ChargerConfig) -> float:
    return cfg.c20_ah / 20.0


def tail_current_threshold_a(cfg: ChargerConfig) -> float:
    return cfg.tail_current_pct_c20 / 100.0 * c20_rate_a(cfg)


def _forecast_predicts_outage(prob: Optional[float], conf: Optional[float], cfg: ChargerConfig) -> bool:
    if prob is None or conf is None:
        return False
    return prob > cfg.precharge_outage_prob_threshold and conf >= cfg.precharge_outage_conf_threshold


def precharge_requested(inp: PolicyInput, cfg: ChargerConfig) -> bool:
    return _forecast_predicts_outage(inp.outage_prob_h3, inp.outage_forecast_confidence, cfg)


def equalisation_gate_ok(inp: PolicyInput, state: PolicyState, cfg: ChargerConfig) -> bool:
    if state.last_equalise_end_s is None:
        days_since = math.inf
    else:
        days_since = (inp.t_s - state.last_equalise_end_s) / SECONDS_PER_DAY
    cond_a = days_since >= cfg.equalise_min_interval_days
    cond_b = inp.sulphation_signature
    cond_c = inp.t_batt_c < cfg.equalise_max_temp_c
    outage_soon = _forecast_predicts_outage(inp.outage_prob_h6, inp.outage_forecast_confidence, cfg)
    cond_d = not outage_soon
    cap_ok = state.quarter_equalise_hours < cfg.equalise_quarterly_cap_h
    return cond_a and cond_b and cond_c and cond_d and cap_ok


def _sensor_fault(inp: PolicyInput, cfg: ChargerConfig) -> bool:
    for v in (inp.v_batt, inp.i_batt, inp.t_batt_c):
        if v is None or math.isnan(v):
            return True
    if not (cfg.v_min_valid <= inp.v_batt <= cfg.v_max_valid):
        return True
    if not (cfg.t_min_valid <= inp.t_batt_c <= cfg.t_max_valid):
        return True
    if not (cfg.i_min_valid <= inp.i_batt <= cfg.i_max_valid):
        return True
    return False


def _heartbeat_lost(inp: PolicyInput, cfg: ChargerConfig) -> bool:
    return inp.heartbeat_ack_age_s is None or inp.heartbeat_ack_age_s > cfg.heartbeat_max_age_s


def _mv_per_cell(v_pack: float, cells: int) -> int:
    return int(round((v_pack / cells) * 1000.0))


def _quarter_rolled(inp: PolicyInput, state: PolicyState, cfg: ChargerConfig) -> PolicyState:
    if inp.t_s - state.quarter_start_s >= cfg.equalise_quarter_days * SECONDS_PER_DAY:
        return replace(state, quarter_start_s=inp.t_s, quarter_equalise_hours=0.0)
    return state


# --------------------------------------------------------------------------
# Main policy loop (design 03 Sec.3.2, evaluated every 60 s)
# --------------------------------------------------------------------------


def evaluate(inp: PolicyInput, state: PolicyState, cfg: ChargerConfig) -> PolicyOutput:
    state = _quarter_rolled(inp, state, cfg)

    float_v = temp_compensated_v(cfg.float_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                  cfg.cells_per_pack, inp.t_batt_c, cfg.ceiling_v, cfg.floor_v)
    absorption_v = temp_compensated_v(cfg.absorption_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                       cfg.cells_per_pack, inp.t_batt_c, cfg.ceiling_v, cfg.floor_v)
    equalise_v = temp_compensated_v(cfg.equalise_v_cell_25, cfg.temp_coeff_v_per_c_cell,
                                     cfg.cells_per_pack, inp.t_batt_c, cfg.ceiling_v, cfg.floor_v)

    # --- fault fallback: any NaN/out-of-range sensor or missing heartbeat ack ---
    if _sensor_fault(inp, cfg) or _heartbeat_lost(inp, cfg):
        return _fault_output(cfg, state, inp.t_s)

    cl_pct = current_limit_pct(inp.t_batt_c, cfg)
    off_thermal = inp.t_batt_c >= cfg.off_temp_c

    if off_thermal:
        new_state = replace(state, phase=ChargePhase.OFF_THERMAL, phase_started_s=inp.t_s)
        alerts = ("charger OFF: T_batt %.1fC >= %.1fC" % (inp.t_batt_c, cfg.off_temp_c),)
        cmds, advice = _emit(cfg, (SetCurrentLimitCmd(0),),
                              ("charger OFF (thermal): T_batt %.1fC" % inp.t_batt_c,))
        return PolicyOutput(phase=ChargePhase.OFF_THERMAL, float_v=float_v, absorption_v=absorption_v,
                             equalise_v=equalise_v, current_limit_pct=0.0, charger_should_be_off=True,
                             commands=cmds, advice=advice, alerts=alerts, fault=False, state=new_state)

    alerts = []

    # --- continuing an equalisation session ---
    if state.phase == ChargePhase.EQUALISE:
        elapsed_h = (inp.t_s - state.phase_started_s) / SECONDS_PER_HOUR
        abort = inp.t_batt_c > cfg.equalise_abort_temp_c
        done = elapsed_h >= state.equalise_planned_duration_h
        if abort or done:
            actual_h = min(elapsed_h, state.equalise_planned_duration_h)
            new_state = replace(state, phase=ChargePhase.FLOAT, phase_started_s=inp.t_s,
                                 last_equalise_end_s=inp.t_s,
                                 quarter_equalise_hours=state.quarter_equalise_hours + actual_h)
            alerts.append("equalisation aborted: T_batt %.1fC > %.1fC" % (inp.t_batt_c, cfg.equalise_abort_temp_c)
                          if abort else "equalisation complete (%.1fh)" % actual_h)
            cmds, advice = _emit(cfg, (SetFloatCmd(_mv_per_cell(float_v, cfg.cells_per_pack)),
                                       SetCurrentLimitCmd(int(round(cl_pct)))),
                                 ("switch to float %.2fV (equalisation ended: %s)"
                                  % (float_v, alerts[-1]),))
            return PolicyOutput(phase=ChargePhase.FLOAT, float_v=float_v, absorption_v=absorption_v,
                                 equalise_v=equalise_v, current_limit_pct=cl_pct, charger_should_be_off=False,
                                 commands=cmds, advice=advice, alerts=tuple(alerts), fault=False, state=new_state)
        remaining_min = max(0, int(round((state.equalise_planned_duration_h - elapsed_h) * 60.0)))
        cmds, advice = _emit(cfg, (SetEqualiseCmd(_mv_per_cell(equalise_v, cfg.cells_per_pack),
                                                   remaining_min, True),
                                   SetCurrentLimitCmd(int(round(cl_pct)))),
                             ("equalising at %.2fV, %d min remaining" % (equalise_v, remaining_min),))
        return PolicyOutput(phase=ChargePhase.EQUALISE, float_v=float_v, absorption_v=absorption_v,
                             equalise_v=equalise_v, current_limit_pct=cl_pct, charger_should_be_off=False,
                             commands=cmds, advice=advice, alerts=tuple(alerts), fault=False, state=state)

    # --- not currently charging: nothing to command ---
    if not inp.charging_requested or not inp.grid_ok:
        new_state = replace(state, phase=ChargePhase.IDLE, phase_started_s=inp.t_s)
        return PolicyOutput(phase=ChargePhase.IDLE, float_v=float_v, absorption_v=absorption_v,
                             equalise_v=equalise_v, current_limit_pct=cl_pct, charger_should_be_off=False,
                             commands=(), advice=(), alerts=(), fault=False, state=new_state)

    precharge = precharge_requested(inp, cfg)

    # --- equalisation start (only from a non-equalising, currently-charging state) ---
    if equalisation_gate_ok(inp, state, cfg):
        new_state = replace(state, phase=ChargePhase.EQUALISE, phase_started_s=inp.t_s,
                             equalise_planned_duration_h=cfg.equalise_duration_h)
        alerts.append("equalisation started: %.1fh planned" % cfg.equalise_duration_h)
        cmds, advice = _emit(cfg, (SetEqualiseCmd(_mv_per_cell(equalise_v, cfg.cells_per_pack),
                                                   int(round(cfg.equalise_duration_h * 60.0)), True),
                                   SetCurrentLimitCmd(int(round(cl_pct)))),
                             ("start equalisation at %.2fV for %.1fh" % (equalise_v, cfg.equalise_duration_h),))
        return PolicyOutput(phase=ChargePhase.EQUALISE, float_v=float_v, absorption_v=absorption_v,
                             equalise_v=equalise_v, current_limit_pct=cl_pct, charger_should_be_off=False,
                             commands=cmds, advice=advice, alerts=tuple(alerts), fault=False, state=new_state)

    # --- absorption / float state machine ---
    if state.phase != ChargePhase.ABSORPTION:
        soc_needs_charge = inp.soc is None or inp.soc < cfg.soc_full_enough
        if soc_needs_charge or precharge:
            new_phase = ChargePhase.ABSORPTION
            phase_started = inp.t_s
        else:
            new_phase = ChargePhase.FLOAT
            phase_started = state.phase_started_s if state.phase == ChargePhase.FLOAT else inp.t_s
    else:
        elapsed_h = (inp.t_s - state.phase_started_s) / SECONDS_PER_HOUR
        i_charge = max(inp.i_batt, 0.0)
        tail_reached = 0.0 < i_charge < tail_current_threshold_a(cfg)
        timed_out = elapsed_h >= absorption_timeout_hours(inp.t_batt_c, cfg)
        if precharge:
            # pre-charge: hold absorption / raise achieved SoC target (05 Sec.2.3, 03 Sec.3.2),
            # overriding the normal tail-current/timeout termination.
            new_phase = ChargePhase.ABSORPTION
            phase_started = state.phase_started_s
            alerts.append("pre-charge hold: absorption extended (P(outage,3h) above threshold)")
        elif tail_reached or timed_out:
            new_phase = ChargePhase.FLOAT
            phase_started = inp.t_s
            alerts.append("absorption terminated: %s" % ("tail current" if tail_reached else "timeout"))
        else:
            new_phase = ChargePhase.ABSORPTION
            phase_started = state.phase_started_s

    new_state = replace(state, phase=new_phase, phase_started_s=phase_started)

    if new_phase == ChargePhase.ABSORPTION:
        timeout_min = int(round(absorption_timeout_hours(inp.t_batt_c, cfg) * 60.0))
        cmds, advice = _emit(cfg, (SetAbsorptionCmd(_mv_per_cell(absorption_v, cfg.cells_per_pack), timeout_min),
                                   SetCurrentLimitCmd(int(round(cl_pct)))),
                             ("hold absorption at %.2fV (timeout %d min)" % (absorption_v, timeout_min),))
    else:
        cmds, advice = _emit(cfg, (SetFloatCmd(_mv_per_cell(float_v, cfg.cells_per_pack)),
                                   SetCurrentLimitCmd(int(round(cl_pct)))),
                             ("hold float at %.2fV" % float_v,))

    return PolicyOutput(phase=new_phase, float_v=float_v, absorption_v=absorption_v, equalise_v=equalise_v,
                         current_limit_pct=cl_pct, charger_should_be_off=False, commands=cmds, advice=advice,
                         alerts=tuple(alerts), fault=False, state=new_state)


def _emit(cfg: ChargerConfig, commands: Tuple[ChargerCommand, ...], advice_lines: Tuple[str, ...]
          ) -> Tuple[Tuple[ChargerCommand, ...], Tuple[str, ...]]:
    """SKU split (03 Sec.3 header): Embedded gets wire commands, Retrofit gets advice text
    for the identical setpoints, and no commands are emitted."""
    if cfg.sku_commandable:
        return commands, ()
    return (), advice_lines


def _fault_output(cfg: ChargerConfig, state: PolicyState, t_s: float) -> PolicyOutput:
    """Command/advise factory defaults: nominal (25C, no derating) setpoints, equalisation
    disabled, full current limit -- the safe baseline the hardware itself falls back to on
    heartbeat loss (03 Sec.1.2), issued proactively here because Sentinel's OWN fault
    (bad sensor reading or a missed heartbeat ack) is the trigger, not necessarily the
    charger's."""
    float_v = cfg.float_v_cell_25 * cfg.cells_per_pack
    absorption_v = cfg.absorption_v_cell_25 * cfg.cells_per_pack
    equalise_v = cfg.equalise_v_cell_25 * cfg.cells_per_pack
    new_state = replace(state, phase=ChargePhase.FAULT, phase_started_s=t_s)
    default_cmds = (
        SetFloatCmd(_mv_per_cell(float_v, cfg.cells_per_pack)),
        SetAbsorptionCmd(_mv_per_cell(absorption_v, cfg.cells_per_pack),
                          int(round(cfg.absorption_timeout_nominal_h * 60.0))),
        SetEqualiseCmd(_mv_per_cell(equalise_v, cfg.cells_per_pack), 0, False),
        SetCurrentLimitCmd(100),
    )
    default_advice = (
        "FAULT: sensor invalid or heartbeat ack missing -- factory defaults "
        "(float %.2fV, absorption %.2fV, equalise disabled, 100%% current limit)"
        % (float_v, absorption_v),
    )
    cmds, advice = _emit(cfg, default_cmds, default_advice)
    return PolicyOutput(phase=ChargePhase.FAULT, float_v=float_v, absorption_v=absorption_v,
                         equalise_v=equalise_v, current_limit_pct=100.0, charger_should_be_off=False,
                         commands=cmds, advice=advice, alerts=default_advice, fault=True, state=new_state)
