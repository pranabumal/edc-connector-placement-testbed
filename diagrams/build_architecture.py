#!/usr/bin/env python3
"""
build_architecture.py

Writes architecture/hybrid.svg, architecture/edge.svg and architecture/cloud.svg:
deployment diagrams of the three provider placements, with the servers'
specifications, the containers and ports on each, and the communication the
tests exercise (numbered; thick arrows are on the timed path). The pull runs
through the consumer's Data Plane (PULL_VIA=consumer-dp).

Drawn directly as SVG on a fixed grid (servers are columns in the order of the
data path, the communication links share rows), so labels never collide with
arrows. Network distances come from timings.json (written by
build_diagrams.py), so they match the sequence diagrams. Server specifications
were read from the machines themselves (lscpu, free, os-release, docker
--version); the database figure is the time of one synchronous write measured
with pg_test_fsync (2026-10-08). IP addresses are left out on purpose.
"""
import json
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "architecture"

CONTROLLER_RTT = "mean 66 ms"   # Mac to the consumer's Control Plane, 10 pings, 2026-10-13

SERVERS = {
    "consumer": ("Consumer: Contabo VPS", "#eeeeee",
                 ["4 vCPU AMD EPYC, 8 GB RAM", "Ubuntu 24.04.4, Docker 29.5.3",
                  "database sync write 0.5 ms", "also hosts the TwinFlow app"]),
    "edge": ("TAU VM 1: edge server", "#fff4d6",
             ["bhyve VM on SmartOS/Triton", "4 vCPU Xeon Gold 6130, 8 GB RAM",
              "Ubuntu 24.04.4, Docker 29.8.2", "database sync write ~100 ms"]),
    "cloud": ("cPouta: CSC cloud VM", "#dcecff",
              ["KVM VM (CSC cPouta)", "4 vCPU Xeon (Cascade Lake)",
               "8 GB RAM, Ubuntu 24.04.5", "Docker 29.8.2",
               "database sync write 1.7 ms"]),
    "source": ("TAU VM 2: data source", "#eee6f8",
               ["bhyve VM, same subnet as VM 1", "2 vCPU Xeon Gold 6130, 8 GB RAM",
                "Ubuntu 24.04.4, Docker 29.8.2", "database sync write ~26 ms"]),
    "ctrl": ("Test controller", "#e4f4e6",
             ["MacBook Air, Apple silicon, macOS", "Tailscale client",
              "runs the test scripts; no data", "passes through it"]),
}
TITLE = {
    "edge": "Edge: provider Control Plane and Data Plane on the edge server",
    "hybrid": "Hybrid: provider Control Plane in the cloud, Data Plane on the edge server",
    "cloud": "Cloud: provider Control Plane and Data Plane in the cloud",
}
BLUE, GREY = "#1f4e79", "#808080"


class Svg:
    def __init__(self, w, h):
        self.w, self.h, self.p = w, h, []

    def add(self, s):
        self.p.append(s)

    def text(self, x, y, lines, size=13.5, bold=False, anchor="start", fill="#222", lh=17, first_bold=False):
        weight = ' font-weight="bold"' if bold else ""
        out = [f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" fill="{fill}"{weight}>']
        for i, ln in enumerate(lines):
            wt = ' font-weight="bold"' if (first_bold and i == 0) else ""
            out.append(f'<tspan x="{x}" dy="{0 if i == 0 else lh}"{wt}>{escape(ln)}</tspan>')
        out.append("</text>")
        self.add("".join(out))

    def box(self, x, y, w, h, fill, stroke="#666", dash=None, rx=8, sw=1.5):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def node(self, x, y, w, h, lines, grey=False):
        self.box(x, y, w, h, "#f4f4f4" if grey else "#ffffff", "#b0b0b0" if grey else "#555",
                 dash="5 4" if grey else None, rx=6)
        total = (len(lines) - 1) * 17
        self.text(x + w / 2, y + h / 2 - total / 2 + 5, lines, anchor="middle",
                  fill="#888" if grey else "#222", first_bold=not grey)

    def db(self, x, y, name):
        w, h, e = 104, 58, 8
        self.add(f'<path d="M{x},{y+e} a{w/2},{e} 0 0 1 {w},0 v{h-2*e} a{w/2},{e} 0 0 1 {-w},0 z" fill="#fafafa" stroke="#777" stroke-width="1.2"/>')
        self.add(f'<path d="M{x},{y+e} a{w/2},{e} 0 0 0 {w},0" fill="none" stroke="#777" stroke-width="1.2"/>')
        self.text(x + w / 2, y + 28, [name, "PostgreSQL 16"], size=11.5, anchor="middle", lh=14)

    def arrow(self, pts, colour=BLUE, width=3.5, dash=None, both=False):
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        da = f' stroke-dasharray="{dash}"' if dash else ""
        m = "ab" if colour == BLUE else "ag"
        ms = f' marker-start="url(#{m})"' if both else ""
        self.add(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}"{da}{ms} marker-end="url(#{m})"/>')

    def label(self, x, y, lines, anchor="middle", bold_first=True):
        """Arrow label; y is the baseline of the first line."""
        self.text(x, y, lines, size=13.5, anchor=anchor, lh=16, first_bold=bold_first)

    def render(self, title):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
                'font-family="Helvetica, Arial, sans-serif">'
                '<defs>'
                '<marker id="ab" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
                f'<path d="M0,0 L10,5 L0,10 z" fill="{BLUE}"/></marker>'
                '<marker id="ag" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
                f'<path d="M0,0 L10,5 L0,10 z" fill="{GREY}"/></marker></defs>'
                f'<rect width="{self.w}" height="{self.h}" fill="#ffffff"/>'
                f'<text x="20" y="28" font-size="21" font-weight="bold" fill="#222">{escape(title)}</text>'
                '<g transform="translate(0,40)">')
        return head + "".join(self.p) + "</g></svg>\n"


def ms(v):
    return "TBD" if v is None else f"{v:.0f} ms"


def build(arch, t):
    cp, dp = t["provider_cp_role"], t["provider_dp_role"]
    r = t["rtt_ms"]
    same = cp == dp
    s = Svg(1660, 1334)

    NX_OFF, NW, NH = 40, 210, 80          # node offset in its box, width, height
    R1, R2 = 150, 540                      # rows: the Control Planes; the Data Plane and the data path
    B = 880                                # bottom of the tall boxes

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
    s.node(scr_x, R1, NW, NH, ["test scripts", "catalog request,", "negotiation"])
    s.node(scr_x, 300, NW, 92, ["ssh :22 to all servers", "deploy, start pull client,", "docker stats, clock offsets", "(not timed)"], grey=True)
    s.arrow([(scr_x + 175, R1 + NH), (scr_x + 175, 300)], GREY, 1.8, dash="5 4")

    # Consumer
    server_box("consumer", CON_X, 40, CON_W, B - 40)
    con_x = unit(CON_X, R1, ["consumer-cp", "Control Plane", "mgmt :9192 · DSP :9193"], "consumer-cp-db")
    PC_Y, PC_H = 370, 70                   # the pull client, between the consumer's two planes
    s.node(con_x, PC_Y, NW, PC_H, ["pull-client.py", "transfer and fetches", "(started over ssh)"])
    unit(CON_X, R2, ["consumer-dp", "Data Plane", "pull proxy :9296", "signaling :9295"], "consumer-dp-db")
    s.node(con_x, 718, NW, 50, ["data-receiver :4000", "push tests only"], grey=True)

    # Provider
    if same:
        server_box(cp, PROV_X, 40, PROV_W, B - 40)
    else:
        server_box(cp, PROV_X, 40, PROV_W, 400)
        server_box(dp, PROV_X, 480, PROV_W, B - 480)
    pcp_x = unit(PROV_X, R1, ["provider-cp", "Control Plane", "mgmt :8182 · DSP :8183", "control :8185"], "provider-cp-db")
    pdp_x = unit(PROV_X, R2, ["provider-dp", "Data Plane", "public :8284", "signaling :8285"], "provider-dp-db")

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
    s.arrow([(scr_x + NW, y1), (con_x, y1)])
    s.label(gap1, y1 - 24, ["(1) HTTP :9192", f"RTT {CONTROLLER_RTT}"])
    s.arrow([(con_x + NW, y1), (pcp_x, y1)], both=True)
    s.label(gap2, y1 - 24, ["(2) DSP :8183", f"RTT {ms(r['consumer_to_provider_cp'])}"])
    s.arrow([(con_x + NW, y5), (pdp_x, y5)])
    s.label(gap2, y5 - 24, ["(7) HTTP :8284", f"RTT {ms(r['consumer_to_provider_dp'])}"])
    s.arrow([(pdp_x + NW, y5), (src_x, y5)])
    s.label(gap3, y5 - 24, ["(8) HTTP :5050", f"RTT {ms(r['provider_dp_to_source'])}"])
    # (4) pull client to the consumer Control Plane, (5) pull client to the consumer Data Plane: vertical
    s.arrow([(con_x + 175, PC_Y), (con_x + 175, R1 + NH)])
    s.label(con_x + 167, 338, ["(4) HTTP :9192", "same host"], anchor="end")
    s.arrow([(con_x + 60, PC_Y + PC_H), (con_x + 60, R2)])
    s.label(con_x + 70, 482, ["(5) HTTP :9296", "same host"], anchor="start")
    # (6) consumer Data Plane to its Control Plane: around the pull client, on the right
    s.arrow([(con_x + NW, R2 + 15), (con_x + NW + 28, R2 + 15), (con_x + NW + 28, R1 + NH - 15), (con_x + NW, R1 + NH - 15)], width=2.2)
    s.label(CON_X + CON_W + 10, 385, ["(6) HTTP :9192", "same host,", "first fetch only"], anchor="start")
    # (3) provider CP to DP: vertical, right part of the nodes
    s.arrow([(pcp_x + 175, R1 + NH), (pdp_x + 175, R2)])
    if same:
        s.label(pcp_x + 167, 385, ["(3) HTTP :8285", "same host"], anchor="end")
    else:
        s.label(pcp_x + 183, 458, ["(3) HTTP :8285", f"RTT {ms(r['provider_cp_to_dp'])}, WAN"], anchor="start")
    # TC4 only: Data Plane to the AAS
    s.arrow([(pdp_x + NW, R2 + 62), (src_x, 700)], GREY, 1.8, dash="5 4")
    s.label(gap3, 705, ["TC4 only", "HTTP :8091"], bold_first=False)

    # Legend
    ly = B + 30
    s.box(20, ly, 1620, 344, "#ffffff", "#999", rx=6, sw=1)
    s.text(40, ly + 28, ["Communication tested (thick arrows are on the timed path)"], size=15, bold=True)
    s.text(40, ly + 56, [
        "(1) catalog and negotiation requests, from the test controller to the consumer Control Plane (management API)",
        "(2) DSP between the Control Planes: catalog, negotiation, transfer request and start",
        "(3) the provider Control Plane tells its Data Plane to start the flow; the Data Plane returns endpoint and token",
        "(4) the pull client starts the transfer and polls the consumer Control Plane for the token",
        "(5) the pull client asks the consumer Data Plane for the data of the transfer, without a token (repeated)",
        "(6) the consumer Data Plane reads endpoint and token from its Control Plane (first fetch of a transfer only)",
        "(7) the consumer Data Plane fetches the data from the provider Data Plane, with the token",
        "(8) the provider Data Plane fetches the payload from the data source",
        "Phases: catalog (1)(2) · negotiation (1)(2) · transfer setup (4)(2)(3)(2) · fetch (5)(7)(8), first fetch also (6)",
    ], size=14, lh=22)
    s.text(40, ly + 270, [
        "RTT: ping round trip between the servers at the start of the run (13 October 2026); (1): mean of 10 pings from the controller.",
        "Thin lines: database connection (JDBC :5432); every connector unit has its own PostgreSQL 16 (0.5 CPU, 256 MB).",
    ], size=14, lh=22)
    s.text(1000, ly + 28, ["Notes"], size=15, bold=True)
    s.text(1000, ly + 56, [
        "Dotted: not timed (ssh from the controller; TC4 reads",
        "the alert through the AAS instead of the simulator).",
        "Greyed: deployed, but not used by the pull tests.",
        "Data path: source, provider Data Plane, consumer",
        "Data Plane, pull client. The client never holds the token.",
        "All traffic between servers goes over the",
        "Tailscale (WireGuard) overlay network.",
        "Connector containers: EDC 0.14.1, 4 CPU / 4 GB each.",
        "Database sync write: time of one synchronous disk",
        "write, measured with pg_test_fsync (8 October 2026).",
    ], size=14, lh=22)
    return s.render(TITLE[arch])


def main():
    timings = json.loads((HERE / "timings.json").read_text())
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.mmd"):
        old.unlink()
    for arch, t in timings.items():
        (OUT / f"{arch}.svg").write_text(build(arch, t))
    print("Wrote", ", ".join(f"architecture/{a}.svg" for a in timings))


if __name__ == "__main__":
    main()
