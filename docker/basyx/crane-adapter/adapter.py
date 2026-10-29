"""
Basyx Crane Adapter
Polls the EDC data simulator and pushes live values into the BaSyx AAS environment.
This bridges the simulator (stand-in for OPC UA) into the AAS submodel elements
so the EDC Provider can fetch from BaSyx instead of the raw simulator.

Runs a background thread for continuous updates + exposes /health.

TC-4: POST /tc4/alert is called by the simulator the moment an alert fires
(event-driven, not polled). The alert is written into the SensorData
submodel's LastAlert collection, stamped with aas_written_unix, which is where
the provider's EDC Data Plane reads it from.
"""

import threading
import time
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

SIMULATOR   = "http://simulator:5000"
BASYX_AAS   = "http://basyx-aas:8081"   # internal Docker port, not the host-mapped 8091

# BaSyx AAS REST API v3 (AAS Part 2):
#   PATCH /submodels/{smIdB64}/submodel-elements/{idShortPath}/$value
# (the camelCase ".../submodelElements/..." path returns 404 on this BaSyx
# version — which is why every write must check the response status)
import base64

def _sm_id_b64(sm_id: str) -> str:
    return base64.urlsafe_b64encode(sm_id.encode()).decode().rstrip("=")

SM_CONTROL  = _sm_id_b64("urn:ilmatar:crane:sm:ControlSignal")
SM_SENSOR   = _sm_id_b64("urn:ilmatar:crane:sm:SensorData")
SM_VIDEO    = _sm_id_b64("urn:ilmatar:crane:sm:VideoStream")

_status = {"running": False, "last_update": None, "errors": 0, "updates": 0}


def _patch(sm_b64: str, id_short_path: str, value) -> None:
    url = f"{BASYX_AAS}/submodels/{sm_b64}/submodel-elements/{id_short_path}/$value"
    requests.patch(url, json=value, timeout=3).raise_for_status()


def _sync_tc1() -> None:
    data = requests.get(f"{SIMULATOR}/tc1/control-signal", timeout=5).json()
    for field in ["setpoint", "actual", "error", "velocity", "timestamp_iso", "actuator_id"]:
        if field in data:
            _patch(SM_CONTROL, field, str(data[field]))


def _sync_tc2() -> None:
    data = requests.get(f"{SIMULATOR}/tc2/sensor-batch", timeout=10).json()
    for field in ["rms", "dominant_freq_hz", "sample_count", "timestamp_iso", "sensor_id"]:
        if field in data:
            _patch(SM_SENSOR, field, str(data[field]))


def _sync_tc3() -> None:
    data = requests.get(f"{SIMULATOR}/tc3/video-frame", timeout=10).json()
    for field in ["frame_id", "timestamp_iso", "camera_id"]:
        if field in data:
            _patch(SM_VIDEO, field, str(data[field]))


def _poll_loop() -> None:
    _status["running"] = True
    # Wait for BaSyx to be ready
    for _ in range(30):
        try:
            r = requests.get(f"{BASYX_AAS}/actuator/health", timeout=3)  # BaSyx Spring Boot actuator
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(3)

    while True:
        try:
            _sync_tc1()
            _sync_tc2()
            _sync_tc3()
            _status["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _status["updates"] += 1
        except Exception as e:
            _status["errors"] += 1
            print(f"[adapter] sync error: {e}", flush=True)
        time.sleep(0.5)   # update every 500 ms


_tc4_status = {"alerts_written": 0, "last_alert_id": None, "errors": 0}


@app.route("/tc4/alert", methods=["POST"])
def tc4_alert():
    """Write a just-fired alert into SensorData/LastAlert and stamp the time
    it landed in the AAS, so TC-4 can report source→AAS and AAS→consumer
    separately."""
    alert = request.get_json(force=True)
    value = {
        "alert_id":         str(alert.get("alert_id", "")),
        "event_type":       str(alert.get("event_type", "")),
        "triggered_field":  str(alert.get("triggered_field", "")),
        "rms":              str(alert.get("rms", 0.0)),
        "rms_threshold":    str(alert.get("rms_threshold", 0.0)),
        "timestamp_iso":    str(alert.get("timestamp_iso", "")),
        "timestamp_unix":   str(alert.get("timestamp_unix", 0.0)),
        "aas_written_unix": f"{time.time():.6f}",
    }
    try:
        _patch(SM_SENSOR, "LastAlert", value)
    except Exception as e:
        _tc4_status["errors"] += 1
        print(f"[adapter] TC-4 alert write failed: {e}", flush=True)
        return jsonify({"status": "error", "error": str(e)}), 502
    _tc4_status["alerts_written"] += 1
    _tc4_status["last_alert_id"] = value["alert_id"]
    return jsonify({"status": "written", **value})


@app.route("/health")
def health():
    return jsonify({"status": "ok", **_status, "tc4": _tc4_status})


if __name__ == "__main__":
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=8099)
