# dashboard — module G: the demo dashboard

Implements 05-Prototype-Build-Plan.md §1 (bring-up step 9, "App/dashboard")
and the finale demo script (§4). Flask 3 backend + a single static HTML/JS/CSS
page, no build step. Conforms to the state schema in `../CONTRACTS.md` §3–§5.

**Honesty note (per CONTRACTS.md §7):** this module renders whatever a
`StateProvider` gives it. In fixture mode, every number on screen —
SoC/V/I/T, outage votes, tier states, appliance events, the SoH/RUL grade —
is **scripted**, not measured: there is no real battery, inverter, or AFE
behind it. The SoC-shed thresholds (T3 ≤40%/≥55%, T2 ≤55%/≥70%) match the
real autopilot thresholds in CONTRACTS.md §5, but the dwell timers (real:
300 s ON / 180 s OFF) are *not* reproduced — the fixture reacts to SoC
instantly, compressed for an 8-minute demo. The SoH/RUL numbers in the
replay walk are the honest "replayed synthetic aging" numbers the finale
script calls for (05 §1, "Demo mode for SoH/RUL"), never claimed as
measurements of a real aged cell. `dashboard/healthlog` verification is
simulated here (always succeeds) — the real hash-chain/ECDSA verification
lives in the (not-yet-built) `healthlog/` module.

## Run it

```bash
# from code/
python -m dashboard.app --provider fixture --port 5000
# open http://<this-machine's-LAN-IP>:5000/  (binds 0.0.0.0 by default,
# matching bring-up step 9: "a laptop web page over Wi-Fi")
```

CLI flags:
| flag | default | notes |
|---|---|---|
| `--provider` | `fixture` | `fixture` (self-contained scripted demo) or `file` (reads a JSON state file written by another process) |
| `--file PATH` | — | required when `--provider file`; the dashboard re-reads this file on every poll |
| `--port` | `5000` | |
| `--host` | `0.0.0.0` | |

## What the fixture provider does on its own

Once started, `FixtureProvider` advances a wall-clock timeline
(`dashboard/fixtures/timeline.json`) even if nobody touches the page, so a
screenshot or an idle laptop still shows a moving demo:
- **t+20 s** — simulated outage (grid drops), unless the presenter has
  already clicked a demo control.
- SoC drains while "on battery" (and slowly recharges while "on grid");
  **T3 sheds automatically once SoC crosses 40%**, restores at 55% (T2 at
  55%/70%), per CONTRACTS.md §5.
- **t+30 s / t+50 s** — two scripted appliance events ("Fan & TV" then
  "Iron / Heater" turning on) land in the Coach event feed.
- **t+90 s onward** — if the presenter never clicks "Advance SoH replay",
  the grade auto-walks COLLECTING → HEALTHY → DEGRADING → REPLACE, one
  step every 30 s.

## Finale click sequence (05-Prototype-Build-Plan.md §4, 8 minutes)

Start the server before the audience arrives so its internal clock is
already past the point where auto-advance would fight the buttons, or just
use the demo buttons — every one of them **pins** the corresponding piece
of state so the automatic timeline stops overriding it.

1. **(0:00)** Open the dashboard on the projector. Point at the physical
   battery/shunt/relays. "Nothing here needs the internet."
2. **(1:00)** Point at the SoC panel: fused SoC (big bar/gauge) vs the raw
   coulomb-counter readout next to it, and the backup-time card.
3. **(2:00)** Physically flip the bench MCB, *or* click **"Flip MCB
   (outage)"**. Point at the three outage-vote dots turning red and the
   "OUTAGE — ON BATTERY" badge (< 2 s).
4. **(3:30)** Click **"Force SoC"** slider down to ≤40% and **Apply**.
   Watch the Iron/Heater (T3) channel badge flip to SHED. Click **"Restore
   mains"** — T3 stays shed on SoC, not on grid state, which is correct:
   only SoC crossing 55% brings it back.
5. **(5:00)** Click **"Reset MCU (fail-safe)"**. T3 badge returns to ON
   immediately ("coil off = load on").
6. **(5:30)** The two scripted appliance events should already be sitting
   in "What just turned on?" (or wait ~20 s / restart near t+30–50 s if you
   want them live). Type a name into the **unlabeled cluster** row and
   click **Label** to demonstrate the Coach labeling flow.
7. **(6:30)** Click **"Advance SoH replay"** three times: grade walks
   COLLECTING → HEALTHY → DEGRADING → REPLACE. Read the "Likely needs
   replacement in 6–14 weeks (plan for 9)" line and the replay banner out
   loud — it says explicitly that this is replayed synthetic aging.
8. **(7:30)** Click **"Verify log"**; explain that a real deployment signs
   and hash-chains every event (healthlog/ module) and that flipping one
   byte in the log breaks the chain — that check itself isn't implemented
   in this dashboard yet, only surfaced/toggled here.

## Switching to the file provider (bench / real pipeline)

Any other process — the ESP32 bridge, a bench Python script, a replay
harness — can drive the same dashboard by writing the full state JSON (see
schema below) to a file and starting:

```bash
python -m dashboard.app --provider file --file /path/to/state.json --port 5000
```

`FileProvider`:
- Re-reads and re-validates the file on every `/api/state` poll (1 Hz from
  the browser). A missing or malformed file never crashes the dashboard —
  it logs a warning/error and keeps serving the last-known-good state (or a
  zeroed default before the first write).
- `POST /api/override` and `POST /api/label` don't have a live bench
  process to apply to yet, so they write a sidecar file next to the state
  file (`state.json.override.json`, `state.json.label.json`) with the
  requested action and a timestamp — a future bench bridge can watch for
  these. `POST /api/verify_log` just re-reads whatever `healthlog` block is
  already in the state file (no local crypto check).
- `POST /api/demo/*` is rejected (400) on the file provider — those buttons
  only make sense against the scripted fixture.

## State schema

See `../CONTRACTS.md` §3–§5 and the `dashboard/state_provider.py` module
docstring for the authoritative schema; `REQUIRED_*_KEYS` constants there
are what `tests/test_dashboard.py` checks against both providers.

```
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
```

## Tests

```bash
python -m pytest tests/test_dashboard.py -q
```

Covers: schema presence for both providers (including a missing/malformed
file for `FileProvider`), all five `/api/demo/*` actions, override
lock+timeout, label promoting an unknown cluster into a named appliance,
and `verify_log`.

## Front end

`dashboard/static/index.html` + `app.js` + `style.css`. No build step,
vanilla JS. Chart.js is loaded from `cdnjs.cloudflare.com` pinned at
`4.4.4` for the SoC gauge only; if it fails to load (offline demo venue),
`app.js` detects that (`window.__chartLoadFailed` set by the script tag's
`onerror`) and falls back to a plain CSS progress bar + numeric readout —
every other panel is plain DOM/CSS and has no external dependency at all.
Dark-neutral theme, large fonts, designed to be readable from the back of
a room on a projector.
