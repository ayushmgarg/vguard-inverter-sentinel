# firmware — module H: the ESP32-S3 firmware project

Glues the existing, independently-tested C algorithm modules (`ekf/`, `autopilot/`,
`nilm/`, `pq/`, `healthlog/`, `model/`) into one ESP-IDF 5.x project, plus a host build
that actually runs the whole control loop end-to-end against a real 1 Hz CSV replay.
Design refs: `04-Self-Contained-Operation-and-Firmware.md`, `03-Parts-Placement-and-Roles.md`,
`CONTRACTS.md`.

## What was executed *here* (read this before trusting any other claim in this tree)

ESP-IDF is **not installed** in this environment. Nothing under `firmware/` has ever been
compiled with `idf.py`, flashed to an ESP32-S3, or run on real hardware. The two things
that genuinely were built and run here:

1. **`firmware/host/sentinel_host_sim`** (`make -C firmware/host host`) -- links the real
   `ekf.c`, `autopilot.c`, `healthlog.c`, and the hand-written `sentinel_int8.c` CNN
   against `firmware/main/sentinel_core.c` (the same engine file `main.c`'s FreeRTOS tasks
   call), fed by a CSV stub instead of I2C/UART/ADC drivers. Verified output (full
   `data/sim_1hz/battery_000.csv`, 1,297,176 rows / ~15 simulated days):
   ```
   sentinel_int8 golden self-test: PASS
   rows processed: 1297176
   SoC trace: min=0.2340 max=1.0000 mean=0.8902
   cycles detected: 16
   final: grade=COLLECTING soh_p50=89.34% rul_weeks_p50=0.0 confidence=MED
   health-log: 17 records, 2044 bytes, hl_verify_chain=OK
   ```
   (manifest's `final_soh_true` for battery 0 is 92.96% -- 89.34% from this simplified
   pipeline is in the right neighbourhood, not a bit-exact target; see "honest limits".)
2. **`components/sentinel_int8`'s golden self-test** -- a C99 int8 forward pass, checked
   bit-exact (not "close enough": int8 fixed-point arithmetic is deterministic) against
   `model/int8_infer.py`'s reference implementation run over the *actual* exported
   weights, via `firmware/tools/make_golden.py`.

Everything else (the ESP-IDF component tree, `main.c`'s FreeRTOS tasks, the drivers,
`sdkconfig.defaults`, `partitions.csv`, the TFLM path) is a from-first-principles-correct
*layout* that would build with `idf.py set-target esp32s3 && idf.py build` on a machine
with ESP-IDF 5.x installed -- but that command has never actually been run against it.

## Build instructions

### Host (what this repo actually runs)
```bash
cd firmware/host
make host                      # builds sentinel_host_sim (requires libcrypto/openssl-dev)
./sentinel_host_sim --csv ../../data/sim_1hz/battery_000.csv \
                     --manifest ../../data/sim_1hz/manifest.csv \
                     --out state.json
python -m dashboard.app --provider file --file firmware/host/state.json   # from code/ root
```
`--max-rows N` truncates the replay for a quick smoke test (`make test` does this with
20000 rows). `data/sim_1hz_b/` (see its own `manifest.csv`) is an alternate battery
cohort and works identically.

### ESP32-S3 target (never run here)
```bash
cd firmware
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```
Requires ESP-IDF 5.x installed and sourced, and (for `CONFIG_SENTINEL_USE_TFLM=y` only)
network access for the IDF Component Manager to fetch `espressif/esp-tflite-micro` and
`joltwallet/littlefs` (see `components/tflm_wrapper/idf_component.yml`,
`main/idf_component.yml`).

## Layout
```
firmware/
  CMakeLists.txt, sdkconfig.defaults, partitions.csv    -- ESP-IDF project root
  components/
    ekf/ autopilot/ nilm/ pq/ healthlog/                -- thin wrappers, compile the
                                                            real code/{module}/*.c by path
    sentinel_int8/    -- hand-written C99 int8 CNN (model/int8_infer.py port) + golden test
    tflm_wrapper/     -- optional esp-tflite-micro path, CONFIG_SENTINEL_USE_TFLM
  main/
    sentinel_core.[ch]     -- the portable engine: EKF -> cycle_feat -> sentinel_int8 ->
                               grade/conformal post-processing -> autopilot -> healthlog.
                               Used by BOTH main.c (ESP32) and host/sentinel_host_sim.c.
    cycle_feat.[ch]        -- simplified per-cycle feature extractor (see "honest limits")
    grade.[ch]              -- C port of model/grade.py (usage-rate EWMA, weeks, grade FSM)
    state_json.[ch]        -- dashboard JSON serialiser (CONTRACTS §3/§5)
    main.c                  -- FreeRTOS tasks, design 04 §2
    ina2xx.[ch] ntc.[ch] pzem_uart.[ch] relays.[ch] storage.[ch] replay.[ch]  -- drivers
    healthlog_signer.[ch], healthlog_signer_esp.c   -- ATECC608 signer stub (see below)
  host/
    sentinel_host_sim.c, Makefile   -- the thing actually built and run here
  tools/
    make_golden.py    -- regenerates components/sentinel_int8/include/sentinel_int8_golden.h
                          from the CURRENT model/artifacts_sim/sentinel_model_int8.h
    make_model_stats.py -- regenerates main/sentinel_model_stats.h from the CURRENT
                          model/artifacts_sim/sentinel_model_header.json
  tests/
    test_firmware_host.py   -- pytest: builds+runs the host sim, checks self-test PASS,
                                state.json schema, health-log chain verification
```
`model/artifacts_sim/` is owned by a different module and gets retrained independently
(observed happening mid-session while building this firmware) -- `firmware/tools/` exists
precisely so the golden vector and standardisation constants can be re-synced with one
command whenever that happens; re-run both before trusting a stale-looking self-test.

## Pin map (DevKitC-1 bench, per `03-Parts-Placement-and-Roles.md` -- placeholders until a
real bench assigns final numbers; anything conflicting with the DevKitC-1's own strapping
pins (0, 45, 46) or USB-JTAG pins (19, 20) must be moved before real use)

| Signal | Function | GPIO (placeholder) | Notes |
|---|---|---|---|
| I2C SDA | INA228/INA226, DS3231, ATECC608 shared bus | 8 | `main.c` `i2c_new_master_bus` |
| I2C SCL | " | 9 | 400 kHz |
| ADC | NTC 10k β3950 divider | ADC1 CH3 (GPIO4) | 12-bit, `ntc.c` |
| UART1 TX | PZEM-004T v3 (Tier-0 AFE fallback) | 17 | 9600 8N1 |
| UART1 RX | " | 18 | |
| SPI (not wired in this pass) | ATM90E32AS AFE | -- | `afe_3hz` task uses the PZEM fallback path only; no SPI driver written -- see honest limits |
| Mains sense | opto tap (C12) / AMC1311 comparator, outage 2-of-3 vote | `CONFIG_SENTINEL_MAINS_SENSE_GPIO` = 16 | digital input; also stands in for the missing AC-RMS ADC leg of the vote, see honest limits |
| Relay coil T1 | essentials (locked, never shed) | `CONFIG_SENTINEL_RELAY_COIL_T1_GPIO` = 5 | ULN2003 input |
| Relay coil T2 | fans/TV | `CONFIG_SENTINEL_RELAY_COIL_T2_GPIO` = 6 | |
| Relay coil T3 | heavy sockets | `CONFIG_SENTINEL_RELAY_COIL_T3_GPIO` = 7 | |
| Relay coil medical | CPAP etc, hw-locked T1 | `CONFIG_SENTINEL_RELAY_COIL_MED_GPIO` = 15 | JP1 jumper is a separate hardware guarantee, not this GPIO |
| Heartbeat | external supervisory timer feed | `CONFIG_SENTINEL_HEARTBEAT_GPIO` = 4 | toggled only while task watchdog is healthy |

## Honest limits (see also each source file's own doc comment -- this is a summary, not
the full list)

- **Never flashed to hardware.** No ESP32-S3 board was available; every ESP-IDF-specific
  file (`main.c`, the drivers, `tflm_wrapper.cpp`) is written against the documented
  ESP-IDF 5.x / esp-tflite-micro API surface but has zero build verification.
- **Timing numbers are host, not ESP.** `sentinel_host_sim`'s ~6 s for 15 simulated days
  on this machine says nothing about real-time performance on an ESP32-S3 at 240 MHz with
  FreeRTOS scheduling overhead, I2C/UART/ADC latency, and Wi-Fi/BLE stacks competing for
  Core 0. Design 04 §4's "~1-10 ms per Invoke" is the design doc's own estimate, not
  something measured here.
- **TFLM path compiled only in concept.** `components/tflm_wrapper` has never been
  compiled (see its own `README.md`). The path this repo actually exercises is the
  hand-written `sentinel_int8` component.
- **`cycle_feat.c` is a simplified, non-bit-exact port** of `features/cycle_features.py`
  (581 lines of CC/CV/FLOAT/DISCHARGE state-machine + ICA peak extraction + rest-OCV --
  reproducing that exactly in C was out of scope for this pass). 10 of 14 dynamic channels
  and 4 of 6 static channels are genuinely computed on-device from EKF/sample signals; the
  rest are fixed, documented neutral placeholders. See `cycle_feat.h`'s doc comment for
  the exact channel-by-channel breakdown.
- **`charger_on` is inferred from `grid` (mains present), not measured.** The CONTRACTS
  §1 stream has no ground-truth charger-relay flag (only `ekf/sim_battery_for_ekf.py`'s
  separate EKF-only test stream does). A current-threshold heuristic was tried first and
  is actively wrong (it flips false during the exact float/tail-current phase the EKF's
  full-charge detector needs `charger_on=true` for); `grid` turned out to be the working
  proxy. See `sentinel_core.c`'s `sentinel_core_on_sample()` doc comment.
- **`ekf_params_default()`'s tail-current threshold (1.5% of C20) needed a calibration
  override (10%) to ever close a cycle against `data/sim_1hz/battery_000.csv`.** That
  default is tuned for `ekf/sim_battery_for_ekf.py`'s own synthetic charge profile, not
  `sim/battery_sim.py`'s (a different module's simulator, observed empirically to float
  down to ~6% of C20 and no lower over a 15-day trace). See `sentinel_config_default()`'s
  doc comment in `sentinel_core.c`. A real deployment calibrates this from the charger's
  actual datasheet tail-current spec, not empirically like this.
- **No ATECC608 driver.** `healthlog_signer_esp_sign_cb()` always fails (documented
  stub) -- on real ESP32 hardware the health log would be silently unsigned/disabled
  until that driver exists. The host build signs with an OpenSSL software key instead
  (exactly `healthlog/test_healthlog_host.c`'s pattern) and that path **is** exercised
  and verified (`hl_verify_chain` = OK in every host run).
- **No AMC1311/ADC-DMA capture, no ATM90E32AS SPI driver.** `task_pq` and `task_afe_3hz`
  in `main.c` are wired to real component APIs (`pq.c`, `event_detector.c`) but driven by
  placeholder/synthetic input, not real waveform capture -- the `coach`/`pq` sections of
  the dashboard state stay empty in every run this repo produces (see `state_json.c`'s
  `append_coach_pq_stub` doc comment). The PZEM-004T Tier-0 UART path is written for real
  hardware but, like everything else in `main.c`, never build- or bench-verified.
- **Grade stayed COLLECTING in the reference run above.** 16 cycles over 15 days clears
  the ≥10-cycle floor, but the grade state machine's hysteresis (3 consecutive same-target
  inferences spanning ≥5 days, design 02 §3.4) didn't lock in before the CSV ran out --
  plausible given how few cycles this window contains and how noisy the simplified
  feature extractor's cycle-to-cycle estimates are, not chased further under this pass's
  time budget.
- **`main.c`'s task decomposition is an honest simplification**, not a literal 1:1 of
  design 04 §2's 9 independent tasks -- see the architecture note at the top of `main.c`.
- **Secure Boot / flash encryption are commented out** in `sdkconfig.defaults`, with the
  real enablement order documented inline -- never turned on for a board that was never
  flashed and has no verified provisioning flow.
