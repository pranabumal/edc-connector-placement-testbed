#!/usr/bin/env python3
"""
summarize-matrix.py <matrix.json> <run-dir>...

Combines several measurement runs (one per architecture and timing profile; see
run-all-tests.sh) into the test-case × architecture matrix of Methods Table 3.2,
writes it to <matrix.json> and prints it. Columns are "<arch>/<timing>".

Reads each run's summary.json, so the runs can be recombined later, e.g. after
repeating one architecture:

    python3 scripts/summarize-matrix.py results/matrix-x.json results/2026…-edge results/2026…-cloud …
"""
import json
import sys
from pathlib import Path

ROWS = [
    ("negotiation_ms", "Negotiation (ms)", lambda t: t.get("negotiation_ms")),
    ("request_to_received_ms", "Request → received, median (ms)",
     lambda t: t["request_to_received_ms"].get("median")),
    ("source_to_received_ms", "Source → received, median (ms, clock-corrected)",
     lambda t: t["source_to_received_ms"].get("median")),
    ("dp_mem_mb", "Provider DP RAM during, avg (MB)",
     lambda t: t["resources"].get("provider-dp", {}).get("during", {}).get("mem_mb", {}).get("avg")),
    ("dp_cpu_pct", "Provider DP CPU during, avg (%)",
     lambda t: t["resources"].get("provider-dp", {}).get("during", {}).get("cpu_pct", {}).get("avg")),
    ("cp_mem_mb", "Provider CP RAM during, avg (MB)",
     lambda t: t["resources"].get("provider-cp", {}).get("during", {}).get("mem_mb", {}).get("avg")),
]


def main(out: Path, run_dirs):
    runs = {}
    for d in map(Path, run_dirs):
        s = json.loads((d / "summary.json").read_text())
        column = f'{s["meta"]["architecture"]}/{s["meta"].get("timing", "default")}'
        runs[column] = {"run_dir": str(d), "summary": s}

    archs = list(runs)
    tcs = sorted({tc for r in runs.values() for tc in r["summary"]["test_cases"]})
    matrix = {tc: {} for tc in tcs}
    for arch, r in runs.items():
        for tc, t in r["summary"]["test_cases"].items():
            matrix[tc][arch] = {key: get(t) for key, _, get in ROWS} | {
                "transfers_received": t["transfers_received"],
                "transfers_requested": t["transfers_requested"],
            }

    out.write_text(json.dumps({
        "architectures": {a: {"run_dir": r["run_dir"],
                              "timing": r["summary"]["meta"].get("timing", "default"),
                              "edc_transfer_wait_ms": r["summary"]["meta"].get("edc_transfer_wait_ms", 1000),
                              "edc_negotiation_wait_ms": r["summary"]["meta"].get("edc_negotiation_wait_ms", 1000),
                              "provider_cp_role": r["summary"]["meta"]["provider_cp_role"],
                              "provider_dp_role": r["summary"]["meta"]["provider_dp_role"],
                              "clocks": r["summary"]["clocks"],
                              "network_rtt_ms": r["summary"]["network_rtt_ms"]}
                          for a, r in runs.items()},
        "matrix": matrix,
    }, indent=2))

    width = 16
    for tc in tcs:
        print(f"\n{tc.upper()}" + "".join(f"{a:>{width}}" for a in archs))
        for key, label, _ in ROWS:
            cells = "".join(f"{(matrix[tc].get(a, {}).get(key) if matrix[tc].get(a, {}).get(key) is not None else '-'):>{width}}"
                            for a in archs)
            print(f"  {label:<48}{cells}")
    print(f"\nMatrix: {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])
