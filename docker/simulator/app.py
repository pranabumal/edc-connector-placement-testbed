"""
EDC Test Plan — Data Simulator
Serves realistic test data for four test cases from the TUNI EDC Test Plan:
  TC-1: Real-time control (near-real-time, 10-100 Hz range)
  TC-2: High-frequency sensors (1 kHz vibration sensor batches)
  TC-3: Video stream (640x480 simulated JPEG frame, ~24 fps target)
  TC-4: Triggered event alert (threshold-crossing flag on TC-2's SensorData fields)

The EDC Provider Data Plane will fetch from these endpoints and push
data to the Receiver service when a transfer process is started.
"""

import time
import math
import random
import json
import base64
import struct
import os
import urllib.request
from flask import Flask, jsonify, Response, request

app = Flask(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────
_start_time = time.time()

# Every request for a test case returns the same payload, byte for byte, apart
# from the timestamps (and TC-4's alert id), so runs on different architectures
# transfer identical data of identical size.
_TC2_NOISE_SEED = 2


def _ts(t: float) -> str:
    """Unix time with a fixed number of digits, so the payload size is constant."""
    return f"{t:.6f}"


# ─────────────────────────────────────────────────────────────────────────────
# TC-1: Real-time control signal
# Simulates a position/velocity control loop output at ~50 Hz.
# Payload is small (~200 bytes) but time-sensitive.
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/tc1/control-signal", methods=["GET"])
def tc1_control_signal():
    t = time.time()
    # One fixed sample of a sinusoidal setpoint with a position error
    elapsed = 0.15
    setpoint = round(math.sin(2 * math.pi * 0.5 * elapsed), 4)
    actual = round(setpoint + 0.0041, 4)
    return jsonify({
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int((t % 1) * 1000):03d}Z",
        "timestamp_unix": _ts(t),
        "signal_type": "position_control",
        "actuator_id": "AGV-001",
        "axis": "x",
        "setpoint": setpoint,
        "actual": actual,
        "error": round(setpoint - actual, 4),
        "velocity": round(math.cos(2 * math.pi * 0.5 * elapsed) * 0.5, 4),
        "control_mode": "PID",
        "frequency_hz": 50,
        "unit": "meters",
    })


# ─────────────────────────────────────────────────────────────────────────────
# TC-2: High-frequency sensor batch
# Simulates a vibration accelerometer at 1 kHz, returning a batch of
# 1000 readings (~1 second of data) as a single HTTP response.
# Payload is large (~50 KB JSON).
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/tc2/sensor-batch", methods=["GET"])
def tc2_sensor_batch():
    t = time.time()
    sample_rate = 1000   # Hz
    sample_count = 1000  # 1 second of data per batch

    # Simulate vibration: dominant frequency 50 Hz + harmonics + noise
    noise = random.Random(_TC2_NOISE_SEED)   # same noise in every batch
    readings = []
    for i in range(sample_count):
        t_sample = i / sample_rate
        value = (
            1.5 * math.sin(2 * math.pi * 50 * t_sample)       # 50 Hz fundamental
            + 0.3 * math.sin(2 * math.pi * 150 * t_sample)    # 3rd harmonic
            + 0.1 * math.sin(2 * math.pi * 250 * t_sample)    # 5th harmonic
            + noise.gauss(0, 0.02)                              # noise
        )
        readings.append(round(value, 6))

    payload = {
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + "Z",
        "timestamp_unix": _ts(t),
        "sensor_id": "VIBRATION-001",
        "sensor_type": "accelerometer",
        "location": "machine_spindle",
        "sample_rate_hz": sample_rate,
        "sample_count": sample_count,
        "unit": "m/s2",
        "dominant_freq_hz": 50,
        "rms": round(math.sqrt(sum(x**2 for x in readings) / sample_count), 4),
        "readings": readings,
    }
    return jsonify(payload)


# ─────────────────────────────────────────────────────────────────────────────
# TC-3: Video frame (simulated)
# Simulates a 640x480 camera frame. The EDC transport overhead per frame
# makes true 24fps through EDC impractical — this endpoint is used to
# measure what throughput is actually achievable.
# Payload: ~15-20 KB (compressed JPEG simulation via structured bytes).
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/tc3/video-frame", methods=["GET"])
def tc3_video_frame():
    t = time.time()

    width, height = 640, 480
    # Simulate a gradient image; the same frame every time
    pixels = bytearray()
    phase = 5
    for row in range(height):
        for col in range(width):
            r = (row + phase) % 256
            g = (col + phase) % 256
            b = (row + col + phase) % 256
            pixels.extend([r, g, b])

    # Compress via zlib to simulate JPEG-like compression
    import zlib
    compressed = zlib.compress(bytes(pixels), level=6)
    encoded = base64.b64encode(compressed).decode("ascii")

    return jsonify({
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + "Z",
        "timestamp_unix": _ts(t),
        "frame_id": 1,
        "camera_id": "CAM-001",
        "location": "production_cell_A",
        "width": width,
        "height": height,
        "channels": 3,
        "format": "RGB_ZLIB",
        "fps_target": 24,
        "compressed_size_bytes": len(compressed),
        "data": encoded,
    })


# ─────────────────────────────────────────────────────────────────────────────
# TC-4: Triggered event alert
# Reuses TC-2's SensorData fields (rms, dominant_freq_hz) as a threshold-crossing
# flag rather than a continuous stream. No new AAS submodel required.
#
# POST /tc4/trigger      — deterministically forces a threshold crossing, so
#                           measurement runs are repeatable rather than waiting
#                           on an organic random crossing.
# GET  /tc4/alert-event  — returns the pending alert once and consumes it
#                           (single-shot, matching "triggered once" semantics).
#                           Returns a no-alert placeholder if nothing is pending.
# ─────────────────────────────────────────────────────────────────────────────
_tc4_rms_threshold = 2.5
_tc4_pending_alert = None

# When set (provider-source unit), each alert is also handed to the crane
# adapter the moment it fires, which writes it into the AAS SensorData
# submodel (LastAlert) — the path the EDC Data Plane reads TC-4 from.
_ADAPTER_URL = os.getenv("ADAPTER_URL", "")


def _notify_adapter(alert: dict) -> str:
    if not _ADAPTER_URL:
        return "not configured"
    req = urllib.request.Request(
        f"{_ADAPTER_URL}/tc4/alert", data=json.dumps(alert).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return "written" if r.status == 200 else f"HTTP {r.status}"
    except Exception as e:
        return f"failed: {e}"


@app.route("/tc4/trigger", methods=["POST"])
def tc4_trigger():
    global _tc4_pending_alert
    t = time.time()
    triggered_rms = round(_tc4_rms_threshold + 0.6125, 4)
    alert_id = f"alert-{int(t * 1000)}"
    _tc4_pending_alert = {
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + "Z",
        "timestamp_unix": _ts(t),
        "sensor_id": "VIBRATION-001",
        "sensor_type": "accelerometer",
        "location": "machine_spindle",
        "event_type": "threshold_alert",
        "triggered_field": "rms",
        "rms": triggered_rms,
        "rms_threshold": _tc4_rms_threshold,
        "dominant_freq_hz": 50,
        "alert_id": alert_id,
    }
    aas = _notify_adapter(_tc4_pending_alert)
    return jsonify({"status": "triggered", "alert_id": alert_id, "rms": triggered_rms, "aas": aas})


@app.route("/tc4/alert-event", methods=["GET"])
def tc4_alert_event():
    global _tc4_pending_alert
    if _tc4_pending_alert is None:
        return jsonify({
            "event_type": "none",
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
            "message": "no active alert — call POST /tc4/trigger first",
        })
    alert = _tc4_pending_alert
    _tc4_pending_alert = None  # single-shot: consumed on read
    return jsonify(alert)


# ─────────────────────────────────────────────────────────────────────────────
# Payload-size sweep
# GET /sweep/<bytes> — a JSON document of exactly <bytes> bytes: a fixed-width
# timestamp and filler. Separates what the payload size costs from what EDC's
# own processing costs, independent of any test case's data.
# ─────────────────────────────────────────────────────────────────────────────
_sweep_filler: dict[int, str] = {}


@app.route("/sweep/<int:size>", methods=["GET"])
def sweep(size: int):
    t = time.time()
    head = '{"timestamp_unix": "%s", "size_bytes": %d, "data": "' % (_ts(t), size)
    tail = '"}'
    n = size - len(head) - len(tail)
    if n < 0 or size > 200 * 1024 * 1024:
        return jsonify({"error": f"size must be between {len(head) + len(tail)} and 200 MiB"}), 400
    if n not in _sweep_filler:
        _sweep_filler[n] = "x" * n
    return Response(head + _sweep_filler[n] + tail, mimetype="application/json")


# ─────────────────────────────────────────────────────────────────────────────
# Health and status
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "uptime_seconds": round(time.time() - _start_time, 1)})


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "EDC Test Plan — Data Simulator",
        "endpoints": {
            "TC-1 Real-time control":   "/tc1/control-signal",
            "TC-2 High-freq sensors":   "/tc2/sensor-batch",
            "TC-3 Video frame":         "/tc3/video-frame",
            "TC-4 Trigger alert":       "POST /tc4/trigger",
            "TC-4 Alert event":         "/tc4/alert-event",
            "Health":                   "/health",
        }
    })


if __name__ == "__main__":
    # Local development only; the container serves the app with waitress (see
    # Dockerfile), which keeps HTTP/1.1 connections open between requests as a
    # production data source does. Werkzeug's development server closes every
    # connection, adding a TCP handshake to each fetch.
    app.run(host="0.0.0.0", port=5000, debug=False)
