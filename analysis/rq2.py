"""
rq2.py — RQ2: the cost of EDC governance per data flow, the deployment factors
that set it, and the classes of industrial data flows it permits.

Run from the repository root:
    analysis/.venv/bin/python analysis/rq2.py

Inputs: the valid runs of the 22 October 2026 campaign (common.RUNS), read
from each run's summary.json (scripts/summarize-run.py). Nothing is sent to
any server. Output is deterministic (fixed bootstrap seeds).

Measurement sets used
  A  push, tuned (transfer state-machine wait 50 ms, database
     synchronous_commit off), 20 transfers per TC, 3 repeats per placement
  B  pull on a fixed schedule for 300 s per TC; seq = 1 worker, par = 4
     workers, src = no-EDC baseline straight from the data source
  C  push with EDC defaults (1000 ms waits, synchronous_commit on), one run
     per placement

Definitions
  one-off cost     catalog_ms (catalogue request), negotiation_ms (contract
                   negotiation), setup_ms (pull: transfer request -> address
                   and token available). Paid once per agreement / transfer.
  per-message      push: request_to_received_ms (a new transfer per message,
                   one clock). pull: request_to_received_ms of one fetch (one
                   clock). Warm-up rule (thesis-wide): the FIRST transfer (push)
                   and the FIRST fetch (pull) of each test case in each run are
                   excluded from all statistics. Pull summary records already
                   start at fetch 2; push records are sorted by their sequence
                   number and #1 is dropped here (Set A cells: n = 3 x 19 = 57;
                   Set C: n = 19). Excluded push values are kept in rq2.json.
  data age         source_to_received_ms of each pull record: the data
                   source's timestamp -> last byte at the consumer, corrected
                   with both machines' NTP offsets (summarize-run.py).
  rate, misses     the schedule block of each pull test case
                   (pull-client.py): achieved_hz, missed_pct (deadline misses
                   including skipped slots).

Pass criterion (thesis, Chapter 3): a flow class is governable in a
mode if the per-message time (median) is below the class deadline AND the
target rate is reached with < 1 % missed deadlines. Push was not run at the
target rate (transfers were started one after another), so for push only the
per-message part of the criterion can be checked.

Statistics: medians with percentile-bootstrap 95 % CIs (10,000 resamples;
for samples above 2,000 values the resamples are drawn in chunks to bound
memory, same estimator); two-sided Mann-Whitney U, Holm-corrected within
a family of nine: Set A vs Set C = 3 placements x 3 TCs; EDC pull (1 worker)
vs baseline data age = 3 placements x 3 TCs; one-off costs between
placements = 3 placement pairs x 3 quantities (catalogue, negotiation, setup).

Known outliers (RQ1): six push transfers in Cloud A-r1 (TC1 #12, 13, 17, 18;
TC2 #8, 9) stalled 4.0-15.8 s in the dp_to_source phase. They stay in the
data; only medians and rank tests are used for claims (means/p95 are not).

Outputs
  figures   R6_one_off_costs, R7_size_effect, R8_deployment_factors,
            R9_rate_vs_target, R10_data_age   (common.savefig)
  tables    T5_2_resources, T5_3_classes      (common.write_table)
  numbers   analysis/out/rq2.json             (common.write_numbers)
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from common import (FS, RUNS, PLACEMENTS, LABEL, COLOR, TCS, TC_SHORT, TC_LABEL, TARGET, WIDTH,
                    RESULTS, load, boot_ci, mwu, savefig, write_table, write_numbers)

SIZE = {"tc1": 272, "tc2": 9640, "tc3": 473603}
MODES = ["seq", "par", "src"]
MODE_LABEL = {"seq": "EDC pull, 1 worker", "par": "EDC pull, 4 workers", "src": "No EDC (baseline)"}
MACHINE = {"cloud": "cPouta", "edge": "TAU VM1", "consumer": "Contabo", "source": "TAU VM2"}
CONTAINERS = ["provider-cp", "provider-cp-db", "provider-dp", "provider-dp-db", "consumer-cp", "consumer-dp"]


# ---------------------------------------------------------------- helpers
def ci(values, n=10000, seed=1):
    """Bootstrap CI of the median; chunked for large samples (same estimator as common.boot_ci)."""
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if len(v) <= 2000:
        return boot_ci(v, n=n, seed=seed)
    rng = np.random.default_rng(seed)
    meds = []
    chunk = max(1, int(2e7 // len(v)))
    done = 0
    while done < n:
        k = min(chunk, n - done)
        meds.append(np.median(rng.choice(v, size=(k, len(v)), replace=True), axis=1))
        done += k
    meds = np.concatenate(meds)
    return (float(np.quantile(meds, 0.025)), float(np.quantile(meds, 0.975)))


def med_ci(values):
    v = [x for x in values if x is not None]
    lo, hi = ci(v)
    return {"n": len(v), "median": float(np.median(v)), "ci95": [lo, hi],
            "p95": float(np.percentile(v, 95))}


def med_ci_runs(runs, tc, n=10000, seed=1):
    """As med_ci for Set A, but the CI is run-level (hierarchical bootstrap: draw
    runs with replacement, then transfers within each drawn run; review phase 3)."""
    groups = [np.asarray(push_vals([r], tc), float) for r in runs]
    out = med_ci(np.concatenate(groups).tolist())
    rng = np.random.default_rng(seed)
    meds = np.empty(n)
    for k in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        meds[k] = np.median(np.concatenate([rng.choice(groups[i], len(groups[i])) for i in pick]))
    out["ci95_transfer"] = out["ci95"]
    out["ci95"] = [float(np.quantile(meds, 0.025)), float(np.quantile(meds, 0.975))]
    return out


def r(x, d=1):
    return None if x is None else round(float(x), d)


def push_tc(run, tc):
    return load(run)["test_cases"][tc]


def pull_tc(run, tc):
    return load(run)["test_cases"]["pull-" + tc]


def _seq(rec):
    """Transfer number within the test case, from run_id 'tcN-<k>-<nanos>'."""
    return int(rec["run_id"].split("-")[1])


def push_records(run, tc, warm=False):
    """Push records without the first (warm-up) transfer; warm=True returns only the first."""
    recs = sorted(push_tc(run, tc)["records"], key=_seq)
    return recs[:1] if warm else recs[1:]


def push_vals(runs, tc, key="request_to_received_ms"):
    out = []
    for run in runs:
        out += [rec[key] for rec in push_records(run, tc) if rec.get(key) is not None]
    return out


def push_phase(runs, tc, phase):
    out = []
    for run in runs:
        out += [rec["phases_ms"][phase] for rec in push_records(run, tc)
                if rec.get("phases_ms") and rec["phases_ms"].get(phase) is not None]
    return out


def holm(pvals):
    """Holm (1979) step-down adjusted p-values, same order as the input."""
    p = np.asarray(pvals, dtype=float)
    order = np.argsort(p)
    m = len(p)
    adj = np.empty(m)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, (m - rank) * p[i])
        adj[i] = min(1.0, run)
    return adj.tolist()


def pull_vals(run, tc, key="request_to_received_ms"):
    return [rec[key] for rec in pull_tc(run, tc)["records"] if rec.get(key) is not None]


def a_runs(p):
    return [RUNS["A"][(p, k)] for k in (1, 2, 3)]


def fmt_ci(d, unit=""):
    return f"{d['median']:.0f} [{d['ci95'][0]:.0f}, {d['ci95'][1]:.0f}]{unit}"


N = {}          # everything quoted, written to rq2.json
problems = []   # data checks that did not pass

# ---------------------------------------------------------------- data checks
for p in PLACEMENTS:
    for run in a_runs(p) + [RUNS["C"][p]]:
        for tc in TCS:
            t = push_tc(run, tc)
            if t["transfers_received"] != t["transfers_requested"] or t["negotiation_retries"] or t["transfer_retries"]:
                problems.append(f"{run} {tc}: received {t['transfers_received']}/{t['transfers_requested']}, "
                                f"retries {t['negotiation_retries']}/{t['transfer_retries']}")
    for m in MODES:
        run = RUNS["B"][(p, m)]
        for tc in TCS:
            t = pull_tc(run, tc)
            s = t["schedule"]
            if t.get("error") or s["ok"] != s["fetched"]:
                problems.append(f"{run} {tc}: error={t.get('error')} ok {s['ok']}/{s['fetched']}")
            if len(t["records"]) != s["fetched"] - 1:
                problems.append(f"{run} {tc}: {len(t['records'])} records for {s['fetched']} fetches")
N["data_checks"] = {"problems": problems,
                    "warm_up_rule": "first push transfer and first pull fetch of each test case in each run excluded (Set A n = 57 per cell, Set C n = 19)"}
N["push_warmup_excluded_ms"] = {
    s_: {p: {tc: [push_records(run, tc, warm=True)[0]["request_to_received_ms"] for run in runs_]
             for tc in TCS} for p, runs_ in ((p, a_runs(p) if s_ == "A" else [RUNS["C"][p]]) for p in PLACEMENTS)}
    for s_ in ("A", "C")}

# clock offsets per run (max |median offset|) — sanity of data-age correction
offs = {}
for p in PLACEMENTS:
    for m in MODES:
        run = RUNS["B"][(p, m)]
        offs[run] = {k: v["offset_ms"]["median"] for k, v in load(run)["clocks"].items()}
N["clock_offsets_ms_setB"] = offs

# ---------------------------------------------------------------- 1. one-off costs (R6)
one_off = {}
for p in PLACEMENTS:
    cat_a = [push_tc(run, tc)["catalog_ms"] for run in a_runs(p) for tc in TCS]
    neg_a = [push_tc(run, tc)["negotiation_ms"] for run in a_runs(p) for tc in TCS]
    cat_c = [push_tc(RUNS["C"][p], tc)["catalog_ms"] for tc in TCS]
    neg_c = [push_tc(RUNS["C"][p], tc)["negotiation_ms"] for tc in TCS]
    b_runs = [RUNS["B"][(p, "seq")], RUNS["B"][(p, "par")]]
    cat_b = [pull_tc(run, tc)["catalog_ms"] for run in b_runs for tc in TCS]
    neg_b = [pull_tc(run, tc)["negotiation_ms"] for run in b_runs for tc in TCS]
    setup = [pull_tc(run, tc)["setup_ms"] for run in b_runs for tc in TCS]
    first_cat = [push_tc(run, "tc1")["catalog_ms"] for run in a_runs(p)]
    later_cat = [push_tc(run, tc)["catalog_ms"] for run in a_runs(p) for tc in ("tc2", "tc3")]
    one_off[p] = {
        "catalog_A": med_ci(cat_a) | {"values": cat_a},
        "negotiation_A": med_ci(neg_a) | {"values": neg_a},
        "catalog_C": {"values": cat_c, "median": float(np.median(cat_c))},
        "negotiation_C": {"values": neg_c, "median": float(np.median(neg_c))},
        "catalog_B": med_ci(cat_b), "negotiation_B": med_ci(neg_b),
        "setup_B": med_ci(setup) | {"values": setup},
        "catalog_A_first_tc1": first_cat, "catalog_A_tc2_tc3_median": float(np.median(later_cat)),
    }
# placement comparisons (Set A + B pooled, tuned settings, n = 15 each)
pairs = [("hybrid", "edge"), ("hybrid", "cloud"), ("edge", "cloud")]
plc_tests = {}
for what in ("negotiation", "catalog"):
    vals = {p: one_off[p][f"{what}_A"]["values"] + [pull_tc(RUNS["B"][(p, m)], tc)[f"{what}_ms"]
                                                     for m in ("seq", "par") for tc in TCS] for p in PLACEMENTS}
    plc_tests[what] = {f"{a}_vs_{b}": dict(zip(("U", "p"), mwu(vals[a], vals[b]))) for a, b in pairs}
    for p in PLACEMENTS:
        one_off[p][f"{what}_AB_median"] = float(np.median(vals[p]))
vals = {p: one_off[p]["setup_B"]["values"] for p in PLACEMENTS}
plc_tests["setup"] = {f"{a}_vs_{b}": dict(zip(("U", "p"), mwu(vals[a], vals[b]))) for a, b in pairs}
keys = [(w, k) for w in plc_tests for k in plc_tests[w]]
for (w, k), ph in zip(keys, holm([plc_tests[w][k]["p"] for w, k in keys])):
    plc_tests[w][k]["p_holm"] = ph
N["one_off"] = one_off
N["one_off_placement_mwu"] = plc_tests
# Set A vs Set C one-off costs, pooled over placements (27 vs 9 values; C is one run per placement)
N["one_off_A_vs_C"] = {}
for what in ("negotiation", "catalog"):
    a = sum((one_off[p][f"{what}_A"]["values"] for p in PLACEMENTS), [])
    c = sum((one_off[p][f"{what}_C"]["values"] for p in PLACEMENTS), [])
    U, pv = mwu(a, c)
    N["one_off_A_vs_C"][what] = {"A": med_ci(a), "C": med_ci(c), "U": U, "p": pv}

fig, axs = plt.subplots(1, 3, figsize=(WIDTH, 2.6), sharey=False)
jit = np.linspace(-0.18, 0.18, 9)
for ax, (key, title) in zip(axs, [("catalog", "Catalogue request"), ("negotiation", "Contract negotiation"),
                                  ("setup", "Pull transfer setup")]):
    for i, p in enumerate(PLACEMENTS):
        if key == "setup":
            v = one_off[p]["setup_B"]["values"]
            ax.scatter(i + np.linspace(-0.15, 0.15, len(v)), v, s=14, color=COLOR[p], marker="^", alpha=0.85, lw=0)
            d = one_off[p]["setup_B"]
        else:
            v = one_off[p][f"{key}_A"]["values"]
            ax.scatter(i - 0.12 + jit[:len(v)] * 0.6, v, s=14, color=COLOR[p], alpha=0.85, lw=0)
            vc = one_off[p][f"{key}_C"]["values"]
            ax.scatter(np.full(len(vc), i + 0.25), vc, s=22, color=COLOR[p], marker="x", lw=1.2)
            d = one_off[p][f"{key}_A"]
        ax.hlines(d["median"], i - 0.3, i + 0.3, color="black", lw=1.5)
    ax.set_xticks(range(3), [LABEL[p] for p in PLACEMENTS])
    ax.set_title(title)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", lw=0.4, alpha=0.4)
axs[0].set_ylabel("Time (ms)")
handles = [Line2D([], [], marker="o", ls="", color="0.3", ms=4, label="Set A (tuned), per TC and run"),
           Line2D([], [], marker="x", ls="", color="0.3", ms=5, label="Set C (defaults)"),
           Line2D([], [], marker="^", ls="", color="0.3", ms=4, label="Set B pull, per TC and run"),
           Line2D([], [], color="black", lw=1.5, label="Median (Set A / Set B)")]
fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.08))
fig.tight_layout()
savefig(fig, "R6_one_off_costs")

# ---------------------------------------------------------------- 2. per-message cost and size (R7)
per_msg = {}
for tc in TCS:
    per_msg[tc] = {}
    for p in PLACEMENTS:
        per_msg[tc][p] = {"push_A": med_ci_runs(a_runs(p), tc),
                          "push_C": med_ci(push_vals([RUNS["C"][p]], tc)),
                          "pull_seq": med_ci(pull_vals(RUNS["B"][(p, "seq")], tc)),
                          "pull_par": med_ci(pull_vals(RUNS["B"][(p, "par")], tc)),
                          "baseline": med_ci(pull_vals(RUNS["B"][(p, "src")], tc))}
    per_msg[tc]["baseline_all"] = med_ci(sum((pull_vals(RUNS["B"][(p, "src")], tc) for p in PLACEMENTS), []))
N["per_message_ms"] = per_msg

# push governance phases (tuned) — where the per-transfer time goes
push_phases = {tc: {p: {ph: float(np.median(push_phase(a_runs(p), tc, ph)))
                        for ph in ("request_to_provider", "provider_to_dp", "dp_to_source", "source_to_received")}
                    for p in PLACEMENTS} for tc in TCS}
N["push_phase_medians_A_ms"] = push_phases

# size ratios TC1 -> TC3 (size x 1741)
size_eff = {}
for p in PLACEMENTS:
    for kind in ("push_A", "pull_seq", "baseline"):
        a, b = per_msg["tc1"][p][kind]["median"], per_msg["tc3"][p][kind]["median"]
        size_eff[f"{p}_{kind}"] = {"tc1_ms": a, "tc2_ms": per_msg["tc2"][p][kind]["median"], "tc3_ms": b,
                                   "ratio_tc3_tc1": b / a,
                                   "loglog_slope_tc2_tc3": float(np.log(b / per_msg["tc2"][p][kind]["median"]) /
                                                                 np.log(SIZE["tc3"] / SIZE["tc2"])),
                                   "tc3_goodput_mbit_s": SIZE["tc3"] * 8 / (b / 1000) / 1e6}
N["size_effect"] = size_eff
N["size_effect_note"] = "Only the three TC payloads (272 B, 9,640 B, 473,603 B); the planned payload sweep (Set S) was not run."

fig, ax = plt.subplots(figsize=(WIDTH, 3.3))
xs = np.array([SIZE[tc] for tc in TCS])
off = {"hybrid": 0.93, "edge": 1.0, "cloud": 1.07}
for p in PLACEMENTS:
    for kind, ls, mk in (("push_A", "-", "o"), ("pull_seq", "--", "s")):
        y = [per_msg[tc][p][kind]["median"] for tc in TCS]
        lo = [per_msg[tc][p][kind]["ci95"][0] for tc in TCS]
        hi = [per_msg[tc][p][kind]["ci95"][1] for tc in TCS]
        ax.errorbar(xs * off[p], y, yerr=[np.subtract(y, lo), np.subtract(hi, y)], color=COLOR[p], ls=ls,
                    marker=mk, ms=4, lw=1.2, capsize=2)
y = [per_msg[tc]["baseline_all"]["median"] for tc in TCS]
ax.plot(xs, y, color=COLOR["source"], ls=":", marker="D", ms=4, lw=1.5)
for tc in TCS:
    ax.axhline(TARGET[tc][1], color="0.6", lw=0.5, ls="-", zorder=0)
for tc, txt in (("tc1", "TC1 deadline 20 ms"), ("tc3", "TC3 deadline 41.7 ms"), ("tc2", "TC2 deadline 1 s")):
    ax.text(8.8e5, TARGET[tc][1] * 1.06, txt, fontsize=7 * FS, color="0.4", ha="right", va="bottom")
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xticks(xs, ["TC1\n272 B", "TC2\n9,640 B", "TC3\n473,603 B"])
ax.minorticks_off()
ax.set_xlim(150, 9e5); ax.set_ylim(15, 3000)
ax.set_xlabel("Payload size (log scale)")
ax.set_ylabel("Median per-message time (ms, log)")
ax.grid(lw=0.4, alpha=0.4)
handles = [Line2D([], [], color=COLOR[p], lw=2, label=LABEL[p]) for p in PLACEMENTS] + [
    Line2D([], [], color="0.3", ls="-", marker="o", ms=4, label="EDC push (Set A)"),
    Line2D([], [], color="0.3", ls="--", marker="s", ms=4, label="EDC pull, 1 worker (Set B)"),
    Line2D([], [], color=COLOR["source"], ls=":", marker="D", ms=4, label="No EDC (baseline)")]
ax.legend(handles=handles, loc="upper center", ncol=3, frameon=False, fontsize=7 * FS, bbox_to_anchor=(0.5, -0.2))
ax.text(0.01, 0.98, "Three payload sizes only (TC1-TC3); no size sweep was run.\nBars: 95 % bootstrap CI of the median.",
        transform=ax.transAxes, ha="left", va="top", fontsize=7 * FS, color="0.35")
fig.tight_layout()
savefig(fig, "R7_size_effect")

# ---------------------------------------------------------------- 3. deployment factors: Set C vs Set A (R8)
factors = {}
for p in PLACEMENTS:
    factors[p] = {}
    for tc in TCS:
        a = push_vals(a_runs(p), tc)
        c = push_vals([RUNS["C"][p]], tc)
        U, pv = mwu(a, c)
        # Set A: run-level interval, as in the text; Set C (one run): median only
        da, dc = med_ci_runs(a_runs(p), tc), med_ci(c)
        ph = {}
        for phase in ("request_to_provider", "provider_to_dp", "dp_to_source", "source_to_received"):
            ma = float(np.median(push_phase(a_runs(p), tc, phase)))
            mc = float(np.median(push_phase([RUNS["C"][p]], tc, phase)))
            ph[phase] = {"A": ma, "C": mc, "diff": mc - ma}
        factors[p][tc] = {"A": da, "C": dc, "diff_ms": dc["median"] - da["median"],
                          "ratio": dc["median"] / da["median"], "U": U, "p": pv, "phases": ph}
# per-repeat medians of Set A, to show C lies outside the repeat-to-repeat spread
for p in PLACEMENTS:
    for tc in TCS:
        factors[p][tc]["A_repeat_medians"] = [float(np.median(push_vals([run], tc))) for run in a_runs(p)]
cells = [(p, tc) for p in PLACEMENTS for tc in TCS]
for (p, tc), ph in zip(cells, holm([factors[p][tc]["p"] for p, tc in cells])):
    factors[p][tc]["p_holm"] = ph
N["setC_vs_setA"] = factors
N["setC_settings"] = {p: {k: load(RUNS["C"][p])["meta"].get(k) for k in ("timing", "edc_transfer_wait_ms",
                                                                         "edc_negotiation_wait_ms")} for p in PLACEMENTS}
N["setA_settings"] = {p: {k: load(a_runs(p)[0])["meta"].get(k) for k in ("timing", "edc_transfer_wait_ms",
                                                                         "edc_negotiation_wait_ms")} for p in PLACEMENTS}

fig, axs = plt.subplots(1, 3, figsize=(WIDTH, 3.3), sharey=True)
for ax, tc in zip(axs, TCS):
    for i, p in enumerate(PLACEMENTS):
        a, c = factors[p][tc]["A"], factors[p][tc]["C"]
        ax.errorbar(i - 0.15, a["median"], yerr=[[a["median"] - a["ci95"][0]], [a["ci95"][1] - a["median"]]],
                    marker="o", ms=6, color=COLOR[p], mfc=COLOR[p], capsize=3, lw=1.2)
        # Set C has one run: no interval is drawn (thesis Section 3.4)
        ax.plot(i + 0.15, c["median"], marker="s", ms=6, color=COLOR[p], mfc="white", ls="")
        f = factors[p][tc]
        ax.text(i, f["C"]["median"] * 1.3, f"×{f['ratio']:.1f}",
                ha="center", va="bottom", fontsize=7 * FS)
    ax.set_xticks(range(3), [LABEL[p] for p in PLACEMENTS])
    ax.set_title(TC_LABEL[tc], fontsize=8 * FS)
    ax.set_yscale("log")
    ax.set_xlim(-0.5, 2.5)
    ax.grid(axis="y", lw=0.4, alpha=0.4)
axs[0].set_ylim(150, 9000)
axs[0].set_yticks([200, 500, 1000, 2000, 5000], ["200", "500", "1000", "2000", "5000"])
axs[0].yaxis.set_minor_formatter(plt.NullFormatter())
axs[0].set_ylabel("median push time (ms, log)")
handles = [Line2D([], [], marker="o", ls="", color="0.3", ms=5, label="Set A: diagnostic profile, 3 runs"),
           Line2D([], [], marker="s", ls="", color="0.3", mfc="white", ms=5,
                  label="Set C: EDC defaults, 1 run"),
           Line2D([], [], marker="", ls="-", color="0.3", lw=1.2, label="bar (Set A): run-level 95 % CI"),
           Line2D([], [], ls="", label="×n: Set C median ÷ Set A median")]
fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, fontsize=7.5 * FS, bbox_to_anchor=(0.5, -0.16))
fig.tight_layout()
savefig(fig, "R8_deployment_factors")

# ---------------------------------------------------------------- 4. resources (T5_2)
def res_rows(runs, tcs, pull=False):
    """{container: dict} with at-rest and during medians over the given runs and TCs."""
    out = {}
    for c in CONTAINERS:
        rest_cpu, rest_mem, cpu, mem, peak, machine = [], [], [], [], [], None
        for run in runs:
            for tc in tcs:
                t = pull_tc(run, tc) if pull else push_tc(run, tc)
                rr = t["resources"].get(c)
                if not rr:
                    continue
                rest_cpu.append(rr["at_rest_cpu_pct"]); rest_mem.append(rr["at_rest_mem_mb"])
                du = rr.get("during") or {}
                machine = du.get("machine", machine)
                if du.get("cpu_pct", {}).get("n"):
                    cpu.append(du["cpu_pct"]["median"]); mem.append(du["mem_mb"]["median"])
                    peak.append(du["cpu_pct"]["max"])
        out[c] = {"machine": machine, "rest_cpu": float(np.median(rest_cpu)), "rest_mem": float(np.median(rest_mem)),
                  "during_cpu": float(np.median(cpu)), "during_mem": float(np.median(mem)),
                  "peak_cpu": float(np.max(peak)), "n_cases": len(cpu)}
    return out


resources = {}
for p in PLACEMENTS:
    resources[p] = {"push_A": res_rows(a_runs(p), TCS),
                    "pull_seq": res_rows([RUNS["B"][(p, "seq")]], TCS, pull=True),
                    "pull_par": res_rows([RUNS["B"][(p, "par")]], TCS, pull=True),
                    "pull_par_tc1": res_rows([RUNS["B"][(p, "par")]], ["tc1"], pull=True),
                    "pull_par_tc3": res_rows([RUNS["B"][(p, "par")]], ["tc3"], pull=True)}
N["resources"] = resources
N["resources_note"] = ("docker stats CPU % (100 % = one core; each connector container limited to 4 CPU / 4 GB). "
                       "at rest = before the test case; during = median of the samples taken during it; "
                       "values are medians over runs and TCs; peak = highest single sample.")

lines = [r"\begin{tabular}{llll rr rr rr r}", r"\toprule",
         r" & & & & \multicolumn{2}{c}{At rest} & \multicolumn{2}{c}{Push (Set A)} & "
         r"\multicolumn{2}{c}{Pull, 4 workers, TC1 (Set B)} & Peak \\",
         r"\cmidrule(lr){5-6}\cmidrule(lr){7-8}\cmidrule(lr){9-10}",
         r"Placement & Container & Machine & Site & CPU \% & MB & CPU \% & MB & CPU \% & MB & CPU \% \\", r"\midrule"]
for p in PLACEMENTS:
    for j, c in enumerate(CONTAINERS):
        a, b = resources[p]["push_A"][c], resources[p]["pull_par_tc1"][c]
        peak = max(a["peak_cpu"], b["peak_cpu"], resources[p]["pull_seq"][c]["peak_cpu"])
        m = a["machine"]
        lines.append(f"{LABEL[p] if j == 0 else ''} & {c} & {MACHINE.get(m, m)} & {m} & "
                     f"{a['rest_cpu']:.0f} & {a['rest_mem']:.0f} & {a['during_cpu']:.0f} & {a['during_mem']:.0f} & "
                     f"{b['during_cpu']:.0f} & {b['during_mem']:.0f} & {peak:.0f} \\\\")
    lines.append(r"\midrule" if p != PLACEMENTS[-1] else r"\bottomrule")
lines.append(r"\end{tabular}")
write_table("T5_2_resources", "\n".join(lines) + "\n")

# ---------------------------------------------------------------- 5. rate vs target (R9)
rate = {}
for p in PLACEMENTS:
    rate[p] = {}
    for m in MODES:
        rate[p][m] = {}
        for tc in TCS:
            s = pull_tc(RUNS["B"][(p, m)], tc)["schedule"]
            rec = pull_tc(RUNS["B"][(p, m)], tc)["records"]
            rate[p][m][tc] = {"target_hz": s["rate_hz"], "achieved_hz": s["achieved_hz"],
                              "achieved_pct_of_target": 100 * s["achieved_hz"] / s["rate_hz"],
                              "missed_pct": s["missed_pct"], "slots": s["slots"], "fetched": s["fetched"],
                              "skipped_slots": s["skipped_slots"], "deadline_met": s["deadline_met"],
                              "median_late_ms": float(np.median([x["late_ms"] for x in rec]))}
N["rate"] = rate

DL_PLAIN = {"tc1": "20 ms", "tc2": "1 s", "tc3": "41.7 ms"}
fig, axs = plt.subplots(2, 3, figsize=(WIDTH, 4.4), sharex="col")
w = 0.26
for k, tc in enumerate(TCS):
    for i, p in enumerate(PLACEMENTS):
        for j, m in enumerate(MODES):
            d = rate[p][m][tc]
            col = COLOR["source"] if m == "src" else COLOR[p]
            hatch = "////" if m == "par" else None
            x = i + (j - 1) * w
            for row, val in ((0, d["achieved_pct_of_target"]), (1, d["missed_pct"])):
                axs[row, k].bar(x, val, width=w * 0.9, color=col if m != "par" else "white", edgecolor=col,
                                hatch=hatch, lw=1)
    axs[0, k].axhline(100, color="black", lw=0.8, ls="--")
    axs[1, k].axhline(1, color="black", lw=0.8, ls="--")
    axs[0, k].set_title(f"{TC_SHORT[tc]}: {TARGET[tc][0]} Hz\ndeadline {DL_PLAIN[tc]}", fontsize=8 * FS)
    if all(rate[p][m][tc]["missed_pct"] == 0 for p in PLACEMENTS for m in MODES):
        axs[1, k].text(1, 50, "0 % missed\nin every run", ha="center", va="center", fontsize=8 * FS, color="0.3")
    axs[0, k].set_ylim(0, 110); axs[1, k].set_ylim(0, 105)
    axs[1, k].set_xticks(range(3), [LABEL[p] for p in PLACEMENTS])
    for row in (0, 1):
        axs[row, k].grid(axis="y", lw=0.4, alpha=0.4)
axs[0, 0].set_ylabel("Achieved rate\n(% of target)")
axs[1, 0].set_ylabel("Missed deadlines (%)")
handles = [Patch(color="0.4", label="EDC pull, 1 worker"),
           Patch(facecolor="white", edgecolor="0.4", hatch="////", label="EDC pull, 4 workers"),
           Patch(color=COLOR["source"], label="No EDC (baseline, 1 worker, same window)"),
           Line2D([], [], color="black", ls="--", lw=0.8, label="Target rate / 1 % miss limit")]
fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.09), fontsize=7 * FS)
fig.text(0.5, -0.16, "Bar colour = placement of the provider connector\n(Hybrid blue, Edge orange, Cloud green); "
         "baseline bars grey.", ha="center", fontsize=7 * FS, color="0.35")
fig.tight_layout()
# Superseded in the thesis by repeats_BD.py (all three runs per condition, review of 29 Oct 2026);
# kept as a preview of the protocol run only.
savefig(fig, "R9_rate_vs_target_protocol_run")

# ---------------------------------------------------------------- 6. data age (R10)
age = {}
for p in PLACEMENTS:
    age[p] = {}
    for tc in TCS:
        age[p][tc] = {}
        for m in MODES:
            age[p][tc][m] = med_ci(pull_vals(RUNS["B"][(p, m)], tc, "source_to_received_ms"))
        e = pull_vals(RUNS["B"][(p, "seq")], tc, "source_to_received_ms")
        b = pull_vals(RUNS["B"][(p, "src")], tc, "source_to_received_ms")
        U, pv = mwu(e, b)
        age[p][tc]["seq_minus_baseline_ms"] = age[p][tc]["seq"]["median"] - age[p][tc]["src"]["median"]
        age[p][tc]["seq_vs_baseline_mwu"] = {"U": U, "p": pv}
        age[p][tc]["seq_share_within_deadline_pct"] = 100 * float(np.mean(np.asarray(e) < TARGET[tc][1]))
        age[p][tc]["baseline_share_within_deadline_pct"] = 100 * float(np.mean(np.asarray(b) < TARGET[tc][1]))
cells = [(p, tc) for p in PLACEMENTS for tc in TCS]
for (p, tc), ph in zip(cells, holm([age[p][tc]["seq_vs_baseline_mwu"]["p"] for p, tc in cells])):
    age[p][tc]["seq_vs_baseline_mwu"]["p_holm"] = ph
N["data_age_ms"] = age

fig, axs = plt.subplots(1, 3, figsize=(WIDTH, 2.9), sharey=False)
for ax, tc in zip(axs, TCS):
    data, pos, cols, hat = [], [], [], []
    for i, p in enumerate(PLACEMENTS):
        for j, m in enumerate(MODES):
            data.append(pull_vals(RUNS["B"][(p, m)], tc, "source_to_received_ms"))
            pos.append(i + (j - 1) * 0.28)
            cols.append(COLOR["source"] if m == "src" else COLOR[p])
            hat.append("////" if m == "par" else None)
    bp = ax.boxplot(data, positions=pos, widths=0.22, whis=(5, 95), showfliers=False, patch_artist=True,
                    medianprops={"color": "black", "lw": 1.2})
    for patch, c, h, m in zip(bp["boxes"], cols, hat, MODES * 3):
        patch.set_facecolor("white" if m == "par" else c); patch.set_edgecolor(c); patch.set_hatch(h)
        patch.set_alpha(0.9)
    ax.set_ylim(bottom=0)
    if tc == "tc2":
        ax.set_ylim(0, 80)
        ax.text(1, 76, "deadline 1 s: off scale", ha="center", va="top", fontsize=7 * FS, color="0.3")
    else:
        ax.axhline(TARGET[tc][1], color="black", ls="--", lw=0.8)
    ax.set_xticks(range(3), [LABEL[p] for p in PLACEMENTS])
    ax.set_title(f"{TC_SHORT[tc]} (deadline {DL_PLAIN[tc]})", fontsize=8 * FS)
    ax.grid(axis="y", lw=0.4, alpha=0.4)
axs[0].set_ylabel("Data age at arrival (ms)")
handles = [Patch(color="0.4", label="EDC pull, 1 worker"),
           Patch(facecolor="white", edgecolor="0.4", hatch="////", label="EDC pull, 4 workers"),
           Patch(color=COLOR["source"], label="No EDC (baseline)"),
           Line2D([], [], color="black", ls="--", lw=0.8, label="Deadline")]
fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.07), fontsize=7 * FS)
fig.text(0.5, -0.12, "Source timestamp to last byte at the consumer, clock-corrected. Box: quartiles; whiskers: 5th-95th percentile.",
         ha="center", fontsize=7 * FS, color="0.35")
fig.tight_layout()
savefig(fig, "R10_data_age")

# ---------------------------------------------------------------- 7. classification (T5_3)
CLASSES = [
    ("tc1", "Hard real-time control (control-to-control, closed loop)"),
    ("tc2", "Soft real-time monitoring (batched vibration sensor)"),
    ("tc3", "Soft real-time video stream (zlib-compressed image frames)"),
]


def pull_pass(p, m, tc):
    d = rate[p][m][tc]
    med = per_msg[tc][p]["pull_seq" if m == "seq" else "pull_par" if m == "par" else "baseline"]["median"]
    return med < TARGET[tc][1] and d["missed_pct"] < 1 and d["achieved_hz"] >= 0.99 * d["target_hz"]


def push_ok(p, tc):
    return per_msg[tc][p]["push_A"]["median"] < TARGET[tc][1]


# push: observed sequential issue interval (driver started the next transfer when the previous one arrived)
push_interval = {}
for p in PLACEMENTS:
    iv = []
    for run in a_runs(p):
        for tc in TCS:
            starts = sorted(float(x.split("|")[1]) for x in
                            (RESULTS / run / f"created-{tc}.tsv").read_text().split())
            iv += list(np.diff(starts))
    push_interval[p] = float(np.median(iv))
N["push_issue_interval_ms_median"] = push_interval

classes = {}
for tc, name in CLASSES:
    c = {"class": name, "deadline_ms": TARGET[tc][1], "target_hz": TARGET[tc][0]}
    c["push_pass"] = {p: push_ok(p, tc) for p in PLACEMENTS}
    for m in MODES:
        c[f"{m}_pass"] = {p: pull_pass(p, m, tc) for p in PLACEMENTS}
    edc_any = any(c["seq_pass"].values()) or any(c["par_pass"].values())
    edc_all = all(c["seq_pass"].values()) or all(c["par_pass"].values())
    base_all = all(c["src_pass"].values())
    base_any = any(c["src_pass"].values())
    if edc_all and base_all:
        verdict, cause = "Governable (pull, every placement)", "none"
    elif not edc_any and not base_any:
        verdict, cause = "Not governable", "network (baseline also fails)"
    elif not edc_any and base_all:
        verdict, cause = "Not governable", "EDC (baseline passes)"
    else:
        verdict, cause = "Mixed", "see per-placement values"
    c["verdict"], c["cause"] = verdict, cause
    classes[tc] = c
N["classes"] = classes


def rng_txt(vals, fmt="{:.0f}"):
    lo, hi = min(vals), max(vals)
    # compare as printed: rounding both to integers collapsed 3.7--3.9 Hz into "3.7"
    return fmt.format(lo) if fmt.format(lo) == fmt.format(hi) else f"{fmt.format(lo)}--{fmt.format(hi)}"


def mark(ok):
    return r"\checkmark" if ok else r"$\times$"


DL_TXT = {"tc1": "20\\,ms", "tc2": "1\\,s", "tc3": "41.7\\,ms"}
lines = [r"\begin{tabular}{p{2.4cm} l p{1.4cm} p{1.7cm} p{1.9cm} p{1.9cm} p{1.9cm} p{1.3cm} p{1.5cm} p{1.8cm}}", r"\toprule",
         r"Data-flow class & TC & Deadline / rate & EDC push (Set A), median ms & EDC pull, 1 worker: ms; Hz; missed & "
         r"EDC pull, 4 workers: ms; Hz; missed & No EDC baseline: ms; Hz; missed & EDC pull adds, ms & Verdict & Cause of failure \\",
         r"\midrule"]
for tc, name in CLASSES:
    c = classes[tc]
    push_ms = [per_msg[tc][p]["push_A"]["median"] for p in PLACEMENTS]
    cells = []
    for m, key in (("seq", "pull_seq"), ("par", "pull_par"), ("src", "baseline")):
        ms = [per_msg[tc][p][key]["median"] for p in PLACEMENTS]
        hz = [rate[p][m][tc]["achieved_hz"] for p in PLACEMENTS]
        mi = [rate[p][m][tc]["missed_pct"] for p in PLACEMENTS]
        ok = all(c[f"{m}_pass"].values())
        cells.append(f"{rng_txt(ms)}; {rng_txt(hz, '{:.1f}')}; {rng_txt(mi, '{:.0f}')}\\,\\% {mark(ok)}")
    pushcell = f"{rng_txt(push_ms)} {mark(all(c['push_pass'].values()))}"
    added = [per_msg[tc][p]["pull_seq"]["median"] - per_msg[tc][p]["baseline"]["median"] for p in PLACEMENTS]
    c["edc_pull_adds_ms"] = dict(zip(PLACEMENTS, added))
    lines.append(f"{name} & {TC_SHORT[tc]} & {DL_TXT[tc]} / {TARGET[tc][0]}\\,Hz & {pushcell}$^a$ & "
                 f"{cells[0]} & {cells[1]} & {cells[2]} & +{rng_txt(added)} & {c['verdict']} & {c['cause']} \\\\")
lines += [r"\bottomrule", r"\end{tabular}",
          r"% ranges are over the three placements (Hybrid, Edge, Cloud).",
          r"% a: push checks only the per-message part of the criterion; push was not run at the target rate."]
write_table("T5_3_classes", "\n".join(lines) + "\n")

write_numbers("rq2", N)

# ---------------------------------------------------------------- console summary
print("data problems:", problems or "none")
for p in PLACEMENTS:
    o = one_off[p]
    print(f"{p:7s} catalog A {fmt_ci(o['catalog_A'])}  neg A {fmt_ci(o['negotiation_A'])}  "
          f"neg C {o['negotiation_C']['values']}  setup B {fmt_ci(o['setup_B'])}  first cat {o['catalog_A_first_tc1']}")
print("placement MWU", plc_tests)
for tc in TCS:
    for p in PLACEMENTS:
        d = per_msg[tc][p]
        f = factors[p][tc]
        print(f"{tc} {p:7s} push {fmt_ci(d['push_A'])} n={d['push_A']['n']} C {fmt_ci(d['push_C'])} n={d['push_C']['n']} (x{f['ratio']:.1f}, +{f['diff_ms']:.0f}, p_holm={f['p_holm']:.1e}) "
              f"seq {fmt_ci(d['pull_seq'])} par {fmt_ci(d['pull_par'])} base {fmt_ci(d['baseline'])}")
    print(f"{tc} baseline all {fmt_ci(per_msg[tc]['baseline_all'])}")
for p in PLACEMENTS:
    for tc in TCS:
        print(p, tc, {k: (round(v['A']), round(v['C'])) for k, v in factors[p][tc]["phases"].items()},
              "A repeats", [round(x) for x in factors[p][tc]["A_repeat_medians"]])
for p in PLACEMENTS:
    for m in MODES:
        print(p, m, {tc: (rate[p][m][tc]["achieved_hz"], rate[p][m][tc]["missed_pct"]) for tc in TCS})
for p in PLACEMENTS:
    print(p, "age", {tc: {m: round(age[p][tc][m]["median"], 1) for m in MODES} for tc in TCS})
print("push phases", push_phases)
print("push interval", push_interval)
print("size", {k: (round(v["ratio_tc3_tc1"], 1), round(v["loglog_slope_tc2_tc3"], 2), round(v["tc3_goodput_mbit_s"], 1))
               for k, v in size_eff.items()})
for tc in TCS:
    print(tc, classes[tc]["verdict"], classes[tc]["cause"],
          {m: classes[tc][f"{m}_pass"] for m in ("push", "seq", "par", "src")})
for p in PLACEMENTS:
    for c in CONTAINERS:
        a = resources[p]["push_A"][c]; b = resources[p]["pull_par"][c]
        print(p, c, a["machine"], round(a["rest_cpu"]), round(a["rest_mem"]), round(a["during_cpu"]),
              round(b["during_cpu"]), round(b["during_mem"]), round(max(a["peak_cpu"], b["peak_cpu"])))
