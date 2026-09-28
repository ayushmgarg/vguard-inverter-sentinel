"""ekf/sim_battery_for_ekf.py — small self-contained 1-RC Thevenin battery
simulator for exercising ekf/ekf.py and ekf/ekf.c.

Independent of the sim/ module another agent is building for the broader
prototype (features/, model/) -- this one exists purely to generate 1 Hz
I/V/T ground truth for the EKF's own tests, per CONTRACTS.md §1's column
layout (t, I, V, T, grid, P_load, soc_true, soh_true) plus a `charger_on`
flag the EKF needs that isn't in the shared stream contract.

What it reproduces, deliberately, for the EKF test suite:
  - a realistic multi-day duty cycle: outage/discharge, bulk charge,
    absorption/float (with load transients riding on top), true rest
    (charger relay open) -- >= 7 simulated days, several cycles/day
  - a 10 mA current-sensor offset and 0.5% gain error injected into the
    *measured* I column only (soc_true / the physics stay error-free), to
    exercise the EKF's zero-current auto-cal and to reproduce the ~1-2%/
    week naive-counter drift budget from design 01 §4
  - abrupt load-current steps (>=5-10% C20) during both charger-on and
    charger-off stretches, for the R_int event estimator (01 §6)
  - a charger_on flag that is explicitly separate from "current is small"
    so float (charger ON, tapered current) is never confused with true
    rest (charger OFF) -- the H30 regression this whole design fixes

This is a *placeholder* physics model (same LUT shapes as ekf/lut.py, not
independently characterised); see ekf/README.md "honest limits".
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List

import pandas as pd

from . import lut

DT_S = 1.0


@dataclass
class SimParams:
    q_rated_ah: float = 150.0
    seed: int = 0
    days: float = 8.0
    # injected current-sensor error (01 §4)
    i_offset_a: float = 0.010
    i_gain_err: float = 0.005
    v_noise_std: float = 0.0015  # INA228 voltage channel, sub-mV-ish RMS
    t_ambient_mean_c: float = 27.0
    t_ambient_amp_c: float = 8.0


class BatterySim:
    """Ground-truth 1-RC Thevenin battery, discharge-positive internally."""

    def __init__(self, params: SimParams = None):
        self.p = params or SimParams()
        self.c20_a = self.p.q_rated_ah / 20.0
        self.soc = 0.75
        self.v1 = 0.0
        self.rng = random.Random(self.p.seed)
        self.soh_true = 100.0  # fresh, constant across this short a sim

    def _t_ambient(self, t_s: float) -> float:
        return (self.p.t_ambient_mean_c
                + self.p.t_ambient_amp_c * math.sin(2 * math.pi * t_s / 86400.0
                                                       - math.pi / 2))

    def step(self, i_discharge_true: float, t_s: float, v_override: float = None):
        """Advance ground truth by DT_S given true discharge-positive current.

        `v_override`, when given, replaces the reported terminal voltage with
        a charger-regulated value (see `_v_charger_setpoint` below) instead
        of the plain OCV - I*R0 - V1 branch. Internal SoC/V1 bookkeeping is
        unaffected either way -- only the *reported* V differs.

        Why: real flooded lead-acid absorption/float voltages (~13.5-14.4 V
        for a 12 V pack) sit ~0.8-1.7 V above the rest-OCV table (design 01
        §2.1 tops out at 12.70-12.79 V) -- that gap is charge-side
        polarisation/gassing overpotential, not IR drop through the few-mOhm
        R0 this baseline 1-RC model carries (01 §1.1 flags 1-RC as a
        deliberate simplification; a slow second branch is a documented
        Phase-2 option). A plain OCV-I*R0-V1 branch with these R0 values can
        never reach 13.5 V at realistic charge currents, so it cannot
        reproduce the charger regulating to an absorption/float setpoint.
        `v_override` models that regulation directly, honestly, instead of
        stretching R0 into a physically wrong regime -- documented again in
        ekf/README.md "honest limits".
        """
        T = self._t_ambient(t_s)
        Qu = self.p.q_rated_ah * lut.f_temp(T) * lut.peukert_multiplier(
            i_discharge_true, self.c20_a)
        eta = 1.0 if i_discharge_true >= 0 else lut.eta_charge(self.soc, T)
        self.soc -= eta * i_discharge_true * DT_S / (3600.0 * Qu)
        self.soc = max(0.0, min(1.0, self.soc))

        tau = lut.tau(self.soc, T)
        R1 = lut.r1(self.soc, T)
        decay = math.exp(-DT_S / tau)
        self.v1 = self.v1 * decay + R1 * (1.0 - decay) * i_discharge_true

        if v_override is not None:
            v_true = v_override
        else:
            R0 = lut.r0(self.soc, T)
            ocv = lut.ocv(self.soc, T)
            v_true = ocv - i_discharge_true * R0 - self.v1
        v_meas = v_true + self.rng.gauss(0.0, self.p.v_noise_std)
        return v_meas, T

    def measured_current(self, i_charge_true: float) -> float:
        """Apply the injected sensor offset + gain error (01 §4)."""
        return i_charge_true * (1.0 + self.p.i_gain_err) + self.p.i_offset_a


# ----------------------------------------------------------------------
# phase schedule
# ----------------------------------------------------------------------

def _phase_schedule(rng: random.Random, days: float):
    """Yield (duration_s, kind, magnitude_a) tiles covering `days` days.

    kind in {"rest", "discharge", "bulk", "absorb_float"}. magnitude_a is a
    nominal discharge-positive current for "discharge" tiles (load current);
    ignored for the others (those compute their own profile).

    Duty cycle is deliberately *light* most days (India's "daily-to-weekly
    outages", 01 §4/§10 -- not a full cycle every day) so the weekly Ah
    throughput -- and hence the gain-error component of coulomb-counting
    drift -- lands near the design doc's own illustrative example (01 §4:
    ~140 Ah/week -> ~0.47%/week gain drift, ~1.1%/week idle-bias drift,
    combined ~1.5-2%/week). Exactly one deliberately deep (~40-50% DoD)
    cycle is placed mid-week so full-detection, coulombic-efficiency and
    measured-capacity (01 §7) all get exercised at least once; small
    ΔI blips are layered onto every discharge/float phase regardless of
    depth so the R_int event estimator (01 §6) sees >=20 events well
    before the 8th day.
    """
    t = 0.0
    day = 0
    total_s = days * 86400.0
    tiles = []
    n_days_est = int(days) + 1
    deep_cycle_day = n_days_est // 2
    while t < total_s:
        # long true rest (charger relay open), most nights high-confidence (>=5h)
        rest_len = rng.uniform(4.5, 7.0) * 3600.0
        tiles.append((rest_len, "rest", 0.0))
        t += rest_len

        if day == deep_cycle_day:
            # the one deep cycle this week: real outage, real DoD (>=30%).
            dis_len = rng.uniform(4.5, 5.5) * 3600.0
            dis_mag = rng.uniform(9.0, 11.0)
        else:
            # ordinary day: grid mostly stays up; a brief light load blip
            # (short inverter test / small transfer, not a real outage).
            dis_len = rng.uniform(0.15, 0.40) * 3600.0
            dis_mag = rng.uniform(1.5, 3.0)
        tiles.append((dis_len, "discharge", dis_mag))
        t += dis_len

        # grid returns -> bulk charge until near-full
        tiles.append((0.0, "bulk", 0.0))

        # absorption/float with load transients (the float != rest case)
        float_len = rng.uniform(2.0, 4.0) * 3600.0
        tiles.append((float_len, "absorb_float", 0.0))
        t += float_len

        # shorter provisional-only rest later in the day (some days)
        if rng.random() < 0.5:
            short_rest = rng.uniform(0.5, 1.4) * 3600.0
            tiles.append((short_rest, "rest", 0.0))
            t += short_rest

        day += 1
    return tiles


def simulate(params: SimParams = None) -> pd.DataFrame:
    p = params or SimParams()
    rng = random.Random(p.seed)
    sim = BatterySim(p)
    tiles = _phase_schedule(rng, p.days)

    rows = []
    t_s = 0.0
    total_s = p.days * 86400.0

    # transient-load bookkeeping (for R_int events): occasional step loads
    # riding on top of the base current, both on-grid and off-grid.
    transient_i = 0.0
    transient_ticks_left = 0

    def next_transient():
        return rng.uniform(0.0, 30.0), rng.choice([-1, 1]) * rng.uniform(0.5, 1.8)

    epoch0 = 1_700_000_000

    for (dur_s, kind, mag) in tiles:
        if t_s >= total_s:
            break

        if kind == "rest":
            n = int(dur_s / DT_S)
            for _ in range(n):
                if t_s >= total_s:
                    break
                i_true_discharge = rng.gauss(0.0, 0.003)  # tiny parasitic draw
                v_true, T = sim.step(i_true_discharge, t_s)
                i_charge_true = -i_true_discharge
                i_meas = sim.measured_current(i_charge_true)
                rows.append((t_s, i_meas, v_true, T, 1, 0.0, sim.soc,
                             sim.soh_true, False))
                t_s += DT_S

        elif kind == "discharge":
            n = int(dur_s / DT_S)
            for k in range(n):
                if t_s >= total_s:
                    break
                if transient_ticks_left <= 0 and rng.random() < 1.0 / 240.0:
                    dur_ticks, delta = next_transient()
                    transient_ticks_left = int(max(5, dur_ticks))
                    transient_i = delta
                if transient_ticks_left > 0:
                    transient_ticks_left -= 1
                else:
                    transient_i = 0.0
                i_true_discharge = max(0.05, mag + transient_i
                                        + rng.gauss(0.0, 0.05))
                v_true, T = sim.step(i_true_discharge, t_s)
                i_charge_true = -i_true_discharge
                i_meas = sim.measured_current(i_charge_true)
                p_load = v_true * i_true_discharge / 0.9
                rows.append((t_s, i_meas, v_true, T, 0, p_load, sim.soc,
                             sim.soh_true, False))
                t_s += DT_S

        elif kind == "bulk":
            # charge at ~C15 (CC) until V approaches the absorption setpoint,
            # then hand off to absorb_float. V ramps from the OCV branch
            # toward the charger's absorption setpoint as SoC climbs (see
            # BatterySim.step's v_override docstring for why this can't come
            # from the plain OCV-I*R0 branch).
            bulk_i_mag = p.q_rated_ah / 15.0
            soc_start = sim.soc
            while t_s < total_s:
                Tnow = sim._t_ambient(t_s)
                v_full_now = 13.5 - 0.024 * (Tnow - 25.0)
                if sim.soc >= 0.97:
                    break
                i_true_discharge = -bulk_i_mag
                v_abs_now = 14.4 - 0.024 * (Tnow - 25.0)
                span = max(0.02, 0.95 - soc_start)
                frac_bulk = min(1.0, max(0.0, (sim.soc - soc_start) / span))
                ocv_now = lut.ocv(sim.soc, Tnow)
                v_target = ocv_now + frac_bulk * (v_abs_now - ocv_now)
                v_true, T = sim.step(i_true_discharge, t_s, v_override=v_target)
                i_charge_true = -i_true_discharge
                i_meas = sim.measured_current(i_charge_true)
                rows.append((t_s, i_meas, v_true, T, 1, 0.0, sim.soc,
                             sim.soh_true, True))
                t_s += DT_S
                if v_true >= v_full_now and sim.soc >= 0.90:
                    break

        elif kind == "absorb_float":
            n = int(dur_s / DT_S)
            # absorption: taper current while the charger regulates from the
            # absorption setpoint down to the float setpoint (v_full_now,
            # matching the EKF's full-detection threshold exactly); load
            # transients ride on top and must NOT be mistaken for true rest
            # (charger_on stays True throughout -- the H30 regression case).
            tail_target = 0.012 * p.q_rated_ah / 20.0  # ~1.2% C20
            for k in range(n):
                if t_s >= total_s:
                    break
                Tnow = sim._t_ambient(t_s)
                v_abs_now = 14.4 - 0.024 * (Tnow - 25.0)
                # regulate a bit *above* the 13.5 V detection threshold (01
                # §5c) -- sitting exactly on it means measurement noise
                # alone flips V>=v_full every few ticks and the ~20 min
                # continuous dwell (01 §5a) can never complete.
                v_float_now = 13.6 - 0.024 * (Tnow - 25.0)
                frac = min(1.0, k / max(1.0, n * 0.15))
                base_charge_i = (1.0 - frac) * (p.q_rated_ah / 25.0) + frac * tail_target
                # transients are rarer than the ~20 min full-detect dwell so a
                # genuine taper can complete between them, but frequent enough
                # to exercise "no false full-detection during load transients".
                if transient_ticks_left <= 0 and rng.random() < 1.0 / 1500.0:
                    dur_ticks, delta = next_transient()
                    transient_ticks_left = int(min(20, max(5, dur_ticks)))
                    transient_i = delta
                if transient_ticks_left > 0:
                    transient_ticks_left -= 1
                else:
                    transient_i = 0.0
                # small regulator ripple only -- must stay well below the
                # tail_target-to-i_tail margin (~20 mA) or noise alone keeps
                # re-triggering the full-detect dwell timer and it can never
                # complete (01 §5a needs a *continuous* 10-30 min dwell).
                i_true_discharge = -(base_charge_i) + transient_i + rng.gauss(0.0, 0.004)
                v_target = v_abs_now + (v_float_now - v_abs_now) * frac
                v_target -= transient_i * lut.r0(sim.soc, Tnow)  # small sag/rise from an uncompensated blip
                v_true, T = sim.step(i_true_discharge, t_s, v_override=v_target)
                i_charge_true = -i_true_discharge
                i_meas = sim.measured_current(i_charge_true)
                rows.append((t_s, i_meas, v_true, T, 1, 0.0, sim.soc,
                             sim.soh_true, True))
                t_s += DT_S

    df = pd.DataFrame(rows, columns=["t", "I", "V", "T", "grid", "P_load",
                                      "soc_true", "soh_true", "charger_on"])
    df["t"] = (df["t"].astype("int64") + epoch0)
    return df


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="ekf/sim_ekf_data.csv")
    ap.add_argument("--days", type=float, default=8.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    df = simulate(SimParams(days=args.days, seed=args.seed))
    df.to_csv(args.out, index=False)
    print(f"wrote {len(df)} rows ({len(df)/86400.0:.2f} sim-days) to {args.out}")


if __name__ == "__main__":
    main()
