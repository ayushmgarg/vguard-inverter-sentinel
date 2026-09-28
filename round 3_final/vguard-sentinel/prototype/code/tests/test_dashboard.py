"""Tests for module G (dashboard/): schema conformance, demo endpoints, and
the override/label flows. Uses Flask's test client, no live server."""
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.app import create_app
from dashboard.state_provider import (
    FileProvider,
    FixtureProvider,
    REQUIRED_APPLIANCE_KEYS,
    REQUIRED_AUTOPILOT_KEYS,
    REQUIRED_BATTERY_KEYS,
    REQUIRED_CHANNEL_KEYS,
    REQUIRED_COACH_KEYS,
    REQUIRED_HEALTHLOG_KEYS,
    REQUIRED_MODEL_KEYS,
    REQUIRED_OUTAGE_KEYS,
    REQUIRED_PQ_KEYS,
    REQUIRED_TOP_LEVEL_KEYS,
    REQUIRED_VOTES_KEYS,
)


def assert_schema(state):
    for key in REQUIRED_TOP_LEVEL_KEYS:
        assert key in state, f"missing top-level key {key}"

    for key in REQUIRED_BATTERY_KEYS:
        assert key in state["battery"], f"missing battery.{key}"

    for key in REQUIRED_MODEL_KEYS:
        assert key in state["model"], f"missing model.{key}"

    for key in REQUIRED_OUTAGE_KEYS:
        assert key in state["outage"], f"missing outage.{key}"
    for key in REQUIRED_VOTES_KEYS:
        assert key in state["outage"]["votes"], f"missing outage.votes.{key}"

    for key in REQUIRED_AUTOPILOT_KEYS:
        assert key in state["autopilot"], f"missing autopilot.{key}"
    for ch in state["autopilot"]["channels"]:
        for key in REQUIRED_CHANNEL_KEYS:
            assert key in ch, f"missing channel key {key}"

    for key in REQUIRED_COACH_KEYS:
        assert key in state["coach"], f"missing coach.{key}"
    for a in state["coach"]["appliances"]:
        for key in REQUIRED_APPLIANCE_KEYS:
            assert key in a, f"missing appliance key {key}"

    for key in REQUIRED_PQ_KEYS:
        assert key in state["pq"], f"missing pq.{key}"

    for key in REQUIRED_HEALTHLOG_KEYS:
        assert key in state["healthlog"], f"missing healthlog.{key}"


@pytest.fixture
def fixture_client():
    provider = FixtureProvider()
    app = create_app(provider)
    app.testing = True
    return app.test_client(), provider


@pytest.fixture
def file_client(tmp_path):
    state_path = tmp_path / "state.json"
    provider = FileProvider(state_path)
    app = create_app(provider)
    app.testing = True
    return app.test_client(), provider, state_path


# ---------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------

def test_state_schema_fixture_provider(fixture_client):
    client, _ = fixture_client
    resp = client.get("/api/state")
    assert resp.status_code == 200
    assert_schema(resp.get_json())


def test_state_schema_file_provider_missing_file(file_client):
    client, _, _ = file_client
    resp = client.get("/api/state")
    assert resp.status_code == 200
    assert_schema(resp.get_json())


def test_state_schema_file_provider_with_data(file_client):
    client, provider, state_path = file_client
    good_state = FixtureProvider().get_state()
    state_path.write_text(json.dumps(good_state))
    resp = client.get("/api/state")
    assert resp.status_code == 200
    body = resp.get_json()
    assert_schema(body)
    assert body["battery"]["soc"] == good_state["battery"]["soc"]


def test_file_provider_survives_malformed_json(file_client):
    client, provider, state_path = file_client
    state_path.write_text("{not valid json")
    resp = client.get("/api/state")
    assert resp.status_code == 200
    assert_schema(resp.get_json())


def test_index_page_served(fixture_client):
    client, _ = fixture_client
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Sentinel" in resp.data


# ---------------------------------------------------------------------
# demo endpoints (fixture provider only)
# ---------------------------------------------------------------------

def test_demo_endpoints_rejected_on_file_provider(file_client):
    client, _, _ = file_client
    resp = client.post("/api/demo/outage")
    assert resp.status_code == 400


def test_demo_outage_and_restore(fixture_client):
    client, _ = fixture_client
    resp = client.post("/api/demo/outage")
    assert resp.status_code == 200
    assert resp.get_json()["outage"]["grid"] == 0

    resp = client.post("/api/demo/restore")
    assert resp.status_code == 200
    assert resp.get_json()["outage"]["grid"] == 1


def _find_channel(state, tier):
    return next(c for c in state["autopilot"]["channels"] if c["tier"] == tier)


def test_demo_force_soc_sheds_and_restores_t3(fixture_client):
    client, _ = fixture_client

    resp = client.post("/api/demo/force_soc", json={"soc": 0.35})
    assert resp.status_code == 200
    state = resp.get_json()
    t3 = _find_channel(state, "T3")
    assert t3["state"] == "SHED"

    resp = client.post("/api/demo/force_soc", json={"soc": 0.9})
    assert resp.status_code == 200
    state = resp.get_json()
    t3 = _find_channel(state, "T3")
    assert t3["state"] == "ON"


def test_demo_force_soc_rejects_out_of_range(fixture_client):
    client, _ = fixture_client
    resp = client.post("/api/demo/force_soc", json={"soc": 1.5})
    assert resp.status_code == 400


def test_demo_reset_mcu_restores_shed_channel(fixture_client):
    client, _ = fixture_client
    client.post("/api/demo/force_soc", json={"soc": 0.30})
    state = client.get("/api/state").get_json()
    assert _find_channel(state, "T3")["state"] == "SHED"

    resp = client.post("/api/demo/reset_mcu")
    assert resp.status_code == 200
    state = resp.get_json()
    t3 = _find_channel(state, "T3")
    assert t3["state"] == "ON"
    assert t3["locked"] is False


def test_demo_replay_soh_walks_grades(fixture_client):
    client, _ = fixture_client
    initial = client.get("/api/state").get_json()["model"]["grade"]
    assert initial == "COLLECTING"

    grades = []
    for _ in range(4):
        resp = client.post("/api/demo/replay_soh")
        grades.append(resp.get_json()["model"]["grade"])

    assert grades[0] == "HEALTHY"
    assert grades[1] == "DEGRADING"
    assert grades[2] == "REPLACE"
    assert grades[3] == "REPLACE"  # stays at the final step

    final_model = client.get("/api/state").get_json()["model"]
    assert final_model["replay_banner"] is not None
    assert 6 <= final_model["rul_weeks_p10"] <= 14
    assert 6 <= final_model["rul_weeks_p90"] <= 14


def test_unknown_demo_action_404(fixture_client):
    client, _ = fixture_client
    resp = client.post("/api/demo/nope")
    assert resp.status_code == 404


# ---------------------------------------------------------------------
# override
# ---------------------------------------------------------------------

def test_override_locks_channel_then_times_out(fixture_client):
    client, _ = fixture_client
    state = client.get("/api/state").get_json()
    t3_name = _find_channel(state, "T3")["name"]

    resp = client.post("/api/override", json={"channel": t3_name, "minutes": 0.002})  # ~120 ms
    assert resp.status_code == 200
    state = resp.get_json()
    ch = next(c for c in state["autopilot"]["channels"] if c["name"] == t3_name)
    assert ch["locked"] is True
    assert ch["state"] == "ON"

    time.sleep(0.3)
    state = client.get("/api/state").get_json()
    ch = next(c for c in state["autopilot"]["channels"] if c["name"] == t3_name)
    assert ch["locked"] is False


def test_override_unknown_channel_rejected(fixture_client):
    client, _ = fixture_client
    resp = client.post("/api/override", json={"channel": "not-a-real-channel", "minutes": 5})
    assert resp.status_code == 400


def test_override_bad_minutes_rejected(fixture_client):
    client, _ = fixture_client
    resp = client.post("/api/override", json={"channel": "Iron / Heater", "minutes": -5})
    assert resp.status_code == 400
    resp = client.post("/api/override", json={"channel": "Iron / Heater", "minutes": 999})
    assert resp.status_code == 400


# ---------------------------------------------------------------------
# label
# ---------------------------------------------------------------------

def test_label_updates_appliance_name(fixture_client):
    client, _ = fixture_client
    state = client.get("/api/state").get_json()
    clusters = state["coach"]["unknown_clusters"]
    assert len(clusters) >= 1
    cluster_id = clusters[0]["cluster_id"]

    resp = client.post("/api/label", json={"cluster_id": cluster_id, "name": "Water Heater"})
    assert resp.status_code == 200
    state = resp.get_json()

    names = [a["name"] for a in state["coach"]["appliances"]]
    assert "Water Heater" in names
    remaining_ids = [c["cluster_id"] for c in state["coach"]["unknown_clusters"]]
    assert cluster_id not in remaining_ids


def test_label_unknown_cluster_rejected(fixture_client):
    client, _ = fixture_client
    resp = client.post("/api/label", json={"cluster_id": "does-not-exist", "name": "Whatever"})
    assert resp.status_code == 400


def test_label_missing_fields_rejected(fixture_client):
    client, _ = fixture_client
    resp = client.post("/api/label", json={"cluster_id": "C1"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------
# verify_log
# ---------------------------------------------------------------------

def test_verify_log(fixture_client):
    client, _ = fixture_client
    resp = client.post("/api/verify_log")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["last_verify_ok"] is True

    state = client.get("/api/state").get_json()
    assert state["healthlog"]["last_verify_ok"] is True
