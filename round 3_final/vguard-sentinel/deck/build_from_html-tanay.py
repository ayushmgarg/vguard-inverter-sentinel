"""Convert the div-based deck storyboard into a PowerPoint.

The HTML is the source of truth for wording and evidence labels.  This keeps
the presentation reviewable in a browser before it is rendered to PPTX.
"""
from html.parser import HTMLParser
from pathlib import Path
import sys

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "storyboard-tanay.html"
OUT = ROOT / "VGuard-Sentinel-Finale-Deck-tanay.pptx"
ASSETS = ROOT / "assets"

GOLD = RGBColor(0xFD, 0xC3, 0x00)
ORANGE = RGBColor(0xF3, 0x92, 0x00)
BLACK = RGBColor(0x00, 0x01, 0x04)
INK = RGBColor(0x22, 0x1E, 0x1F)
GREY = RGBColor(0x6C, 0x75, 0x7D)
LIGHT = RGBColor(0xF3, 0xEF, 0xEF)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)


class Node:
    def __init__(self, tag="root", attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children = []
        self.data = []

    def text(self):
        bits = list(self.data)
        for c in self.children:
            bits.append(c.text())
        return " ".join("".join(bits).split())

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()

    def find(self, tag=None, cls=None):
        found = []
        for c in self.children:
            if (tag is None or c.tag == tag) and (cls is None or c.has_class(cls)):
                found.append(c)
            found.extend(c.find(tag, cls))
        return found


class TreeParser(HTMLParser):
    VOID = {"img", "br", "meta", "link", "input", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID and len(self.stack) > 1:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                return

    def handle_data(self, data):
        self.stack[-1].data.append(data)


def rect(slide, x, y, w, h, fill, line=None):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    s.fill.solid(); s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
    return s


def text(slide, x, y, w, h, value, size=16, color=INK, bold=False,
         italic=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame; tf.clear(); tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(.06)
    tf.margin_top = tf.margin_bottom = Inches(.03)
    p = tf.paragraphs[0]; p.alignment = align
    r = p.add_run(); r.text = value; r.font.name = "Arial"; r.font.size = Pt(size)
    r.font.bold = bold; r.font.italic = italic; r.font.color.rgb = color
    return tb


def add_bullets(slide, x, y, w, h, items, size=15, color=INK):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame; tf.clear(); tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(.05)
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(6)
        r = p.add_run(); r.text = "▪  " + item; r.font.name = "Arial"; r.font.size = Pt(size); r.font.color.rgb = color
    return tb


def add_image(slide, src, x, y, w, h=None):
    path = ROOT / src if not str(src).startswith("/") else Path(src)
    if not path.exists():
        return
    kwargs = {"width": w}
    if h is not None:
        kwargs["height"] = h
    slide.shapes.add_picture(str(path), x, y, **kwargs)


def cards(slide, nodes, x, y, w, h, columns):
    gap = Inches(.16); cw = (w - gap * (columns - 1)) / columns
    for i, n in enumerate(nodes):
        col = i % columns; row = i // columns
        rows = (len(nodes) + columns - 1) // columns
        ch = (h - gap * (rows - 1)) / rows
        xx = x + col * (cw + gap); yy = y + row * (ch + gap)
        fill = GOLD if n.has_class("gold") else LIGHT
        rect(slide, xx, yy, cw, ch, fill)
        rect(slide, xx, yy, Inches(.08), ch, ORANGE)
        hs = n.find("h3"); ps = n.find("p")
        title = hs[0].text() if hs else ""
        body = "\n".join(p.text() for p in ps)
        text(slide, xx + Inches(.18), yy + Inches(.13), cw - Inches(.28), Inches(.38), title, size=16, bold=True)
        text(slide, xx + Inches(.18), yy + Inches(.62), cw - Inches(.28), ch - Inches(.72), body, size=12)


def footer(slide, number, dark=False):
    col = RGBColor(0xBB, 0xBB, 0xBB) if dark else GREY
    text(slide, Inches(.6), Inches(7.18), Inches(10.7), Inches(.2), "V-Guard Sentinel · Team Codey Tingle (TI3271) · computer simulation only", size=9, color=col)
    text(slide, Inches(12.1), Inches(7.18), Inches(.5), Inches(.2), str(number), size=9, color=col, align=PP_ALIGN.RIGHT)


def render_slide(prs, node, number):
    kind = node.attrs.get("data-kind", "bullets")
    dark = node.has_class("dark")
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    rect(slide, 0, 0, prs.slide_width, prs.slide_height, BLACK if dark else WHITE)
    if not dark:
        rect(slide, 0, 0, prs.slide_width, Inches(.10), GOLD)

    sim = node.find("div", "simulation")
    if sim:
        text(slide, Inches(10.2), Inches(.2), Inches(2.4), Inches(.3), sim[0].text(), size=9, color=GOLD if dark else ORANGE, bold=True, align=PP_ALIGN.RIGHT)
    hs = node.find("h1"); title = hs[0].text() if hs else ""
    if kind == "title":
        text(slide, Inches(.65), Inches(1.65), Inches(12), Inches(1.8), title, size=52 if number == 1 else 38, color=GOLD, bold=True)
        lead = node.find("p", "lead")
        if lead: text(slide, Inches(.65), Inches(3.45), Inches(11), Inches(1.2), lead[0].text(), size=23 if number == 1 else 19, color=WHITE)
        meta = node.find("p", "meta")
        if meta: text(slide, Inches(.65), Inches(6.25), Inches(11), Inches(.55), meta[0].text(), size=12, color=WHITE)
        rect(slide, 0, Inches(5.92), prs.slide_width, Inches(.08), GOLD)
        footer(slide, number, dark=True)
        return

    rect(slide, Inches(.6), Inches(.45), Inches(.10), Inches(.68), ORANGE)
    text(slide, Inches(.85), Inches(.36), Inches(10.8), Inches(.55), title, size=28, color=INK, bold=True)
    kick = node.find("div", "kicker")
    if kick: text(slide, Inches(.87), Inches(1.02), Inches(11.3), Inches(.42), kick[0].text(), size=12, color=GREY, italic=True)

    images = node.find("img")
    srcs = [im.attrs.get("src", "") for im in images]
    card_nodes = node.find("div", "card")
    metric_nodes = node.find("div", "metric")
    notes = node.find("p", "note")
    y = Inches(1.50)

    if kind == "cards":
        cards(slide, card_nodes, Inches(.65), y, Inches(12.0), Inches(5.35), 4 if len(card_nodes) >= 4 else 3)
    elif kind == "metrics":
        if srcs: add_image(slide, srcs[0], Inches(4.35), y, Inches(4.7), Inches(2.15))
        for i, m in enumerate(metric_nodes):
            rect(slide, Inches(.8), Inches(3.65 + i * .68), Inches(11.7), Inches(.52), LIGHT)
            rect(slide, Inches(.8), Inches(3.65 + i * .68), Inches(.07), Inches(.52), ORANGE)
            text(slide, Inches(1.0), Inches(3.74 + i * .68), Inches(2.2), Inches(.25), m.text(), size=12, bold=True)
    elif kind == "cluster":
        homes = ["Home A", "Home B", "Home C"]
        for i, label in enumerate(homes):
            x = Inches(1.0 + i * 2.35)
            rect(slide, x, Inches(2.0), Inches(1.55), Inches(.95), LIGHT, ORANGE)
            text(slide, x, Inches(2.28), Inches(1.55), Inches(.28), label + "\nsynthetic", size=12, bold=True, align=PP_ALIGN.CENTER)
        text(slide, Inches(8.0), Inches(2.05), Inches(3.0), Inches(.9), "V-Guard central training\nconsented summaries", size=16, color=INK, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        rect(slide, Inches(7.6), Inches(1.85), Inches(3.8), Inches(1.3), GOLD)
        text(slide, Inches(7.8), Inches(2.05), Inches(3.4), Inches(.9), "V-Guard central training\nconsented summaries", size=16, color=INK, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        for x in (Inches(2.6), Inches(4.95), Inches(7.15), Inches(11.4)):
            text(slide, x, Inches(2.25), Inches(.45), Inches(.35), "→", size=25, color=ORANGE, bold=True, align=PP_ALIGN.CENTER)
        cards(slide, card_nodes, Inches(.7), Inches(4.2), Inches(11.9), Inches(2.0), 3)
    elif kind in ("two-image", "image-side"):
        if srcs:
            for i, src in enumerate(srcs[:2]): add_image(slide, src, Inches(.7 + i * 6.25), y, Inches(5.8), Inches(2.35))
        lists = node.find("ul")
        for i, ul in enumerate(lists[:2]):
            items = [li.text() for li in ul.find("li")]
            add_bullets(slide, Inches(.75 + i * 6.25), Inches(4.05), Inches(5.75), Inches(2.2), items, size=12)
        if kind == "image-side" and card_nodes:
            cards(slide, card_nodes, Inches(8.0), Inches(1.55), Inches(4.5), Inches(4.6), 1)
    elif kind == "image-bottom":
        if srcs: add_image(slide, srcs[0], Inches(.7), y, Inches(11.9), Inches(2.65))
        lists = node.find("ul")
        items = [li.text() for ul in lists for li in ul.find("li")]
        if items: add_bullets(slide, Inches(.85), Inches(4.38), Inches(11.5), Inches(1.8), items, size=13)
        if notes: text(slide, Inches(.8), Inches(5.75), Inches(11.7), Inches(.75), notes[0].text(), size=12, color=INK)
    elif kind == "bullets":
        lists = node.find("ul")
        for i, ul in enumerate(lists[:2]):
            items = [li.text() for li in ul.find("li")]
            add_bullets(slide, Inches(.8 + i * 6.15), Inches(1.62), Inches(5.7), Inches(4.8), items, size=14)
        if notes: text(slide, Inches(.8), Inches(5.9), Inches(11.6), Inches(.7), notes[0].text(), size=12, color=INK)

    footer(slide, number)


def main():
    parser = TreeParser(); parser.feed(HTML.read_text(encoding="utf-8"))
    deck = parser.root.find("div", "deck")[0]
    slides = deck.find("div", "slide")
    prs = Presentation(); prs.slide_width = Inches(13.333); prs.slide_height = Inches(7.5)
    for i, node in enumerate(slides, 1): render_slide(prs, node, i)
    prs.save(OUT)
    print(f"converted {HTML.name} -> {OUT.name} ({len(slides)} slides)")


if __name__ == "__main__":
    main()
