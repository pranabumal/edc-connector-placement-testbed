"""
repeats_BD.py — Sets B and D over all their runs: the protocol run of 22 October 2026
(common.RUNS) and the repeats of 27-28 October 2026 (review re-run F), so that every
condition has up to three runs and the run, not the fetch, is the unit.

  B  per placement, mode (seq / par / src) and TC: each run's median per-message time,
     achieved rate and missed slots, and whether it met the pass criterion of Section 3.3
     (median < deadline, achieved >= 99 % of target, < 1 % missed slots); run-level
     (hierarchical) bootstrap CIs of the pooled median and of the placement differences.
  D  per placement and run: token tests, provider-side termination and contract expiry,
     as rq3.py computes them for the protocol run.

Repeat runs are found by name (results/2026102[78]T*-<placement>-tuned-nosync-<B-mode|D-enf>)
and used only if their summary.json exists. Writes analysis/out/repeats_BD.json.
Run from the repository root:  analysis/.venv/bin/python analysis/repeats_BD.py
"""
import statistics
from itertools import combinations

import numpy as np

from common import RUNS, RESULTS, PLACEMENTS, TCS, TARGET, load, raw, write_numbers

MODES = ["seq", "par", "src"]
WARMUP = 1


def repeats(tag):
    out = []
    for d in sorted(RESULTS.glob(f"2026102[78]T*-*-tuned-nosync-{tag}")):
        if (d / "summary.json").exists():
            out.append(d.name)
    return out


def runs_B(p, m):
    rep = [r for r in repeats(f"B-{m}") if f"-{p}-" in r]
    return [RUNS["B"][(p, m)]] + rep


def runs_D(p):
    rep = [r for r in repeats("D-enf") if f"-{p}-" in r]
    return [RUNS["D"][(p, "enf")]] + rep


# ── Set B ────────────────────────────────────────────────────────────────────
def fetch_ms(run, tc):
    """elapsed_ms of the status-200 fetches in start order, warm-up dropped (as rq1.py)."""
    doc = raw(run, f"pull-pull-{tc}.json")
    ok = sorted((f for f in doc["fetches"] if f.get("status") == 200), key=lambda f: f["start"])
    return [f["elapsed_ms"] for f in ok][WARMUP:]


def per_msg_ms(run, tc):
    """request_to_received_ms of the summary records (as rq2.py, used for the verdicts)."""
    recs = load(run)["test_cases"]["pull-" + tc]["records"]
    return [r["request_to_received_ms"] for r in recs if r.get("request_to_received_ms") is not None]


def hier(groups, n=10000, seed=1):
    rng = np.random.default_rng(seed)
    groups = [np.asarray(g, float) for g in groups if len(g)]
    out = np.empty(n)
    for b in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        out[b] = np.median(np.concatenate([rng.choice(groups[i], len(groups[i])) for i in pick]))
    return out


def r1(x):
    return round(float(x), 1)


B = {}
for p in PLACEMENTS:
    for m in MODES:
        runs = runs_B(p, m)
        for tc in TCS:
            per_run = []
            for run in runs:
                s = load(run)["test_cases"]["pull-" + tc]["schedule"]
                med = float(np.median(per_msg_ms(run, tc)))
                passed = (med < TARGET[tc][1] and s["missed_pct"] < 1
                          and s["achieved_hz"] >= 0.99 * s["rate_hz"])
                per_run.append({"run": run, "median_ms": r1(med),
                                "median_fetch_ms": r1(np.median(fetch_ms(run, tc))),
                                "achieved_hz": round(s["achieved_hz"], 3),
                                "missed_pct": round(s["missed_pct"], 2), "pass": bool(passed)})
            groups = [fetch_ms(run, tc) for run in runs]
            d = hier(groups)
            B[f"{p}-{m}-{tc}"] = {
                "n_runs": len(runs), "runs": per_run,
                "pooled_median_fetch_ms": r1(np.median(np.concatenate(groups))),
                "ci_runlevel": [r1(np.quantile(d, 0.025)), r1(np.quantile(d, 0.975))],
                "run_median_range_ms": [min(x["median_fetch_ms"] for x in per_run),
                                        max(x["median_fetch_ms"] for x in per_run)],
                "pass_all_runs": all(x["pass"] for x in per_run),
                "pass_runs": sum(x["pass"] for x in per_run)}

diffs = []
for m in ("seq", "par"):
    for tc in TCS:
        for a, b in combinations(PLACEMENTS, 2):
            ga = [fetch_ms(r, tc) for r in runs_B(a, m)]
            gb = [fetch_ms(r, tc) for r in runs_B(b, m)]
            da, db = hier(ga, seed=1), hier(gb, seed=2)
            pa, pb = np.median(np.concatenate(ga)), np.median(np.concatenate(gb))
            diffs.append({"mode": m, "tc": tc, "a": a, "b": b, "diff_ms": r1(pa - pb),
                          "ci": [r1(np.quantile(da - db, 0.025)), r1(np.quantile(da - db, 0.975))]})

# overhead over the same-window baseline, per run pair (EDC run k vs baseline run k)
overhead = {}
for p in PLACEMENTS:
    for tc in TCS:
        e, s = runs_B(p, "seq"), runs_B(p, "src")
        overhead[f"{p}-{tc}"] = [r1(np.median(fetch_ms(x, tc)) - np.median(fetch_ms(y, tc)))
                                 for x, y in zip(e, s)]


# ── Set D ────────────────────────────────────────────────────────────────────
def ok(f):
    return f.get("status") == 200


def spacing_s(fetches):
    return statistics.median(b["start"] - a["start"] for a, b in zip(fetches, fetches[1:]))


def first_denial(fetches, t0):
    first = next(i for i, f in enumerate(fetches) if not ok(f) and i > 0)
    last_ok = max(i for i in range(first) if ok(fetches[i]))
    return {"last_allowed_s": round(fetches[last_ok]["start"] - t0, 3),
            "first_denied_s": round(fetches[first]["start"] - t0, 3),
            "allowed_after_first_denial": sum(ok(f) for f in fetches[first:]),
            "denied_statuses": sorted({str(f.get("status", "error")) for f in fetches[first:] if not ok(f)})}


D = {}
for p in PLACEMENTS:
    D[p] = []
    for run in runs_D(p):
        docs = {k: raw(run, f"pull-pull-{k}.json") for k in ("tokens", "terminate", "timed")}
        tt = docs["tokens"]["token_tests"]
        tokens = {name: sorted({str(r.get("status", "error")) for r in rows}) for name, rows in tt.items()}
        term = docs["terminate"]["terminate"]
        tr = first_denial(docs["terminate"]["fetches"], term["requested_at"])
        tm = docs["timed"]
        expiry = float(tm["agreement_signed_at"]) + tm["policy_valid_s"]
        ex = first_denial(tm["fetches"], expiry)
        D[p].append({"run": run, "token_statuses": tokens,
                     "valid_token_fetches_ok": sum(ok(f) for f in docs["tokens"]["fetches"]),
                     "terminate_first_denied_s": tr["first_denied_s"],
                     "terminate_allowed_after": tr["allowed_after_first_denial"],
                     "terminate_api_status": term["status"],
                     "expiry_first_denied_s": ex["first_denied_s"],
                     "expiry_last_allowed_s": ex["last_allowed_s"],
                     "expiry_allowed_after": ex["allowed_after_first_denial"],
                     "expiry_spacing_s": round(spacing_s(tm["fetches"]), 3)})

summary_D = {p: {"n_runs": len(v),
                 "terminate_first_denied_s": [min(x["terminate_first_denied_s"] for x in v),
                                              max(x["terminate_first_denied_s"] for x in v)],
                 "expiry_first_denied_s": [min(x["expiry_first_denied_s"] for x in v),
                                           max(x["expiry_first_denied_s"] for x in v)],
                 "any_allowed_after_denial": any(x["terminate_allowed_after"] or x["expiry_allowed_after"] for x in v)}
             for p, v in D.items()}

# TC2 against the 100 ms communication latency of TS 22.104 (Section 5.3.3): share of
# per-message times over 100 ms, pooled over the runs of each placement and mode
over100 = {}
for p in PLACEMENTS:
    for m in ("seq", "src"):
        v = np.concatenate([per_msg_ms(r, "tc2") for r in runs_B(p, m)])
        over100[f"{p}-{m}"] = {"pct": round(100 * float(np.mean(v > 100)), 1),
                               "per_run_pct": [round(100 * float(np.mean(np.asarray(per_msg_ms(r, "tc2")) > 100)), 1)
                                               for r in runs_B(p, m)]}

write_numbers("repeats_BD", {"B": B, "B_diffs": diffs, "B_overhead_per_run_ms": overhead, "tc2_over_100ms": over100,
                             "D": D, "D_summary": summary_D})

# ── Figure 5.5 (R9): delivery at the target rate over all three runs per condition ──
def fig_rate():
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from common import COLOR, LABEL, WIDTH, FS, savefig
    dl = {"tc1": "20 ms", "tc2": "1 s", "tc3": "41.7 ms"}
    fig, axs = plt.subplots(1, 3, figsize=(WIDTH, 3.45), sharey=True)
    w = 0.26
    for ax, tc in zip(axs, TCS):
        target = TARGET[tc][0]
        missed = [x["missed_pct"] for p in PLACEMENTS for m in MODES for x in B[f"{p}-{m}-{tc}"]["runs"]]
        mtxt = f"missed: {min(missed):.0f} %" if max(missed) == min(missed) else f"missed: {min(missed):.0f}-{max(missed):.0f} %"
        for i, p in enumerate(PLACEMENTS):
            for j, m in enumerate(MODES):
                runs = B[f"{p}-{m}-{tc}"]["runs"]
                v = [100 * r["achieved_hz"] / target for r in runs]
                mean = sum(v) / len(v)
                x = i + (j - 1) * w
                col = COLOR["source"] if m == "src" else COLOR[p]
                ax.bar(x, mean, width=w * 0.9, color="white" if m == "par" else col, edgecolor=col,
                       hatch="////" if m == "par" else None, lw=1)
                ax.errorbar(x, mean, yerr=[[mean - min(v)], [max(v) - mean]], color="black", lw=0.8, capsize=2)
                if m == "seq":       # one worker can fetch at most once per fetch time
                    ceil = 100 * 1000 / B[f"{p}-{m}-{tc}"]["pooled_median_fetch_ms"] / target
                    if ceil < 108:
                        ax.plot([x - w * 0.55, x + w * 0.55], [ceil, ceil], color="black", lw=1.4, ls=":", zorder=5)
        ax.axhline(99, color="black", lw=0.8, ls="--")
        ax.set_title(f"{tc.upper()}: {target} Hz, deadline {dl[tc]}\n{mtxt} of slots", fontsize=7.5 * FS)
        ax.set_xticks(range(3), [LABEL[p] for p in PLACEMENTS])
        ax.set_ylim(0, 110)
        ax.grid(axis="y", lw=0.4, alpha=0.4)
    axs[0].set_ylabel("achieved rate (% of target)")
    hs = [Patch(color=COLOR[p], label=f"{LABEL[p]}, EDC pull, 1 worker") for p in PLACEMENTS] + [
        Patch(facecolor="white", edgecolor="0.4", hatch="////", label="same, 4 workers"),
        Patch(color=COLOR["source"], label="no EDC, 1 worker (baseline)"),
        Line2D([], [], color="black", ls="--", lw=0.8, label="pass: 99 % of the target rate"),
        Line2D([], [], color="black", ls=":", lw=1.2, label="limit of one worker: 1 / fetch time"),
        Line2D([], [], color="black", lw=0.8, marker="_", ms=6, label="bar: mean of 3 runs; whisker: min-max")]
    fig.legend(handles=hs, loc="lower center", ncol=2, frameon=False, fontsize=7 * FS, bbox_to_anchor=(0.5, -0.27))
    fig.tight_layout()
    savefig(fig, "R9_rate_vs_target")


if __name__ == "__main__":
    fig_rate()
    for k, v in B.items():
        print(f"{k:22s} n={v['n_runs']} pooled={v['pooled_median_fetch_ms']:7.1f} CI={v['ci_runlevel']} "
              f"range={v['run_median_range_ms']} pass={v['pass_runs']}/{v['n_runs']}")
    for d in diffs:
        print("diff", d)
    for k, v in overhead.items():
        print("overhead", k, v)
    for k, v in over100.items():
        print("over100", k, v)
    for p, v in summary_D.items():
        print("D", p, v)
