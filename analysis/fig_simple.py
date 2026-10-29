"""
fig_simple.py — two plain bar charts for Chapter 5, after the style of the measured
edge-cloud comparisons in the literature (e.g. Loghin et al. 2019: one bar per setup,
split into its parts). Review of 29 Oct 2026: the strip and box plots were hard to read.

  R13_mode_comparison   per-message time per placement: push, pull and the direct fetch
                        without EDC; bar = median, line = middle half (quartiles), value
                        printed on the bar. Push: Set A (rq1.json); pull and direct: Set B,
                        three runs (spread.json). Extremes are in Table T5_spread.
  R14_phases            where the time of one message goes: push split at the provider's CP,
                        DP and the source (Set A, rq1.json "push_phases"), pull split at the
                        source (Set B, one worker, all three runs, clock-corrected records of
                        each run's summary.json, as rq1.pull_phases).

Run after rq1.py and spread.py, from the repository root.
"""
import json

import numpy as np
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

from common import FS, LABEL, OUT, PLACEMENTS, TCS, TC_LABEL, WIDTH, load, plt, savefig, write_numbers
from repeats_BD import runs_B

R1 = json.loads((OUT / "rq1.json").read_text())
SP = json.loads((OUT / "spread.json").read_text())

MODE_COL = {"push": "#33658A", "pull": "#86BBD8", "direct": "#BDBDBD"}
MODE_LAB = {"push": "Push through EDC", "pull": "Pull through EDC", "direct": "Direct fetch, no EDC"}


def fig_modes():
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 3.0))
    w = 0.27
    for ax, tc in zip(axes, TCS):
        ymax = 0
        for i, pl in enumerate(PLACEMENTS):
            for k, (mode, src) in enumerate((("push", SP["push"]), ("pull", SP["pull"]), ("direct", SP["baseline"]))):
                s = src[tc][pl]
                x = i + (k - 1) * w
                ax.bar(x, s["median"], width=w * 0.92, color=MODE_COL[mode], edgecolor="white", lw=0.5)
                ax.plot([x, x], [s["q1"], s["q3"]], color="black", lw=0.9)
                ax.text(x, s["q3"], f" {s['median']:.0f}",
                        rotation=90, ha="center", va="bottom", fontsize=6.5 * FS)
                ymax = max(ymax, s["q3"])
        ax.set_ylim(0, ymax * 1.28)
        ax.set_xticks(range(3), [LABEL[p] for p in PLACEMENTS])
        ax.set_title(TC_LABEL[tc])
        ax.grid(axis="y", color="#e5e5e5", lw=0.5)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("time per message (ms)")
    hs = [Patch(color=MODE_COL[m]) for m in MODE_COL] + [Line2D([], [], color="black", lw=0.9)]
    ls = [MODE_LAB[m] for m in MODE_COL] + ["middle half of the messages"]
    fig.legend(hs, ls, loc="lower center", ncol=2, frameon=False, fontsize=7 * FS, bbox_to_anchor=(0.5, -0.13))
    fig.tight_layout()
    savefig(fig, "R13_mode_comparison")


PUSH_PH = [("request_to_provider", "push: consumer → provider CP", "#C6DBEF"),
           ("provider_to_dp", "push: provider CP → DP", "#6BAED6"),
           ("dp_to_source", "push: DP → source", "#2171B5"),
           ("source_to_received", "both: source → consumer", "#08306B")]
PULL_PH = [("request_to_source_ms", "pull: consumer → DP → source", "#FDB863"),
           ("source_to_received_ms", "both: source → consumer", "#08306B")]


def pull_phase_medians(pl, tc):
    """Median of each pull phase over all records of the three Set B runs with one worker."""
    out = {}
    for key, _, _ in PULL_PH:
        v = [r[key] for run in runs_B(pl, "seq") for r in load(run)["test_cases"][f"pull-{tc}"]["records"]
             if r.get(key) is not None]
        out[key] = {"median": float(np.median(v)), "n": len(v)}
    return out


def fig_phases():
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 3.0))
    w = 0.36
    for ax, tc in zip(axes, TCS):
        for i, pl in enumerate(PLACEMENTS):
            for k, (phs, data) in enumerate(((PUSH_PH, R1["push_phases"][tc][pl]),
                                             (PULL_PH, pull_phase_medians(pl, tc)))):
                x, bottom = i + (k - 0.5) * w * 1.1, 0.0
                for key, _, col in phs:
                    h = data[key]["median"]
                    ax.bar(x, h, bottom=bottom, width=w, color=col, edgecolor="white", lw=0.6)
                    bottom += h
                ax.text(x, bottom, "push" if k == 0 else "pull", ha="center", va="bottom", fontsize=6.5 * FS)
        ax.set_xticks(range(3), [LABEL[p] for p in PLACEMENTS])
        ax.set_ylim(0, ax.get_ylim()[1] * 1.08)
        ax.set_title(TC_LABEL[tc])
        ax.grid(axis="y", color="#e5e5e5", lw=0.5)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("median time (ms)")
    seen, hs, ls = set(), [], []
    for _, lab, col in PUSH_PH[:3] + PULL_PH[:1] + PUSH_PH[3:]:
        if lab not in seen:
            seen.add(lab); hs.append(Patch(color=col)); ls.append(lab)
    fig.legend(hs, ls, loc="lower center", ncol=2, frameon=False, fontsize=7 * FS, bbox_to_anchor=(0.5, -0.2))
    fig.tight_layout()
    savefig(fig, "R14_phases")


fig_modes()
fig_phases()
write_numbers("fig_simple", {"pull_phases_seq_3runs": {tc: {pl: pull_phase_medians(pl, tc) for pl in PLACEMENTS} for tc in TCS}})
