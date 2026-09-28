"""UART frame codec for the Sentinel-Core <-> charger-MCU link — Python reference.

Implements design doc ``03-Adaptive-Charging-and-Charger-Interface.md`` Sec.1.2
verbatim for the framing shape:

    [SOF 0xAA][CMD][LEN][PAYLOAD...][CRC16_L][CRC16_H][EOF 0x55]

115200-8N1, byte-stuffed, CRC-16/CCITT. Must produce byte-identical frames to
``frames.c`` for the same command (checked in ``tests/test_charger.py`` via
subprocess against ``test_frames_host``, skipped if gcc is unavailable).

Interpretive decisions not pinned down by the design doc (documented here and
in ``README.md`` "Honest limits", per project convention — see e.g.
``autopilot/README.md``):

  * **Byte order.** The design doc doesn't state endianness for multi-byte
    payload fields. The framing byte order is unambiguous ("[CRC16_L]
    [CRC16_H]" — low byte first, i.e. little-endian for the CRC), so every
    multi-byte payload field here is little-endian too, for internal
    consistency.
  * **Voltage payload units.** The design doc's table gives SET_FLOAT's
    payload as "uint16 (mV/cell x100)" but SET_ABSORPTION / SET_EQUALISE as
    plain "uint16 mV/cell" with no x100. Taking "x100" literally on
    SET_FLOAT alone would need up to ~227,000 for a 2.27 V/cell setpoint,
    which overflows a uint16 (max 65535) — inconsistent with the other two
    commands and not representable in the stated type. We treat "x100" as a
    documentation artifact and encode all three voltage fields identically:
    **whole millivolts per cell, uint16, 1 mV resolution** (max 65.535
    V/cell, far more than any lead-acid setpoint needs). This is the only
    reading that is self-consistent across 0x10/0x11/0x12 and fits the
    declared wire type.
  * **Byte stuffing.** The doc says "byte-stuffed" but not the algorithm.
    We use the standard PPP/HDLC-style scheme: SOF (0xAA), EOF (0x55) and
    the escape byte itself (0x7D) are escaped as ESC + (byte ^ 0x20)
    whenever they occur in the CMD/LEN/PAYLOAD/CRC region; SOF/EOF are only
    ever literal at the very start/end of a frame. This is a well-known,
    testable, resync-friendly construction, not an invented one-off.
  * **CRC variant.** "CRC-16/CCITT" is implemented as CRC-16/CCITT-FALSE:
    poly 0x1021, init 0xFFFF, no reflection, no final XOR — the most common
    concrete meaning of that name in embedded UART protocols.
  * **GET_STATUS / NACK payload shapes** are this module's own choice (the
    design doc says "mode, fault flags, V_batt, I_batt if sensed" for
    GET_STATUS and "uint8 code" for NACK without pinning exact field
    widths); see ``decode_status``/``STATUS_MODE_*`` below.

Python 3.9 compatible: no ``match``, no ``X | Y`` union syntax.
"""

from __future__ import annotations

import struct
from typing import List, Optional, Tuple

# --------------------------------------------------------------------------
# Framing constants (design 03 Sec.1.2)
# --------------------------------------------------------------------------

SOF = 0xAA
EOF = 0x55
ESC = 0x7D
ESC_XOR = 0x20

CMD_SET_FLOAT = 0x10
CMD_SET_ABSORPTION = 0x11
CMD_SET_EQUALISE = 0x12
CMD_SET_CURRENT_LIMIT_PCT = 0x13
CMD_SET_TEMP_COMP = 0x14
CMD_GET_STATUS = 0x20
CMD_HEARTBEAT = 0x30
CMD_NACK = 0x7F

CMD_NAMES = {
    CMD_SET_FLOAT: "SET_FLOAT",
    CMD_SET_ABSORPTION: "SET_ABSORPTION",
    CMD_SET_EQUALISE: "SET_EQUALISE",
    CMD_SET_CURRENT_LIMIT_PCT: "SET_CURRENT_LIMIT_PCT",
    CMD_SET_TEMP_COMP: "SET_TEMP_COMP",
    CMD_GET_STATUS: "GET_STATUS",
    CMD_HEARTBEAT: "HEARTBEAT",
    CMD_NACK: "NACK",
}

# GET_STATUS response payload (this module's own layout — see docstring)
STATUS_MODE_OFF = 0
STATUS_MODE_BULK = 1
STATUS_MODE_ABSORPTION = 2
STATUS_MODE_FLOAT = 3
STATUS_MODE_EQUALISE = 4

FAULT_FLAG_SENSOR = 0x01
FAULT_FLAG_HEARTBEAT_LOST = 0x02

# NACK codes
NACK_CRC_ERROR = 0
NACK_RANGE_ERROR = 1
NACK_UNKNOWN_CMD = 2
NACK_BUSY = 3

MAX_PAYLOAD_LEN = 255
# Guard against unbounded buffering on a corrupt/never-terminated stream.
MAX_STUFFED_BODY_LEN = 4 * (2 + MAX_PAYLOAD_LEN + 2)


class FrameError(Exception):
    """Raised only for programmer errors (bad arguments to encoders); the
    streaming parser never raises on malformed wire data — see FrameParser."""


# --------------------------------------------------------------------------
# CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflect, no xorout)
# --------------------------------------------------------------------------

def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


# --------------------------------------------------------------------------
# Byte stuffing (PPP/HDLC-style, see module docstring)
# --------------------------------------------------------------------------

def stuff(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b == SOF or b == EOF or b == ESC:
            out.append(ESC)
            out.append(b ^ ESC_XOR)
        else:
            out.append(b)
    return bytes(out)


def unstuff(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == ESC:
            i += 1
            if i >= n:
                raise FrameError("truncated escape sequence")
            out.append(data[i] ^ ESC_XOR)
        else:
            out.append(b)
        i += 1
    return bytes(out)


# --------------------------------------------------------------------------
# Frame encode
# --------------------------------------------------------------------------

def encode_frame(cmd: int, payload: bytes = b"") -> bytes:
    if not (0 <= cmd <= 0xFF):
        raise FrameError("cmd out of range 0-255: %r" % (cmd,))
    if len(payload) > MAX_PAYLOAD_LEN:
        raise FrameError("payload too long (%d > %d)" % (len(payload), MAX_PAYLOAD_LEN))
    body = bytes([cmd & 0xFF, len(payload) & 0xFF]) + bytes(payload)
    crc = crc16_ccitt(body)
    body_crc = body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])  # CRC16_L, CRC16_H
    return bytes([SOF]) + stuff(body_crc) + bytes([EOF])


def encode_set_float(mv_per_cell: int) -> bytes:
    return encode_frame(CMD_SET_FLOAT, struct.pack("<H", mv_per_cell & 0xFFFF))


def encode_set_absorption(mv_per_cell: int, timeout_min: int) -> bytes:
    return encode_frame(CMD_SET_ABSORPTION, struct.pack("<HH", mv_per_cell & 0xFFFF, timeout_min & 0xFFFF))


def encode_set_equalise(mv_per_cell: int, duration_min: int, enable: bool) -> bytes:
    return encode_frame(
        CMD_SET_EQUALISE,
        struct.pack("<HHB", mv_per_cell & 0xFFFF, duration_min & 0xFFFF, 1 if enable else 0),
    )


def encode_set_current_limit_pct(pct: int) -> bytes:
    if not (0 <= pct <= 100):
        raise FrameError("current limit pct out of range 0-100: %r" % (pct,))
    return encode_frame(CMD_SET_CURRENT_LIMIT_PCT, struct.pack("<B", pct))


def encode_set_temp_comp(uv_per_c_per_cell: int) -> bytes:
    return encode_frame(CMD_SET_TEMP_COMP, struct.pack("<h", uv_per_c_per_cell))


def encode_get_status() -> bytes:
    return encode_frame(CMD_GET_STATUS, b"")


def encode_heartbeat(seq: int) -> bytes:
    return encode_frame(CMD_HEARTBEAT, struct.pack("<I", seq & 0xFFFFFFFF))


def encode_nack(code: int) -> bytes:
    return encode_frame(CMD_NACK, struct.pack("<B", code & 0xFF))


def encode_status(mode: int, fault_flags: int, v_batt_v: float, i_batt_a: float, t_batt_c: float) -> bytes:
    v_cv = int(round(v_batt_v * 100.0))
    i_ca = int(round(i_batt_a * 100.0))
    t_dc = int(round(t_batt_c * 10.0))
    payload = struct.pack("<BBHhh", mode & 0xFF, fault_flags & 0xFF, v_cv & 0xFFFF, i_ca, t_dc)
    return encode_frame(CMD_GET_STATUS, payload)


# --------------------------------------------------------------------------
# Payload decode helpers (host side)
# --------------------------------------------------------------------------

def decode_set_float(payload: bytes) -> int:
    return struct.unpack("<H", payload)[0]


def decode_set_absorption(payload: bytes) -> Tuple[int, int]:
    return struct.unpack("<HH", payload)


def decode_set_equalise(payload: bytes) -> Tuple[int, int, bool]:
    mv, dur, en = struct.unpack("<HHB", payload)
    return mv, dur, bool(en)


def decode_set_current_limit_pct(payload: bytes) -> int:
    return struct.unpack("<B", payload)[0]


def decode_set_temp_comp(payload: bytes) -> int:
    return struct.unpack("<h", payload)[0]


def decode_heartbeat(payload: bytes) -> int:
    return struct.unpack("<I", payload)[0]


def decode_nack(payload: bytes) -> int:
    return struct.unpack("<B", payload)[0]


def decode_status(payload: bytes) -> dict:
    mode, fault_flags, v_cv, i_ca, t_dc = struct.unpack("<BBHhh", payload)
    return {
        "mode": mode,
        "fault_flags": fault_flags,
        "v_batt_v": v_cv / 100.0,
        "i_batt_a": i_ca / 100.0,
        "t_batt_c": t_dc / 10.0,
    }


def frame_to_hex(frame: bytes) -> str:
    return frame.hex().upper()


# --------------------------------------------------------------------------
# Streaming parser -- resync on bad CRC (design 03 Sec.1.2 "the frame codec")
# --------------------------------------------------------------------------

class FrameParser:
    """Byte-at-a-time streaming parser.

    Feed it bytes as they arrive (``feed()`` returns any complete, valid
    frames found in that call as a list of ``(cmd, payload)`` tuples).
    Malformed frames (bad CRC, truncated escape, bad length) are silently
    dropped and the parser resynchronises on the next SOF -- it never
    raises on wire data, matching a real UART receiver that cannot afford
    to throw an exception on line noise. Garbage bytes before the first
    SOF, or a stray SOF that interrupts an in-progress frame, are also
    absorbed cleanly (the interrupted frame is discarded, a fresh one
    starts at the new SOF).
    """

    def __init__(self):
        self._buf = bytearray()
        self._in_frame = False

    def reset(self) -> None:
        self._buf = bytearray()
        self._in_frame = False

    def feed(self, data: bytes) -> List[Tuple[int, bytes]]:
        out = []
        for byte in data:
            if not self._in_frame:
                if byte == SOF:
                    self._in_frame = True
                    self._buf = bytearray()
                # else: not synchronised yet -- discard and keep looking for SOF
                continue
            if byte == SOF:
                # a fresh SOF before we saw EOF: the frame in progress is
                # garbage (dropped mid-stream, or two frames collided) --
                # resync onto this new one rather than accumulating both.
                self._buf = bytearray()
                continue
            if byte == EOF:
                frame = self._try_parse(bytes(self._buf))
                self._in_frame = False
                self._buf = bytearray()
                if frame is not None:
                    out.append(frame)
                continue
            self._buf.append(byte)
            if len(self._buf) > MAX_STUFFED_BODY_LEN:
                # runaway frame (missing EOF) -- give up and resync
                self._in_frame = False
                self._buf = bytearray()
        return out

    @staticmethod
    def _try_parse(stuffed_body: bytes) -> Optional[Tuple[int, bytes]]:
        try:
            body = unstuff(stuffed_body)
        except FrameError:
            return None
        if len(body) < 4:
            return None
        cmd = body[0]
        ln = body[1]
        if len(body) != 2 + ln + 2:
            return None
        payload = body[2:2 + ln]
        crc_lo = body[2 + ln]
        crc_hi = body[2 + ln + 1]
        crc_rx = crc_lo | (crc_hi << 8)
        crc_calc = crc16_ccitt(body[:2 + ln])
        if crc_rx != crc_calc:
            return None
        return cmd, payload


def parse_all(data: bytes) -> List[Tuple[int, bytes]]:
    """Convenience one-shot parse of a complete byte string."""
    return FrameParser().feed(data)
