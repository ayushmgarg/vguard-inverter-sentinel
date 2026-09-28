"""Habit-learning tables for the V-Guard Sentinel autopilot (Engine 2).

Implements design doc 05 (Habit-Autopilot-and-Load-Prioritisation) sections 1-2:
  - 7x24 hour-of-week EWMA load table, 4 seasonal grids, seeded at season
    transition, cold-start blended with a generic double-peak curve.
  - 7x24 Beta-smoothed outage table (p_outage, duration mean/var).
  - P(outage in next h hours) with a confidence score.

This module holds ONLY the statistical tables. It knows nothing about
contactors, tiers or SoC thresholds -- that is controller.py's job. The
controller consumes `forecast_total_demand_wh` and `outage_forecast` each
60 s cycle; in firmware this is the `autopilot` FreeRTOS task's habit
sub-step (design 11 Sec.2 stack table).

Honesty note (CONTRACTS Sec.7): "learns habits" here means exactly what
05 Sec.1.5 says -- EWMA/Beta statistics on hour-of-week bins, not a neural
forecaster. Per-tier load decomposition is NOT available in this
prototype (one battery-side shunt feeds the whole table, same channel as
the EKF, design 05 Sec.1.1) -- see autopilot/README.md "Honest limits".

Pure functions only: every update returns a NEW table; inputs are never
mutated (project coding-style: immutability).
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import List, Optional, Tuple

# --------------------------------------------------------------------------
# Constants (design 05 Sec.1.2, Sec.1.4, Sec.2.1)
# --------------------------------------------------------------------------

ALPHA_LOAD = 0.08          # load EWMA time constant (~3 weeks at 1 update/day/bin)
ALPHA_OUTAGE_DUR = 0.15    # outage duration EWMA
COLD_START_N = 14          # cold-start blend weight denominator: n/(n+14)
CONFIDENCE_N = 8           # outage-probability confidence: n/(n+8)
DEFAULT_HORIZON_H = 3      # default P(outage in next h hours)
N_DOW = 7
N_HOUR = 24

# On-device byte layout (design 05 Sec.1.3). NOT a literal sizeof() of the
# Python dataclasses below -- CPython objects always carry far more
# overhead than a packed C struct. These constants model the firmware's
# packed representation: mean_W f32(4) + var_W f32(4) + n_obs u16(2) +
# last_update u16(2, hours-since-epoch-mod-65536) = 12 B/bin for load;
# p side stored as k,n u16 pairs + duration f32 mean/var = 4+4+4+2+2 =
# 16 B/bin for outage (the design table's own 12/16 B/bin figures).
LOAD_BIN_BYTES = 12
OUTAGE_BIN_BYTES = 16
RESIDENT_RAM_BYTES = N_DOW * N_HOUR * LOAD_BIN_BYTES + N_DOW * N_HOUR * OUTAGE_BIN_BYTES
DORMANT_SEASON_BYTES = 3 * N_DOW * N_HOUR * LOAD_BIN_BYTES
RESIDENT_RAM_TARGET_BYTES = 4700.0  # design 05 Sec.1.3: "Resident RAM ~4.7 KB"


class Season(IntEnum):
    """4 seasonal grids (design 05 Sec.1.1), IMD-inspired month buckets.

    The design doc names the 4 seasons but does not give month
    boundaries; this mapping is this implementation's interpretive
    choice (documented honestly in autopilot/README.md):
      WINTER      Dec, Jan, Feb
      SUMMER      Mar, Apr, May, Jun   (pre-monsoon heat, AC/cooler peak)
      MONSOON     Jul, Aug, Sep
      PRE_MONSOON Oct, Nov             (shoulder / retreating-monsoon)
    """

    WINTER = 0
    SUMMER = 1
    MONSOON = 2
    PRE_MONSOON = 3


_MONTH_TO_SEASON = {
    12: Season.WINTER, 1: Season.WINTER, 2: Season.WINTER,
    3: Season.SUMMER, 4: Season.SUMMER, 5: Season.SUMMER, 6: Season.SUMMER,
    7: Season.MONSOON, 8: Season.MONSOON, 9: Season.MONSOON,
    10: Season.PRE_MONSOON, 11: Season.PRE_MONSOON,
}


def season_for_month(month: int) -> Season:
    """month: 1-12 (calendar month). Raises ValueError outside that range."""
    if month not in _MONTH_TO_SEASON:
        raise ValueError("month must be 1-12, got %r" % (month,))
    return _MONTH_TO_SEASON[month]


# --------------------------------------------------------------------------
# Generic Indian residential double-peak curve (design 05 Sec.1.4)
# --------------------------------------------------------------------------

def generic_double_peak_w(hour: int, connected_load_nameplate_w: float) -> float:
    """Illustrative double-peak shape (06-09h, 18-23h), scaled from the
    inverter's connected-load nameplate. NOT measured data -- a cold-start
    prior only, replaced by real observations as n_obs grows (Sec.1.4).
    """
    if not (0 <= hour <= 23):
        raise ValueError("hour must be 0-23")
    if connected_load_nameplate_w < 0:
        raise ValueError("connected_load_nameplate_w must be >= 0")
    if 6 <= hour <= 9:
        frac = 0.55
    elif 18 <= hour <= 23:
        frac = 0.60
    else:
        frac = 0.15
    return frac * connected_load_nameplate_w


# --------------------------------------------------------------------------
# Load table
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LoadBin:
    mean_w: float = 0.0
    var_w: float = 0.0
    n_obs: int = 0
    last_update_epoch: int = 0

    def blend_weight(self) -> float:
        """n_obs/(n_obs+COLD_START_N) -- design 05 Sec.1.4."""
        return self.n_obs / (self.n_obs + COLD_START_N)


def _empty_grid() -> List[List[LoadBin]]:
    return [[LoadBin() for _ in range(N_HOUR)] for _ in range(N_DOW)]


@dataclass(frozen=True)
class LoadTable:
    """4 seasonal 7x24 grids plus which season is active."""

    grids: Tuple[Tuple[Tuple[LoadBin, ...], ...], ...]
    active_season: Season = Season.WINTER

    @staticmethod
    def new() -> "LoadTable":
        empty = tuple(tuple(tuple(row) for row in _empty_grid()) for _ in range(4))
        return LoadTable(grids=empty, active_season=Season.WINTER)

    def grid(self, season: Optional[Season] = None):
        s = self.active_season if season is None else season
        return self.grids[int(s)]

    def bin(self, dow: int, hour: int, season: Optional[Season] = None) -> LoadBin:
        _check_dow_hour(dow, hour)
        return self.grid(season)[dow][hour]


def _check_dow_hour(dow: int, hour: int) -> None:
    if not (0 <= dow < N_DOW):
        raise ValueError("dow must be 0-6, got %r" % (dow,))
    if not (0 <= hour < N_HOUR):
        raise ValueError("hour must be 0-23, got %r" % (hour,))


def _welford_ewma(mean_old: float, var_old: float, n_obs: int, x: float, alpha: float) -> Tuple[float, float]:
    """design 05 Sec.1.2: mean_new = mean_old + a(x-mean_old);
    var_new = (1-a)(var_old + a(x-mean_old)^2)."""
    if n_obs == 0:
        return x, 0.0
    diff = x - mean_old
    mean_new = mean_old + alpha * diff
    var_new = (1.0 - alpha) * (var_old + alpha * diff * diff)
    return mean_new, var_new


def update_load_hour(table: LoadTable, dow: int, hour: int, x_w: float, now_epoch: int) -> LoadTable:
    """Hourly update for one bin of the ACTIVE season's grid. Returns a new
    LoadTable; `table` is not mutated."""
    _check_dow_hour(dow, hour)
    if x_w < 0:
        raise ValueError("x_w (load power) must be >= 0")
    old = table.bin(dow, hour)
    mean_new, var_new = _welford_ewma(old.mean_w, old.var_w, old.n_obs, x_w, ALPHA_LOAD)
    n_new = min(old.n_obs + 1, 65535)
    new_bin = LoadBin(mean_w=mean_new, var_w=var_new, n_obs=n_new, last_update_epoch=now_epoch)

    grids = list(list(row) for row in table.grids[int(table.active_season)])
    row = list(grids[dow])
    row[hour] = new_bin
    grids[dow] = tuple(row)
    new_active_grid = tuple(grids)

    all_grids = list(table.grids)
    all_grids[int(table.active_season)] = new_active_grid
    return replace(table, grids=tuple(all_grids))


def transition_season(table: LoadTable, new_season: Season, seed_n_obs: int = 4) -> LoadTable:
    """Switch the active season, seeding any never-observed bin of the new
    season's grid from the outgoing season's grid (design 05 Sec.1.1:
    "the active season's grid is seeded from the previous season's at
    transition so day-1 of a season is not a cold start").

    `seed_n_obs` gives the seeded bin a small non-zero borrowed n_obs (capped
    at the source bin's own n_obs) so the cold-start blend
    (n/(n+14)) partially trusts the carried-over mean instead of falling
    back to the fully-generic curve -- a deliberate, documented choice
    since a season-old average is informative but less trustworthy than
    real current-season data.
    """
    if new_season == table.active_season:
        return table
    old_grid = table.grid(table.active_season)
    new_grid = table.grid(new_season)
    seeded_rows = []
    for dow in range(N_DOW):
        seeded_row = []
        for hour in range(N_HOUR):
            dst = new_grid[dow][hour]
            if dst.n_obs == 0:
                src = old_grid[dow][hour]
                borrowed_n = min(seed_n_obs, src.n_obs)
                seeded_row.append(LoadBin(mean_w=src.mean_w, var_w=src.var_w, n_obs=borrowed_n, last_update_epoch=dst.last_update_epoch))
            else:
                seeded_row.append(dst)
        seeded_rows.append(tuple(seeded_row))
    all_grids = list(table.grids)
    all_grids[int(new_season)] = tuple(seeded_rows)
    return LoadTable(grids=tuple(all_grids), active_season=new_season)


def forecast_load_w(table: LoadTable, dow: int, hour: int, connected_load_nameplate_w: float) -> float:
    """Cold-start-blended point forecast for one hour-of-week bin (design
    05 Sec.1.4): weight = n_obs/(n_obs+14) toward the observed EWMA mean,
    (1-weight) toward the generic double-peak curve."""
    b = table.bin(dow, hour)
    generic = generic_double_peak_w(hour, connected_load_nameplate_w)
    w = b.blend_weight()
    return w * b.mean_w + (1.0 - w) * generic


def forecast_total_demand_wh(table: LoadTable, dow: int, hour: int, horizon_h: int, connected_load_nameplate_w: float) -> float:
    """Sum of hourly point forecasts over `horizon_h` hours starting at
    (dow, hour). This is the TOTAL connected-load forecast (all tiers) --
    see module docstring "Honesty note": per-tier decomposition needs NILM
    or per-channel CT metering, not assumed here. Callers that need a
    tier-scoped forecast (design 05 Sec.4.3 `fcst_T1_Wh`) must apply a
    tier-fraction knob themselves (controller.py does this, documented as
    a limit in autopilot/README.md).
    """
    if horizon_h <= 0:
        raise ValueError("horizon_h must be > 0")
    total = 0.0
    d, h = dow, hour
    for i in range(horizon_h):
        hh = (h + i) % 24
        dd = (d + (h + i) // 24) % 7
        total += forecast_load_w(table, dd, hh, connected_load_nameplate_w)  # 1 h bin -> Wh == W
    return total


# --------------------------------------------------------------------------
# Outage table
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class OutageBin:
    k: int = 0                 # outages STARTING in this bin (count)
    n: int = 0                 # weeks OBSERVED for this bin (count)
    dur_mean_min: float = 0.0
    dur_var_min: float = 0.0

    def p_outage(self) -> float:
        """Beta/Laplace-smoothed p = (k+1)/(n+2) -- design 05 Sec.1.1."""
        return (self.k + 1.0) / (self.n + 2.0)

    def confidence(self) -> float:
        """n/(n+8) -- design 05 Sec.2.1."""
        return self.n / (self.n + CONFIDENCE_N)


def _empty_outage_grid() -> Tuple[Tuple[OutageBin, ...], ...]:
    return tuple(tuple(OutageBin() for _ in range(N_HOUR)) for _ in range(N_DOW))


@dataclass(frozen=True)
class OutageTable:
    grid: Tuple[Tuple[OutageBin, ...], ...]

    @staticmethod
    def new() -> "OutageTable":
        return OutageTable(grid=_empty_outage_grid())

    def bin(self, dow: int, hour: int) -> OutageBin:
        _check_dow_hour(dow, hour)
        return self.grid[dow][hour]


def observe_week(table: OutageTable) -> OutageTable:
    """Once-a-week tick: n += 1 for every bin (design 05 Sec.1.1: "n =
    weeks observed"). Independent of whether an outage occurred."""
    new_rows = []
    for dow in range(N_DOW):
        row = []
        for hour in range(N_HOUR):
            b = table.grid[dow][hour]
            row.append(replace(b, n=min(b.n + 1, 65535)))
        new_rows.append(tuple(row))
    return OutageTable(grid=tuple(new_rows))


def record_outage_start(table: OutageTable, dow: int, hour: int) -> OutageTable:
    """k += 1 for the bin in which an outage STARTED."""
    _check_dow_hour(dow, hour)
    b = table.bin(dow, hour)
    new_b = replace(b, k=min(b.k + 1, 65535))
    return _replace_outage_bin(table, dow, hour, new_b)


def record_outage_duration(table: OutageTable, dow: int, hour: int, duration_min: float) -> OutageTable:
    """EWMA (alpha=0.15) update of duration mean/var for the bin the
    outage started in -- design 05 Sec.1.2."""
    _check_dow_hour(dow, hour)
    if duration_min < 0:
        raise ValueError("duration_min must be >= 0")
    b = table.bin(dow, hour)
    mean_new, var_new = _welford_ewma(b.dur_mean_min, b.dur_var_min, b.k, duration_min, ALPHA_OUTAGE_DUR)
    new_b = replace(b, dur_mean_min=mean_new, dur_var_min=var_new)
    return _replace_outage_bin(table, dow, hour, new_b)


def _replace_outage_bin(table: OutageTable, dow: int, hour: int, new_b: OutageBin) -> OutageTable:
    rows = list(list(row) for row in table.grid)
    rows[dow][hour] = new_b
    return OutageTable(grid=tuple(tuple(row) for row in rows))


@dataclass(frozen=True)
class OutageForecast:
    prob: float          # P(outage starts in next h hours)
    confidence: float    # from the starting bin's Beta posterior width


def outage_forecast(table: OutageTable, dow: int, hour: int, horizon_h: int = DEFAULT_HORIZON_H) -> OutageForecast:
    """P(outage in next h hours) = 1 - Pi (1 - p_outage[bin_i]) -- design
    05 Sec.2.1. Confidence reported from the STARTING bin (dow, hour)."""
    if horizon_h <= 0:
        raise ValueError("horizon_h must be > 0")
    _check_dow_hour(dow, hour)
    survive = 1.0
    d, h = dow, hour
    for i in range(horizon_h):
        hh = (h + i) % 24
        dd = (d + (h + i) // 24) % 7
        survive *= (1.0 - table.bin(dd, hh).p_outage())
    prob = 1.0 - survive
    conf = table.bin(dow, hour).confidence()
    return OutageForecast(prob=prob, confidence=conf)


# --------------------------------------------------------------------------
# Memory footprint (design 05 Sec.1.3)
# --------------------------------------------------------------------------

def resident_ram_bytes() -> int:
    """Active-season load grid (168 bins) + outage grid (168 bins), the
    RAM-resident structures. Dormant seasons live in flash (excluded)."""
    return N_DOW * N_HOUR * LOAD_BIN_BYTES + N_DOW * N_HOUR * OUTAGE_BIN_BYTES


def assert_memory_footprint(tolerance: float = 0.05) -> None:
    """Raises AssertionError if the modeled resident RAM footprint drifts
    from the design's ~4.7 KB target by more than `tolerance` (fraction).
    This checks the BYTE-LAYOUT CONSTANTS above, not sys.getsizeof() of the
    Python dataclasses -- CPython object overhead has no bearing on an
    embedded C struct's packed size (see module docstring)."""
    actual = resident_ram_bytes()
    lo = RESIDENT_RAM_TARGET_BYTES * (1.0 - tolerance)
    hi = RESIDENT_RAM_TARGET_BYTES * (1.0 + tolerance)
    assert lo <= actual <= hi, (
        "resident RAM footprint %d B is outside %.0f%% of the design's "
        "~%.0f B target (got lo=%.0f hi=%.0f)" % (actual, tolerance * 100, RESIDENT_RAM_TARGET_BYTES, lo, hi)
    )
