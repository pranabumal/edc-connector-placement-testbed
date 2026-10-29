"""
perf_models.py — checks of the placement effect against published performance
models, and tail statistics, for the Discussion and Results chapters.

Run from the repository root:  analysis/.venv/bin/python analysis/perf_models.py

1. Network centricity (Verma & de Mel 2017, IEEE BigData, doi 10.1109/BigData.2017.8258505)
   A pull fetch is a request–response ("service-oriented") exchange. With the
   cloud DP as the central site, the response time is R_c = K·L0 + P and with an
   edge DP R_e = K·L1 + P, where L0 and L1 are the round-trip times of the path
   consumer → DP → source in the two cases and L2 = L0 − L1 is the part of the
   path that moving the DP removes. With f = 1 (every fetch is served by the DP)
   the model's gain of the edge placement is
       G_r = (L2 / L0) · NC_e,   NC_e = K·L0 / (K·L0 + P)   (enhanced network centricity)
   under its "equivalent processing time" assumption (P the same at edge and
   cloud). K = 1 here: a fetch of a small payload over a kept-alive connection
   takes one round trip. The observed gain is (R_cloud − R_edge) / R_cloud from
   the Set B medians (one worker). Round-trip times are the medians measured by
   the Set B runs of each placement (same time window as the fetches).
   Applied to TC1 and TC2 only: TC3 is bound by throughput, not round trips.

2. Processing + transfer (Loghin et al. 2019, IEEE EDGE, doi 10.1109/EDGE.2019.00029)
   TC3 from the diagnostic set X (26 Oct): effective throughput of a plain
   kept-alive download of 473,603 B from each DP machine, and the remaining
   time attributed to DP processing.

3. Tail statistics (observed worst case; cf. Wilhelm et al. 2008, ACM TECS)
   p95, p99 and maximum of push (Set A, warm-up excluded, n = 57 per cell) and
   pull (Set B, one worker, and the baseline without EDC).

Output: out/perf_models.json (every number the text quotes).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PLACEMENTS, RUNS, TCS, load, raw, write_numbers  # noqa: E402

WARMUP = 1
TC3_BYTES = 473_603


def r(x, n=2):
    return None if x is None else round(float(x), n)


def rtt_of(run):
    """{'a->b': rtt_ms} of one run, both directions measured separately."""
    return {f"{m['from']}->{m['to']}": m["rtt_ms"] for m in load(run)["network_rtt_ms"]}


def rtt_pair(runs, a, b):
    """Median RTT between machines a and b over the runs and both directions."""
    v = []
    for run in runs:
        d = rtt_of(run)
        v += [d[k] for k in (f"{a}->{b}", f"{b}->{a}") if k in d]
    return float(np.median(v))


def fetches(pl, mode, tc):
    doc = raw(RUNS["B"][(pl, mode)], f"pull-pull-{tc}.json")
    ok = sorted((f for f in doc["fetches"] if f.get("status") == 200), key=lambda f: f["start"])
    return np.array([f["elapsed_ms"] for f in ok][WARMUP:], dtype=float)


def push(pl, tc):
    v = []
    for (p, _rep), run in RUNS["A"].items():
        if p == pl:
            v += [x["request_to_received_ms"] for x in load(run)["test_cases"][tc]["records"][WARMUP:]]
    return np.array(v, dtype=float)


def tail(v):
    return {"n": int(len(v)), "median": r(np.median(v)), "p95": r(np.percentile(v, 95)),
            "p99": r(np.percentile(v, 99)), "max": r(v.max())}


N = {}

# ── 1. network centricity ────────────────────────────────────────────────────
# the DP machine per placement (the source is always TAU VM2, the consumer fixed)
DP_HOST = {"hybrid": "edge", "edge": "edge", "cloud": "cloud"}
# Each run records one RTT per machine pair and direction, the mean of 10 pings
# (scripts/lib-metrics.sh rtt_ms). Single values carry outliers of up to 60 ms,
# so the RTTs are pooled: the median over all 18 runs of Sets A and B and both
# directions (36 values per pair). Machines and paths are the same in every placement.
AB_RUNS = list(RUNS["A"].values()) + list(RUNS["B"].values())
PAIRS = [("consumer", "cloud"), ("cloud", "source"), ("consumer", "edge"), ("edge", "source"), ("consumer", "source")]
pair_rtt = {f"{a}-{b}": rtt_pair(AB_RUNS, a, b) for a, b in PAIRS}
N["pair_rtt_ms_pooled"] = {k: r(v) for k, v in pair_rtt.items()}
path_rtt = {pl: pair_rtt[f"consumer-{DP_HOST[pl]}"] + pair_rtt[f"{DP_HOST[pl]}-source"] for pl in PLACEMENTS}
N["path_rtt_ms"] = {pl: r(path_rtt[pl]) for pl in PLACEMENTS}
# spread of the removed hop L2 over the runs (per run: cloud path − edge path, both directions averaged)
l2_runs = []
for run in AB_RUNS:
    def one(a, b, run=run):
        return rtt_pair([run], a, b)
    l2_runs.append(one("consumer", "cloud") + one("cloud", "source") - one("consumer", "edge") - one("edge", "source"))
N["L2_per_run_ms"] = {"median": r(np.median(l2_runs)), "q1": r(np.percentile(l2_runs, 25)),
                      "q3": r(np.percentile(l2_runs, 75)), "n_runs": len(l2_runs)}

nc = {}
for tc in ("tc1", "tc2"):
    med = {pl: float(np.median(fetches(pl, "seq", tc))) for pl in PLACEMENTS}
    base = {pl: float(np.median(fetches(pl, "src", tc))) for pl in PLACEMENTS}
    L0 = path_rtt["cloud"]
    R_c = med["cloud"]
    P_c = R_c - L0                       # non-network time with the cloud DP (K = 1)
    NCe = L0 / R_c
    nc[tc] = {"fetch_median_ms": {pl: r(med[pl]) for pl in PLACEMENTS},
              "baseline_median_ms": {pl: r(base[pl]) for pl in PLACEMENTS},
              "L0_cloud_path_ms": r(L0), "P_cloud_ms": r(P_c), "NCe_cloud": r(NCe, 3)}
    for pl in ("edge", "hybrid"):
        L1 = path_rtt[pl]
        L2 = L0 - L1
        predicted = (L2 / L0) * NCe
        observed = (R_c - med[pl]) / R_c
        P_e = med[pl] - L1
        nc[tc][pl] = {"L1_ms": r(L1), "L2_ms": r(L2), "L2_over_L0": r(L2 / L0, 3),
                      "predicted_gain": r(predicted, 3), "observed_gain": r(observed, 3),
                      "predicted_saving_ms": r(predicted * R_c), "observed_saving_ms": r(R_c - med[pl]),
                      "P_edge_ms": r(P_e), "P_edge_minus_P_cloud_ms": r(P_e - P_c)}
N["network_centricity"] = nc

# ── 2. processing + transfer for TC3 (diagnostic set X, 26 Oct, outside the protocol) ──
# plain kept-alive download without EDC, and fetch through the DP, keep-alive (Evidence_RQ1.md, 26 Oct)
DIAG = {"edge": {"plain_ms": 246.0, "dp_fetch_ms": 577.0, "dp_cpu_ms": (60, 65)},
        "cloud": {"plain_ms": 103.0, "dp_fetch_ms": 314.0, "dp_cpu_ms": (13, 13)}}
N["tc3_transfer_processing"] = {
    h: {"plain_keepalive_ms": d["plain_ms"],
        "effective_throughput_mbit_s": r(TC3_BYTES * 8 / (d["plain_ms"] / 1000) / 1e6, 1),
        "dp_fetch_ms": d["dp_fetch_ms"], "dp_minus_plain_ms": d["dp_fetch_ms"] - d["plain_ms"],
        "dp_cpu_ms_per_fetch": d["dp_cpu_ms"]}
    for h, d in DIAG.items()}

# ── 3. tails ─────────────────────────────────────────────────────────────────
N["tail_push_setA"] = {tc: {pl: tail(push(pl, tc)) for pl in PLACEMENTS} for tc in TCS}
N["tail_pull_seq"] = {tc: {pl: tail(fetches(pl, "seq", tc)) for pl in PLACEMENTS} for tc in TCS}
N["tail_pull_baseline"] = {tc: {pl: tail(fetches(pl, "src", tc)) for pl in PLACEMENTS} for tc in TCS}

write_numbers("perf_models", N)

# console summary
print("pair RTT:", N["pair_rtt_ms_pooled"], "\npath RTT:", N["path_rtt_ms"], " L2 per run:", N["L2_per_run_ms"])
for tc in ("tc1", "tc2"):
    c = nc[tc]
    print(f"\n{tc}: fetch {c['fetch_median_ms']}  baseline {c['baseline_median_ms']}  "
          f"L0={c['L0_cloud_path_ms']}  P_c={c['P_cloud_ms']}  NCe={c['NCe_cloud']}")
    for pl in ("edge", "hybrid"):
        print(f"   {pl}: {c[pl]}")
print("\nTC3:", N["tc3_transfer_processing"])
for k in ("tail_push_setA", "tail_pull_seq", "tail_pull_baseline"):
    print(f"\n{k}")
    for tc in TCS:
        print("  ", tc, {pl: (v["median"], v["p95"], v["p99"], v["max"]) for pl, v in N[k][tc].items()})
