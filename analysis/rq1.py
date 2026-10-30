"""
rq1.py — RQ1: how does placing the EDC Control Plane (CP) and Data Plane (DP)
on cloud and edge (Hybrid, Edge, Cloud) affect latency and reliability?

Run from the repository root:  analysis/.venv/bin/python analysis/rq1.py
Deterministic: every bootstrap uses a fixed seed (common.boot_ci, seed 1;
diff_ci below, seed 1).

Data (runs listed in common.RUNS, see results/RUN_REGISTER-20261022.md)
  Set A  push, tuned-nosync, 3 repeats × 3 placements × TC1–TC3 × 20 transfers.
         Metric: request_to_received_ms (consumer CP creates the transfer →
         receiver has the data; one clock) and its four clock-corrected phases
         (request_to_provider, provider_to_dp, dp_to_source, source_to_received).
  Set B  pull on a fixed 300 s schedule. Metric: elapsed_ms of every fetch with
         HTTP status 200, read from the raw pull-pull-<tc>.json.
         seq = 1 worker, par = 4 workers, src = no-EDC baseline straight from
         the data source, run in each placement's time window.

Warm-up rule (applied everywhere)
  The first transfer of each test case in each run is excluded, and so is the
  first fetch of each test case in each pull run. In both modes it carries
  one-off work (new connections, cold code paths): push TC1 first transfers are
  551–1071 ms against ≈ 300 ms afterwards. summarize-run.py already drops the
  first pull fetch but keeps every push transfer; this script drops both, so
  push cells have n = 3 × 19 = 57. The first transfers are still drawn in R1
  (hollow markers) and counted in the reliability table.

Statistics
  medians with 95 % percentile-bootstrap CIs (common.boot_ci);
  difference of medians with a 95 % bootstrap CI (diff_ci, groups resampled
  independently); two-sided Mann–Whitney U (common.mwu) with Holm's correction
  (Holm 1979) over the 9 pairwise push comparisons (3 pairs × 3 TCs), and
  separately over the 9 pairwise pull comparisons; rank-biserial effect size
  r = 2U/(n1·n2) − 1 (positive = first group slower); Kruskal–Wallis per TC.
  Run-to-run variation: the range of the three repeat medians of one placement,
  compared with the range of the pooled placement medians, and a Kruskal–Wallis
  test across the three repeats of each placement.

Outputs
  figures R1_push_latency, R2_push_phases, R3_phase_spread, R4_repeat_medians,
  R5_pull_fetch (common.savefig); tables T5_1_significance, T5_1b_reliability,
  T5_1c_pull_significance (common.write_table); numbers out/rq1.json.
"""
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (FS, COLOR, LABEL, PLACEMENTS, RUNS, TC_LABEL, TC_SHORT, TCS, WIDTH, boot_ci, load,  # noqa: E402
                    mwu, plt, raw, savefig, write_numbers, write_table)

WARMUP = 1          # transfers / fetches dropped at the start of each test case of each run
REPEATS = (1, 2, 3)
PHASES = ("request_to_provider", "provider_to_dp", "dp_to_source", "source_to_received")
PHASE_LABEL = {"request_to_provider": "request → provider CP",
               "provider_to_dp": "provider CP → DP",
               "dp_to_source": "DP → source answers",
               "source_to_received": "source → received"}
# ordered stages in time: one hue, light → dark (not a placement colour)
PHASE_COLOR = {"request_to_provider": "#C6DBEF", "provider_to_dp": "#9ECAE1",
               "dp_to_source": "#4292C6", "source_to_received": "#08306B"}
PAIRS = [("hybrid", "edge"), ("hybrid", "cloud"), ("edge", "cloud")]


# ── helpers ──────────────────────────────────────────────────────────────────
def r2(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 2)


def med_ci(v):
    lo, hi = boot_ci(v)
    return {"n": len(v), "median": r2(np.median(v)), "ci": [r2(lo), r2(hi)],
            "q1": r2(np.percentile(v, 25)), "q3": r2(np.percentile(v, 75)),
            "iqr": r2(np.percentile(v, 75) - np.percentile(v, 25)),
            "p5": r2(np.percentile(v, 5)), "p95": r2(np.percentile(v, 95)),
            "min": r2(np.min(v)), "max": r2(np.max(v))}


def diff_ci(a, b, n=10000, level=0.95, seed=1):
    """Bootstrap CI of median(a) − median(b), each group resampled on its own."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    rng = np.random.default_rng(seed)
    da = np.median(rng.choice(a, size=(n, len(a)), replace=True), axis=1)
    db = np.median(rng.choice(b, size=(n, len(b)), replace=True), axis=1)
    q = (1 - level) / 2
    return float(np.quantile(da - db, q)), float(np.quantile(da - db, 1 - q))


def holm(pvals):
    """Holm–Bonferroni adjusted p-values, in the input order."""
    p = np.asarray(pvals, float)
    order = np.argsort(p)
    m = len(p)
    adj = np.empty(m)
    running = 0.0
    for k, i in enumerate(order):
        running = max(running, (m - k) * p[i])
        adj[i] = min(1.0, running)
    return adj.tolist()


def fmt_p(p):
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def compare(groups_by_tc, pairs=PAIRS):
    """Pairwise MWU per TC, Holm over all comparisons; plus Kruskal–Wallis per TC."""
    rows = []
    for tc in TCS:
        for a, b in pairs:
            x, y = groups_by_tc[tc][a], groups_by_tc[tc][b]
            U, p = mwu(x, y)
            lo, hi = diff_ci(x, y)
            rows.append({"tc": tc, "a": a, "b": b, "n_a": len(x), "n_b": len(y),
                         "median_a": r2(np.median(x)), "median_b": r2(np.median(y)),
                         "diff_ms": r2(np.median(x) - np.median(y)), "diff_ci": [r2(lo), r2(hi)],
                         "U": U, "r_rb": r2(2 * U / (len(x) * len(y)) - 1), "p": p})
    for row, padj in zip(rows, holm([r["p"] for r in rows])):
        row["p_holm"] = padj
        row["significant"] = bool(padj < 0.05)
    kw = {}
    for tc in TCS:
        H, p = stats.kruskal(*[groups_by_tc[tc][pl] for pl in PLACEMENTS])
        kw[tc] = {"H": r2(H), "p": p}
    return rows, kw


# ── data ─────────────────────────────────────────────────────────────────────
def push_records():
    """Every Set A transfer: placement, repeat, tc, index (1-based), total, phases."""
    out = []
    for (pl, rep), run in RUNS["A"].items():
        s = load(run)
        for tc in TCS:
            for i, r in enumerate(s["test_cases"][tc]["records"], start=1):
                out.append({"placement": pl, "repeat": rep, "tc": tc, "index": i,
                            "total": r["request_to_received_ms"], "phases": r.get("phases_ms")})
    return out


def pull_fetches(pl, mode, tc):
    """elapsed_ms of the status-200 fetches of one Set B run and TC, in start order, warm-up dropped."""
    doc = raw(RUNS["B"][(pl, mode)], f"pull-pull-{tc}.json")
    ok = sorted((f for f in doc["fetches"] if f.get("status") == 200), key=lambda f: f["start"])
    return [f["elapsed_ms"] for f in ok][WARMUP:]


def pull_phases(pl, mode, tc):
    """Clock-corrected pull phases from summary.json (its records already omit the first fetch)."""
    recs = load(RUNS["B"][(pl, mode)])["test_cases"][f"pull-{tc}"]["records"]
    return {k: [r[k] for r in recs if r.get(k) is not None]
            for k in ("request_to_source_ms", "source_to_received_ms")}


PUSH = push_records()
KEPT = [r for r in PUSH if r["index"] > WARMUP]
FIRST = [r for r in PUSH if r["index"] <= WARMUP]


def push(pl, tc, rep=None, key="total", recs=KEPT):
    return [(r["total"] if key == "total" else r["phases"][key]) for r in recs
            if r["placement"] == pl and r["tc"] == tc and (rep is None or r["repeat"] == rep)
            and (key == "total" or r["phases"])]


def hier_medians(groups, n=10000, seed=1):
    """Bootstrap distribution of the pooled median with runs as the unit: draw
    len(groups) runs with replacement, then resample the transfers within each
    drawn run, pool and take the median (review phase 3, 27 Oct 2026)."""
    rng = np.random.default_rng(seed)
    groups = [np.asarray(g, float) for g in groups if len(g)]
    out = np.empty(n)
    for b in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        out[b] = np.median(np.concatenate([rng.choice(groups[i], len(groups[i])) for i in pick]))
    return out


def hier_ci(groups, level=0.95):
    d = hier_medians(groups)
    q = (1 - level) / 2
    return [r2(np.quantile(d, q)), r2(np.quantile(d, 1 - q))]


def hier_diff(groups_a, groups_b, level=0.95):
    """Difference of pooled medians a − b with a run-level (hierarchical) bootstrap CI."""
    da, db = hier_medians(groups_a, seed=1), hier_medians(groups_b, seed=2)
    q = (1 - level) / 2
    pa = np.median(np.concatenate([np.asarray(g, float) for g in groups_a]))
    pb = np.median(np.concatenate([np.asarray(g, float) for g in groups_b]))
    return {"diff_ms": r2(pa - pb), "ci": [r2(np.quantile(da - db, q)), r2(np.quantile(da - db, 1 - q))]}


def runs_of(pl, tc, key="total"):
    return [push(pl, tc, rep=k, key=key) for k in REPEATS]


N = {}   # every number the report quotes

# ── push: medians, tests ─────────────────────────────────────────────────────
N["warmup_rule"] = f"first {WARMUP} transfer/fetch of each test case of each run excluded"
N["push"] = {tc: {pl: med_ci(push(pl, tc)) for pl in PLACEMENTS} for tc in TCS}
# Run-level CIs (three runs per placement): these replace the transfer-level CIs
# in the figures and the text; the transfer-level ones are kept as ci_transfer.
for tc in TCS:
    for pl in PLACEMENTS:
        N["push"][tc][pl]["ci_transfer"] = N["push"][tc][pl]["ci"]
        N["push"][tc][pl]["ci"] = hier_ci(runs_of(pl, tc))
N["push_diff_runlevel"] = [dict(tc=tc, a=a, b=b, **hier_diff(runs_of(a, tc), runs_of(b, tc)))
                           for tc in TCS for a, b in PAIRS]
N["push_phase_diff_runlevel"] = [dict(tc=tc, phase=ph, a=a, b=b, **hier_diff(runs_of(a, tc, ph), runs_of(b, tc, ph)))
                                 for tc in TCS for ph in PHASES for a, b in PAIRS]
N["push_all_incl_first"] = {tc: {pl: med_ci(push(pl, tc, recs=PUSH)) for pl in PLACEMENTS} for tc in TCS}
N["push_first_transfer"] = {tc: {pl: [r2(x) for x in push(pl, tc, recs=FIRST)] for pl in PLACEMENTS} for tc in TCS}
first_all = [r["total"] for r in FIRST]
N["push_first_vs_rest"] = {tc: {"first_median": r2(np.median([r["total"] for r in FIRST if r["tc"] == tc])),
                                "rest_median": r2(np.median([r["total"] for r in KEPT if r["tc"] == tc]))}
                           for tc in TCS}

sig_rows, kw = compare({tc: {pl: push(pl, tc) for pl in PLACEMENTS} for tc in TCS})
N["push_tests"] = {"pairwise": sig_rows, "kruskal": kw}
# sensitivity: same tests with the first transfers kept
sens_rows, sens_kw = compare({tc: {pl: push(pl, tc, recs=PUSH) for pl in PLACEMENTS} for tc in TCS})
N["push_tests_incl_first"] = {"pairwise": [{k: r[k] for k in ("tc", "a", "b", "diff_ms", "p", "p_holm", "significant")}
                                           for r in sens_rows], "kruskal": sens_kw}

# phases
N["push_phases"] = {tc: {pl: {ph: med_ci(push(pl, tc, key=ph)) for ph in PHASES} for pl in PLACEMENTS} for tc in TCS}
all_phase_vals = [r["phases"][ph] for r in KEPT if r["phases"] for ph in PHASES]
N["push_phase_check"] = {
    "records_with_phases": sum(1 for r in KEPT if r["phases"]),
    "records": len(KEPT),
    "min_phase_ms": r2(min(all_phase_vals)),
    "max_abs_sum_minus_total_ms": r2(max(abs(sum(r["phases"].values()) - r["total"]) for r in KEPT if r["phases"])),
}
# which phase carries the variation: IQR of each phase, pooled over placements, per TC
N["push_phase_iqr"] = {tc: {ph: r2(np.subtract(*np.percentile(
    [v for pl in PLACEMENTS for v in push(pl, tc, key=ph)], [75, 25]))) for ph in PHASES} for tc in TCS}
N["push_total_iqr"] = {tc: r2(np.subtract(*np.percentile([v for pl in PLACEMENTS for v in push(pl, tc)], [75, 25])))
                       for tc in TCS}
# phase-level placement tests (Kruskal–Wallis per TC and phase, Holm over the 12)
ph_kw = []
for tc in TCS:
    for ph in PHASES:
        H, p = stats.kruskal(*[push(pl, tc, key=ph) for pl in PLACEMENTS])
        ph_kw.append({"tc": tc, "phase": ph, "H": r2(H), "p": p})
for row, padj in zip(ph_kw, holm([r["p"] for r in ph_kw])):
    row["p_holm"] = padj
N["push_phase_kruskal"] = ph_kw
# pairwise MWU per phase (Holm over the 36 = 4 phases × 3 pairs × 3 TCs) to name which placement differs
ph_pw = []
for tc in TCS:
    for ph in PHASES:
        for a, b in PAIRS:
            x, y = push(a, tc, key=ph), push(b, tc, key=ph)
            U, p = mwu(x, y)
            ph_pw.append({"tc": tc, "phase": ph, "a": a, "b": b,
                          "diff_ms": r2(np.median(x) - np.median(y)), "p": p})
for row, padj in zip(ph_pw, holm([r["p"] for r in ph_pw])):
    row["p_holm"] = padj
    row["significant"] = bool(padj < 0.05)
N["push_phase_pairwise"] = ph_pw

# run-to-run variation
rep = {}
for tc in TCS:
    rep[tc] = {}
    for pl in PLACEMENTS:
        meds = {f"r{k}": r2(np.median(push(pl, tc, rep=k))) for k in REPEATS}
        cis = {f"r{k}": [r2(x) for x in boot_ci(push(pl, tc, rep=k))] for k in REPEATS}
        H, p = stats.kruskal(*[push(pl, tc, rep=k) for k in REPEATS])
        rep[tc][pl] = {"medians": meds, "ci": cis, "range_ms": r2(max(meds.values()) - min(meds.values())),
                       "kruskal_repeats_H": r2(H), "kruskal_repeats_p": p}
    pooled = [N["push"][tc][pl]["median"] for pl in PLACEMENTS]
    rep[tc]["between_placements_range_ms"] = r2(max(pooled) - min(pooled))
    rep[tc]["max_within_placement_range_ms"] = max(rep[tc][pl]["range_ms"] for pl in PLACEMENTS)
N["push_repeats"] = rep

# tail: transfers far above the rest (all are kept in every statistic above)
TAIL_MS = 1500
N["push_tail"] = {
    "threshold_ms": TAIL_MS,
    "events": [{"placement": r["placement"], "repeat": r["repeat"], "tc": r["tc"], "index": r["index"],
                "total_ms": r2(r["total"]), "dp_to_source_ms": r2(r["phases"]["dp_to_source"])}
               for r in KEPT if r["tc"] != "tc3" and r["total"] > TAIL_MS],
    "p95": {tc: {pl: N["push"][tc][pl]["p95"] for pl in PLACEMENTS} for tc in TCS},
    "max": {tc: {pl: N["push"][tc][pl]["max"] for pl in PLACEMENTS} for tc in TCS},
}
N["push_tail"]["count"] = len(N["push_tail"]["events"])
N["push_tail"]["of"] = len(KEPT)
# medians and tests are robust to them; this sensitivity check drops the tail events to show it
_no_tail = [r for r in KEPT if not (r["tc"] != "tc3" and r["total"] > TAIL_MS)]
_rows, _kw = compare({tc: {pl: push(pl, tc, recs=_no_tail) for pl in PLACEMENTS} for tc in TCS})
N["push_tests_without_tail"] = {"pairwise": [{k: r[k] for k in ("tc", "a", "b", "diff_ms", "p", "p_holm", "significant")}
                                             for r in _rows], "kruskal": _kw}

# ── pull ─────────────────────────────────────────────────────────────────────
N["pull"] = {mode: {tc: {pl: med_ci(pull_fetches(pl, mode, tc)) for pl in PLACEMENTS} for tc in TCS}
             for mode in ("seq", "par", "src")}
N["pull_first_fetch_ms"] = {mode: {tc: {pl: load(RUNS["B"][(pl, mode)])["test_cases"][f"pull-{tc}"]["first_fetch_ms"]
                                        for pl in PLACEMENTS} for tc in TCS} for mode in ("seq", "par", "src")}
N["pull_phases_seq"] = {tc: {pl: {k: med_ci(v) for k, v in pull_phases(pl, "seq", tc).items()} for pl in PLACEMENTS}
                        for tc in TCS}
N["pull_phases_src"] = {tc: {pl: {k: med_ci(v) for k, v in pull_phases(pl, "src", tc).items() if v}
                             for pl in PLACEMENTS} for tc in TCS}
pull_rows, pull_kw = compare({tc: {pl: pull_fetches(pl, "seq", tc) for pl in PLACEMENTS} for tc in TCS})
N["pull_tests_seq"] = {"pairwise": pull_rows, "kruskal": pull_kw}
# EDC vs its own window's baseline (seq), Holm over 9
vs_src = []
for tc in TCS:
    for pl in PLACEMENTS:
        x, y = pull_fetches(pl, "seq", tc), pull_fetches(pl, "src", tc)
        U, p = mwu(x, y)
        lo, hi = diff_ci(x, y)
        vs_src.append({"tc": tc, "placement": pl, "edc_median": r2(np.median(x)), "src_median": r2(np.median(y)),
                       "overhead_ms": r2(np.median(x) - np.median(y)), "overhead_ci": [r2(lo), r2(hi)],
                       "r_rb": r2(2 * U / (len(x) * len(y)) - 1), "p": p})
for row, padj in zip(vs_src, holm([r["p"] for r in vs_src])):
    row["p_holm"] = padj
N["pull_vs_baseline_seq"] = vs_src
# baseline stability across the three time windows (placement-independent path)
N["pull_baseline_window_range_ms"] = {tc: r2(max(N["pull"]["src"][tc][pl]["median"] for pl in PLACEMENTS)
                                             - min(N["pull"]["src"][tc][pl]["median"] for pl in PLACEMENTS))
                                      for tc in TCS}
src_kw = {}
for tc in TCS:
    H, p = stats.kruskal(*[pull_fetches(pl, "src", tc) for pl in PLACEMENTS])
    src_kw[tc] = {"H": r2(H), "p": p}
N["pull_baseline_window_kruskal"] = src_kw

# ── reliability ──────────────────────────────────────────────────────────────
relA = {}
for pl in PLACEMENTS:
    req = rec = tr = nr = 0
    nonzero_exit = 0
    for k in REPEATS:
        s = load(RUNS["A"][(pl, k)])
        for tc in TCS:
            t = s["test_cases"][tc]
            req += t["transfers_requested"]
            rec += t["transfers_received"]
            tr += t["transfer_retries"]
            nr += t["negotiation_retries"]
            nonzero_exit += int(t["exit_code"] not in (0, None))
    relA[pl] = {"runs": len(REPEATS), "requested": req, "received": rec, "transfer_retries": tr,
                "negotiation_retries": nr, "nonzero_exit": nonzero_exit}
relB = {}
for pl in PLACEMENTS:
    for mode in ("seq", "par", "src"):
        run = RUNS["B"][(pl, mode)]
        s = load(run)
        agg = Counter()
        for tc in TCS:
            t = s["test_cases"][f"pull-{tc}"]
            sch = t["schedule"]
            fetches = raw(run, f"pull-pull-{tc}.json")["fetches"]
            agg["slots"] += sch["slots"]
            agg["fetched"] += len(fetches)
            agg["ok"] += sum(1 for f in fetches if f.get("status") == 200)
            agg["errors"] += sum(1 for f in fetches if f.get("status") != 200)
            agg["skipped"] += sch["skipped_slots"]
            agg["transfer_retries"] += t["transfer_retries"]
            agg["negotiation_retries"] += t["negotiation_retries"]
            agg["run_errors"] += int(bool(t.get("error")))
        relB[(pl, mode)] = dict(agg)
N["reliability_A"] = relA
N["reliability_B"] = {f"{pl}-{mode}": v for (pl, mode), v in relB.items()}
N["reliability_B_skipped_by_tc"] = {
    f"{pl}-{mode}": {tc: load(RUNS["B"][(pl, mode)])["test_cases"][f"pull-{tc}"]["schedule"]["skipped_slots"]
                     for tc in TCS} for pl in PLACEMENTS for mode in ("seq", "par", "src")}
N["reliability_B_achieved_hz"] = {
    f"{pl}-{mode}": {tc: load(RUNS["B"][(pl, mode)])["test_cases"][f"pull-{tc}"]["schedule"]["achieved_hz"]
                     for tc in TCS} for pl in PLACEMENTS for mode in ("seq", "par", "src")}

# network RTT consumer ↔ provider sites (from the Set A runs), for the caveats
rtt = {}
for (pl, k), run in RUNS["A"].items():
    for r in load(run)["network_rtt_ms"]:
        rtt.setdefault(f"{r['from']}->{r['to']}", []).append(r["rtt_ms"])
N["network_rtt_ms_setA"] = {k: {"median": r2(np.median(v)), "min": r2(min(v)), "max": r2(max(v))}
                            for k, v in sorted(rtt.items())}

# ── figures ──────────────────────────────────────────────────────────────────
rng = np.random.default_rng(7)   # jitter only
YTOP_TOTAL = {"tc1": 1350, "tc2": 1000, "tc3": 1500}     # R1 axis tops; points above are marked, not hidden
YTOP_PHASE = {"tc1": 450, "tc2": 450, "tc3": 1300}       # R3 axis tops


def off_scale(ax, x, v, top):
    """Mark values above the axis top with a triangle and one label (count and range in s)."""
    over = np.asarray([y for y in v if y > top])
    if len(over):
        ax.scatter([x], [top * 0.985], marker="^", s=14, color="#333333", zorder=5, clip_on=False)
        rng_s = f"{over.min() / 1000:.1f} s" if len(over) == 1 else f"{over.min() / 1000:.1f}–{over.max() / 1000:.1f} s"
        ax.annotate(f"{len(over)} off scale\n{rng_s}", (x, top * 0.985), xytext=(-7, 0), textcoords="offset points",
                    fontsize=7 * FS, ha="right", va="top", color="#333333")


def fig_r1():
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 3.2))
    for ax, tc in zip(axes, TCS):
        top = YTOP_TOTAL[tc]
        ax.set_ylim(0, top)
        for i, pl in enumerate(PLACEMENTS):
            v = np.asarray(push(pl, tc))
            off_scale(ax, i, v, top)
            v = v[v <= top]
            ax.scatter(i + rng.uniform(-0.18, 0.18, len(v)), v, s=7, color=COLOR[pl], alpha=0.45, lw=0)
            f = np.asarray(push(pl, tc, recs=FIRST))
            ax.scatter(i + rng.uniform(-0.18, 0.18, len(f)), f, s=12, facecolor="none", edgecolor="#555555",
                       lw=0.7, label="first transfer (excluded)" if (tc == "tc1" and i == 0) else None)
            m = N["push"][tc][pl]
            ax.errorbar(i + 0.32, m["median"], yerr=[[m["median"] - m["ci"][0]], [m["ci"][1] - m["median"]]],
                        fmt="o", color="black", ms=3.5, capsize=2, lw=1)
        ax.set_xticks(range(3), [LABEL[p] for p in PLACEMENTS], rotation=25, ha="right", rotation_mode="anchor")
        ax.set_xlim(-0.5, 2.6)
        ax.set_title(TC_LABEL[tc])
        ax.grid(axis="y", color="#e5e5e5", lw=0.5)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("request → received (ms)")
    from matplotlib.lines import Line2D   # key for every mark (review of 29 Oct 2026)
    hs, ls = axes[0].get_legend_handles_labels()
    hs = [Line2D([], [], marker="o", ls="", color="0.45", alpha=0.6, ms=3.5, label="one transfer")] + hs + [
        Line2D([], [], marker="o", ls="-", color="black", ms=3.5, lw=1, label="median, 95 % run-level CI"),
        Line2D([], [], marker="^", ls="", color="0.2", ms=4, label="transfers above the axis")]
    fig.legend(handles=hs, loc="lower center", frameon=False, fontsize=7 * FS, ncol=2,
               bbox_to_anchor=(0.5, -0.09))
    fig.tight_layout()
    savefig(fig, "R1_push_latency")


def fig_r2():
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 2.9))
    for ax, tc in zip(axes, TCS):
        for i, pl in enumerate(PLACEMENTS):
            bottom = 0.0
            for ph in PHASES:
                h = N["push_phases"][tc][pl][ph]["median"]
                ax.bar(i, h, bottom=bottom, width=0.62, color=PHASE_COLOR[ph], edgecolor="white", lw=1,
                       label=PHASE_LABEL[ph] if (tc == "tc1" and i == 0) else None)
                bottom += h
            tot = N["push"][tc][pl]["median"]
            ax.plot([i - 0.36, i + 0.36], [tot, tot], color="black", lw=1.2,
                    label="median total" if (tc == "tc1" and i == 0) else None)
        ax.set_xticks(range(3), [LABEL[p] for p in PLACEMENTS])
        ax.set_title(TC_LABEL[tc])
        ax.grid(axis="y", color="#e5e5e5", lw=0.5)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("median time (ms)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False, fontsize=7 * FS, bbox_to_anchor=(0.5, -0.16))
    fig.tight_layout()
    savefig(fig, "R2_push_phases")


def fig_r3():
    fig, axes = plt.subplots(3, 1, figsize=(WIDTH, 6.2))
    for ax, tc in zip(axes, TCS):
        for j, ph in enumerate(PHASES):
            for i, pl in enumerate(PLACEMENTS):
                v = push(pl, tc, key=ph)
                pos = j + (i - 1) * 0.26
                bp = ax.boxplot([v], positions=[pos], widths=0.22, whis=(5, 95), showfliers=True,
                                patch_artist=True, medianprops={"color": "black", "lw": 1},
                                flierprops={"marker": "o", "ms": 2, "mec": COLOR[pl], "mfc": "none", "alpha": 0.6},
                                boxprops={"lw": 0.6}, whiskerprops={"lw": 0.6}, capprops={"lw": 0.6})
                bp["boxes"][0].set_facecolor(COLOR[pl])
                bp["boxes"][0].set_alpha(0.75)
                off_scale(ax, pos, v, YTOP_PHASE[tc])
        ax.set_ylim(0, YTOP_PHASE[tc])
        ax.set_xticks(range(4), [PHASE_LABEL[p] for p in PHASES])
        ax.set_xlim(-0.5, 3.5)
        ax.set_title(TC_LABEL[tc], loc="left")
        ax.set_ylabel("ms")
        ax.grid(axis="y", color="#e5e5e5", lw=0.5)
        ax.set_axisbelow(True)
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLOR[p], alpha=0.75) for p in PLACEMENTS]
    fig.legend(handles, [LABEL[p] for p in PLACEMENTS], loc="lower center", ncol=3, frameon=False,
               bbox_to_anchor=(0.5, -0.03))
    fig.text(0.5, -0.05, "Box: quartiles and median; whiskers: 5th–95th percentile (computed on all values); "
             "circles: beyond. n = 57 per box. ▲: values above the axis.", ha="center", fontsize=7 * FS)
    fig.tight_layout()
    savefig(fig, "R3_phase_spread")


def fig_r4():
    markers = {1: "o", 2: "s", 3: "^"}
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 2.6))
    for ax, tc in zip(axes, TCS):
        for i, pl in enumerate(PLACEMENTS):
            for k in REPEATS:
                m = N["push_repeats"][tc][pl]["medians"][f"r{k}"]
                lo, hi = N["push_repeats"][tc][pl]["ci"][f"r{k}"]
                x = i + (k - 2) * 0.18
                ax.errorbar(x, m, yerr=[[m - lo], [hi - m]], fmt=markers[k], color=COLOR[pl], ms=4,
                            capsize=1.5, lw=0.8, mec="white", mew=0.5,
                            label=f"r{k}" if (tc == "tc1" and i == 0) else None)
            pooled = N["push"][tc][pl]["median"]
            ax.plot([i - 0.32, i + 0.32], [pooled, pooled], color="black", lw=0.8, ls="--",
                    label="pooled median" if (tc == "tc1" and i == 0) else None)
        ax.set_xticks(range(3), [LABEL[p] for p in PLACEMENTS])
        ax.set_title(TC_LABEL[tc])
        ax.grid(axis="y", color="#e5e5e5", lw=0.5)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("median request → received (ms)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, fontsize=7 * FS, bbox_to_anchor=(0.5, -0.08))
    fig.tight_layout()
    savefig(fig, "R4_repeat_medians")


def fig_r5():
    # Review of 29 Oct 2026 (K. Mätäsniemi): show the extremes, not only the box. Every box also
    # marks its fastest fetch (▼) and its slowest (▲ at the top of the axis, value in seconds),
    # because the slowest fetches lie far above the boxes.
    top = {"tc1": 100, "tc2": 120, "tc3": 1000}
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 3.3))
    for ax, tc in zip(axes, TCS):
        ax.set_ylim(0, top[tc])
        for i, pl in enumerate(PLACEMENTS):
            for off, mode, col in ((-0.17, "seq", COLOR[pl]), (0.17, "src", COLOR["source"])):
                v = np.asarray(pull_fetches(pl, mode, tc))
                x = i + off
                bp = ax.boxplot([v], positions=[x], widths=0.28, whis=(5, 95), showfliers=False,
                                patch_artist=True, medianprops={"color": "black", "lw": 1},
                                boxprops={"lw": 0.6}, whiskerprops={"lw": 0.6}, capprops={"lw": 0.6})
                bp["boxes"][0].set_facecolor(col)
                bp["boxes"][0].set_alpha(0.75 if mode == "seq" else 0.45)
                ax.plot([x], [v.min()], marker="v", ms=3.5, color="#333333", zorder=5)
                if v.max() > top[tc]:
                    ax.plot([x], [top[tc]], marker="^", ms=3.5, color="#333333", clip_on=False, zorder=5)
                    ax.annotate(f"{v.max() / 1000:.2f}", (x, top[tc]), xytext=(0, 4), textcoords="offset points",
                                rotation=90, ha="center", va="bottom", fontsize=8 * FS, color="#333333")
                else:
                    ax.plot([x], [v.max()], marker="^", ms=3.5, color="#333333", zorder=5)
        ax.set_xticks(range(3), [LABEL[p] for p in PLACEMENTS], rotation=25, ha="right", rotation_mode="anchor")
        ax.set_title(TC_LABEL[tc], pad=30)
        ax.grid(axis="y", color="#e5e5e5", lw=0.5)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("fetch time (ms)")
    from matplotlib.lines import Line2D
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLOR[p], alpha=0.75) for p in PLACEMENTS] + \
              [plt.Rectangle((0, 0), 1, 1, color=COLOR["source"], alpha=0.45),
               Line2D([], [], marker="v", ls="", color="#333333", ms=3.5),
               Line2D([], [], marker="^", ls="", color="#333333", ms=3.5)]
    labels = [f"{LABEL[p]} (through EDC)" for p in PLACEMENTS] + [LABEL["source"] + ", same time window",
              "fastest fetch", "slowest fetch (s, above the axis)"]
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=7 * FS, bbox_to_anchor=(0.5, -0.24))
    fig.tight_layout()
    savefig(fig, "R5_pull_fetch")


for f in (fig_r1, fig_r2, fig_r3, fig_r4, fig_r5):
    f()

# ── tables ───────────────────────────────────────────────────────────────────
NAME = {"hybrid": "Hybrid", "edge": "Edge", "cloud": "Cloud"}


def sig_table(rows, kwd, caption_n):
    lines = [r"\begin{tabular}{llrrrrrr}", r"\toprule",
             r"TC & Pair & Median A & Median B & $\Delta$ (ms) & 95\,\% CI of $\Delta$ & $p$ & $p_\mathrm{Holm}$ \\",
             r"\midrule"]
    for tc in TCS:
        for r in [x for x in rows if x["tc"] == tc]:
            lines.append(f"{TC_SHORT[tc]} & {NAME[r['a']]}--{NAME[r['b']]} & {r['median_a']:.1f} & {r['median_b']:.1f} & "
                         f"{r['diff_ms']:+.1f} & [{r['diff_ci'][0]:+.1f}, {r['diff_ci'][1]:+.1f}] & "
                         f"{fmt_p(r['p'])} & {fmt_p(r['p_holm'])} \\\\")
        k = kwd[tc]
        lines.append(f"\\multicolumn{{8}}{{l}}{{\\quad Kruskal--Wallis {TC_SHORT[tc]}: $H = {k['H']:.2f}$, "
                     f"$p = {fmt_p(k['p'])}$}} \\\\")
        if tc != TCS[-1]:
            lines.append(r"\midrule")
    lines += [r"\bottomrule", r"\end{tabular}",
              f"% {caption_n}. Two-sided Mann--Whitney U; Holm over the 9 pairwise comparisons; "
              r"$\Delta$ = median A $-$ median B, bootstrap CI (10\,000 resamples). Generated by analysis/rq1.py."]
    return "\n".join(lines) + "\n"


write_table("T5_1_significance", sig_table(sig_rows, kw, "Set A push, n = 57 per placement and TC (first transfer of each run excluded)"))
write_table("T5_1c_pull_significance", sig_table(pull_rows, pull_kw, "Set B pull, sequential client, status-200 fetches after the first"))

rel = [r"\begin{tabular}{llrrrrr}", r"\toprule",
       r"\multicolumn{7}{l}{\textit{Set A, push (3 runs $\times$ 3 TCs $\times$ 20 transfers per placement)}} \\",
       r"Placement & & Requested & Received & Transfer retries & Negotiation retries & \\", r"\midrule"]
for pl in PLACEMENTS:
    a = relA[pl]
    rel.append(f"{NAME[pl]} & & {a['requested']} & {a['received']} & {a['transfer_retries']} & {a['negotiation_retries']} & \\\\")
rel += [r"\midrule",
        r"\multicolumn{7}{l}{\textit{Set B, pull (300 s per TC, TC1--TC3 summed)}} \\",
        r"Placement & Client & Slots & Fetches & OK (200) & Errors & Skipped slots \\", r"\midrule"]
MODE = {"seq": "1 worker", "par": "4 workers", "src": "no EDC"}
for pl in PLACEMENTS:
    for mode in ("seq", "par", "src"):
        b = relB[(pl, mode)]
        rel.append(f"{NAME[pl]} & {MODE[mode]} & {b['slots']} & {b['fetched']} & {b['ok']} & {b['errors']} & {b['skipped']} \\\\")
rel += [r"\bottomrule", r"\end{tabular}",
        "% Skipped slots: schedule slots the client could not start within one period because the previous fetch "
        "was still running (rate limit of a request-response client), not failed requests. Generated by analysis/rq1.py."]
write_table("T5_1b_reliability", "\n".join(rel) + "\n")

write_numbers("rq1", N)

# ── console summary ──────────────────────────────────────────────────────────
print("push median [95% CI] ms, n=57")
for tc in TCS:
    print(" ", tc, "  ".join(f"{pl}: {N['push'][tc][pl]['median']} {N['push'][tc][pl]['ci']}" for pl in PLACEMENTS),
          f"KW p={kw[tc]['p']:.3g}")
for r in sig_rows:
    print(f"  {r['tc']} {r['a']}-{r['b']}: d={r['diff_ms']} {r['diff_ci']} p={r['p']:.3g} holm={r['p_holm']:.3g}")
print("pull seq median ms (src)")
for tc in TCS:
    print(" ", tc, "  ".join(f"{pl}: {N['pull']['seq'][tc][pl]['median']} ({N['pull']['src'][tc][pl]['median']})"
                             for pl in PLACEMENTS))
