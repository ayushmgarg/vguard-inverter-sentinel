"""Physics tables and per-battery parameter randomisation for the duty-cycle simulator.

References (see sim/README.md for the full mapping):
- design 01 (Battery-State-Estimation) SS2.1 OCV table, SS1.5 R0/R1/C1 typical values,
  SS2.5 Peukert.
- design 02 (TinyML-SoH-RUL-Pipeline) SS4.3 duty-cycle simulator spec, SS1.5 Arrhenius LUT.
"""
import math

import numpy as np

# ---------------------------------------------------------------------------
# OCV(SoC) table, design 01 SS2.1 -- tubular deep-cycle default (12 V pack terminal V)
# ---------------------------------------------------------------------------
SOC_PTS = np.array([0.00, 0.10, 0.25, 0.50, 0.75, 0.90, 1.00])
OCV_PTS = np.array([11.80, 11.90, 12.05, 12.30, 12.50, 12.60, 12.70])
OCV_TEMP_COEF_V_PER_C = -0.0035  # ~ -3 to -4 mV/degC per 12V pack, design 01 SS2.2

V_BOOST = 14.4       # charger CC->CV target, design 02 SS1.0
V_FLOAT = 13.7        # float regulation voltage
V_CUTOFF = 10.5        # inverter low-voltage cutoff (contract sane range floor is 10.5)
CHARGER_V_TEMP_COEF = -0.024  # V/degC per 12V pack (design 01 SS5a, reused for V_boost/V_float)

CC_TAIL_FRAC = 0.02       # CV->float transition, I < 2% C10 (design 02 SS1.0)

ARRHENIUS_EA_OVER_R = 6400.0  # design 02 SS1.5, doubles per ~10 degC
T_REF_K = 298.15


def ocv_scalar(soc, temp_c):
    """Piecewise-linear OCV(SoC) + temperature offset, scalar, hot-loop friendly."""
    if soc <= 0.0:
        v = OCV_PTS[0]
    elif soc >= 1.0:
        v = OCV_PTS[-1]
    else:
        # SOC_PTS has 7 points; linear scan is cheap and branch-predictable
        i = 0
        while soc > SOC_PTS[i + 1]:
            i += 1
        frac = (soc - SOC_PTS[i]) / (SOC_PTS[i + 1] - SOC_PTS[i])
        v = OCV_PTS[i] + frac * (OCV_PTS[i + 1] - OCV_PTS[i])
    return v + OCV_TEMP_COEF_V_PER_C * (temp_c - 25.0)


def r0_soc_mult(soc):
    """+40% empty vs full (design 01 SS1.5), linear in SoC."""
    return 1.0 + 0.40 * (1.0 - soc)


def r1_soc_mult(soc):
    """Same base rise as R0 plus a sharp knee below 20% SoC (design 01 SS1.5)."""
    base = 1.0 + 0.40 * (1.0 - soc)
    knee = 0.9 * max(0.0, 0.20 - soc) / 0.20
    return base + knee


# fitted so mult(-18C)/mult(30C) == 1.5, per design 01 SS1.5 ("+50% cold")
_R_TEMP_K = 0.00844


def r_temp_mult(temp_c):
    return math.exp(-_R_TEMP_K * (temp_c - 25.0))


def f_temp_capacity(temp_c):
    """Capacity temperature derating, ~100% at 25C, mid-80s% at 0C (design 01 SS2.5)."""
    f = 1.0 + 0.006 * (temp_c - 25.0)
    return min(1.05, max(0.55, f))


def peukert_mult(i_abs_a, i20_a, n):
    """Usable-capacity multiplier from Peukert's law (design 01 SS2.5)."""
    if i_abs_a <= i20_a or i_abs_a <= 1e-6:
        return 1.0
    m = (i20_a / i_abs_a) ** (n - 1.0)
    return max(0.55, m)


def r_polarization_ohm(soc, discharging, k_pol_ohm_ah, c_rated_ah):
    """Shepherd-style polarisation term (design 02 SS4.3: 'Shepherd/Thevenin'): an
    extra series-resistance-like term that diverges near the empty (discharge) or
    full (charge) boundary, capturing the steep voltage swing a linear R0/R1 alone
    cannot -- this is what drives a realistic CC->CV transition near V_boost and the
    inverter cutoff near V_cutoff."""
    denom = max(soc, 0.03) if discharging else max(1.0 - soc, 0.006)
    base_ohm = k_pol_ohm_ah / c_rated_ah
    return base_ohm / denom


def eta_charge_base(soc):
    """Charge coulombic efficiency vs SoC, design 01 SS1.3: ~0.98 below 70%, tapering
    to 0.70-0.85 above 90% (gassing)."""
    if soc < 0.70:
        return 0.98
    if soc >= 0.90:
        return 0.78
    frac = (soc - 0.70) / 0.20
    return 0.98 + frac * (0.78 - 0.98)


def arrhenius_af(temp_c):
    tk = temp_c + 273.15
    return math.exp(ARRHENIUS_EA_OVER_R * (1.0 / T_REF_K - 1.0 / tk))


# ---------------------------------------------------------------------------
# Ambient temperature profiles -- synthetic Chennai / Delhi diurnal + seasonal
# ---------------------------------------------------------------------------
SITE_PROFILES = {
    # mean_C, seasonal_amp_C, peak_day (day-of-year of the hottest month), diurnal_amp_C
    "chennai": dict(mean=29.0, seasonal_amp=3.5, peak_day=130, diurnal_amp=4.0),
    "delhi": dict(mean=26.0, seasonal_amp=9.5, peak_day=160, diurnal_amp=8.0),
}


def ambient_temp_c(day_of_year, hour_of_day, site, noise=0.0):
    p = SITE_PROFILES[site]
    seasonal = p["seasonal_amp"] * math.cos(2 * math.pi * (day_of_year - p["peak_day"]) / 365.0)
    diurnal = p["diurnal_amp"] * math.cos(2 * math.pi * (hour_of_day - 14.0) / 24.0)
    return p["mean"] + seasonal + diurnal + noise


# ---------------------------------------------------------------------------
# Per-battery domain randomisation
# ---------------------------------------------------------------------------
class BatteryParams:
    """One randomly-drawn tubular lead-acid battery + its randomised ageing severity.

    All ranges are design-doc typical values (01 SS1.5, SS2.5; 02 SS4.3) sampled per
    battery ("domain randomisation per battery").
    """

    def __init__(self, battery_id, rng):
        self.battery_id = battery_id
        self.C_rated = float(rng.uniform(100.0, 230.0))  # Ah, C10 basis
        self.I10 = self.C_rated / 10.0
        self.I20 = self.C_rated / 20.0

        k_r0 = rng.uniform(0.6, 1.2)     # Ohm*Ah, design 01 SS1.5
        k_r1 = k_r0 * rng.uniform(0.5, 1.0)
        self.R0_25_full_mohm = 1000.0 * k_r0 / self.C_rated
        self.R1_25_full_mohm = 1000.0 * k_r1 / self.C_rated
        tau = rng.uniform(20.0, 120.0)   # s
        r1_ohm = self.R1_25_full_mohm / 1000.0
        self.C1_farad = tau / max(r1_ohm, 1e-6)

        self.k_pol_ohm_ah = float(rng.uniform(1.0, 2.2))    # Shepherd polarisation severity, Ohm*Ah
        self.peukert_n = float(rng.uniform(1.15, 1.35))
        self.eta_inv = float(rng.uniform(0.83, 0.87))       # inverter efficiency ~0.85
        self.eta_c0 = float(rng.uniform(0.90, 0.97))        # BoL coulombic efficiency

        self.i_cc_frac = float(rng.uniform(0.10, 0.15))     # charger CC, frac of C10
        self.i_cc_a = self.i_cc_frac * self.C_rated

        self.site = "chennai" if rng.uniform() < 0.5 else "delhi"
        self.base_outage_rate = float(rng.uniform(0.3, 3.0))  # /day, design 02 SS4.3
        self.seasonal_phase_day = float(rng.uniform(0.0, 365.0))

        self.k_self_heat = float(rng.uniform(0.02, 0.06))   # deg C per (A^2 * mOhm)
        self.tau_therm_s = float(rng.uniform(600.0, 1800.0))

        # --- ageing severity, randomised so SoH fades to <=80% within the
        # accelerated cycle budget for a meaningful (not all) fraction of batteries ---
        # capacity_fade_frac and r0_growth_mult are dimensionless (0-1 / >=1) states,
        # updated once per cycle by k * (this cycle's weighted-Ah/C_rated or stress-days);
        # ranges tuned (see sim/README.md) so soh_true crosses 80% within roughly
        # 80-350 cycles for a meaningful (not all) fraction of the randomised fleet.
        self.k_cap_wear = float(rng.uniform(0.0009, 0.0026))   # fade fraction per (weighted Ah / C_rated)
        self.k_cap_therm = float(rng.uniform(0.0006, 0.0022))  # fade fraction per 25C-equiv stress-day
        self.k_r0_wear = float(rng.uniform(0.0012, 0.0035))    # R0 growth mult per (weighted Ah / C_rated)
        self.k_r0_therm = float(rng.uniform(0.0004, 0.0012))
        self.k_sulf = float(rng.uniform(0.010, 0.030))         # sulphation index growth per 25C-equiv discharge-day
        self.k_eta = float(rng.uniform(0.006, 0.016))          # eta_c decline per sulphation unit
        self.k_ca = float(rng.uniform(0.020, 0.050))           # charge-acceptance decline per sulphation unit
        self.label_noise_pts = 1.5


def build_seasonal_rate(day_of_year, base_rate, phase_day):
    """Seasonal modulation of the Poisson outage rate, design 02 SS4.3 (0.3-3/day)."""
    factor = 1.0 + 0.5 * math.sin(2 * math.pi * (day_of_year - phase_day) / 365.0)
    rate = base_rate * factor
    return min(3.0, max(0.15, rate))
