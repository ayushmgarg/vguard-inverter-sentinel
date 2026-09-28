"""tests/test_healthlog.py — pytest for the signed hash-chained health log (module F).

Covers CONTRACTS.md §6 / design doc 09 §4's threat model: tamper, deletion, reorder,
replay/re-insertion, truncation — plus resume-from-file and cross-verification against the
C implementation (healthlog/healthlog.c) via its host test binary.

Run: `pytest -q` from the code/ root (CONTRACTS.md §0).
"""

import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import healthlog as hl  # noqa: E402  (path insert must happen first)


# ----------------------------------------------------------------------------------------
# Fixtures / helpers
# ----------------------------------------------------------------------------------------


def build_chain(n_records=4):
    priv = hl.generate_keypair()
    pub = hl.export_public_key_raw(priv)
    writer = hl.HealthLogWriter(hl.make_sign_fn(priv))
    types = [
        hl.EventType.FW_VERSION,
        hl.EventType.CAPACITY_SAMPLE,
        hl.EventType.GRADE_CHANGE,
        hl.EventType.OVER_TEMP,
        hl.EventType.DEEP_DISCHARGE,
        hl.EventType.ANOMALY,
    ]
    payloads = [b"1.0.0", b"\x50\x00\x00\x00", b"\x02", b"", b"\x01\x02", b"x"]
    records = []
    for i in range(n_records):
        rec = writer.append(types[i % len(types)], payloads[i % len(payloads)], ts_ms=1_000_000 + i)
        records.append(rec)
    return writer.buffer, pub, priv, records


def flip_byte(buf: bytes, offset: int) -> bytes:
    b = bytearray(buf)
    b[offset] ^= 0xFF
    return bytes(b)


# ----------------------------------------------------------------------------------------
# Core validity / format
# ----------------------------------------------------------------------------------------


def test_record_size_matches_format():
    buf, pub, priv, records = build_chain(1)
    rec = records[0]
    assert len(buf) == 112 + len(rec.payload)
    assert rec.prev_hash == hl.GENESIS_PREV_HASH


def test_valid_chain_verifies():
    buf, pub, priv, records = build_chain(6)
    ok, n, bad, reason = hl.verify_chain(buf, pub)
    assert ok is True
    assert n == 6
    assert bad is None
    assert reason == "ok"


def test_pubkey_mismatch_fails():
    buf, pub, priv, records = build_chain(3)
    other_priv = hl.generate_keypair()
    other_pub = hl.export_public_key_raw(other_priv)
    ok, n, bad, reason = hl.verify_chain(buf, other_pub)
    assert ok is False
    assert bad == 0  # every signature fails to verify under the wrong key, starting at record 0


# ----------------------------------------------------------------------------------------
# Tamper detection — flipping one byte in any field fails at the right index
# ----------------------------------------------------------------------------------------


def _record_offsets(records):
    """Byte offset (within the concatenated buffer) each record starts at."""
    offsets = []
    o = 0
    for rec in records:
        offsets.append(o)
        o += len(rec.to_bytes())
    return offsets


@pytest.mark.parametrize(
    "target_index,field",
    [
        (1, "counter"),
        (1, "ts_ms"),
        (1, "type"),
        (1, "len"),
        (1, "payload"),
        (1, "prev_hash"),
        (1, "sig"),
        (0, "prev_hash"),  # genesis prev_hash tamper — must be caught at index 0
        (2, "sig"),
    ],
)
def test_tamper_single_byte_detected_at_right_index(target_index, field):
    buf, pub, priv, records = build_chain(4)
    offsets = _record_offsets(records)
    rec = records[target_index]
    base = offsets[target_index]

    field_offset = {
        "counter": 0,
        "ts_ms": 4,
        "type": 12,
        "len": 14,
    }
    if field in field_offset:
        byte_off = base + field_offset[field]
    elif field == "payload":
        assert len(rec.payload) > 0, "test misconfigured: record has empty payload"
        byte_off = base + 16
    elif field == "prev_hash":
        byte_off = base + 16 + len(rec.payload)
    elif field == "sig":
        byte_off = base + 16 + len(rec.payload) + 32
    else:
        raise AssertionError(field)

    tampered = flip_byte(buf, byte_off)
    ok, n, bad, reason = hl.verify_chain(tampered, pub)
    assert ok is False
    assert bad == target_index, "field=%s reason=%s" % (field, reason)
    assert n == target_index  # every record strictly before the bad one still verified


# ----------------------------------------------------------------------------------------
# Deletion (counter gap)
# ----------------------------------------------------------------------------------------


def test_delete_middle_record_fails_with_gap():
    buf, pub, priv, records = build_chain(5)
    offsets = _record_offsets(records)
    # Delete record index 2 (drop its bytes entirely).
    start = offsets[2]
    end = offsets[3]
    deleted = buf[:start] + buf[end:]

    ok, n, bad, reason = hl.verify_chain(deleted, pub)
    assert ok is False
    assert n == 2  # records 0 and 1 still verify fine
    assert bad == 2
    assert "gap" in reason or "reorder" in reason


def test_delete_last_record_only_detectable_with_known_counter():
    buf, pub, priv, records = build_chain(4)
    offsets = _record_offsets(records)
    truncated_clean = buf[: offsets[3]]  # exactly 3 whole records, cleanly cut

    # Without external knowledge, a clean prefix is itself a valid (shorter) chain.
    ok, n, bad, reason = hl.verify_chain(truncated_clean, pub)
    assert ok is True
    assert n == 3

    # With the previously-known last counter (3, since 4 records -> counters 0..3), the
    # same bytes are correctly flagged as truncated.
    ok2, n2, bad2, reason2 = hl.verify_chain(truncated_clean, pub, expected_last_counter=3)
    assert ok2 is False
    assert "truncat" in reason2


# ----------------------------------------------------------------------------------------
# Reorder
# ----------------------------------------------------------------------------------------


def test_reorder_two_records_fails():
    buf, pub, priv, records = build_chain(5)
    offsets = _record_offsets(records) + [len(buf)]
    parts = [buf[offsets[i] : offsets[i + 1]] for i in range(5)]
    # Swap records 1 and 2.
    parts[1], parts[2] = parts[2], parts[1]
    reordered = b"".join(parts)

    ok, n, bad, reason = hl.verify_chain(reordered, pub)
    assert ok is False
    assert bad == 1  # record now at position 1 has counter == 2, breaking continuity


# ----------------------------------------------------------------------------------------
# Replay / re-insertion
# ----------------------------------------------------------------------------------------


def test_reinsert_old_record_fails():
    buf, pub, priv, records = build_chain(5)
    offsets = _record_offsets(records) + [len(buf)]
    record1_bytes = buf[offsets[1] : offsets[2]]
    # Splice a duplicate copy of record 1 back in right after record 3.
    insert_at = offsets[4]
    replayed = buf[:insert_at] + record1_bytes + buf[insert_at:]

    ok, n, bad, reason = hl.verify_chain(replayed, pub)
    assert ok is False
    assert bad == 4  # first four original records still fine; the re-inserted copy breaks it
    assert n == 4


# ----------------------------------------------------------------------------------------
# Resume from file
# ----------------------------------------------------------------------------------------


def test_resume_from_file_continues_chain(tmp_path):
    path = tmp_path / "log.bin"
    priv = hl.generate_keypair()
    pub = hl.export_public_key_raw(priv)

    w1 = hl.HealthLogWriter(hl.make_sign_fn(priv), pubkey=pub, path=str(path))
    w1.append(hl.EventType.FW_VERSION, b"1.0.0")
    w1.append(hl.EventType.CAPACITY_SAMPLE, b"\x50\x00\x00\x00")
    assert w1.counter == 2

    # Simulate a process restart: new writer instance, same file, same key.
    w2 = hl.HealthLogWriter(hl.make_sign_fn(priv), pubkey=pub, path=str(path))
    assert w2.counter == 2  # resumed correctly
    w2.append(hl.EventType.GRADE_CHANGE, b"\x02")
    assert w2.counter == 3

    on_disk = path.read_bytes()
    ok, n, bad, reason = hl.verify_chain(on_disk, pub)
    assert ok is True
    assert n == 3

    # And the in-memory buffer of the resumed writer matches the file exactly.
    assert w2.buffer == on_disk


def test_resume_refuses_corrupted_file(tmp_path):
    path = tmp_path / "log.bin"
    priv = hl.generate_keypair()
    pub = hl.export_public_key_raw(priv)
    w1 = hl.HealthLogWriter(hl.make_sign_fn(priv), pubkey=pub, path=str(path))
    w1.append(hl.EventType.FW_VERSION, b"1.0.0")
    w1.append(hl.EventType.CAPACITY_SAMPLE, b"\x50\x00\x00\x00")

    # Corrupt the file on disk (flip a byte in the first record's payload).
    data = bytearray(path.read_bytes())
    data[20] ^= 0xFF
    path.write_bytes(data)

    with pytest.raises(hl.HealthLogError):
        hl.HealthLogWriter(hl.make_sign_fn(priv), pubkey=pub, path=str(path))


# ----------------------------------------------------------------------------------------
# claim_bundle
# ----------------------------------------------------------------------------------------


def test_claim_bundle_self_verifies():
    buf, pub, priv, records = build_chain(3)
    bundle = hl.claim_bundle(buf, pub, device_pseudonym="deadbeef" * 4)
    assert bundle["self_verified_ok"] is True
    assert bundle["n_records"] == 3
    assert bundle["device_pseudonym"] == "deadbeef" * 4


def test_derive_pseudonym_deterministic_and_rotates():
    secret = b"device-secret-32-bytes-of-noise"
    p1 = hl.derive_pseudonym(secret, b"salt-epoch-1", b"epoch1")
    p2 = hl.derive_pseudonym(secret, b"salt-epoch-1", b"epoch1")
    p3 = hl.derive_pseudonym(secret, b"salt-epoch-2", b"epoch1")
    assert p1 == p2
    assert p1 != p3
    assert len(p1) == 32  # 128 bits, hex-encoded


# ----------------------------------------------------------------------------------------
# Cross-verification with the C implementation
# ----------------------------------------------------------------------------------------

HEALTHLOG_DIR = ROOT / "healthlog"
GCC_AVAILABLE = shutil.which("gcc") is not None


@pytest.fixture(scope="module")
def c_build():
    if not GCC_AVAILABLE:
        pytest.skip("gcc not available")
    result = subprocess.run(
        ["make", "-C", str(HEALTHLOG_DIR), "clean"],
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["make", "-C", str(HEALTHLOG_DIR)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail("C build failed:\n%s\n%s" % (result.stdout, result.stderr))
    binary = HEALTHLOG_DIR / "test_healthlog_host"
    assert binary.exists()
    return binary


def test_c_self_test_passes(c_build):
    result = subprocess.run([str(c_build)], capture_output=True, text=True, cwd=str(HEALTHLOG_DIR))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAILED" not in result.stderr


def test_c_produced_chain_verifies_in_python(c_build):
    # test_healthlog_host's self-test run (above) writes these as a side effect (relative to
    # HEALTHLOG_DIR); re-run here to be self-contained/order-independent.
    subprocess.run([str(c_build)], capture_output=True, text=True, cwd=str(HEALTHLOG_DIR), check=True)
    chain_path = HEALTHLOG_DIR / "chain_from_c.bin"
    pubkey_path = HEALTHLOG_DIR / "pubkey_from_c.bin"
    assert chain_path.exists() and pubkey_path.exists()

    chain = chain_path.read_bytes()
    pubkey = pubkey_path.read_bytes()
    assert len(pubkey) == 64

    ok, n, bad, reason = hl.verify_chain(chain, pubkey)
    assert ok is True, "reason=%s bad_index=%s" % (reason, bad)
    assert n == 4  # the base chain written by test_healthlog_host's self-test (see healthlog.c CHECK list)


def test_python_produced_chain_verifies_in_c(c_build, tmp_path):
    buf, pub, priv, records = build_chain(4)
    chain_path = tmp_path / "chain_from_py.bin"
    pubkey_path = tmp_path / "pubkey_from_py.bin"
    chain_path.write_bytes(buf)
    pubkey_path.write_bytes(pub)

    result = subprocess.run(
        [str(c_build), "--verify", str(chain_path), str(pubkey_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout



# ----------------------------------------------------------------------------------------
# Checkpoints (format.md §8) — signed truncation-detection attestations
# ----------------------------------------------------------------------------------------


def test_checkpoint_round_trip():
    priv = hl.generate_keypair()
    pub = hl.export_public_key_raw(priv)
    w = hl.HealthLogWriter(hl.make_sign_fn(priv))
    for i in range(5):
        w.append(hl.EventType.CAPACITY_SAMPLE, b"\x50\x00\x00\x00", ts_ms=1_000_000 + i)

    ckpt = w.checkpoint(ts_ms=42)
    assert ckpt.last_counter == 4
    assert ckpt.ts_ms == 42
    assert ckpt.head_hash == w._last_hash  # internal, but pins the intended semantics

    ser = ckpt.serialize()
    assert len(ser) == hl.CHECKPOINT_SIZE == 108

    parsed = hl.Checkpoint.parse(ser)
    assert parsed == ckpt
    assert parsed.verify_signature(pub) is True

    ok, n, bad, reason = hl.verify_chain(w.buffer, pub, checkpoint=ckpt)
    assert ok is True
    assert n == 5
    assert reason == "ok"


def test_checkpoint_on_empty_log_raises():
    priv = hl.generate_keypair()
    w = hl.HealthLogWriter(hl.make_sign_fn(priv))
    with pytest.raises(hl.HealthLogError):
        w.checkpoint()


def test_checkpoint_tampered_signature_fails():
    priv = hl.generate_keypair()
    pub = hl.export_public_key_raw(priv)
    w = hl.HealthLogWriter(hl.make_sign_fn(priv))
    for i in range(4):
        w.append(hl.EventType.CAPACITY_SAMPLE, b"\x50\x00\x00\x00", ts_ms=1_000_000 + i)
    ckpt = w.checkpoint(ts_ms=42)

    bad_sig = flip_byte(ckpt.sig, 0)
    tampered_ckpt = hl.Checkpoint(ckpt.last_counter, ckpt.ts_ms, ckpt.head_hash, bad_sig)

    assert tampered_ckpt.verify_signature(pub) is False
    ok, n, bad, reason = hl.verify_chain(w.buffer, pub, checkpoint=tampered_ckpt)
    assert ok is False
    assert "signature" in reason


def test_checkpoint_truncated_chain_fails_with_truncated_reason():
    priv = hl.generate_keypair()
    pub = hl.export_public_key_raw(priv)
    w = hl.HealthLogWriter(hl.make_sign_fn(priv))
    records = []
    for i in range(5):
        records.append(w.append(hl.EventType.CAPACITY_SAMPLE, b"\x50\x00\x00\x00", ts_ms=1_000_000 + i))
    ckpt = w.checkpoint(ts_ms=42)  # last_counter == 4

    offsets = _record_offsets(records)
    truncated = w.buffer[: offsets[3]]  # only records 0..2 present (chain ends at counter 2)

    ok, n, bad, reason = hl.verify_chain(truncated, pub, checkpoint=ckpt)
    assert ok is False
    assert "TRUNCATED" in reason
    # Without the checkpoint, this same truncated prefix is itself a perfectly valid
    # (shorter) chain — the checkpoint is what turns "shorter" into "detectably truncated".
    ok_no_ckpt, _, _, _ = hl.verify_chain(truncated, pub)
    assert ok_no_ckpt is True


def test_checkpoint_longer_chain_passes():
    priv = hl.generate_keypair()
    pub = hl.export_public_key_raw(priv)
    w = hl.HealthLogWriter(hl.make_sign_fn(priv))
    for i in range(4):
        w.append(hl.EventType.CAPACITY_SAMPLE, b"\x50\x00\x00\x00", ts_ms=1_000_000 + i)
    ckpt = w.checkpoint(ts_ms=42)  # last_counter == 3

    # More records appended after the checkpoint was taken — still a valid, longer chain.
    w.append(hl.EventType.ANOMALY, b"", ts_ms=2_000_000)
    w.append(hl.EventType.OVER_TEMP, b"\x01", ts_ms=2_000_001)

    ok, n, bad, reason = hl.verify_chain(w.buffer, pub, checkpoint=ckpt)
    assert ok is True
    assert n == 6
    assert reason == "ok"


def test_checkpoint_head_hash_mismatch_fails():
    priv = hl.generate_keypair()
    pub = hl.export_public_key_raw(priv)
    w = hl.HealthLogWriter(hl.make_sign_fn(priv))
    for i in range(4):
        w.append(hl.EventType.CAPACITY_SAMPLE, b"\x50\x00\x00\x00", ts_ms=1_000_000 + i)
    ckpt = w.checkpoint(ts_ms=42)

    # Build a checkpoint that claims the *right* last_counter/ts_ms but a wrong head_hash,
    # re-signed so the signature itself is valid — isolates the head_hash check from the
    # signature check.
    wrong_head_hash = flip_byte(ckpt.head_hash, 0)
    header = struct.pack("<IQ", ckpt.last_counter, ckpt.ts_ms)  # last_counter u32, ts_ms u64
    import hashlib

    digest = hashlib.sha256(header + wrong_head_hash).digest()
    sig = hl.make_sign_fn(priv)(digest)
    wrong_ckpt = hl.Checkpoint(ckpt.last_counter, ckpt.ts_ms, wrong_head_hash, sig)

    assert wrong_ckpt.verify_signature(pub) is True  # signature itself is fine
    ok, n, bad, reason = hl.verify_chain(w.buffer, pub, checkpoint=wrong_ckpt)
    assert ok is False
    assert "head_hash" in reason
    assert bad == ckpt.last_counter


# ----------------------------------------------------------------------------------------
# Checkpoint cross-verification with the C implementation
# ----------------------------------------------------------------------------------------


def test_c_emitted_checkpoint_verifies_in_python(c_build):
    subprocess.run([str(c_build)], capture_output=True, text=True, cwd=str(HEALTHLOG_DIR), check=True)
    chain_path = HEALTHLOG_DIR / "chain_from_c.bin"
    pubkey_path = HEALTHLOG_DIR / "pubkey_from_c.bin"
    checkpoint_path = HEALTHLOG_DIR / "checkpoint_from_c.bin"
    assert chain_path.exists() and pubkey_path.exists() and checkpoint_path.exists()

    chain = chain_path.read_bytes()
    pubkey = pubkey_path.read_bytes()
    ckpt_bytes = checkpoint_path.read_bytes()
    assert len(ckpt_bytes) == hl.CHECKPOINT_SIZE == 108

    ckpt = hl.Checkpoint.parse(ckpt_bytes)
    assert ckpt.verify_signature(pubkey) is True

    ok, n, bad, reason = hl.verify_chain(chain, pubkey, checkpoint=ckpt)
    assert ok is True, "reason=%s bad_index=%s" % (reason, bad)
    assert n == 4
    assert ckpt.last_counter == 3


def test_python_tampered_chain_rejected_in_c(c_build, tmp_path):
    buf, pub, priv, records = build_chain(4)
    offsets = _record_offsets(records)
    tampered = flip_byte(buf, offsets[1] + 20)
    chain_path = tmp_path / "chain_from_py.bin"
    pubkey_path = tmp_path / "pubkey_from_py.bin"
    chain_path.write_bytes(tampered)
    pubkey_path.write_bytes(pub)

    result = subprocess.run(
        [str(c_build), "--verify", str(chain_path), str(pubkey_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "FAIL" in result.stdout
