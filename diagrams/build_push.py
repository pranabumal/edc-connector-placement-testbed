#!/usr/bin/env python3
"""
build_push.py [--hybrid <run-dir>] [--edge <run-dir>] [--cloud <run-dir>]

Diagrams of the PUSH flow of stock EDC 0.14.1 (transfer type HttpData-PUSH),
for each architecture a run directory is given for. Writes into push/:

  <arch>.mmd, split/<arch>_<tc>.mmd   sequence diagrams (TC1 to TC3)
  architecture/<arch>.svg             deployment diagram
  timings.json                        every number the diagrams show

In a push the consumer names a destination in its transfer request and the
provider's Data Plane sends the data there. The consumer's side is a data
platform (a digital twin platform, an ERP), simulated by two programs on the
consumer's machine: the consumer application (the test-case scripts), which
asks for the catalog, negotiates and requests transfers, and the receiver, its
ingestion endpoint and the destination it names. The consumer's Data Plane
takes no part: stock EDC only ever asks a consumer-side Data Plane to prepare
a destination, and this deployment registers none to prepare.

The runs must have the application on the consumer's machine
(run-all-tests.sh, APP_ON=consumer), so no timed step involves the controller.

All timings come from the runs' summary.json (scripts/run-all-tests.sh with
test cases tc1, tc2, tc3). A value a run does not contain is written as TBD;
nothing is estimated. Architectures given earlier stay in timings.json, so the
three can be added one at a time.

Timings per test case:
  catalog_ms, negotiation   timed by the consumer application, on the consumer's
                            machine; negotiation = negotiation_ms - catalog_ms
  request to received       the consumer's Control Plane creates the transfer
                            -> the receiver logs the arrival; one clock (both
                            on the consumer's machine); median over the transfers
  phases                    that time split at three points (summarize-run.py):
                            request -> provider CP -> provider DP -> source ->
                            receiver; clock-corrected, medians
  first data                catalog + negotiation + the first transfer
"""
import argparse
import json
from pathlib import Path

from build_architecture import GREY, SERVERS, TITLE, Svg, ms
from build_diagrams import ARCH_TITLE, HOST, INIT, fmt_bytes, fmt_ms, rtt

HERE = Path(__file__).resolve().parent
OUT = HERE / "push"
SERVERS = dict(SERVERS, ctrl=("Test controller", "#e4f4e6",
                                 ["MacBook Air, Apple silicon, macOS", "Tailscale client",
                                  "starts and observes the run; no", "timed step or data passes through it"]))
TCS = [
    ("tc1", "TC1", "control signal", "/tc1/control-signal", "rgb(220,235,255)"),
    ("tc2", "TC2", "sensor batch", "/tc2/sensor-batch", "rgb(220,255,225)"),
    ("tc3", "TC3", "video frame", "/tc3/video-frame", "rgb(255,235,210)"),
]
PHASES = ("request_to_provider", "provider_to_dp", "dp_to_source", "source_to_received")


def collect(arch, run_dir):
    s = json.loads((Path(run_dir) / "summary.json").read_text())
    m = s["meta"]
    cp_role, dp_role = m["provider_cp_role"], m["provider_dp_role"]
    if m.get("application_on") != "consumer":
        raise SystemExit(f"{run_dir}: the consumer application did not run on the consumer's machine "
                         f"(application_on = {m.get('application_on')}); run it with APP_ON=consumer")
    out = {"architecture": arch, "flow": "push", "application_on": "consumer", "run_dir": str(run_dir), "timing_profile": m.get("timing"),
           "edc_transfer_wait_ms": m.get("edc_transfer_wait_ms"),
           "provider_cp_role": cp_role, "provider_dp_role": dp_role,
           "rtt_ms": {"consumer_to_provider_cp": rtt(s, "consumer", cp_role),
                      "provider_cp_to_dp": rtt(s, cp_role, dp_role),
                      "provider_dp_to_source": rtt(s, dp_role, "source"),
                      "consumer_to_provider_dp": rtt(s, "consumer", dp_role)},
           "test_cases": {}}
    for key, name, *_ in TCS:
        t = s["test_cases"].get(key)
        d = {k: None for k in ("size_bytes", "transfers_requested", "transfers_received", "catalog_ms",
                               "negotiation_ms", "request_to_received_median_ms", "request_to_received_min_ms",
                               "request_to_received_max_ms", "first_transfer_ms", "first_data_ms",
                               "negotiation_retries", "transfer_retries")}
        d["phases_median_ms"] = {p: None for p in PHASES}
        if t and t.get("records"):
            neg_total, cat = t.get("negotiation_ms"), t.get("catalog_ms")
            r2r = t.get("request_to_received_ms") or {}
            d.update(
                size_bytes=t["records"][0].get("size_bytes"),
                transfers_requested=t.get("transfers_requested"),
                transfers_received=t.get("transfers_received"),
                catalog_ms=cat,
                negotiation_ms=(neg_total - cat) if neg_total is not None and cat is not None else None,
                request_to_received_median_ms=r2r.get("median"),
                request_to_received_min_ms=r2r.get("min"),
                request_to_received_max_ms=r2r.get("max"),
                first_transfer_ms=t["records"][0].get("request_to_received_ms"),
                negotiation_retries=t.get("negotiation_retries"),
                transfer_retries=t.get("transfer_retries"),
            )
            for p in PHASES:
                d["phases_median_ms"][p] = ((t.get("phases_ms") or {}).get(p) or {}).get("median")
            parts = [d["catalog_ms"], d["negotiation_ms"], d["first_transfer_ms"]]
            d["first_data_ms"] = None if None in parts else round(sum(parts), 1)
        out["test_cases"][name] = d
    return out


def network_note(a):
    r, cp, dp = a["rtt_ms"], a["provider_cp_role"], a["provider_dp_role"]
    def one(v):
        return "TBD" if v is None else f"{v:.0f} ms"
    cpdp = "same host" if cp == dp else f"{one(r['provider_cp_to_dp'])}, WAN"
    return (f"Network RTT: consumer to provider CP {one(r['consumer_to_provider_cp'])}"
            f" | provider CP to DP {cpdp}"
            f" | provider DP to source {one(r['provider_dp_to_source'])}"
            f" | provider DP to consumer {one(r['consumer_to_provider_dp'])}")


def sequence(a, tcs=TCS):
    cp, dp = a["provider_cp_role"], a["provider_dp_role"]
    L = [INIT, "sequenceDiagram", "    autonumber"]

    def box(label, colour, members):
        L.append(f"    box {colour} {label}")
        L.extend(f"    participant {p}" for p in members)
        L.append("    end")

    box(*HOST["consumer"], ["R as Consumer application", "RX as Receiver", "CC as Consumer CP", "CD as Consumer DP"])
    if cp == dp:
        box(*HOST[cp], ["PC as Provider CP", "PD as Provider DP"])
    else:
        box(*HOST[cp], ["PC as Provider CP"])
        box(*HOST[dp], ["PD as Provider DP"])
    box(*HOST["source"], ["S as Data source"])
    L.append("")
    L.append(f"    Note over R,S: {ARCH_TITLE[a['architecture']]}")
    L.append(f"    Note over R,S: {network_note(a)}")
    L.append(f"    Note over R,S: Push, stock EDC 0.14.1, EDC wait {a['edc_transfer_wait_ms']} ms, 4 CPU / 4 GB per connector")
    L.append("    Note over R,RX: Consumer data platform, simulated")
    L.append("    Note over CD: Not used in a push")

    for key, name, label, endpoint, colour in tcs:
        d = a["test_cases"][name]
        ph = d["phases_median_ms"]
        n = d["transfers_received"] if d["transfers_received"] is not None else "TBD"
        L += [
            "",
            f"    rect {colour}",
            f"    Note over R,S: {name}: {label}, {fmt_bytes(d['size_bytes'])} (source {endpoint})",
            # 1) Catalog
            "    R->>CC: Catalog request",
            "    CC->>PC: Catalog request (DSP)",
            "    PC-->>CC: Catalog with offers",
            "    CC-->>R: Catalog with offers",
            f"    Note over R,PC: 1) Catalog: {fmt_ms(d['catalog_ms'])}",
            # 2) Contract negotiation
            "    R->>CC: Start negotiation",
            "    CC->>PC: Contract request",
            "    PC-->>CC: Contract agreement",
            "    CC->>PC: Verify agreement",
            "    PC-->>CC: Agreement finalized",
            "    loop negotiationPoll",
            "        R->>CC: Poll state, every 0.1 s",
            "    end",
            f"    Note over R,PC: 2) Negotiation, once: {fmt_ms(d['negotiation_ms'])}",
            # 3) Push transfers
            f"    loop {n} transfers",
            "        R->>CC: Start push transfer, destination = receiver",
            "        CC->>PC: Transfer request",
            f"        Note over CC,PC: a) request to provider CP: {fmt_ms(ph['request_to_provider'])}",
            "        PC->>PD: Start data flow",
            "        PC-->>CC: Transfer start",
            f"        Note over PC,PD: b) provider CP to DP: {fmt_ms(ph['provider_to_dp'])}",
            "        PD->>S: GET payload",
            f"        Note over PD,S: c) DP to source: {fmt_ms(ph['dp_to_source'])}",
            "        S-->>PD: Payload",
            "        PD->>RX: POST payload",
            f"        Note over RX,S: d) source to receiver: {fmt_ms(ph['source_to_received'])}",
            "    end",
            f"    Note over R,S: 3) One transfer, request to received: {fmt_ms(d['request_to_received_median_ms'])} median"
            f" ({fmt_ms(d['request_to_received_min_ms'])} to {fmt_ms(d['request_to_received_max_ms'])})",
            f"    Note over R,S: {name} to first data: {fmt_ms(d['first_data_ms'])}, then one transfer per piece of data",
            "    end",
        ]
    return "\n".join(L) + "\n"


def architecture(arch, t):
    cp, dp = t["provider_cp_role"], t["provider_dp_role"]
    r = t["rtt_ms"]
    same = cp == dp
    s = Svg(1660, 1302)

    NX_OFF, NW, NH = 40, 210, 80
    R1, R2 = 150, 540
    B = 880

    def server_box(role, x, y, w, h):
        title, fill, spec = SERVERS[role]
        s.box(x, y, w, h, fill)
        s.text(x + 14, y + 30, [title], size=17, bold=True)
        s.text(x + 14, y + h - 12 - 17 * (len(spec) - 1) - 4, spec, size=13, fill="#333", lh=17)

    def unit(x, y_row, lines, db_name):
        nx = x + NX_OFF
        s.node(nx, y_row, NW, NH, lines)
        s.add(f'<line x1="{nx+52}" y1="{y_row+NH}" x2="{nx+52}" y2="{y_row+NH+25}" stroke="#777" stroke-width="1.2"/>')
        s.db(nx, y_row + NH + 25, db_name)
        return nx

    CTRL_X, CON_X, PROV_X, SRC_X = 20, 440, 900, 1380
    CTRL_W, CON_W, PROV_W, SRC_W = 270, 300, 310, 260

    # Test controller
    server_box("ctrl", CTRL_X, 40, CTRL_W, 450)
    scr_x = CTRL_X + NX_OFF
    s.node(scr_x, R1, NW, 110, ["ssh :22 to all servers", "deploy, start the application,", "collect its results,", "docker stats, clock offsets", "(not timed)"], grey=True)

    # Consumer
    server_box("consumer", CON_X, 40, CON_W, B - 40)
    con_x = unit(CON_X, R1, ["consumer-cp", "Control Plane", "mgmt :9192 · DSP :9193"], "consumer-cp-db")
    # The consumer's data platform, simulated: the application that asks, and its ingestion endpoint
    APP_Y, APP_H = 388, 76
    s.box(con_x - 14, APP_Y - 16, NW + 28, R2 + NH + 34 - (APP_Y - 16), "none", "#555", dash="7 4", rx=8, sw=1.3)
    s.node(con_x, APP_Y, NW, APP_H, ["consumer application", "test-case scripts: catalog,", "negotiation, transfer requests"])
    s.node(con_x, R2, NW, NH, ["data-receiver :4000", "ingestion endpoint,", "logs every arrival"])
    s.text(con_x + NW / 2, R2 + NH + 22, ["Consumer data platform, simulated"], size=12.5, anchor="middle", fill="#333")
    s.text(con_x + NW / 2, 500, ["stands for a digital twin", "platform or an ERP"], size=12.5, anchor="middle", fill="#555", lh=15)
    s.node(con_x, 672, NW, 62, ["consumer-dp + own database", "Data Plane, deployed;", "not used in a push"], grey=True)

    # Provider
    if same:
        server_box(cp, PROV_X, 40, PROV_W, B - 40)
    else:
        server_box(cp, PROV_X, 40, PROV_W, 400)
        server_box(dp, PROV_X, 480, PROV_W, B - 480)
    pcp_x = unit(PROV_X, R1, ["provider-cp", "Control Plane", "mgmt :8182 · DSP :8183", "control :8185"], "provider-cp-db")
    pdp_x = unit(PROV_X, R2, ["provider-dp", "Data Plane", "signaling :8285"], "provider-dp-db")

    # Data source
    server_box("source", SRC_X, 480, SRC_W, B - 480)
    src_x = SRC_X + NX_OFF
    s.node(src_x, R2, NW, NH, ["data-simulator :5050", "TC1 to TC3 payloads"])
    s.node(src_x, 660, NW, 80, ["basyx-aas :8091", "MongoDB, crane-adapter", "TC4 only"], grey=True)

    # Communication links
    y1, y5 = R1 + 40, R2 + 40
    gap1 = (CTRL_X + CTRL_W + CON_X) / 2
    gap2 = (CON_X + CON_W + PROV_X) / 2
    gap3 = (PROV_X + PROV_W + SRC_X) / 2
    s.arrow([(scr_x + NW, y1), (CON_X, y1)], GREY, 1.8, dash="5 4")
    s.label(gap1, y1 - 24, ["ssh :22", "not timed"], bold_first=False)
    s.arrow([(con_x + 175, APP_Y), (con_x + 175, R1 + NH)])
    s.label(con_x + 167, 338, ["(1) HTTP :9192", "same host"], anchor="end")
    s.arrow([(con_x + NW, y1), (pcp_x, y1)], both=True)
    s.label(gap2, y1 - 24, ["(2) DSP :8183", f"RTT {ms(r['consumer_to_provider_cp'])}"])
    s.arrow([(pcp_x + 175, R1 + NH), (pdp_x + 175, R2)])
    if same:
        s.label(pcp_x + 167, 385, ["(3) HTTP :8285", "same host"], anchor="end")
    else:
        s.label(pcp_x + 183, 458, ["(3) HTTP :8285", f"RTT {ms(r['provider_cp_to_dp'])}, WAN"], anchor="start")
    s.arrow([(pdp_x + NW, y5), (src_x, y5)])
    s.label(gap3, y5 - 24, ["(4) HTTP GET :5050", f"RTT {ms(r['provider_dp_to_source'])}"])
    s.arrow([(pdp_x, y5), (con_x + NW, y5)])
    s.label(gap2, y5 - 24, ["(5) HTTP POST :4000", f"RTT {ms(r['consumer_to_provider_dp'])}"])
    s.arrow([(pdp_x + NW, R2 + 62), (src_x, 700)], GREY, 1.8, dash="5 4")
    s.label(gap3, 705, ["TC4 only", "HTTP :8091"], bold_first=False)

    # Legend
    ly = B + 30
    s.box(20, ly, 1620, 312, "#ffffff", "#999", rx=6, sw=1)
    s.text(40, ly + 28, ["Communication tested (thick arrows are on the timed path)"], size=15, bold=True)
    s.text(40, ly + 56, [
        "(1) catalog, negotiation and transfer requests, from the consumer application to its Control Plane (management API)",
        "(2) DSP between the Control Planes: catalog, negotiation, transfer request and start",
        "(3) the provider Control Plane tells its Data Plane to start the flow",
        "(4) the provider Data Plane fetches the payload from the data source",
        "(5) the provider Data Plane pushes the payload to the destination the application named: its ingestion endpoint",
        "Phases: catalog (1)(2) · negotiation (1)(2) · one transfer, request to received (2)(3)(4)(5)",
    ], size=14, lh=22)
    s.text(40, ly + 204, [
        "A transfer is timed from its creation on the consumer Control Plane to its arrival at the receiver, on one clock.",
        "Catalog and negotiation are timed by the consumer application, on the same server. The test controller is in no timed step.",
        "RTT: ping round trip between the servers at the start of the run.",
        "Thin lines: database connection (JDBC :5432); every connector unit has its own PostgreSQL 16 (0.5 CPU, 256 MB).",
    ], size=14, lh=22)
    s.text(1000, ly + 28, ["Notes"], size=15, bold=True)
    s.text(1000, ly + 56, [
        "Stock EDC 0.14.1, transfer type HttpData-PUSH.",
        "Data path: source, provider Data Plane, ingestion",
        "endpoint. The address of that endpoint travels in",
        "each transfer request; nothing is registered before.",
        "Greyed: deployed, but not used. The consumer Data",
        "Plane carries no data in stock EDC.",
        "Dotted: not timed (ssh from the controller; TC4 reads",
        "the alert through the AAS instead of the simulator).",
        "All traffic between servers goes over the",
        "Tailscale (WireGuard) overlay network.",
        "Connector containers: EDC 0.14.1, 4 CPU / 4 GB each.",
    ], size=14, lh=22)
    return s.render(TITLE[arch] + " (push)")


def main():
    ap = argparse.ArgumentParser()
    for arch in ("hybrid", "edge", "cloud"):
        ap.add_argument(f"--{arch}", help=f"run directory of the {arch} push run")
    args = ap.parse_args()
    (OUT / "split").mkdir(parents=True, exist_ok=True)
    (OUT / "architecture").mkdir(exist_ok=True)
    tfile = OUT / "timings.json"
    archs = json.loads(tfile.read_text()) if tfile.exists() else {}
    given = [a for a in ("hybrid", "edge", "cloud") if getattr(args, a)]
    if not given:
        ap.error("give at least one of --hybrid, --edge, --cloud")
    for arch in given:
        archs[arch] = collect(arch, getattr(args, arch))
    for arch in given:
        a = archs[arch]
        (OUT / f"{arch}.mmd").write_text(sequence(a))
        for tc in TCS:
            (OUT / "split" / f"{arch}_{tc[1].lower()}.mmd").write_text(sequence(a, [tc]))
        (OUT / "architecture" / f"{arch}.svg").write_text(architecture(arch, a))
    tfile.write_text(json.dumps(archs, indent=2) + "\n")
    tbd = [f"{arch}/{name}/{k}" for arch in given for name, d in archs[arch]["test_cases"].items()
           for k, v in list(d.items()) + list(d["phases_median_ms"].items()) if v is None]
    print("Wrote push diagrams for:", ", ".join(given))
    print("TBD values:", ", ".join(tbd) if tbd else "none")


if __name__ == "__main__":
    main()
