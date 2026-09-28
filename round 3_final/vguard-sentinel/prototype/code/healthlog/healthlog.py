"""Signed, append-only, hash-chained health log — Python reference implementation.

Implements the format frozen in ``healthlog/format.md`` and the module contract in
``CONTRACTS.md`` §6 / design doc ``09-Security-OTA-and-Health-Log.md`` §4. This is the
prototype "warranty instrument": a writer appends events, each hash-chained to the previous
record and signed; a verifier, given only the registered public key, can detect tampering,
deletion, reorder, replay/re-insertion, and truncation without trusting the device.

Honesty note (see README "Limits"): the private key here is an ordinary software ECDSA-P256
key held in the Python process. In production (09 §4) the key is generated inside and never
leaves an ATECC608 secure element; ``HealthLogWriter`` takes a ``sign_fn`` callback for
exactly this reason — swapping in a secure-element-backed callback requires no change to the
chain/verification logic below.

Python 3.9 compatible: no ``match``, no ``X | Y`` union syntax.
"""

import hashlib
import os
import struct
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils as ec_utils
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


# --------------------------------------------------------------------------------------
# Constants / format (see format.md)
# --------------------------------------------------------------------------------------

HEADER_FMT = "<IQHH"  # counter u32, ts_ms u64, type u16, len u16
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 16
HASH_SIZE = 32
SIG_SIZE = 64
PUBKEY_SIZE = 64
GENESIS_PREV_HASH = b"\x00" * HASH_SIZE

assert HEADER_SIZE == 16

# Checkpoint (format.md §8): last_counter u32, ts_ms u64, head_hash[32], sig[64].
CHECKPOINT_HEADER_FMT = "<IQ"  # last_counter u32, ts_ms u64
CHECKPOINT_HEADER_SIZE = struct.calcsize(CHECKPOINT_HEADER_FMT)  # 12
CHECKPOINT_SIZE = CHECKPOINT_HEADER_SIZE + HASH_SIZE + SIG_SIZE  # 12 + 32 + 64 = 108

assert CHECKPOINT_HEADER_SIZE == 12
assert CHECKPOINT_SIZE == 108


class EventType(IntEnum):
    FULL_CHARGE = 0
    CAPACITY_SAMPLE = 1
    GRADE_CHANGE = 2
    ANOMALY = 3
    OVER_TEMP = 4
    DEEP_DISCHARGE = 5
    PQ_EVENT = 6
    CHARGER_SETPOINT = 7
    USER_OVERRIDE = 8
    FW_VERSION = 9
    MODEL_VERSION = 10


class HealthLogError(Exception):
    """Raised on malformed input or an attempt to resume onto a broken chain."""


# --------------------------------------------------------------------------------------
# Record — immutable
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Record:
    """One health-log record. Immutable: constructing a "changed" record means building a
    new ``Record``, never mutating fields of an existing one (coding-style: immutability)."""

    counter: int
    ts_ms: int
    type: int
    payload: bytes
    prev_hash: bytes
    sig: bytes

    def __post_init__(self):
        if not (0 <= self.counter <= 0xFFFFFFFF):
            raise HealthLogError("counter out of u32 range")
        if not (0 <= self.ts_ms <= 0xFFFFFFFFFFFFFFFF):
            raise HealthLogError("ts_ms out of u64 range")
        if not (0 <= self.type <= 0xFFFF):
            raise HealthLogError("type out of u16 range")
        if len(self.payload) > 0xFFFF:
            raise HealthLogError("payload too large for u16 len field")
        if len(self.prev_hash) != HASH_SIZE:
            raise HealthLogError("prev_hash must be 32 bytes")
        if len(self.sig) != SIG_SIZE:
            raise HealthLogError("sig must be 64 bytes")

    def signed_bytes(self) -> bytes:
        """Header ‖ payload ‖ prev_hash — exactly the bytes that are hashed and signed."""
        header = struct.pack(HEADER_FMT, self.counter, self.ts_ms, self.type, len(self.payload))
        return header + self.payload + self.prev_hash

    def hash(self) -> bytes:
        return hashlib.sha256(self.signed_bytes()).digest()

    def to_bytes(self) -> bytes:
        return self.signed_bytes() + self.sig

    @staticmethod
    def parse_at(buf: bytes, offset: int) -> Tuple["Record", int]:
        """Parse one record starting at ``offset``. Returns (record, next_offset).
        Raises HealthLogError if the buffer is truncated (not enough bytes for the
        declared header/payload/prev_hash/sig)."""
        if offset + HEADER_SIZE > len(buf):
            raise HealthLogError("truncated: not enough bytes for record header")
        counter, ts_ms, type_, ln = struct.unpack_from(HEADER_FMT, buf, offset)
        o = offset + HEADER_SIZE
        end_payload = o + ln
        end_prev = end_payload + HASH_SIZE
        end_sig = end_prev + SIG_SIZE
        if end_sig > len(buf):
            raise HealthLogError("truncated: not enough bytes for payload/prev_hash/sig")
        payload = bytes(buf[o:end_payload])
        prev_hash = bytes(buf[end_payload:end_prev])
        sig = bytes(buf[end_prev:end_sig])
        return Record(counter, ts_ms, type_, payload, prev_hash, sig), end_sig


def parse_all(buf: bytes) -> List[Record]:
    """Parse every record in ``buf`` with no validation beyond structural framing.
    Raises HealthLogError on a trailing partial record (truncation)."""
    records = []
    offset = 0
    n = len(buf)
    while offset < n:
        rec, offset = Record.parse_at(buf, offset)
        records.append(rec)
    return records


# --------------------------------------------------------------------------------------
# Checkpoint — signed truncation-detection attestation (format.md §8)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Checkpoint:
    """A small, independently-signed attestation of "the chain's head is at counter
    ``last_counter``, whose own running hash is ``head_hash``, as of ``ts_ms``".

    This does not grow the chain itself; it is a separate 108-byte signed object a
    verifier can hold onto (from a prior telemetry upload or app sync, see format.md §8)
    and later check a chain against, to catch a *clean* truncation of the chain's tail —
    the one class of tamper ``verify_chain`` alone cannot detect without such external
    knowledge (README "Honest limits").
    """

    last_counter: int
    ts_ms: int
    head_hash: bytes
    sig: bytes

    def __post_init__(self):
        if not (0 <= self.last_counter <= 0xFFFFFFFF):
            raise HealthLogError("last_counter out of u32 range")
        if not (0 <= self.ts_ms <= 0xFFFFFFFFFFFFFFFF):
            raise HealthLogError("ts_ms out of u64 range")
        if len(self.head_hash) != HASH_SIZE:
            raise HealthLogError("head_hash must be 32 bytes")
        if len(self.sig) != SIG_SIZE:
            raise HealthLogError("sig must be 64 bytes")

    def signed_bytes(self) -> bytes:
        """last_counter ‖ ts_ms ‖ head_hash — exactly the bytes that are hashed and
        signed (format.md §8)."""
        header = struct.pack(CHECKPOINT_HEADER_FMT, self.last_counter, self.ts_ms)
        return header + self.head_hash

    def digest(self) -> bytes:
        return hashlib.sha256(self.signed_bytes()).digest()

    def to_bytes(self) -> bytes:
        return self.signed_bytes() + self.sig

    # serialize/parse are the names asked for in the module brief; kept as aliases of the
    # Record-style to_bytes()/parse_at() so both naming conventions work.
    def serialize(self) -> bytes:
        return self.to_bytes()

    @staticmethod
    def parse(buf: bytes) -> "Checkpoint":
        """Parse exactly CHECKPOINT_SIZE bytes from the start of ``buf``. Raises
        HealthLogError if ``buf`` is shorter than that."""
        if len(buf) < CHECKPOINT_SIZE:
            raise HealthLogError("truncated: not enough bytes for a checkpoint")
        last_counter, ts_ms = struct.unpack_from(CHECKPOINT_HEADER_FMT, buf, 0)
        o = CHECKPOINT_HEADER_SIZE
        head_hash = bytes(buf[o : o + HASH_SIZE])
        sig = bytes(buf[o + HASH_SIZE : o + HASH_SIZE + SIG_SIZE])
        return Checkpoint(last_counter, ts_ms, head_hash, sig)

    def verify_signature(self, pubkey: bytes) -> bool:
        """Verify this checkpoint's own signature against ``pubkey`` (raw 64B), without
        looking at any chain bytes at all."""
        return verify_hash_sig(pubkey, self.digest(), self.sig)


# --------------------------------------------------------------------------------------
# Key handling
# --------------------------------------------------------------------------------------


def generate_keypair() -> ec.EllipticCurvePrivateKey:
    """Software ECDSA-P256 keypair for the host prototype. Production keys are generated
    inside the ATECC608 and never touch a general-purpose CPU (09 §4)."""
    return ec.generate_private_key(ec.SECP256R1())


def export_public_key_raw(key) -> bytes:
    """Raw 64-byte X‖Y public key (no SEC1 0x04 tag) — see format.md §4.
    Accepts either a private key (its public part is exported) or a public key."""
    pub = key.public_key() if isinstance(key, ec.EllipticCurvePrivateKey) else key
    encoded = pub.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    if len(encoded) != 65 or encoded[0] != 0x04:
        raise HealthLogError("unexpected public key encoding")
    return encoded[1:]


def _pubkey_from_raw(pubkey: bytes) -> ec.EllipticCurvePublicKey:
    if len(pubkey) != PUBKEY_SIZE:
        raise HealthLogError("pubkey must be 64 raw bytes (X||Y)")
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b"\x04" + pubkey)


def sign_hash(private_key: ec.EllipticCurvePrivateKey, digest32: bytes) -> bytes:
    """ECDSA-P256 over an already-computed 32-byte SHA-256 digest, returned as raw r‖s
    (64 bytes) per format.md §4."""
    if len(digest32) != HASH_SIZE:
        raise HealthLogError("digest must be 32 bytes")
    der = private_key.sign(digest32, ec.ECDSA(ec_utils.Prehashed(hashes.SHA256())))
    r, s = ec_utils.decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def verify_hash_sig(pubkey: bytes, digest32: bytes, sig64: bytes) -> bool:
    if len(sig64) != SIG_SIZE:
        return False
    try:
        pub = _pubkey_from_raw(pubkey)
    except Exception:
        return False
    r = int.from_bytes(sig64[:32], "big")
    s = int.from_bytes(sig64[32:], "big")
    der = ec_utils.encode_dss_signature(r, s)
    try:
        pub.verify(der, digest32, ec.ECDSA(ec_utils.Prehashed(hashes.SHA256())))
        return True
    except InvalidSignature:
        return False


# Signature of the pluggable signer callback: digest32 -> sig64. Lets a caller swap in
# something other than an in-process private key (e.g. a subprocess proxy for a secure
# element) without touching HealthLogWriter's chain logic.
SignFn = Callable[[bytes], bytes]


def make_sign_fn(private_key: ec.EllipticCurvePrivateKey) -> SignFn:
    return lambda digest32: sign_hash(private_key, digest32)


# --------------------------------------------------------------------------------------
# Writer
# --------------------------------------------------------------------------------------


class HealthLogWriter:
    """Append-only writer. Holds the in-memory chain state (next counter, last hash) and
    optionally persists every appended record to a file, resuming from it if it already
    exists and is non-empty.

    ``Record`` objects are immutable; the writer's own bookkeeping (counter, last hash,
    buffered bytes) is ordinary mutable I/O state, not a domain object being mutated.
    """

    def __init__(
        self,
        sign_fn: SignFn,
        pubkey: Optional[bytes] = None,
        path: Optional[str] = None,
    ):
        """``pubkey`` (raw 64B), if given, is used to verify the chain on resume before
        trusting it — a writer should never blindly append onto a chain it cannot itself
        confirm is intact. If ``path`` doesn't exist yet, a fresh chain is started."""
        self._sign_fn = sign_fn
        self._pubkey = pubkey
        self._path = path
        self._buf = bytearray()
        self._counter = 0
        self._last_hash = GENESIS_PREV_HASH

        if path is not None and os.path.exists(path) and os.path.getsize(path) > 0:
            self._resume(path)

    def _resume(self, path: str) -> None:
        with open(path, "rb") as f:
            data = f.read()
        if self._pubkey is not None:
            ok, n_records, first_bad, reason = verify_chain(data, self._pubkey)
            if not ok:
                raise HealthLogError(
                    "cannot resume: existing log file is not a valid chain "
                    "(record %s: %s)" % (first_bad, reason)
                )
            records = parse_all(data)
            assert len(records) == n_records
        else:
            # No pubkey available to this writer instance: still parse and check the hash
            # chain (structure + linkage), just not signatures.
            records = parse_all(data)
            running = GENESIS_PREV_HASH
            for i, rec in enumerate(records):
                if rec.counter != i:
                    raise HealthLogError("cannot resume: counter gap at record %d" % i)
                if rec.prev_hash != running:
                    raise HealthLogError("cannot resume: broken hash chain at record %d" % i)
                running = rec.hash()
        self._buf = bytearray(data)
        if records:
            last = records[-1]
            self._counter = last.counter + 1
            self._last_hash = last.hash()

    def append(self, event_type: int, payload: bytes, ts_ms: Optional[int] = None) -> Record:
        if ts_ms is None:
            ts_ms = int(time.time() * 1000)
        counter = self._counter
        prev_hash = self._last_hash
        header = struct.pack(HEADER_FMT, counter, ts_ms, int(event_type), len(payload))
        digest = hashlib.sha256(header + payload + prev_hash).digest()
        sig = self._sign_fn(digest)
        rec = Record(counter, ts_ms, int(event_type), bytes(payload), prev_hash, sig)

        rec_bytes = rec.to_bytes()
        self._buf += rec_bytes
        if self._path is not None:
            with open(self._path, "ab") as f:
                f.write(rec_bytes)

        # advance state only after the write above succeeded
        self._counter = counter + 1
        self._last_hash = digest
        return rec

    @property
    def buffer(self) -> bytes:
        return bytes(self._buf)

    @property
    def counter(self) -> int:
        """Next counter value that will be used (== number of records appended so far)."""
        return self._counter

    def checkpoint(self, ts_ms: Optional[int] = None) -> Checkpoint:
        """Produce a signed checkpoint over the writer's current head (the most recently
        appended record) — see format.md §8. Signs through the same ``sign_fn`` as
        ``append`` (never touches a private key directly). Raises HealthLogError if
        nothing has been appended yet (there is no head to checkpoint)."""
        if self._counter == 0:
            raise HealthLogError("cannot checkpoint an empty log")
        if ts_ms is None:
            ts_ms = int(time.time() * 1000)
        last_counter = self._counter - 1
        head_hash = self._last_hash
        header = struct.pack(CHECKPOINT_HEADER_FMT, last_counter, ts_ms)
        digest = hashlib.sha256(header + head_hash).digest()
        sig = self._sign_fn(digest)
        return Checkpoint(last_counter, ts_ms, head_hash, sig)


# --------------------------------------------------------------------------------------
# Verifier
# --------------------------------------------------------------------------------------


def verify_chain(
    buf: bytes,
    pubkey: bytes,
    expected_last_counter: Optional[int] = None,
    checkpoint: Optional[Checkpoint] = None,
) -> Tuple[bool, int, Optional[int], str]:
    """Verify a full hash-chained, signed record buffer against ``pubkey`` (raw 64B).

    Returns ``(ok, n_records, first_bad_index, reason)``:
      - ``ok``: True iff every record verified (and, if ``expected_last_counter`` and/or
        ``checkpoint`` were given, the chain actually reaches that point — see truncation
        note below).
      - ``n_records``: number of records that verified successfully (== len(buf's records)
        when ok).
      - ``first_bad_index``: index of the first record that failed, or None if ok.
      - ``reason``: human-readable reason for the first failure, or "ok".

    Detects, per design doc 09 §4 / CONTRACTS §6:
      - **tamper**: any changed byte in a record changes its recomputed hash, which then
        fails either the signature check (payload/header/prev_hash tamper) or the next
        record's prev_hash-linkage check.
      - **deletion**: a missing middle record leaves a counter gap.
      - **reorder**: swapped records break counter-continuity and/or hash linkage.
      - **replay / re-insertion**: re-inserting an old record duplicates/violates strict
        counter continuity and breaks hash linkage at the insertion point.
      - **truncation**: a trailing partial record is a structural parse error; a *clean*
        cut at a record boundary (removing whole trailing records) is only detectable by
        the caller supplying the previously-known ``expected_last_counter``, or a
        previously-obtained signed ``checkpoint`` (format.md §8) — the chain bytes alone
        cannot distinguish "this is the whole log" from "this is a valid prefix of a
        longer log" without external knowledge of how far the log had grown.

    ``checkpoint``, if given, additionally requires (format.md §8):
      (a) the checkpoint's own signature verifies against ``pubkey``;
      (b) the chain contains a record at counter == ``checkpoint.last_counter`` whose own
          recomputed hash equals ``checkpoint.head_hash``;
      (c) the chain does not end before ``checkpoint.last_counter`` — reported with a
          "TRUNCATED" reason when it does. A chain *longer* than the checkpoint (newer
          records appended since the checkpoint was taken) is fine and still passes.
    """
    if len(pubkey) != PUBKEY_SIZE:
        return False, 0, 0, "invalid pubkey length"

    if checkpoint is not None and not checkpoint.verify_signature(pubkey):
        return False, 0, None, "checkpoint signature invalid"

    records: List[Record] = []
    offset = 0
    n = len(buf)
    index = 0
    while offset < n:
        try:
            rec, offset = Record.parse_at(buf, offset)
        except HealthLogError as e:
            return False, index, index, "truncated record at byte offset %d (%s)" % (offset, e)

        if rec.counter != index:
            return False, index, index, "counter gap or reorder: expected %d, got %d" % (
                index,
                rec.counter,
            )

        expected_prev = GENESIS_PREV_HASH if index == 0 else records[index - 1].hash()
        if rec.prev_hash != expected_prev:
            return False, index, index, "hash chain broken: prev_hash mismatch (tamper, reorder, or replay)"

        digest = rec.hash()
        if not verify_hash_sig(pubkey, digest, rec.sig):
            return False, index, index, "signature verification failed (tamper)"

        records.append(rec)
        index += 1

    if expected_last_counter is not None:
        last_seen = records[-1].counter if records else -1
        if last_seen != expected_last_counter:
            return (
                False,
                len(records),
                len(records),
                "truncated: expected last counter %d, chain ends at %d"
                % (expected_last_counter, last_seen),
            )

    if checkpoint is not None:
        last_seen = records[-1].counter if records else -1
        if last_seen < checkpoint.last_counter:
            return (
                False,
                len(records),
                len(records),
                "TRUNCATED: chain ends at counter %d, checkpoint requires %d"
                % (last_seen, checkpoint.last_counter),
            )
        target = records[checkpoint.last_counter]
        if target.hash() != checkpoint.head_hash:
            return (
                False,
                len(records),
                checkpoint.last_counter,
                "checkpoint head_hash mismatch at counter %d" % checkpoint.last_counter,
            )

    return True, len(records), None, "ok"


# --------------------------------------------------------------------------------------
# Claim bundle (warranty upload) — 09 §4 "Use", 09 §5, 08 §A4 (pseudonym)
# --------------------------------------------------------------------------------------

import base64
import hmac


def derive_pseudonym(device_secret: bytes, rotating_salt: bytes, epoch_id: bytes) -> str:
    """``pseudonym = Trunc128(HMAC-SHA256(device_secret, rotating_salt ‖ epoch_id))`` per
    design doc 08 §A4. ``device_secret`` lives in eFuse/ATECC608 and is never transmitted;
    only the resulting pseudonym goes in the claim bundle. Returned as 32 hex chars (128
    bits)."""
    mac = hmac.new(device_secret, rotating_salt + epoch_id, hashlib.sha256).digest()
    return mac[:16].hex()


def claim_bundle(buf: bytes, pubkey: bytes, device_pseudonym: str) -> dict:
    """Build the one-tap warranty-claim upload payload (09 §4 "Use", §5 data minimisation:
    the raw chain stays on device and only leaves it as part of an explicit, user-triggered
    claim). Self-verifies before bundling so a claim is never submitted with a chain the
    device itself cannot attest as intact; ``ok``/``reason`` are still included so the
    receiving party (V-Guard) redoes verification independently rather than trusting this
    flag."""
    ok, n_records, first_bad_index, reason = verify_chain(buf, pubkey)
    return {
        "format_version": 1,
        "device_pseudonym": device_pseudonym,
        "public_key_hex": pubkey.hex(),
        "chain_b64": base64.b64encode(buf).decode("ascii"),
        "n_records": n_records,
        "self_verified_ok": ok,
        "self_verify_first_bad_index": first_bad_index,
        "self_verify_reason": reason,
    }
