"""ekf/params.py — EKF tuning defaults, design 01 §3.2/§3.3/§5c/§8.

Every default below cites the design-doc range it was drawn from (usually
the midpoint of a stated band). These are prototype defaults for a 150 Ah
tubular flooded battery; a real deployment loads per-SKU values selected at
commissioning (01 §2.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EKFParams:
    # --- capacity / Peukert, 01 §2.5 ---
    q_rated_ah: float = 150.0
    peukert_n: float = 1.25

    # --- noise, 01 §3.2 / §8 ---
    r_v: float = 0.004 ** 2          # sigma_v 2-5 mV, mid 4 mV
    q_soc: float = 5e-5 ** 2         # 1e-5..1e-4, mid
    q_v1: float = 0.010 ** 2         # 5-15 mV, mid 10 mV
    q_r0_idle: float = 1e-10         # ordinary ticks: no random drift
    q_r0_event: float = 0.5e-3 ** 2  # opened for the single update after a qualifying event
    r0_event_meas_var: float = 1.0e-3 ** 2  # uncertainty on one R_int event estimate
    chi2_gate: float = 9.0           # ~3 sigma, 01 §3.4 item 1

    # --- full detection (charger ON), 01 §5a/§5c ---
    v_full_25c: float = 13.5
    v_full_tempco_v_per_c: float = -0.024  # ~-24 mV/C per 12V
    i_tail_frac_c20: float = 0.015   # 1-2% C20, mid
    t_full_dwell_s: float = 1200.0   # 10-30 min, mid (20 min)

    # --- true rest-OCV anchor (charger OFF only -- H30 fix), 01 §5b/§5c ---
    i_rest_frac_c20: float = 0.0075  # 0.5-1% C20, mid
    t_rest_prov_s: float = 4500.0    # 60-90 min, mid (75 min)
    t_rest_high_s: float = 18000.0   # 4-6 h, mid (5 h)
    r_rest_med: float = 0.020 ** 2
    r_rest_high: float = 0.004 ** 2

    # --- R_int event estimator, 01 §6 ---
    di_thresh_frac_c20: float = 0.075  # 5-10% C20, mid
    r0_min_events: int = 20            # 01 §6.2 (20-50 window, apply from 20)
    r0_max_buffer: int = 50
    r0_sanity_envelope_mult: float = 3.0  # 01 §3.4 item 5

    # --- divergence guards, 01 §3.4 ---
    soc_bounds: tuple = (0.0, 1.0)
    r0_bounds_ohm: tuple = (1e-3, 50e-3)
    p_floor: tuple = (1e-9, 1e-8, 1e-13)
    p_ceiling: tuple = (0.25, 0.01, 0.02 ** 2)
    cross_check_thresh: float = 0.09   # 8-10%, item 4
    cross_check_dwell_s: float = 300.0
    cross_check_q_inflate: float = 5.0

    # --- zero-current auto-cal, 01 §4 ---
    zero_cal_alpha: float = 0.02
    zero_cal_i_thresh_a: float = 0.05

    # --- coulombic efficiency / capacity per cycle, 01 §7 ---
    min_dod_for_capacity_cycle: float = 0.30

    # --- initialisation, 01 §3.3 ---
    p0_soc_var: float = 0.20 ** 2
    p0_v1_var: float = 0.05 ** 2
    p0_r0_var_frac: float = 0.30

    def __post_init__(self):
        self.c20_a = self.q_rated_ah / 20.0
