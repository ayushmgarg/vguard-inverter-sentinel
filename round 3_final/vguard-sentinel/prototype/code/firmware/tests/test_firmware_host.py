"""firmware/tests/test_firmware_host.py -- pytest for module H (firmware glue).

Builds firmware/host/sentinel_host_sim via `make host`, runs it on a short CSV replay of
a real sim_1hz battery, and checks:
  1. the sentinel_int8 golden self-test reports PASS in stdout,
  2. state.json is written and satisfies CONTRACTS.md §3/§5 (checked against the actual
     dashboard schema in dashboard/state_provider.py, not a hand-copied one),
  3. the C-produced health-log chain verifies with the Python reference implementation
     (healthlog/healthlog.py's verify_chain -- CONTRACTS §7 cross-verification pattern,
     the same one tests/test_healthlog.py uses for the other direction).

Run: `pytest -q` from the code/ root (CONTRACTS.md §0) -- this file needs no special
invocation, it is discovered like any other test under code/.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]   # .../code
FIRMWARE_DIR = ROOT / "firmware"
HOST_DIR = FIRMWARE_DIR / "host"
CSV_PATH = ROOT / "data" / "sim_1hz" / "battery_000.csv"
MANIFEST_PATH = ROOT / "data" / "sim_1hz" / "manifest.csv"

sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.skipif(
    shutil.which("gcc") is None and shutil.which("cc") is None,
    reason="no C compiler available",
)


def _have_openssl() -> bool:
    try:
        subprocess.run(["pkg-config", "--exists", "libcrypto"], check=True)
        return True
    except Exception:
        return False


requires_openssl = pytest.mark.skipif(
    not _have_openssl(), reason="firmware/host requires libcrypto (OpenSSL) -- see firmware/host/Makefile"
)


@pytest.fixture(scope="module")
def built_binary():
    subprocess.run(["make", "clean"], cwd=HOST_DIR, check=True, capture_output=True)
    result = subprocess.run(["make", "host"], cwd=HOST_DIR, capture_output=True, text=True)
    assert result.returncode == 0, "make host failed:\n%s\n%s" % (result.stdout, result.stderr)
    binary = HOST_DIR / "sentinel_host_sim"
    assert binary.exists(), "sentinel_host_sim was not produced by `make host`"
    return binary


@pytest.fixture(scope="module")
def sim_run(built_binary, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("sentinel_host_sim_run")
    state_path = out_dir / "state.json"
    hl_path = out_dir / "healthlog.bin"
    pubkey_path = out_dir / "pubkey.bin"

    assert CSV_PATH.exists(), "expected sim data at %s (per CONTRACTS §1)" % CSV_PATH
    assert MANIFEST_PATH.exists(), "expected manifest at %s" % MANIFEST_PATH

    result = subprocess.run(
        [
            str(built_binary),
            "--csv", str(CSV_PATH),
            "--manifest", str(MANIFEST_PATH),
            "--out", str(state_path),
            "--max-rows", "300000",   # ~3.5 simulated days -- enough for several
                                        # full-charge cycles and health-log records,
                                        # short enough to run in a couple of seconds
            "--dump-healthlog", str(hl_path),
            "--dump-pubkey", str(pubkey_path),
        ],
        capture_output=True, text=True,
    )
    return {
        "result": result,
        "state_path": state_path,
        "hl_path": hl_path,
        "pubkey_path": pubkey_path,
    }


@requires_openssl
def test_binary_builds(built_binary):
    assert built_binary.exists()


@requires_openssl
def test_selftest_pass_in_output(sim_run):
    result = sim_run["result"]
    assert result.returncode == 0, "sentinel_host_sim exited nonzero:\n%s\n%s" % (result.stdout, result.stderr)
    assert "sentinel_int8 golden self-test: PASS" in result.stdout
    assert "self-test: PASS" in result.stdout


@requires_openssl
def test_summary_reports_cycles_and_healthlog(sim_run):
    out = sim_run["result"].stdout
    assert "cycles detected:" in out
    assert "health-log:" in out
    assert "hl_verify_chain=OK" in out


@requires_openssl
def test_state_json_has_contract_keys(sim_run):
    from dashboard.state_provider import (
        REQUIRED_TOP_LEVEL_KEYS, REQUIRED_BATTERY_KEYS, REQUIRED_MODEL_KEYS,
        REQUIRED_OUTAGE_KEYS, REQUIRED_VOTES_KEYS, REQUIRED_AUTOPILOT_KEYS,
        REQUIRED_CHANNEL_KEYS, REQUIRED_COACH_KEYS, REQUIRED_PQ_KEYS,
        REQUIRED_HEALTHLOG_KEYS, GRADES, CONFIDENCES,
    )

    state_path = sim_run["state_path"]
    assert state_path.exists(), "sentinel_host_sim did not write state.json"
    data = json.loads(state_path.read_text())

    for key in REQUIRED_TOP_LEVEL_KEYS:
        assert key in data, "state.json missing top-level key %r" % key

    for key in REQUIRED_BATTERY_KEYS:
        assert key in data["battery"], "battery missing %r" % key
    for key in REQUIRED_MODEL_KEYS:
        assert key in data["model"], "model missing %r" % key
    assert data["model"]["grade"] in GRADES
    assert data["model"]["confidence"] in CONFIDENCES

    for key in REQUIRED_OUTAGE_KEYS:
        assert key in data["outage"]
    for key in REQUIRED_VOTES_KEYS:
        assert key in data["outage"]["votes"]

    for key in REQUIRED_AUTOPILOT_KEYS:
        assert key in data["autopilot"]
    assert len(data["autopilot"]["channels"]) == 4, "expected the 4 contactor channels"
    for ch in data["autopilot"]["channels"]:
        for key in REQUIRED_CHANNEL_KEYS:
            assert key in ch
        assert ch["state"] in ("ON", "SHED")
        assert ch["tier"] in ("T1", "T2", "T3")

    for key in REQUIRED_COACH_KEYS:
        assert key in data["coach"]
    for key in REQUIRED_PQ_KEYS:
        assert key in data["pq"]
    for key in REQUIRED_HEALTHLOG_KEYS:
        assert key in data["healthlog"]
    assert data["healthlog"]["n_records"] >= 1, "expected at least one health-log record over 300000 rows"


@requires_openssl
def test_state_json_validates_via_dashboard_provider(sim_run):
    """Round-trips state.json through the real dashboard FileProvider/schema
    validator, not a re-implementation of it."""
    from dashboard.state_provider import validate_state_schema

    data = json.loads(sim_run["state_path"].read_text())
    validated = validate_state_schema(data)
    assert validated["model"]["grade"] is not None
    assert isinstance(validated["autopilot"]["channels"], list)


@requires_openssl
def test_healthlog_chain_verifies_with_python(sim_run):
    """Cross-verification, CONTRACTS §7: a chain produced by the C engine must
    verify with the Python reference implementation, exactly like
    tests/test_healthlog.py does for the other direction (Python chain / C verifier)."""
    from healthlog.healthlog import verify_chain

    hl_path = sim_run["hl_path"]
    pubkey_path = sim_run["pubkey_path"]
    assert hl_path.exists() and hl_path.stat().st_size > 0, "no health-log bytes were dumped"
    assert pubkey_path.exists() and pubkey_path.stat().st_size == 64

    buf = hl_path.read_bytes()
    pubkey = pubkey_path.read_bytes()
    ok, n_records, first_bad_index, reason = verify_chain(buf, pubkey)
    assert ok, "healthlog.py verify_chain rejected the C-produced chain: %s (first bad index %s)" % (reason, first_bad_index)
    assert n_records >= 1


@requires_openssl
def test_healthlog_chain_rejects_tamper(sim_run):
    """Sanity check that the cross-verification above is actually exercising the
    signature/hash-chain, not vacuously passing on an empty/trivial buffer."""
    from healthlog.healthlog import verify_chain

    buf = bytearray(sim_run["hl_path"].read_bytes())
    pubkey = sim_run["pubkey_path"].read_bytes()
    assert len(buf) > 16, "chain too short to tamper meaningfully"
    buf[16] ^= 0xFF  # first byte of the first record's payload region
    ok, _, _, _ = verify_chain(bytes(buf), pubkey)
    assert not ok, "verify_chain should reject a tampered chain"
