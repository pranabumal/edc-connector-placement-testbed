#!/usr/bin/env python3
"""
push-report-charts.py <out-dir> hybrid=<run-dir> edge=<run-dir> cloud=<run-dir>

Charts for a comparison report of PUSH runs (test cases tc1, tc2, tc3), one run
per architecture, read from each run's summary.json. Writes SVG files into
<out-dir> (standard library only; render to PNG with a browser if needed):

  fig1-transfer-times.svg   every transfer as a dot, per test case and
                            architecture, with the median and its 95 % bootstrap
                            confidence interval; the first transfer is hollow
  fig2-phases.svg           where one transfer's time goes: median of the four
                            phases, stacked, per test case and architecture
  fig3-phase-spread.svg     spread of each phase (min, quartiles, max)
  fig4-sequence.svg         transfer time in the order the transfers were made
"""
import json
import random
import statistics as st
import sys
from html import escape
from pathlib import Path

ARCHS = [("hybrid", "Hybrid", "#0072B2"), ("edge", "Edge", "#E69F00"), ("cloud", "Cloud", "#009E73")]
TCS = [("tc1", "TC1: control signal, 272 B"), ("tc2", "TC2: sensor batch, 9.6 KB"), ("tc3", "TC3: video frame, 474 KB")]
PHASES = [("request_to_provider", "Request → provider Control Plane", "#4C566A"),
          ("provider_to_dp", "Provider Control Plane → Data Plane", "#5E9FB5"),
          ("dp_to_source", "Data Plane → data source", "#E0B04F"),
          ("source_to_received", "Source → consumer's endpoint", "#BF616A")]
FONT = 'font-family="Helvetica, Arial, sans-serif"'


def median_ci(values, n=4000):
    rng = random.Random(1)
    meds = sorted(st.median(rng.choices(values, k=len(values))) for _ in range(n))
    return st.median(values), meds[int(0.025 * n)], meds[int(0.975 * n)]


def quartiles(v):
    v = sorted(v)
    q = st.quantiles(v, n=4, method="inclusive")
    return v[0], q[0], q[1], q[2], v[-1]


class Svg:
    def __init__(self, w, h, title):
        self.w, self.h = w, h
        self.p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" {FONT}>',
                  f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
                  f'<text x="20" y="30" font-size="19" font-weight="bold" fill="#222">{escape(title)}</text>']

    def text(self, x, y, s, size=13, anchor="start", fill="#333", bold=False, rotate=None):
        w = ' font-weight="bold"' if bold else ""
        r = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
        self.p.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{fill}"{w}{r}>{escape(str(s))}</text>')

    def line(self, x1, y1, x2, y2, stroke="#333", width=1, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.p.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{width}"{d}/>')

    def rect(self, x, y, w, h, fill, stroke="none", opacity=1):
        self.p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" opacity="{opacity}"/>')

    def circle(self, x, y, r, fill, stroke="none", opacity=1, sw=1.5):
        self.p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" opacity="{opacity}"/>')

    def save(self, path):
        Path(path).write_text("".join(self.p) + "</svg>\n")


def y_axis(s, x0, x1, y0, y1, ymax, step, label=None):
    """Horizontal grid lines and tick labels; returns the value → y function."""
    def fy(v):
        return y1 - (v / ymax) * (y1 - y0)
    v = 0
    while v <= ymax + 1e-9:
        s.line(x0, fy(v), x1, fy(v), "#dddddd" if v else "#555", 1)
        s.text(x0 - 8, fy(v) + 4, f"{v:,.0f}", 12, "end", "#555")
        v += step
    if label:
        s.text(x0 - 46, (y0 + y1) / 2, label, 12.5, "middle", "#333", rotate=-90)
    return fy


def nice_max(v, step):
    return (int(v / step) + 1) * step


def fig1(data, out):
    s = Svg(1500, 620, "One push transfer, request to received: every transfer, median and 95 % confidence interval")
    pw, x0, y0, y1 = 430, 90, 80, 520
    for i, (tc, label) in enumerate(TCS):
        px = x0 + i * (pw + 40)
        allv = [v for a, _, _ in ARCHS for v in data[a][tc]["r2r"]]
        step = 100 if max(allv) <= 1000 else 200
        ymax = nice_max(max(allv), step)
        fy = y_axis(s, px, px + pw, y0, y1, ymax, step, "milliseconds" if i == 0 else None)
        s.text(px + pw / 2, y0 - 22, label, 15, "middle", "#222", bold=True)
        if tc == "tc1":
            s.line(px, fy(100), px + pw, fy(100), "#B00020", 1.5, "6 4")
            s.text(px + pw - 4, fy(100) + 16, "100 ms criterion", 12, "end", "#B00020")
        rng = random.Random(7)
        for j, (a, name, colour) in enumerate(ARCHS):
            cx = px + pw * (j + 0.5) / 3
            vals = data[a][tc]["r2r"]
            for k, v in enumerate(vals):
                jx = cx + rng.uniform(-38, 38)
                if k == 0:
                    s.circle(jx, fy(v), 5, "#ffffff", colour, 1, 2)
                else:
                    s.circle(jx, fy(v), 4.5, colour, opacity=0.55)
            med, lo, hi = median_ci(vals)
            s.rect(cx - 58, fy(hi), 116, fy(lo) - fy(hi), colour, opacity=0.18)
            s.line(cx - 58, fy(med), cx + 58, fy(med), "#111", 2.5)
            s.text(cx + 64, fy(med) + 4, f"{med:.0f}", 13, "start", "#111", bold=True)
            s.text(cx, y1 + 22, name, 14, "middle", "#222", bold=True)
            s.text(cx, y1 + 40, f"[{lo:.0f}–{hi:.0f}]", 12, "middle", "#555")
    s.text(90, 590, "Dots: the 20 transfers of a run (hollow: the first one). Black line and number: median. Shaded band and brackets: "
                    "95 % bootstrap confidence interval of the median.", 12.5, fill="#444")
    s.save(out / "fig1-transfer-times.svg")


def fig2(data, out):
    s = Svg(1500, 560, "Where one transfer's time goes: median of each phase")
    x0, bar_h, gap = 250, 30, 10
    xmax = 800
    x1 = 1320
    def fx(v):
        return x0 + v / xmax * (x1 - x0)
    y = 78
    for v in range(0, xmax + 1, 100):
        s.line(fx(v), y - 8, fx(v), y + 3 * (3 * (bar_h + gap) + 34) - 20, "#dddddd" if v else "#555")
        s.text(fx(v), y + 3 * (3 * (bar_h + gap) + 34) - 2, f"{v}", 12, "middle", "#555")
    s.text((x0 + x1) / 2, y + 3 * (3 * (bar_h + gap) + 34) + 18, "milliseconds (sum of the phase medians)", 12.5, "middle")
    for tc, label in TCS:
        s.text(20, y + 14, label.split(":")[0], 15, bold=True, fill="#222")
        s.text(20, y + 32, label.split(": ")[1], 12.5, fill="#555")
        for a, name, _ in ARCHS:
            s.text(x0 - 10, y + bar_h / 2 + 5, name, 13.5, "end", "#222")
            x = 0
            for p, _, colour in PHASES:
                v = st.median(data[a][tc]["phases"][p])
                s.rect(fx(x), y, fx(x + v) - fx(x), bar_h, colour, "#ffffff")
                if fx(x + v) - fx(x) > 26:
                    s.text((fx(x) + fx(x + v)) / 2, y + bar_h / 2 + 4.5, f"{v:.0f}", 12.5, "middle", "#ffffff", bold=True)
                x += v
            s.text(fx(x) + 8, y + bar_h / 2 + 5, f"{x:.0f}", 13, "start", "#111", bold=True)
            y += bar_h + gap
        y += 34
    lx = 250
    for _, label, colour in PHASES:
        s.rect(lx, 44, 16, 16, colour)
        s.text(lx + 22, 57, label, 13)
        lx += 34 + 7.2 * len(label)
    s.save(out / "fig2-phases.svg")


def fig3(data, out):
    s = Svg(1500, 660, "Spread of each phase over the 20 transfers (range, quartiles, median)")
    pw, x0, y0, y1 = 430, 90, 96, 540
    for i, (tc, label) in enumerate(TCS):
        px = x0 + i * (pw + 40)
        allv = [v for a, _, _ in ARCHS for p, _, _ in PHASES for v in data[a][tc]["phases"][p]]
        step = 100 if max(allv) <= 800 else 200
        fy = y_axis(s, px, px + pw, y0, y1, nice_max(max(allv), step), step, "milliseconds" if i == 0 else None)
        s.text(px + pw / 2, y0 - 34, label, 15, "middle", "#222", bold=True)
        for k, (p, plabel, _) in enumerate(PHASES):
            gx = px + pw * (k + 0.5) / 4
            for j, (a, _, colour) in enumerate(ARCHS):
                cx = gx + (j - 1) * 26
                lo, q1, med, q3, hi = quartiles(data[a][tc]["phases"][p])
                s.line(cx, fy(lo), cx, fy(hi), colour, 1.5)
                s.rect(cx - 9, fy(q3), 18, max(fy(q1) - fy(q3), 1.5), colour, opacity=0.45)
                s.line(cx - 9, fy(med), cx + 9, fy(med), "#111", 2.2)
            short = ["Request →", "provider CP"], ["Provider", "CP → DP"], ["DP →", "source"], ["Source →", "endpoint"]
            s.text(gx, y1 + 20, short[k][0], 12.5, "middle", "#222")
            s.text(gx, y1 + 36, short[k][1], 12.5, "middle", "#222")
    lx = 90
    for _, name, colour in ARCHS:
        s.rect(lx, 600, 16, 16, colour, opacity=0.6)
        s.text(lx + 22, 613, name, 13)
        lx += 100
    s.text(lx + 20, 613, "Thin line: fastest to slowest transfer. Box: middle half of the transfers. Black line: median.", 12.5, fill="#444")
    s.save(out / "fig3-phase-spread.svg")


def fig4(data, out):
    s = Svg(1500, 600, "Transfer time in the order the transfers were made")
    pw, x0, y0, y1 = 430, 90, 80, 500
    for i, (tc, label) in enumerate(TCS):
        px = x0 + i * (pw + 40)
        allv = [v for a, _, _ in ARCHS for v in data[a][tc]["r2r"]]
        step = 100 if max(allv) <= 1000 else 200
        fy = y_axis(s, px, px + pw, y0, y1, nice_max(max(allv), step), step, "milliseconds" if i == 0 else None)
        s.text(px + pw / 2, y0 - 22, label, 15, "middle", "#222", bold=True)
        n = max(len(data[a][tc]["r2r"]) for a, _, _ in ARCHS)
        def fx(k):
            return px + 14 + k * (pw - 28) / (n - 1)
        for k in range(0, n, 5):
            s.text(fx(k), y1 + 18, k + 1, 12, "middle", "#555")
        s.text(fx(n - 1), y1 + 18, n, 12, "middle", "#555")
        s.text(px + pw / 2, y1 + 38, "transfer number", 12.5, "middle")
        for a, _, colour in ARCHS:
            v = data[a][tc]["r2r"]
            pts = " ".join(f"{fx(k):.1f},{fy(x):.1f}" for k, x in enumerate(v))
            s.p.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="2" opacity="0.9"/>')
            for k, x in enumerate(v):
                s.circle(fx(k), fy(x), 3.2, colour)
    lx = 90
    for _, name, colour in ARCHS:
        s.line(lx, 570, lx + 26, 570, colour, 3)
        s.text(lx + 32, 575, name, 13)
        lx += 110
    s.save(out / "fig4-sequence.svg")


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    runs = dict(a.split("=", 1) for a in sys.argv[2:])
    data = {}
    for a, _, _ in ARCHS:
        summary = json.loads((Path(runs[a]) / "summary.json").read_text())
        data[a] = {}
        for tc, _ in TCS:
            recs = summary["test_cases"][tc]["records"]
            data[a][tc] = {"r2r": [r["request_to_received_ms"] for r in recs],
                           "phases": {p: [r["phases_ms"][p] for r in recs if r.get("phases_ms")] for p, _, _ in PHASES}}
    for f in (fig1, fig2, fig3, fig4):
        f(data, out)
    print("Wrote", ", ".join(sorted(p.name for p in out.glob("fig*.svg"))))


if __name__ == "__main__":
    main()
