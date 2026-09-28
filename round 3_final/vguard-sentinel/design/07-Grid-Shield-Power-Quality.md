# 07 — Engine 3b: Grid Shield — Power-Quality Detection (worked out to a T)

**Resolves Gap Register:** H19 (RMS method, thresholds, event schema, storage, alerting, Class-S honesty).

## 1. Measurement method
- **Half-cycle sliding RMS, `Urms(1/2)`** — one full-cycle RMS refreshed every half-cycle (a new value every 10 ms at 50 Hz). This is one of the two methods IEC 61000-4-30 permits for dip/swell detection (the Class-A method); **Class S** (survey grade, the right tier for a consumer device) permits `Urms(1/2)` or `Urms(1)`.
- **Frequency** — zero-crossing period timing over a rolling 10-cycle window; flag outside 50 Hz ± 3 % (configurable to the CEA band).
- **THD** — 4-cycle (80 ms) FFT on the voltage waveform, harmonics to the 25th–40th order per ADC budget (IEC 61000-4-7 windowing convention).
- Source signal for `Urms(1/2)`, frequency and the THD FFT: the **AMC1311-isolated mains divider sampled by the ESP32-S3 ADC at ~4 kS/s** (10 §3). The internal ADC is not metering-grade (06 §1.4), but sag/swell/interruption thresholds are 10 %-class and a 4-cycle FFT THD indicator is Class-S-like, so this path is adequate here — and it is independent of the SPI/AFE, so outage detection survives an AFE fault. The **ATM90E32AS sag/zero-crossing flags cross-check** every event; if certified THD/harmonic registers are wanted, the pin-compatible ATM90E36A provides them (D4 in 12).

## 2. Classification thresholds (IEEE 1159 conventions)
| Event | Magnitude | Duration buckets |
|---|---|---|
| Sag (dip) | 0.1–0.9 pu | instantaneous 0.5–30 cycles (10 ms–0.5 s) · momentary 30 cycles–3 s · temporary 3 s–1 min |
| Swell | > 1.1 pu | same buckets |
| Interruption | < 0.1 pu | momentary 0.5 cycles–3 s · temporary 3 s–1 min · sustained > 1 min |

## 3. Event record schema (~32 B packed)
```c
struct PQEvent {
  uint32_t ts_epoch_ms;
  uint8_t  type;            // SAG | SWELL | INTERRUPTION | FREQ_DEV | THD_EXCURSION
  float    magnitude_pu;
  uint32_t duration_ms;
  float    pre_event_rms_V;
  float    post_event_rms_V;
  float    thd_pct;         // if relevant
};
```

## 4. Storage and rotation
Circular buffer in a dedicated LittleFS partition: 1000 events × 32 B ≈ 32 KB, oldest-first rotation; synced to app/cloud opportunistically. Weeks of typical event rates survive fully offline.

## 5. Alerts and "appliance-protection analytics" — what it concretely means
- **Real-time push** only when severity warrants (e.g., > 2 sags of ≥ momentary duration in 24 h) — actionable, not spam.
- **Monthly rollup**: counts of sags/swells/interruptions by duration class, worst THD, frequency-deviation events. This is the analytics: a dated, timestamped record the owner (or an insurer) can present as **evidence of utility-caused events** for warranty or damage claims — the same use industrial PQ meters serve.
- Grid Shield **does not trip or protect in real time** — the inverter's own transfer switch is faster than anything the Core can do; the value is detection, logging, alerting and evidence. (Report §8 already states this; keep it.)

## 6. Class-S vs Class-A — say it plainly
Describe Grid Shield as **"IEC 61000-4-30 Class-S-like methodology"**, never "Class A" or "61000-4-30 compliant". Class A needs calibrated instrument-transformer-grade sensing, tight aggregation-window accuracy and synchronised timing for contractual disputes — none of which a single metering AFE without certified PT/CT and without GPS/PTP time can claim. Class S exists precisely for survey-grade monitoring.

## 7. Four-step summary (judge-ready)
1. **Sample & compute half-cycle RMS** every 10 ms (Class-S-permitted method), plus a 4-cycle FFT for THD and zero-crossing timing for frequency.
2. **Classify** excursions against IEEE 1159 magnitude/duration buckets.
3. **Log** compact structured events to a rotating on-device flash buffer; sync when connected.
4. **Alert & report** — real-time push on severe events; monthly rollups as appliance-protection/warranty evidence; labelled Class-S-like, not a certified instrument.

## References
IEC 61000-4-30:2025 (IEC webstore) · Schneider Electric technical note, *IEC 61000-4-30 overview — Class A vs Class S* · EC&M, *Ranking Electrical Disturbances — Part 2 (IEEE 1159 categories)* · IEC 61000-4-7 (harmonics measurement).
