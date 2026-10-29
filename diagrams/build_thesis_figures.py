#!/usr/bin/env python3
"""
build_thesis_figures.py — Figures 4.1 to 4.4 of the thesis (Chapter 4).

  F4_1_testbed   the four machines, their sites and the overlay network
  F4_2_hybrid    provider Control Plane on the cloud machine, Data Plane on the edge machine
  F4_3_edge      both provider planes on the edge machine
  F4_4_cloud     both provider planes on the cloud machine

Review phase 2 (27 Oct 2026): port numbers removed (they are in the deployment
files under deploy/units).

Same drawing style as build_architecture.py (servers as boxes, containers and
ports inside, numbered communication), but sized for the thesis text width:
the SVG is about 690 px wide and is printed at the 15 cm text width, so 14.5 px
text ends up at about 9 pt (TAU writing tips: figure text should not be much
smaller than the 12 pt body text). No title or key inside the figure; the
LaTeX caption gives them.

The round-trip times are the medians over the 25 valid runs of the
22 October 2026 campaign (results/RUN_REGISTER-20261022.md), each run's
values measured with ten pings at its start. Machine specifications as in
Table 4.1 of the thesis. Writes thesis/<name>.svg; render_thesis_figures.sh
turns them into the PDFs the thesis includes.
"""
import json
import re
import statistics
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OUT = HERE / "thesis"

CTRL, DATA, GREY = "#1f4e79", "#D55E00", "#808080"
FILL = {"consumer": "#eeeeee", "cloud": "#dcecff", "edge": "#fff4d6", "source": "#eee6f8"}
MACHINE = {
    "consumer": ("Consumer machine", ["Contabo VPS, Germany", "4 vCPU, 7.9 GB RAM"]),
    "cloud": ("Cloud machine", ["cPouta VM, Finland", "4 vCPU, 7.7 GB RAM"]),
    "edge": ("Edge machine", ["TAU VM 1, Tampere", "4 vCPU, 7.7 GB, HDD"]),
    "source": ("Data source", ["TAU VM 2", "2 vCPU, HDD"]),
}


def campaign_rtts():
    """Median RTT per machine pair over the valid runs of the run register."""
    reg = (REPO / "results" / "RUN_REGISTER-20261022.md").read_text().split("## Failed")[0]
    runs = re.findall(r"\| (20261022T\d+-[\w-]+) \| [A-D] ", reg)
    pairs = {}
    for d in runs:
        for e in json.loads((REPO / "results" / d / "summary.json").read_text())["network_rtt_ms"]:
            if e["rtt_ms"] is not None:
                pairs.setdefault(frozenset((e["from"], e["to"])), []).append(e["rtt_ms"])
    return len(runs), {k: statistics.median(v) for k, v in pairs.items()}


class Svg:
    def __init__(self, w, h):
        self.w, self.h, self.p = w, h, []

    def add(self, s):
        self.p.append(s)

    def text(self, x, y, lines, size=14, bold=False, anchor="start", fill="#222", lh=17, first_bold=False):
        weight = ' font-weight="bold"' if bold else ""
        out = [f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" fill="{fill}"{weight}>']
        for i, ln in enumerate(lines):
            wt = ' font-weight="bold"' if (first_bold and i == 0) else ""
            out.append(f'<tspan x="{x}" dy="{0 if i == 0 else lh}"{wt}>{escape(ln)}</tspan>')
        out.append("</text>")
        self.add("".join(out))

    def box(self, x, y, w, h, fill, stroke="#666", dash=None, rx=8, sw=1.5):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def node(self, x, y, w, h, lines, grey=False, size=14.5):
        self.box(x, y, w, h, "#f4f4f4" if grey else "#ffffff", "#b0b0b0" if grey else "#555",
                 dash="5 4" if grey else None, rx=6)
        lh = 17
        self.text(x + w / 2, y + h / 2 - (len(lines) - 1) * lh / 2 + 5, lines, size=size, anchor="middle",
                  fill="#888" if grey else "#222", first_bold=not grey, lh=lh)

    def db(self, x, y):
        w, h, e = 96, 46, 7
        self.add(f'<path d="M{x},{y+e} a{w/2},{e} 0 0 1 {w},0 v{h-2*e} a{w/2},{e} 0 0 1 {-w},0 z" fill="#fafafa" stroke="#777" stroke-width="1.2"/>')
        self.add(f'<path d="M{x},{y+e} a{w/2},{e} 0 0 0 {w},0" fill="none" stroke="#777" stroke-width="1.2"/>')
        self.text(x + w / 2, y + 31, ["PostgreSQL"], size=12.5, anchor="middle")

    def arrow(self, pts, colour=CTRL, width=3.2, dash=None, both=False):
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        da = f' stroke-dasharray="{dash}"' if dash else ""
        m = {CTRL: "mc", DATA: "md", GREY: "mg"}[colour]
        st = f' marker-start="url(#{m})"' if both else ""
        self.add(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}"{da}{st} marker-end="url(#{m})"/>')

    def line(self, x1, y1, x2, y2, colour="#555", width=2, dash=None):
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" stroke-width="{width}"{da}/>')

    def label(self, x, y, lines, anchor="middle", bg=False, size=14):
        """Arrow label; y is the baseline of the first line. bg: white patch behind it."""
        if bg:
            wmax = max(len(s) for s in lines) * size * 0.56
            x0 = x - wmax / 2 if anchor == "middle" else (x - wmax if anchor == "end" else x)
            self.add(f'<rect x="{x0-4}" y="{y-size}" width="{wmax+8}" height="{16*len(lines)+6}" fill="#ffffff" rx="3"/>')
        self.text(x, y, lines, size=size, anchor=anchor, lh=16, first_bold=True)

    def legend(self, items, size=14.5):
        """Key below the drawing (review of 29 Oct 2026: arrow and line meanings in the figure,
        not only in the caption). items: (style, label); the canvas grows by the rows needed."""
        sample = {"ctrl": (CTRL, None, True), "data": (DATA, None, True), "data-dash": (DATA, "9 5", True),
                  "ctrl-dash": (CTRL, "7 5", True), "grey-dash": (GREY, "7 5", True), "link": (CTRL, None, False)}
        x, y0, row = 12, self.h + 8, 0
        self.add(f'<line x1="8" y1="{y0 - 2}" x2="{self.w - 8}" y2="{y0 - 2}" stroke="#d0d0d0" stroke-width="1"/>')
        for style, text in items:
            wtxt = len(text) * size * 0.47
            if x + 52 + wtxt > self.w - 8:
                x, row = 12, row + 1
            y = y0 + 20 + row * 26
            if style in sample:
                colour, dash, head = sample[style]
                if head:
                    self.arrow([(x, y - 5), (x + 42, y - 5)], colour, width=2.4, dash=dash)
                else:
                    self.line(x, y - 5, x + 42, y - 5, colour, 2.4)
            elif style == "site":
                self.box(x, y - 15, 42, 20, "none", "#888", dash="7 4", rx=5, sw=1.3)
            elif style == "muted":
                self.box(x, y - 15, 42, 20, "#f4f4f4", "#b0b0b0", dash="5 4", rx=5)
            elif style == "t":
                self.add(f'<text x="{x + 21}" y="{y}" font-size="{size}" font-style="italic" fill="{CTRL}" '
                         f'text-anchor="middle">t<tspan baseline-shift="sub" font-size="11.5">n</tspan></text>')
            elif style == "num":
                self.add(f'<circle cx="{x + 21}" cy="{y - 5}" r="11" fill="#333"/><text x="{x + 21}" y="{y}" '
                         f'font-size="13" font-weight="bold" fill="#fff" text-anchor="middle">n</text>')
            self.text(x + 52, y, [text], size=size, fill="#222")
            x += 52 + wtxt + 20
        self.h = int(y0 + 20 + row * 26 + 12)

    def render(self):
        mk = "".join(
            f'<marker id="{i}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4.5" markerHeight="4.5" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
            for i, c in (("mc", CTRL), ("md", DATA), ("mg", GREY)))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" font-family="Helvetica, Arial, sans-serif">'
                f'<defs>{mk}</defs><rect width="{self.w}" height="{self.h}" fill="#ffffff"/>'
                + "".join(self.p) + "</svg>\n")


def ms(v):
    return f"{v:.0f} ms"


def server_box(s, role, x, y, w, h):
    title, spec = MACHINE[role]
    s.box(x, y, w, h, FILL[role])
    s.text(x + 10, y + 24, [title], size=16, bold=True)
    s.text(x + 10, y + h - 12 - 16 * (len(spec) - 1), spec, size=13.5, fill="#333", lh=16)


def placement(arch, rtt, nruns):
    """One placement. The numbered links are explained in the caption of Figure 4.2."""
    cp, dp = {"hybrid": ("cloud", "edge"), "edge": ("edge", "edge"), "cloud": ("cloud", "cloud")}[arch]
    same = cp == dp
    r = lambda a, b: rtt[frozenset((a, b))]
    TOP = 34                         # room above the machines for the site labels
    B = 582                          # bottom of the tall boxes
    s = Svg(690, B + TOP + 8)
    s.add(f'<g transform="translate(0,{TOP})">')

    CON_X, CON_W = 10, 200
    PROV_X, PROV_W = 300, 200
    SRC_X, SRC_W = 570, 112
    NW = 180                         # node width in the consumer and provider columns
    con_x, prov_x, src_x = CON_X + 10, PROV_X + 10, SRC_X + 8
    R1, R1H = 50, 88                 # Control Plane row
    R2, R2H = 352, 80                # Data Plane / data path row
    RCV_Y = 447                      # receiver, below the application
    CB = 260                         # height of the cloud box in Hybrid
    LOW = 316                        # top of the lower boxes (edge in Hybrid, data source)

    def site(x, y, w, h, lines):
        s.box(x, y, w, h, "none", "#888", dash="7 4", rx=10, sw=1.3)
        s.text(x + 9, y + 18, lines, size=14, fill="#555", bold=True, lh=16)

    # Sites (dashed), drawn first so the machines lie on top
    site(2, -30, CON_W + 16, B + 38, ["Contabo, Germany"])
    if arch == "hybrid":
        site(292, -30, PROV_W + 16, CB + 38, ["CSC cPouta, Finland"])
        site(292, CB + 12, 396, B - CB - 4, ["Tampere University,", "Finland"])   # two lines: clear of arrow (3)
    elif arch == "edge":
        site(292, -30, 396, B + 38, ["Tampere University, Finland"])
    else:
        site(292, -30, PROV_W + 16, B + 38, ["CSC cPouta, Finland"])
        site(562, LOW - 62, SRC_W + 16, B - LOW + 70, ["Tampere", "University,", "Finland"])

    # Consumer machine
    server_box(s, "consumer", CON_X, 0, CON_W, B)
    s.node(con_x, R1, NW, R1H, ["Consumer CP", "negotiates, transfers,", "holds the EDR"])
    s.line(con_x + 48, R1 + R1H, con_x + 48, R1 + R1H + 18, "#777", 1.2)
    s.db(con_x, R1 + R1H + 18)
    s.node(con_x, R2, NW, R2H, ["Consumer app", "test cases,", "pull client"])
    s.node(con_x, RCV_Y, NW, R2H, ["Receiver", "push destination,", "logs arrivals"])

    # Provider machine(s)
    if same:
        server_box(s, cp, PROV_X, 0, PROV_W, B)
    else:
        server_box(s, cp, PROV_X, 0, PROV_W, CB)
        server_box(s, dp, PROV_X, LOW, PROV_W, B - LOW)
    s.node(prov_x, R1, NW, R1H, ["Provider CP", "catalogue, contracts,", "transfers, policy"])
    s.line(prov_x + 48, R1 + R1H, prov_x + 48, R1 + R1H + 18, "#777", 1.2)
    s.db(prov_x, R1 + R1H + 18)
    s.node(prov_x, R2, NW, R2H, ["Provider DP", "checks the token", "on every fetch"])
    s.line(prov_x + 48, R2 + R2H, prov_x + 48, R2 + R2H + 18, "#777", 1.2)
    s.db(prov_x, R2 + R2H + 18)

    # Data source
    server_box(s, "source", SRC_X, LOW, SRC_W, B - LOW)
    s.node(src_x, R2, SRC_W - 16, R2H, ["Simulator", "TC1 to TC3"])

    # Control messages (blue)
    s.arrow([(con_x + 160, R2), (con_x + 160, R1 + R1H)])
    s.label(con_x + 168, 250, ["(1)"], anchor="start", size=14)
    y2 = R1 + R1H / 2
    s.arrow([(con_x + NW, y2), (prov_x, y2)], both=True)
    s.label((con_x + NW + prov_x) / 2, y2 - 22, ["(2) DSP", f"RTT {ms(r('consumer', cp))}"], bg=True)
    s.arrow([(prov_x + 165, R1 + R1H), (prov_x + 165, R2)])
    s.label(prov_x + 157, 228 if same else 200, ["(3)", "same machine" if same else f"RTT {ms(r(cp, dp))}"],
            anchor="end", size=14)   # Hybrid: above the cloud machine's spec lines

    # Data (orange, in the direction the data move)
    y4 = R2 + R2H / 2
    s.arrow([(src_x, y4), (prov_x + NW, y4)], DATA)
    s.label((prov_x + NW + src_x) / 2, y4 - 22, ["(4)", f"RTT {ms(r(dp, 'source'))}"], bg=True)
    s.arrow([(prov_x, R2 + 26), (con_x + NW, R2 + 26)], DATA, dash="9 5")
    s.label((con_x + NW + prov_x) / 2, R2 + 4, ["(6) pull", f"RTT {ms(r('consumer', dp))}"], bg=True)
    yr = RCV_Y + R2H / 2
    s.arrow([(prov_x, R2 + 64), (225, R2 + 64), (225, yr), (con_x + NW, yr)], DATA)
    s.label(262, R2 + 96, ["(5) push", f"RTT {ms(r('consumer', dp))}"], bg=True)
    s.add("</g>")
    s.legend([("ctrl", "control message"), ("data", "data (push and source)"),
              ("data-dash", "data fetched in pull"), ("site", "site")])
    return s.render()


def testbed(rtt, nruns):
    """Machines, sites and overlay links. The caption explains the lines and the RTTs."""
    s = Svg(700, 440)
    r = lambda a, b: ms(rtt[frozenset((a, b))])

    def site(x, y, w, h, name):
        s.box(x, y, w, h, "none", "#888", dash="7 4", rx=10, sw=1.3)
        s.text(x + 10, y + 19, name if isinstance(name, list) else [name], size=14, fill="#555", bold=True, lh=16)

    def machine(role, x, y, w, h, lines):
        title, _ = MACHINE[role]
        s.box(x, y, w, h, FILL[role], "#555", rx=8)
        s.text(x + w / 2, y + 24, [title] + lines, size=14.5, anchor="middle", lh=17.5, first_bold=True)

    # Sites and machines
    site(5, 125, 210, 205, "Contabo, Germany")
    site(290, 0, 230, 190, "CSC cPouta, Finland")
    site(290, 205, 405, 210, ["Tampere University,", "Finland"])
    CON = (15, 158, 190, 160)
    CLD = (305, 32, 200, 150)
    EDG = (305, 248, 200, 158)
    SRC = (555, 248, 132, 158)
    machine("consumer", *CON, ["Contabo VPS", "4 vCPU · 7.9 GB", "consumer CP, DP,", "receiver and", "application"])
    machine("cloud", *CLD, ["CSC cPouta VM", "4 vCPU · 7.7 GB", "Cloud: provider CP, DP", "Hybrid: provider CP"])
    machine("edge", *EDG, ["TAU VM 1", "4 vCPU · 7.7 GB · HDD", "Edge: provider CP, DP", "Hybrid: provider DP"])
    machine("source", *SRC, ["TAU VM 2", "2 vCPU · 7.7 GB", "HDD", "data simulator,", "AAS, adapter"])

    def link(pts, text, at):
        s.add('<path d="M' + " L".join(f"{x},{y}" for x, y in pts) + f'" fill="none" stroke="{CTRL}" stroke-width="2.4"/>')
        s.label(at[0], at[1], [text], bg=True)

    cx2 = CON[0] + CON[2]
    sx = SRC[0] + SRC[2] / 2
    link([(cx2, 190), (CLD[0], 110)], r("consumer", "cloud"), (255, 157))
    link([(cx2, 285), (EDG[0], 330)], r("consumer", "edge"), (255, 313))
    link([(CON[0] + 95, CON[1] + CON[3]), (CON[0] + 95, 430), (sx, 430), (sx, SRC[1] + SRC[3])],
         r("consumer", "source"), (380, 435))
    link([(470, CLD[1] + CLD[3]), (470, EDG[1])], r("cloud", "edge"), (470, 203))
    link([(CLD[0] + CLD[2], 100), (sx, 100), (sx, SRC[1])], r("cloud", "source"), (560, 105))
    link([(EDG[0] + EDG[2], 330), (SRC[0], 330)], r("edge", "source"), (530, 335))

    # Test controller
    s.node(15, 20, 190, 84, ["Test controller", "(laptop): SSH to all", "machines, on no", "measured path"], grey=True, size=13.5)
    s.legend([("link", "overlay link, median RTT"), ("site", "site"), ("muted", "not on any measured path")])
    return s.render()


def main():
    nruns, rtt = campaign_rtts()
    OUT.mkdir(exist_ok=True)
    (OUT / "F4_1_testbed.svg").write_text(testbed(rtt, nruns))
    for i, arch in ((2, "hybrid"), (3, "edge"), (4, "cloud")):
        (OUT / f"F4_{i}_{arch}.svg").write_text(placement(arch, rtt, nruns))
    print(f"{nruns} runs; median RTTs:", {"-".join(sorted(k)): round(v, 1) for k, v in rtt.items()})


if __name__ == "__main__":
    main()
