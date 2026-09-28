// V-Guard Sentinel demo dashboard — vanilla JS, polls /api/state every 1 s.
// Chart.js (loaded in index.html from cdnjs, pinned version) draws the SoC
// gauge if available; the CSS bar + numeric readout work with or without it.
//
// Security note: appliance/cluster names can come from the user-facing
// "label" box, so every dynamic value is inserted with textContent / DOM
// node construction below — never innerHTML with interpolated strings —
// to avoid reflecting a crafted label back as markup (XSS).

(function () {
  "use strict";

  const POLL_MS = 1000;
  let socChart = null;

  function $(id) { return document.getElementById(id); }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  // el("div", {class: "x"}, ["text", childNode, ...])
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach((k) => {
        if (k === "class") node.className = attrs[k];
        else if (k === "text") node.textContent = attrs[k];
        else node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach((c) => {
      if (c === null || c === undefined) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function setConnStatus(ok) {
    const node = $("conn-status");
    node.textContent = ok ? "live" : "disconnected";
    node.className = ok ? "ok" : "bad";
  }

  function pct(x) {
    if (x === null || x === undefined || Number.isNaN(x)) return "--";
    return (x * 100).toFixed(1);
  }

  // ---- SoC gauge -----------------------------------------------------
  function chartAvailable() {
    return typeof window.Chart !== "undefined" && !window.__chartLoadFailed;
  }

  function initChartFallback() {
    if (!chartAvailable()) {
      $("chart-fallback-note").hidden = false;
      $("soc-canvas-wrap").hidden = true;
    }
  }

  function updateSocGauge(soc) {
    if (!chartAvailable()) return;
    const value = Math.max(0, Math.min(1, soc)) * 100;
    const color = value <= 40 ? "#ef5350" : value <= 55 ? "#ffb300" : "#4caf50";
    if (!socChart) {
      const ctx = $("soc-canvas").getContext("2d");
      socChart = new Chart(ctx, {
        type: "doughnut",
        data: { datasets: [{ data: [value, 100 - value], backgroundColor: [color, "#333a44"], borderWidth: 0 }] },
        options: {
          cutout: "72%",
          plugins: { legend: { display: false }, tooltip: { enabled: false } },
          animation: { duration: 300 },
        },
      });
    } else {
      socChart.data.datasets[0].data = [value, 100 - value];
      socChart.data.datasets[0].backgroundColor = [color, "#333a44"];
      socChart.update();
    }
  }

  // ---- render sections -------------------------------------------------
  function renderBattery(battery) {
    $("soc-fused").textContent = pct(battery.soc);
    $("soc-raw").textContent = pct(battery.soc_raw_coulomb);
    $("soc-bar-fill").style.width = Math.max(0, Math.min(100, battery.soc * 100)) + "%";
    $("soc-bar-raw").style.left = Math.max(0, Math.min(100, battery.soc_raw_coulomb * 100)) + "%";
    $("batt-v").textContent = battery.v;
    $("batt-i").textContent = battery.i;
    $("batt-t").textContent = battery.t;
    $("batt-r0").textContent = battery.r0_mohm;
    $("batt-sohr").textContent = battery.soh_r;
    updateSocGauge(battery.soc);
  }

  function renderOutage(outage) {
    const badge = $("grid-badge");
    if (outage.grid) {
      badge.textContent = "GRID UP";
      badge.className = "badge grid-up";
    } else {
      badge.textContent = "OUTAGE — ON BATTERY";
      badge.className = "badge grid-down";
    }
    $("grid-since").textContent = outage.since_s;
    ["rms", "mode_pin", "discharge"].forEach((k) => {
      const node = $("vote-" + k);
      node.className = "vote-dot " + (outage.votes[k] ? "yes" : "no");
    });
  }

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then((r) => r.json());
  }

  function sendDemo(action, body) { return postJson("/api/demo/" + action, body); }
  function sendOverride(channel, minutes) { return postJson("/api/override", { channel: channel, minutes: minutes }); }

  function renderAutopilot(autopilot) {
    const list = $("channels-list");
    clear(list);
    autopilot.channels.forEach((ch) => {
      const stateBadge = el("span", { class: "badge " + (ch.state === "ON" ? "on" : "shed"), text: ch.state });
      const lockedBadge = ch.locked
        ? el("span", {
            class: "badge locked",
            text: "LOCKED" + (ch.override_remaining_s !== null && ch.override_remaining_s !== undefined
              ? " (" + Math.round(ch.override_remaining_s) + "s)" : ""),
          })
        : null;

      const overrideBtn = el("button", { class: "secondary", text: "Override ON (30 min)" });
      overrideBtn.disabled = ch.locked;
      overrideBtn.addEventListener("click", () => sendOverride(ch.name, 30).then(applyState));

      const card = el("div", { class: "channel-card" }, [
        el("div", { class: "row" }, [
          el("span", { class: "name", text: ch.name }),
          el("span", { class: "tier-tag", text: ch.tier }),
        ]),
        el("div", { class: "row" }, [stateBadge, lockedBadge]),
        overrideBtn,
      ]);
      list.appendChild(card);
    });

    const reasons = $("autopilot-reasons");
    clear(reasons);
    autopilot.reasons.forEach((r) => reasons.appendChild(el("li", { text: r })));

    $("backup-min").textContent = autopilot.est_backup_min;
  }

  function renderSoh(model) {
    const tag = $("grade-tag");
    tag.textContent = model.grade;
    tag.className = "grade-tag grade-" + model.grade;
    $("soh-band").textContent = "SoH " + model.soh_p10 + "–" + model.soh_p90 + "% (p50 " + model.soh_p50 + "%)";
    if (model.grade === "REPLACE" || model.grade === "SERVICE_NOW") {
      $("rul-text").textContent =
        "Likely needs replacement in " + model.rul_weeks_p10 + "–" + model.rul_weeks_p90 +
        " weeks (plan for " + model.rul_weeks_p50 + ")";
    } else {
      $("rul-text").textContent =
        "RUL " + model.rul_weeks_p10 + "–" + model.rul_weeks_p90 + " weeks (p50 " + model.rul_weeks_p50 + ")";
    }
    $("n-weeks").textContent = model.n_weeks;
    $("confidence").textContent = model.confidence;
    const meta = state.meta || {};
    const src = $("source-badge");
    if (src) {
      src.textContent = (meta.stale ? "DISCONNECTED (" + Math.round(meta.age_s) + " s) · " : "") + "source: " + (meta.source || "unknown")
        + (meta.override_ack ? " · override ack: " + (meta.override_ack.channel || "") + " until " + (meta.override_ack.expires_at || "?") : "");
      src.className = meta.stale ? "badge stale" : "badge";
    }
    const banner = $("replay-banner");
    if (model.replay_banner) {
      banner.textContent = model.replay_banner;
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
  }

  function renderCoach(coach) {
    const appliances = $("appliances-list");
    clear(appliances);
    coach.appliances.forEach((a) => {
      appliances.appendChild(el("div", { class: "appliance-row" }, [
        el("span", { text: a.name }),
        el("span", {}, [
          el("span", { class: "badge confidence-" + a.confidence, text: a.confidence }),
          " " + a.kwh_today + " kWh",
        ]),
      ]));
    });

    const events = $("events-list");
    clear(events);
    coach.events.forEach((e) => {
      const desc = e.t + " — " + e.name + " turned ON (ΔP " + e.dP + " W, ΔQ " + e.dQ +
        " VAR, φ " + e.phi_deg + "°)";
      events.appendChild(el("div", { class: "event-row" }, [
        el("span", { text: desc }),
        el("span", { class: "badge confidence-" + e.confidence, text: e.confidence }),
      ]));
    });

    const clusters = $("clusters-list");
    clear(clusters);
    coach.unknown_clusters.forEach((c) => {
      const label = el("span", {
        text: "Unknown load " + c.cluster_id + " (ΔP " + c.dP_w + " W, seen " + c.count +
          "x, first " + c.first_seen + ")",
      });
      const nameInput = el("input", { placeholder: "name it…" });
      nameInput.style.width = "8rem";
      const btn = el("button", { text: "Label" });
      btn.addEventListener("click", () => {
        const value = nameInput.value.trim();
        if (!value) return;
        postJson("/api/label", { cluster_id: c.cluster_id, name: value }).then(applyState);
      });
      clusters.appendChild(el("div", { class: "cluster-row" }, [label, nameInput, btn]));
    });
  }

  function renderPq(pq) {
    const list = $("pq-events-list");
    clear(list);
    pq.events.forEach((e) => {
      const mag = (e.magnitude_pct !== null && e.magnitude_pct !== undefined) ? e.magnitude_pct + "%" : "";
      const dur = e.duration_ms ? " / " + e.duration_ms + " ms" : "";
      list.appendChild(el("div", { class: "pq-row" }, [
        el("span", { text: e.t + " — " + e.type }),
        el("span", { text: mag + dur }),
      ]));
    });

    const rollup = $("rollup-grid");
    clear(rollup);
    const months = Object.keys(pq.monthly_rollup);
    const latest = months.length ? pq.monthly_rollup[months[months.length - 1]] : { sags: 0, swells: 0, interruptions: 0 };
    [["sags", "Sags"], ["swells", "Swells"], ["interruptions", "Interruptions"]].forEach(function (pair) {
      const key = pair[0], label = pair[1];
      rollup.appendChild(el("div", {}, [
        el("div", { class: "count", text: String(latest[key] || 0) }),
        el("div", { class: "label", text: label }),
      ]));
    });
  }

  function renderHealthlog(healthlog) {
    $("hl-n").textContent = healthlog.n_records;
    if (healthlog.last_verify_ok === null || healthlog.last_verify_ok === undefined) {
      $("hl-verify").textContent = "not yet run";
    } else {
      $("hl-verify").textContent = healthlog.last_verify_ok ? "OK — chain intact" : "FAILED — chain broken";
    }
  }

  function applyState(state) {
    if (!state || !state.battery) return;
    renderBattery(state.battery);
    renderOutage(state.outage);
    renderAutopilot(state.autopilot);
    renderSoh(state.model);
    renderCoach(state.coach);
    renderPq(state.pq);
    renderHealthlog(state.healthlog);
  }

  function poll() {
    fetch("/api/state")
      .then((r) => r.json())
      .then((state) => {
        setConnStatus(true);
        applyState(state);
      })
      .catch(() => setConnStatus(false));
  }

  // ---- demo control wiring ---------------------------------------------
  function wireDemoControls() {
    $("btn-outage").addEventListener("click", () => sendDemo("outage").then(applyState));
    $("btn-restore").addEventListener("click", () => sendDemo("restore").then(applyState));
    $("btn-reset-mcu").addEventListener("click", () => sendDemo("reset_mcu").then(applyState));
    $("btn-replay").addEventListener("click", () => sendDemo("replay_soh").then(applyState));

    const range = $("force-soc-range");
    range.addEventListener("input", () => { $("force-soc-value").textContent = range.value + "%"; });
    $("btn-force-soc").addEventListener("click", () => {
      sendDemo("force_soc", { soc: Number(range.value) / 100 }).then(applyState);
    });

    $("verify-btn").addEventListener("click", () => {
      fetch("/api/verify_log", { method: "POST" }).then((r) => r.json()).then(() => poll());
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initChartFallback();
    wireDemoControls();
    poll();
    setInterval(poll, POLL_MS);
  });
})();
