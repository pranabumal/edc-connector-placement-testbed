"""
fig_timing_intervals.py — Figure F2.3 of the thesis (Chapter 2, sec:industry40).

Transfer intervals of industrial use cases from 3GPP TS 22.104 V17.7.0
(Tables 5.2-1 and 5.2-2, pp. 14–19), with the intervals of the three test cases. No measured values. The 5G-ACIA
classes are defined by latency, not interval, so they are not drawn on this axis.
"""
import matplotlib.pyplot as plt

import common as c

# (label, kind, a, b) — TS 22.104 Tables 5.2-1 / 5.2-2, exactly as specified:
#   "range" a..b ms; "le" at most a ms (and b, if given, a second "at most" value); "ge" at least a ms
USE_CASES = [
    ("Motion control", "range", 0.5, 2),
    ("Mobile robots (control)", "range", 1, 50),
    ("Control-to-control", "le", 10, 50),
    ("Closed-loop process control", "ge", 10, None),
    ("Video-operated remote control\n(15–250 kB messages)", "range", 10, 100),
    ("Asset monitoring, vibration / thermal\n(25 kB / 250 kB messages)", "le", 1000, None),
    ("Process monitoring, plant asset mgmt.", "range", 100, 60000),
]
TESTS = [("TC1", 20.0), ("TC3", 1000 / 24), ("TC2", 1000.0)]
GREY = "#4d4d4d"


def main():
    # narrower axes: labels outside the axes widen the saved (tight) PDF, which LaTeX
    # then shrinks to the text width (review phase 6: text printed at 6.6 pt)
    fig, ax = plt.subplots(figsize=(c.WIDTH - 2.35, 3.8))
    arrow = dict(arrowstyle="-|>", color=GREY, lw=1.4, mutation_scale=9)
    for i, (name, kind, a, b) in enumerate(reversed(USE_CASES)):
        if kind == "range":
            ax.plot([a, b], [i, i], lw=5, color=GREY, solid_capstyle="butt")
        elif kind == "le":       # at most a (and b): marker, arrow towards shorter intervals
            for v in (a, b):
                if v:
                    ax.plot([v], [i], marker="|", ms=11, mew=2.5, color=GREY)
                    ax.annotate("", xy=(v / 3, i), xytext=(v, i), arrowprops=arrow)
                    # two bounds on one row (10 and 50 ms): the second label goes right of its marker
                    right = b is not None and v == b
                    ax.text(v * (1.15 if right else 0.9), i + 0.18, f"≤ {v:g} ms" if v < 1000 else f"≤ {v / 1000:g} s",
                            ha="left" if right else "right", va="bottom", fontsize=7 * c.FS, color=GREY)
        elif kind == "ge":       # at least a: marker, arrow towards longer intervals
            ax.plot([a], [i], marker="|", ms=11, mew=2.5, color=GREY)
            ax.annotate("", xy=(a * 3, i), xytext=(a, i), arrowprops=arrow)
            ax.text(a * 0.87, i + 0.18, f"≥ {a:g} ms", ha="right", va="bottom", fontsize=7 * c.FS, color=GREY)
    ax.set_yticks(range(len(USE_CASES)))
    ax.set_yticklabels([u[0] for u in reversed(USE_CASES)])
    for label, ms in TESTS:
        ax.axvline(ms, color="#0072B2", lw=1, ls="--", zorder=0)
        ha = {"TC1": "right", "TC3": "left"}.get(label, "center")    # TC1 and TC3 are close: label outwards
        ax.text(ms * (0.92 if ha == "right" else 1.08 if ha == "left" else 1), -0.75, label, color="#0072B2",
                ha=ha, va="top", fontsize=8 * c.FS, fontweight="bold")
    ax.set_xscale("log")
    ax.set_xlim(0.1, 100000)
    ax.set_ylim(-1.15, len(USE_CASES) - 0.4)
    ax.set_xticks([0.1, 1, 10, 100, 1000, 10000, 100000])
    ax.set_xticklabels(["0.1 ms", "1 ms", "10 ms", "100 ms", "1 s", "10 s", "100 s"], rotation=35, ha="right")
    ax.set_xlabel("Transfer interval (logarithmic)")
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#e6e6e6", lw=0.6, zorder=-1)
    c.savefig(fig, "F2_3_timing_intervals")


if __name__ == "__main__":
    main()
