"""State providers for the Sentinel demo dashboard.

`StateProvider` is the pluggable interface the Flask app (`dashboard/app.py`)
polls once a second. Two concrete providers exist:

- `FixtureProvider` — an in-memory, self-advancing scripted demo used for the
  finale (Tier 0 bench). It loads its static configuration from the JSON
  files in `dashboard/fixtures/` and holds live, mutable state (SoC, outage,
  overrides, ...) that evolves both automatically (a wall-clock timeline) and
  in response to the `/api/demo/*` presenter buttons.
- `FileProvider` — reads a JSON state file written by another process (the
  real bench firmware bridge, or a replay script). This is how the dashboard
  will eventually be fed by the real pipeline; nothing about the schema
  changes between the two providers.

Schema (see CONTRACTS.md §3, §4, §5 and 02-Product-Definition §5):
    battery:    soc, soc_raw_coulomb, v, i, t, r0_mohm, soh_r
    model:      soh_p10/p50/p90, rul_weeks_p10/p50/p90, grade, n_weeks,
                confidence, replay_banner
    outage:     grid, votes {rms, mode_pin, discharge}, since_s
    autopilot:  channels [{name, tier, state, locked, override_remaining_s}],
                est_backup_min, reasons
    coach:      appliances [{name, kwh_today, confidence, last_event}],
                events, unknown_clusters
    pq:         events, monthly_rollup
    healthlog:  n_records, last_verify_ok
"""
from __future__ import annotations

import copy
import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Grades per CONTRACTS.md §3.
GRADES = ("COLLECTING", "HEALTHY", "DEGRADING", "REPLACE", "SERVICE_NOW")
CONFIDENCES = ("LOW", "MED", "HIGH")

REQUIRED_TOP_LEVEL_KEYS = (
    "battery", "model", "outage", "autopilot", "coach", "pq", "healthlog",
)
REQUIRED_BATTERY_KEYS = ("soc", "soc_raw_coulomb", "v", "i", "t", "r0_mohm", "soh_r")
REQUIRED_MODEL_KEYS = (
    "soh_p10", "soh_p50", "soh_p90",
    "rul_weeks_p10", "rul_weeks_p50", "rul_weeks_p90",
    "grade", "n_weeks", "confidence", "replay_banner",
)
REQUIRED_OUTAGE_KEYS = ("grid", "votes", "since_s")
REQUIRED_VOTES_KEYS = ("rms", "mode_pin", "discharge")
REQUIRED_AUTOPILOT_KEYS = ("channels", "est_backup_min", "reasons")
REQUIRED_CHANNEL_KEYS = ("name", "tier", "state", "locked")
REQUIRED_COACH_KEYS = ("appliances", "events", "unknown_clusters")
REQUIRED_APPLIANCE_KEYS = ("name", "kwh_today", "confidence", "last_event")
REQUIRED_PQ_KEYS = ("events", "monthly_rollup")
REQUIRED_HEALTHLOG_KEYS = ("n_records", "last_verify_ok")


def _default_state() -> Dict[str, Any]:
    """A minimal, fully schema-conformant state used before any real data
    exists (e.g. FileProvider before the upstream pipeline has written its
    first file)."""
    return {
        "battery": {
            "soc": 0.0, "soc_raw_coulomb": 0.0, "v": 0.0, "i": 0.0, "t": 0.0,
            "r0_mohm": 0.0, "soh_r": 0.0,
        },
        "model": {
            "soh_p10": 0.0, "soh_p50": 0.0, "soh_p90": 0.0,
            "rul_weeks_p10": 0, "rul_weeks_p50": 0, "rul_weeks_p90": 0,
            "grade": "COLLECTING", "n_weeks": 0, "confidence": "LOW",
            "replay_banner": None,
        },
        "outage": {
            "grid": 1,
            "votes": {"rms": False, "mode_pin": False, "discharge": False},
            "since_s": 0.0,
        },
        "autopilot": {"channels": [], "est_backup_min": 0.0, "reasons": []},
        "coach": {"appliances": [], "events": [], "unknown_clusters": []},
        "pq": {"events": [], "monthly_rollup": {}},
        "healthlog": {"n_records": 0, "last_verify_ok": None},
    }


def validate_state_schema(data: Any) -> Dict[str, Any]:
    """Defensively merge externally-supplied state (e.g. from FileProvider)
    onto the default template so a partially-written or stale file never
    crashes the dashboard. Never trust external data (coding-style rule).
    """
    template = _default_state()
    if not isinstance(data, dict):
        logger.warning("state file did not contain a JSON object; using defaults")
        return template
    merged: Dict[str, Any] = {}
    for key in REQUIRED_TOP_LEVEL_KEYS:
        section = data.get(key)
        if isinstance(section, dict) and isinstance(template[key], dict):
            merged_section = dict(template[key])
            merged_section.update(section)
            merged[key] = merged_section
        elif key in data:
            merged[key] = data[key]
        else:
            logger.warning("state file missing top-level key %r; using default", key)
            merged[key] = template[key]
    return merged


class StateProvider(ABC):
    """Pluggable state source polled by the Flask app once a second."""

    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """Return the full state dict (see module docstring for schema)."""
        raise NotImplementedError

    def override(self, channel: str, minutes: float) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not support overrides")

    def label(self, cluster_id: str, name: str) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not support labeling")

    def verify_log(self) -> Dict[str, Any]:
        raise NotImplementedError(f"{type(self).__name__} does not support verify_log")


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"required fixture file missing: {path} "
            "(FixtureProvider cannot start without dashboard/fixtures/*.json)"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"fixture file {path} is not valid JSON: {exc}") from exc


class FixtureProvider(StateProvider):
    """Self-contained, self-advancing scripted demo.

    Two things move the state forward:
    1. A wall-clock timeline (config in fixtures/timeline.json) that advances
       on every `get_state()` call so the demo moves even if nobody touches
       the presenter buttons: outage at t+20 s, T3 shed once SoC crosses
       40%, two appliance events, and (if the presenter never clicks
       "replay") an automatic SoH replay walk.
    2. The `/api/demo/*` presenter actions used to pace the finale script
       (05-Prototype-Build-Plan.md §4): outage, restore, reset_mcu,
       replay_soh, force_soc. These pin the corresponding piece of state so
       the automatic timeline stops fighting the presenter.
    """

    def __init__(self, fixtures_dir: Optional[Path] = None):
        self._dir = Path(fixtures_dir) if fixtures_dir else FIXTURES_DIR
        self._lock = threading.RLock()

        self._channels_cfg = _load_json(self._dir / "channels.json")
        self._appliances_cfg = _load_json(self._dir / "appliances.json")
        self._pq_seed = _load_json(self._dir / "pq_seed.json")
        self._replay_steps = _load_json(self._dir / "soh_replay_steps.json")
        self._timeline = _load_json(self._dir / "timeline.json")
        self._battery_cfg = _load_json(self._dir / "baseline_battery.json")

        now = time.monotonic()
        self._start_t = now

        # --- grid / outage ---
        self._grid = 1
        self._grid_since = now
        self._grid_manual = False
        self._auto_outage_fired = False

        # --- battery / SoC ---
        self._soc = float(self._timeline["soc_baseline"])
        self._last_soc_update = now

        # --- autopilot ---
        self._prev_tier_state = {ch["name"]: "ON" for ch in self._channels_cfg}
        self._overrides: Dict[str, float] = {}
        self._mcu_reset_until = 0.0

        # --- coach ---
        self._kwh = {a["name"]: float(a["kwh_today"]) for a in self._appliances_cfg}
        self._confidence = {a["name"]: a["confidence"] for a in self._appliances_cfg}
        self._last_event: Dict[str, Optional[str]] = {a["name"]: None for a in self._appliances_cfg}
        self._events: List[Dict[str, Any]] = []
        self._appliance_events_fired = [False] * len(self._timeline["appliance_event_offsets_s"])
        self._unknown_clusters: List[Dict[str, Any]] = [
            {"cluster_id": "C1", "first_seen": self._now_str(), "dP_w": 42, "count": 3, "name": None},
        ]

        # --- PQ ---
        self._pq_events: List[Dict[str, Any]] = list(self._pq_seed["events"])
        self._monthly_rollup: Dict[str, Dict[str, int]] = copy.deepcopy(self._pq_seed["monthly_rollup"])

        # --- SoH replay ---
        self._replay_step = 0
        self._replay_manual = False

        # --- health log ---
        self._healthlog_n = 12
        self._healthlog_last_verify_ok: Optional[bool] = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._start_t

            self._advance_grid(elapsed)
            self._advance_soc(now)
            self._advance_appliance_events(elapsed)
            self._advance_replay(elapsed)
            self._expire_overrides(now)

            channels = self._compute_channels(now)
            return {
                "battery": self._compute_battery(),
                "model": self._compute_model(),
                "outage": self._compute_outage(now),
                "autopilot": self._compute_autopilot(channels, now),
                "coach": self._compute_coach(),
                "pq": self._compute_pq(),
                "healthlog": {
                    "n_records": self._healthlog_n,
                    "last_verify_ok": self._healthlog_last_verify_ok,
                },
            }

    def override(self, channel: str, minutes: float) -> None:
        with self._lock:
            names = {ch["name"] for ch in self._channels_cfg}
            if channel not in names:
                raise ValueError(f"unknown channel: {channel!r}")
            self._overrides[channel] = time.monotonic() + float(minutes) * 60.0

    def label(self, cluster_id: str, name: str) -> None:
        with self._lock:
            cluster = next((c for c in self._unknown_clusters if c["cluster_id"] == cluster_id), None)
            if cluster is None:
                raise ValueError(f"unknown cluster_id: {cluster_id!r}")
            cluster["name"] = name
            self._unknown_clusters.remove(cluster)
            # Promote the newly-labelled cluster into the known-appliance list.
            self._kwh.setdefault(name, 0.0)
            self._confidence[name] = "LOW"
            self._last_event[name] = self._now_str()
            if not any(a["name"] == name for a in self._appliances_cfg):
                self._appliances_cfg.append({"name": name, "kwh_today": 0.0, "confidence": "LOW"})

    def verify_log(self) -> Dict[str, Any]:
        # The real hash-chain / ECDSA verification lives in healthlog/ (out
        # of scope for this module). The fixture simulates a successful
        # verify so the dashboard's "verify" button has something to show.
        with self._lock:
            self._healthlog_last_verify_ok = True
            return {"n_records": self._healthlog_n, "last_verify_ok": self._healthlog_last_verify_ok}

    # ------------------------------------------------------------------
    # presenter (finale) actions — fixture provider only
    # ------------------------------------------------------------------
    def demo_outage(self) -> None:
        with self._lock:
            self._grid_manual = True
            self._set_grid(0)

    def demo_restore(self) -> None:
        with self._lock:
            self._grid_manual = True
            self._set_grid(1)

    def demo_reset_mcu(self) -> None:
        with self._lock:
            self._mcu_reset_until = time.monotonic() + float(self._timeline["mcu_reset_hold_s"])
            # A real MCU reset also clears any manual override sitting on T3.
            for ch in self._channels_cfg:
                if ch["tier"] == "T3":
                    self._overrides.pop(ch["name"], None)

    def demo_replay_soh(self) -> None:
        with self._lock:
            self._replay_manual = True
            self._replay_step = min(self._replay_step + 1, len(self._replay_steps) - 1)

    def demo_force_soc(self, soc: float) -> None:
        with self._lock:
            if not (0.0 <= soc <= 1.0):
                raise ValueError("soc must be between 0 and 1")
            self._soc = soc
            self._last_soc_update = time.monotonic()

    # ------------------------------------------------------------------
    # internal: timeline advance
    # ------------------------------------------------------------------
    def _now_str(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _set_grid(self, value: int) -> None:
        if value != self._grid:
            self._grid = value
            self._grid_since = time.monotonic()
            self._healthlog_n += 1
            if value == 0:
                self._pq_events.append({
                    "t": self._now_str(), "type": "INTERRUPTION",
                    "magnitude_pct": 100, "duration_ms": None,
                })
                month = datetime.now().strftime("%Y-%m")
                bucket = self._monthly_rollup.setdefault(month, {"sags": 0, "swells": 0, "interruptions": 0})
                bucket["interruptions"] = bucket.get("interruptions", 0) + 1

    def _advance_grid(self, elapsed: float) -> None:
        if self._grid_manual or self._auto_outage_fired:
            return
        if elapsed >= self._timeline["auto_outage_at_s"]:
            self._set_grid(0)
            self._auto_outage_fired = True

    def _advance_soc(self, now: float) -> None:
        dt = max(0.0, now - self._last_soc_update)
        if dt <= 0:
            return
        if self._grid == 0:
            self._soc -= self._timeline["soc_drain_rate_per_s_outage"] * dt
        else:
            self._soc += self._timeline["soc_charge_rate_per_s_grid"] * dt
        self._soc = max(0.0, min(self._timeline["soc_max"], self._soc))
        self._last_soc_update = now

    def _advance_appliance_events(self, elapsed: float) -> None:
        offsets = self._timeline["appliance_event_offsets_s"]
        script = [
            {"name": "Fan & TV", "dP": 60, "dQ": 14, "phi_deg": 13, "confidence": "HIGH"},
            {"name": "Iron / Heater", "dP": 1000, "dQ": 40, "phi_deg": 2, "confidence": "MED"},
        ]
        for idx, offset in enumerate(offsets):
            if self._appliance_events_fired[idx]:
                continue
            if elapsed < offset:
                continue
            self._appliance_events_fired[idx] = True
            spec = script[idx] if idx < len(script) else script[-1]
            event = {
                "t": self._now_str(),
                "name": spec["name"],
                "dP": spec["dP"],
                "dQ": spec["dQ"],
                "phi_deg": spec["phi_deg"],
                "confidence": spec["confidence"],
            }
            self._events.append(event)
            self._last_event[spec["name"]] = event["t"]
            self._kwh[spec["name"]] = self._kwh.get(spec["name"], 0.0) + spec["dP"] / 1000.0 * 0.1
            self._healthlog_n += 1

    def _advance_replay(self, elapsed: float) -> None:
        if self._replay_manual:
            return
        start = self._timeline["replay_auto_start_s"]
        interval = self._timeline["replay_auto_interval_s"]
        if elapsed < start:
            return
        target_step = min(1 + int((elapsed - start) // interval), len(self._replay_steps) - 1)
        if target_step > self._replay_step:
            self._replay_step = target_step

    def _expire_overrides(self, now: float) -> None:
        expired = [name for name, expiry in self._overrides.items() if expiry <= now]
        for name in expired:
            del self._overrides[name]

    # ------------------------------------------------------------------
    # internal: state computation
    # ------------------------------------------------------------------
    def _compute_channels(self, now: float) -> List[Dict[str, Any]]:
        t3_shed, t3_restore = self._timeline["t3_shed_soc"], self._timeline["t3_restore_soc"]
        t2_shed, t2_restore = self._timeline["t2_shed_soc"], self._timeline["t2_restore_soc"]
        in_reset_hold = now < self._mcu_reset_until

        channels = []
        for ch in self._channels_cfg:
            name, tier = ch["name"], ch["tier"]
            prev = self._prev_tier_state[name]

            if tier == "T1":
                desired = "ON"
            elif tier == "T2":
                if self._soc <= t2_shed:
                    desired = "SHED"
                elif self._soc >= t2_restore:
                    desired = "ON"
                else:
                    desired = prev
            elif tier == "T3":
                if in_reset_hold:
                    desired = "ON"
                elif self._soc <= t3_shed:
                    desired = "SHED"
                elif self._soc >= t3_restore:
                    desired = "ON"
                else:
                    desired = prev
            else:
                desired = prev

            locked = False
            override_remaining = None
            expiry = self._overrides.get(name)
            if expiry is not None and expiry > now:
                desired = "ON"
                locked = True
                override_remaining = round(expiry - now, 1)

            self._prev_tier_state[name] = desired
            channels.append({
                "name": name,
                "tier": tier,
                "state": desired,
                "locked": locked,
                "override_remaining_s": override_remaining,
            })
        return channels

    def _compute_battery(self) -> Dict[str, Any]:
        cfg = self._battery_cfg
        if self._grid:
            v = cfg["v_grid_up"]
            i = cfg["i_charge"]
        else:
            load_w = sum(ch["watts"] for ch in self._channels_cfg if self._prev_tier_state[ch["name"]] == "ON")
            v = cfg["v_grid_down"]
            i = -round(load_w / v, 2)
        soc_raw = max(0.0, min(1.0, self._soc + cfg["raw_offset"]))
        return {
            "soc": round(self._soc, 4),
            "soc_raw_coulomb": round(soc_raw, 4),
            "v": round(v, 2),
            "i": round(i, 2),
            "t": cfg["t_celsius"],
            "r0_mohm": cfg["r0_mohm"],
            "soh_r": cfg["soh_r"],
        }

    def _compute_model(self) -> Dict[str, Any]:
        return dict(self._replay_steps[self._replay_step])

    def _compute_outage(self, now: float) -> Dict[str, Any]:
        vote = bool(self._grid == 0)
        return {
            "grid": self._grid,
            "votes": {"rms": vote, "mode_pin": vote, "discharge": vote},
            "since_s": round(now - self._grid_since, 1),
        }

    def _compute_autopilot(self, channels: List[Dict[str, Any]], now: float) -> Dict[str, Any]:
        load_w = sum(ch["watts"] for ch, c in zip(self._channels_cfg, channels) if c["state"] == "ON")
        load_w = max(load_w, self._timeline["idle_load_w"])
        capacity_wh = self._soc * self._timeline["battery_usable_wh"]
        est_backup_min = round(min(999.0, capacity_wh / load_w * 60.0), 1)

        reasons: List[str] = []
        soc_pct = round(self._soc * 100, 1)
        in_reset_hold = now < self._mcu_reset_until
        for c in channels:
            if c["locked"]:
                reasons.append(f"Override active on {c['name']}: {c['override_remaining_s']}s remaining")
            elif c["tier"] == "T3" and in_reset_hold and c["state"] == "ON":
                reasons.append(f"{c['name']}: fail-safe restore (MCU reset, coil de-energised)")
            elif c["tier"] == "T3" and c["state"] == "SHED":
                reasons.append(f"{c['name']} shed: SoC {soc_pct}% <= {self._timeline['t3_shed_soc']*100:.0f}% threshold")
            elif c["tier"] == "T2" and c["state"] == "SHED":
                reasons.append(f"{c['name']} shed: SoC {soc_pct}% <= {self._timeline['t2_shed_soc']*100:.0f}% threshold")
        if not reasons:
            reasons.append(f"All channels nominal at SoC {soc_pct}%")

        return {"channels": channels, "est_backup_min": est_backup_min, "reasons": reasons}

    def _compute_coach(self) -> Dict[str, Any]:
        appliances = [
            {
                "name": a["name"],
                "kwh_today": round(self._kwh.get(a["name"], 0.0), 3),
                "confidence": self._confidence.get(a["name"], a["confidence"]),
                "last_event": self._last_event.get(a["name"]),
            }
            for a in self._appliances_cfg
        ]
        return {
            "appliances": appliances,
            "events": list(reversed(self._events)),
            "unknown_clusters": copy.deepcopy(self._unknown_clusters),
        }

    def _compute_pq(self) -> Dict[str, Any]:
        return {
            "events": list(self._pq_events),
            "monthly_rollup": copy.deepcopy(self._monthly_rollup),
        }


class FileProvider(StateProvider):
    """Reads a JSON state file written by another process (bench bridge or
    replay script). Stateless from this module's point of view — it simply
    re-reads and validates the file on every poll, keeping the last known
    good state around if the file is missing, mid-write, or malformed."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._last_good = _default_state()

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            try:
                raw = self._path.read_text(encoding="utf-8")
            except FileNotFoundError:
                logger.warning("FileProvider: %s not found; serving last-known state", self._path)
                return self._last_good
            except OSError as exc:
                logger.error("FileProvider: failed to read %s: %s", self._path, exc)
                return self._last_good

            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.error("FileProvider: %s is not valid JSON (%s); serving last-known state", self._path, exc)
                return self._last_good

            state = validate_state_schema(data)
            # provenance: tell the UI where this came from and how old it is
            try:
                age_s = max(0.0, time.time() - self._path.stat().st_mtime)
            except OSError:
                age_s = float("inf")
            meta = dict(state.get("meta", {}))
            meta.setdefault("source", "file")          # producer may set 'bench' / 'host-sim' / 'replay'
            meta["age_s"] = age_s
            meta["stale"] = age_s > 10.0               # 1 Hz producer expected; >10 s = disconnected
            meta["override_ack"] = self._read_ack()
            state["meta"] = meta
            self._last_good = state
            return self._last_good

    def _read_ack(self):
        """Device acknowledgement of the last override request, written by the
        producer next to the state file as <state>.override.ack.json."""
        ack = self._path.with_name(self._path.name + ".override.ack.json")
        try:
            return json.loads(ack.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def override(self, channel: str, minutes: float) -> None:
        self._write_sidecar("override", {"channel": channel, "minutes": minutes})

    def label(self, cluster_id: str, name: str) -> None:
        self._write_sidecar("label", {"cluster_id": cluster_id, "name": name})

    def verify_log(self) -> Dict[str, Any]:
        # No local crypto verification is implemented here (that lives in
        # healthlog/, out of scope for the dashboard) — surface whatever the
        # upstream pipeline already computed.
        return self.get_state().get("healthlog", {"n_records": 0, "last_verify_ok": None})

    def _write_sidecar(self, kind: str, payload: Dict[str, Any]) -> None:
        sidecar = self._path.with_name(self._path.name + f".{kind}.json")
        payload = dict(payload)
        payload["requested_at"] = time.time()
        try:
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:
            logger.error("FileProvider: failed to write %s request to %s: %s", kind, sidecar, exc)
            raise
