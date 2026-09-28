import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import sys
OUT = sys.argv[1]
INK="#1d1d1f"; GOLD="#E0A800"; ORANGE="#F39200"; CYAN="#0E9FB8"; VIO="#8B5CF6"; RED="#D63A4F"; GREEN="#1E9E5A"
with plt.xkcd(scale=0.8, length=120, randomness=2):
    plt.rcParams["font.family"] = ["Comic Sans MS", "DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(16, 9)); fig.patch.set_facecolor("#FFFDF6"); ax.set_facecolor("#FFFDF6")
    ax.set_xlim(0, 160); ax.set_ylim(0, 90); ax.axis("off")
    def box(x, y, w, h, t, c=INK, fs=13, fc="none"):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.5", ec=c, fc=fc, lw=2.2))
        ax.text(x + w / 2, y + h / 2, t, ha="center", va="center", fontsize=fs, color=c)
    def ln(pts, c=INK, lw=2.2, ls="-"):
        xs, ys = zip(*pts); ax.plot(xs, ys, color=c, lw=lw, ls=ls)
    def arrow(p, q, c=INK):
        ax.annotate("", q, p, arrowprops=dict(arrowstyle="->", color=c, lw=2.2))
    ax.text(4, 84, "Tier-0 bench — how we wire it (prototype/05)", fontsize=22, color=INK)
    ax.text(4, 79.5, "real battery · real inverter · three relay-switched tiers · nothing on the internet", fontsize=13, color="#555")
    box(4, 58, 16, 9, "mains\nsocket", fs=12)
    box(26, 58, 12, 9, "MCB\n6 A", c=RED, fs=13)
    ax.text(26, 54.5, "flip = outage!", fontsize=12, color=RED)
    box(46, 50, 30, 20, "INVERTER\n900–1000 VA\n(Prime-class)", fs=14)
    box(46, 12, 30, 16, "12 V TUBULAR\nBATTERY 150 Ah", c=GREEN, fs=14)
    ln([(20, 62.5), (26, 62.5)], GOLD, 3); ln([(38, 62.5), (46, 62.5)], GOLD, 3)
    ax.text(39, 64.5, "AC-IN", fontsize=11, color=GOLD)
    # battery cables + shunt
    ln([(54, 28), (54, 50)], RED, 4); ax.text(50.5, 38, "+", fontsize=20, color=RED)
    ln([(68, 28), (68, 34)], INK, 4); ln([(68, 40), (68, 50)], INK, 4)
    box(64.5, 34, 7, 6, "SHUNT", c=ORANGE, fs=10)
    ax.text(72.5, 29.5, "500 A / 75 mV\nin the − lead", fontsize=11, color=ORANGE)
    # ESP32 + helpers
    box(96, 22, 26, 21, "ESP32-S3\n(Sentinel)\nEKF · int8 CNN\nautopilot · NILM", c=VIO, fs=13)
    box(126, 36, 16, 6, "INA226", c=VIO, fs=11); box(126, 28, 16, 6, "DS3231 RTC", c=VIO, fs=11)
    box(126, 20, 16, 6, "ULN2003 + 555", c=VIO, fs=11)
    ln([(71.5, 37), (96, 37)], VIO, 1.8, "--"); ax.text(79, 38.5, "Kelvin mV", fontsize=11, color=VIO)
    ln([(76.5, 16), (88, 16), (88, 27), (96, 27)], VIO, 1.8, "--"); ax.text(77, 12.5, "NTC on battery post", fontsize=11, color=VIO)
    ln([(122.4, 39), (126, 39)], VIO, 1.8); ln([(122.4, 31), (126, 31)], VIO, 1.8); ln([(122.4, 23), (126, 23)], VIO, 1.8)
    # AC-OUT, PZEM, relays, loads
    ln([(76, 62.5), (94, 62.5)], CYAN, 3); ax.text(78, 64.5, "AC-OUT", fontsize=11, color=CYAN)
    box(94, 58.5, 13, 8, "PZEM\n+ CT", c=CYAN, fs=11)
    ln([(107, 62.5), (112, 62.5)], CYAN, 3)
    ln([(112, 74), (112, 51)], CYAN, 3)
    for y, lab, ld, col in [(74, "RELAY 1 (NC)", "LED bulb · charger · router   T1 keep", GREEN), (62.5, "RELAY 2 (NC)", "table fan · 100 W bulb   T2 defer", GOLD), (51, "RELAY 3 (NC)", "500 W iron / heater   T3 shed", ORANGE)]:
        ln([(112, y), (116, y)], CYAN, 3); box(116, y - 3, 17, 6, lab, c=col, fs=10)
        ax.text(135, y - 0.7, ld, fontsize=11, color=col)
    ln([(142.4, 23), (152, 23), (152, 44.5), (114, 44.5), (114, 51)], RED, 1.8, "--")
    ax.text(124, 13.5, "coil drive to relays · coil off = load ON", fontsize=12, color=RED)
    ln([(100.5, 43.4), (100.5, 58.1)], VIO, 1.8, "--"); ax.text(92.5, 50, "UART", fontsize=11, color=VIO)
    ax.text(4, 5, "Reset the ESP32 while T3 is shed → relay 3 re-closes in about a second.", fontsize=14, color=INK)
fig.savefig(OUT, dpi=150, facecolor=fig.get_facecolor())
