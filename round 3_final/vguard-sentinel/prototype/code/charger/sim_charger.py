"""Simulated charger device -- host-side stand-in for the MCU/DAC bridge on the
other end of the UART link (design 03 Sec.1.2).

**Honesty note (see README "Honest limits"):** no real Indian inverter exposes
this interface today (03 Sec.0). This module is a *test double*: it speaks the
same ``charger/frames.py`` wire format Sentinel-Core would, enforces the same
hardware safety ceiling "independent of any software" that 03 Sec.1.1
describes (a comparator/zener clamp above 15.5 V -- modelled here as a
firmware-level NACK, since there is no literal analog clamp to simulate), and
drives a toy CC/CV/float battery model so ``policy.py``'s commands can be
exercised end-to-end in ``tests/test_charger.py`` without hardware. It is not
a validated model of any specific battery or charger IC.

Battery model: a small Thevenin equivalent (OCV(SoC) + R0 + one RC branch),
NOT the project's EKF (``ekf/``) -- deliberately, per the task spec, since
this is a plant model for the charger to regulate against, not a state
estimator under test.

Unlike ``policy.py`` (a pure decision function, per the project's
immutability rule), ``SimCharger`` is a small mutable class: it stands in for
a real hardware device, which genuinely has state that evolves as frames
arrive and time passes -- the same judgement call the project already makes
for ``ekf.py`` and the C ``ap_t``/``hl_t`` structs (mutation is the normal,
unavoidable idiom for a stateful device model / firmware object; the
immutability discipline applies to decision logic like ``policy.py``).

Python 3.9 compatible: no ``match``, no ``X | Y`` union syntax.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

from charger import frames

HEARTBEAT_TIMEOUT_S = 2.0  # 03 Sec.1.2: "<=2s period; on loss the charger reverts to factory defaults"
HARD_CEILING_V = 15.5      # 03 Sec.1.1 hardware ceiling, enforced here regardless of what is requested
CELLS_PER_PACK = 6

# Factory defaults (hardware-programmed on the charger MCU/DAC bridge -- numerically the
# same illustrative 25C nominal values as policy.ChargerConfig's defaults, documented as
# such rather than imported, since a real device's factory defaults live in its own
# firmware and don't depend on Sentinel's policy config).
FACTORY_FLOAT_V_CELL = 2.27
FACTORY_ABSORPTION_V_CELL = 2.435
FACTORY_EQUALISE_V_CELL = 2.54
FACTORY_CURRENT_LIMIT_PCT = 100


@dataclass(frozen=True)
class TheveninBattery:
    """Tiny 2nd-order Thevenin equivalent for a 12 V lead-acid pack: OCV(SoC) + series R0
    + one RC branch. Deliberately not the project's EKF plant model (ekf/) -- this is a
    charge-side plant for the simulated charger to regulate against, not a state estimator.
    Illustrative parameters, not fit to a measured cell.
    """

    capacity_ah: float = 150.0
    r0_ohm: float = 0.02
    r1_ohm: float = 0.01
    c1_farad: float = 4000.0   # tau = r1*c1 = 40 s
    soc: float = 0.5
    v1: float = 0.0            # RC branch state, V

    def ocv_v(self) -> float:
        # crude monotonic 6-cell OCV curve: 1.95 V/cell (empty) -> 2.15 V/cell (full)
        soc_c = max(0.0, min(1.0, self.soc))
        return CELLS_PER_PACK * (1.95 + 0.20 * soc_c)

    def step(self, i_charge_a: float, dt_s: float) -> Tuple["TheveninBattery", float]:
        """i_charge_a: + charging, - discharging (CONTRACTS.md Sec.1 convention).
        Returns (new_battery, terminal_voltage)."""
        tau = self.r1_ohm * self.c1_farad
        v1_new = self.v1 + dt_s * (i_charge_a * self.r1_ohm / tau - self.v1 / tau) if tau > 0 else self.v1
        v_term = self.ocv_v() + i_charge_a * self.r0_ohm + v1_new
        soc_new = self.soc + (i_charge_a * dt_s / 3600.0) / self.capacity_ah
        soc_new = max(0.0, min(1.0, soc_new))
        return replace(self, soc=soc_new, v1=v1_new), v_term


class SimCharger:
    """Simulated charger MCU/DAC bridge. Accepts decoded (cmd, payload) frames (feed raw
    bytes via ``feed_bytes``), enforces the 15.5 V hard ceiling on any voltage setpoint
    (NACK on violation), applies accepted setpoints to a toy CC/CV/float model, and
    reverts to factory defaults if no heartbeat is seen for > 2 s.
    """

    def __init__(self, battery: Optional[TheveninBattery] = None, t0: float = 0.0, t_batt_c: float = 25.0):
        self.battery = battery if battery is not None else TheveninBattery()
        self.t_now = t0
        self.battery_t_c = t_batt_c
        self.last_heartbeat_t: Optional[float] = None
        self.last_heartbeat_seq = 0
        self.mode = frames.STATUS_MODE_FLOAT
        self.float_mv = int(round(FACTORY_FLOAT_V_CELL * 1000))
        self.absorption_mv = int(round(FACTORY_ABSORPTION_V_CELL * 1000))
        self.absorption_timeout_min = 180
        self.equalise_mv = int(round(FACTORY_EQUALISE_V_CELL * 1000))
        self.equalise_duration_min = 0
        self.equalise_enabled = False
        self.current_limit_pct = FACTORY_CURRENT_LIMIT_PCT
        self.fault_flags = 0
        self.last_v_term = self.battery.ocv_v()
        self._last_i_charge = 0.0
        self._parser = frames.FrameParser()

    # ---- factory reset -----------------------------------------------------

    def revert_to_factory_defaults(self) -> None:
        self.mode = frames.STATUS_MODE_FLOAT
        self.float_mv = int(round(FACTORY_FLOAT_V_CELL * 1000))
        self.absorption_mv = int(round(FACTORY_ABSORPTION_V_CELL * 1000))
        self.absorption_timeout_min = 180
        self.equalise_mv = int(round(FACTORY_EQUALISE_V_CELL * 1000))
        self.equalise_duration_min = 0
        self.equalise_enabled = False
        self.current_limit_pct = FACTORY_CURRENT_LIMIT_PCT
        self.fault_flags |= frames.FAULT_FLAG_HEARTBEAT_LOST

    def _pack_v(self, mv_per_cell: int) -> float:
        return mv_per_cell * CELLS_PER_PACK / 1000.0

    def _over_ceiling(self, mv_per_cell: int) -> bool:
        return self._pack_v(mv_per_cell) > HARD_CEILING_V + 1e-6

    # ---- frame handling ------------------------------------------------

    def process_frame(self, cmd: int, payload: bytes) -> Optional[bytes]:
        """Process one decoded frame. Returns response frame bytes (NACK or a
        GET_STATUS reply), or None if the command was accepted silently
        (the design's command table has no explicit ACK for a valid SET_*)."""
        if cmd == frames.CMD_SET_FLOAT:
            mv = frames.decode_set_float(payload)
            if self._over_ceiling(mv):
                return frames.encode_nack(frames.NACK_RANGE_ERROR)
            self.float_mv = mv
            if self.mode not in (frames.STATUS_MODE_ABSORPTION, frames.STATUS_MODE_EQUALISE):
                self.mode = frames.STATUS_MODE_FLOAT
            return None

        if cmd == frames.CMD_SET_ABSORPTION:
            mv, timeout_min = frames.decode_set_absorption(payload)
            if self._over_ceiling(mv):
                return frames.encode_nack(frames.NACK_RANGE_ERROR)
            self.absorption_mv = mv
            self.absorption_timeout_min = timeout_min
            self.mode = frames.STATUS_MODE_ABSORPTION
            return None

        if cmd == frames.CMD_SET_EQUALISE:
            mv, duration_min, enable = frames.decode_set_equalise(payload)
            if enable and self._over_ceiling(mv):
                return frames.encode_nack(frames.NACK_RANGE_ERROR)
            self.equalise_mv = mv
            self.equalise_duration_min = duration_min
            self.equalise_enabled = enable
            self.mode = frames.STATUS_MODE_EQUALISE if enable else frames.STATUS_MODE_FLOAT
            return None

        if cmd == frames.CMD_SET_CURRENT_LIMIT_PCT:
            pct = frames.decode_set_current_limit_pct(payload)
            if pct > 100:
                return frames.encode_nack(frames.NACK_RANGE_ERROR)
            self.current_limit_pct = pct
            return None

        if cmd == frames.CMD_SET_TEMP_COMP:
            frames.decode_set_temp_comp(payload)  # accepted, informational only in this sim
            return None

        if cmd == frames.CMD_HEARTBEAT:
            seq = frames.decode_heartbeat(payload)
            self.last_heartbeat_seq = seq
            self.last_heartbeat_t = self.t_now
            self.fault_flags &= ~frames.FAULT_FLAG_HEARTBEAT_LOST
            return None

        if cmd == frames.CMD_GET_STATUS:
            return frames.encode_status(self.mode, self.fault_flags, self.last_v_term,
                                         self._last_i_charge, self.battery_t_c)

        return frames.encode_nack(frames.NACK_UNKNOWN_CMD)

    def feed_bytes(self, data: bytes) -> List[bytes]:
        """Feed raw UART bytes; returns any response frames (NACK / GET_STATUS reply)."""
        responses = []
        for cmd, payload in self._parser.feed(data):
            resp = self.process_frame(cmd, payload)
            if resp is not None:
                responses.append(resp)
        return responses

    # ---- electrical model tick ------------------------------------------

    def _target_voltage(self) -> float:
        if self.mode == frames.STATUS_MODE_EQUALISE and self.equalise_enabled:
            return self._pack_v(self.equalise_mv)
        if self.mode == frames.STATUS_MODE_ABSORPTION:
            return self._pack_v(self.absorption_mv)
        return self._pack_v(self.float_mv)

    def _max_charge_current_a(self) -> float:
        base_a = 0.2 * self.battery.capacity_ah  # illustrative ~C5 max bulk rate
        return base_a * (self.current_limit_pct / 100.0)

    def tick(self, t_now: float, dt_s: float) -> float:
        """Advance the simulated device/battery by dt_s. Returns the new terminal
        voltage. Must be called at a cadence fast enough to catch heartbeat loss
        (the model only reverts to factory defaults at the tick where the > 2 s
        threshold is actually crossed)."""
        self.t_now = t_now
        if self.last_heartbeat_t is not None and (t_now - self.last_heartbeat_t) > HEARTBEAT_TIMEOUT_S:
            self.revert_to_factory_defaults()

        target_v = self._target_voltage()
        max_i = self._max_charge_current_a()
        v_err = target_v - self.last_v_term
        kp_a_per_v = 50.0  # aggressive proportional gain -- sim convergence aid, not a real controller
        i_cmd = max(0.0, min(max_i, v_err * kp_a_per_v))

        self.battery, v_term = self.battery.step(i_cmd, dt_s)
        self.last_v_term = v_term
        self._last_i_charge = i_cmd
        return v_term

    def get_status_payload(self) -> dict:
        return {
            "mode": self.mode,
            "fault_flags": self.fault_flags,
            "v_batt_v": self.last_v_term,
            "i_batt_a": self._last_i_charge,
            "t_batt_c": self.battery_t_c,
            "soc": self.battery.soc,
        }
