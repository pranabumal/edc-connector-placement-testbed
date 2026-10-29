"""
rq3.py — RQ3: where is access to shared data enforced, and where does a
connector's control over the data end? (measurement set D, 22 October 2026)

Data (common.RUNS["D"]), all stock EDC 0.14.1 pull (HttpData-PULL): the
consumer fetches straight from the provider Data Plane (DP) with the token
of the Endpoint Data Reference (EDR); about one fetch every 0.15 s (0.1 s
pause + the fetch itself).

  pull-pull-tokens.json     10 fetches with no token, 10 with a wrong token
                            (signature altered) -> token_tests
  pull-pull-terminate.json  the provider terminates the transfer through its
                            Management API 10 s into fetching -> terminate
  pull-pull-timed.json      contract valid 45 s after agreement; fetching goes
                            on past expiry -> agreement_signed_at, fetches
  pull-pull-timed-linkcut.json + linkcut-pull-timed-linkcut.txt (Hybrid only)
                            same as timed, but the provider CP machine (cPouta)
                            and DP machine (TAU edge VM1) cannot reach each
                            other from ~20 s into the test case for ~70 s

Clocks: fetch and terminate times are taken on the consumer machine; the
cut/restore times on the edge machine. clock.tsv of the link-cut run shows
every machine within 1.9 ms of the reference (single samples in the other
Set D runs reach 8.7 ms, but those tests use only the consumer clock); both
are far below the ~0.15 s fetch spacing, so no correction is applied (the
largest offset per run is reported in the numbers).

Expiry: agreement_signed_at (contractSigningDate) is in whole seconds, so the
nominal expiry instant signed_at + 45 s and every "after expiry" time carry up
to ~1 s of uncertainty. Terminate and link-cut times have no such limit; their
resolution is one fetch interval.

Outputs: figures R11_expiry_timeline, R11b_linkcut_timeline, R11c_termination,
R12_data_path; table T5_4_enforcement; numbers analysis/out/rq3.json.

Run from the repository root:  analysis/.venv/bin/python analysis/rq3.py
"""
import statistics

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

from common import (FS, RUNS, RESULTS, PLACEMENTS, LABEL, COLOR, WIDTH, raw,
                    savefig, write_table, write_numbers)

DENIED_C = "#D55E00"     # Okabe–Ito vermillion: denied fetches (also a different marker)
CUT_C = "#CC79A7"        # Okabe–Ito reddish purple: link cut period
GREY = "#7F7F7F"


# ── helpers ──────────────────────────────────────────────────────────────────
def ok(f):
    return f.get("status") == 200


def spacing_s(fetches):
    """Median time between the starts of consecutive fetches (the resolution)."""
    return statistics.median(b["start"] - a["start"] for a, b in zip(fetches, fetches[1:]))


def first_denial(fetches, t0):
    """Times relative to t0 of the last allowed fetch before the first denial,
    the first denied fetch, and how many fetches were allowed after that."""
    first = next(i for i, f in enumerate(fetches) if not ok(f) and i > 0)
    last_ok = max(i for i in range(first) if ok(fetches[i]))
    return {
        "last_allowed_s": round(fetches[last_ok]["start"] - t0, 3),
        "first_denied_s": round(fetches[first]["start"] - t0, 3),
        "allowed_after_first_denial": sum(ok(f) for f in fetches[first:]),
        "denied_statuses": sorted({str(f.get("status", "error")) for f in fetches[first:] if not ok(f)}),
        "fetches_allowed": sum(ok(f) for f in fetches),
        "fetches_denied": sum(not ok(f) for f in fetches),
        "fetch_errors": sum("error" in f for f in fetches),
    }


def max_clock_offset_ms(run):
    vals = []
    for line in (RESULTS / run / "clock.tsv").read_text().splitlines():
        parts = line.split("\t")
        try:
            vals.append(abs(float(parts[-1])) * 1000)
        except (ValueError, IndexError):
            pass
    return round(max(vals), 2) if vals else None


def strip(ax, fetches, t0, y, colour, size=16):
    """Fetch starts relative to t0 on one lane: allowed = colour '|', denied = vermillion 'x'."""
    a = [f["start"] - t0 for f in fetches if ok(f)]
    d = [f["start"] - t0 for f in fetches if not ok(f)]
    ax.scatter(a, [y] * len(a), marker="|", s=size * 6, color=colour, linewidths=1.2, zorder=3)
    ax.scatter(d, [y] * len(d), marker="x", s=size, color=DENIED_C, linewidths=1.0, zorder=3)


# ── data ─────────────────────────────────────────────────────────────────────
D = RUNS["D"]
N = {"tokens": {}, "terminate": {}, "expiry": {}, "linkcut": {}, "clock_max_abs_offset_ms": {}}
docs = {}
for p in PLACEMENTS:
    run = D[(p, "enf")]
    docs[p] = {k: raw(run, f"pull-pull-{k}.json") for k in ("tokens", "terminate", "timed")}
    N["clock_max_abs_offset_ms"][p] = max_clock_offset_ms(run)

    tt = docs[p]["tokens"]["token_tests"]
    N["tokens"][p] = {name: {"n": len(rows),
                             "statuses": sorted({str(r.get("status", "error")) for r in rows}),
                             "median_ms": round(statistics.median(r["elapsed_ms"] for r in rows), 1),
                             "body_bytes": sorted({r.get("size_bytes") for r in rows})}
                      for name, rows in tt.items()}
    N["tokens"][p]["valid_token_fetches_ok"] = sum(ok(f) for f in docs[p]["tokens"]["fetches"])

    term = docs[p]["terminate"]["terminate"]
    tf = docs[p]["terminate"]["fetches"]
    r = first_denial(tf, term["requested_at"])
    r.update({"api_answered_s": round(term["answered_at"] - term["requested_at"], 3),
              "api_status": term["status"],
              "fetches_allowed_after_request": sum(ok(f) for f in tf if f["start"] >= term["requested_at"]),
              "fetch_spacing_s": round(spacing_s(tf), 3)})
    N["terminate"][p] = r

    tm = docs[p]["timed"]
    expiry = float(tm["agreement_signed_at"]) + tm["policy_valid_s"]
    r = first_denial(tm["fetches"], expiry)
    r.update({"policy_valid_s": tm["policy_valid_s"], "uncertainty_s": 1.0,
              "fetch_spacing_s": round(spacing_s(tm["fetches"]), 3)})
    N["expiry"][p] = r

# Hybrid with the CP–DP link cut
lc_run = D[("hybrid", "linkcut")]
lc = raw(lc_run, "pull-pull-timed-linkcut.json")
marks = dict(line.split() for line in (RESULTS / lc_run / "linkcut-pull-timed-linkcut.txt").read_text().splitlines())
cut, restored = float(marks["cut"]), float(marks["restored"])
lc_exp = float(lc["agreement_signed_at"]) + lc["policy_valid_s"]
lcf = lc["fetches"]
served_cut = [f for f in lcf if ok(f) and lc_exp <= f["start"] < restored]
r = first_denial(lcf, restored)
N["linkcut"] = {
    "cut_rel_expiry_s": round(cut - lc_exp, 2),
    "restored_rel_expiry_s": round(restored - lc_exp, 2),
    "cut_duration_s": round(restored - cut, 2),
    "served_after_expiry_while_cut": len(served_cut),
    "served_after_expiry_while_cut_span_s": round(served_cut[-1]["start"] - lc_exp, 2),
    "served_after_expiry_total": sum(ok(f) for f in lcf if f["start"] >= lc_exp),
    "first_denied_after_restore_s": r["first_denied_s"],
    "last_allowed_after_restore_s": r["last_allowed_s"],
    "first_denied_after_expiry_s": round(r["first_denied_s"] + restored - lc_exp, 2),
    "allowed_after_first_denial": r["allowed_after_first_denial"],
    "denied_statuses": r["denied_statuses"],
    "fetches_allowed": r["fetches_allowed"], "fetches_denied": r["fetches_denied"],
    "fetch_errors": r["fetch_errors"],
    "fetch_spacing_s": round(spacing_s(lcf), 3),
    "clock_max_abs_offset_ms": max_clock_offset_ms(lc_run),
}
N["runs"] = {f"{k[0]}-{k[1]}": v for k, v in D.items()}
N["notes"] = ("expiry times: agreement_signed_at is whole seconds, +-1 s; terminate and link-cut "
              "times: resolution one fetch interval (fetch_spacing_s); link-cut run clocks within 1.9 ms")
write_numbers("rq3", N)


# ── R11: access around contract expiry, per placement ────────────────────────
fig, ax = plt.subplots(figsize=(WIDTH, 2.3))
for i, p in enumerate(PLACEMENTS):
    tm = docs[p]["timed"]
    e = float(tm["agreement_signed_at"]) + tm["policy_valid_s"]
    y = len(PLACEMENTS) - 1 - i
    strip(ax, tm["fetches"], e, y, COLOR[p])
    fd = N["expiry"][p]["first_denied_s"]
    ax.annotate(f"first denial {fd:+.2f} s", (fd, y), xytext=(fd + 0.5, y + 0.32),
                fontsize=7.5 * FS, va="center", arrowprops=dict(arrowstyle="-", color=GREY, lw=0.6))
ax.axvspan(0, 1, color=GREY, alpha=0.15, lw=0, zorder=0)
ax.axvline(0, color="black", lw=0.8, ls="--", zorder=1)
ax.text(1.05, len(PLACEMENTS) - 0.2, "grey band: expiry known to ±1 s\n(whole-second agreement time)",
        ha="left", va="bottom", fontsize=7 * FS, color="#333333")
ax.set_yticks(range(len(PLACEMENTS)), [LABEL[p] for p in reversed(PLACEMENTS)])
ax.set_xlim(-3, 4)
ax.set_ylim(-0.6, len(PLACEMENTS) + 0.45)
ax.set_xlabel("time relative to nominal contract expiry (agreement + 45 s), s")
ax.scatter([], [], marker="|", color="black", label="fetch allowed (200, placement colour)")
ax.scatter([], [], marker="x", color=DENIED_C, label="fetch denied (403)")
ax.legend(loc="lower left", ncol=2, frameon=False, bbox_to_anchor=(0, -0.48))
ax.spines["left"].set_visible(False)
ax.tick_params(axis="y", length=0)
savefig(fig, "R11_expiry_timeline")


# ── R11b: Hybrid, expiry while the CP–DP link is cut ─────────────────────────
fig, (a1, a2) = plt.subplots(2, 1, figsize=(WIDTH, 3.2), gridspec_kw={"height_ratios": [1, 1], "hspace": 0.9})
rc, rr = cut - lc_exp, restored - lc_exp
for ax, (lo, hi) in ((a1, (-38, 62)), (a2, (rr - 2, rr + 2))):
    ax.axvspan(rc, rr, color=CUT_C, alpha=0.18, lw=0, zorder=0)
    strip(ax, lcf, lc_exp, 0, COLOR["hybrid"])
    ax.axvline(0, color="black", lw=0.8, ls="--")
    for x in (rc, rr):
        ax.axvline(x, color=CUT_C, lw=1.0)
    ax.set_xlim(lo, hi)
    ax.set_ylim(-1, 1.2)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
a1.text(rc, 0.6, " link cut", color="#8B3A6B", fontsize=7.5 * FS, va="bottom")
a1.text(rr, 0.6, " restored", color="#8B3A6B", fontsize=7.5 * FS, va="bottom")
a1.text(0, 0.6, " expiry (±1 s)", fontsize=7.5 * FS, va="bottom")
a1.text((0 + rr) / 2 - 2, -0.75, f"{N['linkcut']['served_after_expiry_while_cut']} fetches served after expiry",
        ha="center", fontsize=7.5 * FS)
a1.set_xlabel("time relative to nominal contract expiry, s")
a1.set_title("Hybrid: provider CP (cPouta) ↔ DP (TAU edge) link cut", loc="left")
fd = N["linkcut"]["first_denied_after_restore_s"]
a2.annotate(f"first denial {fd:+.2f} s after restore", (rr + fd, 0), xytext=(rr + fd + 0.25, 0.65),
            fontsize=7.5 * FS, arrowprops=dict(arrowstyle="-", color=GREY, lw=0.6))
a2.text(rr, -0.75, "restored ", ha="right", color="#8B3A6B", fontsize=7.5 * FS)
a2.set_xlabel("same axis, zoomed around the restore, s")
a2.scatter([], [], marker="|", color=COLOR["hybrid"], label="fetch allowed (200)")
a2.scatter([], [], marker="x", color=DENIED_C, label="fetch denied (403)")
a2.legend(loc="upper left", ncol=2, frameon=False, bbox_to_anchor=(0, -0.6))
savefig(fig, "R11b_linkcut_timeline")


# ── R11c: provider terminates → first denied fetch ───────────────────────────
fig, ax = plt.subplots(figsize=(WIDTH, 2.2))
for i, p in enumerate(PLACEMENTS):
    term = docs[p]["terminate"]["terminate"]
    y = len(PLACEMENTS) - 1 - i
    strip(ax, docs[p]["terminate"]["fetches"], term["requested_at"], y, COLOR[p], size=22)
    ans = N["terminate"][p]["api_answered_s"]
    ax.plot([ans, ans], [y - 0.28, y + 0.28], color="black", lw=0.8, ls=":")
    fd = N["terminate"][p]["first_denied_s"]
    ax.annotate(f"{fd:.2f} s", (fd, y), xytext=(fd + 0.07, y + 0.3), fontsize=7.5 * FS,
                arrowprops=dict(arrowstyle="-", color=GREY, lw=0.6))
sp = statistics.median(N["terminate"][p]["fetch_spacing_s"] for p in PLACEMENTS)
ax.axvline(0, color="black", lw=0.8, ls="--")
ax.annotate("", xy=(-0.6 + sp, -0.55), xytext=(-0.6, -0.55),
            arrowprops=dict(arrowstyle="|-|", color="black", lw=0.7, mutation_scale=3))
ax.text(-0.6 + sp + 0.03, -0.55, f"resolution: one fetch ≈ {sp:.2f} s (0.1 s pause + fetch)",
        fontsize=7 * FS, va="center", bbox=dict(fc="white", ec="none", pad=0.5), zorder=4)
ax.set_yticks(range(len(PLACEMENTS)), [LABEL[p] for p in reversed(PLACEMENTS)])
ax.set_xlim(-0.65, 0.75)
ax.set_ylim(-0.85, len(PLACEMENTS) - 0.4)
ax.set_xlabel("time since the provider's terminate request, s (consumer clock)")
ax.plot([], [], color="black", lw=0.8, ls=":", label="provider API answered (204)")
ax.scatter([], [], marker="|", color="black", label="allowed")
ax.scatter([], [], marker="x", color=DENIED_C, label="denied (403)")
ax.legend(loc="lower left", ncol=3, frameon=False, bbox_to_anchor=(0, -0.48))
ax.spines["left"].set_visible(False)
ax.tick_params(axis="y", length=0)
savefig(fig, "R11c_termination")


# ── R12: data path and enforcement points per placement (schematic) ──────────
def box(ax, x, y, w, h, text, fc="white", ec="black", ls="-", fs=7.5, bold=False, tc="black"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=fc, ec=ec, ls=ls, lw=0.9))
    if text:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs * FS, color=tc,
                fontweight="bold" if bold else "normal")


def arrow(ax, a, b, color="black", ls="-", lw=1.4, rad=0.0, style="-|>"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=9, color=color, lw=lw,
                                 ls=ls, connectionstyle=f"arc3,rad={rad}", shrinkA=1, shrinkB=1))


MACH = {"cloud": "cPouta VM (cloud)", "edge": "TAU VM1 (edge)"}
PLACE = {"hybrid": {"cp": "cloud", "dp": "edge"},
         "edge": {"cp": "edge", "dp": "edge"},
         "cloud": {"cp": "cloud", "dp": "cloud"}}
MACH2 = {"cloud": "cPouta VM\n(cloud)", "edge": "TAU VM1\n(edge)"}   # two-line labels inside the machine boxes
XM, WM = 2.3, 4.45           # provider machine box(es): x, width
XC, WC, HC = 4.3, 2.3, 1.05   # CP and DP boxes: CP on top, DP below, in every placement
YCP, YDP = 2.55, 0.45
fig, axes = plt.subplots(3, 1, figsize=(WIDTH, 7.1))
for ax, p in zip(axes, PLACEMENTS):
    ax.set_xlim(-0.05, 10.2)
    ax.set_ylim(0, 4.3)
    ax.axis("off")
    cp_m, dp_m = PLACE[p]["cp"], PLACE[p]["dp"]
    unused = ({"cloud", "edge"} - {cp_m, dp_m})
    if unused:
        title = f"{LABEL[p]}: CP and DP on {MACH[cp_m]}; {MACH[unused.pop()].split(' (')[0]} not used"
    else:
        title = f"{LABEL[p]}: CP on {MACH[cp_m]}, DP on {MACH[dp_m]}"
    ax.text(0, 4.28, title, fontsize=8.5 * FS, fontweight="bold", va="top", color=COLOR[p])
    # provider machine(s)
    if cp_m == dp_m:
        box(ax, XM, 0.25, WM, 3.6, "")
        ax.text(XM + 0.1, 3.75, MACH2[cp_m], fontsize=7 * FS, va="top")
    else:
        box(ax, XM, 2.35, WM, 1.5, "")
        ax.text(XM + 0.1, 3.75, MACH2[cp_m], fontsize=7 * FS, va="top")
        box(ax, XM, 0.25, WM, 1.5, "")
        ax.text(XM + 0.1, 1.74, MACH[dp_m], fontsize=7 * FS, va="top")   # one line: the data arrow runs below
    box(ax, XC, YCP, WC, HC, "Provider CP\nevaluates policy\n(monitor ~1 s)", fc="#E8F1F8", fs=6.8)
    box(ax, XC, YDP, WC, HC, "Provider DP\nchecks token\non every fetch", fc="#FCEBDD", fs=6.8)
    # CP -> DP termination signal
    xm = XC + WC / 2
    arrow(ax, (xm, YCP), (xm, YDP + HC), color="black", ls="--", lw=1.0)
    # Hybrid: one line in the gap between the two machine boxes, clear of the machine label
    note = "terminate signal crosses machines" if cp_m != dp_m else "terminate signal\n(same machine)"
    ynote = 2.05 if cp_m != dp_m else (YCP + YDP + HC) / 2
    ax.text(xm - 0.12, ynote, note, fontsize=6.2 * FS, va="center", ha="right")
    # data source and consumer
    box(ax, 0.0, 0.45, 1.9, HC, "Data source\nTAU VM2", fc="#F2F2F2", fs=6.8)
    box(ax, 7.35, 0.32, 2.75, 3.53, "", fc="#F2F2F2")
    ax.text(8.72, 3.75, "Consumer (Contabo)", fontsize=7 * FS, ha="center", va="top")
    box(ax, 7.45, 2.15, 2.55, 1.05, "Consumer CP\nreceives the EDR\nand its token", fc="white", fs=6.8)
    box(ax, 7.45, YDP, 2.55, HC, "Consumer app\nholds the data", fc="white", fs=6.8, bold=True)
    # data path: source -> provider DP -> consumer app
    yd = YDP + HC / 2
    arrow(ax, (1.9, yd), (XC, yd), color=COLOR[p], lw=2.0)
    arrow(ax, (XC + WC, yd), (7.45, yd), color=COLOR[p], lw=2.0)
    ax.text((1.9 + XC) / 2, yd + 0.1, "data", fontsize=6.5 * FS, color=COLOR[p], ha="center", va="bottom")
    # where control ends (explained in the key below)
    ax.plot([7.15, 7.15], [0.05, 3.95], color=DENIED_C, lw=1.2, ls=(0, (4, 2)))
# key (review of 29 Oct 2026): line meanings in the figure, not only in the caption
from matplotlib.lines import Line2D
fig.legend(handles=[Line2D([0], [0], color="0.35", lw=2.0, label="data path (colour = placement)"),
                    Line2D([0], [0], color="black", lw=1.0, ls="--", label="terminate signal, CP to DP"),
                    Line2D([0], [0], color=DENIED_C, lw=1.2, ls=(0, (4, 2)),
                           label="connector control ends: data delivered")],
           loc="lower center", ncol=2, frameon=False, fontsize=7 * FS, bbox_to_anchor=(0.5, 0.0))
fig.subplots_adjust(hspace=0.08, bottom=0.09)
savefig(fig, "R12_data_path")


# ── T5.4: enforcement per placement ──────────────────────────────────────────
def st(p, name):
    t = N["tokens"][p][name]
    return f"{'/'.join(t['statuses'])}"


rows = []
for p in PLACEMENTS:
    t, e = N["terminate"][p], N["expiry"][p]
    rows.append(f"{LABEL[p]} & {st(p, 'no_token')} & {st(p, 'wrong_token')} & "
                f"\\num{{{t['first_denied_s']:.2f}}} & \\num{{{e['first_denied_s']:.1f}}} $\\pm$ 1 & "
                f"{t['allowed_after_first_denial']} / {e['allowed_after_first_denial']} \\\\")
L = N["linkcut"]
latex = (
    "% generated by analysis/rq3.py -- do not edit by hand\n"
    "\\begin{tabular}{lccccc}\n\\hline\n"
    "Placement & No token & Wrong token & Terminate $\\rightarrow$ & Expiry $\\rightarrow$ & Allowed after \\\\\n"
    " & (10 fetches) & (10 fetches) & first denial (s) & first denial (s) & first denial \\\\\n\\hline\n"
    + "\n".join(rows) + "\n\\hline\n"
    f"\\multicolumn{{6}}{{l}}{{Hybrid, provider CP--DP link cut for \\num{{{L['cut_duration_s']:.0f}}} s "
    f"(expiry {abs(L['cut_rel_expiry_s']):.0f} s into the cut):}} \\\\\n"
    f"\\multicolumn{{6}}{{l}}{{\\quad {L['served_after_expiry_while_cut']} fetches served in the "
    f"\\num{{{L['restored_rel_expiry_s']:.1f}}} s from expiry to restore (all status 200);}} \\\\\n"
    f"\\multicolumn{{6}}{{l}}{{\\quad first denial \\num{{{L['first_denied_after_restore_s']:.2f}}} s after "
    f"restore; {L['allowed_after_first_denial']} fetches allowed after it.}} \\\\\n\\hline\n"
    "\\end{tabular}\n"
    "% No/wrong token: status of all 10 fetches. Terminate: resolution one fetch (~0.15 s).\n"
    "% Expiry: agreement time is whole seconds (+-1 s).\n"
    "% 'Allowed after first denial': terminate test / expiry test.\n"
)
write_table("T5_4_enforcement", latex)

# console summary
for p in PLACEMENTS:
    print(f"{LABEL[p]:7} tokens {N['tokens'][p]['no_token']['statuses']}/{N['tokens'][p]['wrong_token']['statuses']}  "
          f"terminate->deny {N['terminate'][p]['first_denied_s']} s (API answered {N['terminate'][p]['api_answered_s']} s)  "
          f"expiry->deny {N['expiry'][p]['first_denied_s']} s +-1")
print("link cut:", {k: L[k] for k in ("cut_rel_expiry_s", "restored_rel_expiry_s", "served_after_expiry_while_cut",
                                      "first_denied_after_restore_s", "allowed_after_first_denial")})
