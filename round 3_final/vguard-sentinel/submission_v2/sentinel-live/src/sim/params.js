// Every number here is taken from the team's own documents:
//   prototype/01 (inverter states, windows, charging), prototype/02–05 (parts, bench plan),
//   design/03 (charge setpoints), design/05 (autopilot thresholds), design/06 (NILM),
//   design/07 (PQ), design/02 (grades), dashboard fixtures, household_simulation defaults.

export const P = {
  // Battery / inverter (prototype 01 §3, household_simulation README)
  V_NOM: 12,
  ETA_INV: 0.85,             // inverter efficiency
  ETA_CHG: 0.9,              // charge acceptance
  CUTOFF_SOC: 0.2,           // 80 % usable DoD → low-battery cut-off (S4)
  IDLE_W: 5,                 // fixtures/timeline.json idle_load_w
  TRANSFER_MS: 8,            // < 10 ms on V-Guard Prime (UPS mode)
  MAINS_RETURN_S: 5,         // S6: mains stable for a few seconds
  INV_RATING_W: 800,         // Prime 1150: 1000 VA / 800 W

  // Charging (prototype 01 §3 S7, design 03 table)
  BULK_C: 0.1,               // bulk ≈ 10 % of Ah
  V_ABS: 14.4,
  V_FLOAT: 13.5,
  TEMP_COEF: -0.024,         // −24 mV/°C per 12 V (Victron default −4 mV/°C/cell), ref 25 °C
  T_REF: 25,
  DERATE_START: 45,          // begin current derating
  DERATE_STOP: 58,           // hard stop ≈ 58 °C (design 12 D14)

  // Autopilot (design 05 §4.2)
  T3_SHED: 0.40, T3_RESTORE: 0.55,
  T2_SHED: 0.55, T2_RESTORE: 0.70,
  EVAL_S: 60,                // re-evaluation interval
  MIN_OFF_DWELL_S: 180,      // 3–5 min anti short-cycle
  MIN_ON_DWELL_S: 300,       // controller.py dwell_on_s
  ENDURANCE_MARGIN: 1.2,     // E_avail < 1.2 × forecast T1 Wh → shed T3
  ALERTS: [0.5, 0.35, 0.2],

  // Outage detection (design 05 §7)
  S1_PU: 0.1,                // mains Urms < 0.1 pu
  S1_DEBOUNCE_S: 1.5,        // sustained 1–2 s
  S1_ALONE_S: 5,             // s1 alone for ≥ N2
  RESTORE_PU: 0.9,
  RESTORE_DEBOUNCE_S: 15,    // 10–30 s
  S3_DISCHARGE_A: 1.0,

  // Fail-safe (prototype 03 C8, design 05 §6)
  SUPERVISOR_S: 2,           // heartbeat missing 2 s → all coils off → loads ON
  REBOOT_S: 6,

  // NILM (design 06)
  NILM_PTH_W: 25,

  // Grid
  V_MAINS: 230,
  UPS_WIN: [180, 260],
  NORMAL_WIN: [90, 290],
};

// SoH/RUL grades straight from dashboard/fixtures/soh_replay_steps.json
export const GRADES = [
  { grade: 'COLLECTING', n_weeks: 2, confidence: 'LOW', soh_p10: 90, soh_p50: 95, soh_p90: 98, rul_p10: 120, rul_p50: 180, rul_p90: 250 },
  { grade: 'HEALTHY', n_weeks: 40, confidence: 'MED', soh_p10: 88, soh_p50: 93, soh_p90: 97, rul_p10: 60, rul_p50: 90, rul_p90: 130 },
  { grade: 'DEGRADING', n_weeks: 70, confidence: 'MED', soh_p10: 78, soh_p50: 83, soh_p90: 88, rul_p10: 20, rul_p50: 30, rul_p90: 45 },
  { grade: 'REPLACE', n_weeks: 95, confidence: 'HIGH', soh_p10: 62, soh_p50: 68, soh_p90: 74, rul_p10: 6, rul_p50: 9, rul_p90: 14 },
];

// Appliance library (design 06 table + prototype 05 bench loads + dashboard channels)
export const KINDS = {
  tube:   { name: 'LED tube light', w: 20, q: 4 },
  bulb:   { name: 'LED bulb', w: 9, q: 2 },
  fan:    { name: 'Ceiling fan', w: 60, q: 30 },
  tv:     { name: 'LED TV', w: 70, q: 12 },
  router: { name: 'Wi-Fi router', w: 10, q: 1 },
  fridge: { name: 'Fridge', w: 120, q: 100 },
  iron:   { name: 'Iron', w: 500, q: 0 },
  cpap:   { name: 'CPAP', w: 40, q: 8 },
  laptop: { name: 'Laptop', w: 45, q: 6 },
  ac:     { name: 'Split AC', w: 1450, q: 600, nonInverter: true },
};

export const TIER_META = {
  T1: { label: 'Keep', color: '#2BD67B' },
  T2: { label: 'Defer', color: '#FDC300' },
  T3: { label: 'Shed', color: '#F39200' },
  MED: { label: 'Never shed', color: '#FF4D6D' },
  NI: { label: 'Mains only', color: '#8A94A6' },
};

export const COLORS = {
  gold: '#FDC300',
  orange: '#F39200',
  grid: '#FDC300',       // mains-sourced power
  battery: '#22D3EE',    // battery-sourced power
  data: '#C084FC',       // Sentinel sensing / control lines
  good: '#2BD67B',
  bad: '#FF4D6D',
};
