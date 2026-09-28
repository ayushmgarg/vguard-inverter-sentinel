# Health-log binary record format

Implements design doc **09-Security-OTA-and-Health-Log.md §4** ("Signed, tamper-evident
health log") and the C API frozen in `CONTRACTS.md §6`. This file is the single source of
truth for the on-disk / on-wire byte layout; `healthlog.py` and `healthlog.c` both implement
exactly this.

## 1. Byte order

**All multi-byte integer fields are little-endian.** This matches the ESP32-S3 target (both
its Xtensa and RISC-V variants are LE) and every host platform (x86-64, ARM64 Linux/macOS)
this prototype is built and tested on. Cross-verification between the C and Python
implementations (`tests/test_healthlog.py`) depends on both sides agreeing on this; a device
targeting a big-endian MCU would need to re-derive the format, not just recompile.

## 2. Record layout

A record is a flat byte sequence, fields in this exact order, with **no padding** between
them (`healthlog.c` uses explicit byte-wise packing, not a packed C struct, so it cannot
inherit compiler alignment padding on any platform):

| Field | Type | Size | Offset | Meaning |
|---|---|---|---|---|
| `counter` | `u32` LE | 4 | 0 | Monotonic record index. First record (genesis) is `0`; each subsequent record is exactly `+1`. Never reused, never skipped. |
| `ts_ms` | `u64` LE | 8 | 4 | Milliseconds since Unix epoch, from the DS3231-backed RTC (10 §6) in production; `time.time()*1000` / `gettimeofday` on host. Not itself authenticated against an external clock — see README threat-model limits. |
| `type` | `u16` LE | 2 | 12 | Event type, see §4 enum. |
| `len` | `u16` LE | 2 | 14 | Length of `payload` in bytes. `0 <= len <= 65535`. |
| `payload` | `u8[len]` | `len` | 16 | Event-specific data (opaque to the log itself — e.g. a small packed struct with SoH %, temperature, grade code, firmware semver, ...). Payload schemas are defined per event type by the producing module, not by this log. |
| `prev_hash` | `u8[32]` | 32 | `16+len` | The hash (§3) of the **previous** record. All-zero for the genesis record (`counter == 0`). |
| `sig` | `u8[64]` | 64 | `16+len+32` | ECDSA-P256 signature over this record's own hash (§3), raw `r‖s` (32 B `r` + 32 B `s`, each big-endian per SEC1/ECDSA convention — this is the one field in the record that is *not* little-endian, since it is opaque signature material, not an integer the log interprets). |

**Total record size = `112 + len` bytes.** With `len == 0` (an event carrying no payload,
e.g. a bare heartbeat) a record is 112 bytes.

A serialized log/chain is simply records concatenated back-to-back in append order, with no
inter-record separator, length prefix, or trailer — a reader recovers record boundaries by
reading `len` out of each record's own 16-byte header before reading its payload.

## 3. Hash

```
hash = SHA-256( counter (4B LE) ‖ ts_ms (8B LE) ‖ type (2B LE) ‖ len (2B LE) ‖ payload (len B) ‖ prev_hash (32B) )
```

i.e. SHA-256 over every byte of the record **except** `sig` itself (§2 offsets `0` through
`16+len+32`, exclusive of the trailing 64 signature bytes). This is exactly the first
`112 + len - 64 = 48 + len` bytes of the serialized record.

This hash is:
1. What gets **signed** (§4) to produce `sig`.
2. What the **next** record stores in its own `prev_hash` — this is the hash chain link.

The hash is never itself stored in the record; a verifier (or the writer, when resuming)
recomputes it from the record's own fields.

## 4. Signature

ECDSA over curve **P-256 (secp256r1 / prime256v1)**, signing the 32-byte hash from §3
directly (the hash is treated as already-hashed / "prehashed" input to ECDSA — it is not
hashed a second time). The signature is stored in **raw `r‖s` form, 64 bytes**, not DER: `r`
(32 bytes, big-endian, zero-padded if short) followed by `s` (32 bytes, big-endian,
zero-padded if short). This is the fixed-size, parse-free form suitable for an MCU and for
the flat record layout above; DER is not used anywhere in this format.

The private key never appears in this format or in `healthlog.c`'s data structures — signing
happens exclusively through the `hl_sign_cb` callback (`healthlog.h`), so the same code path
works whether the signer is an OpenSSL software key (this prototype, host build) or an
ATECC608 secure element (production target, 09 §4) that never releases its private key.

The public key, wherever referenced in this codebase (`healthlog.py` key export, `pubkey[64]`
parameter to `hl_verify_chain`), is the raw uncompressed P-256 point **without** the leading
`0x04` SEC1 tag: 32 bytes `X` followed by 32 bytes `Y`, big-endian — i.e. `SEC1
uncompressed-point (65 B)` with the tag byte stripped.

## 5. Genesis record

The first record ever appended (`counter == 0`) has `prev_hash` = 32 zero bytes. There is no
special-cased "genesis marker" event type; genesis is identified purely by `counter == 0` and
an all-zero `prev_hash`. A verifier checks this explicitly: a chain whose first record has
`counter != 0` or a non-zero `prev_hash` is invalid from record 0 (this also catches "start
mid-chain" truncation of the *front* of a buffer, as opposed to the back — see README §
truncation).

## 6. Event type enum

`type` (u16). Values are stable across the Python and C implementations (`healthlog.py`
`EventType`, `healthlog.h` `HL_*` constants) and MUST NOT be renumbered once devices in the
field have written logs using them — a renumbering invalidates every historical claim bundle.

| Value | Name | Producer (design doc) |
|---|---|---|
| 0 | `FULL_CHARGE` | full-charge detection (01, 09 §4) |
| 1 | `CAPACITY_SAMPLE` | capacity sample (01, 02) |
| 2 | `GRADE_CHANGE` | SoH grade transition (02 §3) |
| 3 | `ANOMALY` | anomaly alarm |
| 4 | `OVER_TEMP` | over-temperature event |
| 5 | `DEEP_DISCHARGE` | deep discharge event |
| 6 | `PQ_EVENT` | power-quality event (07) |
| 7 | `CHARGER_SETPOINT` | charger setpoint applied (03) |
| 8 | `USER_OVERRIDE` | user override of autopilot (05) |
| 9 | `FW_VERSION` | firmware version record (OTA, 09 §3) |
| 10 | `MODEL_VERSION` | model version record (OTA, 09 §3) |

`payload` contents per type are out of scope for this module (module F only guarantees the
envelope is tamper-evident and ordered) — each producing module defines and versions its own
payload struct; this log does not interpret `payload` bytes at all.

## 7. Worked example (genesis record, empty payload)

```
counter    = 0            -> 00 00 00 00
ts_ms      = 1000          -> E8 03 00 00 00 00 00 00
type       = 9 (FW_VERSION)-> 09 00
len        = 0             -> 00 00
payload    = (none)
prev_hash  = 32 x 0x00
hash_input = the 48 bytes above (16-byte header + 0 payload + 32-byte prev_hash)
hash       = SHA-256(hash_input)                      (32 bytes)
sig        = ECDSA-P256-raw(private_key, hash)         (64 bytes)
record     = hash_input (48B) || sig (64B) = 112 bytes total
```


## Signed checkpoint (truncation detection)
`Checkpoint = {u32 last_counter, u64 ts_ms, u8 head_hash[32], u8 sig[64]}` (108 B), signature by the same device key over `last_counter ‖ ts_ms ‖ head_hash`, where `head_hash` is the running hash of the record with that counter.

**Use:** the device emits a checkpoint with every telemetry batch (design 08 §A3) and on every app sync; the server and app keep the latest one. A warranty claim is verified with `verify_chain(buf, pubkey, checkpoint=latest)`: the checkpoint signature must verify, the chain must contain a record with `last_counter` whose running hash equals `head_hash`, and a chain that ends before `last_counter` is **TRUNCATED**. Newer records after the checkpoint are allowed.

**What a checkpoint cannot do:** records appended after the latest checkpoint can still be dropped undetected until the next checkpoint is taken — the exposure window equals the checkpoint interval. A clean prefix with no checkpoint at all remains undetectable, as before.
