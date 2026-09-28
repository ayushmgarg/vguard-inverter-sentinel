# 04 — How the box operates on its own: firmware architecture and exactly how the TinyML runs

## 1. Self-contained means: no network is on the critical path of any function
| Function | Needs cloud? | Needs phone? | Needs the inverter to cooperate? |
|---|---|---|---|
| SoC, R_int, backup-time estimate | no | no | no |
| SoH/RUL grade + "replace within N weeks" | no (model is in flash) | no | no |
| Outage detection, tiered shedding, fail-safe | no | no | no (2-of-3 works with our own AC sense + current sign) |
| Appliance events, kWh per appliance | no | only to *name* clusters | no |
| Sag/swell/interruption log | no | no | no |
| Health log (signed) | no | to *upload* a claim | no |
| Habit/outage tables, pre-charge advisory | no | no | Embedded for active pre-charge |
| Model/firmware updates, fleet telemetry | yes (opportunistic) | or phone as relay | no |
Power comes from the battery; state persists in flash; the clock is battery-backed. Unplug the router for a year and every row above still works.

## 2. Firmware architecture (ESP-IDF 5.x, FreeRTOS, two cores)
```
Core 0 (protocol core)                     Core 1 (application core)
─────────────────────                      ──────────────────────────
Wi-Fi / BLE stacks (only when enabled)     sense_1hz     prio 20  timer-driven: INA228, NTC, AMC1311 RMS → publishes Sample{I,V,T,Vac_rms,t}
mqtt_telemetry  prio 5                     ekf           prio 18  consumes Sample → SoC, V1, R0, anchors, R_int events  (design 01)
ota + model_ota prio 4                     autopilot     prio 17  60 s tick + outage events → contactor commands via driver API (design 05)
app_ble         prio 6                     cycle_feat    prio 12  segmentation + per-cycle features (design 02 §1)
                                           ml_infer      prio 10  event-driven: builds window, runs AE + 3 × CNN, grades (design 02 §3–6)
                                           afe_3hz       prio 14  ATM90E32AS SPI read → NILM event detector → k-NN (design 06)
                                           pq            prio 15  4 kS/s ADC DMA → Urms(1/2), 4-cycle FFT, IEEE 1159 classify (design 07)
                                           logger        prio 8   LittleFS append: features, events, PQ, telemetry queue; health-log signing via ATECC608
                                           heartbeat     prio 24  toggles the supervisory-timer GPIO every 500 ms *only if* all critical tasks checked in (task watchdog)
```
- **Inter-task data**: one immutable `Sample` struct per second on a ring; tasks read by index — no shared mutable state (immutability rule).
- **Watchdogs**: ESP-IDF task watchdog on sense_1hz/ekf/autopilot; hardware RWDT; the external supervisory timer (design 10 §4) is fed only by `heartbeat`, which only runs if the task watchdog is healthy. Any hang → contactors drop → loads on.
- **Power modes**: mains present, NILM on: all tasks; outage: Wi-Fi off, BLE 5 s advertising, afe_3hz suspended, AFE load-switched off; idle nights: light-sleep between 1 Hz ticks.

## 3. Flash and RAM map (16 MB module)
| Partition | Size | Content |
|---|---|---|
| bootloader + partition table | 64 KB | Secure Boot V2 |
| nvs | 64 KB | config, calibration, pseudonym, EKF persisted state, model pointer, circuit map |
| otadata | 8 KB | A/B selection |
| app0 / app1 | 2 × 3 MB | firmware A/B |
| model_a / model_b | 2 × 128 KB | SoH/RUL ×3 seeds + AE + NILM priors, signed, with header |
| data (LittleFS) | 1 MB | feature history (36 B/cycle), NILM events (64 B), PQ events (32 B), telemetry queue, health-log chain |
| coredump | 64 KB | crash forensics |
RAM (of 512 KB SRAM): Wi-Fi/BLE stacks ≈ 100–150 KB when on; TFLM arena 16 KB + interpreter 4 KB; feature state 12 KB; NILM rings 27 KB; PQ DMA buffers 16 KB; LittleFS cache 8 KB; tasks/stacks ≈ 60 KB. PSRAM (8 MB) holds the NILM 1-min aggregates and log staging. Comfortable.

## 4. Exactly how the TinyML part works — from Python to a number on the screen
1. **Offline (laptop/cloud)**: Keras model per design 02 §2.2 is trained (Stage A Li-ion → Stage B synthetic → Stage C campaign), 3 seeds. Each is converted with the TFLite converter using **full-integer post-training quantisation** (representative dataset of ~500 feature windows) → `soh_rul_s{0,1,2}.tflite` (~32 KB each). The conformal offsets, input mean/scale vectors, feature-schema version and grade thresholds are packed into a small header; header + flatbuffers are concatenated, CRC'd and signed into `model.bin`.
2. **Onto the device**: `model.bin` is flashed into `model_a` (factory) or downloaded into the inactive slot (OTA). The firmware never contains the weights in its own image — models and firmware update independently.
3. **At boot**: `ml_infer` maps the active model slot, checks CRC + signature + schema version, and creates one `tflite::MicroInterpreter` per seed with a `MicroMutableOpResolver` registering exactly: RESHAPE, EXPAND_DIMS, CONV_2D, FULLY_CONNECTED, CONCATENATION, RELU (ESP-NN kernels are linked for CONV_2D/FULLY_CONNECTED/RELU). `AllocateTensors()` carves the activations out of a static 16 KB arena. A **golden self-test** runs a built-in window and compares outputs to expected values; failure → fall back to the other slot.
4. **At each cycle end** (`cycle_feat` posts an event): the last 30 per-cycle vectors (14 × int16 each) and the 6 statics are standardised with the header mean/scale, clipped to ±3σ, and quantised to int8 with the input tensor's scale/zero-point. `interpreter->Invoke()` runs in ~1–10 ms. The two output tensors (3 values each) are dequantised: SoH = 60 + 40·y, RUL_EFC = exp(8·y) − 1.
5. **Post-processing in plain C**: average the three seeds; apply conformal offsets to get [P10, P90]; convert EFC → weeks with this home's EWMA outage rate; cap by calendar aging; cross-check against the on-device RLS line; run the grade state machine (3 inferences over ≥ 5 days, hysteresis). Result: `{soh50, p10, p90, rul_weeks{p10,p50,p90}, grade, confidence}` → LittleFS, health log, app.
6. **The anomaly autoencoder** runs first on the same event with its own interpreter (3 KB model, 56→6→56); reconstruction error above the stored e_99 on 2 of 3 cycles → "Service now" and the cycle is masked from the SoH window.
7. **No training on the device.** Personalisation is the ratio-to-baseline features and the conformal offset update when a direct capacity sample occurs.
Everything the model needs — the 30-cycle window, the statics, the baseline medians from the battery's first 10 cycles — is computed and stored on the device from the 1 Hz samples. That is the whole "ESP will have TinyML" story: **fixed int8 weights in flash, a 16 KB arena, one Invoke per outage cycle, and C code around it that turns quantiles into "replace in 6–14 weeks".**

## 5. The other on-device intelligence that is *not* a neural net (and why)
| Engine | Method | Why not a network |
|---|---|---|
| SoC | 3-state EKF | physics is known; needs no training data; auditable |
| Load/outage habits | 168-bin EWMA tables | single-home load is too noisy for a forecaster to beat a histogram; a judge can read the table |
| Appliance matching | rules + k-NN on 13 features | learns from one user label; 7 KB; interpretable |
| Sag/swell | half-cycle RMS thresholds | a standard, not a model |
| Shedding | thresholds + hysteresis + dwell | safety logic must be deterministic |

## 6. Boot, install and failure behaviour
- **First boot / unconfigured**: all contactor channels T1 (never shed); SoC initialised from OCV if at rest else 50 % with wide covariance; grade = "collecting data (needs ≥ 10 cycles)"; NILM in silent learning; no alerts for 24 h.
- **Commissioning (USB or BLE, 10 min)**: battery model/Ah, shunt value, CT ratio and polarity check (sign of P), circuit map + tiers, region, tariff, consent.
- **Sensor fault** (NaN, stuck, out of range): engine falls back (EKF → coulomb-count only; NILM off), logs, LED, app alert; contactors never shed on unreliable data.
- **Brown-out / crash / hang**: buck holds to ~4.5 V input; any reset drops coils → loads on; state restored from NVS; EKF covariance widened after an unclean shutdown.
- **AFE or CT missing**: Coach and PQ disabled, everything else runs.
