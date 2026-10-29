#!/usr/bin/env python3
"""
compare-architectures.py <run-dir>...

Compares architectures run under the same settings (one run directory each,
see run-all-tests.sh) and prints Markdown:

  - per test case and architecture: median request→received with a 95 %
    bootstrap confidence interval, and the median of each phase
    (see summarize-run.py: request→provider, provider→DP, DP→source,
    source→received);
  - per pair of architectures: the difference of the medians with a 95 %
    bootstrap confidence interval, and a two-sided Mann–Whitney U test
    (normal approximation with tie and continuity correction; suited to the
    skewed, outlier-prone latency data, and adequate from about n = 10).

PULL test cases (pull-…) are compared on the time of one fetch through the
provider's Data Plane; their tables also give the one-off setup time, the
first fetch (which opens the connection) and the two fetch phases. pull-timed
adds when a time-limited contract stopped giving access.

Standard library only; the bootstrap uses a fixed seed, so output is repeatable.
"""
import json
import math
import random
import statistics
import sys
from itertools import combinations
from pathlib import Path

PHASES = ("request_to_provider", "provider_to_dp", "dp_to_source", "source_to_received")
ARCH_ORDER = ["edge", "hybrid", "cloud"]
TITLES = {
    "tc1": "TC-1: control signal (272 bytes)",
    "tc2": "TC-2: sensor batch (9,640 bytes)",
    "tc3": "TC-3: video frame (473,603 bytes)",
    "tc4": "TC-4: alert through the AAS server (241 bytes)",
}
BOOT = 5000


def mann_whitney_p(a, b):
    """Two-sided p-value of the Mann–Whitney U test, normal approximation."""
    n1, n2 = len(a), len(b)
    pooled = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks, i = [0.0] * len(pooled), 0
    ties = 0.0
    while i < len(pooled):
        j = i
        while j + 1 < len(pooled) and pooled[j + 1][0] == pooled[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        t = j - i + 1
        ties += t ** 3 - t
        i = j + 1
    r1 = sum(r for r, (_, g) in zip(ranks, pooled) if g == 0)
    u = r1 - n1 * (n1 + 1) / 2
    mu = n1 * n2 / 2
    n = n1 + n2
    sigma = math.sqrt(n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1))))
    if sigma == 0:
        return 1.0
    z = (abs(u - mu) - 0.5) / sigma
    return max(0.0, min(1.0, math.erfc(z / math.sqrt(2))))


def boot_ci(sample_fn, rng):
    vals = sorted(sample_fn(rng) for _ in range(BOOT))
    return vals[int(0.025 * BOOT)], vals[int(0.975 * BOOT) - 1]


def median_ci(xs, rng):
    return boot_ci(lambda r: statistics.median(r.choices(xs, k=len(xs))), rng)


def diff_ci(a, b, rng):
    return boot_ci(lambda r: statistics.median(r.choices(a, k=len(a))) - statistics.median(r.choices(b, k=len(b))), rng)


def fmt(v):
    return f"{v:,.0f}"


def title_of(tc):
    if tc == "pull-timed":
        return "Policy enforcement: time-limited contract, TC-1 data (pull)"
    if tc.startswith("pull-"):
        return title_of(tc[5:]) + " — pull"
    if tc in TITLES:
        return TITLES[tc]
    size = int(tc[1:])
    label = f"{size / 1048576:g} MiB" if size >= 1048576 else f"{size / 1024:g} KiB"
    return f"Payload sweep: {label} ({size:,} bytes)"


def tc_order(tc):
    if tc == "pull-timed":
        return (9, 0, "")
    group = 2 if tc.startswith("pull-") else 0
    base = tc[5:] if tc.startswith("pull-") else tc
    return (group, 0, base) if base.startswith("tc") else (group + 1, int(base[1:]), "")


def cell(stat):
    return fmt(stat["median"]) if stat and stat.get("n") else "–"


def main(run_dirs):
    runs = {}
    for d in map(Path, run_dirs):
        s = json.loads((d / "summary.json").read_text())
        runs[s["meta"]["architecture"]] = s
    archs = [a for a in ARCH_ORDER if a in runs] + [a for a in runs if a not in ARCH_ORDER]
    tcs = sorted({tc for s in runs.values() for tc in s["test_cases"]}, key=tc_order)
    rng = random.Random(1)

    for tc in tcs:
        print(f"### {title_of(tc)}\n")
        pull = tc.startswith("pull-")
        if pull:
            print("| Architecture | Fetches | Setup, once (ms) | First fetch (ms) | Fetch, median [95% CI] (ms) "
                  "| Request → source | Source → received |")
        else:
            print("| Architecture | Transfers | Request → received, median [95% CI] (ms) "
                  "| Request → provider | Provider → DP | DP → source | Source → received |")
        print("|---|---|---|---|---|---|---|")
        totals = {}
        enforcement = {}
        for a in archs:
            t = runs[a]["test_cases"].get(tc)
            if not t:
                continue
            xs = [r["request_to_received_ms"] for r in t["records"] if r["request_to_received_ms"] is not None]
            if not xs:
                continue
            totals[a] = xs
            lo, hi = median_ci(xs, rng)
            if pull:
                ph = t["pull_phases_ms"]
                print(f"| {a.capitalize()} | {t['transfers_received']} of {t['transfers_requested']} "
                      f"| {fmt(t['setup_ms'])} | {fmt(t['first_fetch_ms'])} "
                      f"| {statistics.median(xs):,.1f} [{lo:,.1f}–{hi:,.1f}] "
                      f"| {cell(ph['request_to_source'])} | {cell(ph['source_to_received'])} |")
                if t.get("policy_enforcement"):
                    enforcement[a] = t["policy_enforcement"]
                continue
            ph = t.get("phases_ms", {})
            cells = [fmt(ph[p]["median"]) if ph.get(p, {}).get("n") else "–" for p in PHASES]
            print(f"| {a.capitalize()} | {len(xs)} of {t['transfers_requested']} "
                  f"| {fmt(statistics.median(xs))} [{fmt(lo)}–{fmt(hi)}] | " + " | ".join(cells) + " |")
        print()
        if enforcement:
            print("| Architecture | Contract valid (s) | Fetches allowed | Fetches denied | Denied with "
                  "| Last allowed after expiry (s) | First denied after expiry (s) | Allowed after first denial |")
            print("|---|---|---|---|---|---|---|---|")
            for a, e in enforcement.items():
                print(f"| {a.capitalize()} | {e['policy_valid_s']:g} | {e['fetches_allowed']} | {e['fetches_denied']} "
                      f"| HTTP {', '.join(e['denied_statuses']) or '–'} | {e['last_allowed_after_expiry_s']} "
                      f"| {e['first_denied_after_expiry_s']} | {e['allowed_after_first_denial']} |")
            print("\nTimes after expiry are ± 1 s: EDC records the agreement time in whole seconds.\n")
        if len(totals) > 1:
            print("| Comparison | Difference of medians [95% CI] (ms) | p (Mann–Whitney) |")
            print("|---|---|---|")
            for a, b in combinations([x for x in archs if x in totals], 2):
                d = statistics.median(totals[a]) - statistics.median(totals[b])
                lo, hi = diff_ci(totals[a], totals[b], rng)
                p = mann_whitney_p(totals[a], totals[b])
                digits = 1 if pull else 0
                print(f"| {a.capitalize()} − {b.capitalize()} | {d:+,.{digits}f} [{lo:+,.{digits}f} to {hi:+,.{digits}f}] "
                      f"| {p:.3f}{' *' if p < 0.05 else ''} |")
            print()
    print("Phases are medians in ms. * p < 0.05. A negative difference means the first architecture is faster.")


if __name__ == "__main__":
    main(sys.argv[1:])
