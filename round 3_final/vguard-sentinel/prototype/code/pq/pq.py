"""pq/pq.py -- Grid Shield power-quality analyser (design 07).

Processes a 4 kS/s mains-voltage sample stream (AMC1311-isolated divider on
the ESP32-S3 ADC, design 07 Sec 1 / 10 Sec 3) into:
  * half-cycle sliding RMS Urms(1/2), refreshed every zero crossing (~10 ms
    at 50 Hz) -- the IEC 61000-4-30 Class-S-permitted dip/swell method.
  * frequency from zero-crossing period timing over a rolling 10-cycle window.
  * THD from a 4-cycle (80 ms) FFT, harmonics 2..39 (see note below on the
    40th being Nyquist-limited at 4 kS/s / 50 Hz).
  * IEEE 1159 sag/swell/interruption classification with duration buckets.
  * a ~32 B PQEvent record (measured size documented below), a 1000-event
    circular buffer, and a monthly rollup.

Honesty (design 07 Sec 6): this is "IEC 61000-4-30 Class-S-like", never
Class A -- there is no certified PT/CT and no GPS/PTP time base here.
"""
from __future__ import annotations

import dataclasses
import math
import struct
from collections import deque
from typing import List, Optional

import numpy as np

# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class PQParams:
    fs_hz: float = 4000.0
    f_nominal: float = 50.0
    v_nominal: float = 230.0
    sag_pu: float = 0.9
    swell_pu: float = 1.1
    interruption_pu: float = 0.1
    hysteresis_pu: float = 0.02       # must recover past band by this margin to close an event
    freq_window_cycles: int = 10
    freq_dev_frac: float = 0.03       # +/-3% of f_nominal (CONTRACTS/design default)
    freq_hysteresis_frac: float = 0.005  # must recover below (freq_dev_frac - this) to close
    thd_window_cycles: int = 4
    thd_max_harmonic: int = 39        # 40th is exactly Nyquist at 4 kS/s / 50 Hz -- see README
    thd_excursion_pct: float = 8.0
    buffer_len: int = 1000


PQ_TYPE_SAG = 0
PQ_TYPE_SWELL = 1
PQ_TYPE_INTERRUPTION = 2
PQ_TYPE_FREQ_DEV = 3
PQ_TYPE_THD_EXCURSION = 4
PQ_TYPE_NAMES = {
    PQ_TYPE_SAG: "SAG", PQ_TYPE_SWELL: "SWELL", PQ_TYPE_INTERRUPTION: "INTERRUPTION",
    PQ_TYPE_FREQ_DEV: "FREQ_DEV", PQ_TYPE_THD_EXCURSION: "THD_EXCURSION",
}

# design 07 Sec 3 struct layout, natural C alignment: uint32 + uint8 (+3 pad)
# + float + uint32 + float + float + float = 28 B measured (the design doc
# says "~32 B"; 28 B is what `sizeof(struct PQEvent)` actually gives under
# standard x86-64/ARM alignment -- see pq/README.md).
_STRUCT_FMT = "<IB3xfIfff"
PQ_EVENT_STRUCT_SIZE = struct.calcsize(_STRUCT_FMT)


@dataclasses.dataclass
class PQEvent:
    ts_epoch_ms: int
    type: int
    magnitude_pu: float
    duration_ms: int
    pre_event_rms_V: float
    post_event_rms_V: float
    thd_pct: float = float("nan")

    @property
    def type_name(self) -> str:
        return PQ_TYPE_NAMES[self.type]

    def pack(self) -> bytes:
        return struct.pack(_STRUCT_FMT, self.ts_epoch_ms & 0xFFFFFFFF, self.type,
                            self.magnitude_pu, self.duration_ms, self.pre_event_rms_V,
                            self.post_event_rms_V,
                            0.0 if math.isnan(self.thd_pct) else self.thd_pct)

    @staticmethod
    def unpack(buf: bytes) -> "PQEvent":
        ts, typ, mag, dur, pre, post, thd = struct.unpack(_STRUCT_FMT, buf)
        return PQEvent(ts, typ, mag, dur, pre, post, thd)


def classify_duration_bucket(event_type: int, duration_s: float, f_nominal: float = 50.0) -> str:
    """IEEE 1159 duration bucket, design 07 Sec 2 table."""
    cycles = duration_s * f_nominal
    if event_type in (PQ_TYPE_SAG, PQ_TYPE_SWELL):
        if 0.5 <= cycles <= 30:
            return "instantaneous"
        if duration_s <= 3.0:
            return "momentary"
        if duration_s <= 60.0:
            return "temporary"
        return "sustained"
    if event_type == PQ_TYPE_INTERRUPTION:
        if duration_s <= 3.0:
            return "momentary"
        if duration_s <= 60.0:
            return "temporary"
        return "sustained"
    return "n/a"


# --------------------------------------------------------------------------- #
# Circular event buffer (design 07 Sec 4)
# --------------------------------------------------------------------------- #
class CircularEventBuffer:
    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self._buf: List[Optional[PQEvent]] = [None] * capacity
        self._head = -1   # index of most recently written slot
        self._count = 0

    def push(self, ev: PQEvent) -> None:
        self._head = (self._head + 1) % self.capacity
        self._buf[self._head] = ev
        self._count = min(self._count + 1, self.capacity)

    def to_list(self) -> List[PQEvent]:
        """Oldest-first."""
        if self._count < self.capacity:
            return [e for e in self._buf[: self._count] if e is not None]
        return [self._buf[(self._head + 1 + i) % self.capacity] for i in range(self.capacity)]

    def __len__(self):
        return self._count


# --------------------------------------------------------------------------- #
# Monthly rollup (design 07 Sec 5)
# --------------------------------------------------------------------------- #
def monthly_rollup(events: List[PQEvent]) -> dict:
    counts = {name: {"instantaneous": 0, "momentary": 0, "temporary": 0, "sustained": 0, "n/a": 0}
              for name in PQ_TYPE_NAMES.values()}
    worst_thd = 0.0
    n_freq_dev = 0
    for ev in events:
        bucket = classify_duration_bucket(ev.type, ev.duration_ms / 1000.0)
        counts[ev.type_name][bucket] += 1
        if not math.isnan(ev.thd_pct):
            worst_thd = max(worst_thd, ev.thd_pct)
        if ev.type == PQ_TYPE_FREQ_DEV:
            n_freq_dev += 1
    return dict(counts=counts, worst_thd_pct=worst_thd, n_freq_dev_events=n_freq_dev,
                n_total_events=len(events))


# --------------------------------------------------------------------------- #
# THD via 4-cycle block FFT (harmonic k lands exactly on FFT bin k*(N*f0/fs))
# --------------------------------------------------------------------------- #
def compute_thd(samples: np.ndarray, fs_hz: float, f_nominal: float, max_harmonic: int) -> float:
    n = len(samples)
    spec = np.fft.rfft(samples * np.ones(n))  # rectangular window, per IEC 61000-4-7 4-cycle block
    bin_per_harmonic = f_nominal * n / fs_hz   # samples chosen so this is an integer (see PQParams)
    k1 = int(round(bin_per_harmonic))
    if k1 <= 0 or k1 >= len(spec):
        return float("nan")
    fundamental = abs(spec[k1])
    if fundamental < 1e-9:
        return 0.0
    harmonics_sq = 0.0
    for h in range(2, max_harmonic + 1):
        kb = int(round(bin_per_harmonic * h))
        if kb >= len(spec):
            break
        harmonics_sq += abs(spec[kb]) ** 2
    return 100.0 * math.sqrt(harmonics_sq) / fundamental


# --------------------------------------------------------------------------- #
# Streaming processor
# --------------------------------------------------------------------------- #
class PQProcessor:
    """Call push_sample() once per ADC sample (4 kS/s). poll_event() drains
    the emitted-event queue (mirrors pq.c's pq_push_sample/pq_poll_event)."""

    def __init__(self, params: Optional[PQParams] = None, t0_ms: int = 0):
        self.p = params or PQParams()
        self.fs = self.p.fs_hz
        self.dt_ms = 1000.0 / self.fs
        self.t_ms = float(t0_ms)

        self._prev_sample = 0.0
        self._started = False
        self._half_cycle_samples: List[float] = []
        self._urms_half = self.p.v_nominal
        self._urms_half_ts_ms = self.t_ms

        # zero-crossing (rising) history for frequency
        self._rising_ts: deque = deque(maxlen=self.p.freq_window_cycles + 1)
        self._freq_hz = self.p.f_nominal

        # THD block buffer
        samples_per_cycle = self.fs / self.p.f_nominal
        self._thd_block_n = int(round(samples_per_cycle * self.p.thd_window_cycles))
        self._thd_buf: List[float] = []
        self._thd_pct = 0.0

        # sag/swell/interruption state machine
        self._in_event = False
        self._event_type = None
        self._event_start_ms = 0.0
        self._event_extreme_pu = 1.0
        self._pre_event_rms = self.p.v_nominal
        self._steady_rms_accum: List[float] = []

        # frequency-deviation state machine
        self._in_freq_event = False
        self._freq_event_start_ms = 0.0
        self._freq_event_extreme = self.p.f_nominal

        self._event_queue: List[PQEvent] = []
        self.buffer = CircularEventBuffer(self.p.buffer_len)

    # -- public API (mirrors pq.h) --------------------------------------- #
    def push_sample(self, v_sample: float) -> None:
        if not self._started:
            # No valid "previous sample" yet -- do not run zero-crossing
            # detection against the arbitrary init value (avoids a false
            # crossing when the stream happens to start at/near 0).
            self._started = True
            self._half_cycle_samples.append(v_sample)
            self._thd_buf.append(v_sample)
            self._prev_sample = v_sample
            self.t_ms += self.dt_ms
            return
        self._update_half_cycle_rms(v_sample)
        self._update_frequency(v_sample)
        self._update_thd(v_sample)
        self._prev_sample = v_sample
        self.t_ms += self.dt_ms

    def poll_event(self) -> Optional[PQEvent]:
        if self._event_queue:
            ev = self._event_queue.pop(0)
            self.buffer.push(ev)
            return ev
        return None

    # -- internals ---------------------------------------------------------- #
    def _emit(self, ev: PQEvent) -> None:
        self._event_queue.append(ev)

    def _update_half_cycle_rms(self, v: float) -> None:
        crossed = (self._prev_sample <= 0.0 < v) or (self._prev_sample >= 0.0 > v)
        self._half_cycle_samples.append(v)
        # A half cycle at f_nominal spans ~fs/(2*f_nominal) samples; guard
        # against a spurious "crossing" on the very first sample (which
        # starts exactly at 0) or on noise, which would otherwise finalise a
        # near-empty segment as a false near-zero RMS reading.
        half_cycle_n = self.fs / (2.0 * self.p.f_nominal)
        min_len = max(4, int(0.3 * half_cycle_n))
        max_len = int(2.0 * half_cycle_n)
        if crossed and len(self._half_cycle_samples) > min_len:
            seg = np.asarray(self._half_cycle_samples[:-1])  # samples of the completed half-cycle
            self._urms_half = float(np.sqrt(np.mean(seg ** 2)))
            self._urms_half_ts_ms = self.t_ms
            self._half_cycle_samples = [v]
            self._check_magnitude_event()
        elif len(self._half_cycle_samples) > max_len:
            # Stall watchdog: a full interruption (V ~ 0) never crosses zero,
            # so a real meter must force-evaluate a segment after waiting
            # ~2x the nominal half-cycle length with no crossing, or a
            # complete outage would never be detected/timed correctly.
            seg = np.asarray(self._half_cycle_samples)
            self._urms_half = float(np.sqrt(np.mean(seg ** 2)))
            self._urms_half_ts_ms = self.t_ms
            self._half_cycle_samples = []
            self._check_magnitude_event()

    def _update_frequency(self, v: float) -> None:
        rising = self._prev_sample <= 0.0 < v
        if rising:
            self._rising_ts.append(self.t_ms)
            if len(self._rising_ts) >= 2:
                periods = np.diff(np.asarray(self._rising_ts))
                avg_period_ms = float(np.mean(periods))
                if avg_period_ms > 1e-6:
                    self._freq_hz = 1000.0 / avg_period_ms
                    self._check_frequency_event()

    def _update_thd(self, v: float) -> None:
        self._thd_buf.append(v)
        if len(self._thd_buf) >= self._thd_block_n:
            block = np.asarray(self._thd_buf[: self._thd_block_n])
            thd = compute_thd(block, self.fs, self.p.f_nominal, self.p.thd_max_harmonic)
            if not math.isnan(thd):
                self._thd_pct = thd
                self._check_thd_event()
            self._thd_buf = self._thd_buf[self._thd_block_n:]

    def _check_magnitude_event(self) -> None:
        pu = self._urms_half / self.p.v_nominal
        if not self._in_event:
            if pu < self.p.interruption_pu:
                self._start_event(PQ_TYPE_INTERRUPTION, pu)
            elif pu < self.p.sag_pu:
                self._start_event(PQ_TYPE_SAG, pu)
            elif pu > self.p.swell_pu:
                self._start_event(PQ_TYPE_SWELL, pu)
            else:
                self._pre_event_rms = self._urms_half
        else:
            if self._event_type == PQ_TYPE_INTERRUPTION and pu >= self.p.interruption_pu:
                if pu < self.p.sag_pu:
                    self._event_type = PQ_TYPE_SAG  # escalated/recovered partway
                    self._event_extreme_pu = min(self._event_extreme_pu, pu)
                    return
            if self._event_type == PQ_TYPE_SAG and pu < self.p.interruption_pu:
                self._event_type = PQ_TYPE_INTERRUPTION
            self._event_extreme_pu = (min(self._event_extreme_pu, pu)
                                       if self._event_type in (PQ_TYPE_SAG, PQ_TYPE_INTERRUPTION)
                                       else max(self._event_extreme_pu, pu))
            recovered = self.p.sag_pu + self.p.hysteresis_pu <= pu <= self.p.swell_pu - self.p.hysteresis_pu
            if recovered:
                self._end_event(self._urms_half)

    def _start_event(self, etype: int, pu: float) -> None:
        self._in_event = True
        self._event_type = etype
        self._event_start_ms = self._urms_half_ts_ms
        self._event_extreme_pu = pu

    def _end_event(self, post_rms: float) -> None:
        duration_ms = max(0, int(round(self._urms_half_ts_ms - self._event_start_ms)))
        ev = PQEvent(
            ts_epoch_ms=int(round(self._event_start_ms)),
            type=self._event_type,
            magnitude_pu=self._event_extreme_pu,
            duration_ms=duration_ms,
            pre_event_rms_V=self._pre_event_rms,
            post_event_rms_V=post_rms,
            thd_pct=float("nan"),
        )
        self._emit(ev)
        self._in_event = False
        self._event_type = None
        self._pre_event_rms = post_rms

    def _check_frequency_event(self) -> None:
        dev = abs(self._freq_hz - self.p.f_nominal) / self.p.f_nominal
        if not self._in_freq_event:
            if dev > self.p.freq_dev_frac:
                self._in_freq_event = True
                self._freq_event_start_ms = self.t_ms
                self._freq_event_extreme = self._freq_hz
        else:
            if abs(self._freq_hz - self.p.f_nominal) > abs(self._freq_event_extreme - self.p.f_nominal):
                self._freq_event_extreme = self._freq_hz
            if dev <= self.p.freq_dev_frac - self.p.freq_hysteresis_frac:
                duration_ms = max(0, int(round(self.t_ms - self._freq_event_start_ms)))
                ev = PQEvent(
                    ts_epoch_ms=int(round(self._freq_event_start_ms)),
                    type=PQ_TYPE_FREQ_DEV,
                    magnitude_pu=self._freq_event_extreme / self.p.f_nominal,
                    duration_ms=duration_ms,
                    pre_event_rms_V=self.p.f_nominal,
                    post_event_rms_V=self._freq_hz,
                    thd_pct=float("nan"),
                )
                self._emit(ev)
                self._in_freq_event = False

    def _check_thd_event(self) -> None:
        if self._thd_pct > self.p.thd_excursion_pct:
            ev = PQEvent(
                ts_epoch_ms=int(round(self.t_ms)),
                type=PQ_TYPE_THD_EXCURSION,
                magnitude_pu=self._urms_half / self.p.v_nominal,
                duration_ms=int(round(1000.0 * self.p.thd_window_cycles / self.p.f_nominal)),
                pre_event_rms_V=self._urms_half,
                post_event_rms_V=self._urms_half,
                thd_pct=self._thd_pct,
            )
            self._emit(ev)

    # -- convenience read-outs -------------------------------------------- #
    @property
    def urms_half(self) -> float:
        return self._urms_half

    @property
    def frequency_hz(self) -> float:
        return self._freq_hz

    @property
    def thd_pct(self) -> float:
        return self._thd_pct


def run_processor_on_stream(samples: np.ndarray, params: Optional[PQParams] = None) -> List[PQEvent]:
    proc = PQProcessor(params)
    for v in samples:
        proc.push_sample(float(v))
    events = []
    while True:
        ev = proc.poll_event()
        if ev is None:
            break
        events.append(ev)
    return events
