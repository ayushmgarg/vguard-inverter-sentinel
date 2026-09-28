"""Render a two-minute analytical Sentinel prototype animation.

The animation is intentionally computer-only: every house, signal, metric, and
decision is generated or replayed from the prototype's simulated path. It has
no claim of a physical experiment or a deployed fleet.
"""
from pathlib import Path
import math

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "VGuard-Sentinel-Prototype-Analysis-tanay.mp4"
W, H = 1280, 720
FPS = 15
DURATION = 120

BLACK = (0, 1, 4); WHITE = (255, 255, 255); INK = (34, 30, 31)
GOLD = (253, 195, 0); ORANGE = (243, 146, 0); LIGHT = (243, 239, 239)
GREY = (177, 177, 177); RED = (218, 53, 69); GREEN = (44, 151, 97)

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
ITALIC = "/home/tanay/.local/lib/python3.14/site-packages/matplotlib/mpl-data/fonts/ttf/DejaVuSans-Oblique.ttf"


def f(size, bold=False, italic=False):
    path = BOLD if bold else ITALIC if italic else FONT
    return ImageFont.truetype(path, size)


def txt(d, xy, s, size=22, fill=WHITE, bold=False, italic=False, anchor=None):
    d.text(xy, s, font=f(size, bold, italic), fill=fill, anchor=anchor)


def box(d, xy, fill=LIGHT, outline=None, radius=12, width=3):
    d.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width if outline else 1)


def wrap(d, x, y, width, lines, size=20, fill=WHITE, gap=8):
    yy = y
    for line in lines:
        words = line.split(); cur = ""
        for word in words:
            trial = (cur + " " + word).strip()
            if d.textlength(trial, font=f(size)) > width and cur:
                txt(d, (x, yy), cur, size, fill); yy += size + gap; cur = word
            else: cur = trial
        if cur: txt(d, (x, yy), cur, size, fill); yy += size + gap
    return yy


def header(d, title, subtitle, t):
    d.rectangle((0, 0, W, 10), fill=GOLD)
    txt(d, (65, 37), title, 38, GOLD, bold=True)
    txt(d, (67, 92), subtitle, 17, GREY, italic=True)
    txt(d, (1210, 28), "COMPUTER SIMULATION ONLY", 12, GOLD, bold=True, anchor="ra")
    d.rectangle((0, H - 46, W, H), fill=(10, 11, 14))
    txt(d, (65, H - 25), "V-Guard Sentinel · analytical prototype walkthrough · no practical experiments", 12, GREY, anchor="lm")
    txt(d, (1215, H - 25), f"{t:05.1f}s / 120.0s", 12, GOLD, anchor="rm")
    d.rectangle((0, H - 6, int(W * min(t / DURATION, 1)), 0 + H), fill=ORANGE)


def pipeline(d, y=290, active=0):
    names = ["generated\nI / V / T / load", "local\nEKF + features", "decision\nautopilot", "int8\nSoH/RUL", "dashboard\nstate.json"]
    x0, bw, gap = 65, 205, 36
    for i, name in enumerate(names):
        x = x0 + i * (bw + gap); fill = GOLD if i == active else LIGHT
        box(d, (x, y, x + bw, y + 110), fill=fill, outline=ORANGE if i == active else None)
        txt(d, (x + bw/2, y + 55), name, 18, INK, bold=True, anchor="mm")
        if i < len(names)-1: txt(d, (x + bw + 7, y + 55), "→", 30, ORANGE, bold=True, anchor="mm")


def house(d, x, y, label, soc, status, hot=False):
    roof = [(x + 15, y + 40), (x + 75, y - 16), (x + 135, y + 40)]
    d.polygon(roof, fill=ORANGE)
    d.rectangle((x + 25, y + 35, x + 125, y + 125), fill=LIGHT, outline=ORANGE, width=3)
    txt(d, (x + 75, y + 62), label, 17, INK, bold=True, anchor="mm")
    d.rectangle((x + 42, y + 82, x + 108, y + 98), fill=(220, 220, 220))
    d.rectangle((x + 42, y + 82, x + 42 + int(66 * soc), y + 98), fill=GREEN if soc > .55 else ORANGE if soc > .4 else RED)
    txt(d, (x + 75, y + 112), f"SoC {soc*100:.0f}% · {status}", 11, INK, anchor="mm")
    if hot: d.ellipse((x + 109, y + 46, x + 125, y + 62), fill=RED)


def chart(d, x, y, w, h, title, xs, ys, color=ORANGE, ymin=0, ymax=100, bands=None, thresholds=()):
    box(d, (x, y, x + w, y + h), fill=(18, 20, 24), outline=(70, 70, 70), radius=8, width=2)
    txt(d, (x + 18, y + 15), title, 16, WHITE, bold=True)
    px, py, pw, ph = x + 50, y + 55, w - 75, h - 80
    d.line((px, py + ph, px + pw, py + ph), fill=GREY, width=2)
    d.line((px, py, px, py + ph), fill=GREY, width=2)
    for val, lab in thresholds:
        yy = py + ph - int((val - ymin) / (ymax - ymin) * ph)
        d.line((px, yy, px + pw, yy), fill=RED if val <= 40 else GOLD, width=2)
        txt(d, (px + pw - 3, yy - 13), lab, 11, RED if val <= 40 else GOLD, anchor="ra")
    a = np.asarray(xs); b = np.asarray(ys)
    if bands is not None:
        lo, hi = bands
        poly = []
        for xx, vv in zip(a, hi): poly.append((px + int(xx * pw), py + ph - int((vv-ymin)/(ymax-ymin)*ph)))
        for xx, vv in zip(a[::-1], lo[::-1]): poly.append((px + int(xx * pw), py + ph - int((vv-ymin)/(ymax-ymin)*ph)))
        d.polygon(poly, fill=(99, 80, 20))
    pts = [(px + int(xx * pw), py + ph - int((vv-ymin)/(ymax-ymin)*ph)) for xx, vv in zip(a, b)]
    if len(pts) > 1: d.line(pts, fill=color, width=4, joint="curve")
    txt(d, (px, py + ph + 12), "cycle / time", 11, GREY)


def scene_frame(t):
    im = Image.new("RGB", (W, H), BLACK); d = ImageDraw.Draw(im)
    if t < 15:
        header(d, "V-Guard Sentinel", "A two-minute analytical walkthrough of the software prototype", t)
        txt(d, (65, 170), "What is working in simulation", 31, WHITE, bold=True)
        wrap(d, 68, 230, 700, ["A generated household stream is processed locally by the Sentinel pipeline. The animation follows one outage decision, one synthetic health prediction, and one simulated cluster-of-homes aggregation.", "Every visual carries the same boundary as the repository: no real battery, inverter, ESP32, home, or field experiment is behind the animation."], 21, WHITE, 11)
        pipeline(d, 450, active=min(4, int((t/15)*5)))
        return im
    if t < 35:
        header(d, "Scene 1 · Input cluster", "Different simulated homes create different electrical conditions", t)
        local = t - 15
        vals = [0.84 - .012*local, 0.62 - .009*local, 0.48 - .004*local, 0.73 - .006*local]
        states = ["grid present", "partial SoC", "outage", "hot condition"]
        for i, (v, st) in enumerate(zip(vals, states)):
            house(d, 90 + i*285, 250, f"Home {chr(65+i)}", max(.18, v), st, i == 2)
        txt(d, (640, 455), "generated 1 Hz streams", 22, GOLD, bold=True, anchor="ma")
        txt(d, (640, 500), "I · V · T · grid · P_load", 19, GREY, anchor="ma")
        d.line((175, 390, 1100, 390), fill=ORANGE, width=4)
        return im
    if t < 58:
        header(d, "Scene 2 · Local decision loop", "The outage signal becomes an auditable controller decision", t)
        local = t - 35; progress = min(local / 23, 1)
        pipeline(d, 180, active=min(4, int(progress*5)))
        chart(d, 90, 385, 610, 230, "simulated SoC during outage", np.linspace(0,1,80), 92 - 55*np.linspace(0,1,80)**1.1, color=GOLD, ymin=20, ymax=100, thresholds=((55,"restore"),(40,"shed")))
        box(d, (760, 385, 1180, 610), fill=LIGHT)
        txt(d, (790, 415), "Controller output", 22, INK, bold=True)
        rows = [("Outage vote", "2-of-3 → ON BATTERY", ORANGE), ("T1 essentials", "KEEP", GREEN), ("T2 defer", "WAIT", GOLD), ("T3 heavy load", "SHED at 40%", RED)]
        for i, (a,b,c) in enumerate(rows):
            txt(d, (790, 465+i*32), a, 15, INK, bold=True); txt(d, (1145, 465+i*32), b, 15, c, bold=True, anchor="ra")
        return im
    if t < 80:
        header(d, "Scene 3 · Synthetic health prediction", "The model produces a calibrated uncertainty band, not a false-precision date", t)
        x = np.linspace(0,1,90); true = 100 - 23*x**1.25; pred = true + 2.4*np.sin(x*11); width = 7 + 10*x
        chart(d, 60, 165, 750, 430, "SoH on independent synthetic test batteries", x, pred, color=ORANGE, ymin=65, ymax=105, bands=(pred-width,pred+width))
        d.line((110, 165+55+int((105-80)/(105-65)*(430-80)), 785, 165+55+int((105-80)/(105-65)*(430-80))), fill=RED, width=2)
        txt(d, (850, 210), "8.2 pt", 58, ORANGE, bold=True); txt(d, (850, 275), "SoH MAE", 24, WHITE, bold=True)
        wrap(d, 850, 335, 340, ["Synthetic run: 16 batteries, 3 final-test batteries.", "80% coverage improves after conformal calibration, but the interval is 34 points wide.", "Real tubular accuracy requires the planned ageing campaign."], 18, GREY, 9)
        return im
    if t < 98:
        header(d, "Scene 4 · Coach and Grid Shield", "Synthetic AC streams make the analytical path visible", t)
        x = np.linspace(0,1,180); p = 500 + 130*np.sin(x*15) + 240*(x>.35) - 180*(x>.6) + 160*(x>.78)
        chart(d, 65, 175, 560, 330, "aggregate P at simulated inverter AC output", x, p, color=GOLD, ymin=200, ymax=1000)
        x2=np.linspace(0,1,200); v=np.ones(200); v[(x2>.35)&(x2<.48)] = .55; v[(x2>.72)&(x2<.80)] = 1.15
        chart(d, 655, 175, 560, 330, "synthetic voltage event", x2, v, color=ORANGE, ymin=0.2, ymax=1.3, thresholds=((.9,"sag"),(1.1,"swell")))
        box(d, (100, 545, 1180, 625), fill=LIGHT)
        txt(d, (125, 585), "NILM event signatures → appliance cluster labels", 17, INK, bold=True)
        txt(d, (635, 585), "half-cycle RMS / FFT → PQ event record", 17, INK, bold=True)
        txt(d, (1180, 585), "hardware AFE + CT + reference meter: pending", 13, RED, bold=True, anchor="ra")
        return im
    if t < 113:
        header(d, "Scene 5 · Cluster-of-homes learning view", "The fleet picture is simulated; central learning is the current path", t)
        vals=[.75+.06*math.sin(t), .50+.08*math.sin(t*.8), .65+.05*math.cos(t), .38+.07*math.sin(t*1.2)]
        for i,v in enumerate(vals): house(d, 70+i*250, 200, f"Home {chr(65+i)}", v, "local inference")
        txt(d, (640, 370), "→", 50, ORANGE, bold=True, anchor="mm")
        box(d, (425, 430, 855, 550), fill=GOLD)
        txt(d, (640, 466), "V-Guard central training", 24, INK, bold=True, anchor="mm")
        txt(d, (640, 505), "consented, pseudonymised summaries", 16, INK, anchor="mm")
        txt(d, (950, 470), "→ model update\n(next replay)", 22, ORANGE, bold=True, anchor="lm")
        txt(d, (640, 610), "Flower / Secure Aggregation / DP-FTRL are designed but deliberately deferred.", 17, GREY, italic=True, anchor="mm")
        return im
    header(d, "Scene 6 · Evidence boundary and next gates", "A credible prototype ends by showing what still has to be measured", t)
    cols=[("IMPLEMENTED IN SOFTWARE", ["simulator + features", "EKF / autopilot / NILM / PQ", "int8 reference + host replay", "dashboard + signed-log host path"], GOLD), ("SYNTHETIC ONLY", ["SoH/RUL metrics", "household cluster", "P/Q and voltage traces", "central-learning illustration"], (247, 224, 143)), ("NEXT VALIDATION", ["tubular ageing campaign", "ESP32-S3 flash + timing", "AFE / contactor bench", "field pilot and real replacements"], LIGHT)]
    for i,(h,items,c) in enumerate(cols):
        x=55+i*405; box(d,(x,190,x+370,520),fill=c)
        txt(d,(x+20,220),h,20,INK,bold=True)
        for j,item in enumerate(items): txt(d,(x+25,285+j*43),"• "+item,17,INK)
    txt(d,(640,590),"No practical experiments are implied by this video.", 23, RED, bold=True, anchor="mm")
    return im


def main():
    writer = imageio.get_writer(str(OUT), fps=FPS, codec="libx264", quality=8, macro_block_size=1,
                                ffmpeg_log_level="error", pixelformat="yuv420p")
    try:
        for n in range(DURATION * FPS):
            writer.append_data(np.asarray(scene_frame(n / FPS)))
            if n % (FPS * 10) == 0: print(f"rendered {n/FPS:.0f}s / {DURATION}s")
    finally:
        writer.close()
    print(f"wrote {OUT} ({DURATION}s, {FPS} fps)")


if __name__ == "__main__":
    main()
