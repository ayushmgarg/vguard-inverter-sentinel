# healthlog — module F: the signed, append-only, hash-chained health log

Implements design doc **09-Security-OTA-and-Health-Log.md §4** ("Signed, tamper-evident
health log — the warranty instrument"), the pseudonymisation formula from **08
-Fleet-Learning-Central-and-Federated.md §A4**, the time source from **10-Hardware
-Interfaces-and-Power.md §6** (DS3231), and the C API frozen in `../CONTRACTS.md` §6. The
exact byte layout is in [`format.md`](format.md) — read that first if you're implementing
against this module rather than just using it.

Two parallel implementations, kept in lockstep by the shared format:
- **`healthlog.py`** — the Python reference implementation (writer, verifier, key handling,
  claim bundle).
- **`healthlog.c` / `healthlog.h`** — the C99, host-buildable implementation matching the
  `hl_append` / `hl_verify_chain` signatures fixed in `CONTRACTS.md` §6, plus a bundled
  fallback SHA-256 (`sha256.c`/`sha256.h`).

Cross-verified against each other: `tests/test_healthlog.py` builds a chain in Python and
verifies it with the C binary, and vice versa (see "Test results" below).

## Commands

```bash
# Python: exercised entirely through pytest, no separate CLI.
cd code/                      # CONTRACTS.md §0: all tests run from the code/ root
pytest -q tests/test_healthlog.py     # this module only
pytest -q                              # whole prototype suite

# C: build + host self-test (produces chain_from_c.bin / pubkey_from_c.bin as a side effect,
# used by the Python cross-verification tests above)
cd healthlog/
make clean && make          # auto-detects libcrypto via pkg-config, see "Crypto backend"
./test_healthlog_host       # run the self-test directly (writer, verifier, tamper/delete/
                             # resume checks); pytest also runs this via subprocess
make backend                 # prints HAVE_OPENSSL=0/1 without building, for CI/diagnostics

# Verify an externally-produced chain (e.g. one written by healthlog.py) with the C verifier:
./test_healthlog_host --verify path/to/chain.bin path/to/pubkey_64B.bin
```

## Record size

Per `format.md` §2: **`112 + len(payload)` bytes per record** (16-byte header + payload +
32-byte `prev_hash` + 64-byte signature). A payload-less event (e.g. a bare heartbeat) is
112 bytes. `len` is a `u16`, so payload is capped at 65 535 bytes — every event type actually
produced by this design (SoH %, temperature, grade code, firmware semver, ...) is a handful
of bytes, nowhere near that ceiling.

## Test results

Last run (host: this container, `gcc 13.3.0`, `Python 3.9.19`, `cryptography 42.0.0`,
`OpenSSL 3.0.13`):

```
$ pytest -q tests/test_healthlog.py
........................                                                [100%]
24 passed in 1.79s

$ pytest -q            # whole code/ suite, confirms this module didn't break anything else
...........................................                            [100%]
43 passed in 3.30s

$ cd healthlog && make clean && make && ./test_healthlog_host
HAVE_OPENSSL=1
[...20 "ok:" lines covering init/append/verify/tamper/delete/resume/write...]
all checks passed
```

What each pytest test actually checks (see `tests/test_healthlog.py` for the full list):
valid-chain acceptance; wrong-pubkey rejection; single-byte tamper in every field (`counter`,
`ts_ms`, `type`, `len`, `payload`, `prev_hash` — including the genesis record's own
`prev_hash` — and `sig`) each failing at the exact right record index; middle-record deletion
(counter gap); two-record reorder; replay via re-inserting an old record; truncation, both
the structural (mid-record cut) and the "clean prefix" case that only `expected_last_counter`
can catch; resume-from-file continuing the counter/hash chain correctly across a simulated
process restart; resume refusing a corrupted on-disk file; `claim_bundle` self-verification;
pseudonym derivation determinism/rotation; and four cross-verification tests (C self-test
passes under pytest; a C-produced chain verifies in Python; a Python-produced chain verifies
in the C binary; a Python-tampered chain is rejected by the C binary).

## Crypto backend

The C build **used `libcrypto` (OpenSSL) for both SHA-256 and ECDSA-P256** on this host
(`pkg-config --exists libcrypto` succeeded; `Makefile` set `-DHL_USE_OPENSSL` and linked
`-lcrypto`). Concretely:
- **SHA-256**: `EVP_Digest` / `EVP_MD_CTX` (`healthlog.c`).
- **ECDSA-P256 verify**: legacy `EC_KEY` / `ECDSA_SIG` API (`ECDSA_do_verify` on a
  `BN_bin2bn`-reconstructed raw-`r`/`s` signature and an `EC_POINT_oct2point`-reconstructed
  public key) — chosen over `EVP_PKEY` because `EVP_PKEY`'s signature API speaks DER, and
  this format's 64-byte fixed-size `r‖s` wire signature (format.md §4) needs the low-level
  component accessors. OpenSSL 3.0 deprecates this API in favour of `EVP_PKEY` but it remains
  fully functional; the Makefile passes `-Wno-deprecated-declarations` for exactly this.
- **ECDSA-P256 sign** (`test_healthlog_host.c`'s `openssl_sign_cb`, standing in for the
  secure element): `ECDSA_do_sign` on the same `EC_KEY`, r/s extracted with
  `ECDSA_SIG_get0` and packed via `BN_bn2binpad`.

**If libcrypto/OpenSSL headers are not found** (`sha256.c`/`sha256.h`, self-rolled, no
dependencies, verified byte-for-byte against Python's `hashlib.sha256` across empty input,
short strings, and every SHA-256 block-boundary edge case from 50–65 input bytes):
- SHA-256 still works (`hl_sha256` in `sha256.c` is unconditionally compiled in and used).
- **ECDSA verification and signing are unavailable** — `healthlog.h` documents this: signing
  was always going to be callback-only (see "Design intent" below), but without OpenSSL there
  is no bundled ECDSA implementation to call for *verification* either.
  `hl_verify_chain`/`hl_verify_chain_detail` still walk the hash chain (counter continuity +
  `prev_hash` linkage) and will correctly catch deletion/reorder/replay/truncation, but
  **cannot catch a payload/header tamper that recomputes to a chain-consistent hash with a
  forged-but-unchecked signature** — `hl_verify_chain_detail`'s `reason` string says so
  explicitly ("signatures NOT checked (built without OpenSSL/libcrypto)"), and
  `test_healthlog_host.c` falls back to a SHA-256-only known-answer test instead of the full
  signed-chain exercise. This environment has OpenSSL, so this path is present and compiles
  (`make HAVE_OPENSSL=0` effectively, i.e. undefine `HL_USE_OPENSSL`) but was not the path
  exercised by the "Test results" run above.

## Design intent: why signing is always a callback

`hl_append` **never holds or touches a private key**. Every signature is produced by a
caller-supplied `hl_sign_cb(hash32, sig64, ctx)` (`healthlog.h`), and `HealthLogWriter` in
Python takes an equivalent `sign_fn` callable. This is not incidental — it's the point: 09 §4
puts the real private key **inside an ATECC608 secure element, generated there, and never
extracted**. The host prototype's callback wraps an ordinary OpenSSL/`cryptography` software
key instead, but *no other code in this module changes* when the callback is swapped for one
that talks to real secure-element hardware over I2C. `hl_verify_chain` is a pure function over
bytes + a public key — it doesn't care who or what signed the chain, only whether the
signatures check out, which is exactly what a warranty dispute (09 §4 "Use") needs: the
verifier only ever needs the *registered public key*, never the device.

## Threat model coverage

| Threat | Design doc claim (09 §4) | What this implementation actually does | Verified by |
|---|---|---|---|
| **Tamper** | "no extractable key, so no forged plausible log" — a hash mismatch breaks the chain | Every record's hash covers its own header+payload+prev_hash; a verifier recomputes it and checks the ECDSA signature against the registered pubkey. Any single-bit change anywhere in a record's signed fields is caught **at that exact record's index** (never silently accepted, never misattributed to a different record). | `test_tamper_single_byte_detected_at_right_index` (9 field/index combinations, Python); "hl_verify_chain rejects a tampered byte" (C self-test) |
| **Deletion** | "the counter must strictly increase" — a counter gap | `counter` must equal the running record index exactly (0, 1, 2, ...); removing any record leaves a gap that fails at the first record after the hole. | `test_delete_middle_record_fails_with_gap`; "hl_verify_chain rejects a deleted middle record" (C) |
| **Reorder** | not named explicitly in 09 §4 but implied by "counter + chain" | Swapping two records breaks counter continuity (a record now claims a counter that isn't the next expected one) and/or `prev_hash` linkage. | `test_reorder_two_records_fails` |
| **Replay / re-insertion** | "replay — the counter must strictly increase and each signature covers the counter" | Splicing a copy of an old, individually-valid, individually-signed record back into the sequence still breaks counter continuity and `prev_hash` linkage at the insertion point — a valid signature on a record does not make it valid *at that position* in the chain. | `test_reinsert_old_record_fails` |
| **Truncation** (front/back) | not explicitly named in 09 §4 | Front: genesis (`counter==0`) must have an all-zero `prev_hash`, catching "start mid-chain". Back: a mid-record cut is a structural parse failure (caught unconditionally); a *clean* cut at a record boundary is provably indistinguishable from "this is the whole log" using the bytes alone — `verify_chain`/`hl_verify_chain_detail` accept an optional `expected_last_counter` for exactly this case, which the *verifier* (V-Guard, holding the device's last-known counter from a prior sync) supplies, not the chain itself. | `test_delete_last_record_only_detectable_with_known_counter` |
| **Clone** | "a clone needs its own registered key; ATECC608 keys are provisioned once and non-extractable" | **Out of scope for this software module** — cloning resistance is a hardware property of the ATECC608 (non-extractable key generated in-chip), not something `healthlog.py`/`healthlog.c` can provide or test. What this module *does* guarantee: a clone using a *different* key produces a chain that fails verification against the *registered* pubkey (`test_pubkey_mismatch_fails` demonstrates the mechanism), which is the software half of clone detection — the hardware half (can the key ever be extracted to put in a clone) is asserted by the chip datasheet, not by this code. | `test_pubkey_mismatch_fails` (mechanism only, not a hardware clone-resistance proof) |

## Honest limits

- **The private key here is a plain software ECDSA-P256 key**, generated by
  `cryptography`/OpenSSL in an ordinary process, not inside a secure element. Anyone with
  code-execution on this host can read it out of memory and forge an arbitrarily convincing
  chain. This is a deliberate and disclosed prototype simplification, not an oversight —
  09 §4 explicitly calls out "eFuse-only keys on the S3 are a lower-cost fallback with
  materially weaker tamper resistance; use the secure element wherever the log decides
  warranty." **Production must sign through the ATECC608**, generated in-chip at manufacture,
  never extracted. This library's `hl_sign_cb` / `sign_fn` callback boundary exists
  specifically so that swap requires zero changes to the chain/verification logic.
- **Clock trust**: `ts_ms` comes from whatever clock the writer used (`hl_now_ms()` in C,
  `time.time()` in Python; production is the DS3231, 10 §6) and is itself covered by the hash
  chain and signature — so a timestamp can't be edited *after the fact* without breaking
  verification, but nothing in this module stops a compromised device from writing a false
  timestamp *at append time*, before it's ever hashed. The log proves internal consistency
  and non-repudiation of what the device claimed, not ground truth about wall-clock time.
- **A physically substituted sensor is explicitly out of scope** (09 §4's own stated
  limitation, repeated here because it matters for how a warranty claim should be read): this
  log proves what the device's firmware *saw and hashed*, not that the battery/temperature/
  current readings feeding it were genuine. If an attacker feeds an honest logger forged
  sensor data upstream of `hl_append`, every record they produce will verify perfectly — the
  chain is airtight about *integrity and ordering*, not about *truthfulness of the inputs*.
  Sensor-plausibility checks (01 §3.4, 02 §6) are the documented mitigation, and live outside
  this module.
- **Payload contents are uninterpreted.** This module guarantees the *envelope* (ordering,
  integrity, non-repudiation) for whatever bytes a producer hands `hl_append`/`append()`; it
  does not validate, schema-check, or interpret `payload`. A producer writing a malformed or
  semantically-wrong payload (e.g. a SoH percentage of 200%) produces a perfectly
  chain-valid, signature-valid record — "valid" here means "provably came from the registered
  key, in this position, unmodified since," not "the contents make sense."
- **No key-rotation / revocation mechanism in this module.** The design (08 §A4) rotates the
  *pseudonym* quarterly, but the signing key itself is provisioned once at manufacture (09 §4)
  and this module has no code path for re-keying an in-field device or revoking a compromised
  key from the verifier side — the V-Guard device registry (09 §4 "public key registered ...
  at the same factory step") is where that would live, and it's out of this prototype's scope.
- **No storage/wear-leveling story.** `hl_init`/`hl_append` assume a caller-owned, statically
  allocated buffer (matching the "no malloc" requirement) but this module says nothing about
  how that buffer maps onto actual flash, circular overwrite policy once full, or
  power-loss-during-write atomicity on the real MCU — those are firmware-glue concerns
  (explicitly out of scope per `CONTRACTS.md` §0: "no ESP-IDF dependency in algorithm
  modules").


## Signed checkpoints (added 2026-09-22, review point 9)
`HealthLogWriter.checkpoint()` / `hl_checkpoint()` produce a 108-byte signed `{last_counter, ts_ms, head_hash}`; `verify_chain(..., checkpoint=)` / `hl_verify_chain_ckpt()` fail a chain that is shorter than the checkpoint (TRUNCATED), has a mismatching head hash, or a bad checkpoint signature. Tests: 7 new cases (31 total); a C-emitted checkpoint (`checkpoint_from_c.bin`) verifies in Python. Threat-table update — **truncation: detected up to the latest checkpoint held by the server/app; the window since the last checkpoint remains exposed.**
