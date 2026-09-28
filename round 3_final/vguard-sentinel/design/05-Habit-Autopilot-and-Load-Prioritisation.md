# 05 — Engine 2: Habit-Learning Autopilot & Load Prioritisation (worked out to a T)

**Resolves Gap Register:** H11 (what is learned), H12 (outage prediction / pre-charge), H13 (circuit map), H14 (shedding algorithm), H15 (fail-safe wiring), H16 ("within one circuit" wording), H34 (on-device habit data), H36 (outage detection).

## 0. Two honesty calibrations (carry into every deck/answer)
- "Learns load and outage patterns" = **statistical pattern-matching on the device's own history** (EWMA-smoothed hour-of-week bins), not a general forecasting AI. Deliberate and defensible (§1.5).
- "Pre-charges ahead of a predicted outage" is an **active control action only if Sentinel can command the charger** (embedded/new-inverter SKU). On a **retrofit** it degrades to an advisory + earlier shed thresholds. Say this plainly (§2.3, and see 03 / 12).

## 1. What is learned, and how
### 1.1 Representation
**Load profile** — a 7×24 hour-of-day × day-of-week grid (168 bins), each holding an exponentially-weighted mean and variance of load power (W), from the same current channel that feeds the EKF:
```
bin[dow][hour] = { mean_W: f32, var_W: f32, n_obs: u16, last_update: u32 }
```
Updated **once per hour** (hourly average), not per ADC tick — bounds flash write amplification and matches the timescale habits change on.

**Seasonal drift** — India's residential load shifts hard by season (AC/cooler in summer, geyser in winter, monsoon outage patterns). Keep **4 seasonal grids** (Winter / Summer / Monsoon / Pre-monsoon, IMD-aligned); the active season's grid is seeded from the previous season's at transition so day-1 of a season is not a cold start.

**Outage model** — a parallel 7×24 grid:
```
outage_bin[dow][hour] = { p_outage: f32 (Beta-smoothed), dur_mean_min: f32, dur_var_min: f32, n_obs: u16 }
```
`p_outage` is Laplace/Beta-smoothed, `p = (k+1)/(n+2)` (k = outages starting in that bin, n = weeks observed) — one early outage can never lock in p=1.0, and the estimate is naturally confidence-weighted.

### 1.2 Update rule (EWMA, O(1) per sample)
```
mean_new = mean_old + α·(x − mean_old)
var_new  = (1−α)·(var_old + α·(x − mean_old)²)     # Welford-style EW variance
```
- `α_load = 0.08` (≈3-week time constant at one update/day/bin): rejects one-offs (guests, appliance left on) yet tracks a real habit shift (new AC) within a month.
- Outage probability uses count-based Beta smoothing (more honest for a rare event); `α_outage = 0.15` only for duration mean/variance.

### 1.3 Memory footprint
| Structure | Bins | B/bin | Total |
|---|---|---|---|
| Load profile, active season (RAM) | 168 | 12 | ≈2.0 KB |
| Load profile, 3 dormant seasons (flash) | 504 | 12 | ≈6.0 KB |
| Outage histogram | 168 | 16 | ≈2.7 KB |
| **Resident RAM** | | | **≈4.7 KB** (≈10.7 KB incl. flash copies) |
Journaled to NVS (wear-levelled) hourly — negligible wear over product life.

### 1.4 Cold-start defaults
Until `n_obs ≥ 14` per bin, blend a **generic Indian residential double-peak curve** (06–09 h, 18–23 h; scaled from the inverter's connected-load nameplate) with observed data, weighted `n_obs/(n_obs+14)`. `p_outage` cold-starts at an uninformative ≈5 % with wide confidence, so no aggressive pre-charge fires on thin data.

### 1.5 Why EWMA/histogram beats a neural forecaster here
- The predictable component is **scheduling, not dynamics** — Indian rotational load-shedding repeats by hour/weekday, exactly what a histogram captures.
- **Single-household load is high-variance**; predictability studies show individual-meter forecasts are far worse than aggregated ones and simple statistical baselines stay competitive with learned models (Hong & Fan tutorial review; Wang et al. smart-meter analytics review; Xu & Meng predictability-vs-aggregation).
- **Auditable**: a judge (or a warranty dispute) can read the 168-cell table; a weight matrix cannot be inspected the same way — this matters for a safety-adjacent shed/keep decision.
- No training pipeline, no drift retraining, no catastrophic mispredictions from a model under-trained on a few outages/month.

### 1.6 Optional tiny GRU — v2 only, gated
TinyML on ESP32 is feasible at small sizes (sub-5 KB quantised models run in µs; online ridge regression predicts in ~2 ms). A tiny residual model may be enabled **only if field telemetry shows exploitable structure the 168-bin table misses**, and only as a **correction term on top of the histogram baseline** — never replacing the interpretable path. Not a v1 claim.

## 2. Outage prediction — honestly
### 2.1 Estimator
```
P(outage starts in next h hours | dow, hour) = 1 − Π_{i=0}^{h−1} (1 − p_outage[dow][(hour+i) mod 24])   # default h = 3
confidence = n_obs / (n_obs + 8)   # from Beta posterior width
```
### 2.2 Can / cannot
- **Can:** repeating scheduled outages (discom load-shedding rosters) — hour/weekday-periodic by construction.
- **Cannot:** unscheduled faults (transformer trips, storms, cable faults) — **unpredictable from one household's history**; Grid Shield *reacts* to those, it does not predict them.
- **Reporting rule:** always phrase as "based on N weeks of this unit's own outage history, X % chance of a scheduled-pattern outage in the next h hours (confidence low/med/high)" — never an unconditional forecast.

### 2.3 Pre-charge logic
```
if P(outage, h=3) > 0.55 AND confidence ≥ 0.5:
    SoC_target = min(SoC_target_normal + 15 pp, 100 %)      # e.g. 70 % → 85 %
    raise T2/T3 shed thresholds by +10 pp for the predicted window
    if charger_commandable:   # embedded SKU
        request charger to run absorption/bulk now (within SoH-derived charge-rate limits)
    else:                     # retrofit SKU
        push advisory: "Scheduled-outage pattern likely 18:00–19:00 — limit heavy loads now."
```
**Embedded-vs-retrofit must be an explicit SKU decision** (Sentinel-Embedded vs Sentinel-Retrofit), not glossed over.

## 3. Circuit map & configuration
- Installer assigns each of **4 contactor channels** (app, BLE/Wi-Fi provisioning) a label ("Fridge", "Geyser", "AC-Bedroom", "Pump") and a tier **T1 keep / T2 defer / T3 shed**.
- **Hardware medical/never-shed lock**: a per-channel jumper/DIP on the driver board forces that channel to T1 in firmware regardless of app config; the app cannot override hardware.
- **Fail-safe default:** until configured, **all channels = T1** — an unconfigured unit never sheds anything nobody approved.
- Storage — NVS namespace `circuit_cfg`, one CRC-checked blob per channel:
```c
struct ChannelConfig { uint8_t channel_id; char label[24]; Tier tier; bool hw_locked_t1; uint32_t crc; };
```
CRC mismatch or missing blob → fall back to all-T1, never to a guess.

## 4. Shedding decision algorithm
### 4.1 Usable energy
```
E_usable(t) = SoH · SoC(t) · C_usable(I_fcst, T) · V_nominal      [Wh]
C_usable(I,T) = C_rated · (C_rated / (I_fcst · t_rated))^(n−1) · f_temp(T)     # Peukert correction
```
Peukert `n`: flooded lead-acid ≈1.2–1.4, AGM ≈1.05–1.15, gel ≈1.1–1.25 (Victron SmartShunt docs; Battle Born). A 100 Ah (C20) battery drained over 2 h yields roughly ~56 Ah — hence the correction. `I_fcst` = forecast T1(+T2) load ÷ V_nominal.

### 4.2 Rules — with hysteresis and dwell
| Parameter | Default | Rationale |
|---|---|---|
| Shed T3 at SoC | 40 % | lead-acid "don't routinely go below ~40–50 %" guidance |
| Restore T3 at SoC | 55 % | 15 pp hysteresis → no chatter |
| Defer T2 at SoC | 55 % | shed T2 before T3 becomes urgent |
| Restore T2 at SoC | 70 % | 15 pp hysteresis |
| Shed T1 | **never** | spec |
| Min ON dwell (compressor loads) | 5 min | short-cycle protection |
| Min OFF dwell (compressor restart) | 3–5 min | industry anti-short-cycle delay (Copeland: ≥3 min) |
| Re-evaluation interval | 60 s | responsiveness vs contactor wear |
| Low-SoC alerts | 50 / 35 / 20 % | info / warn / critical, independent of shed |
| User-override timeout | 30 min (max 4 h) | a forgotten override cannot defeat safety indefinitely |
| Forecast-disagreement escalation | actual SoC decline > 1.3× forecast for > 5 min | drop the predictive layer, fall back to pure SoC thresholds |

### 4.3 Pseudocode (every 60 s while on battery)
```
evaluate_tiers():
    E_avail = SoH*SoC*C_usable(I_fcst_T1T2,T)*V_nom
    fcst_T1_Wh = habit.forecast_demand(T1, horizon_h=H)
    remaining_min = outage.expected_remaining_duration(now)
    mode = CONSERVATIVE if |actual_rate − forecast_rate| > 1.3*forecast_rate for 5 min else PREDICTIVE
    # essentials-at-risk hard floor (always)
    if grid_out and E_avail < 1.2*fcst_T1_Wh: shed(T3, "T1 endurance at risk")
    # SoC hysteresis ladder (always the floor logic)
    if SoC <= 40: shed(T3)   elif SoC >= 55 and dwell_ok(T3): restore(T3)
    if SoC <= 55: defer(T2)  elif SoC >= 70 and dwell_ok(T2): restore(T2)
    # predictive pre-emption (only PREDICTIVE, only pre-outage)
    if mode == PREDICTIVE and not grid_out and outage.P(h=3).prob > 0.55 and .conf > 0.5:
        raise_soc_target(+15pp); tighten_shed_thresholds(+10pp)
    assert T1 never shed/deferred
    for change in pending: if elapsed(channel) >= min_dwell: actuate + log(channel, action, SoC, reason) else requeue
```
### 4.4 User override
App override ("keep AC on") applies to the SoC-ladder tiers only — it **cannot** override the essentials-at-risk hard floor. Every override times out (default 30 min); the UI shows the countdown. (Precedent: Victron SoC-based AC-Out-2 load-shed assistant.)

## 5. "Prioritising within the single essential circuit" — the honest limit (H16)
With one contactor per tier, **Sentinel cannot shed or re-prioritise individual loads inside T1** — a contactor is one on/off gate for everything behind it. What is possible, and the wording to use:
| Feature | What it actually does | Wording |
|---|---|---|
| Staged SoC alerts | Notify at 50/35/20 % while T1 stays powered | "Staged battery-reserve alerts, not load control" |
| Reserve-mode advisory | Prompt the user to switch off non-essential T1 devices | "Advisory guidance for manual load reduction" |
| Optional sub-circuit | Installer splits T1 into T1a (fridge+router, hard-wired) and T1b (lights, on a 5th channel) | "Optional finer split, subject to installer wiring" |
| Smart-plug integration | Wi-Fi relays per appliance orchestrated over local MQTT | "**Roadmap** — do not claim as shipped" |
Precedent: Tesla's Backup Gateway achieves per-circuit shedding only with one dedicated control circuit per shed-able load — the same physical constraint applies. **Granularity = number of contactor channels wired, not a software feature.**

## 6. Fail-safe & safety (H15)
- **NC (Form-B) contactors**, wired so the load circuit is **closed when the coil is de-energised**. "Shedding" = energising the coil to open. Loss of control power, crash, brown-out or watchdog reset → coils drop → **all loads ON**. (This is the opposite of Tesla's convention; NC is correct for our "loads default to energised" spec — call it out to installers, it is easy to wire backwards.)
- **Watchdog**: ESP32-S3 hardware WDT **plus** an independent supervisory circuit on the driver board that gates the coil-enable line — if the MCU stops toggling a heartbeat GPIO for 2 s, the board forces all coils off (loads on) regardless of firmware.
- **Sensor fault → all-on**: out-of-range / NaN / stuck readings → log, force de-energised state; never shed on unreliable data.
- **Startup**: NC contactors are physically closed with no drive current — loads are on before any code runs; no boot path is needed to "turn loads on".
- **Manual bypass**: an electrician-accessible mechanical bypass per contactor for service and for graceful degradation if the whole board dies.
- **Compressor restart delay** (3–5 min) respected wherever Sentinel has switching control; a hard fail-safe all-on after an MCU crash cannot enforce it — an accepted trade-off of "never leave essentials dark".

## 7. Outage detection (H36) and recharge
```
s1 = mains_Urms(1/2) < 0.1 pu sustained ≥ N1 (1–2 s)   # AMC1311 → ESP32 ADC fast path (10 §3), cross-checked by the ATM90E32AS sag flag; IEEE 1159 "interruption"
s2 = inverter_mode_pin == BACKUP                      # embedded SKU only
s3 = battery net-discharge current > idle threshold
outage = (s1 AND (s2 OR s3))  OR  (s1 alone for ≥ N2)
```
2-of-3 voting guards against one failed sensor; `s1`-alone with longer debounce keeps retrofit working. **Restore** = `Urms > 0.9 pu` for 10–30 s (longer debounce — grids often flicker at outage end). On restore: bulk→absorption→float per the health policy, and **delay reconnecting T2/T3 until SoC crosses the restore threshold or absorption completes**, so a depleted battery is not hit with recharge current and heavy load at once.

## 8. Six-step summary (judge-ready)
1. **Observe** — hourly, log load power and mains-loss/restore events into a 168-bin hour-of-week table with EWMA updates; a few KB, no cloud, no training.
2. **Forecast transparently** — P(outage in next 3 h) straight from that table with a confidence score; refuses to act confidently on thin data.
3. **Pre-charge where commandable, advise where not** — raise SoC target / tighten thresholds ahead of a high-probability window; on retrofit hardware this is a notification.
4. **Detect the real outage** by 2-of-3 vote with debounce, independent of prediction.
5. **Shed by tier with hysteresis and dwell** — T3 at 40 % (restore 55 %), T2 at 55 % (restore 70 %), T1 never; 3–5 min dwell; 60 s re-evaluation.
6. **Fail safe and re-evaluate until grid restores** — any fault forces NC contactors to all-loads-on; staged recharge and delayed reconnection protect the battery.

## References
Hong & Fan, *Probabilistic electric load forecasting: a tutorial review* (Int. J. Forecasting) · Wang et al., *Review of Smart Meter Data Analytics* (arXiv:1802.04117) · Xu & Meng, *Short-term load forecasting at different aggregation levels* (arXiv:1903.10679) · Victron, *Battery capacity and Peukert exponent* (SmartShunt manual) · Battle Born, *Peukert effect* · VIOX, *HVAC time-delay relay / compressor protection*; ACHR News, *Compressor time delay relays* · Victron Community, *Multiplus-II load shedding on AC-Out-2* · Tesla Energy Library, *Backup Gateway load shedding* · siqma, *ESP32 TinyML benchmark* · arXiv:2606.17613, *Online ridge regression for edge prediction*.
