"""Sentinel finale deck rebuilt on the reference deck's design system (dark charcoal, single yellow accent,
soft-grey cards with a yellow bar, olive note strips, numbered hairline columns, numbered timeline, half-slide image panels)."""
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
import os
from PIL import Image
C = lambda h: RGBColor.from_string(h)
BG, DARK, CARD, LINE, NOTE, YEL, TXT, MUTED, WHITE, INKD = C("27272B"), C("1B1B1E"), C("46464A"), C("5F5F63"), C("4D4000"), C("FFE14D"), C("D7D4CC"), C("9A9A9E"), C("FFFFFF"), C("1B1B1E")
FONT = "Raleway"; A = "assets_dark"
prs = Presentation(); prs.slide_width = Inches(16); prs.slide_height = Inches(9); W, H = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[6]

def rect(s, x, y, w, h, fill, line=None):
    r = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h); r.fill.solid(); r.fill.fore_color.rgb = fill
    if line is None: r.line.fill.background()
    else: r.line.color.rgb = line
    r.shadow.inherit = False; return r
def rrect(s, x, y, w, h, fill):
    r = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h); r.fill.solid(); r.fill.fore_color.rgb = fill; r.line.fill.background(); r.shadow.inherit = False
    r.adjustments[0] = 0.06; return r
def text(s, x, y, w, h, t, size=17, color=TXT, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, italic=False, font=FONT, ls=1.1):
    tb = s.shapes.add_textbox(x, y, w, h); tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.04); tf.margin_top = tf.margin_bottom = Inches(0.02)
    for i, ln in enumerate(t if isinstance(t, list) else [t]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph(); p.alignment = align; p.line_spacing = ls
        r = p.add_run(); r.text = ln; f = r.font; f.size = Pt(size); f.color.rgb = color; f.bold = bold; f.italic = italic; f.name = font
    return tb
def rich(s, x, y, w, h, parts, size=17, ls=1.15):
    """parts: list of paragraphs; each paragraph = list of (text, color, bold)"""
    tb = s.shapes.add_textbox(x, y, w, h); tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.04); tf.margin_top = tf.margin_bottom = Inches(0.02)
    for i, para in enumerate(parts):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph(); p.line_spacing = ls; p.space_after = Pt(5)
        for (t, col, b) in para:
            r = p.add_run(); r.text = t; r.font.size = Pt(size); r.font.color.rgb = col; r.font.bold = b; r.font.name = FONT
    return tb
def bullets(s, x, y, w, h, items, size=16, gap=5):
    parts = []
    for it in items:
        if it.startswith("**") and "**" in it[2:]:
            head, rest = it[2:].split("**", 1); parts.append([("•  ", YEL, False), (head, WHITE, True), (rest, TXT, False)])
        else: parts.append([("•  ", YEL, False), (it, TXT, False)])
    tb = rich(s, x, y, w, h, parts, size=size)
    for p in tb.text_frame.paragraphs: p.space_after = Pt(gap)
    return tb
def title(s, t, x=Inches(0.85), y=Inches(0.6), w=Inches(9), size=38):
    text(s, x, y, w, Inches(1.0), t, size=size, color=YEL, bold=True)
def logo(s):
    p = os.path.join(A, "vguard-big-idea-logo.png"); s.shapes.add_picture(p, Inches(14.01), Inches(8.33), height=Inches(0.54))
    text(s, Inches(0.4), Inches(8.42), Inches(8), Inches(0.4), "V-Guard Sentinel · Team Codey Tingle (TI3271) · Big Idea Tech 2026, Track 4", size=10, color=MUTED)
def slide():
    s = prs.slides.add_slide(BLANK); rect(s, 0, 0, W, H, BG); return s
def panel_pic(s, name, x, y, w, h):
    """fit an image inside a fixed panel (letterbox on DARK)"""
    rect(s, x, y, w, h, DARK)
    p = os.path.join(A, name + ".png"); im = Image.open(p); iw, ih = im.size
    ar = iw / ih; pw, ph = w, h
    if pw / ph > ar: pw2 = int(ph * ar); s.shapes.add_picture(p, x + (pw - pw2) // 2, y, height=ph)
    else: ph2 = int(pw / ar); s.shapes.add_picture(p, x, y + (ph - ph2) // 2, width=pw)
def note(s, x, y, w, h, head, body, size=15):
    rrect(s, x, y, w, h, NOTE)
    rect(s, x + Inches(0.22), y + h // 2 - Inches(0.1), Inches(0.2), Inches(0.2), YEL)
    rich(s, x + Inches(0.55), y + Inches(0.1), w - Inches(0.7), h - Inches(0.15), [[(head + " ", YEL, True), (body, TXT, False)]], size=size)
def card(s, x, y, w, h, head, body, hsize=18, bsize=15):
    rrect(s, x, y, w, h, DARK); rect(s, x, y, Inches(0.1), h, YEL)
    text(s, x + Inches(0.33), y + Inches(0.2), w - Inches(0.45), Inches(0.4), head, size=hsize, color=WHITE, bold=True)
    text(s, x + Inches(0.33), y + Inches(0.65), w - Inches(0.45), h - Inches(0.75), body, size=bsize, color=TXT)
def kit(s, x, y, w, h, head, l1, l2, tag="Perfect for:"):
    rrect(s, x, y, w, h, BG); rrect(s, x + Inches(0.04), y + Inches(0.03), w - Inches(0.08), Inches(0.75), CARD)
    text(s, x + Inches(0.3), y + Inches(0.18), w - Inches(0.6), Inches(0.45), head, size=19, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    text(s, x + Inches(0.3), y + Inches(1.0), w - Inches(0.6), Inches(0.9), l1, size=15, color=TXT)
    rich(s, x + Inches(0.3), y + h - Inches(0.95), w - Inches(0.6), Inches(0.8), [[(tag + " ", YEL, True), (l2, TXT, False)]], size=15)
def numcol(s, x, y, w, n, head, body):
    text(s, x, y, Inches(0.5), Inches(0.3), n, size=17, color=YEL)
    rect(s, x, y + Inches(0.38), w, Inches(0.03), YEL)
    text(s, x, y + Inches(0.56), w, Inches(0.4), head, size=19, color=WHITE, bold=True)
    text(s, x, y + Inches(1.05), w, Inches(1.4), body, size=15.5, color=TXT)
def timeline(s, x, y, items, step=Inches(0.98)):
    rect(s, x + Inches(0.2), y, Inches(0.03), step * (len(items) - 1) + Inches(0.4), LINE)
    for i, (h, b) in enumerate(items):
        yy = y + step * i
        c = s.shapes.add_shape(MSO_SHAPE.OVAL, x, yy, Inches(0.42), Inches(0.42)); c.fill.solid(); c.fill.fore_color.rgb = CARD; c.line.fill.background()
        text(s, x, yy + Inches(0.03), Inches(0.42), Inches(0.36), str(i + 1), size=17, color=WHITE, align=PP_ALIGN.CENTER)
        rect(s, x + Inches(0.4), yy + Inches(0.2), Inches(0.55), Inches(0.03), LINE)
        text(s, x + Inches(1.13), yy + Inches(0.02), Inches(8), Inches(0.35), h, size=15, color=WHITE, bold=True)
        text(s, x + Inches(1.13), yy + Inches(0.4), Inches(8), Inches(0.6), b, size=13.5, color=TXT)

# ---------- 1 · Title (left image panel, like the reference) ----------
s = slide(); panel_pic(s, "panel_title", 0, 0, Inches(6), H)
text(s, Inches(6.94), Inches(2.0), Inches(8.4), Inches(1.7), "V-Guard Sentinel: the self-aware home inverter", size=43, color=YEL, bold=True)
rich(s, Inches(6.94), Inches(4.2), Inches(8.4), Inches(0.9), [[("Team: ", WHITE, True), ("Codey Tingle (TI3271) · Ayush Manoj Garg, Eshan Shukla, Tanay Chaplot", TXT, False)]], size=24)
rich(s, Inches(7.06), Inches(5.55), Inches(8.2), Inches(2.0), [[("Problem: ", WHITE, True), ("India's home inverters switch in under 10 ms but are blind to the one part that actually fails — the battery. It dies without warning, the family loses backup and pays ₹15–18 k, and V-Guard pays inside the warranty window. Today's products sense voltage and current and turn none of it into foresight.", TXT, False)]], size=19)
logo(s)

# ---------- 2 · Vision & mission (right image panel) ----------
s = slide(); panel_pic(s, "panel_vision", Inches(10), 0, Inches(6), H)
title(s, "Our Vision & Mission", y=Inches(1.0), size=43)
rrect(s, Inches(0.94), Inches(2.17), Inches(8.11), Inches(1.94), CARD)
text(s, Inches(1.21), Inches(2.44), Inches(3), Inches(0.4), "Vision", size=21.5, color=WHITE, bold=True)
text(s, Inches(1.21), Inches(2.98), Inches(7.57), Inches(1.0), "Every V-Guard product moves from smart to intelligent: it predicts its own failure, learns its owner's habits and acts on its own — offline, on a ₹300 microcontroller.", size=19, color=TXT)
text(s, Inches(0.94), Inches(4.69), Inches(3), Inches(0.4), "Goals", size=21.5, color=YEL, bold=True)
bullets(s, Inches(0.94), Inches(5.25), Inches(4.0), Inches(2.6), ["Never let a battery die unannounced", "Keep the essentials alive through every blackout", "Turn warranty into evidence, not argument"], size=18, gap=9)
text(s, Inches(5.34), Inches(4.69), Inches(3), Inches(0.4), "Tech Stack", size=21.5, color=YEL, bold=True)
text(s, Inches(5.34), Inches(5.25), Inches(4.2), Inches(2.6), "ESP32-S3 · TensorFlow Lite Micro (int8) · Kalman filtering · event-based NILM · IEEE 1159 power quality · ECDSA-signed logs · Flask dashboard · ESP-IDF firmware · Python/C prototype with 245 tests", size=17, color=TXT)
logo(s)

# ---------- 3 · Engine suite (left image panel, icon list, note strip) ----------
s = slide(); panel_pic(s, "panel_suite", 0, 0, Inches(6), H)
text(s, Inches(6.66), Inches(0.55), Inches(8.7), Inches(0.6), "Sentinel Engine Suite", size=30, color=YEL, bold=True)
eng = [("Engine 1 · Battery Health", "Coulomb counting and a Kalman filter fuse current, voltage and temperature into state of charge; a 28 k-parameter int8 network turns each outage cycle into a state-of-health band and the warning “replace within 6–14 weeks”."),
       ("Engine 2 · Habit Autopilot", "Learns the home's load and outage rhythm, detects a blackout in under 2 s by a 2-of-3 vote, and sheds heavy loads by tier so the fridge, lights and router last longest. Every fault fails safe: coil off means loads on."),
       ("Engine 3 · Energy Coach & Grid Shield", "A metering front-end on the inverter output gives real and reactive power. Appliance events are recognised and priced; sags, swells and interruptions are logged as appliance-protection evidence."),
       ("Engine 4 · Fleet Intelligence", "Consented, pseudonymised per-cycle summaries (~1 KB/day) train better models centrally and return over the air. Federated learning is designed and deliberately on hold.")]
for i, (h, b) in enumerate(eng):
    y = Inches(1.35) + Inches(1.5) * i
    rect(s, Inches(6.66), y, Inches(0.42), Inches(0.42), YEL); text(s, Inches(6.66), y + Inches(0.02), Inches(0.42), Inches(0.4), str(i + 1), size=17, color=INKD, bold=True, align=PP_ALIGN.CENTER)
    text(s, Inches(7.25), y - Inches(0.02), Inches(8), Inches(0.4), h, size=15, color=WHITE, bold=True)
    text(s, Inches(6.66), y + Inches(0.5), Inches(8.7), Inches(0.95), b, size=13, color=TXT)
note(s, Inches(6.66), Inches(7.45), Inches(8.68), Inches(0.8), "Key advantage:", "every core function runs with zero internet — a virtue in India, not a compromise; retrofits the installed base or embeds in new inverters.", size=13.5)
logo(s)

# ---------- 4 · Product SKUs as kits (2×2 cards) ----------
s = slide(); title(s, "The Product Kits", y=Inches(0.62), size=39.5)
kit(s, Inches(0.87), Inches(1.88), Inches(7.0), Inches(2.77), "Sentinel-Retrofit box", "Core board beside the inverter · external 0.1 mΩ shunt in the battery negative lead · NTC on the battery · CT + voltage tap on AC-OUT · 4 fail-safe contactor channels.", "the installed base — a 30–45 minute electrician install, no inverter modification")
kit(s, Inches(8.12), Inches(1.88), Inches(7.0), Inches(2.77), "Sentinel-Embedded board", "Daughter-board inside a new V-Guard inverter · Kelvin-taps the inverter's own shunt · commands the charger through a DAC on the PWM node with a hardware voltage/thermal ceiling.", "the Smart Pro family — adaptive charging and the life-extension claim live here only")
kit(s, Inches(0.87), Inches(4.89), Inches(7.0), Inches(2.77), "Energy Coach kit", "ATM90E32AS metering front-end + split-core CT + voltage tap + isolator: real and reactive power at 3 Hz on the inverter output (optional second CT on the mains).", "homes that want appliance-level kWh, ₹ at ToD tariff and grid-event evidence")
kit(s, Inches(8.12), Inches(4.89), Inches(7.0), Inches(2.77), "Contactor panel", "2–4 × 25 A normally-closed DIN contactors with 12 V coils, one hardware-locked medical channel and a supervisory timer that drops every coil if the processor stops its heartbeat.", "tiered load-shedding — granularity equals the number of channels wired")
rich(s, Inches(0.87), Inches(7.8), Inches(13.0), Inches(0.5), [[("Cost by engine: ", YEL, True), ("basic board ≈ ₹750 · with shunt ≈ ₹1,050 · full retrofit with Coach ≈ ₹1,650–2,050 · embedded increment ₹450–1,300 — single-digit % of a ₹15 k battery.", TXT, False)]], size=13.5)
logo(s)

# ---------- 5 · Engine 1 (top banner + 3 numbered columns + note) ----------
s = slide(); panel_pic(s, "soh_band", 0, 0, W, Inches(3.03))
text(s, Inches(0.85), Inches(3.3), Inches(12), Inches(0.7), "Engine 1: Predicting Battery Life", size=38.5, color=YEL, bold=True)
numcol(s, Inches(0.85), Inches(4.35), Inches(4.61), "01", "Estimate", "A 3-state Kalman filter (SoC, polarisation, R0) on 1 Hz current, voltage and temperature. SoC re-anchors to 100 % on charge-current taper and to the OCV table only after a true rest with the charger off.")
numcol(s, Inches(5.7), Inches(4.35), Inches(4.61), "02", "Reduce", "Each outage cycle becomes 14 physics features plus 6 lifetime integrals: resistance and sag vs the battery's own baseline, throughput, depth of discharge, coulombic efficiency, charge acceptance, dQ/dV, Arrhenius heat stress.")
numcol(s, Inches(10.55), Inches(4.35), Inches(4.61), "03", "Infer", "An int8 1-D CNN over the last 30 cycles, three seeds averaged, quantile heads P10/P50/P90 with conformal calibration — a window, never a date. 16 KB of RAM, ~1–10 ms per inference on the ESP32-S3.")
rect(s, Inches(0.85), Inches(7.18), Inches(0.03), Inches(0.93), YEL)
rich(s, Inches(1.21), Inches(7.22), Inches(13.9), Inches(0.9), [[("Measured today (synthetic tubular data, independent test split): ", YEL, True), ("SoH MAE 8.2 pt · 80 % band coverage 0.66 → 0.99 after calibration but still 34 pt wide · EKF within ±3 % vs 7 %/week naive drift · int8 costs +0.01 pt · target ≤ 3 pt needs the aging campaign.", TXT, False)]], size=15)
logo(s)

# ---------- 6 · Engine 2 (top banner + two lists + grey panel) ----------
s = slide(); panel_pic(s, "autopilot_ladder", 0, 0, W, Inches(2.8))
text(s, Inches(0.78), Inches(3.0), Inches(12), Inches(0.7), "Engine 2: Autopilot That Fails Safe", size=35.5, color=YEL, bold=True)
text(s, Inches(0.78), Inches(3.95), Inches(4), Inches(0.4), "How It Works", size=17.5, color=YEL, bold=True)
bullets(s, Inches(0.78), Inches(4.45), Inches(6.94), Inches(2.5), ["Hour-of-week load and outage tables (4.7 KB) a judge can read", "Forecasts the roster, not the storm: scheduled cuts are predictable, faults are detected", "Outage declared by a 2-of-3 vote in under 2 s; restore after 10–30 s above 0.9 pu", "T1 never shed · T2 defer ≤ 55 % · T3 shed ≤ 40 %, 15-point hysteresis, 3–5 min dwell"], size=15, gap=4)
text(s, Inches(8.28), Inches(3.95), Inches(4), Inches(0.4), "Key Benefits", size=17.5, color=YEL, bold=True)
bullets(s, Inches(8.28), Inches(4.45), Inches(6.94), Inches(2.5), ["Fridge, router, lights and medical loads last longest", "No chatter, no compressor short-cycling: 65 tests, 50/50 scripted scenarios in C", "30-minute user override that cannot beat the safety floor", "Works with zero internet and no inverter cooperation"], size=15, gap=4)
rrect(s, Inches(0.66), Inches(7.03), Inches(14.43), Inches(1.25), CARD)
text(s, Inches(1.01), Inches(7.2), Inches(6), Inches(0.4), "Fail-safe by wiring, not by software", size=17.5, color=WHITE, bold=True)
text(s, Inches(1.01), Inches(7.62), Inches(13.9), Inches(0.6), "Normally-closed contactors: an energised coil sheds, a de-energised coil means loads on. Any crash, brown-out or watchdog reset — and an independent supervisory timer on the driver board — drops every coil within 2 s.", size=15, color=TXT)
logo(s)

# ---------- 7 · Engine 3 (right image panel with two charts + three cards + note) ----------
s = slide(); rect(s, Inches(10), 0, Inches(6), H, DARK)
panel_pic(s, "nilm_events", Inches(10.15), Inches(0.6), Inches(5.7), Inches(3.7)); panel_pic(s, "pq_dip", Inches(10.15), Inches(4.7), Inches(5.7), Inches(3.7))
text(s, Inches(0.8), Inches(0.71), Inches(9), Inches(0.7), "Engine 3: Energy Coach & Grid Shield", size=30, color=YEL, bold=True)
text(s, Inches(0.8), Inches(1.6), Inches(8.6), Inches(0.9), "How the ESP32 tells appliances apart from one aggregate signal — and why the report's first bill of materials could not do it without a metering front-end:", size=16.5, color=TXT)
card(s, Inches(0.8), Inches(2.69), Inches(4.08), Inches(2.07), "1 · Detect the step", "Moving-average change test on real and reactive power at 3 Hz: ΔP ≥ 25 W, settle-time limit, ON/OFF pairing.", bsize=14)
card(s, Inches(5.11), Inches(2.69), Inches(4.08), Inches(2.07), "2 · Sign it", "13 numbers per event — ΔP, ΔQ, phase angle, inrush ratio, settling time, harmonic share, duration, periodicity, time of day.", bsize=14)
card(s, Inches(0.8), Inches(4.99), Inches(4.08), Inches(1.75), "3 · Match it", "Rules + k-NN against a per-home library seeded from an Indian appliance table and named by the user: “what just turned on?”", bsize=14)
card(s, Inches(5.11), Inches(4.99), Inches(4.08), Inches(1.75), "Grid Shield", "Half-cycle RMS on an isolated tap, IEEE 1159 buckets, 4-cycle FFT for THD. Class-S-like, never “Class A”.", bsize=14)
note(s, Inches(0.8), Inches(6.95), Inches(8.39), Inches(1.34), "Measured:", "event recall 1.00, fridge F1 0.97; 13/13 dips detected, magnitude error < 1 %, duration error 0 half-cycles. Honest scope: fridge, AC, geyser, pump, iron/kettle — not two identical fans, not loads under 40 W.", size=14)
logo(s)

# ---------- 8 · Prototype: what runs (hero band + chart + lists) ----------
s = slide(); text(s, Inches(0.63), Inches(0.5), Inches(10), Inches(0.6), "The Prototype: What Actually Runs", size=28.5, color=YEL, bold=True)
rrect(s, Inches(0.63), Inches(1.27), Inches(14.74), Inches(1.73), CARD)
rect(s, Inches(0.81), Inches(1.45), Inches(0.54), Inches(0.54), YEL); text(s, Inches(0.81), Inches(1.5), Inches(0.54), Inches(0.5), "✓", size=24, color=INKD, bold=True, align=PP_ALIGN.CENTER)
text(s, Inches(1.5), Inches(1.42), Inches(13.6), Inches(0.6), "245 automated tests · 6 C modules bit-identical to Python · full-int8 model on 3 seeds · firmware host build", size=20, color=WHITE, bold=True)
text(s, Inches(0.81), Inches(2.25), Inches(14.4), Inches(0.6), "Not a slide deck — a codebase. Every engine implemented, tested and reproducible with one script; the same C is linked into the ESP-IDF firmware.", size=18, color=TXT)
panel_pic(s, "tests_per_module", Inches(0.62), Inches(3.4), Inches(7.2), Inches(4.7))
text(s, Inches(8.3), Inches(3.4), Inches(7), Inches(0.4), "Inside the repository", size=20, color=YEL, bold=True)
bullets(s, Inches(8.3), Inches(3.9), Inches(7.1), Inches(4.4), ["**Simulator + features:** synthetic Indian tubular duty cycles at 1 Hz → 14 + 6 physics features per cycle", "**Model pipeline:** train → evaluate → int8 → .tflite, independent test split, leakage guard, transfer ablation", "**EKF · autopilot · NILM · PQ · health log · charger policy:** Python reference + C99 port", "**Firmware:** ESP-IDF task map; host binary runs the loop on a battery CSV and feeds the dashboard", "**Dashboard:** Flask + one page; scripted finale sequence or live device file"], size=14.5, gap=5)
logo(s)

# ---------- 9 · Self-contained (left image + lists) ----------
s = slide(); panel_pic(s, "firmware_tasks", Inches(0.45), Inches(1.75), Inches(8.4), Inches(5.6))
text(s, Inches(0.47), Inches(0.5), Inches(12), Inches(0.6), "Self-Contained by Construction", size=30, color=YEL, bold=True)
text(s, Inches(0.47), Inches(1.15), Inches(12), Inches(0.5), "Unplug the router for a year: every function below still works. The cloud only adds updates and fleet learning.", size=16, color=TXT)
text(s, Inches(9.3), Inches(1.8), Inches(6.2), Inches(0.4), "How the TinyML actually runs", size=19, color=YEL, bold=True)
bullets(s, Inches(9.3), Inches(2.3), Inches(6.3), Inches(4.5), ["Fixed int8 weights (3 × 36.7 KB) in a signed model partition, updated independently of firmware", "TFLite Micro with six registered ops and a 16 KB arena; golden self-test at boot, fallback slot on failure", "One inference per outage cycle: the last 30 cycles in, three quantiles out", "Plain C turns quantiles into weeks and “replace within N weeks” with hysteresis", "No training on the device, ever — personalisation is ratio-to-baseline features and a conformal offset"], size=14.5, gap=6)
note(s, Inches(9.3), Inches(6.95), Inches(6.2), Inches(0.9), "Draw:", "≈ 2.6 mA average from the battery — 0.04 % of a 150 Ah battery per day.", size=13.5)
logo(s)

# ---------- 10 · Demo (flow banner + concept card + link strip) ----------
s = slide(); text(s, Inches(0.47), Inches(0.37), Inches(12), Inches(0.6), "Live Demonstration", size=28.5, color=YEL, bold=True)
panel_pic(s, "demo_flow", Inches(0.45), Inches(1.1), Inches(15.1), Inches(3.1))
rrect(s, Inches(0.45), Inches(4.5), Inches(7.3), Inches(2.6), DARK)
text(s, Inches(0.8), Inches(4.65), Inches(6.7), Inches(0.4), "Demo Concept", size=18, color=WHITE, bold=True)
text(s, Inches(0.8), Inches(5.1), Inches(6.7), Inches(1.9), "“A real 12 V tubular battery and inverter on the table, three relay-switched load tiers, nothing connected to the internet — and we pull the processor's reset while the heater circuit is shed to prove that loads come back.”", size=15.5, color=TXT, italic=True)
rrect(s, Inches(8.2), Inches(4.5), Inches(7.35), Inches(2.6), DARK)
text(s, Inches(8.55), Inches(4.65), Inches(6.8), Inches(0.4), "Real vs replayed", size=18, color=WHITE, bold=True)
bullets(s, Inches(8.55), Inches(5.1), Inches(6.8), Inches(2.0), ["**Real:** SoC and R0 from the shunt and Kalman filter, outage detection, tiered shedding, fail-safe restore, appliance events, signed-log verification", "**Replayed, labelled on screen:** the SoH walk to “Replace within N weeks” — a bench battery does not age in a week"], size=14, gap=4)
rrect(s, Inches(0.45), Inches(7.3), Inches(15.1), Inches(0.85), NOTE)
rich(s, Inches(0.8), Inches(7.48), Inches(14.5), Inches(0.6), [[("REPOSITORY (PRIVATE):  ", YEL, True), ("github.com/epshukla/vguard-sentinel — design register (17 decisions), prototype code, run_all.sh reproduces every number on this deck", TXT, False)]], size=15)
logo(s)

# ---------- 11 · Evidence ladder ----------
s = slide(); text(s, Inches(0.63), Inches(0.5), Inches(14), Inches(0.6), "Proven · Synthetic · Still Needs Hardware", size=30, color=YEL, bold=True)
text(s, Inches(0.63), Inches(1.15), Inches(14), Inches(0.5), "We separate what is deployable today from what is a research target — credibility is the whole game.", size=16, color=TXT)
panel_pic(s, "evidence_ladder", Inches(0.6), Inches(1.8), Inches(14.8), Inches(4.6))
note(s, Inches(0.63), Inches(6.7), Inches(14.74), Inches(1.4), "What building it taught us:", "float voltage is not open-circuit voltage; a battery shunt cannot see appliances; adaptive charging is embedded-only; federate the model that has labels on the device. Every correction is a numbered decision (D1–D17) in the design register.", size=15)
logo(s)

# ---------- 12 · Feasibility & roadmap (lists + timeline + right image) ----------
s = slide(); rect(s, Inches(10), 0, Inches(6), H, DARK); panel_pic(s, "cost_tiers", Inches(10.15), Inches(1.9), Inches(5.7), Inches(5.2))
text(s, Inches(0.65), Inches(0.51), Inches(9), Inches(0.6), "Feasibility & Growth Roadmap", size=29.5, color=YEL, bold=True)
text(s, Inches(0.65), Inches(1.48), Inches(4), Inches(0.3), "Technical Feasibility", size=14.5, color=YEL, bold=True)
bullets(s, Inches(0.65), Inches(1.85), Inches(4.3), Inches(2.2), ["ESP32-S3 with vector extensions, ₹300", "Metering AFE class used in smart meters", "Retrofit needs no inverter modification", "Embedded slots into the Smart Pro family"], size=13, gap=2)
text(s, Inches(0.65), Inches(3.48), Inches(4), Inches(0.3), "Business Value", size=14.5, color=YEL, bold=True)
bullets(s, Inches(0.65), Inches(3.85), Inches(4.3), Inches(2.0), ["Timely battery replacement revenue", "Warranty decided from signed evidence", "A premium “intelligent” tier", "A fleet-data moat no competitor can buy"], size=13, gap=2)
text(s, Inches(5.23), Inches(1.48), Inches(4), Inches(0.3), "Validation Targets", size=14.5, color=YEL, bold=True)
bullets(s, Inches(5.23), Inches(1.85), Inches(4.5), Inches(2.2), ["SoC within 3 % on reference shunts", "≥ 75 % RUL-window hit-rate", "Zero unsafe sheds; fridge/AC F1 ≥ 0.8", "Life-extension % measured, not assumed"], size=13, gap=2)
text(s, Inches(5.23), Inches(3.48), Inches(4), Inches(0.3), "What We Need", size=14.5, color=YEL, bold=True)
bullets(s, Inches(5.23), Inches(3.85), Inches(4.5), Inches(2.0), ["ESP32-S3 bench hardware", "One opened Prime-series inverter + charger schematic", "Batteries and cyclers for Gate 1"], size=13, gap=2)
timeline(s, Inches(0.65), Inches(5.45), [("Gate 1 · Dataset (6–8 months)", "24–36 tubular batteries, 3 temperatures × 3 depths × 2 regimes in the Kochi reliability lab → real SoH labels"), ("Gate 2 · Field pilot (100 units, 6 months)", "SoC, RUL, shedding safety, Coach accuracy and power budget verified in real homes"), ("Gate 3 · Learning stability", "Three model releases with no regression; embedded SKU ships in the Smart Pro family")])
logo(s)

# ---------- 13 · Close ----------
s = slide(); panel_pic(s, "panel_close", Inches(10), 0, Inches(6), H)
text(s, Inches(0.9), Inches(2.2), Inches(8.8), Inches(3.2), ["Coil off means loads on.", "A window, never a date.", "Offline first, fleet second."], size=38, color=YEL, bold=True, ls=1.25)
text(s, Inches(0.9), Inches(6.0), Inches(8.8), Inches(0.6), "V-Guard Sentinel — Team Codey Tingle (TI3271)", size=22, color=WHITE)
text(s, Inches(0.9), Inches(6.7), Inches(8.8), Inches(1.0), "Big Idea Tech 2026 · Track 4 · Finale, Kochi, 24 September 2026", size=16, color=TXT)
logo(s)
prs.save("VGuard-Sentinel-Finale-Deck.pptx"); print("saved", len(prs.slides), "slides")
