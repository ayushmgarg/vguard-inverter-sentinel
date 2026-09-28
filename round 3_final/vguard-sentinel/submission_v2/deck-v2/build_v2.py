"""V-Guard Sentinel — finale deck v2. Same V-Guard Big Idea Tech format (black / gold / orange / white, Arial),
assertion-evidence slides (sentence headline + one visual), talk track in speaker notes."""
import json, os, sys, copy
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.oxml.ns import qn
from lxml import etree
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(HERE, "assets")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "deck_v2.pptx")
TRACE = json.load(open(os.path.join(HERE, "trace.json"), encoding="utf-8"))

C = lambda h: RGBColor.from_string(h)
GOLD, ORANGE, BLACK, INK, GREY, LIGHT, WHITE = C("FDC300"), C("F39200"), C("000104"), C("221E1F"), C("6C757D"), C("F3EFEF"), C("FFFFFF")
CYAN, GREEN, RED, DARK2 = C("0E9FB8"), C("1E9E5A"), C("D63A4F"), C("14171C")
FONT = "Arial"

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
W, H = prs.slide_width, prs.slide_height
counter = [0]
IN = Inches


def rect(s, x, y, w, h, fill, shape=MSO_SHAPE.RECTANGLE, line=None):
    sh = s.shapes.add_shape(shape, x, y, w, h)
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    if line is None: sh.line.fill.background()
    else: sh.line.color.rgb = line; sh.line.width = Pt(1.25)
    sh.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE: sh.adjustments[0] = 0.08
    return sh


def text(s, x, y, w, h, runs, size=16, color=INK, bold=False, italic=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, gap=4, margin=0.04):
    """runs: str | list of paragraphs; a paragraph may be a list of (text, {overrides}) tuples."""
    tb = s.shapes.add_textbox(x, y, w, h); tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = IN(margin); tf.margin_top = tf.margin_bottom = IN(0.02)
    paras = runs if isinstance(runs, list) else [runs]
    for i, p in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph(); para.alignment = align; para.space_after = Pt(gap)
        for seg in (p if isinstance(p, list) else [(p, {})]):
            t, o = seg if isinstance(seg, tuple) else (seg, {})
            r = para.add_run(); r.text = t; f = r.font
            f.name = FONT; f.size = Pt(o.get("size", size)); f.bold = o.get("bold", bold); f.italic = o.get("italic", italic)
            f.color.rgb = o.get("color", color)
    return tb


def pic(s, name, x, y, w=None, h=None, fit=None):
    """fit=(w,h): contain inside the box, centred."""
    p = os.path.join(A, name)
    if fit:
        bw, bh = fit; iw, ih = Image.open(p).size
        sc = min(bw / iw, bh / ih); pw, ph = int(iw * sc), int(ih * sc)
        return s.shapes.add_picture(p, x + (bw - pw) // 2, y + (bh - ph) // 2, pw, ph)
    return s.shapes.add_picture(p, x, y, w, h)


def framed(s, name, x, y, w, h, border=GOLD):
    sh = pic(s, name, x, y, fit=(w, h))
    sh.line.color.rgb = border; sh.line.width = Pt(1.5)
    return sh


def notes(s, t):
    s.notes_slide.notes_text_frame.text = t


def chrome(s, title, kicker=None, dark=False):
    counter[0] += 1
    if dark: rect(s, 0, 0, W, H, C("0B0E13"))
    rect(s, 0, 0, W, IN(0.12), GOLD)
    rect(s, IN(0.6), IN(0.42), IN(0.12), IN(0.62), ORANGE)
    text(s, IN(0.85), IN(0.3), IN(11.9), IN(0.8), title, size=27, bold=True, color=WHITE if dark else BLACK)
    if kicker: text(s, IN(0.87), IN(1.0), IN(11.8), IN(0.45), kicker, size=14, italic=True, color=C("A9B0BC") if dark else GREY)
    rect(s, 0, H - IN(0.42), W, IN(0.42), BLACK)
    text(s, IN(0.6), H - IN(0.40), IN(9), IN(0.38), "V-Guard Sentinel  ·  Big Idea Tech 2026, Track 4  ·  Team Codey Tingle (TI3271)", size=10, color=GOLD, anchor=MSO_ANCHOR.MIDDLE)
    text(s, W - IN(1.6), H - IN(0.40), IN(1.0), IN(0.38), str(counter[0]), size=10, color=WHITE, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)


def stat(s, x, y, w, big, small, col=ORANGE, dark=False, bigsize=40):
    text(s, x, y, w, IN(0.8), big, size=bigsize, bold=True, color=col)
    text(s, x, y + IN(0.78), w, IN(0.8), small, size=13, color=C("C9CED6") if dark else INK)


def chip(s, x, y, w, h, t, fill, tcol=INK, size=13, bold=True):
    r = rect(s, x, y, w, h, fill, MSO_SHAPE.ROUNDED_RECTANGLE)
    tf = r.text_frame; tf.word_wrap = True; tf.margin_left = tf.margin_right = IN(0.06)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    lines = t.split("\n")
    for i, ln in enumerate(lines):
        if i: p = tf.add_paragraph(); p.alignment = PP_ALIGN.CENTER
        rr = p.add_run(); rr.text = ln; rr.font.size = Pt(size if i == 0 else size - 2); rr.font.bold = bold if i == 0 else False
        rr.font.color.rgb = tcol; rr.font.name = FONT
    return r


def arrow(s, x, y, w, h=IN(0.3), col=INK):
    a = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x, y, w, h); a.fill.solid(); a.fill.fore_color.rgb = col; a.line.fill.background(); a.shadow.inherit = False
    return a


def num_badge(s, x, y, n, col=GOLD, tcol=BLACK, d=0.5):
    c = rect(s, x, y, IN(d), IN(d), col, MSO_SHAPE.OVAL)
    tf = c.text_frame; tf.margin_left = tf.margin_right = 0; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER; r = p.add_run(); r.text = str(n)
    r.font.size = Pt(16); r.font.bold = True; r.font.color.rgb = tcol; r.font.name = FONT


def plot_layout(chart, x, y, w, h):
    """pin the chart's inner plot area (fractions of the chart frame) so overlays line up."""
    pa = chart._chartSpace.find(".//" + qn("c:plotArea"))
    lay = pa.find(qn("c:layout"))
    if lay is None:
        lay = etree.SubElement(pa, qn("c:layout")); pa.remove(lay); pa.insert(0, lay)
    for ch in list(lay): lay.remove(ch)
    ml = etree.SubElement(lay, qn("c:manualLayout"))
    for tag, val in (("c:layoutTarget", "inner"), ("c:xMode", "edge"), ("c:yMode", "edge"), ("c:x", x), ("c:y", y), ("c:w", w), ("c:h", h)):
        etree.SubElement(ml, qn(tag)).set("val", str(val))


def tick_skip(chart, n):
    ax = chart._chartSpace.find(".//" + qn("c:catAx"))
    for tag in ("c:tickLblSkip", "c:tickMarkSkip"):
        el = etree.SubElement(ax, qn(tag)); el.set("val", str(n))


# ======================= 1. TITLE =======================
s = prs.slides.add_slide(BLANK); counter[0] += 1
rect(s, 0, 0, W, H, BLACK)
pic(s, "title_right.png", IN(7.6), 0, IN(5.733), H)
ov = rect(s, IN(7.6), 0, IN(5.733), H, BLACK); ov.fill.fore_color.rgb = BLACK
ov_x = ov._element; sp = ov_x.spPr.find(qn("a:solidFill")); clr = sp.find(qn("a:srgbClr")); a = etree.SubElement(clr, qn("a:alpha")); a.set("val", "35000")
rect(s, 0, IN(5.9), W, IN(0.08), GOLD)
pic(s, "logo.png", IN(0.7), IN(0.55), h=IN(0.7))
text(s, IN(0.7), IN(1.9), IN(6.8), IN(1.1), "V-Guard Sentinel", size=50, bold=True, color=GOLD)
text(s, IN(0.7), IN(3.0), IN(6.5), IN(1.6), "The inverter already knows when the power goes. Sentinel teaches it what to keep on — and when its battery will quit.", size=22, color=WHITE)
text(s, IN(0.7), IN(4.75), IN(7), IN(0.5), "Track 4 · From Smart Products to Intelligent Products", size=15, color=GOLD)
text(s, IN(0.7), IN(6.15), IN(12), IN(0.9), ["Team Codey Tingle (TI3271)  ·  Ayush Manoj Garg · Eshan Shukla · Tanay Chaplot", "Finale · Kochi · 24 September 2026"], size=14, color=WHITE)
notes(s, "[0:00–0:20] Good morning. We're Team Codey Tingle. In the next ten minutes we'll show you Sentinel — first the idea, then the working prototype live, then what's proven and what isn't. Behind us is our simulated village; you'll see it in action in a few minutes.")

# ======================= 2. HOOK =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "10:03 pm. The battery dies — with no warning.", "Three hours into a power cut, Home 6 in our village goes dark. Home 1 has the same battery and appliances — and stays lit.")
framed(s, "v_home6_dark_c.png", IN(0.6), IN(1.6), IN(8.0), IN(5.15))
x0 = IN(9.0)
stat(s, x0, IN(1.65), IN(3.9), "85 %", "of Indian households face a power cut every day (LocalCircles, 2023)")
stat(s, x0, IN(3.35), IN(3.9), "×2 wear", "every +10 °C: lead-acid life halves with heat — the Indian summer is the battery's enemy", col=RED)
stat(s, x0, IN(5.05), IN(3.9), "≈ 1.5 %", "of V-Guard revenue goes to warranty (≈ ₹69 cr, FY24)", col=GOLD)
notes(s, "[0:20–0:50] Picture a family in Kochi. The evening power cut starts at seven. The inverter switches over in under ten milliseconds — it's fast. But nobody knows how much the battery has left, or how healthy it is. At three minutes past ten it simply dies: fridge, Wi-Fi, lights, all gone. Eighty-five percent of Indian homes face cuts daily. Heat halves lead-acid life every ten degrees. And for V-Guard, those surprise failures land in the warranty bill — about one and a half percent of revenue. The inverter is fast. The battery is blind. That's the gap.")

# ======================= 3. IDEA =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "Sentinel turns a smart inverter into an intelligent one.", "Smart products take commands. Intelligent products predict, decide and act — without the cloud.")
steps = [("CONNECTED", "app on / off", LIGHT, INK), ("SMART", "schedules · alerts · usage", C("FCB817"), INK), ("INTELLIGENT", "predicts failure · learns the home\nacts on its own — offline", GOLD, BLACK)]
for i, (t, sub, f, tc) in enumerate(steps):
    x = IN(0.9 + i * 4.15)
    chip(s, x, IN(2.2), IN(3.45), IN(2.1), f"{t}\n{sub}", f, tc, size=22)
    if i < 2: arrow(s, x + IN(3.55), IN(3.1), IN(0.5))
text(s, IN(9.2), IN(4.45), IN(3.4), IN(0.5), "← Sentinel", size=18, bold=True, color=ORANGE)
for i, (h_, b_) in enumerate([("Embedded", "a daughter-board inside new V-Guard inverters"), ("Retrofit", "a 30-minute electrician fit on the installed base"), ("Offline-first", "every core function works with zero internet")]):
    x = IN(0.9 + i * 4.15)
    num_badge(s, x, IN(5.25), i + 1)
    text(s, x + IN(0.65), IN(5.2), IN(3.3), IN(1.1), [[(h_ + "  ", {"bold": True, "size": 16}), (b_, {"size": 15})]])
notes(s, "[0:50–1:10] Our idea in one sentence: Sentinel turns V-Guard's smart inverter into an intelligent one. Today's products take commands. Sentinel predicts when the battery will fail, decides which loads to keep alive, and acts on its own — even with no internet, which in India is a feature, not a compromise. It ships two ways: built into new inverters, or retrofitted by an electrician in half an hour.")

# ======================= 4. WHERE IT SITS =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "One small box reads the battery and switches the loads.", "Nothing on the battery or the inverter is modified on the retrofit — only the negative cable passes through a shunt.")
framed(s, "v_home1_corner_c.png", IN(0.6), IN(1.6), IN(7.6), IN(5.15))
items = [("Shunt in the battery − lead", "battery current → INA228"), ("NTC on the battery post", "temperature: the #1 ageing driver"), ("CT + voltage tap on AC-OUT", "real & reactive power → ATM90E32AS"), ("4 NC contactors in the DB", "coil off = load ON, always"), ("ESP32-S3 Sentinel Core", "90 × 70 × 35 mm, powered by the battery")]
for i, (h_, b_) in enumerate(items):
    y = IN(1.7 + i * 1.0)
    num_badge(s, IN(8.55), y, i + 1, d=0.45)
    text(s, IN(9.15), y - IN(0.05), IN(3.7), IN(0.95), [[(h_, {"bold": True, "size": 15})], [(b_, {"size": 13, "color": GREY})]], gap=1)
notes(s, "[1:10–1:35] Physically, Sentinel is a box the size of a deck of cards beside the inverter. This is the 'power corner' of Home 1 in our simulation. Five touch points: a shunt in the battery's negative cable for current, a temperature probe on the battery post, a current transformer on the inverter output, four fail-safe contactors in the distribution board — and the ESP32 core itself. Gold dots are mains power, cyan is battery power, violet is Sentinel sensing.")

# ======================= 5. FOUR ENGINES =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "Four jobs, one board — all on the ESP32, no cloud needed.")
eng = [("1", "Battery health", "Predicts a replacement window — 'replace in 6–14 weeks'", GOLD), ("2", "Habit autopilot", "Keeps the fridge, lights and router alive during a cut", ORANGE),
       ("3", "Energy coach + grid shield", "Names the big appliances; logs every sag and swell", C("FCB817")), ("4", "Signed health log", "Tamper-proof record — warranty decided by evidence", LIGHT)]
for i, (n, t, b, f) in enumerate(eng):
    x = IN(0.6 + i * 3.1)
    rect(s, x, IN(1.55), IN(2.85), IN(4.2), f, MSO_SHAPE.ROUNDED_RECTANGLE)
    text(s, x + IN(0.25), IN(1.75), IN(2.4), IN(1.2), n, size=60, bold=True, color=BLACK)
    text(s, x + IN(0.25), IN(3.05), IN(2.4), IN(0.9), t, size=20, bold=True, color=BLACK)
    text(s, x + IN(0.25), IN(4.1), IN(2.4), IN(1.5), b, size=15, color=INK)
text(s, IN(0.6), IN(6.05), IN(12), IN(0.6), "Same core, same sensors, different models → the platform extends to pumps, stabilisers and water heaters.", size=14, italic=True, color=GREY)
notes(s, "[1:35–1:50] Four jobs, one board. One: battery health — a warning window, not a guess. Two: the autopilot that keeps essentials alive. Three: the energy coach and grid shield — which appliances use what, and what the grid did to your home. Four: a signed health log, so warranty is decided by evidence, not argument. Let me take them one at a time, quickly.")

# ======================= 6. ENGINE 1 =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "It gives a window, not a date: \"replace in 6–14 weeks\".", "Physics first, learning second — every step runs on the ESP32.")
chain = [("1 Hz sensing", "I · V · T", LIGHT), ("Kalman filter", "SoC · R_int", C("FCB817")), ("14 + 6 features", "per outage cycle", C("FCB817")), ("int8 CNN × 3", "28 k params · 16 KB", GOLD), ("Grade", "window, never a date", ORANGE)]
for i, (t, b, f) in enumerate(chain):
    x = IN(0.6 + i * 2.5)
    chip(s, x, IN(1.6), IN(2.1), IN(1.05), f"{t}\n{b}", f, WHITE if f == ORANGE else INK, size=15)
    if i < 4: arrow(s, x + IN(2.13), IN(1.97), IN(0.33), IN(0.3))
pic(s, "soh_band_c.png", IN(0.6), IN(2.95), fit=(IN(8.6), IN(3.85)))
stat(s, IN(9.55), IN(3.0), IN(3.3), "8.2 pt", "SoH error on 3 never-seen test batteries (synthetic data — honest, not flattering)", col=ORANGE, bigsize=34)
stat(s, IN(9.55), IN(4.55), IN(3.3), "+0.01 pt", "accuracy lost going float → int8 — it fits on the chip for free", col=GOLD, bigsize=34)
text(s, IN(9.55), IN(6.1), IN(3.4), IN(0.7), "Band is calibrated but wide today; the Kochi aging campaign narrows it.", size=12, italic=True, color=GREY)
notes(s, "[1:50–2:25] How does a small microcontroller predict battery life? Physics first. A Kalman filter turns current, voltage and temperature into charge and internal resistance. Each outage becomes 20 features the lead-acid literature says drive wear — resistance growth, heat stress, depth of discharge. A tiny int8 network — 28 thousand parameters, 16 KB of RAM — outputs a band, and we show a window: replace in 6 to 14 weeks, plan for 6. Honest numbers: on three batteries the model has never seen, the error is 8.2 points — on synthetic data. The band is calibrated but wide; real tubular aging data from the Kochi lab is what narrows it. And quantising to int8 cost us one hundredth of a point.")

# ======================= 7. ENGINE 2 — real sim trace =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "Same outage, same battery: only Home 1 keeps its fridge on.", "Battery charge through the 7–11 pm cut, straight from our simulation engine; thresholds from design doc 05.")
rows = TRACE["rows"]
cd = CategoryChartData(); cd.categories = [r["t"] for r in rows]
cd.add_series("Home 1 — with Sentinel", [r["h1"] for r in rows])
cd.add_series("Home 6 — no Sentinel", [r["h6"] for r in rows])
cd.add_series("T2 defer 55 %", [55] * len(rows)); cd.add_series("T3 shed 40 %", [40] * len(rows)); cd.add_series("cut-off 20 %", [20] * len(rows))
cx, cy, cw, ch_ = IN(0.6), IN(1.55), IN(8.9), IN(5.25)
gf = s.shapes.add_chart(XL_CHART_TYPE.LINE, cx, cy, cw, ch_, cd); chart = gf.chart
chart.has_legend = True; chart.legend.position = XL_LEGEND_POSITION.TOP; chart.legend.include_in_layout = False
chart.legend.font.size = Pt(11); chart.legend.font.name = FONT
styles = [(ORANGE, 3.5, None), (INK, 3.5, None), (C("E0A800"), 1.25, "dash"), (RED, 1.25, "dash"), (GREY, 1.25, "sysDot")]
for ser, (col, wpt, dash) in zip(chart.plots[0].series, styles):
    ser.smooth = False; ser.format.line.color.rgb = col; ser.format.line.width = Pt(wpt)
    ser.marker.style = None
    m = ser._element.get_or_add_marker(); sym = m.find(qn("c:symbol"))
    if sym is None: sym = etree.SubElement(m, qn("c:symbol"))
    sym.set("val", "none")
    if dash:
        ln = ser.format.line._get_or_add_ln(); pd = etree.SubElement(ln, qn("a:prstDash")); pd.set("val", dash)
va = chart.value_axis; va.minimum_scale = 0; va.maximum_scale = 100; va.major_unit = 20
va.has_major_gridlines = True; va.major_gridlines.format.line.color.rgb = C("E4E4E4")
va.tick_labels.font.size = Pt(11); va.tick_labels.font.name = FONT; va.format.line.fill.background()
ca = chart.category_axis; ca.tick_labels.font.size = Pt(11); ca.tick_labels.font.name = FONT
tick_skip(chart, 6)
PX, PY, PW, PH = 0.07, 0.11, 0.91, 0.77
plot_layout(chart, PX, PY, PW, PH)
n = len(rows)
def xat(clock):
    idx = [r["t"] for r in rows].index(clock)
    return cx + int(cw * (PX + PW * (idx + 0.5) / n))
def yat(v): return cy + int(ch_ * (PY + PH * (1 - v / 100)))
def callout(clock, v, label, col, dx=0.1, dy=-0.75, wdt=2.25):
    x, y = xat(clock), yat(v)
    dot = rect(s, x - IN(0.08), y - IN(0.08), IN(0.16), IN(0.16), col, MSO_SHAPE.OVAL)
    text(s, x + IN(dx), y + IN(dy), IN(wdt), IN(0.7), label, size=12, bold=True, color=col)
callout("20:25", 55, "8:24 pm · fans & TV deferred\n(T2 at 55 %)", C("B8860B"), dx=0.1, dy=-0.95)
callout("22:05", 20, "10:03 pm · Home 6 cut-off:\nfridge, router, lights OFF", RED, dx=-2.35, dy=0.15, wdt=2.4)
callout("22:40", 40, "10:37 pm · heavy sockets shed\n(T3 at 40 %)", ORANGE, dx=-1.2, dy=0.2, wdt=2.6)
x2 = IN(9.8)
stat(s, x2, IN(1.6), IN(3.1), "57 min", "Home 6 sat in the dark until mains returned at 11 pm", col=RED, bigsize=36)
stat(s, x2, IN(3.2), IN(3.1), "0 min", "Home 1's fridge, router and hall light were never off", col=GREEN, bigsize=36)
text(s, x2, IN(4.85), IN(3.1), IN(2.0), [[("Coil off = load on.", {"bold": True, "size": 15})], [("NC contactors, a hardware supervisory timer and a medical jumper: any crash or reset brings every load back.", {"size": 13, "color": GREY})]])
notes(s, "[2:25–3:00] This is the heart of it, and it isn't a drawing — it's the output of our simulation engine. Home 1 and Home 6 have the identical 150 Ah battery and identical appliances. Only Home 1 has Sentinel. At 8:24 pm Home 1 drops to 55 percent and defers the fans and TV; its curve flattens. Home 6 keeps burning everything, and at 10:03 pm hits the cut-off — fridge, router, lights, all off for 57 minutes. Home 1 sheds the heavy sockets at 40 percent and keeps its essentials on till mains returns. The rule is a readable ladder — 55 and 40 percent with hysteresis — not a black box. And every contactor is normally-closed: if Sentinel crashes, every load comes back on.")

# ======================= 8. ENGINE 3 =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "One sensor saves energy and catches a misbehaving grid.", "Both run on the metering front-end (ATM90E32AS) and the isolated voltage tap (AMC1311) — outputs of the team's own detector code.")
pic(s, "nilm_events.png", IN(0.6), IN(1.55), fit=(IN(6.1), IN(3.5)))
pic(s, "pq_dip.png", IN(6.75), IN(1.55), fit=(IN(6.1), IN(3.5)))
text(s, IN(0.7), IN(5.15), IN(5.9), IN(1.6), [[("Energy Coach  ", {"bold": True, "size": 16, "color": ORANGE}), ("123 switch-ON/OFF events found in 3 h of whole-home power; each becomes a 13-number signature. Fridge F1 0.97, iron 1.00.", {"size": 14})]])
text(s, IN(6.85), IN(5.15), IN(5.9), IN(1.6), [[("Grid Shield  ", {"bold": True, "size": 16, "color": RED}), ("a 120 ms sag to 0.55 pu measured as 0.54; a 100 ms swell to 1.15 pu as 1.16. 13 / 13 dips caught. Logged, dated, signed.", {"size": 14})]])
notes(s, "[3:00–3:25] Engine three. We added a real metering chip on the inverter output — the kind inside a smart meter. On the left, three hours of a home's power: every orange line is an appliance switching on, gold is off — 123 events, each turned into a signature so the app can ask 'what just turned on?'. On the right, the grid shield: the chip computes RMS every half cycle, catches a 120-millisecond sag and a swell, and writes them into the signed log — evidence for the owner when a fluctuation damages an appliance. We're honest about scope: big appliances, not two identical fans.")

# ======================= 9. PoC ARCHITECTURE — EMBEDDED =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "Inside the inverter, Sentinel taps what's already there.", "Our 3D proof of concept of the Embedded SKU: lid off, every part clickable, live power flow.", dark=True)
framed(s, "b_inside_c.png", IN(0.6), IN(1.55), IN(7.7), IN(5.2))
taps = [("Inverter's own shunt (I8)", "→ INA228 · battery current"), ("Mode / mains line", "→ PC817 opto · outage vote s2"), ("SG3525 charge feedback", "→ MCP4725 DAC · temperature-compensated charging"),
        ("AC-OUT rail", "→ AMC1311 + ATM90E32AS · V, P, Q"), ("4 coil outputs", "→ NC contactor panel · T1 / T2 / T3 / medical")]
for i, (h_, b_) in enumerate(taps):
    y = IN(1.65 + i * 1.02)
    num_badge(s, IN(8.6), y, i + 1, d=0.45)
    text(s, IN(9.2), y - IN(0.05), IN(3.7), IN(0.95), [[(h_, {"bold": True, "size": 15, "color": WHITE})], [(b_, {"size": 13, "color": C("C9CED6")})]], gap=1)
notes(s, "[3:25–3:45] For new V-Guard inverters Sentinel isn't a box — it's a daughter-board inside. This is our 3D proof of concept with the lid off: transformer, MOSFET bridge, changeover relay, control board, and our board on standoffs. It taps five things the inverter already has: its current shunt, its mode line, the charger's feedback node — which is how Sentinel does temperature-compensated charging, only on the embedded version — the output rail, and four coil outputs to the contactors.")

# ======================= 10. CAD =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "Designed to be built: 90 × 70 × 35 mm, HV zone fenced off.", "Mechanical drawing from our round-3 spec, and the same board as a 3D render in the simulation.", dark=True)
pic(s, "cad_sheet.png", IN(0.5), IN(1.5), fit=(IN(8.3), IN(5.35)))
framed(s, "b_board_c.png", IN(8.95), IN(1.6), IN(3.85), IN(2.55))
text(s, IN(8.95), IN(4.3), IN(3.9), IN(2.4), [[("Battery current never enters the PCB", {"bold": True, "size": 14, "color": GOLD})], [("only the shunt's millivolts do.", {"size": 13, "color": C("C9CED6")})],
                                                [("Isolation moat", {"bold": True, "size": 14, "color": GOLD})], [("AMC1311 and PC817 straddle the HV zone.", {"size": 13, "color": C("C9CED6")})],
                                                [("UL94 V-0 PC/ABS, 4× M3", {"bold": True, "size": 14, "color": GOLD})], [("DIN or screw mount beside the inverter.", {"size": 13, "color": C("C9CED6")})]], gap=2)
notes(s, "[3:45–4:00] It's designed to be built. Enclosure 90 by 70 by 35, board 80 by 60, flame-retardant plastic. Two things we'd point an engineer to: the battery's 30-plus amps never touch our board — only the shunt's millivolts do — and the mains-side sensing sits behind an isolation moat that the isolated amplifier and optocoupler straddle. On the right, the same board as a 3D render with every chip where the drawing puts it.")

# ======================= 11. SKETCH =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "And this is exactly how the bench is wired.", "Tier-0 demonstrator from prototype doc 05 — every part available from Indian distributors today.")
pic(s, "bench_sketch.png", IN(0.6), IN(1.45), fit=(IN(12.1), IN(5.5)))
notes(s, "[4:00–4:10] And the simplest version — our bench sketch. Mains through a 6-amp MCB into a Prime-class inverter, a 150 Ah tubular battery with the shunt in its negative lead, an ESP32, and three normally-closed relays for the three tiers. Flipping that MCB is our outage. Let's do exactly that, live.")

# ======================= 12. DEMO HANDOFF =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "Let's watch it happen — live.", "Sentinel Live runs offline in one HTML file. Three moments to watch for:", dark=True)
tiles = [("v_overview_outage.png", "1 · The village", "Feeder cuts at 7 pm. Watch Home 6 go dark at 10:03 while its twin stays lit."),
         ("b_transfer_slowmo.png", "2 · Flip the MCB", "Relay swings in slow motion: 8 ms gap on the scope, outage confirmed in 1.5 s."),
         ("b_failsafe_reset.png", "3 · Crash it", "Drop SoC below 40 % → the iron sheds. Reset the chip → every load comes back.")]
for i, (img, h_, b_) in enumerate(tiles):
    x = IN(0.6 + i * 4.15)
    framed(s, img, x, IN(1.7), IN(3.9), IN(2.6))
    text(s, x, IN(4.5), IN(3.9), IN(0.5), h_, size=19, bold=True, color=GOLD)
    text(s, x, IN(5.05), IN(3.9), IN(1.4), b_, size=14, color=WHITE)
notes(s, "[4:10–8:10] LIVE DEMO (about 4 minutes). Switch to Sentinel-Live.html, full screen.\n"
         "1) Village tab: press ⏭ 18:58 at 180×. Feeder drops at 19:00 — flows turn cyan, street lights go out. Click Home 1 → Power corner: point at shunt, NTC, CT, Sentinel, contactors. ⏭ 20:20: T2 deferred (bedroom dark). ⏭ 21:55: at 22:03 Home 6 goes DARK; Home 1 still lit. Press Reset MCU on Home 1: all loads back, re-shed after reboot.\n"
         "2) Inverter + Sentinel tab: switch the iron on. Click MAINS MCB → slow motion: relay swings, scope shows the 8 ms gap gold→cyan, timeline +0.0 / +8.0 ms, Sentinel confirms at ~1.5 s. Hover the board: C1 ESP32, C6 metering, C13 DAC.\n"
         "3) Drag SoC to 38 % → CH3 opens, iron goes cold; fan deferred. Reset MCU → everything back, charger reverts to factory. Restore MCB → S6 then bulk charging. Temp slider to 45 °C → setpoints drop, current derates. Verify chain → alter one byte → broken.\n"
         "Back to slides.")

# ======================= 13. EVIDENCE + HONESTY =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "What's proven, what's synthetic, and what still needs hardware.", "We'd rather you trust three honest columns than one shiny number.")
big = [("245", "automated tests, all passing"), ("6", "C modules bit-identical to Python"), ("3 %", "Kalman SoC error vs 7.2 %/week naive"), ("13 / 13", "grid dips detected")]
for i, (b, t) in enumerate(big):
    stat(s, IN(0.7 + i * 3.1), IN(1.5), IN(2.9), b, t, col=ORANGE, bigsize=38)
cols = [("PROVEN IN CODE", GOLD, ["int8 model exported + golden self-test in C", "autopilot: 50 / 50 C scenarios, zero chatter", "signed log: tamper, delete, replay caught"]),
        ("SYNTHETIC ONLY", C("FCB817"), ["SoH 8.2 pt on simulated tubular batteries", "RUL band calibrated (0.99) but wide", "NILM / PQ on synthetic streams"]),
        ("NEEDS HARDWARE / DATA", LIGHT, ["ESP32 flash + latency on silicon", "real bench: battery, CT, relays", "aging campaign → real SoH accuracy"])]
for i, (h_, f, lst) in enumerate(cols):
    x = IN(0.6 + i * 4.15)
    rect(s, x, IN(3.35), IN(3.9), IN(3.35), f, MSO_SHAPE.ROUNDED_RECTANGLE)
    text(s, x + IN(0.25), IN(3.5), IN(3.5), IN(0.5), h_, size=16, bold=True, color=BLACK)
    text(s, x + IN(0.25), IN(4.1), IN(3.5), IN(2.5), [[("▪  ", {"color": ORANGE}), (t, {})] for t in lst], size=14, gap=8)
notes(s, "[8:10–8:40] Credibility is the whole game with R&D judges, so here it is plainly. Proven in code: 245 tests, six C modules that match Python bit for bit, an int8 model that self-tests in C, and a signed log that catches tampering — you just saw it break. Synthetic only: the battery-health accuracy and the appliance numbers, because no real tubular aging data exists yet. Needs hardware: flashing to the ESP32, the physical bench, and the aging campaign. We also cut federated learning from this prototype on purpose — it's designed, not built.")

# ======================= 14. PRODUCT + COST =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "Two SKUs, one board — for 5–14 % of what one battery costs.", "Cost stated by the engines each tier enables (design decision D7), against a ₹15 k tubular battery.")
cd = CategoryChartData()
cd.categories = ["Basic board\n(E1+E2)", "+ shunt\n(standalone)", "+ Coach kit\n(E3)", "Embedded\nincrement", "Embedded\n+ Coach"]
lo = [750, 1050, 1650, 450, 850]; hi = [750, 1050, 2050, 700, 1300]
cd.add_series("from", lo); cd.add_series("up to", [h_ - l for h_, l in zip(hi, lo)])
gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_STACKED, IN(0.6), IN(1.55), IN(7.4), IN(5.2), cd); ch2 = gf.chart
ch2.has_legend = False
ch2.plots[0].gap_width = 60
for ser, col in zip(ch2.plots[0].series, [GOLD, C("E8E1CF")]):
    ser.format.fill.solid(); ser.format.fill.fore_color.rgb = col
va = ch2.value_axis; va.maximum_scale = 2500; va.minimum_scale = 0; va.major_unit = 500; va.has_major_gridlines = True
va.major_gridlines.format.line.color.rgb = C("E4E4E4"); va.tick_labels.font.size = Pt(11); va.format.line.fill.background()
va.tick_labels.number_format = '"₹"#,##0'; va.tick_labels.number_format_is_linked = False
ch2.category_axis.tick_labels.font.size = Pt(11)
plot_layout(ch2, 0.1, 0.04, 0.88, 0.8)
labels = ["₹750", "₹1,050", "₹1,650–2,050", "₹450–700", "₹850–1,300"]
for i, lab in enumerate(labels):
    x = IN(0.6) + int(IN(7.4) * (0.1 + 0.88 * (i + 0.5) / 5)) - IN(0.7)
    y = IN(1.55) + int(IN(5.2) * (0.04 + 0.8 * (1 - hi[i] / 2500))) - IN(0.38)
    text(s, x, y, IN(1.4), IN(0.35), lab, size=12, bold=True, align=PP_ALIGN.CENTER)
for i, (h_, b_) in enumerate([("Sentinel-Embedded", "Inside new V-Guard inverters. Taps the inverter's own shunt; controls the charger through a DAC with a hardware ceiling. Life-extension claims live here only."),
                              ("Sentinel-Retrofit", "Box beside any inverter. External shunt, NTC, CT and 4 fail-safe contactors. Advisory on charging, protective on loads. ≈ 2.6 mA average draw.")]):
    y = IN(1.6 + i * 2.6)
    rect(s, IN(8.35), y, IN(4.45), IN(2.35), LIGHT, MSO_SHAPE.ROUNDED_RECTANGLE)
    text(s, IN(8.6), y + IN(0.15), IN(4.0), IN(0.5), h_, size=18, bold=True, color=BLACK)
    text(s, IN(8.6), y + IN(0.7), IN(4.0), IN(1.6), b_, size=13)
notes(s, "[8:40–9:05] The product is one board sold two ways. Embedded inside new inverters, it adds 450 to 1,300 rupees. As a retrofit for the millions already installed, 750 rupees for the basic battery-and-autopilot box, up to about 2,000 with the energy coach. Against a 15,000-rupee battery that's 5 to 14 percent — for knowing when to replace it, and keeping the fridge alive when it matters.")

# ======================= 15. ROADMAP + ASK =======================
s = prs.slides.add_slide(BLANK)
chrome(s, "Three validation gates — and what we need to pass the first.")
gates = [("GATE 1 · DATASET", "6–8 months · Kochi reliability lab", "24–36 tubular batteries at 3 temperatures × 3 depths → real SoH labels and a measured life-extension number"),
         ("GATE 2 · FIELD PILOT", "6 months · 100 retrofit homes", "SoC within 3 %, ≥ 75 % RUL-window hit rate, zero unsafe sheds, fridge/AC F1 ≥ 0.8"),
         ("GATE 3 · PRODUCT", "Smart Pro family", "Embedded SKU into the inverter that already has Wi-Fi, BLE and the Smart 2.0 app")]
for i, (h_, sub, b_) in enumerate(gates):
    x = IN(0.6 + i * 4.15)
    num_badge(s, x, IN(1.55), i + 1, d=0.6)
    if i < 2: arrow(s, x + IN(0.75), IN(1.7), IN(3.25), IN(0.3), col=C("D9D9D9"))
    text(s, x, IN(2.35), IN(3.9), IN(0.45), h_, size=17, bold=True, color=ORANGE)
    text(s, x, IN(2.8), IN(3.9), IN(0.4), sub, size=13, italic=True, color=GREY)
    text(s, x, IN(3.25), IN(3.85), IN(1.5), b_, size=14)
rect(s, IN(0.6), IN(4.95), IN(12.15), IN(1.75), BLACK, MSO_SHAPE.ROUNDED_RECTANGLE)
text(s, IN(0.9), IN(5.1), IN(5.6), IN(1.5), [[("What V-Guard gains", {"bold": True, "size": 17, "color": GOLD})], [("battery replacements at the right time · warranty by evidence · a premium 'intelligent' tier · a fleet-data moat", {"size": 14, "color": WHITE})]])
text(s, IN(6.85), IN(5.1), IN(5.7), IN(1.5), [[("What we ask for", {"bold": True, "size": 17, "color": GOLD})], [("one opened Prime-series inverter + charger schematic · ESP32 bench parts · batteries and cyclers for Gate 1", {"size": 14, "color": WHITE})]])
notes(s, "[9:05–9:35] Our roadmap is written as gates, not dates. Gate one: a proper aging campaign in V-Guard's Kochi reliability lab — that's what turns our synthetic accuracy into real accuracy. Gate two: a hundred retrofit homes for six months with hard pass criteria. Gate three: the embedded version inside the Smart Pro family, which already has Wi-Fi and the app. What V-Guard gets: well-timed battery sales, evidence-based warranty, a premium tier, and data no competitor can buy. What we ask for: one opened Prime inverter with its charger schematic, the bench parts, and lab time.")

# ======================= 16. CLOSE =======================
s = prs.slides.add_slide(BLANK); counter[0] += 1
rect(s, 0, 0, W, H, BLACK)
pic(s, "v_home1_inside_c.png", IN(7.0), IN(0), fit=(IN(6.33), IN(7.5)))
ov = rect(s, IN(7.0), 0, IN(6.33), H, BLACK)
clr = ov._element.spPr.find(qn("a:solidFill")).find(qn("a:srgbClr")); etree.SubElement(clr, qn("a:alpha")).set("val", "40000")
text(s, IN(0.8), IN(1.7), IN(6.3), IN(2.6), ["Coil off means loads on.", "A window, never a date.", "Offline first, fleet second."], size=34, bold=True, color=GOLD, gap=10)
rect(s, IN(0.8), IN(4.35), IN(1.2), IN(0.06), ORANGE)
text(s, IN(0.8), IN(4.6), IN(6.0), IN(1.2), ["Thank you — we'd love your questions.", "Team Codey Tingle (TI3271)"], size=18, color=WHITE)
pic(s, "logo.png", IN(0.8), IN(6.3), h=IN(0.6))
notes(s, "[9:35–10:00] Three lines to remember. Coil off means loads on — it fails safe. A window, never a date — it's honest about uncertainty. Offline first, fleet second — it works in the village before it ever talks to the cloud. Thank you — we'd love your questions. (Appendix slides follow for Q&A.)")

# ======================= APPENDIX =======================
def appendix(title, kicker=None):
    sl = prs.slides.add_slide(BLANK); chrome(sl, title, kicker)
    t = rect(sl, W - IN(2.3), IN(0.35), IN(1.7), IN(0.4), LIGHT, MSO_SHAPE.ROUNDED_RECTANGLE)
    text(sl, W - IN(2.3), IN(0.37), IN(1.7), IN(0.38), "APPENDIX · Q&A", size=11, bold=True, color=GREY, align=PP_ALIGN.CENTER)
    return sl

s = appendix("Q&A · Firmware: two cores, no network needed.")
pic(s, "firmware_tasks.png", IN(0.6), IN(1.35), fit=(IN(12.1), IN(4.9)))
text(s, IN(0.6), IN(6.35), IN(12), IN(0.5), "Fixed int8 weights in flash · one inference per outage cycle · no training on the device · task watchdog + external supervisory timer.", size=13, italic=True, color=GREY)
notes(s, "If asked about firmware / RTOS / memory: ESP-IDF, FreeRTOS, Core 1 runs sensing, EKF, autopilot, ML, NILM, PQ, logger; Core 0 radios only. Heartbeat task feeds the external supervisory timer only when every critical task checked in.")

s = appendix("Q&A · Every part on the board, and the job it does.")
parts = [("C1", "ESP32-S3-WROOM-1 N16R8", "the brain: EKF, int8 CNN, NILM, PQ, autopilot"), ("C2", "MP2315 buck", "power from the 12 V battery (≈ 2.6 mA avg)"), ("C3", "INA228", "shunt mV + battery V; hardware coulomb counter"),
         ("C4", "NTC input", "battery temperature"), ("C5", "AMC1311", "isolated fast AC tap: outage, sag, swell"), ("C6", "ATM90E32AS", "P, Q, PF at 3 Hz for the energy coach"),
         ("C7", "ULN2003", "4 × 12 V coil drivers; coil off on reset"), ("C8", "Supervisory timer", "no heartbeat for 2 s → all coils off"), ("C9", "JP1 medical jumper", "one channel can never be shed"),
         ("C10", "DS3231 + CR2032", "time of day through outages"), ("C11", "ATECC608", "private key signs the health log"), ("C12", "PC817", "inverter mode line → outage vote s2"),
         ("C13", "MCP4725 (Embedded)", "charge-setpoint offset into SG3525 feedback"), ("C14", "USB-C · LEDs · TVS", "service and protection")]
for i, (idn, nm, role) in enumerate(parts):
    col, row = i // 7, i % 7
    x = IN(0.6 + col * 6.2); y = IN(1.4 + row * 0.75)
    chip(s, x, y, IN(0.75), IN(0.55), idn, GOLD, size=14)
    text(s, x + IN(0.9), y - IN(0.03), IN(5.2), IN(0.7), [[(nm + "  ", {"bold": True, "size": 14}), (role, {"size": 13, "color": GREY})]])
notes(s, "Parts traceability from prototype doc 03. INA228 breakouts aren't sold in India, so the Tier-0 bench uses INA226 + PZEM-004T; Tier 1 places ATM90E32AS on our own PCB.")

s = appendix("Q&A · Corrections to our own report.", "From the design register — the positions we defend.")
fixes = [("D1", "A battery shunt can't see appliances", "added a metering front-end + CT on AC-OUT"), ("D2", "Retrofit can't command the charger", "split into Embedded (controls) and Retrofit (advises)"),
         ("D3", "Float voltage isn't open-circuit voltage", "anchor SoC on charge taper; OCV only after true rest"), ("D8", "'Fail-safe' needed a mechanism", "NC contactors, pull-downs, supervisory timer, medical jumper"),
         ("D12", "Uncertainty method unspecified", "quantile heads + 3 seeds + conformal band → a window"), ("D15", "Federated learning in the prototype", "cut on purpose: designed, not built"),
         ("D16", "'Neural accelerator', 'microamp draw'", "ESP-NN vector extensions; ≈ 2.6 mA average")]
for i, (d, a_, b_) in enumerate(fixes):
    y = IN(1.6 + i * 0.72)
    chip(s, IN(0.6), y, IN(0.85), IN(0.55), d, ORANGE, WHITE, size=14)
    text(s, IN(1.65), y + IN(0.05), IN(5.0), IN(0.6), a_, size=14, bold=True)
    text(s, IN(6.8), y + IN(0.05), IN(6.0), IN(0.6), "→  " + b_, size=14, color=INK)
notes(s, "If asked 'what changed since round 2?': these are the design decisions D1–D17 in design/12. Leading with our own corrections builds trust.")

s = appendix("Q&A · Safety and standards we design to.")
pic(s, "b_shed_c.png", IN(0.6), IN(1.4), fit=(IN(6.4), IN(4.4)))
text(s, IN(7.3), IN(1.45), IN(5.5), IN(5.2), [[("Isolation", {"bold": True, "size": 16, "color": ORANGE})], [("reinforced AMC1311 barrier; HV zone behind a moat; TVS on every line", {"size": 14})],
      [("Fail-safe", {"bold": True, "size": 16, "color": ORANGE})], [("NC contactors — any fault, reset or brown-out brings loads back", {"size": 14})],
      [("Standards", {"bold": True, "size": 16, "color": ORANGE})], [("IS 13252 / IEC 62368-1 (BIS gate) · IEC 62040 UPS · IEC 61000 EMC · IEEE 1159 / IEC 61000-4-30 Class-S-like PQ · UL94 V-0 enclosure", {"size": 14})],
      [("Charging", {"bold": True, "size": 16, "color": ORANGE})], [("−24 mV/°C compensation, derate above 45 °C, stop at 58 °C, 2 s heartbeat revert to factory", {"size": 14})]], gap=4)
notes(s, "If asked about safety certification: we target IS 13252 / IEC 62368-1 as the BIS gate; PQ is 'Class-S-like', never claimed Class A.")

prs.save(OUT)
print("saved", OUT, "slides:", len(prs.slides))
