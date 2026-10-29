#!/usr/bin/env python3
"""
simple-report.py <run-dir>...

Prints, as Markdown, one table per test case with one row per run
(architecture × timing profile): data size, number of transfers, total time,
negotiation time, transfer time and the network round-trip times on the data
path. Reads each run's summary.json (see summarize-run.py).

    python3 scripts/simple-report.py results/2026…-edge-default results/2026…-cloud-default …
"""
import json
import statistics
import sys
from pathlib import Path

TC_TITLES = {
    "tc1": "TC-1: real-time control signal",
    "tc2": "TC-2: high-frequency sensor batch",
    "tc3": "TC-3: video frame",
    "tc4": "TC-4: triggered alert (through the AAS server)",
}
ARCH_LABELS = {
    "edge": "Edge (CP edge, DP edge)",
    "hybrid": "Hybrid (CP cloud, DP edge)",
    "cloud": "Cloud (CP cloud, DP cloud)",
}
ARCH_ORDER = ["edge", "hybrid", "cloud"]


def size_text(sizes):
    lo, hi = min(sizes), max(sizes)
    return f"{lo:,}" if lo == hi else f"{lo:,}–{hi:,}"


def rtt(summary, a, b):
    for r in summary["network_rtt_ms"]:
        if r["from"] == a and r["to"] == b:
            return r["rtt_ms"]
    return None


def main(run_dirs):
    runs = []
    for d in map(Path, run_dirs):
        s = json.loads((d / "summary.json").read_text())
        runs.append(s)
    runs.sort(key=lambda s: (ARCH_ORDER.index(s["meta"]["architecture"]), s["meta"].get("timing", "default")))

    for tc, title in TC_TITLES.items():
        print(f"### {title}\n")
        print("| Architecture | EDC wait | Data size (bytes) | Transfers | Total time (ms) | Negotiation (ms) "
              "| Transfer time, median (ms) | Transfer time, min–max (ms) | RTT source ↔ DP (ms) | RTT DP ↔ consumer (ms) |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for s in runs:
            t = s["test_cases"].get(tc)
            if not t:
                continue
            m = s["meta"]
            times = [r["request_to_received_ms"] for r in t["records"]]
            sizes = [r["size_bytes"] for r in t["records"]]
            dp = m["provider_dp_role"]
            total = t["negotiation_ms"] + sum(times)
            print(f'| {ARCH_LABELS[m["architecture"]]} | {m.get("edc_transfer_wait_ms", 1000)} ms '
                  f'| {size_text(sizes)} | {t["transfers_received"]} of {t["transfers_requested"]} '
                  f'| {total:,.0f} | {t["negotiation_ms"]:,.0f} | {statistics.median(times):,.0f} '
                  f'| {min(times):,.0f}–{max(times):,.0f} '
                  f'| {rtt(s, "source", dp):.1f} | {rtt(s, dp, "consumer"):.1f} |')
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
