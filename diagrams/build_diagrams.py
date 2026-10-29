#!/usr/bin/env python3
"""
build_diagrams.py --hybrid <run-dir> --edge <run-dir> --cloud <run-dir>

Writes hybrid.mmd, edge.mmd, cloud.mmd (sequence diagrams) and
timing_overview.mmd (flowchart) next to this script, plus timings.json with
every number the diagrams show.

All timings come from the runs' summary.json (scripts/run-all-tests.sh,
scripts/summarize-run.py), run with test cases pull-tc1, pull-tc2, pull-tc3
and PULL_VIA=consumer-dp: the consumer's Data Plane fetches from the provider's
Data Plane (its pull proxy), so the diagrams show that path. A value a run does
not contain is written as TBD; nothing is estimated.

Timings per test case (all from one run per architecture):
  catalog_ms          catalogue request, as timed by the test controller
  negotiation         negotiation_ms - catalog_ms (negotiation_ms spans the
                      catalogue request to the agreement)
  setup_ms            transfer request -> address and token on the consumer's
                      Control Plane (timed on the consumer host)
  fetch median / first fetch
                      one request to the consumer's Data Plane until the last
                      byte is back, timed on the consumer host; the first fetch
                      also opens the connections and looks up the token
  total (to first data)
                      catalog + negotiation + setup + first fetch
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TCS = [
    # key, asset, label, source endpoint, section colour, edge colour
    ("pull-tc1", "TC1", "control signal", "/tc1/control-signal", "rgb(220,235,255)", "#1f77b4"),
    ("pull-tc2", "TC2", "sensor batch", "/tc2/sensor-batch", "rgb(220,255,225)", "#2ca02c"),
    ("pull-tc3", "TC3", "video frame", "/tc3/video-frame", "rgb(255,235,210)", "#ff7f0e"),
]
HOST = {
    # No parentheses in box labels: Mermaid reads them as part of the colour
    "consumer": ("Consumer - Contabo", "rgb(238,238,238)"),
    "edge": ("TAU VM 1 - edge", "rgb(255,246,222)"),
    "cloud": ("cPouta - cloud", "rgb(226,240,255)"),
    "source": ("TAU VM 2 - data source", "rgb(240,234,250)"),
}
ARCH_TITLE = {
    "edge": "Edge: provider CP and DP on TAU VM 1",
    "hybrid": "Hybrid: provider CP on cPouta, DP on TAU VM 1",
    "cloud": "Cloud: provider CP and DP on cPouta",
}


def fmt_ms(v):
    return "TBD" if v is None else f"{v:,.0f} ms"


def fmt_ms1(v):
    """Fetch times are tens of milliseconds: one decimal."""
    return "TBD" if v is None else (f"{v:,.0f} ms" if v >= 1000 else f"{v:,.1f} ms")


def fmt_bytes(v):
    return "TBD" if v is None else f"{v:,} B"


def rtt(summary, a, b):
    if a == b:
        return None
    for r in summary["network_rtt_ms"]:
        if r["from"] == a and r["to"] == b:
            return r["rtt_ms"]
    return None


def collect(arch, run_dir):
    s = json.loads((Path(run_dir) / "summary.json").read_text())
    m = s["meta"]
    cp_role, dp_role = m["provider_cp_role"], m["provider_dp_role"]
    vias = {t.get("via") for t in s["test_cases"].values() if t.get("via")}
    if vias != {"consumer-dp"}:
        raise SystemExit(f"{run_dir}: not a run through the consumer's Data Plane (via = {sorted(vias) or 'not recorded'}); "
                         "run it with PULL_VIA=consumer-dp")
    out = {"architecture": arch, "run_dir": str(run_dir), "timing_profile": m.get("timing"), "via": "consumer-dp",
           "edc_transfer_wait_ms": m.get("edc_transfer_wait_ms"),
           "provider_cp_role": cp_role, "provider_dp_role": dp_role,
           "rtt_ms": {"consumer_to_provider_cp": rtt(s, "consumer", cp_role),
                      "provider_cp_to_dp": rtt(s, cp_role, dp_role),
                      "provider_dp_to_source": rtt(s, dp_role, "source"),
                      "consumer_to_provider_dp": rtt(s, "consumer", dp_role)},
           "test_cases": {}}
    for key, name, *_ in TCS:
        t = s["test_cases"].get(key)
        d = {k: None for k in ("size_bytes", "fetches", "catalog_ms", "negotiation_ms", "setup_ms",
                               "first_fetch_ms", "fetch_median_ms", "total_to_first_data_ms",
                               "negotiation_retries")}
        if t and not t.get("error"):
            neg_total, cat = t.get("negotiation_ms"), t.get("catalog_ms")
            d.update(
                size_bytes=(t["records"][0]["size_bytes"] if t.get("records") else None),
                fetches=t.get("transfers_received"),
                catalog_ms=cat,
                negotiation_ms=(neg_total - cat) if neg_total is not None and cat is not None else None,
                setup_ms=t.get("setup_ms"),
                first_fetch_ms=t.get("first_fetch_ms"),
                fetch_median_ms=t["request_to_received_ms"].get("median"),
                negotiation_retries=t.get("negotiation_retries"),
            )
            parts = [d["catalog_ms"], d["negotiation_ms"], d["setup_ms"], d["first_fetch_ms"]]
            d["total_to_first_data_ms"] = None if None in parts else round(sum(parts), 1)
        out["test_cases"][name] = d
    return out


def network_note(a):
    r, cp, dp = a["rtt_ms"], a["provider_cp_role"], a["provider_dp_role"]
    def one(v):
        return "TBD" if v is None else f"{v:.0f} ms"
    cpdp = ("same host" if cp == dp else f"{one(r['provider_cp_to_dp'])}, WAN")
    return (f"Network RTT: consumer to provider CP {one(r['consumer_to_provider_cp'])}"
            f" | provider CP to DP {cpdp}"
            f" | provider DP to source {one(r['provider_dp_to_source'])}"
            f" | consumer to provider DP {one(r['consumer_to_provider_dp'])}")


INIT = ("%%{init: {'theme': 'neutral', 'themeVariables': {'noteBkgColor': '#fff6bf', 'noteBorderColor': '#c9b200', "
        "'noteTextColor': '#222222'}, 'sequence': {'actorMargin': 35, 'messageMargin': 22, 'boxMargin': 6}}}%%")


def sequence(a, tcs=TCS):
    cp, dp = a["provider_cp_role"], a["provider_dp_role"]
    L = [INIT, "sequenceDiagram", "    autonumber"]

    def box(role, members):
        label, colour = HOST[role]
        L.append(f"    box {colour} {label}")
        L.extend(f"    participant {p}" for p in members)
        L.append("    end")

    box("consumer", ["R as Test runner", "CC as Consumer CP", "CD as Consumer DP"])
    if cp == dp:
        box(cp, ["PC as Provider CP", "PD as Provider DP"])
    else:
        box(cp, ["PC as Provider CP"])
        box(dp, ["PD as Provider DP"])
    box("source", ["S as Data source"])
    L.append("")
    L.append(f"    Note over R,S: {ARCH_TITLE[a['architecture']]}")
    L.append(f"    Note over R,S: {network_note(a)}")
    L.append(f"    Note over R,S: Pull, EDC wait {a['edc_transfer_wait_ms']} ms, 4 CPU / 4 GB per connector")

    for key, name, label, endpoint, colour, _ in tcs:
        d = a["test_cases"][name]
        L += [
            "",
            f"    rect {colour}",
            f"    Note over R,S: {name}: {label}, {fmt_bytes(d['size_bytes'])} (source {endpoint})",
            # 1) Catalog fetch
            "    R->>CC: Catalog request",
            "    CC->>PC: Catalog request (DSP)",
            "    PC-->>CC: Catalog with offers",
            "    CC-->>R: Catalog with offers",
            f"    Note over CC,PC: 1) Catalog: {fmt_ms(d['catalog_ms'])}",
            # 2) Contract negotiation
            "    R->>CC: Start negotiation",
            "    CC->>PC: Contract request",
            "    PC-->>CC: Contract agreement",
            "    CC->>PC: Verify agreement",
            "    PC-->>CC: Agreement finalized",
            "    loop negotiationPoll",
            "        R->>CC: Poll state, every 0.1 s",
            "    end",
            f"    Note over CC,PC: 2) Negotiation: {fmt_ms(d['negotiation_ms'])}",
            # 3) Data transfer (pull)
            "    R->>CC: Start pull transfer",
            "    CC->>PC: Transfer request",
            "    PC->>PD: Start data flow",
            "    PD-->>PC: Endpoint and token",
            "    PC-->>CC: Transfer start, token",
            "    loop edrPoll",
            "        R->>CC: Poll endpoint and token",
            "    end",
            f"    Note over CC,PC: 3a) Transfer setup, once: {fmt_ms(d['setup_ms'])}",
            f"    loop {d['fetches'] if d['fetches'] is not None else 'TBD'} fetches",
            "        R->>CD: GET data of the transfer, no token",
            "        opt first fetch only",
            "            CD->>CC: Get endpoint and token",
            "            CC-->>CD: Endpoint and token",
            "        end",
            "        CD->>PD: GET data with token",
            "        PD->>S: GET payload",
            "        S-->>PD: Payload",
            "        PD-->>CD: Payload",
            "        CD-->>R: Payload",
            "    end",
            f"    Note over CD,S: 3b) Fetch: {fmt_ms1(d['fetch_median_ms'])} median, first {fmt_ms1(d['first_fetch_ms'])}",
            f"    Note over R,S: Total {name} to first data: {fmt_ms(d['total_to_first_data_ms'])}",
            "    end",
        ]
    return "\n".join(L) + "\n"


def overview(archs):
    L = ["%%{init: {'theme': 'neutral', 'flowchart': {'nodeSpacing': 40, 'rankSpacing': 90}}}%%", "flowchart LR"]
    colours = []
    n = 0
    for arch in ("cloud", "edge", "hybrid"):   # Mermaid stacks them in reverse
        a = archs[arch]
        i = arch[0]
        L.append(f'    subgraph {arch.upper()}["{ARCH_TITLE[arch]}"]')
        L.append("        direction LR")
        L.append(f'        {i}0(["Start"])')
        prev = f"{i}0"
        for key, name, label, endpoint, _, edge_colour in TCS:
            d = a["test_cases"][name]
            node = f"{i}{name[-1]}"
            L.append(f'        {prev} -->|"{name}: {fmt_ms(d["total_to_first_data_ms"])}"| {node}["{name} done"]')
            colours.append((n, edge_colour))
            n += 1
            prev = node
        L.append("    end")
    L.append("")
    for idx, colour in colours:
        L.append(f"    linkStyle {idx} stroke:{colour},stroke-width:3px")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    for arch in ("hybrid", "edge", "cloud"):
        ap.add_argument(f"--{arch}", required=True, help=f"run directory of the {arch} run")
    args = ap.parse_args()
    archs = {arch: collect(arch, getattr(args, arch)) for arch in ("hybrid", "edge", "cloud")}
    for arch, a in archs.items():
        (HERE / f"{arch}.mmd").write_text(sequence(a))
    (HERE / "timing_overview.mmd").write_text(overview(archs))
    (HERE / "split").mkdir(exist_ok=True)
    for arch, a in archs.items():
        for tc in TCS:
            (HERE / "split" / f"{arch}_{tc[1].lower()}.mmd").write_text(sequence(a, [tc]))
    (HERE / "timings.json").write_text(json.dumps(archs, indent=2) + "\n")
    tbd = [f"{arch}/{name}/{k}" for arch, a in archs.items() for name, d in a["test_cases"].items()
           for k, v in d.items() if v is None and k != "negotiation_retries"]
    tbd += [f"{arch}/rtt/{k}" for arch, a in archs.items() for k, v in a["rtt_ms"].items()
            if v is None and not (k == "provider_cp_to_dp" and a["provider_cp_role"] == a["provider_dp_role"])]
    print("TBD values:", ", ".join(tbd) if tbd else "none")


if __name__ == "__main__":
    main()
