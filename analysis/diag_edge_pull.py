"""
diag_edge_pull.py — evaluates the diagnostic set X of 26 October 2026 (not a protocol set).

Question: why is a TC3 pull fetch through the edge Data Plane slower than through the
cloud Data Plane (Set B: 559-588 ms against 304 ms)? Set X fetches TC3 at 24 Hz for 120 s
with one worker, once over one kept-alive connection (as in Set B) and once with a new
connection per fetch, while diag-monitor.sh samples the TCP state of the Data Plane's
connections (ss -tinm, inside the container) and the machine's CPU (vmstat) every second.

Prints, per run: fetch time per 20 s window, median fetch time, and for the connection
from the Data Plane's public API (:8284) to the consumer the median and maximum of the
congestion window, the smoothed RTT, the retransmitted segments and the send queue;
and the CPU steal and I/O wait of the machine. Writes analysis/out/diag_edge_pull.json.
"""
import json
import re
import statistics as st
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "results"
OUT = Path(__file__).resolve().parent / "out"


def fetch_stats(d):
    j = json.loads((d / "pull-pull-tc3.json").read_text())
    f = [x for x in j["fetches"] if x.get("status") == 200][1:]     # warm-up rule: first fetch excluded
    t0 = j["schedule"]["started_at"]
    win = {}
    for x in f:
        win.setdefault(int((x["start"] - t0) // 20), []).append(x["elapsed_ms"])
    e = sorted(x["elapsed_ms"] for x in f)
    return {"n": len(e), "median_ms": st.median(e), "p10_ms": e[len(e) // 10], "p90_ms": e[9 * len(e) // 10],
            "achieved_hz": j["schedule"]["achieved_hz"],
            "window_medians_ms": [round(st.median(win[k])) for k in sorted(win)]}


def ss_stats(d):
    """Samples of the connections whose local port is 8284 (the public API, to the consumer)."""
    p = d / "diag-ss.txt"
    if not p.exists():
        return None
    rows, cur = [], None
    for ln in p.read_text().splitlines():
        if ln.startswith("@ "):
            continue
        if re.match(r"^\s*\d+\s+\d+\s+\S+:\d+\s+\S+", ln):
            q = ln.split()
            cur = {"send_q": int(q[1]), "local": q[2], "peer": q[3]}
            continue
        if cur is not None and "cwnd:" in ln:
            g = lambda k: (re.search(rf"\b{k}:([\d.]+)", ln) or [None, None])[1]
            cur.update(cwnd=g("cwnd"), rtt=(re.search(r"\brtt:([\d.]+)", ln) or [None, None])[1],
                       retrans_total=(re.search(r"\bretrans:\d+/(\d+)", ln) or [None, None])[1],
                       ssthresh=g("ssthresh"), unacked=g("unacked"), lost=g("lost"),
                       snd_wnd=g("snd_wnd"), delivery_rate=(re.search(r"delivery_rate (\S+)", ln) or [None, None])[1])
            rows.append(cur)
            cur = None
    pub = [r for r in rows if r["local"].endswith(":8284")]

    def num(k):
        return [float(r[k]) for r in pub if r.get(k) is not None]
    out = {"samples": len(pub), "connections": len({r["peer"] for r in pub})}
    for k in ("cwnd", "rtt", "ssthresh", "send_q", "snd_wnd"):
        v = num(k)
        if v:
            out[k] = {"median": st.median(v), "min": min(v), "max": max(v)}
    rt = num("retrans_total")
    out["retrans_segments_max"] = max(rt) if rt else 0
    return out


def vm_stats(d):
    p = d / "diag-vmstat.txt"
    if not p.exists():
        return None
    head, rows = None, []
    for ln in p.read_text().splitlines():
        q = ln.split()
        if "us" in q and "st" in q:
            head = q
        elif head and q and q[0].isdigit():
            rows.append(dict(zip(head, q)))
    col = lambda k: [int(r[k]) for r in rows if k in r]
    return {k: {"median": st.median(col(k)), "max": max(col(k))} for k in ("us", "sy", "wa", "st") if col(k)}


def main():
    runs = sorted(RESULTS.glob("20261026T*-tuned-nosync-X-*")) + sorted(RESULTS.glob("20261027T*-tuned-nosync-X-*"))
    if not runs:
        sys.exit("no set X runs found")
    res = {}
    for d in runs:
        r = {"fetch": fetch_stats(d), "tcp_public": ss_stats(d), "cpu": vm_stats(d)}
        res[d.name] = r
        f = r["fetch"]
        print(f"\n{d.name}\n  fetch median {f['median_ms']:.0f} ms (p10 {f['p10_ms']:.0f}, p90 {f['p90_ms']:.0f}), "
              f"{f['achieved_hz']} Hz, n={f['n']}\n  per 20 s: {f['window_medians_ms']}")
        print(f"  tcp :8284 {json.dumps(r['tcp_public'])}")
        print(f"  cpu       {json.dumps(r['cpu'])}")
    OUT.mkdir(exist_ok=True)
    (OUT / "diag_edge_pull.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
