#!/usr/bin/env python3
"""
pull-client.py — the consumer's side of an EDC PULL transfer, timed.

Runs ON THE CONSUMER MACHINE (run-all-tests.sh starts it there), so every time
it reports is taken on one clock, next to the consumer's Control Plane:

  1. starts a transfer of type HttpData-PULL under an existing agreement;
  2. waits for the Endpoint Data Reference (EDR) — the provider Data Plane's
     address and an access token — to appear on the consumer's Control Plane;
  3. fetches the data COUNT times from that address with the token, over one
     kept-alive connection, like a consumer application reading repeatedly.
     With --proxy it fetches through the consumer's own Data Plane instead
     (GET <proxy>/<transfer id>, no token): that Data Plane holds the token
     and fetches from the provider's Data Plane, so the data travels Data
     Plane to Data Plane.
     With --duration it instead keeps fetching for that many seconds, to see
     when a time-limited contract stops giving access.

Fixed schedule (--rate HZ --duration S): fetch slot k is due at
start + k/HZ, however long earlier fetches took — the way an application
that needs the data at that rate would ask for it. A fetch meets its deadline
if it has the data within --deadline-ms of its slot (default: one period). A
slot whose time is already a full period past when a worker gets to it is
skipped and counted as missed, so a slow path cannot catch up in bursts.
--parallel N spreads the slots over N workers, each with its own connection.

--source-url URL is the baseline without EDC: no transfer, no token; the same
fetches go straight to the data source.

Enforcement tests (measurement set D):
  --terminate-after S   S seconds into the fetching, the PROVIDER terminates the
                        transfer through its Management API (--provider-mgmt),
                        as its operator would; the fetches go on, to see when
                        the token stops working. Times in "terminate".
  --token-tests N       before the normal fetches, N fetches each with no token
                        and with a wrong one (the real token with its signature
                        altered); statuses and times in "token_tests".

Prints one JSON document:
  setup_ms        transfer request → EDR available (paid once per transfer)
  via             "provider-dp" (direct), "consumer-dp" (through the proxy)
                  or "source" (baseline, no EDC)
  fetches[]       per fetch: start (unix s), elapsed_ms, status, size_bytes,
                  payload_timestamp (the data source's stamp, its own clock);
                  on a schedule also slot, late_ms (start − slot time),
                  deadline_met, worker
  schedule        on a schedule: rate, deadline, slots, skipped slots, deadline
                  misses and the rate achieved

Standard library only.
"""
import argparse
import http.client
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


def call(method, url, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def field(doc, name):
    """EDC may return a property bare or under its namespace."""
    for k, v in doc.items():
        if k == name or k.endswith("/" + name) or k.endswith(":" + name):
            return v
    return None


def fetch_once(conn, u, path, headers):
    """One GET over a kept-alive connection; returns (record, connection to use next)."""
    start = time.time()
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        status = resp.status
    except (http.client.HTTPException, OSError) as e:
        conn.close()
        return {"start": round(start, 6), "elapsed_ms": round((time.time() - start) * 1000, 2),
                "error": str(e)}, http.client.HTTPConnection(u.hostname, u.port or 80, timeout=300)
    elapsed = (time.time() - start) * 1000
    stamp = None
    try:
        stamp = float(json.loads(body).get("timestamp_unix"))
    except (ValueError, TypeError, AttributeError):
        pass
    return {"start": round(start, 6), "elapsed_ms": round(elapsed, 2), "status": status,
            "size_bytes": len(body), "payload_timestamp": stamp}, conn


def token_tests(u, path, token, n):
    """n fetches with no token and n with a wrong one, each on a fresh connection."""
    # a JWT is header.payload.signature: change the signature's first character
    head, _, sig = token.rpartition(".")
    wrong = f"{head}.{'A' if sig[:1] != 'A' else 'B'}{sig[1:]}" if head else token[:-1] + ("x" if token[-1:] != "x" else "y")
    results = {}
    for name, hdrs in (("no_token", {}), ("wrong_token", {"Authorization": wrong})):
        rows = []
        for _ in range(n):
            conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=30)
            rec, conn = fetch_once(conn, u, path, hdrs)
            conn.close()
            rows.append({k: rec.get(k) for k in ("status", "elapsed_ms", "size_bytes", "error") if rec.get(k) is not None})
        results[name] = rows
    return results


def terminate_later(provider_mgmt, consumer_tp_id, at, record):
    """At time `at`, terminate the transfer on the provider's side (its own id
    for it carries the consumer's id as correlationId)."""
    try:
        found = []
        while not found and time.time() < at + 30:
            found = call("POST", f"{provider_mgmt}/transferprocesses/request", {
                "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                "@type": "QuerySpec",
                "filterExpression": [{"operandLeft": "correlationId", "operator": "=", "operandRight": consumer_tp_id}],
            }) or []
            if not found:
                time.sleep(0.5)
        if not found:
            record["error"] = "provider has no transfer with this correlationId"
            return
        provider_tp_id = found[0]["@id"]
        record["provider_transfer_id"] = provider_tp_id
        if time.time() < at:
            time.sleep(at - time.time())
        record["requested_at"] = round(time.time(), 6)
        req = urllib.request.Request(f"{provider_mgmt}/transferprocesses/{provider_tp_id}/terminate", method="POST",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps({"@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                                                      "@type": "TerminateTransfer", "reason": "set D: provider terminates"}).encode())
        with urllib.request.urlopen(req, timeout=30) as r:
            record["status"] = r.status
        record["answered_at"] = round(time.time(), 6)
    except Exception as e:      # recorded, the fetching goes on
        record["error"] = repr(e)


def run_schedule(u, path, headers, rate, duration, deadline_ms, workers, new_connection=False):
    """Fetch on a fixed schedule (see the module doc); returns (fetches, summary).
    new_connection: open a fresh connection for every fetch instead of keeping one alive."""
    period = 1.0 / rate
    slots = int(round(duration * rate))
    lock = threading.Lock()
    state = {"next": 0}
    fetches, skipped = [], []
    t0 = time.time() + 0.5          # let every worker open its connection first

    def worker(w):
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=300)
        while True:
            with lock:
                k = state["next"]
                state["next"] += 1
            if k >= slots:
                break
            due = t0 + k * period
            now = time.time()
            if now < due:
                time.sleep(due - now)
            elif now - due >= period:
                with lock:
                    skipped.append(k)
                continue
            if new_connection:
                conn.close()
                conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=300)
            rec, conn = fetch_once(conn, u, path, headers)
            rec.update({"slot": k, "worker": w, "late_ms": round((rec["start"] - due) * 1000, 2)})
            if rec.get("status") == 200:
                rec["deadline_met"] = (rec["start"] - due) * 1000 + rec["elapsed_ms"] <= deadline_ms
            else:
                rec["deadline_met"] = False
            with lock:
                fetches.append(rec)
        conn.close()

    crashed = []

    def guarded(w):
        try:
            worker(w)
        except Exception as e:     # a dead worker must fail the run, not read as missed slots
            crashed.append(repr(e))

    threads = [threading.Thread(target=guarded, args=(w,)) for w in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if crashed:
        raise RuntimeError(f"fetch worker failed: {crashed[0]}")
    fetches.sort(key=lambda f: f["slot"])
    ok = [f for f in fetches if f.get("status") == 200]
    met = sum(1 for f in fetches if f["deadline_met"])
    summary = {
        "rate_hz": rate, "period_ms": round(period * 1000, 3), "deadline_ms": deadline_ms,
        "duration_s": duration, "parallel": workers, "new_connection": new_connection, "started_at": round(t0, 6),
        "slots": slots, "fetched": len(fetches), "ok": len(ok), "skipped_slots": len(skipped),
        "deadline_met": met, "missed": slots - met,
        "missed_pct": round(100 * (slots - met) / slots, 3) if slots else None,
        "achieved_hz": round(len(ok) / duration, 3),
    }
    return fetches, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mgmt", help="consumer management API base, e.g. http://host:9192/management/v3")
    ap.add_argument("--provider-dsp")
    ap.add_argument("--agreement")
    ap.add_argument("--rate", type=float, help="fetch on a fixed schedule of this many per second (needs --duration)")
    ap.add_argument("--deadline-ms", type=float, help="on a schedule: deadline after each slot (default one period)")
    ap.add_argument("--parallel", type=int, default=1, help="on a schedule: workers, each with its own connection")
    ap.add_argument("--new-connection", action="store_true", help="on a schedule: a fresh connection for every fetch (diagnostic)")
    ap.add_argument("--source-url", help="baseline without EDC: fetch straight from this data-source URL")
    ap.add_argument("--terminate-after", type=float, help="provider terminates the transfer this many seconds into the fetching")
    ap.add_argument("--provider-mgmt", help="provider management API base, for --terminate-after")
    ap.add_argument("--token-tests", type=int, default=0, help="fetches each with no token and a wrong token first")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--interval", type=float, default=0.2, help="pause between fetches, seconds")
    ap.add_argument("--trigger-url", help="POST here before each fetch (TC-4: fires the alert)")
    ap.add_argument("--duration", type=float, help="fetch for this many seconds instead of COUNT times")
    ap.add_argument("--policy-valid-s", type=float, help="recorded in the output: how long the contract allows use")
    ap.add_argument("--edr-timeout", type=float, default=30)
    ap.add_argument("--proxy", help="consumer Data Plane pull proxy base, e.g. http://host:9296/proxy; "
                                    "fetch through it instead of from the provider's Data Plane")
    a = ap.parse_args()
    if a.rate and not a.duration:
        ap.error("--rate needs --duration")
    if a.terminate_after is not None and not a.provider_mgmt:
        ap.error("--terminate-after needs --provider-mgmt")
    if not a.source_url and not (a.mgmt and a.provider_dsp and a.agreement):
        ap.error("--mgmt, --provider-dsp and --agreement are needed unless --source-url is given")

    out = {"count": a.count}
    if a.source_url:
        # baseline: no EDC at all
        fetch_url, headers = a.source_url, {}
        out["via"] = "source"
    else:
        if a.policy_valid_s is not None:
            out["policy_valid_s"] = a.policy_valid_s
            # when the agreement was signed, as the consumer's Control Plane has it (whole seconds)
            out["agreement_signed_at"] = field(call("GET", f"{a.mgmt}/contractagreements/{a.agreement}"), "contractSigningDate")

        # 1. start the transfer
        t0 = time.time()
        tp = call("POST", f"{a.mgmt}/transferprocesses", {
            "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
            "@type": "TransferRequestDto",
            "connectorId": "provider",
            "counterPartyAddress": a.provider_dsp,
            "contractId": a.agreement,
            "protocol": "dataspace-protocol-http",
            "transferType": "HttpData-PULL",
        })
        transfer_id = tp["@id"]
        out["transfer_id"] = transfer_id
        out["requested_at"] = round(t0, 6)

        # 2. wait for the EDR
        edr = None
        while time.time() - t0 < a.edr_timeout:
            try:
                edr = call("GET", f"{a.mgmt}/edrs/{transfer_id}/dataaddress", timeout=5)
                break
            except urllib.error.HTTPError:
                time.sleep(0.01)
        if edr is None:
            state = field(call("GET", f"{a.mgmt}/transferprocesses/{transfer_id}"), "state")
            out["error"] = f"no EDR within {a.edr_timeout} s (transfer state {state})"
            print(json.dumps(out))
            return 1
        out["setup_ms"] = round((time.time() - t0) * 1000, 2)
        endpoint, token = field(edr, "endpoint"), field(edr, "authorization")
        out["endpoint"] = endpoint
        if a.proxy:
            fetch_url, headers = f"{a.proxy.rstrip('/')}/{transfer_id}", {}
        else:
            fetch_url, headers = endpoint, {"Authorization": token}
        out["via"] = "consumer-dp" if a.proxy else "provider-dp"

    # 3. fetch: on a fixed schedule, or repeatedly with a pause, over kept-alive connections
    out["fetch_url"] = fetch_url
    u = urllib.parse.urlparse(fetch_url)
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    if a.token_tests and not a.source_url and not a.proxy:
        out["token_tests"] = token_tests(u, path, headers["Authorization"], a.token_tests)
    if a.rate:
        deadline_ms = a.deadline_ms if a.deadline_ms is not None else 1000.0 / a.rate
        out["fetches"], out["schedule"] = run_schedule(u, path, headers, a.rate, a.duration, deadline_ms, a.parallel, a.new_connection)
        print(json.dumps(out))
        return 0
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=300)
    fetches = []
    fetch_start = time.time()
    if a.terminate_after is not None:
        out["terminate"] = {"after_s": a.terminate_after}
        threading.Thread(target=terminate_later, daemon=True,
                         args=(a.provider_mgmt, out["transfer_id"], fetch_start + a.terminate_after, out["terminate"])).start()
    while (time.time() - fetch_start < a.duration) if a.duration else (len(fetches) < a.count):
        if a.trigger_url:
            urllib.request.urlopen(urllib.request.Request(a.trigger_url, data=b"", method="POST"), timeout=10).read()
        rec, conn = fetch_once(conn, u, path, headers)
        fetches.append(rec)
        time.sleep(a.interval)
    conn.close()
    out["fetches"] = fetches
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
