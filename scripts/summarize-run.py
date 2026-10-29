#!/usr/bin/env python3
"""
summarize-run.py <run-dir>

Computes summary.json for one measurement run (see run-all-tests.sh) from the
raw files in <run-dir>, and prints a short table. Safe to re-run: it only reads
the raw files, so a summary can be recomputed after changing this script.

Latencies, and which clocks they depend on:

  request_to_received_ms
      consumer-cp creates the transfer → the receiver logs the arrival.
      Both run on the consumer's machine: ONE clock, no correction needed.
      Covers the whole governed path: DSP transfer request to the provider,
      CP → DP start signal, the DP fetching from the source, the push.

  source_to_received_ms
      payload timestamp (stamped on the data-source machine) → arrival on the
      consumer machine. TWO clocks: corrected with each machine's measured
      offset against NTP (median of the samples before and after the test
      case). Raw values are kept next to the corrected ones.

  source_to_aas_ms (TC-4 via the AAS)
      alert fired → written into the AAS. One clock (the source machine).

  aas_to_receiver_ms (TC-4 via the AAS)
      written into the AAS → arrival. Two clocks, corrected as above.

  phases_ms (not TC-4) — request_to_received_ms split at three points:
      request_to_provider   consumer CP creates the transfer → the provider's
                            CP has accepted the request (consumer CP's wait,
                            the DSP request over the network)
      provider_to_dp        → the provider's DP has the start signal (provider
                            CP's wait, the CP → DP signal)
      dp_to_source          → the data source answers the DP's fetch (DP's
                            wait, the request to the source)
      source_to_received    → the data is at the receiver (response from the
                            source, push to the consumer)
      Each step crosses machines and is corrected with both clocks' offsets;
      the four add up to request_to_received_ms. TC-4's payload is stamped when
      the alert fires, before the request, so it has no phases.

PULL test cases (pull-…, see 7-pull-transfer.sh and pull-client.py) have no
receiver: the consumer starts one transfer, gets the provider Data Plane's
address and an access token, and fetches the data repeatedly. For them:

  setup_ms                 transfer request → address and token available on
                           the consumer's Control Plane. One clock; paid once.
  request_to_received_ms   one fetch: request to the provider's Data Plane →
                           last byte back at the consumer. One clock. The first
                           fetch also opens the connection (first_fetch_ms);
                           the statistics are over the later ones.
  pull_phases_ms           request_to_source: fetch start → the data source
                           stamps the payload (the request reaching the DP, the
                           token check, the DP asking the source);
                           source_to_received: → last byte at the consumer.
                           Two clocks, corrected. For TC-4 the alert is fired
                           just before each fetch, so only source_to_received
                           (alert → consumer) is given.
  schedule                 fetches on a fixed schedule (PULL_RATE): rate,
                           deadline, slots, skipped slots, deadline misses
                           and the rate achieved, as pull-client.py counted
                           them; each record then has slot, late_ms and
                           deadline_met. via "source" is the baseline without
                           EDC (no setup, straight from the data source).

Offset convention: offset = NTP time − local clock (positive = local clock is
behind). A latency measured from machine S to machine C is corrected as
    true = measured + (offset_C − offset_S)
"""

PHASES = ("request_to_provider", "provider_to_dp", "dp_to_source", "source_to_received")
import json
import statistics
import sys
from pathlib import Path


def stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "stdev": round(statistics.stdev(values), 2) if len(values) > 1 else 0.0,
    }


def num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def read_tsv(path):
    if not path.exists():
        return []
    return [line.rstrip("\n").split("\t") for line in path.read_text().splitlines() if line.strip()]


def stats_file(path):
    """'name cpu mem_mb' lines → {name: [(cpu, mem), ...]}"""
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.split()
            if len(parts) == 3:
                out.setdefault(parts[0], []).append((num(parts[1]), num(parts[2])))
    return out


def main(run_dir: Path):
    meta = json.loads((run_dir / "meta.json").read_text())
    roles = meta["roles"]
    host_role = {}                        # host → the machine's label in clock.tsv
    for _label, machine, host, _offset in read_tsv(run_dir / "clock.tsv"):
        host_role.setdefault(host, machine)

    def machine_of(role):
        return host_role.get(roles[role]["host"], role)

    # ── Clocks ────────────────────────────────────────────────────────────────
    clock_rows = read_tsv(run_dir / "clock.tsv")      # label, machine, host, offset_s
    clocks = {}
    for label, machine, host, v in clock_rows:
        clocks.setdefault(machine, {"host": host, "samples": []})["samples"].append((label, float(v) * 1000))

    def offset_ms(machine, tc):
        vals = [v for label, v in clocks.get(machine, {}).get("samples", [])
                if label in (f"before-{tc}", f"after-{tc}")]
        return statistics.median(vals) if vals else None

    clock_summary = {}
    for machine, c in clocks.items():
        vals = [v for _, v in c["samples"]]
        firsts = [v for label, v in c["samples"] if label == c["samples"][0][0]]
        lasts = [v for label, v in c["samples"] if label == c["samples"][-1][0]]
        clock_summary[machine] = {
            "host": c["host"],
            "offset_ms": stats(vals),
            "drift_ms_over_run": round(statistics.median(lasts) - statistics.median(firsts), 2),
        }

    # ── Run log ───────────────────────────────────────────────────────────────
    log = read_tsv(run_dir / "run.log")
    negotiation = {r[1]: num(r[2]) for r in log if r[0] == "neg"}
    catalog = {r[1]: num(r[2]) for r in log if r[0] == "catalog"}   # catalogue request alone; also inside negotiation_ms
    retries = {}                                       # tc → failed attempts that were retried
    for r in log:
        if r[0] in ("neg_retry", "transfer_retry"):
            key = "negotiation_retries" if r[0] == "neg_retry" else "transfer_retries"
            retries.setdefault(r[1], {"negotiation_retries": 0, "transfer_retries": 0})[key] += 1
    exit_codes = {r[1]: int(r[2]) for r in log if r[0] == "exit"}
    transfers = {}                                     # tc → {run_id: transfer_id}
    for r in log:
        if r[0] == "transfer":
            transfers.setdefault(r[1], {})[r[2]] = r[3]

    # ── At-rest resources ─────────────────────────────────────────────────────
    at_rest = {name: samples[-1] for name, samples in stats_file(run_dir / "at-rest.txt").items()}

    source_m, consumer_m = machine_of("source"), machine_of("consumer")
    cp_m, dp_m = machine_of(meta["provider_cp_role"]), machine_of(meta["provider_dp_role"])

    def pipe_file(path, ncols):
        rows = []
        if path.exists():
            for line in path.read_text().splitlines():
                parts = line.strip().split("|")
                if len(parts) == ncols:
                    rows.append(parts)
        return rows
    def pull_case(tc, doc):
        """Summary of a PULL test case from pull-client.py's output."""
        off_src, off_con = offset_ms(source_m, tc), offset_ms(consumer_m, tc)
        have_clocks = off_src is not None and off_con is not None
        records = []
        for i, f in enumerate(doc.get("fetches", [])):
            if f.get("status") != 200:
                continue
            start, elapsed, stamp = f["start"] * 1000, f["elapsed_ms"], f.get("payload_timestamp")
            rec = {"fetch": i + 1, "request_to_received_ms": elapsed, "size_bytes": f.get("size_bytes")}
            if "slot" in f:   # fixed schedule (pull-client.py --rate)
                rec.update({"slot": f["slot"], "late_ms": f["late_ms"], "deadline_met": f["deadline_met"]})
            if stamp and have_clocks:
                src = stamp * 1000 + off_src
                rec["source_to_received_ms"] = round(start + elapsed + off_con - src, 2)
                if not tc.endswith("tc4"):
                    rec["request_to_source_ms"] = round(src - (start + off_con), 2)
            records.append(rec)
        later = records[1:] if len(records) > 1 else records
        # Time-limited contract: when did access actually stop?
        enforcement = None
        if doc.get("policy_valid_s") is not None and doc.get("agreement_signed_at"):
            fetches = doc.get("fetches", [])
            ok = [f for f in fetches if f.get("status") == 200]
            denied = [f for f in fetches if f.get("status") != 200 and ok and f["start"] > ok[0]["start"]]
            expires = float(doc["agreement_signed_at"]) + doc["policy_valid_s"]
            enforcement = {
                "policy_valid_s": doc["policy_valid_s"],
                "fetches_allowed": len(ok),
                "fetches_denied": len(denied),
                "denied_statuses": sorted({str(f.get("status", "error")) for f in denied}),
                # agreement time is known to the second, so these are ± 1 s
                "last_allowed_after_expiry_s": round(ok[-1]["start"] - expires, 2) if ok else None,
                "first_denied_after_expiry_s": round(denied[0]["start"] - expires, 2) if denied else None,
                "allowed_after_first_denial": sum(1 for f in ok if denied and f["start"] > denied[0]["start"]),
            }
        # Provider terminated the transfer (set D): when did access stop?
        termination = None
        term = doc.get("terminate")
        if term:
            fetches = doc.get("fetches", [])
            termination = dict(term)
            if term.get("requested_at"):
                after = [f for f in fetches if f["start"] >= term["requested_at"]]
                ok_after = [f for f in after if f.get("status") == 200]
                denied = [f for f in after if f.get("status") != 200]
                termination.update({
                    "fetches_allowed_after_request": len(ok_after),
                    "last_allowed_after_request_s": round(ok_after[-1]["start"] - term["requested_at"], 3) if ok_after else None,
                    "first_denied_after_request_s": round(denied[0]["start"] - term["requested_at"], 3) if denied else None,
                    "denied_statuses": sorted({str(f.get("status", "error")) for f in denied}),
                    "allowed_after_first_denial": sum(1 for f in ok_after if denied and f["start"] > denied[0]["start"]),
                })
        tokens = None
        if doc.get("token_tests"):
            tokens = {name: {"statuses": sorted({str(r.get("status", "error")) for r in rows}),
                             "elapsed_ms": stats([r.get("elapsed_ms") for r in rows])}
                      for name, rows in doc["token_tests"].items()}
        return {
            **({"provider_termination": termination} if termination else {}),
            **({"token_tests": tokens} if tokens else {}),
            "mode": "pull",
            "error": doc.get("error"),
            "transfers_requested": len(doc.get("fetches", [])) or doc.get("count", 0),
            "transfers_received": len(records),
            "via": doc.get("via"),
            "setup_ms": doc.get("setup_ms"),
            **({"schedule": doc["schedule"]} if doc.get("schedule") else {}),
            **({"policy_enforcement": enforcement} if enforcement else {}),
            "first_fetch_ms": records[0]["request_to_received_ms"] if records else None,
            "request_to_received_ms": stats([r["request_to_received_ms"] for r in later]),
            "source_to_received_ms": stats([r.get("source_to_received_ms") for r in later]),
            "pull_phases_ms": {
                "request_to_source": stats([r.get("request_to_source_ms") for r in later]),
                "source_to_received": stats([r.get("source_to_received_ms") for r in later]),
            },
            "records": later,
        }

    test_cases = {}
    for tc in sorted(transfers.keys() | exit_codes.keys()):
        receiver = json.loads((run_dir / f"receiver-{tc}.json").read_text() or "{}") \
            if (run_dir / f"receiver-{tc}.json").exists() else {}
        created = {}
        cpath = run_dir / f"created-{tc}.tsv"
        if cpath.exists():
            for line in cpath.read_text().splitlines():
                parts = line.strip().split("|")
                if len(parts) == 3:
                    created[parts[0]] = num(parts[1])  # ms since epoch, consumer clock

        off_src, off_con = offset_ms(source_m, tc), offset_ms(consumer_m, tc)
        correction = (off_con - off_src) if off_src is not None and off_con is not None else None
        off_cp, off_dp = offset_ms(cp_m, tc), offset_ms(dp_m, tc)

        # Provider-side timestamps (ms, each on its own machine's clock)
        provider_tp, provider_at = {}, {}               # consumer id → provider id / created
        for consumer_id, provider_id, created_at in pipe_file(run_dir / f"provider-cp-{tc}.tsv", 3):
            provider_tp[consumer_id], provider_at[consumer_id] = provider_id, num(created_at)
        dp_at = {pid: num(c) for pid, c in pipe_file(run_dir / f"provider-dp-{tc}.tsv", 2)}

        def phases(tp, created_ms, recv_s, src_s):
            """The four phases in ms on NTP time, or None where a timestamp or offset is missing."""
            if tc == "tc4" or None in (off_con, off_cp, off_dp, off_src):
                return None
            t = [created_ms + off_con if created_ms else None,
                 provider_at[tp] + off_cp if provider_at.get(tp) else None,
                 dp_at[provider_tp[tp]] + off_dp if dp_at.get(provider_tp.get(tp)) else None,
                 src_s * 1000 + off_src if src_s else None,
                 recv_s * 1000 + off_con if recv_s else None]
            if None in t:
                return None
            return {name: round(t[k + 1] - t[k], 2) for k, name in enumerate(PHASES)}

        run_to_tp = transfers.get(tc, {})
        records = []
        for rec in receiver.get("records", []):
            rid = rec.get("run_id")
            if rid not in run_to_tp:
                continue                                # not from this run
            tp = run_to_tp[rid]
            recv = num(rec.get("received_at"))
            created_ms = created.get(tp)
            raw = num(rec.get("latency_ms"))
            a2r = num(rec.get("aas_to_receiver_ms"))
            ph = phases(tp, created_ms, recv, num(rec.get("sender_timestamp")))
            records.append({
                "run_id": rid,
                "transfer_id": tp,
                "request_to_received_ms": round(recv * 1000 - created_ms, 2) if recv and created_ms else None,
                "source_to_received_ms_raw": raw,
                "source_to_received_ms": round(raw + correction, 2) if raw is not None and correction is not None else None,
                "source_to_aas_ms": num(rec.get("source_to_aas_ms")),
                "aas_to_receiver_ms": round(a2r + correction, 2) if a2r is not None and correction is not None else None,
                "size_bytes": rec.get("size_bytes"),
                **({"phases_ms": ph} if ph else {}),
            })

        # Resources during the test case, per container, on its own machine
        during = {}
        for f in run_dir.glob(f"stats-{tc}-*.txt"):
            machine = f.stem.split("-", 2)[2]
            for name, samples in stats_file(f).items():
                during[name] = {
                    "machine": machine,
                    "samples": len(samples),
                    "cpu_pct": stats([c for c, _ in samples]),
                    "mem_mb": stats([m for _, m in samples]),
                }
        resources = {}
        for name in sorted(set(during) | set(at_rest)):
            resources[name] = {
                "at_rest_cpu_pct": at_rest.get(name, (None, None))[0],
                "at_rest_mem_mb": at_rest.get(name, (None, None))[1],
                **({"during": during[name]} if name in during else {}),
            }

        pull_file = run_dir / f"pull-{tc}.json"
        if pull_file.exists():
            test_cases[tc] = {
                "exit_code": exit_codes.get(tc),
                "negotiation_ms": negotiation.get(tc),
                "catalog_ms": catalog.get(tc),
                **retries.get(tc, {"negotiation_retries": 0, "transfer_retries": 0}),
                **pull_case(tc, json.loads(pull_file.read_text() or "{}")),
                "resources": resources,
            }
            continue

        test_cases[tc] = {
            "exit_code": exit_codes.get(tc),
            "transfers_requested": len(run_to_tp),
            "transfers_received": len(records),
            "negotiation_ms": negotiation.get(tc),
            "catalog_ms": catalog.get(tc),
            **retries.get(tc, {"negotiation_retries": 0, "transfer_retries": 0}),
            "request_to_received_ms": stats([r["request_to_received_ms"] for r in records]),
            "source_to_received_ms": stats([r["source_to_received_ms"] for r in records]),
            "source_to_received_ms_raw": stats([r["source_to_received_ms_raw"] for r in records]),
            "clock_correction_ms": round(correction, 2) if correction is not None else None,
            **({"source_to_aas_ms": stats([r["source_to_aas_ms"] for r in records]),
                "aas_to_receiver_ms": stats([r["aas_to_receiver_ms"] for r in records])}
               if any(r["source_to_aas_ms"] is not None for r in records) else {}),
            **({"phases_ms": {name: stats([r["phases_ms"][name] for r in records if "phases_ms" in r])
                              for name in PHASES}}
               if any("phases_ms" in r for r in records) else {}),
            "resources": resources,
            "records": records,
        }

    summary = {
        "meta": meta,
        "network_rtt_ms": [{"from": a, "to": b, "rtt_ms": num(v)} for a, b, v in read_tsv(run_dir / "network.tsv")],
        "clocks": clock_summary,
        "test_cases": test_cases,
        "notes": __doc__.split("Latencies, and which clocks they depend on:")[1].strip(),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # ── Printed table ─────────────────────────────────────────────────────────
    print(f"Architecture: {meta['architecture']}   (provider CP on {meta['provider_cp_role']}, "
          f"DP on {meta['provider_dp_role']})   timing: {meta.get('timing', 'default')} "
          f"(EDC transfer wait {meta.get('edc_transfer_wait_ms', 1000)} ms, "
          f"negotiation wait {meta.get('edc_negotiation_wait_ms', 1000)} ms)")
    for machine, c in clock_summary.items():
        print(f"  clock {machine:<9} {c['offset_ms'].get('median', '?'):>8} ms vs NTP"
              f"   (drift over run {c['drift_ms_over_run']} ms)")
    print()
    print(f"  {'':4} {'n':>3} {'negotiation':>12} {'request→received':>17} {'source→received':>16} {'DP RAM':>8} {'DP CPU':>7}")
    print(f"  {'':4} {'':>3} {'ms':>12} {'median ms':>17} {'median ms*':>16} {'avg MB':>8} {'avg %':>7}")
    for tc, t in test_cases.items():
        dp = t["resources"].get("provider-dp", {}).get("during", {})
        print(f"  {tc:4} {t['transfers_received']:>3} {t['negotiation_ms'] or '-':>12} "
              f"{t['request_to_received_ms'].get('median', '-'):>17} "
              f"{t['source_to_received_ms'].get('median', '-'):>16} "
              f"{dp.get('mem_mb', {}).get('avg', '-'):>8} {dp.get('cpu_pct', {}).get('avg', '-'):>7}")
    print("  * clock-corrected (two machines); request→received is on one clock")
    if any(t.get("mode") == "pull" for t in test_cases.values()):
        print()
        print(f"  pull, ms            {'setup':>9} {'first fetch':>12} {'fetch median':>13} {'request→source':>15} {'source→received':>16}")
        for tc, t in test_cases.items():
            if t.get("mode") == "pull":
                p = t["pull_phases_ms"]
                print(f"  {tc:<19} {t.get('setup_ms') or '-':>9} {t.get('first_fetch_ms') or '-':>12} "
                      f"{t['request_to_received_ms'].get('median', '-'):>13} "
                      f"{p['request_to_source'].get('median', '-'):>15} {p['source_to_received'].get('median', '-'):>16}")
                e = t.get("policy_enforcement")
                if e:
                    print(f"    policy valid {e['policy_valid_s']:g} s: {e['fetches_allowed']} fetches allowed, {e['fetches_denied']} denied "
                          f"({', '.join(e['denied_statuses']) or '-'}); last allowed {e['last_allowed_after_expiry_s']} s, "
                          f"first denied {e['first_denied_after_expiry_s']} s after expiry (± 1 s)")
    if any("phases_ms" in t for t in test_cases.values()):
        print()
        print(f"  phases, median ms   {'request→provider':>17} {'provider→DP':>12} {'DP→source':>10} {'source→received':>16}")
        for tc, t in test_cases.items():
            if "phases_ms" in t:
                p = t["phases_ms"]
                print(f"  {tc:<19} " + " ".join(f"{p[n].get('median', '-'):>{w}}" for n, w in zip(PHASES, (17, 12, 10, 16))))
    print(f"\nSummary: {run_dir / 'summary.json'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
