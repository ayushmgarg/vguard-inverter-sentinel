"""Generates every chart/flowchart for the Sentinel deck in the V-Guard Big Idea Tech palette."""
import sys, json, os
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
sys.path.insert(0, os.path.abspath("../prototype/code"))
OUT = "assets"
GOLD, ORANGE, AMBER, BLACK, INK, GREY, LIGHT, WHITE = "#FDC300", "#F39200", "#FCB817", "#000104", "#221E1F", "#6c757d", "#F3EFEF", "#FFFFFF"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12, "axes.edgecolor": INK, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK})

def box(ax, x, y, w, h, text, fc=WHITE, ec=INK, fs=11, bold=False, tc=INK, ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=fc, ec=ec, lw=1.8, ls=ls))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=tc, fontweight="bold" if bold else "normal")

def arrow(ax, p, q, color=INK, lw=2, ls="-"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=16, color=color, lw=lw, ls=ls))

def save(fig, name):
    fig.savefig(f"{OUT}/{name}.png", dpi=180, bbox_inches="tight", facecolor=WHITE); plt.close(fig)

# ---------- 1. Smart -> Intelligent positioning ----------
fig, ax = plt.subplots(figsize=(12, 4.2)); ax.set_xlim(0, 12); ax.set_ylim(0, 4.2); ax.axis("off")
steps = [("CONNECTED", "app control,\nremote on/off", LIGHT), ("SMART", "schedules, alerts,\nusage stats", AMBER), ("INTELLIGENT", "predicts failure, learns the home,\nacts on its own — offline", GOLD)]
for i, (t, sub, c) in enumerate(steps):
    box(ax, 0.4 + i * 4.0, 1.2, 3.4, 2.0, f"{t}\n\n{sub}", fc=c, ec=INK, fs=12, bold=True)
    if i < 2: arrow(ax, (3.85 + i * 4.0, 2.2), (4.35 + i * 4.0, 2.2), lw=3)
ax.text(6, 3.8, "Where V-Guard's products are today  →  where Sentinel takes them", ha="center", fontsize=13, color=INK, fontweight="bold")
ax.text(10.1, 0.7, "Sentinel", ha="center", fontsize=13, color=ORANGE, fontweight="bold")
save(fig, "positioning")

# ---------- 2. System placement / boundary ----------
fig, ax = plt.subplots(figsize=(13, 6.4)); ax.set_xlim(0, 13); ax.set_ylim(0, 6.4); ax.axis("off")
box(ax, 0.3, 4.6, 2.6, 1.3, "Mains / DB\n(230 V)", fc=LIGHT)
box(ax, 3.3, 4.6, 3.6, 1.3, "INVERTER\nAC-IN · changeover · bridge\ncharger · AC-OUT", fc=LIGHT, bold=True, fs=10)
box(ax, 7.6, 4.6, 2.4, 1.3, "Inverter-group loads\nvia NC contactors", fc=LIGHT)
box(ax, 3.3, 0.4, 3.6, 1.2, "12 V TUBULAR BATTERY\n100–230 Ah · no electronics", fc=LIGHT, bold=True, fs=10)
box(ax, 7.1, 1.8, 5.7, 2.2, "SENTINEL CORE  (box beside the inverter)\nESP32-S3 · INA228 · NTC · AMC1311 · ATM90E32AS\nULN2003 + supervisory timer · DS3231 · ATECC608\nEKF · TinyML int8 CNN · NILM · PQ · autopilot", fc=GOLD, ec=INK, fs=9.5, bold=True)
box(ax, 0.3, 1.9, 2.6, 1.0, "X1 shunt\nin battery − lead", fc=AMBER, fs=10)
box(ax, 0.3, 0.5, 2.6, 0.9, "X2 NTC on battery", fc=AMBER, fs=10)
arrow(ax, (2.9, 5.25), (3.3, 5.25)); arrow(ax, (6.9, 5.25), (7.6, 5.25))
arrow(ax, (5.1, 1.6), (5.1, 4.6), color=ORANGE, lw=3); ax.text(5.25, 3.0, "battery cables", color=ORANGE, fontsize=10, rotation=90, va="center")
arrow(ax, (2.9, 2.4), (7.3, 2.6), ls="--"); arrow(ax, (2.9, 0.95), (7.3, 2.3), ls="--")
arrow(ax, (6.9, 4.8), (8.3, 4.0), ls="--"); ax.text(6.95, 4.12, "CT + V tap on AC-OUT", fontsize=9, color=INK)
arrow(ax, (9.5, 4.0), (9.0, 4.6), color=ORANGE, lw=2.5); ax.text(9.6, 4.2, "4 × coil drive\n(coil off = loads on)", fontsize=9.5, color=ORANGE)
box(ax, 10.5, 4.7, 2.2, 1.1, "Phone app / cloud\n(optional)", fc=WHITE, ls="--", fs=10)
arrow(ax, (11.6, 4.0), (11.6, 4.7), ls="--")
ax.text(6.5, 6.15, "Everything inside the gold box runs with zero internet; the inverter and battery are not modified on the retrofit SKU", ha="center", fontsize=11, color=INK, style="italic")
save(fig, "placement")

# ---------- 3. Engine 1 signal flow ----------
fig, ax = plt.subplots(figsize=(13, 3.6)); ax.set_xlim(0, 13); ax.set_ylim(0, 3.6); ax.axis("off")
chain = [("1 Hz sensing\nI · V · T", LIGHT), ("3-state EKF\nSoC · V1 · R0\n+ taper / rest anchors", AMBER), ("14 + 6 features\nper outage cycle", AMBER), ("int8 1-D CNN ×3\n28 k params · 16 KB arena\nP10/P50/P90", GOLD), ("Conformal band\n+ grade machine", GOLD), ("\"Replace within\n6–14 weeks\"", ORANGE)]
for i, (t, c) in enumerate(chain):
    box(ax, 0.2 + i * 2.15, 0.9, 1.95, 1.9, t, fc=c, fs=10, bold=(i >= 3))
    if i < 5: arrow(ax, (2.15 + i * 2.15, 1.85), (2.35 + i * 2.15, 1.85), lw=2.5)
ax.text(6.5, 0.35, "Anomaly autoencoder + hard rules run beside the chain and raise \"Service now\" for sudden faults", ha="center", fontsize=10.5, color=GREY, style="italic")
save(fig, "engine1_flow")

# ---------- 4. SoH prediction band on an independent test battery ----------
try:
    import torch
    from model.evaluate import load_ensemble, ensemble_forward, raw_to_real
    from model.windowing import load_and_validate, build_windows, apply_standardizer
    art = "../prototype/code/model/artifacts_sim/"
    models, stats, split = load_ensemble(art)
    df = load_and_validate("../prototype/code/data/features_sim_all.csv")
    w = build_windows(df)
    off = json.load(open(art + "metrics.json"))["conformal_offsets"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), sharey=True)
    for k, bid in enumerate(split["test_batteries"][:3]):
        ax = axes[k]
        idx = np.where(w.battery_id == bid)[0]; idx = idx[np.argsort(w.cycle_idx[idx])]
        ws = w.subset(idx); Xd, Xs = apply_standardizer(ws.X_dyn, ws.X_stat, stats)
        real = raw_to_real(ensemble_forward(models, Xd, Xs))
        p10 = real["soh_p10"] - off["c_lo_soh"]; p90 = real["soh_p90"] + off["c_hi_soh"]
        x = ws.cycle_idx
        ax.fill_between(x, p10, p90, color=GOLD, alpha=0.30, label="P10–P90 band (conformal)")
        ax.plot(x, real["soh_q50"], color=ORANGE, lw=2.4, label="predicted P50")
        ax.plot(x, ws.soh_true, color=INK, lw=1.6, ls="--", label="true SoH (simulator)")
        ax.axhline(80, color="#dc3545", lw=1.4, ls=":")
        ax.set_title("test battery %s" % bid, fontsize=11, color=INK); ax.set_xlabel("outage cycle"); ax.grid(alpha=0.25)
        if k == 0: ax.set_ylabel("State of health (%)"); ax.legend(fontsize=8.5, loc="lower left", frameon=False)
    axes[0].set_ylim(55, 105); axes[2].text(axes[2].get_xlim()[1], 80.6, "EoL 80 %", ha="right", color="#dc3545", fontsize=9)
    fig.suptitle("SoH prediction on 3 independent test batteries — synthetic tubular data; band is calibrated but wide (MAE 8.2 pt)", fontsize=12, color=INK)
    save(fig, "soh_band")
except Exception as e:
    print("soh_band skipped:", e)

# ---------- 5. Autopilot SoC ladder ----------
fig, ax = plt.subplots(figsize=(12, 4.2))
t = np.linspace(0, 6, 400); soc = 95 - 12 * t + 3 * np.sin(t * 2)
soc = np.clip(soc, 20, 100)
ax.plot(t, soc, color=INK, lw=2.5, label="battery SoC during an outage")
for y, lab, c in [(70, "T2 restore ≥70 %", AMBER), (55, "T2 defer ≤55 %  ·  T3 restore ≥55 %", ORANGE), (40, "T3 shed ≤40 %", "#dc3545")]:
    ax.axhline(y, color=c, lw=1.6, ls="--"); ax.text(6.05, y, lab, va="center", fontsize=10, color=c)
ax.axhspan(0, 40, color="#dc3545", alpha=0.06); ax.axhspan(40, 55, color=ORANGE, alpha=0.06)
ax.text(0.1, 24, "T1 essentials: NEVER shed — fridge, router, lights, medical", fontsize=11, color=INK, fontweight="bold")
ax.set_xlim(0, 8.4); ax.set_ylim(15, 100); ax.set_xlabel("hours into outage"); ax.set_ylabel("SoC (%)")
ax.set_title("Tiered shedding with 15-point hysteresis, 3–5 min dwell, 60 s re-evaluation", fontsize=12, color=INK)
ax.legend(frameon=False, loc="upper right"); ax.grid(alpha=0.25)
save(fig, "autopilot_ladder")

# ---------- 6. Outage detection / fail-safe flow ----------
fig, ax = plt.subplots(figsize=(13, 3.4)); ax.set_xlim(0, 13); ax.set_ylim(0, 3.4); ax.axis("off")
chain = [("mains RMS < 0.1 pu\n(AMC1311 path)", LIGHT), ("inverter mode pin\n(embedded)", LIGHT), ("discharge onset\n(shunt)", LIGHT)]
for i, (t, c) in enumerate(chain): box(ax, 0.2, 2.45 - i * 0.95, 2.6, 0.8, t, fc=c, fs=9.5)
box(ax, 3.4, 1.1, 2.2, 1.3, "2-of-3 vote\n≤ 2 s debounce", fc=AMBER, bold=True, fs=10.5)
for i in range(3): arrow(ax, (2.8, 2.85 - i * 0.95), (3.4, 1.75))
box(ax, 6.1, 1.1, 2.4, 1.3, "Autopilot\nevery 60 s", fc=GOLD, bold=True, fs=10.5); arrow(ax, (5.6, 1.75), (6.1, 1.75), lw=2.5)
box(ax, 9.0, 1.1, 3.8, 1.3, "NC contactors\ncoil energised = shed\nany fault / reset → coils drop → ALL LOADS ON", fc=ORANGE, bold=True, fs=9.5, tc=WHITE); arrow(ax, (8.5, 1.75), (9.0, 1.75), lw=2.5)
ax.text(6.5, 0.12, "Independent supervisory timer on the driver board cuts every coil if the processor stops its 2 s heartbeat — a hardware guarantee, not firmware", ha="center", fontsize=10, color=GREY, style="italic")
save(fig, "failsafe_flow")

# ---------- 7. NILM event detection on the synthetic home ----------
try:
    from nilm.appliance_sim import simulate_home
    from nilm.event_detector import EventDetector
    df, _gt = simulate_home(duration_s=3 * 3600, rate_hz=1.0, afe=False, seed=7)
    det = EventDetector(has_afe=False); evs = []
    for r in df.itertuples():
        e = det.push(float(r.t), float(r.P), float(r.Q), float(r.Vrms))
        
        if e: evs.append(e)
    fig, ax = plt.subplots(figsize=(12, 4.2))
    tt = (df["t"].to_numpy() - df["t"].iloc[0]) / 60.0
    ax.plot(tt, df["P"], color=INK, lw=1.2, label="aggregate real power at the inverter output")
    for e in evs:
        te = (e.t0 - df["t"].iloc[0]) / 60.0
        ax.axvline(te, color=ORANGE if e.dP > 0 else GOLD, lw=1.2, alpha=0.8)
    ax.set_xlabel("minutes"); ax.set_ylabel("W"); ax.set_title(f"Energy Coach: {len(evs)} appliance ON/OFF events detected from the P/Q stream (orange = ON, gold = OFF)", fontsize=12, color=INK)
    ax.legend(frameon=False, loc="upper left"); ax.grid(alpha=0.25)
    save(fig, "nilm_events")
except Exception as e:
    print("nilm_events skipped:", e)

# ---------- 8. Grid Shield dip detection ----------
try:
    from pq.pq import run_processor_on_stream
    fs = 4000; f0 = 50; T = 1.2
    t = np.arange(0, T, 1 / fs); v = 230 * np.sqrt(2) * np.sin(2 * np.pi * f0 * t)
    dip = (t > 0.40) & (t < 0.52); v[dip] *= 0.55
    swell = (t > 0.85) & (t < 0.95); v[swell] *= 1.15
    events = run_processor_on_stream(v)
    half = int(fs / f0 / 2); rms = np.full_like(t, np.nan)
    for i in range(2 * half, len(v), half):
        rms[i - half:i] = np.sqrt(np.mean(v[i - 2 * half:i] ** 2))
    print("pq events:", [(getattr(e, "event_type", "?"), round(getattr(e, "magnitude_pu", 0), 3)) for e in events][:4])
    fig, ax = plt.subplots(figsize=(12, 4.2))
    ax.plot(t * 1000, v / (230 * np.sqrt(2)), color=LIGHT, lw=0.8)
    ax.plot(t * 1000, np.array(rms, dtype=float) / 230.0, color=INK, lw=2, label="half-cycle RMS Urms(1/2), pu")
    ax.axhline(0.9, color=ORANGE, ls="--"); ax.axhline(1.1, color=ORANGE, ls="--"); ax.axhline(0.1, color="#dc3545", ls=":")
    ax.text(1200, 0.91, "sag < 0.9 pu", color=ORANGE, ha="right", fontsize=10); ax.text(1200, 1.11, "swell > 1.1 pu", color=ORANGE, ha="right", fontsize=10)
    ax.set_xlabel("ms"); ax.set_ylabel("pu"); ax.set_ylim(-1.6, 1.7); ax.set_title("Grid Shield: 120 ms sag to 0.55 pu and 100 ms swell classified per IEEE 1159 (magnitude error < 1 %)", fontsize=12, color=INK)
    ax.legend(frameon=False, loc="lower left"); ax.grid(alpha=0.25)
    save(fig, "pq_dip")
except Exception as e:
    print("pq_dip skipped:", e)

# ---------- 9. Tests per module ----------
mods = [("autopilot", 65), ("charger", 48), ("health log", 31), ("model", 21), ("dashboard", 19), ("datasets", 12), ("features", 12), ("sim", 11), ("firmware host", 7), ("NILM", 6), ("PQ", 6), ("EKF", 5), ("leakage", 2)]
fig, ax = plt.subplots(figsize=(11, 4.6))
names = [m for m, _ in mods][::-1]; vals = [v for _, v in mods][::-1]
ax.barh(names, vals, color=[GOLD if v >= 20 else AMBER for v in vals], edgecolor=INK)
for i, v in enumerate(vals): ax.text(v + 0.8, i, str(v), va="center", fontsize=10, color=INK)
ax.set_xlabel("automated tests (245 total, all passing, plus C host builds for 6 modules)"); ax.set_title("What was actually executed on this prototype codebase", fontsize=12, color=INK)
ax.grid(axis="x", alpha=0.25); ax.spines[["top", "right"]].set_visible(False)
save(fig, "tests_per_module")

# ---------- 10. Firmware task map ----------
fig, ax = plt.subplots(figsize=(13, 5.2)); ax.set_xlim(0, 13); ax.set_ylim(0, 5.2); ax.axis("off")
ax.text(3.2, 4.85, "Core 0 — radios (optional, off in outages)", fontsize=11, fontweight="bold", color=INK); ax.text(9.2, 4.85, "Core 1 — control loop (always on)", fontsize=11, fontweight="bold", color=INK)
for i, t in enumerate(["Wi-Fi / BLE stacks", "MQTT telemetry (~1 KB/day)", "OTA: firmware A/B · model A/B", "BLE app: labels, tiers, override"]):
    box(ax, 0.4, 3.9 - i * 0.95, 5.4, 0.75, t, fc=LIGHT, fs=10)
tasks = ["sense_1hz → Sample ring", "ekf (SoC, R0, anchors)", "autopilot (60 s) + outage vote", "cycle_feat → ml_infer (int8 CNN, per cycle)", "afe_3hz → NILM  ·  pq (4 kS/s RMS/FFT)", "logger (LittleFS) · health-log signing", "heartbeat → supervisory timer"]
for i, t in enumerate(tasks):
    box(ax, 6.4, 4.2 - i * 0.62, 6.2, 0.5, t, fc=GOLD if i in (1, 3) else AMBER, fs=9.5, bold=(i in (1, 3)))
ax.text(6.5, 0.15, "Flash: bootloader · NVS · app A/B (3 MB) · model A/B (128 KB) · data 1 MB · coredump   |   RAM for ML ≈ 32 KB of 512 KB", fontsize=9.5, color=GREY, style="italic")
save(fig, "firmware_tasks")

# ---------- 11. Demo sequence ----------
fig, ax = plt.subplots(figsize=(13, 2.9)); ax.set_xlim(0, 13); ax.set_ylim(0, 2.9); ax.axis("off")
steps = ["Live SoC / R_int\non the real battery", "Flip the MCB:\noutage in < 2 s", "SoC ≤ 40 %:\nT3 sheds, T1 stays", "Reset the MCU:\nall loads back < 2 s", "Switch fan, iron:\nCoach asks\n\"what turned on?\"", "SoH replay:\n\"replace in 6–14 wk\"", "Signed log:\none byte altered → fails"]
for i, t in enumerate(steps):
    box(ax, 0.15 + i * 1.85, 0.6, 1.7, 1.7, t, fc=GOLD if i in (2, 3) else LIGHT, fs=9, bold=(i in (2, 3)))
    if i < 6: arrow(ax, (1.85 + i * 1.85, 1.45), (2.0 + i * 1.85, 1.45), lw=2)
save(fig, "demo_flow")

# ---------- 12. Evidence ladder ----------
fig, ax = plt.subplots(figsize=(12, 3.8)); ax.set_xlim(0, 12); ax.set_ylim(0, 3.8); ax.axis("off")
cols = [("PROVEN HERE", "245 tests · C ports bit-identical to Python\nint8 model exported and self-tested\nfail-safe logic, PQ & NILM detectors\nsigned log with checkpoints", GOLD),
        ("SYNTHETIC ONLY", "SoH MAE 8.2 pt on an independent test split\nRUL band calibrated (0.99 coverage, too wide)\nEKF ±3 % vs 7 %/week naive drift\nall on simulated tubular batteries", AMBER),
        ("NEEDS HARDWARE / DATA", "ESP32 flash + latency on silicon\nreal battery, CT, PZEM on the bench\naging campaign → real SoH accuracy\nlife-extension % measured, not assumed", LIGHT)]
for i, (h, b, c) in enumerate(cols):
    box(ax, 0.2 + i * 3.95, 0.3, 3.7, 3.2, "", fc=c)
    ax.text(2.05 + i * 3.95, 3.05, h, ha="center", fontsize=12, fontweight="bold", color=INK)
    ax.text(2.05 + i * 3.95, 1.55, b, ha="center", va="center", fontsize=9.8, color=INK)
save(fig, "evidence_ladder")

# ---------- 13. Cost tiers ----------
fig, ax = plt.subplots(figsize=(11, 3.9))
tiers = ["Basic board\n(Engines 1+2)", "+ shunt\n(standalone)", "+ Coach kit\n(Engine 3)", "Embedded increment\n(basic)", "Embedded increment\n(with Coach)"]
lo = [750, 1050, 1650, 450, 850]; hi = [750, 1050, 2050, 700, 1300]
x = np.arange(len(tiers))
ax.bar(x, hi, color=LIGHT, edgecolor=INK); ax.bar(x, lo, color=GOLD, edgecolor=INK)
for i in range(len(tiers)): ax.text(i, hi[i] + 40, f"₹{lo[i]:,}" + (f"–{hi[i]:,}" if hi[i] != lo[i] else ""), ha="center", fontsize=10, color=INK)
ax.set_xticks(x); ax.set_xticklabels(tiers, fontsize=9.5); ax.set_ylabel("INR per unit"); ax.set_ylim(0, 2500)
ax.set_title("Cost stated by the engines each tier enables — all single-digit % of a ₹15 k battery", fontsize=12, color=INK)
ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="y", alpha=0.25)
save(fig, "cost_tiers")

# ---------- 14. Problem stats ----------
fig, ax = plt.subplots(figsize=(12, 3.4)); ax.set_xlim(0, 12); ax.set_ylim(0, 3.4); ax.axis("off")
stats_ = [("~10 y → ~3.3 y", "lead-acid life at 25 °C vs 41 °C:\nheat halves life every +10 °C"), ("≈1.5 %", "of V-Guard revenue goes to\nwarranty (≈₹69 cr, FY24)"), ("< 10 ms", "V-Guard Prime transfer time —\nthe inverter is fast; the battery is blind")]
for i, (n, s) in enumerate(stats_):
    box(ax, 0.2 + i * 3.95, 0.3, 3.7, 2.8, "", fc=LIGHT)
    ax.text(2.05 + i * 3.95, 2.35, n, ha="center", fontsize=22, fontweight="bold", color=ORANGE)
    ax.text(2.05 + i * 3.95, 1.1, s, ha="center", va="center", fontsize=10.5, color=INK)
save(fig, "problem_stats")
print("assets:", sorted(os.listdir(OUT)))
