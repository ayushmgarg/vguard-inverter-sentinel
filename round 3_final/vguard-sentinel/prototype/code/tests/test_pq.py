"""tests/test_pq.py -- Grid Shield power-quality analyser tests (design 07)
on a synthetic 230 V / 50 Hz waveform at 4 kS/s.

Covers:
  * injected dips at 70%, 40%, 0% (interruption) depth over 0.5-250 cycles
    -- detection rate for dips >= 1 cycle, magnitude error, duration error,
       IEEE 1159 bucket correctness
  * swells (>1.1 pu)
  * a 3% frequency deviation
  * 5% THD (single injected harmonic, exact expected value)
  * C analyser matches the Python port on an identical waveform (subprocess;
    skipped if gcc is unavailable)

Numbers are printed with `pytest -q -s tests/test_pq.py`.
"""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from pq.pq import (PQParams, PQ_TYPE_SAG, PQ_TYPE_SWELL, PQ_TYPE_INTERRUPTION,
                    PQ_TYPE_FREQ_DEV, run_processor_on_stream, classify_duration_bucket,
                    compute_thd)

ROOT = Path(__file__).resolve().parent.parent
PQ_DIR = ROOT / "pq"
HAS_GCC = shutil.which("gcc") is not None

FS = 4000.0
F0 = 50.0
VRMS = 230.0
VPK = VRMS * math.sqrt(2.0)


def _make_dip_waveform(depth_frac: float, dur_cycles: float, start_s: float = 0.5,
                        tail_s: float = 1.0) -> np.ndarray:
    dur_s = dur_cycles / F0
    total_s = start_s + dur_s + tail_s
    t = np.arange(int(round(total_s * FS))) / FS
    v = VPK * np.sin(2 * np.pi * F0 * t)
    mask = (t >= start_s) & (t < start_s + dur_s)
    v[mask] *= depth_frac
    return v


DIP_CASES = [
    # (label, depth_frac, expected_event_type, duration_cycles)
    ("sag70_0.5c", 0.70, PQ_TYPE_SAG, 0.5),
    ("sag70_1c", 0.70, PQ_TYPE_SAG, 1.0),
    ("sag70_10c", 0.70, PQ_TYPE_SAG, 10.0),
    ("sag70_30c", 0.70, PQ_TYPE_SAG, 30.0),
    ("sag70_100c", 0.70, PQ_TYPE_SAG, 100.0),
    ("sag40_1c", 0.40, PQ_TYPE_SAG, 1.0),
    ("sag40_10c", 0.40, PQ_TYPE_SAG, 10.0),
    ("sag40_30c", 0.40, PQ_TYPE_SAG, 30.0),
    ("sag40_100c", 0.40, PQ_TYPE_SAG, 100.0),
    ("sag40_250c", 0.40, PQ_TYPE_SAG, 250.0),
    ("interrupt_1c", 0.0, PQ_TYPE_INTERRUPTION, 1.0),
    ("interrupt_10c", 0.0, PQ_TYPE_INTERRUPTION, 10.0),
    ("interrupt_100c", 0.0, PQ_TYPE_INTERRUPTION, 100.0),
    ("interrupt_250c", 0.0, PQ_TYPE_INTERRUPTION, 250.0),
]


def test_dip_detection_rate_and_accuracy():
    detected_ge1cycle = 0
    total_ge1cycle = 0
    mag_errors = []
    dur_errors_half_cycles = []
    bucket_ok = 0
    bucket_total = 0

    for label, depth, expected_type, cycles in DIP_CASES:
        v = _make_dip_waveform(depth, cycles)
        events = run_processor_on_stream(v, PQParams(fs_hz=FS, f_nominal=F0, v_nominal=VRMS))
        mag_events = [e for e in events if e.type in (PQ_TYPE_SAG, PQ_TYPE_INTERRUPTION, PQ_TYPE_SWELL)]

        is_ge1 = cycles >= 1.0
        if is_ge1:
            total_ge1cycle += 1

        if not mag_events:
            print(f"[PQ] {label}: NOT DETECTED")
            continue

        # pick the event with the most extreme magnitude (the injected dip)
        ev = min(mag_events, key=lambda e: e.magnitude_pu) if depth < 1.0 else mag_events[0]
        detected_type_ok = ev.type == expected_type

        if is_ge1:
            detected_ge1cycle += 1

        mag_err_pct = abs(ev.magnitude_pu - depth) * 100.0
        mag_errors.append(mag_err_pct)

        expected_dur_s = cycles / F0
        dur_err_s = abs(ev.duration_ms / 1000.0 - expected_dur_s)
        half_cycle_s = 1.0 / (2.0 * F0)
        dur_errors_half_cycles.append(dur_err_s / half_cycle_s)

        bucket = classify_duration_bucket(ev.type, ev.duration_ms / 1000.0)
        expected_bucket = classify_duration_bucket(expected_type, expected_dur_s)
        bucket_total += 1
        if bucket == expected_bucket:
            bucket_ok += 1

        print(f"[PQ] {label}: type_ok={detected_type_ok} mag={ev.magnitude_pu:.3f} "
              f"(expected {depth:.2f}, err={mag_err_pct:.2f}%) dur={ev.duration_ms}ms "
              f"(expected {expected_dur_s*1000:.1f}ms) bucket={bucket} (expected {expected_bucket})")

    detection_rate = detected_ge1cycle / total_ge1cycle if total_ge1cycle else 0.0
    mean_mag_err = float(np.mean(mag_errors)) if mag_errors else float("nan")
    max_mag_err = float(np.max(mag_errors)) if mag_errors else float("nan")
    mean_dur_err_hc = float(np.mean(dur_errors_half_cycles)) if dur_errors_half_cycles else float("nan")
    max_dur_err_hc = float(np.max(dur_errors_half_cycles)) if dur_errors_half_cycles else float("nan")
    bucket_acc = bucket_ok / bucket_total if bucket_total else 0.0

    print(f"\n[PQ] SUMMARY: detection_rate(>=1 cycle)={detection_rate:.3f} "
          f"({detected_ge1cycle}/{total_ge1cycle}) mean_mag_err={mean_mag_err:.2f}% "
          f"max_mag_err={max_mag_err:.2f}% mean_dur_err={mean_dur_err_hc:.2f} half-cycles "
          f"max_dur_err={max_dur_err_hc:.2f} half-cycles bucket_accuracy={bucket_acc:.3f}")

    assert detection_rate >= 0.99, f"detection rate too low: {detection_rate:.3f}"
    assert max_mag_err <= 2.0, f"magnitude error too high: {max_mag_err:.2f}%"
    assert max_dur_err_hc <= 1.0, f"duration error too high: {max_dur_err_hc:.2f} half-cycles"
    assert bucket_acc >= 0.95, f"IEEE 1159 bucket accuracy too low: {bucket_acc:.3f}"


def test_swell_detection():
    v = _make_dip_waveform(1.25, 20.0)  # "dip" helper reused: 1.25x = a swell
    events = run_processor_on_stream(v, PQParams(fs_hz=FS, f_nominal=F0, v_nominal=VRMS))
    swells = [e for e in events if e.type == PQ_TYPE_SWELL]
    print(f"\n[PQ] swell: {[(round(e.magnitude_pu,3), e.duration_ms) for e in swells]}")
    assert len(swells) == 1
    assert abs(swells[0].magnitude_pu - 1.25) < 0.03
    assert abs(swells[0].duration_ms - 400) <= 20  # 20 cycles = 400 ms


def test_frequency_deviation():
    # design 07 Sec 1 flags outside 50 Hz +/- 3%; inject a clear 3.5% step so
    # the test isn't sitting exactly on the threshold (CONTRACTS-style
    # "measured numbers" honesty: a dead-on-threshold injection would be
    # measuring float noise, not the detector).
    dur_s = 2.0
    t = np.arange(int(dur_s * FS)) / FS
    freq = np.where((t >= 0.5) & (t < 1.5), F0 * 1.035, F0)  # +3.5% for 1 s
    phase = 2 * np.pi * np.cumsum(freq) / FS
    v = VPK * np.sin(phase)
    events = run_processor_on_stream(v, PQParams(fs_hz=FS, f_nominal=F0, v_nominal=VRMS))
    freq_events = [e for e in events if e.type == PQ_TYPE_FREQ_DEV]
    print(f"\n[PQ] freq deviation events: "
          f"{[(round(e.magnitude_pu,4), e.duration_ms) for e in freq_events]}")
    assert len(freq_events) == 1, f"expected one continuous deviation event, got {len(freq_events)}"
    best = freq_events[0]
    assert abs(best.magnitude_pu - 1.035) < 0.01
    assert abs(best.duration_ms - 1000) <= 250  # rolling 10-cycle window adds edge lag


def test_thd_measurement():
    dur_s = 0.5
    t = np.arange(int(dur_s * FS)) / FS
    v = VPK * np.sin(2 * np.pi * F0 * t) + 0.05 * VPK * np.sin(2 * np.pi * 5 * F0 * t)
    thd = compute_thd(v[:320], FS, F0, 39)
    print(f"\n[PQ] THD measurement: {thd:.3f}% (injected 5.000%)")
    assert abs(thd - 5.0) <= 1.0


# --------------------------------------------------------------------------- #
# C parity
# --------------------------------------------------------------------------- #
def _build_c_binaries():
    subprocess.run(["make", "-C", str(PQ_DIR)], check=True, capture_output=True)


def _round_trip(v: np.ndarray) -> np.ndarray:
    """Round through the same %.6f text both implementations are fed, so
    both see bit-identical input (fair parity check, not a precision test)."""
    return np.array([float(f"{x:.6f}") for x in v])


@pytest.mark.skipif(not HAS_GCC, reason="gcc not available")
def test_c_matches_python():
    _build_c_binaries()
    v = _make_dip_waveform(0.4, 30.0, start_s=0.3, tail_s=0.5)
    v = _round_trip(v)
    samples_text = "\n".join(f"{x:.6f}" for x in v)

    binary = PQ_DIR / "pq_main"
    proc = subprocess.run([str(binary), str(FS), str(F0), str(VRMS)], input=samples_text,
                           capture_output=True, text=True, check=True)
    c_lines = [l for l in proc.stdout.strip().splitlines() if l]

    py_events = run_processor_on_stream(v, PQParams(fs_hz=FS, f_nominal=F0, v_nominal=VRMS))

    print(f"\n[PQ] C/Python parity: C emitted {len(c_lines)}, Python emitted {len(py_events)}")
    assert len(c_lines) == len(py_events)
    for line, ev in zip(c_lines, py_events):
        ts, typ, mag, dur, pre, post, thd = line.split(",")
        assert int(ts) == ev.ts_epoch_ms
        assert int(typ) == ev.type
        assert math.isclose(float(mag), ev.magnitude_pu, abs_tol=1e-3)
        assert int(dur) == ev.duration_ms
        assert math.isclose(float(pre), ev.pre_event_rms_V, abs_tol=1e-2)
        assert math.isclose(float(post), ev.post_event_rms_V, abs_tol=1e-2)


@pytest.mark.skipif(not HAS_GCC, reason="gcc not available")
def test_c_host_unit_tests_pass():
    _build_c_binaries()
    proc = subprocess.run([str(PQ_DIR / "test_pq_host")], capture_output=True, text=True)
    print(f"\n[PQ] test_pq_host:\n{proc.stdout}{proc.stderr}")
    assert proc.returncode == 0, f"test_pq_host failed: {proc.stdout}{proc.stderr}"
