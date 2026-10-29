"""
EDC Test Plan — Data Receiver
Accepts HTTP push transfers from the EDC Consumer Data Plane and logs
timing/size metrics so test case performance can be measured.

Endpoints:
  POST /receive/tc1   — receives TC-1 control signal pushes
  POST /receive/tc2   — receives TC-2 sensor batch pushes
  POST /receive/tc3   — receives TC-3 video frame pushes
  GET  /metrics       — returns all logged transfer records
  GET  /metrics/<tc>  — returns records for a specific test case
  POST /reset         — clears all records (between test runs)
  GET  /health        — liveness check
"""

import time
import json
import statistics
from collections import defaultdict
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── In-memory log (cleared between test runs via POST /reset) ─────────────────
_records: dict[str, list] = defaultdict(list)
for _tc in ("tc1", "tc2", "tc3", "tc4"):
    _records[_tc]
_start_time = time.time()


def _num(v):
    """Timestamps may arrive as numbers or as strings (the AAS value-only
    serialisation BaSyx returns renders xs:double values as strings)."""
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _stats(values: list, prefix: str) -> dict:
    if not values:
        return {}
    return {
        f"{prefix}_min":    round(min(values), 2),
        f"{prefix}_max":    round(max(values), 2),
        f"{prefix}_avg":    round(statistics.mean(values), 2),
        f"{prefix}_median": round(statistics.median(values), 2),
        f"{prefix}_stdev":  round(statistics.stdev(values), 2) if len(values) > 1 else 0,
    }


def _record_transfer(tc: str) -> dict:
    # Read the whole body first: the arrival time is when the last byte is in,
    # which matters for large payloads (the handler starts after the headers).
    raw = request.get_data()
    received_at = time.time()
    size_bytes = len(raw)

    # Try to parse JSON for preview; fall back to raw bytes info
    preview = None
    ts_aas = None
    try:
        parsed = json.loads(raw)
        ts_sent = _num(parsed.get("timestamp_unix")) or _num(parsed.get("timestamp"))
        latency_ms = round((received_at - ts_sent) * 1000, 2) if ts_sent else None
        # TC-4 via the AAS: when the payload also says when it landed in the
        # AAS, split the end-to-end latency into source→AAS (one clock, on the
        # source machine) and AAS→receiver (crosses machines).
        ts_aas = _num(parsed.get("aas_written_unix"))
        preview = {k: v for k, v in parsed.items() if k not in ("data", "readings")}
    except Exception:
        ts_sent = None
        latency_ms = None

    record = {
        # Set by the test scripts through the transfer's data destination
        # ("header:X-Run-Id"), so each arrival can be matched to the transfer
        # that produced it — and to that transfer's creation time on
        # consumer-cp, which runs on this same machine (one clock).
        "run_id": request.headers.get("X-Run-Id"),
        "received_at": round(received_at, 6),
        "size_bytes": size_bytes,
        "content_type": request.content_type,
        "latency_ms": latency_ms,
        "sender_timestamp": ts_sent,
        "source_to_aas_ms": round((ts_aas - ts_sent) * 1000, 2) if ts_aas and ts_sent else None,
        "aas_to_receiver_ms": round((received_at - ts_aas) * 1000, 2) if ts_aas else None,
        "preview": preview,
    }
    _records[tc].append(record)

    print(
        f"[{tc.upper()}] received {size_bytes:,} bytes"
        + (f" | latency {latency_ms} ms" if latency_ms is not None else ""),
        flush=True,
    )
    return record


# ─────────────────────────────────────────────────────────────────────────────
# Receive endpoints — one per test case so logs stay separate
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/receive/tc1", methods=["POST"])
def receive_tc1():
    record = _record_transfer("tc1")
    return jsonify({"status": "ok", "tc": "tc1", "size_bytes": record["size_bytes"]})


@app.route("/receive/tc2", methods=["POST"])
def receive_tc2():
    record = _record_transfer("tc2")
    return jsonify({"status": "ok", "tc": "tc2", "size_bytes": record["size_bytes"]})


@app.route("/receive/tc3", methods=["POST"])
def receive_tc3():
    record = _record_transfer("tc3")
    return jsonify({"status": "ok", "tc": "tc3", "size_bytes": record["size_bytes"]})


@app.route("/receive/tc4", methods=["POST"])
def receive_tc4():
    record = _record_transfer("tc4")
    return jsonify({"status": "ok", "tc": "tc4", "size_bytes": record["size_bytes"]})


# Payload-size sweep (scripts/6-payload-sweep.sh): one log per size, e.g. s1048576
@app.route("/receive/<tc>", methods=["POST"])
def receive_sweep(tc: str):
    if not (tc.startswith("s") and tc[1:].isdigit()):
        return jsonify({"error": f"unknown test case '{tc}'"}), 404
    record = _record_transfer(tc)
    return jsonify({"status": "ok", "tc": tc, "size_bytes": record["size_bytes"]})


# ─────────────────────────────────────────────────────────────────────────────
# Metrics — summary + raw records
# ─────────────────────────────────────────────────────────────────────────────
def _summarise(records: list) -> dict:
    if not records:
        return {"count": 0}
    latencies = [r["latency_ms"] for r in records if r["latency_ms"] is not None]
    sizes = [r["size_bytes"] for r in records]
    summary = {
        "count": len(records),
        "total_bytes": sum(sizes),
        "avg_size_bytes": round(statistics.mean(sizes), 1) if sizes else None,
    }
    summary.update(_stats(latencies, "latency_ms"))
    summary.update(_stats([r["source_to_aas_ms"] for r in records if r.get("source_to_aas_ms") is not None], "source_to_aas_ms"))
    summary.update(_stats([r["aas_to_receiver_ms"] for r in records if r.get("aas_to_receiver_ms") is not None], "aas_to_receiver_ms"))
    return summary


@app.route("/metrics", methods=["GET"])
def metrics_all():
    return jsonify({
        "uptime_seconds": round(time.time() - _start_time, 1),
        "tc1": {"summary": _summarise(_records["tc1"]), "records": _records["tc1"][-20:]},
        "tc2": {"summary": _summarise(_records["tc2"]), "records": _records["tc2"][-20:]},
        "tc3": {"summary": _summarise(_records["tc3"]), "records": _records["tc3"][-20:]},
        "tc4": {"summary": _summarise(_records["tc4"]), "records": _records["tc4"][-20:]},
    })


@app.route("/metrics/<tc>", methods=["GET"])
def metrics_tc(tc: str):
    if tc not in _records:
        return jsonify({"error": f"no records for test case '{tc}'"}), 404
    return jsonify({
        "tc": tc,
        "summary": _summarise(_records[tc]),
        "records": _records[tc],
    })


@app.route("/reset", methods=["POST"])
def reset():
    for key in _records:
        _records[key].clear()
    return jsonify({"status": "reset", "message": "all records cleared"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "uptime_seconds": round(time.time() - _start_time, 1),
        "records": {k: len(v) for k, v in _records.items()},
    })


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "EDC Test Plan — Data Receiver",
        "endpoints": {
            "Receive TC-1": "POST /receive/tc1",
            "Receive TC-2": "POST /receive/tc2",
            "Receive TC-3": "POST /receive/tc3",
            "Receive TC-4": "POST /receive/tc4",
            "All metrics":  "GET  /metrics",
            "TC metrics":   "GET  /metrics/<tc1|tc2|tc3|tc4>",
            "Reset logs":   "POST /reset",
            "Health":       "GET  /health",
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4000, debug=False)
