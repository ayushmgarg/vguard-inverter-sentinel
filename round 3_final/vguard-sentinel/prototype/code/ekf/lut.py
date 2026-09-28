"""ekf/lut.py — design-doc 01 §1.5-§2.2 lookup tables (bilinear over SoC x T).

All table values below are engineering placeholders pending the bench aging
campaign (design 01 §1.5: "characterise-in-lab; do not ship these as
truth"). The 25 C OCV row is the design-doc table verbatim (01 §2.1); the
0 C / 45 C rows are the -3.5 mV/C/12V calibration-day coefficient (01 §2.2)
applied to that row as a stand-in 2-D table, pending real 0/25/45 C bench
characterisation (01 §1.6). R0/R1/tau shapes follow the qualitative notes in
01 §1.5 (+40% R0 empty, +50% cold; R1 knee sharper below 20% SoC) with
invented magnitudes inside the documented bands.

The grids and bilinear scheme here are mirrored *exactly* in ekf/ekf.c so
the C port and this module agree bit-for-bit on interpolation behaviour.
"""

from __future__ import annotations

import bisect

SOC_GRID = [0.0, 0.10, 0.25, 0.50, 0.75, 0.90, 1.00]
T_GRID = [0.0, 25.0, 45.0]

# OCV(SoC,T) [V] -- 01 Table §2.1 (25C row) + §2.2 tempco applied (0C/45C rows)
OCV_TABLE = [
    [11.8875, 11.9875, 12.1375, 12.3875, 12.5875, 12.6875, 12.7875],  # T=0C
    [11.80, 11.90, 12.05, 12.30, 12.50, 12.60, 12.70],  # T=25C (design verbatim)
    [11.73, 11.83, 11.98, 12.23, 12.43, 12.53, 12.63],  # T=45C
]

# R0(SoC,T) [ohm] -- 01 §1.5 placeholder (+40% empty, +50% cold vs 25C/full)
R0_TABLE = [
    [0.009450, 0.008775, 0.0077625, 0.0070875, 0.006885, 0.006750, 0.006750],
    [0.006300, 0.005850, 0.0051750, 0.0047250, 0.004590, 0.004500, 0.004500],
    [0.005355, 0.004973, 0.0043988, 0.0040163, 0.003902, 0.003825, 0.003825],
]

# R1(SoC,T) [ohm] -- 01 §1.5 placeholder (sharp knee below 20% SoC)
R1_TABLE = [
    [0.01470, 0.010780, 0.006860, 0.005390, 0.004900, 0.004900, 0.004900],
    [0.01050, 0.007700, 0.004900, 0.003850, 0.003500, 0.003500, 0.003500],
    [0.00945, 0.006930, 0.004410, 0.003465, 0.003150, 0.003150, 0.003150],
]

# tau = R1*C1 [s] -- 01 §1.5 band (20-120 s), tabulated directly
TAU_TABLE = [
    [120.0, 114.4, 85.8, 71.5, 64.35, 60.775, 60.775],
    [110.0, 88.0, 66.0, 55.0, 49.5, 46.75, 46.75],
    [88.0, 70.4, 52.8, 44.0, 39.6, 37.4, 37.4],
]


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _bracket(grid, v):
    v = _clip(v, grid[0], grid[-1])
    i = bisect.bisect_right(grid, v) - 1
    i = _clip(i, 0, len(grid) - 2)
    i = int(i)
    lo, hi = grid[i], grid[i + 1]
    frac = 0.0 if hi == lo else (v - lo) / (hi - lo)
    return i, frac


def bilinear(table, soc: float, t: float) -> float:
    si, sf = _bracket(SOC_GRID, soc)
    ti, tf = _bracket(T_GRID, t)
    v00 = table[ti][si]
    v01 = table[ti][si + 1]
    v10 = table[ti + 1][si]
    v11 = table[ti + 1][si + 1]
    v0 = v00 + (v01 - v00) * sf
    v1 = v10 + (v11 - v10) * sf
    return v0 + (v1 - v0) * tf


def ocv(soc: float, t: float) -> float:
    return bilinear(OCV_TABLE, soc, t)


def docv_dsoc(soc: float, t: float, eps: float = 0.01) -> float:
    """Finite-difference dOCV/dSoC, 01 §3.1."""
    lo = _clip(soc - eps, 0.0, 1.0)
    hi = _clip(soc + eps, 0.0, 1.0)
    if hi == lo:
        return 0.0
    return (ocv(hi, t) - ocv(lo, t)) / (hi - lo)


def ocv_inverse(v: float, t: float) -> float:
    """Invert OCV(., T) for SoC at fixed T (01 §3.3 rest-init rule).

    Dense linear search over the SoC grid at fixed T -- OCV is monotonic
    increasing in SoC, small table, called only at (re)initialisation.
    """
    n = 200
    dense_soc = [i / n for i in range(n + 1)]
    dense_ocv = [ocv(s, t) for s in dense_soc]
    v = _clip(v, dense_ocv[0], dense_ocv[-1])
    for i in range(n):
        lo, hi = dense_ocv[i], dense_ocv[i + 1]
        if lo <= v <= hi:
            frac = 0.0 if hi == lo else (v - lo) / (hi - lo)
            return dense_soc[i] + frac * (dense_soc[i + 1] - dense_soc[i])
    return 0.5


def r0(soc: float, t: float) -> float:
    return bilinear(R0_TABLE, soc, t)


def r1(soc: float, t: float) -> float:
    return bilinear(R1_TABLE, soc, t)


def tau(soc: float, t: float) -> float:
    return _clip(bilinear(TAU_TABLE, soc, t), 20.0, 120.0)


def _interp1d(x: float, breaks, vals) -> float:
    x = _clip(x, breaks[0], breaks[-1])
    for i in range(len(breaks) - 1):
        lo, hi = breaks[i], breaks[i + 1]
        if lo <= x <= hi:
            frac = 0.0 if hi == lo else (x - lo) / (hi - lo)
            return vals[i] + frac * (vals[i + 1] - vals[i])
    return vals[-1]


def f_temp(t: float) -> float:
    """01 §2.5: ~100% at 25C, mid-80s% at 0C; no high-T capacity derate
    (India heat handled via the R0/SoH path per design note)."""
    return _interp1d(t, [-10.0, 0.0, 25.0, 45.0], [0.75, 0.85, 1.00, 1.00])


def eta_charge(soc: float, t: float) -> float:
    """01 §1.3: ~0.98 below 70% SoC, tapering to 0.70-0.85 above 90% SoC
    (gassing). T dependence not characterised -- SoC-only placeholder."""
    del t
    return _interp1d(soc, [0.0, 0.70, 0.90, 1.00], [0.98, 0.98, 0.90, 0.77])


def peukert_multiplier(i_discharge_a: float, c20_a: float, n: float = 1.25,
                        floor: float = 0.55) -> float:
    """01 §2.5. Q_usable(I) = Q_rated*(I20/|I|)^(n-1) for |I|>I20, clamped."""
    ia = abs(i_discharge_a)
    if c20_a <= 0.0 or ia <= c20_a:
        return 1.0
    mult = (c20_a / ia) ** (n - 1.0)
    return _clip(mult, floor, 1.0)
