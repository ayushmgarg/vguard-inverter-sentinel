# components/tflm_wrapper -- optional esp-tflite-micro path

**Status: compiled only in concept.** ESP-IDF and the `espressif/esp-tflite-micro`
managed component are not installed in this environment (see `firmware/README.md`).
`tflm_wrapper.cpp` is written against the esp-tflite-micro v1.x API as documented
upstream (`MicroMutableOpResolver<N>`, `MicroInterpreter`, `AllocateTensors`), but it
has **never been compiled, linked, or run** here. Treat it as a well-specified stub, not
a verified implementation.

## Why this exists alongside `sentinel_int8`

Two independent int8 inference paths, on purpose:

- **`components/sentinel_int8`** -- a hand-written C99 port of `model/int8_infer.py`,
  reading the weights/scales directly out of `model/artifacts_sim/sentinel_model_int8.h`.
  Host-buildable, no framework dependency, and **the path this repo actually builds and
  runs** (`firmware/host/sentinel_host_sim`, `sentinel_int8_selftest()` PASS in every
  run). This is the path `main.c` uses by default (`CONFIG_SENTINEL_USE_TFLM=n`).
- **`tflm_wrapper`** -- runs the *actual* `.tflite` flatbuffer
  (`model/artifacts_sim/sentinel_model_seed0.tflite`) through esp-tflite-micro, matching
  design 04 §4 step 3's described architecture (`MicroMutableOpResolver` with exactly
  RESHAPE / EXPAND_DIMS / CONV_2D / FULLY_CONNECTED / CONCATENATION / RELU, 16 KB arena,
  golden self-test). Enable with `CONFIG_SENTINEL_USE_TFLM=y`.

Keeping both means: if `sentinel_model_int8.h`'s hand-derived (multiplier,shift) tables
ever drift from what the TFLite converter would produce, `tflm_wrapper`'s independent
path (driven straight off the flatbuffer's own quantisation params) is the
cross-check -- but that cross-check has not been exercised here since it cannot build.

## What a real bring-up needs to do before trusting this file

1. `idf.py build` with `CONFIG_SENTINEL_USE_TFLM=y` once ESP-IDF + the Component
   Manager can fetch `espressif/esp-tflite-micro` -- confirm it compiles at all.
2. Check the resolver's op set against whatever `model/export_tflite.py` actually
   emits for a real `.tflite` (this file assumes the six ops design 04 §4 lists; a
   different TF version or converter flag could lower the graph differently).
3. Run `tflm_wrapper_selftest()` on target and confirm it's within tolerance of the
   `sentinel_int8_selftest()` golden vector (see `firmware/host/gen_golden.py`) --
   they are independently-quantised models (hand PTQ vs. TFLite converter PTQ), so
   the comparison tolerance is intentionally loose (0.05 in this file), not bit-exact.
4. Measure actual arena usage (`recording_micro_allocator` or similar) -- the 16 KB
   figure is design 04 §3's stated budget, not something this file has confirmed the
   real graph fits into.
