#!/usr/bin/env python3
"""
build_sequence_figures.py — Figures 4.5 and 4.6 of the thesis (Section 4.4).

  F4_5_push_sequence   one push transfer (HttpData-PUSH), with the timestamps t0..t4
                       of the push phases (Equation 3.2 of the thesis)
  F4_6_pull_sequence   one pull transfer (HttpData-PULL): setup once, then repeated
                       fetches with the token, then the end of access

Review of 29 Oct 2026: the earlier Mermaid versions were printed at about 7 pt after
scaling to the text width. These are drawn at the printed size in the style of
Figures 4.1-4.4 (build_thesis_figures.py): 690 px = the 15 cm text width, so 15.5 px
text prints at about 9.5 pt (TAU writing tips: figure text not much smaller than the
12 pt body text). Control messages blue, data orange, refusals grey; replies dashed.
The numbers in the circles are the steps the text of Section 4.4 refers to.
Writes thesis/<name>.svg; render_thesis_figures.sh turns them into PDFs.
"""
from html import escape

from build_thesis_figures import CTRL, DATA, GREY, FILL, OUT, Svg

W = 690
FS = 15.5          # message labels
HS = 15.5          # lane headers (bold)
ROW = 44           # one single-line message (label clear of the circles of the row above)
BAND_T = 30        # band title row


class Seq:
    def __init__(self, lanes):
        """lanes: list of (key, [header lines], x, fill)."""
        self.lanes = {k: (lines, x, fill) for k, lines, x, fill in lanes}
        self.order = [k for k, *_ in lanes]
        self.ops = []           # (kind, args) in drawing order, laid out top to bottom
        self.y = 70             # below the headers
        self.bands = []

    def x(self, k):
        return self.lanes[k][1]

    def band(self, title):
        if self.bands:
            self.bands[-1][2] = self.y
        self.bands.append([title, self.y, None])
        self.y += BAND_T

    def msg(self, a, b, label, num=None, colour=CTRL, reply=False, both=False, tmark=None, tmark_at="end"):
        lines = label if isinstance(label, list) else [label]
        self.y += 16 * (len(lines) - 1)
        self.y += ROW - 10
        self.ops.append(("msg", dict(a=a, b=b, y=self.y, lines=lines, num=num, colour=colour, reply=reply,
                                      both=both, tmark=tmark, tmark_at=tmark_at)))
        self.y += 12

    def note(self, text):
        self.y += ROW - 8
        self.ops.append(("note", dict(y=self.y, text=text)))
        self.y += 8

    def render(self, legend=None):
        self.bands[-1][2] = self.y + 10
        h = int(self.y + 22)
        s = Svg(W, h)
        # bands
        for title, y0, y1 in self.bands:
            s.box(4, y0 + 4, W - 8, y1 - y0 - 4, "#f2f5f9", "#c8d0da", rx=6, sw=1)
        # lifelines and headers
        for k in self.order:
            lines, x, fill = self.lanes[k]
            s.line(x, 56, x, h - 10, "#9a9a9a", 1.4, dash="4 4")
            bw = 104
            s.box(x - bw / 2, 6, bw, 50, fill, "#555", rx=6)
            s.text(x, 26, lines, size=HS, bold=True, anchor="middle", lh=17)
        # band titles, on a patch of the band colour so the lifelines do not cross them
        for title, y0, y1 in self.bands:
            s.add(f'<rect x="8" y="{y0 + 8}" width="{len(title) * 14.5 * 0.58 + 10}" height="21" fill="#f2f5f9"/>')
            s.text(12, y0 + 23, [title], size=14.5, bold=True, fill="#3a4a5c")
        # messages
        for kind, o in self.ops:
            if kind == "note":
                wn = len(o["text"]) * FS * 0.53
                s.add(f'<rect x="{W / 2 - wn / 2 - 6}" y="{o["y"] - 15}" width="{wn + 12}" height="21" fill="#f2f5f9"/>')
                s.text(W / 2, o["y"], [o["text"]], size=FS, anchor="middle", fill="#333")
                continue
            xa, xb, y = self.x(o["a"]), self.x(o["b"]), o["y"]
            dash = "7 5" if o["reply"] else None
            s.arrow([(xa, y), (xb, y)], o["colour"], width=2.4, dash=dash, both=o["both"])
            # label above the arrow, centred, on a white patch so lifelines do not cross it
            mid = (xa + xb) / 2
            n = len(o["lines"])
            wmax = max(len(t) for t in o["lines"]) * FS * 0.53
            top = y - 14 - 16 * n
            s.add(f'<rect x="{mid - wmax / 2 - 4}" y="{top + 1}" width="{wmax + 8}" height="{16 * n + 2}" '
                  f'fill="#ffffff" fill-opacity="0.92" rx="3"/>')
            s.text(mid, top + 14, o["lines"], size=FS, anchor="middle", lh=16, fill="#222")
            if o["num"] is not None:
                # on the sender's lifeline; for a two-way message, beside it, clear of the arrowhead
                cx = xa - 18 if o["both"] else xa
                s.add(f'<circle cx="{cx}" cy="{y}" r="12" fill="#333"/>')
                s.add(f'<text x="{cx}" y="{y + 5}" font-size="14" font-weight="bold" fill="#fff" '
                      f'text-anchor="middle">{o["num"]}</text>')
            if o["tmark"]:
                k = o["b"] if o["tmark_at"] == "end" else o["a"]
                tx = self.x(k)
                right = o["tmark_at"] == "start"
                s.add(f'<text x="{tx + (8 if right else -8)}" y="{y + 19}" font-size="{FS}" font-style="italic" '
                      f'fill="#1f4e79" text-anchor="{"start" if right else "end"}">t'
                      f'<tspan baseline-shift="sub" font-size="11.5">{escape(o["tmark"])}</tspan></text>')
        if legend:
            s.legend(legend)
        return s.render()


def push():
    q = Seq([("rcv", ["Receiver", "(consumer)"], 56, FILL["consumer"]),
             ("app", ["Consumer", "application"], 172, FILL["consumer"]),
             ("ccp", ["Consumer", "CP"], 290, FILL["consumer"]),
             ("pcp", ["Provider", "CP"], 408, "#ffffff"),
             ("pdp", ["Provider", "DP"], 526, "#ffffff"),
             ("src", ["Data", "source"], 634, FILL["source"])])
    q.band("Once per agreement: catalogue and contract negotiation")
    q.msg("app", "ccp", "negotiate", 1)
    q.msg("ccp", "pcp", "DSP", 2, both=True)
    q.band("Once per message: one transfer process")
    q.msg("app", "ccp", "start push", 3, tmark="0")
    q.msg("ccp", "pcp", "DSP request", 4, tmark="1")
    q.msg("pcp", "pdp", "start flow", 5, tmark="2")
    q.msg("pdp", "src", "GET", 6)
    q.msg("src", "pdp", "payload", 7, colour=DATA, tmark="3", tmark_at="start")
    q.msg("pdp", "rcv", "POST payload to the receiver", 8, colour=DATA, tmark="4")
    q.msg("pdp", "pcp", "completed", 9, reply=True)
    q.msg("pcp", "ccp", "DSP completion", 10, reply=True)
    q.note("Next message: steps 3 to 10 again, as a new transfer process")
    return q.render(legend=[("ctrl", "request or control"), ("data", "data"), ("ctrl-dash", "reply"),
                            ("num", "step n, in the text"), ("t", "timestamp of a push phase")])


def pull():
    q = Seq([("app", ["Consumer", "application"], 66, FILL["consumer"]),
             ("ccp", ["Consumer", "CP"], 206, FILL["consumer"]),
             ("pcp", ["Provider", "CP"], 346, "#ffffff"),
             ("pdp", ["Provider", "DP"], 486, "#ffffff"),
             ("src", ["Data", "source"], 626, FILL["source"])])
    q.band("Once per agreement: catalogue and negotiation, as in push")
    q.y += 4
    q.band("Once per transfer: setup")
    q.msg("app", "ccp", "start pull", 1)
    q.msg("ccp", "pcp", "DSP request", 2)
    q.msg("pcp", "pdp", "start flow", 3)
    q.msg("pdp", "pcp", "EDR, token stored", 4, reply=True)
    q.msg("pcp", "ccp", "DSP start + EDR", 5, reply=True)
    q.msg("ccp", "app", "EDR: endpoint, token", 6, reply=True)
    q.band("Every fetch, whenever the application asks")
    q.msg("app", "pdp", "GET with token", 7)
    q.msg("pdp", "src", "token valid: GET", 8)
    q.msg("src", "pdp", "payload", 9, colour=DATA)
    q.msg("pdp", "app", "payload", 10, colour=DATA)
    q.band("End of access: contract expiry or termination by the provider")
    q.msg("pcp", "pdp", "stop flow", 11)
    q.msg("app", "pdp", "GET with token", 12)
    q.msg("pdp", "app", "403: token removed", 13, colour=GREY, reply=True)
    return q.render(legend=[("ctrl", "request or control"), ("data", "data"), ("ctrl-dash", "reply"),
                            ("grey-dash", "refusal"), ("num", "step n, in the text")])


def main():
    OUT.mkdir(exist_ok=True)
    (OUT / "F4_5_push_sequence.svg").write_text(push())
    (OUT / "F4_6_pull_sequence.svg").write_text(pull())


if __name__ == "__main__":
    main()
