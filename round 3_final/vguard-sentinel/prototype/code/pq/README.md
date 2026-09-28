# pq/ -- Grid Shield: power-quality analyser

Implements design doc `07-Grid-Shield-Power-Quality.md` in full, and the `PQEvent` /
`pq_push_sample`/`pq_poll_event` API of `CONTRACTS.md` Sec 4/6.

## Files

| File | Implements |
|---|---|
| `pq.py` | Half-cycle sliding RMS `Urms(1/2)`, zero-crossing frequency (rolling 10-cycle window), 4-cycle FFT THD, IEEE 1159 sag/swell/interruption classification + duration buckets, `PQEvent` record, 1000-event circular buffer, monthly rollup |
| `pq.h/.c` | C99 port, static buffers, `pq_push_sample`/`pq_poll_event` per CONTRACTS.md Sec 6 |
| `pq_main.c` | Host CLI: reads one voltage sample per line on stdin, emits events as CSV -- used by the Python/C parity test |
| `test_pq_host.c` | Standalone C unit test (sag magnitude/duration, THD reading, no-false-positive on a clean sine) |
| `Makefile` | Builds all of the above with `gcc -std=c99 -O2 -lm` |

## Run it

```bash
cd documentation/prototype/code
python3 -m pytest -q -s tests/test_pq.py    # Python pipeline + C parity + C host tests
make -C pq && make -C pq test                # C host tests standalone
```

## What was measured here (230 V / 50 Hz synthetic waveform, 4 kS/s)

Reproduce with `pytest -q -s tests/test_pq.py`.

- **Dip/interruption detection**, 14 injected cases (70%/40%/0% depth, 0.5-250 cycles):
  - **Detection rate for dips >= 1 cycle: 13/13 = 100%** (design target: >= 99%)
  - **Magnitude error: mean 0.48%, max 0.86%** across all cases (target: <= 2%)
  - **Duration error: 0.00 half-cycles** (exact, to millisecond rounding) in every case
    (target: <= 1 half-cycle)
  - **IEEE 1159 duration-bucket accuracy: 14/14 = 100%**
- **Swell**: injected 1.25 pu / 20 cycles -> detected **1.266 pu / 400 ms** (magnitude
  error 1.3%, duration exact).
- **Frequency deviation**: injected +3.5% for 1.0 s -> detected **1.036 pu (3.6%
  deviation) for 891 ms** as one continuous event (edge lag from the rolling 10-cycle
  average, as expected -- a step is felt only once enough new-frequency cycles have
  entered the window).
- **THD**: single 5th-harmonic injection at 5.0% amplitude -> measured **5.000%**
  (harmonic bins land exactly on FFT bins by construction, see below, so this case has
  ~zero measurement error; ±1 pt tolerance is intended for less exact/noisier signals).
- **C/Python parity**: bit-for-bit identical event stream (type, magnitude, duration,
  pre/post RMS) on the same waveform, verified by
  `tests/test_pq.py::test_c_matches_python`. The Python side computes THD via
  `np.fft.rfft`; the C side uses per-harmonic Goertzel filters -- both compute the
  *same* DFT coefficients (the window length is chosen so each harmonic lands exactly
  on an FFT bin, see `compute_thd()`/`goertzel_mag()`), so results match to float
  tolerance without needing an FFT library in C.
- **PQEvent struct size**: `struct.calcsize` / `sizeof(pq_event_t)` = **28 bytes**
  under standard alignment (`uint32 + uint8[+3 pad] + float + uint32 + float + float +
  float`), not the "~32 B" the design doc estimates -- see "Honest limits" below.

## Honest limits

- **"IEC 61000-4-30 Class-S-like", never Class A** (design 07 Sec 6, restated here on
  purpose): there is no certified PT/CT and no GPS/PTP time base in this prototype or
  its host-test harness. `Urms(1/2)` and the duration-bucket thresholds are the
  Class-S-permitted method; nothing here should be represented as calibrated,
  contractual-dispute-grade metrology.
- **Struct size is 28 B, not "~32 B".** The design doc's Sec 3 code block is a good-
  faith estimate; `sizeof(struct PQEvent)` under standard x86-64/ARM alignment is 28 B
  (3 bytes of padding after the `uint8 type` field to re-align the next `float`). This
  affects only the flash-budget arithmetic of design 06/07 (1000 events is ~27.3 KB, not
  ~32 KB) -- reported here rather than silently forcing the struct to pad to exactly 32
  B, which would misrepresent what the code actually stores.
- **A full interruption needs a stall watchdog.** A genuinely dead mains (`V == 0`)
  never crosses zero, so pure zero-crossing-triggered half-cycle RMS would never
  finalise a segment during an outage. Both `pq.py` and `pq.c` force-evaluate the
  accumulated segment if no crossing occurs for ~2x the nominal half-cycle length. This
  is a necessary, deliberate addition beyond the design doc's method description, not
  a deviation from it -- discovered by testing the 0%-depth cases, not assumed
  up front.
- **Harmonics computed 2nd-39th, not to the 40th.** At 4 kS/s and a 50 Hz fundamental,
  the 40th harmonic (2000 Hz) is exactly the Nyquist frequency -- unusable. The design
  doc's own range ("25th-40th order per ADC budget") acknowledges this is ADC-rate-
  dependent; `PQParams.thd_max_harmonic` defaults to 39.
- **Frequency-deviation hysteresis (`freq_hysteresis_frac`, default 0.5%) is an
  addition, not in the design doc.** Without it, a deviation that sits close to the 3%
  threshold made the state machine open/close every cycle (chatter) instead of one
  continuous event -- found via `test_frequency_deviation` during testing, fixed by
  requiring recovery to `freq_dev_frac - freq_hysteresis_frac` before closing, mirroring
  the `hysteresis_pu` the design already specifies for sag/swell/interruption.
- **No real ADC, no AMC1311 divider, no ESP32-S3 ADC noise model.** `tests/test_pq.py`
  injects clean synthetic sines with exact-percentage dips/swells/THD; ADC quantisation,
  aliasing beyond the Nyquist-limited harmonic count, and the isolated divider's own
  transfer function are out of scope here (design 07 Sec 1 / 10 Sec 3).
- **Monthly rollup (`monthly_rollup()`) is exercised only by manual/ad hoc testing**,
  not by a dedicated `tests/test_pq.py` case with a month's worth of synthesised
  events.
- **THD is computed on non-overlapping 4-cycle blocks**, not a sliding window; a THD
  excursion shorter than one 80 ms block, or straddling a block boundary, may be
  under-reported. This matches the design's "4-cycle (80 ms) FFT" language but is worth
  stating plainly.
