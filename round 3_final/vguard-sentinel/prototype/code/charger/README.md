# charger — Engine 1c: adaptive charging policy & charger-control interface

Implements design doc **03 — Adaptive-Charging-and-Charger-Interface** in
full: Sec.1.2 (UART frame codec), Sec.2 (Retrofit honest capability), Sec.3
(the policy loop, both SKUs), plus the tail-current/rest-anchor numbers from
**01-Battery-State-Estimation.md Sec.5a**. Interfaces conform to
`../CONTRACTS.md` Sec.0 (Python 3.9, C99, host-buildable, no ESP-IDF
dependency here) and Sec.1 (`I`: + charge / - discharge battery convention).

## Files

| File | What it is | Design ref |
|---|---|---|
| `policy.py` | pure-function 60 s policy loop: temp-compensated setpoints, current-limit derating, adaptive absorption termination, equalisation scheduler, pre-charge, fault fallback | 03 Sec.3, 01 Sec.5a |
| `frames.py` | UART frame codec (Python reference): CRC-16/CCITT-FALSE, PPP-style byte stuffing, streaming parser with resync | 03 Sec.1.2 |
| `frames.h` / `frames.c` | C99 port of `frames.py`, static allocation, must byte-match it | same |
| `test_frames_host.c` | host test harness: internal self-tests (`./test_frames_host`) + `--vectors` mode for the Python parity check | 11-style host test convention (see `autopilot/`, `healthlog/`) |
| `parity_vectors.txt` | shared command/argument table both languages encode, for the parity test | -- |
| `Makefile` | host build (`gcc -std=c99 -O2 -lm`), no ESP-IDF dependency | CONTRACTS Sec.0 |
| `sim_charger.py` | simulated charger device: enforces the 15.5 V ceiling (NACK), toy Thevenin CC/CV/float battery model, reverts to factory defaults on heartbeat loss, GET_STATUS | 03 Sec.1.1-1.2, task spec |
| `../tests/test_charger.py` | pytest suite: setpoints, derating/OFF, absorption termination, equalisation gate, pre-charge, retrofit, fault fallback, sim-charger, codec, C-port parity | -- |

## Commands

```sh
# Python policy + codec + simulated charger
python3 -c "import sys; sys.path.insert(0,'..'); from charger import policy, frames, sim_charger"

# C host build + self-tests + parity vector emission
cd charger
make            # builds ./test_frames_host
make test       # runs self-tests, then emits parity vector hex to stdout
./test_frames_host --vectors parity_vectors.txt   # just the vector emission

# full test suite (from documentation/prototype/code/, per CONTRACTS.md)
pytest -q tests/test_charger.py
```

## What was executed here (last run in this environment)

**pytest** (`pytest -q tests/test_charger.py`):

```
48 passed
```

covering: temperature compensation at 10/25/40 C (formula match + monotonicity),
hardware ceiling/floor clamp across a -40..88 C sweep, the derating curve
(exact match at several points, 60 % at 55 C), OFF at >=58 C, absorption
termination via tail current and via timeout (and that timeout lengthens when
cold), the equalisation gate individually requiring each of its four
conditions plus the quarterly water-loss cap, pre-charge holding/extending
absorption only when `sku_commandable=True` and being advisory-only
otherwise, Retrofit emitting zero commands across every phase while
producing the *same* setpoint numbers as advice text, fault fallback on
NaN/out-of-range sensors and on a stale heartbeat ack, the simulated
charger's NACK-on-over-ceiling and heartbeat-loss revert, GET_STATUS
round-trip, and frame-codec round-trip / CRC-corruption-then-resync /
stray-SOF-resync / byte-at-a-time streaming.

**C build** (`cd charger && make test`): `gcc -std=c99 -Wall -Wextra -O2`
builds cleanly with zero warnings; `./test_frames_host`'s 19 internal
`CHECK()`s all pass (`ALL CHECKS PASSED`), including the standard
CRC-16/CCITT-FALSE check value for `"123456789"` (`0x29B1`), a payload
deliberately containing SOF/EOF/ESC bytes round-tripping through stuffing,
a corrupted-CRC frame being silently dropped with the parser recovering the
*next* valid frame, and a stray SOF interrupting an in-progress frame being
absorbed correctly.

**C/Python codec parity** (`test_c_matches_python_byte_for_byte`, run from
`pytest`): every command in `parity_vectors.txt` — including one value
(`0xAAAA`) chosen specifically to trigger the byte-stuffing path — encodes
to byte-identical hex from both languages.

### Computed setpoints (design 03 Sec.3.1/3.2 formula, this module's default
per-cell values, `python3 -c "..."` against `policy.py`)

| T (°C) | Float (V) | Absorption (V) | Equalise (V) | Current limit (%) |
|---|---|---|---|---|
| 10 | 13.980 | 14.970 | 15.500 (ceiling-clamped) | 100 |
| 25 | 13.620 | 14.610 | 15.240 | 100 |
| 40 | 13.260 | 14.250 | 14.880 | 100 |

(`V_target(T) = 6 x (V_25/cell + coeff x (T-25))`, coeff = -4 mV/°C/cell;
15.5 V hardware ceiling from 03 Sec.1.1. At 10 °C the equalise setpoint
would be 15.60 V uncompensated — the ceiling clamp is doing real work here,
which is exactly the case the clamp exists for.)

## Honest limits

- **No real Indian home inverter exposes this UART interface today** (03
  Sec.0: analog PWM controllers, no documented control bus). Everything in
  this module that issues *commands* (as opposed to computing advisory
  setpoints) is scoped to the **Embedded SKU only** — a hypothetical future
  V-Guard-owned charger board. `sim_charger.py` is a test double for that
  future MCU/DAC bridge, not a model of any shipping product.
- **Only the simulated charger was executed here.** No hardware-in-the-loop
  bench, no real UART link, no real PWM feedback-node DAC injection (03
  Sec.1.1). "48 tests passed" and "19 C checks passed" describe a scripted,
  in-process/host-process exercise, not a wired rig.
- **Battery-specific limits (C20_ah, per-cell setpoints, temperature
  coefficient) are illustrative defaults**, not measured for a specific
  V-Guard battery. 03 Sec.3.1 gives ranges (e.g. float 2.23-2.30 V/cell);
  this module picks the midpoint of each range and documents that choice in
  `policy.py`'s module docstring. **Before field use these MUST come from
  the manufacturer's own datasheet** for the battery actually deployed —
  the same caveat CONTRACTS.md Sec.7 and every other module in this
  prototype carries for its own illustrative constants.
- **Two design-doc ambiguities were resolved by engineering judgement, not
  by the design doc itself** (both documented at their definition sites):
  (1) SET_FLOAT's payload is annotated "uint16 (mV/cell x100)" in 03
  Sec.1.2's table while SET_ABSORPTION/SET_EQUALISE say plain "uint16
  mV/cell" — taking "x100" literally on SET_FLOAT alone overflows a uint16
  for any real setpoint and is inconsistent with the other two commands, so
  all three are encoded identically as whole millivolts/cell here; (2) byte
  order for multi-byte payload fields isn't stated, so this module uses
  little-endian throughout (matching the framing's own stated
  `[CRC16_L][CRC16_H]` low-byte-first order).
- **The byte-stuffing algorithm (PPP/HDLC-style ESC+XOR) and the CRC
  variant (CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no
  reflect/xorout) are this module's concrete choice** for "byte-stuffed...
  CRC-16/CCITT" (03 Sec.1.2 states the requirement, not the exact
  algorithm). Both are standard, testable constructions, not invented
  one-offs, and the CRC implementation is checked against the textbook
  `CRC-16/CCITT-FALSE("123456789") == 0x29B1` reference value.
  `parity_vectors.txt` exists precisely so the C and Python ports can never
  silently drift from each other on this choice.
- **The absorption/float/equalise phase state machine is this module's
  own construction**, not literally specified by 03 Sec.3.2's one-line
  pseudocode. In particular: (a) bulk-phase CC ramp-up is deliberately out
  of scope — the charger hardware's own closed loop under the absorption
  voltage cap handles it ("defence in depth", 03 Sec.1.2); this module only
  decides which setpoint should currently be in effect. (b) Absorption is
  (re)entered whenever `charging_requested and grid_ok` and either SoC is
  unknown/not yet full or a pre-charge is active — there is no independent
  bulk->absorption crossover detector here (that would duplicate the EKF's
  own SoC/charger-state role, 01 Sec.5a/5b, which is out of this module's
  scope). (c) The 6 h equalisation "no outage predicted" gate condition
  reuses the pre-charge trigger's own probability/confidence thresholds
  (P > 0.55, confidence >= 0.5) because 03 Sec.3.2 gives numbers for the 3 h
  pre-charge case only, not a separate number for the 6 h gate.
- **"Quarter" for the water-loss cap is a rolling 90-day window in the same
  monotonic-seconds clock used everywhere else in this prototype**, not a
  calendar quarter — there is no wall-clock dependency anywhere in
  `prototype/code/`, and introducing one just for this cap would be
  inconsistent with every other module.
- **The setpoint floor (12.0 V pack) and the equalisation quarterly cap
  (8 h) are this module's own illustrative defaults.** The task explicitly
  asks for "a floor" alongside the 15.5 V hardware ceiling and for a
  quarterly cap "guard[ing] against water loss," but 03 gives numbers for
  neither. Both are `ChargerConfig` fields, meant to be overridden per
  battery/installation, not shipped values.
- **`sim_charger.py`'s battery model is a toy 2nd-order Thevenin
  equivalent** (OCV(SoC) + R0 + one RC branch, illustrative parameters),
  deliberately *not* the project's EKF (`ekf/`) — it exists only to give
  the simulated charger's CC/CV/float regulation something to act on, not
  to validate SoC/SoH estimation. Its OCV curve, R0/R1/C1 values and
  proportional-controller gain are not fit to any measured cell.
  `SimCharger` itself is a small mutable class rather than an immutable
  dataclass — deliberately, matching the project's existing precedent for
  stateful device/plant models (`ekf.py`'s `EKF` class, the C `ap_t`/`hl_t`
  structs) — the immutability discipline in this codebase targets *decision
  logic* (`policy.py` is a pure function throughout), not a simulated piece
  of hardware that genuinely has state evolving over wall time.
- **GET_STATUS and NACK payload layouts are this module's own choice.** 03
  Sec.1.2 names the fields ("mode, fault flags, V_batt, I_batt if sensed"
  for GET_STATUS; "uint8 code" for NACK) without pinning exact widths;
  `frames.py`'s module docstring records the concrete 8-byte status layout
  and the 4 NACK codes used here.
- **The 15-30 % life-extension claim (03 Sec.3.3) is not validated by
  anything in this module.** This module implements the mechanism the
  claim depends on (temperature compensation, adaptive absorption,
  gated equalisation); the claim itself can only be validated by the
  aging campaign (design 04), which does not run here.
