"""
review_rerun.py — evaluates the review re-runs of 27 October 2026 (set R of
scripts/run-measurement-set.sh), supplementary to the protocol runs of 22 October.

  linkcut  Hybrid, three cuts of the CP-DP link starting 28, 18 and 8 s before the
           contract expires; as rq3.py, plus the provider planes' logs and transfer
           records saved by run-all-tests.sh (when the termination reached the DP)
  push1hz  TC2 push at 1 Hz for 300 s per placement: a slot meets its deadline if
           its data arrive within 1 s of its due time (creation on consumer-cp +
           request_to_received, both on the consumer machine's clock, minus the due
           time logged by 3-tc2-high-freq-sensors.sh on the same machine); skipped
           slots count as missed, as in pull
  pulldef  TC2 pull at 1 Hz for 300 s, one worker, EDC's default profile

Writes analysis/out/review_rerun.json. Run from the repository root:
    analysis/.venv/bin/python analysis/review_rerun.py
"""
import json
import re
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PLACEMENTS, RESULTS, load, raw, write_numbers  # noqa: E402


def latest(pattern):
    runs = sorted(d.name for d in RESULTS.glob(pattern) if (d / "summary.json").exists())
    return runs[-1] if runs else None


def ok(f):
    return f.get("status") == 200


def pct(v, q):
    return round(float(np.percentile(v, q)), 1)


N = {"runs": {}}

# ── link cut ─────────────────────────────────────────────────────────────────
N["linkcut"] = {}
for at in (20, 30, 40):
    run = latest(f"*-hybrid-tuned-nosync-R-linkcut-at{at}")
    if not run:
        continue
    N["runs"][f"linkcut-at{at}"] = run
    d = RESULTS / run
    lc = raw(run, "pull-pull-timed-linkcut.json")
    marks = dict(line.split() for line in (d / "linkcut-pull-timed-linkcut.txt").read_text().splitlines()
                 if line.split()[0] in ("cut", "restored"))
    cut, restored = float(marks["cut"]), float(marks["restored"])
    exp = float(lc["agreement_signed_at"]) + lc["policy_valid_s"]
    f = lc["fetches"]
    served_cut = [x for x in f if ok(x) and exp <= x["start"] < restored]
    after = [x for x in f if x["start"] >= exp]
    first_denied = next((x for x in after if not ok(x)), None)
    res = {
        "cut_rel_expiry_s": round(cut - exp, 2),
        "restored_rel_expiry_s": round(restored - exp, 2),
        "served_after_expiry_while_cut": len(served_cut),
        "served_after_expiry_total": sum(ok(x) for x in after),
        "first_denied_rel_expiry_s": round(first_denied["start"] - exp, 2) if first_denied else None,
        "first_denied_after_restore_s": round(first_denied["start"] - restored, 2) if first_denied else None,
        "allowed_after_first_denial": (sum(ok(x) for x in after if x["start"] > first_denied["start"])
                                       if first_denied else None),
        "fetches": len(f),
    }
    # When did the DP's data flow end? (DP database, DP machine clock)
    flows = [json.loads(line) for line in (d / "db-provider-dp-flows-pull-timed-linkcut.jsonl").read_text().splitlines()
             if line.startswith("{")] if (d / "db-provider-dp-flows-pull-timed-linkcut.jsonl").exists() else []
    tps = [json.loads(line) for line in (d / "db-provider-cp-transfers-pull-timed-linkcut.jsonl").read_text().splitlines()
           if line.startswith("{")] if (d / "db-provider-cp-transfers-pull-timed-linkcut.jsonl").exists() else []
    toks = [line for line in (d / "db-provider-dp-tokens-pull-timed-linkcut.jsonl").read_text().splitlines()
            if line.startswith("{")] if (d / "db-provider-dp-tokens-pull-timed-linkcut.jsonl").exists() else []

    def ts_rel(ms):
        return None if ms is None else round(ms / 1000 - exp, 2)

    # State codes of EDC 0.14.1 (DataFlowStates, TransferProcessStates; read from the jars)
    dp_names = {150: "STARTED", 200: "COMPLETED", 250: "TERMINATED", 300: "FAILED"}
    cp_names = {600: "STARTED", 825: "TERMINATING", 850: "TERMINATED", 900: "DEPROVISIONING", 1000: "DEPROVISIONED"}
    res["dp_flows"] = [{"state": dp_names.get(x.get("state"), x.get("state")),
                        "state_rel_expiry_s": ts_rel(x.get("state_time_stamp")),
                        # link-cut.sh and the DP database both run on the DP's machine: one clock
                        "state_after_restore_s": round(x["state_time_stamp"] / 1000 - restored, 2)} for x in flows]
    res["cp_transfers"] = [{"state": cp_names.get(x.get("state"), x.get("state")),
                            "state_rel_expiry_s": ts_rel(x.get("state_time_stamp")),
                            "error": x.get("error_detail")} for x in tps]
    res["dp_tokens_left"] = len(toks)
    # log lines about termination, signalling or connection failures (each machine's clock)
    for plane in ("cp", "dp"):
        p = d / f"log-provider-{plane}-pull-timed-linkcut.txt"
        lines = p.read_text(errors="replace").splitlines() if p.exists() else []
        pat = re.compile(r"(?i)terminat|signal|connect|refused|timed? ?out|unreachable|WARNING|SEVERE|revok|expir")
        res[f"log_{plane}_lines"] = len(lines)
        res[f"log_{plane}_matches"] = [line[:300] for line in lines if pat.search(line)][:60]
    N["linkcut"][f"at{at}"] = res

# ── push at 1 Hz ─────────────────────────────────────────────────────────────
N["push1hz"] = {}
for p in PLACEMENTS:
    run = latest(f"*-{p}-tuned-nosync-R-push1hz")
    if not run:
        continue
    N["runs"][f"push1hz-{p}"] = run
    d = RESULTS / run
    t = load(run)["test_cases"]["tc2"]
    log = (d / "run.log").read_text().splitlines()
    due = {int(c[2]): int(c[3]) / 1e6 for c in (x.split("\t") for x in log) if c[0] == "push_due"}
    skipped = [int(c[2]) for c in (x.split("\t") for x in log) if c[0] == "push_skip"]
    created = {}
    for line in (d / "created-tc2.tsv").read_text().splitlines():
        parts = line.split("|")
        if len(parts) >= 2:
            created[parts[0]] = float(parts[1])
    slots = 300
    late, r2r, lag, slow = [], [], [], []
    for rec in t["records"]:
        k = int(rec["run_id"].split("-")[1])
        v = rec.get("request_to_received_ms")
        if v is None or rec["transfer_id"] not in created or k not in due:
            continue
        arrival_ms = created[rec["transfer_id"]] + v
        late.append(arrival_ms - due[k])
        lag.append(created[rec["transfer_id"]] - due[k])   # client: due time -> transfer created
        if v > 1000:
            slow.append({"slot": k, "ms": round(v, 1), "phases_ms": rec.get("phases_ms")})
        if k > 1:
            r2r.append(v)
    met = sum(x <= 1000 for x in late)
    N["push1hz"][p] = {
        "slots": slots, "transfers_received": t["transfers_received"], "skipped": len(skipped),
        "deadline_met": met, "missed": slots - met, "missed_pct": round(100 * (slots - met) / slots, 2),
        "achieved_hz": round(t["transfers_received"] / slots, 3),
        "arrival_after_due_ms": {"median": round(statistics.median(late), 1), "p99": pct(late, 99),
                                 "max": round(max(late), 1)} if late else None,
        "request_to_received_ms": {"n": len(r2r), "median": round(statistics.median(r2r), 1),
                                   "p95": pct(r2r, 95), "p99": pct(r2r, 99), "max": round(max(r2r), 1)} if r2r else None,
        "retries": [t["negotiation_retries"], t["transfer_retries"]],
        # The test client starts a transfer only after it has seen the previous one
        # complete (state polled every 0.5 s), so a slow transfer delays the next
        # start. Independent of the client: transfers whose own request-to-received
        # time exceeded the 1 s deadline.
        "client_start_lag_ms": {"median": round(statistics.median(lag), 1),
                                "p90": pct(lag, 90), "max": round(max(lag), 1)} if lag else None,
        "transfers_over_deadline": len(slow),
        "transfers_over_deadline_pct": round(100 * len(slow) / len(late), 2) if late else None,
        "slow_transfers": slow,
    }

# ── pull, EDC defaults ───────────────────────────────────────────────────────
N["pulldef"] = {}
for p in PLACEMENTS:
    run = latest(f"*-{p}-default-R-pulldef")
    if not run:
        continue
    N["runs"][f"pulldef-{p}"] = run
    t = load(run)["test_cases"]["pull-tc2"]
    v = [rec["request_to_received_ms"] for rec in t["records"] if rec.get("request_to_received_ms") is not None]
    N["pulldef"][p] = {"schedule": t["schedule"], "setup_ms": t.get("setup_ms"),
                       "fetch_ms": {"n": len(v), "median": round(statistics.median(v), 1),
                                    "p99": pct(v, 99), "max": round(max(v), 1)} if v else None}

write_numbers("review_rerun", N)
print(json.dumps({k: v for k, v in N.items() if k != "linkcut"}, indent=1)[:4000])
for k, v in N["linkcut"].items():
    print(k, {x: v[x] for x in v if not x.startswith("log_")})
