"""
fig_background.py — Figures 2.1 and 2.2 of the thesis (Chapter 2), conceptual
diagrams with no measured values.

  F2_1_cpdp      Control Plane and Data Plane in an EDC connector, and the
                 Dataspace Protocol (DSP) between two connectors
  F2_2_pushpull  push and pull transfers: who starts the data movement and
                 where the data go

They replace the earlier Mermaid drafts (diagrams/thesis/F2_1_cpdp.mmd,
F2_2_pushpull.mmd), which printed at 4-6 pt. Drawn 6.1 in wide, the width of
the text, so the 10 pt text prints at about 10 pt.

Run from the repository root:  analysis/.venv/bin/python analysis/fig_background.py
"""
import sys
from pathlib import Path

from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
from common import WIDTH, plt  # noqa: E402

OUT = c.THESIS / "images" / "background"
OUT.mkdir(parents=True, exist_ok=True)
CTRL, DATA = "#1f4e79", "#D55E00"
FS = 10


def box(ax, x, y, w, h, title, body="", fc="white", ec="#555555", ls="-", fs=FS):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.0,rounding_size=0.12",
                                fc=fc, ec=ec, ls=ls, lw=1.0))
    text = title if not body else f"{title}\n{body}"
    t = ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, linespacing=1.25)
    if body:   # bold first line
        t.set_text("")
        n_body = body.count("\n") + 1   # title line above, body lines below; centred as one block
        ax.annotate(title, (x + w / 2, y + h / 2), xytext=(0, n_body / 2 * fs * 1.25),
                    textcoords="offset points", ha="center", va="center", fontsize=fs, fontweight="bold")
        ax.annotate(body, (x + w / 2, y + h / 2), xytext=(0, -fs * 1.25 / 2), textcoords="offset points",
                    ha="center", va="center", fontsize=fs, linespacing=1.25)


def frame(ax, x, y, w, h, title):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.0,rounding_size=0.15",
                                fc="#f4f4f4", ec="#888888", ls=(0, (4, 2)), lw=1.0))
    ax.text(x + 0.12, y + h - 0.1, title, ha="left", va="top", fontsize=FS, fontweight="bold", color="#444444")


def arrow(ax, a, b, color=CTRL, lw=1.6, both=False, ls="-"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="<|-|>" if both else "-|>", mutation_scale=11,
                                 color=color, lw=lw, ls=ls, shrinkA=0, shrinkB=0))


def label(ax, x, y, text, color="black", ha="center", va="center", bold_first=False):
    ax.text(x, y, text, ha=ha, va=va, fontsize=FS - 0.5, color=color, linespacing=1.2)


def key(fig, extra=None):
    """Key below the drawing: what the arrow colours mean (review of 29 Oct 2026)."""
    from matplotlib.lines import Line2D
    h = [Line2D([0], [0], color=CTRL, lw=1.8, marker=">", markevery=[1], ms=6, label="control message"),
         Line2D([0], [0], color=DATA, lw=2.4, marker=">", markevery=[1], ms=6, label="data")]
    if extra:
        h.append(Line2D([0], [0], color="none", label=extra))
    fig.legend(handles=h, loc="lower center", ncol=len(h), frameon=False, fontsize=FS,
               handlelength=2.6, bbox_to_anchor=(0.5, 0.0))


def save(fig, name):
    fig.savefig(OUT / f"{name}.pdf")
    fig.savefig(c.OUT / "png" / f"{name}.png", dpi=200)
    plt.close(fig)


# ── F2.1 ─────────────────────────────────────────────────────────────────────
def fig_cpdp():
    fig, ax = plt.subplots(figsize=(WIDTH, 3.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5)
    ax.axis("off")
    plane_cp = "catalogue\ncontract negotiation\ntransfer processes\npolicy evaluation"
    # data source
    box(ax, 0.0, 0.75, 1.15, 0.9, "Data\nsource", fc="#eee6f8")
    # provider and consumer connectors
    for x, name, dp_body in ((1.4, "Provider connector", "moves the data\nchecks access tokens"),
                             (6.05, "Consumer connector", "receives the data\n(or another endpoint)")):
        frame(ax, x, 0.25, 2.95, 4.6, name)
        box(ax, x + 0.15, 2.4, 2.65, 1.95, "Control Plane", plane_cp, fc="#dcecff")
        box(ax, x + 0.15, 0.45, 2.65, 1.3, "Data Plane", dp_body, fc="#fff4d6")
        arrow(ax, (x + 0.75, 2.4), (x + 0.75, 1.75))
        label(ax, x + 0.85, 2.07, "Data Plane\nSignaling", ha="left")
    # DSP between the Control Planes
    arrow(ax, (4.2, 3.35), (6.2, 3.35), both=True)
    label(ax, 5.2, 3.75, "Dataspace\nProtocol (DSP)")
    label(ax, 5.2, 2.85, "catalogue,\nnegotiation,\ntransfer", color="#333333", va="top")
    # data
    arrow(ax, (1.15, 1.2), (1.55, 1.2), color=DATA, lw=2.2)
    arrow(ax, (4.2, 1.1), (6.2, 1.1), color=DATA, lw=2.2)
    label(ax, 5.2, 1.35, "data", color=DATA)
    fig.tight_layout(pad=0.1, rect=(0, 0.08, 1, 1))
    key(fig)
    save(fig, "F2_1_cpdp")


# ── F2.2 ─────────────────────────────────────────────────────────────────────
def fig_pushpull():
    fig, (ap, al) = plt.subplots(2, 1, figsize=(WIDTH, 5.35))
    for ax, title in ((ap, "Push"), (al, "Pull")):
        ax.set_xlim(0, 10)
        ax.set_ylim(-0.75, 3.45)
        ax.axis("off")
        ax.text(0, 3.42, title, ha="left", va="top", fontsize=FS + 1, fontweight="bold")
    CPB, DPB, SRC = (3.9, 1.95, 2.5, 1.0), (3.9, 0.05, 2.5, 1.0), (8.3, 0.1, 1.7, 0.9)
    for ax in (ap, al):
        box(ax, *CPB, "Provider\nControl Plane", fc="#dcecff")
        box(ax, *SRC, "Source", fc="#eee6f8")
    # push
    box(ap, *DPB, "Provider\nData Plane", fc="#fff4d6")
    box(ap, 0.0, 1.95, 1.9, 1.0, "Consumer", fc="#eeeeee")
    box(ap, 0.0, 0.05, 1.9, 1.0, "Consumer's\ndestination", fc="#eeeeee")
    arrow(ap, (1.9, 2.45), (3.9, 2.45))
    label(ap, 2.9, 2.6, "1 · transfer request\nwith its destination", va="bottom")
    arrow(ap, (5.15, 1.95), (5.15, 1.05))
    label(ap, 5.3, 1.5, "2 · start", ha="left")
    arrow(ap, (8.3, 0.55), (6.4, 0.55), color=DATA, lw=2.2)
    label(ap, 7.35, 0.8, "3 · data", color=DATA, va="bottom")
    arrow(ap, (3.9, 0.55), (1.9, 0.55), color=DATA, lw=2.2)
    label(ap, 2.9, 0.8, "4 · data sent to\nthe destination", color=DATA, va="bottom")
    # pull
    box(al, *DPB, "Provider Data Plane\nchecks only the token", fc="#fff4d6", fs=FS - 0.5)
    box(al, 0.0, 0.05, 1.9, 2.9, "Consumer", fc="#eeeeee")
    arrow(al, (1.9, 2.7), (3.9, 2.7))
    label(al, 2.9, 2.8, "1 · transfer\nrequest", va="bottom")
    arrow(al, (3.9, 2.2), (1.9, 2.2))
    label(al, 2.9, 2.1, "2 · endpoint and\naccess token (EDR)", va="top")
    arrow(al, (1.9, 0.8), (3.9, 0.8), color=DATA, lw=2.2)
    label(al, 2.9, 0.9, "3 · fetch with\ntoken (repeated)", color=DATA, va="bottom")
    arrow(al, (3.9, 0.3), (1.9, 0.3), color=DATA, lw=2.2)
    label(al, 2.9, 0.2, "4 · data in\nthe response", color=DATA, va="top")
    arrow(al, (8.3, 0.55), (6.4, 0.55), color=DATA, lw=2.2)
    label(al, 7.35, 0.8, "data", color=DATA, va="bottom")
    fig.tight_layout(pad=0.1, h_pad=0.6, rect=(0, 0.06, 1, 1))
    key(fig, "1–4: order of the steps")
    save(fig, "F2_2_pushpull")


if __name__ == "__main__":
    fig_cpdp()
    fig_pushpull()
