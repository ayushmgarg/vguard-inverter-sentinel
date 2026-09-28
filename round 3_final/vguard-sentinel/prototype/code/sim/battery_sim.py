"""1 Hz synthetic duty-cycle simulator for Indian tubular flooded lead-acid batteries.

Implements design 02-TinyML-SoH-RUL-Pipeline.md SS4.3 (and the underlying electrical /
ageing model from 01-Battery-State-Estimation.md SS1.3, SS2.1, SS2.5): Poisson outage
arrivals with seasonal rate, lognormal outage durations, appliance-switching household
load through an inverter, CC/CV/float charger, a 1-RC Thevenin electrical model with
Peukert-corrected coulomb counting, Arrhenius temperature stress, a Schiffer-style
weighted-Ah ageing model driving capacity fade and R0 growth, and a sulphation index
driving coulombic-efficiency and charge-acceptance decline. See sim/README.md for the
full section-by-section mapping and the "what this is not" honesty notes.

CLI: python -m sim.battery_sim --n 24 --out data/sim_1hz/ --seed 0
"""
import argparse
import math
import os
import time

import numpy as np
import pandas as pd

from sim.physics import (
    BatteryParams,
    CC_TAIL_FRAC,
    CHARGER_V_TEMP_COEF,
    SITE_PROFILES,
    V_BOOST,
    V_CUTOFF,
    V_FLOAT,
    ambient_temp_c,
    arrhenius_af,
    build_seasonal_rate,
)

_TWO_PI_365 = 2.0 * math.pi / 365.0
_TWO_PI_24 = 2.0 * math.pi / 24.0
_ARRHENIUS_K = 6400.0
_ARRHENIUS_T0 = 298.15

STREAM_COLUMNS = ["t", "I", "V", "T", "grid", "P_load", "soc_true", "soh_true"]

# ageing / stop conditions
SOH_STOP_FLOOR = 55.0     # stop simulating a battery once soh_true drops below this
SOH_EOL = 80.0             # design 02 SS0 definition of EoL

# appliance load model (design 02 SS4.3: 150-900 W with appliance switching)
LOAD_MIN_W = 150.0
LOAD_MAX_W = 900.0
LOAD_SWITCH_MIN_S = 120
LOAD_SWITCH_MAX_S = 900

# Schiffer weighted-Ah coefficients, design 02 SS1.3 defaults
SCHIFFER_A = 1.0
SCHIFFER_B = 0.3

# max wall-clock seconds a CC or CV phase may run before we force a transition
# (safety guard against a mis-tuned parameter draw producing a non-terminating phase)
MAX_PHASE_SECONDS = 8 * 3600


def _draw_load_switch(rng):
    return int(rng.uniform(LOAD_SWITCH_MIN_S, LOAD_SWITCH_MAX_S))


class _LoadGen:
    """Household appliance-switching load, W. Stateful across the whole battery run
    so 'grid' phases see a continuous (if unused) demand trace too."""

    def __init__(self, rng):
        self.rng = rng
        self.level = float(rng.uniform(LOAD_MIN_W, LOAD_MAX_W))
        self.next_switch = _draw_load_switch(rng)

    def step(self):
        self.next_switch -= 1
        if self.next_switch <= 0:
            self.level = float(self.rng.uniform(LOAD_MIN_W, LOAD_MAX_W))
            self.next_switch = _draw_load_switch(self.rng)
        return self.level


class _BatteryState:
    """Mutable electrical + calendar + ageing state carried across cycles."""

    def __init__(self, bp):
        self.soc = 1.0
        self.soc_uncl = 1.0  # unclamped SoC integral, drives the Shepherd polarisation
        # denominator so continued CV current still raises internal overvoltage after
        # the reported SoC has saturated at 1.0 (real overcharge/gassing behaviour) --
        # without this the polarisation term freezes and CV current never tapers.
        self.v1 = 0.0
        self.self_heat = 0.0
        self.sim_hours = 0.0  # synthetic calendar clock (diurnal/seasonal only)
        self.t_global = 0
        self.hours_since_full = 6.0  # plausible warm-start value (battery has some history)
        self.capacity_fade_frac = 1.0
        self.r0_growth_mult = 1.0
        self.sulfation = 0.0
        self.eta_c_current = bp.eta_c0
        self.ca_mult_current = 1.0
        self.s_total_cum = 0.0
        self.s_float_cum = 0.0
        self.s_disch_cum = 0.0
        self.efc_cum = 0.0


def _step_calendar(st, dt_hours):
    st.sim_hours += dt_hours


def _ambient_now(bp, st):
    day = (st.sim_hours / 24.0) % 365.0
    hour = st.sim_hours % 24.0
    return ambient_temp_c(day, hour, bp.site)


def _simulate_discharge(bp, st, load_gen, duration_s, buf):
    """Discharge phase, inlined for speed (called ~1e7 times across a full run)."""
    soc = st.soc
    soc_uncl = st.soc_uncl
    v1 = st.v1
    self_heat = st.self_heat
    sim_hours = st.sim_hours
    t_global = st.t_global
    r0_growth = st.r0_growth_mult
    s_total = st.s_total_cum
    s_disch = st.s_disch_cum

    C_rated = bp.C_rated
    I20 = bp.I20
    n_pk = bp.peukert_n
    eta_inv = bp.eta_inv
    k_pol_base = bp.k_pol_ohm_ah / C_rated
    R0_full = bp.R0_25_full_mohm
    R1_full = bp.R1_25_full_mohm
    C1 = bp.C1_farad
    k_self_heat = bp.k_self_heat
    tau_therm = bp.tau_therm_s
    site = SITE_PROFILES[bp.site]
    s_mean, s_amp, s_peak, s_diurnal = site["mean"], site["seasonal_amp"], site["peak_day"], site["diurnal_amp"]

    exp = math.exp
    sqrt = math.sqrt
    cos = math.cos

    t_list = buf["t"]
    I_list = buf["I"]
    V_list = buf["V"]
    T_list = buf["T"]
    grid_list = buf["grid"]
    P_list = buf["P_load"]
    soc_list = buf["soc"]

    t0_soc = soc
    soc_min = soc
    q_dis_ah = 0.0

    for _ in range(duration_s):
        day = (sim_hours / 24.0) % 365.0
        hour = sim_hours % 24.0
        temp_amb = s_mean + s_amp * cos(_TWO_PI_365 * (day - s_peak)) + s_diurnal * cos(_TWO_PI_24 * (hour - 14.0))
        temp_c = temp_amb + self_heat

        mult_T = exp(-0.00844 * (temp_c - 25.0))
        r0_mohm = R0_full * r0_growth * (1.0 + 0.40 * (1.0 - soc)) * mult_T
        r0_ohm = r0_mohm / 1000.0
        r1_mohm = R1_full * r0_growth * (1.0 + 0.40 * (1.0 - soc) + 0.9 * max(0.0, 0.20 - soc) / 0.20) * mult_T
        r1_ohm = r1_mohm / 1000.0
        tau = max(1.0, r1_ohm * C1)

        if soc <= 0.0:
            ocv_base = 11.80
        elif soc < 0.10:
            ocv_base = 11.80 + (soc / 0.10) * 0.10
        elif soc < 0.25:
            ocv_base = 11.90 + ((soc - 0.10) / 0.15) * 0.15
        elif soc < 0.50:
            ocv_base = 12.05 + ((soc - 0.25) / 0.25) * 0.25
        elif soc < 0.75:
            ocv_base = 12.30 + ((soc - 0.50) / 0.25) * 0.20
        elif soc < 0.90:
            ocv_base = 12.50 + ((soc - 0.75) / 0.15) * 0.10
        elif soc < 1.00:
            ocv_base = 12.60 + ((soc - 0.90) / 0.10) * 0.10
        else:
            ocv_base = 12.70
        ocv = ocv_base - 0.0035 * (temp_c - 25.0)

        denom = max(soc_uncl, 0.03)
        r_pol = k_pol_base / denom
        r_eff = r0_ohm + r_pol

        p_load = load_gen.step()
        p_batt = p_load / eta_inv

        disc = (ocv - v1) ** 2 - 4.0 * r_eff * p_batt
        cutoff = False
        if disc < 0.0:
            i_amp = p_batt / max(V_CUTOFF, 1.0)
            cutoff = True
        else:
            i_amp = ((ocv - v1) - sqrt(disc)) / (2.0 * r_eff)

        v_term = ocv - i_amp * r_eff - v1
        if v_term <= V_CUTOFF or cutoff:
            i_amp = 0.0
            v_term = ocv - v1

        i_abs = abs(i_amp)
        pk = 1.0 if (i_abs <= I20 or i_abs <= 1e-6) else max(0.55, (I20 / i_abs) ** (n_pk - 1.0))
        f_temp = min(1.05, max(0.55, 1.0 + 0.006 * (temp_c - 25.0)))
        q_usable = max(C_rated * f_temp * pk, 1.0)
        d_soc = -i_amp * (1.0 / 3600.0) / q_usable
        soc = min(1.0, max(0.0, soc + d_soc))
        soc_uncl = min(1.3, max(-0.2, soc_uncl + d_soc))
        e_tau = exp(-1.0 / tau)
        v1 = v1 * e_tau + r1_ohm * (1.0 - e_tau) * i_amp

        heat_target = min(15.0, k_self_heat * i_amp * i_amp * r0_mohm)
        self_heat += (heat_target - self_heat) * (1.0 / tau_therm)
        self_heat = max(0.0, min(20.0, self_heat))

        af = exp(_ARRHENIUS_K * (1.0 / _ARRHENIUS_T0 - 1.0 / (temp_c + 273.15)))
        d_days = af / 86400.0
        s_total += d_days
        if soc < 0.5:
            s_disch += d_days
        sim_hours += 1.0 / 3600.0

        t_list.append(t_global)
        I_list.append(i_amp)  # internal convention: + = discharge
        V_list.append(v_term)
        T_list.append(temp_c)
        grid_list.append(0)
        P_list.append(p_load)
        soc_list.append(soc)
        t_global += 1
        q_dis_ah += i_amp / 3600.0
        soc_min = min(soc_min, soc)

    st.soc, st.soc_uncl, st.v1 = soc, soc_uncl, v1
    st.self_heat, st.sim_hours, st.t_global = self_heat, sim_hours, t_global
    st.s_total_cum, st.s_disch_cum = s_total, s_disch

    dod_k = t0_soc - soc_min
    return dict(n=duration_s, q_dis_ah=q_dis_ah, dod_k=max(0.0, dod_k))


def _simulate_charge(bp, st, load_gen, buf):
    """CC then CV, inlined for speed. Returns q_chg_ah, n, ca60."""
    soc = st.soc
    soc_uncl = st.soc_uncl
    v1 = st.v1
    self_heat = st.self_heat
    sim_hours = st.sim_hours
    t_global = st.t_global
    r0_growth = st.r0_growth_mult
    s_total = st.s_total_cum
    s_disch = st.s_disch_cum
    eta_c_cur = st.eta_c_current
    ca_mult = st.ca_mult_current

    C_rated = bp.C_rated
    k_pol_base = bp.k_pol_ohm_ah / C_rated
    R0_full = bp.R0_25_full_mohm
    R1_full = bp.R1_25_full_mohm
    C1 = bp.C1_farad
    k_self_heat = bp.k_self_heat
    tau_therm = bp.tau_therm_s
    eta_c0 = bp.eta_c0
    i_cc_a = bp.i_cc_a
    site = SITE_PROFILES[bp.site]
    s_mean, s_amp, s_peak, s_diurnal = site["mean"], site["seasonal_amp"], site["peak_day"], site["diurnal_amp"]

    exp = math.exp
    cos = math.cos

    t_list = buf["t"]
    I_list = buf["I"]
    V_list = buf["V"]
    T_list = buf["T"]
    grid_list = buf["grid"]
    P_list = buf["P_load"]
    soc_list = buf["soc"]

    q_cc_ah = 0.0
    n_cc = 0
    steps = 0
    while steps < MAX_PHASE_SECONDS:
        day = (sim_hours / 24.0) % 365.0
        hour = sim_hours % 24.0
        temp_amb = s_mean + s_amp * cos(_TWO_PI_365 * (day - s_peak)) + s_diurnal * cos(_TWO_PI_24 * (hour - 14.0))
        temp_c = temp_amb + self_heat
        mult_T = exp(-0.00844 * (temp_c - 25.0))
        r0_mohm = R0_full * r0_growth * (1.0 + 0.40 * (1.0 - soc)) * mult_T
        r0_ohm = r0_mohm / 1000.0
        r1_mohm = R1_full * r0_growth * (1.0 + 0.40 * (1.0 - soc) + 0.9 * max(0.0, 0.20 - soc) / 0.20) * mult_T
        r1_ohm = r1_mohm / 1000.0
        tau = max(1.0, r1_ohm * C1)
        if soc <= 0.0:
            ocv_base = 11.80
        elif soc < 0.10:
            ocv_base = 11.80 + (soc / 0.10) * 0.10
        elif soc < 0.25:
            ocv_base = 11.90 + ((soc - 0.10) / 0.15) * 0.15
        elif soc < 0.50:
            ocv_base = 12.05 + ((soc - 0.25) / 0.25) * 0.25
        elif soc < 0.75:
            ocv_base = 12.30 + ((soc - 0.50) / 0.25) * 0.20
        elif soc < 0.90:
            ocv_base = 12.50 + ((soc - 0.75) / 0.15) * 0.10
        elif soc < 1.00:
            ocv_base = 12.60 + ((soc - 0.90) / 0.10) * 0.10
        else:
            ocv_base = 12.70
        ocv = ocv_base - 0.0035 * (temp_c - 25.0)
        r_pol = k_pol_base / max(1.0 - soc_uncl, 0.006)
        r_eff = r0_ohm + r_pol
        i_amp = -i_cc_a
        v_term = ocv - i_amp * r_eff - v1
        if v_term >= V_BOOST + CHARGER_V_TEMP_COEF * (temp_c - 25.0):
            break

        eta = (0.98 if soc < 0.70 else (0.78 if soc >= 0.90 else 0.98 + ((soc - 0.70) / 0.20) * (0.78 - 0.98))) * (eta_c_cur / eta_c0)
        d_soc = -eta * i_amp * (1.0 / 3600.0) / C_rated
        soc = min(1.0, max(0.0, soc + d_soc))
        soc_uncl = min(1.3, max(-0.2, soc_uncl + d_soc))
        e_tau = exp(-1.0 / tau)
        v1 = v1 * e_tau + r1_ohm * (1.0 - e_tau) * i_amp

        heat_target = min(15.0, k_self_heat * i_amp * i_amp * r0_mohm)
        self_heat += (heat_target - self_heat) * (1.0 / tau_therm)
        self_heat = max(0.0, min(20.0, self_heat))
        af = exp(_ARRHENIUS_K * (1.0 / _ARRHENIUS_T0 - 1.0 / (temp_c + 273.15)))
        s_total += af / 86400.0
        if soc < 0.5:
            s_disch += af / 86400.0
        sim_hours += 1.0 / 3600.0

        p_load = load_gen.step()
        t_list.append(t_global)
        I_list.append(i_amp)
        V_list.append(v_term)
        T_list.append(temp_c)
        grid_list.append(1)
        P_list.append(p_load)
        soc_list.append(soc)
        t_global += 1
        q_cc_ah += abs(i_amp) / 3600.0
        n_cc += 1
        steps += 1

    # ---- CV ----
    q_cv_ah = 0.0
    n_cv = 0
    ca60 = None
    steps = 0
    t_cv0 = 0
    tail_a = CC_TAIL_FRAC * C_rated
    while steps < MAX_PHASE_SECONDS:
        day = (sim_hours / 24.0) % 365.0
        hour = sim_hours % 24.0
        temp_amb = s_mean + s_amp * cos(_TWO_PI_365 * (day - s_peak)) + s_diurnal * cos(_TWO_PI_24 * (hour - 14.0))
        temp_c = temp_amb + self_heat
        mult_T = exp(-0.00844 * (temp_c - 25.0))
        r0_mohm = R0_full * r0_growth * (1.0 + 0.40 * (1.0 - soc)) * mult_T
        r0_ohm = r0_mohm / 1000.0
        r1_mohm = R1_full * r0_growth * (1.0 + 0.40 * (1.0 - soc) + 0.9 * max(0.0, 0.20 - soc) / 0.20) * mult_T
        r1_ohm = r1_mohm / 1000.0
        tau = max(1.0, r1_ohm * C1)
        if soc <= 0.0:
            ocv_base = 11.80
        elif soc < 0.10:
            ocv_base = 11.80 + (soc / 0.10) * 0.10
        elif soc < 0.25:
            ocv_base = 11.90 + ((soc - 0.10) / 0.15) * 0.15
        elif soc < 0.50:
            ocv_base = 12.05 + ((soc - 0.25) / 0.25) * 0.25
        elif soc < 0.75:
            ocv_base = 12.30 + ((soc - 0.50) / 0.25) * 0.20
        elif soc < 0.90:
            ocv_base = 12.50 + ((soc - 0.75) / 0.15) * 0.10
        elif soc < 1.00:
            ocv_base = 12.60 + ((soc - 0.90) / 0.10) * 0.10
        else:
            ocv_base = 12.70
        ocv = ocv_base - 0.0035 * (temp_c - 25.0)
        r_pol = k_pol_base / max(1.0 - soc_uncl, 0.006)
        r_eff = r0_ohm + r_pol
        v_target = V_BOOST + CHARGER_V_TEMP_COEF * (temp_c - 25.0)
        i_amp = (ocv - v1 - v_target) / r_eff
        i_amp = max(-i_cc_a, i_amp) * ca_mult
        if abs(i_amp) < tail_a:
            break

        eta = (0.98 if soc < 0.70 else (0.78 if soc >= 0.90 else 0.98 + ((soc - 0.70) / 0.20) * (0.78 - 0.98))) * (eta_c_cur / eta_c0)
        d_soc = -eta * i_amp * (1.0 / 3600.0) / C_rated
        soc = min(1.0, max(0.0, soc + d_soc))
        soc_uncl = min(1.3, max(-0.2, soc_uncl + d_soc))
        e_tau = exp(-1.0 / tau)
        v1 = v1 * e_tau + r1_ohm * (1.0 - e_tau) * i_amp
        v_term = ocv - i_amp * r_eff - v1

        heat_target = min(15.0, k_self_heat * i_amp * i_amp * r0_mohm)
        self_heat += (heat_target - self_heat) * (1.0 / tau_therm)
        self_heat = max(0.0, min(20.0, self_heat))
        af = exp(_ARRHENIUS_K * (1.0 / _ARRHENIUS_T0 - 1.0 / (temp_c + 273.15)))
        s_total += af / 86400.0
        if soc < 0.5:
            s_disch += af / 86400.0
        sim_hours += 1.0 / 3600.0

        p_load = load_gen.step()
        t_list.append(t_global)
        I_list.append(i_amp)
        V_list.append(v_term)
        T_list.append(temp_c)
        grid_list.append(1)
        P_list.append(p_load)
        soc_list.append(soc)
        t_global += 1
        q_cv_ah += abs(i_amp) / 3600.0
        if t_cv0 == 60:
            ca60 = abs(i_amp)
        t_cv0 += 1
        n_cv += 1
        steps += 1

    st.soc, st.soc_uncl, st.v1 = soc, soc_uncl, v1
    st.self_heat, st.sim_hours, st.t_global = self_heat, sim_hours, t_global
    st.s_total_cum, st.s_disch_cum = s_total, s_disch
    st.hours_since_full = 0.0
    return dict(
        q_chg_ah=q_cc_ah + q_cv_ah,
        n=n_cc + n_cv,
        ca60=ca60 if ca60 is not None else (abs(I_list[-1]) if I_list else 0.0),
    )


def _simulate_float(bp, st, load_gen, duration_s, buf):
    soc = st.soc
    soc_uncl = st.soc_uncl
    v1 = st.v1
    self_heat = st.self_heat
    sim_hours = st.sim_hours
    t_global = st.t_global
    r0_growth = st.r0_growth_mult
    s_total = st.s_total_cum
    s_float = st.s_float_cum
    s_disch = st.s_disch_cum
    eta_c_cur = st.eta_c_current
    hours_since_full = st.hours_since_full

    C_rated = bp.C_rated
    k_pol_base = bp.k_pol_ohm_ah / C_rated
    R0_full = bp.R0_25_full_mohm
    R1_full = bp.R1_25_full_mohm
    C1 = bp.C1_farad
    k_self_heat = bp.k_self_heat
    tau_therm = bp.tau_therm_s
    eta_c0 = bp.eta_c0
    i_cc_a = bp.i_cc_a
    site = SITE_PROFILES[bp.site]
    s_mean, s_amp, s_peak, s_diurnal = site["mean"], site["seasonal_amp"], site["peak_day"], site["diurnal_amp"]

    exp = math.exp
    cos = math.cos

    t_list = buf["t"]
    I_list = buf["I"]
    V_list = buf["V"]
    T_list = buf["T"]
    grid_list = buf["grid"]
    P_list = buf["P_load"]
    soc_list = buf["soc"]

    for _ in range(duration_s):
        day = (sim_hours / 24.0) % 365.0
        hour = sim_hours % 24.0
        temp_amb = s_mean + s_amp * cos(_TWO_PI_365 * (day - s_peak)) + s_diurnal * cos(_TWO_PI_24 * (hour - 14.0))
        temp_c = temp_amb + self_heat

        mult_T = exp(-0.00844 * (temp_c - 25.0))
        r0_mohm = R0_full * r0_growth * (1.0 + 0.40 * (1.0 - soc)) * mult_T
        r0_ohm = r0_mohm / 1000.0
        r1_mohm = R1_full * r0_growth * (1.0 + 0.40 * (1.0 - soc) + 0.9 * max(0.0, 0.20 - soc) / 0.20) * mult_T
        r1_ohm = r1_mohm / 1000.0
        tau = max(1.0, r1_ohm * C1)
        if soc <= 0.0:
            ocv_base = 11.80
        elif soc < 0.10:
            ocv_base = 11.80 + (soc / 0.10) * 0.10
        elif soc < 0.25:
            ocv_base = 11.90 + ((soc - 0.10) / 0.15) * 0.15
        elif soc < 0.50:
            ocv_base = 12.05 + ((soc - 0.25) / 0.25) * 0.25
        elif soc < 0.75:
            ocv_base = 12.30 + ((soc - 0.50) / 0.25) * 0.20
        elif soc < 0.90:
            ocv_base = 12.50 + ((soc - 0.75) / 0.15) * 0.10
        elif soc < 1.00:
            ocv_base = 12.60 + ((soc - 0.90) / 0.10) * 0.10
        else:
            ocv_base = 12.70
        ocv = ocv_base - 0.0035 * (temp_c - 25.0)
        r_pol = k_pol_base / max(1.0 - soc_uncl, 0.006)
        r_eff = r0_ohm + r_pol
        v_target = V_FLOAT + CHARGER_V_TEMP_COEF * (temp_c - 25.0)
        i_amp = (ocv - v1 - v_target) / r_eff
        i_amp = max(-i_cc_a * 0.3, min(0.02 * C_rated, i_amp))

        if soc < 0.70:
            eta_base = 0.98
        elif soc >= 0.90:
            eta_base = 0.78
        else:
            eta_base = 0.98 + ((soc - 0.70) / 0.20) * (0.78 - 0.98)
        eta = eta_base * (eta_c_cur / eta_c0) if i_amp < 0 else 1.0
        d_soc = -eta * i_amp * (1.0 / 3600.0) / C_rated
        soc = min(1.0, max(0.0, soc + d_soc))
        soc_uncl = min(1.3, max(-0.2, soc_uncl + d_soc))
        e_tau = exp(-1.0 / tau)
        v1 = v1 * e_tau + r1_ohm * (1.0 - e_tau) * i_amp
        v_term = ocv - i_amp * r_eff - v1

        heat_target = min(15.0, k_self_heat * i_amp * i_amp * r0_mohm)
        self_heat += (heat_target - self_heat) * (1.0 / tau_therm)
        self_heat = max(0.0, min(20.0, self_heat))
        af = exp(_ARRHENIUS_K * (1.0 / _ARRHENIUS_T0 - 1.0 / (temp_c + 273.15)))
        d_days = af / 86400.0
        s_total += d_days
        s_float += d_days
        if soc < 0.5:
            s_disch += d_days
        sim_hours += 1.0 / 3600.0

        p_load = load_gen.step()
        t_list.append(t_global)
        I_list.append(i_amp)
        V_list.append(v_term)
        T_list.append(temp_c)
        grid_list.append(1)
        P_list.append(p_load)
        soc_list.append(soc)
        t_global += 1
        hours_since_full += 1.0 / 3600.0

    st.soc, st.soc_uncl, st.v1 = soc, soc_uncl, v1
    st.self_heat, st.sim_hours, st.t_global = self_heat, sim_hours, t_global
    st.s_total_cum, st.s_float_cum, st.s_disch_cum = s_total, s_float, s_disch
    st.hours_since_full = hours_since_full


def _fast_forward(bp, st, hours):
    if hours <= 0:
        return
    temp_mid = _ambient_now(bp, st)
    _step_calendar(st, hours)
    temp_mid2 = _ambient_now(bp, st)
    af = 0.5 * (arrhenius_af(temp_mid) + arrhenius_af(temp_mid2))
    d_days = af * hours / 24.0
    st.s_total_cum += d_days
    st.s_float_cum += d_days
    st.hours_since_full += hours
    st.self_heat = 0.0
    st.t_global += int(hours * 3600)  # keep t monotonic across the skipped span


def simulate_battery(battery_id, master_seed, out_dir, max_cycles, cycle_hours_range,
                      label_noise_std, sensor_noise, float_cap_hours):
    rng = np.random.default_rng(master_seed * 1_000_003 + battery_id)
    bp = BatteryParams(battery_id, rng)
    st = _BatteryState(bp)
    load_gen = _LoadGen(rng)
    st.sim_hours = float(rng.uniform(0.0, 365.0)) * 24.0

    csv_path = os.path.join(out_dir, "battery_%03d.csv" % battery_id)
    if os.path.exists(csv_path):
        os.remove(csv_path)

    cycle_rows = []  # per-cycle debug/manifest info (not written to the 1Hz stream)
    header_written = False

    for k in range(max_cycles):
        soh_before = 100.0 * st.capacity_fade_frac
        if soh_before <= SOH_STOP_FLOOR:
            break

        cycle_target_hours = float(rng.uniform(*cycle_hours_range))
        day_of_year = (st.sim_hours / 24.0) % 365.0
        rate_today = build_seasonal_rate(day_of_year, bp.base_outage_rate, bp.seasonal_phase_day)
        gap_hours = float(rng.exponential(24.0 / rate_today))
        outage_hours = float(np.clip(rng.lognormal(mean=0.0, sigma=0.6), 0.2, 6.0))

        t_full_k = st.hours_since_full

        buf = {c: [] for c in ("t", "I", "V", "T", "grid", "P_load", "soc")}
        s_total_before = st.s_total_cum
        s_disch_before = st.s_disch_cum

        dis_stats = _simulate_discharge(bp, st, load_gen, int(outage_hours * 3600), buf)
        chg_stats = _simulate_charge(bp, st, load_gen, buf)

        charge_hours = chg_stats["n"] / 3600.0
        gap_remaining_hours = max(0.0, gap_hours - outage_hours - charge_hours)
        float_budget_hours = max(0.25, cycle_target_hours - outage_hours - charge_hours)
        float_budget_hours = min(float_budget_hours, float_cap_hours)
        emitted_float_hours = min(gap_remaining_hours, float_budget_hours)
        fastforward_hours = max(0.0, gap_remaining_hours - emitted_float_hours)

        _simulate_float(bp, st, load_gen, int(emitted_float_hours * 3600), buf)
        _fast_forward(bp, st, fastforward_hours)

        # ---- per-cycle ageing update (Schiffer weighted-Ah + Arrhenius + sulphation) ----
        q_dis_ah = dis_stats["q_dis_ah"]
        dod_k = dis_stats["dod_k"]
        w_k = 1.0 + SCHIFFER_A * max(0.0, dod_k - 0.5) + SCHIFFER_B * max(0.0, math.log((t_full_k + 1e-6) / 24.0 + 1.0))
        q_w_k = q_dis_ah * w_k
        d_s_total = st.s_total_cum - s_total_before
        d_s_disch = st.s_disch_cum - s_disch_before

        st.capacity_fade_frac -= (bp.k_cap_wear * q_w_k / bp.C_rated + bp.k_cap_therm * d_s_total)
        st.capacity_fade_frac = float(np.clip(st.capacity_fade_frac, 0.30, 1.05))
        st.r0_growth_mult += (bp.k_r0_wear * q_w_k / bp.C_rated + bp.k_r0_therm * d_s_total)
        st.sulfation += bp.k_sulf * d_s_disch
        st.eta_c_current = float(np.clip(bp.eta_c0 - bp.k_eta * st.sulfation, 0.65, bp.eta_c0))
        st.ca_mult_current = float(np.clip(1.0 - bp.k_ca * st.sulfation, 0.25, 1.0))
        st.efc_cum += q_dis_ah / bp.C_rated

        soh_row = soh_before
        if label_noise_std > 0:
            soh_row = float(np.clip(soh_row + rng.normal(0.0, label_noise_std), 0.0, 100.0))

        n_rows = len(buf["t"])
        if n_rows == 0:
            continue
        arr_I = np.asarray(buf["I"], dtype=np.float64)
        arr_V = np.asarray(buf["V"], dtype=np.float64)
        arr_T = np.asarray(buf["T"], dtype=np.float64)
        if sensor_noise:
            arr_I = arr_I + rng.normal(0.0, 0.01, n_rows)
            arr_V = arr_V + rng.normal(0.0, 0.003, n_rows)
            arr_T = arr_T + rng.normal(0.0, 0.15, n_rows)
        arr_V = np.clip(arr_V, V_CUTOFF, 14.8)

        df = pd.DataFrame({
            "t": np.asarray(buf["t"], dtype=np.int64),
            "I": (-arr_I).astype(np.float32),  # flip to contract convention: +charge -discharge
            "V": arr_V.astype(np.float32),
            "T": arr_T.astype(np.float32),
            "grid": np.asarray(buf["grid"], dtype=np.int8),
            "P_load": np.asarray(buf["P_load"], dtype=np.float32),
            "soc_true": np.asarray(buf["soc"], dtype=np.float32),
            "soh_true": np.full(n_rows, soh_row, dtype=np.float32),
        })
        df.to_csv(csv_path, mode="a", header=not header_written, index=False)
        header_written = True

        cycle_rows.append(dict(
            battery_id=battery_id, cycle_idx=k, soh_true=soh_before,
            q_dis_ah=q_dis_ah, dod_k=dod_k, t_full_h=t_full_k, efc_cum=st.efc_cum,
            eta_c=st.eta_c_current, ca_mult=st.ca_mult_current, r0_growth=st.r0_growth_mult,
        ))

    return bp, cycle_rows


def _write_manifest(out_dir, rows):
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out_dir, "manifest.csv"), index=False)


def _write_cycle_debug(out_dir, all_cycle_rows):
    df = pd.DataFrame(all_cycle_rows)
    df.to_csv(os.path.join(out_dir, "sim_cycle_debug.csv"), index=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=24, help="number of batteries to simulate")
    ap.add_argument("--out", type=str, default="data/sim_1hz/", help="output directory")
    ap.add_argument("--seed", type=int, default=0, help="master RNG seed")
    ap.add_argument("--cycles", type=int, default=300, help="max outage/recharge cycles per battery")
    ap.add_argument("--cycle-hours-min", type=float, default=8.0)
    ap.add_argument("--cycle-hours-max", type=float, default=12.0)
    ap.add_argument("--float-cap-hours", type=float, default=3.0,
                     help="max float duration emitted at 1Hz before fast-forwarding calendar time")
    ap.add_argument("--label-noise-std", type=float, default=0.0,
                     help="stddev (pts) of optional Gaussian noise added to soh_true per cycle; "
                          "design spec offers +-1.5pt as an option, e.g. --label-noise-std 1.5")
    ap.add_argument("--no-sensor-noise", action="store_true",
                     help="disable small INA228-like sensor noise on I/V/T")
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    t_start = time.time()
    manifest_rows = []
    all_cycle_rows = []
    for i in range(args.n):
        bp, cycle_rows = simulate_battery(
            battery_id=i,
            master_seed=args.seed,
            out_dir=args.out,
            max_cycles=args.cycles,
            cycle_hours_range=(args.cycle_hours_min, args.cycle_hours_max),
            label_noise_std=args.label_noise_std,
            sensor_noise=not args.no_sensor_noise,
            float_cap_hours=args.float_cap_hours,
        )
        n_cycles_run = len(cycle_rows)
        soh_end = cycle_rows[-1]["soh_true"] if cycle_rows else 100.0
        print("battery %03d: C=%.0f Ah, site=%s, cycles=%d, final soh_true=%.1f%%, elapsed=%.1fs"
              % (i, bp.C_rated, bp.site, n_cycles_run, soh_end, time.time() - t_start))
        manifest_rows.append(dict(
            battery_id=i, C_rated_Ah=bp.C_rated, I10_A=bp.I10, I20_A=bp.I20,
            R0_25_full_mohm=bp.R0_25_full_mohm, R1_25_full_mohm=bp.R1_25_full_mohm,
            C1_farad=bp.C1_farad, peukert_n=bp.peukert_n, eta_inv=bp.eta_inv, eta_c0=bp.eta_c0,
            i_cc_frac=bp.i_cc_frac, site=bp.site, base_outage_rate_per_day=bp.base_outage_rate,
            n_cycles=n_cycles_run, final_soh_true=soh_end,
        ))
        all_cycle_rows.extend(cycle_rows)

    _write_manifest(args.out, manifest_rows)
    _write_cycle_debug(args.out, all_cycle_rows)
    print("done: %d batteries in %.1fs -> %s" % (args.n, time.time() - t_start, args.out))


if __name__ == "__main__":
    main()
