#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# lib-endpoints.sh — where each connector unit is reachable, as seen from the
# machine running the test scripts. Sourced by every test script.
#
# Distributed deployment: deploy/deploy.sh writes deploy/.endpoints.env with
# the resolved host of each unit (provider-source, provider-cp, provider-dp,
# consumer-cp, consumer-dp) for the chosen architecture; it is loaded here.
#
# Single-machine compose (docker/docker-compose.yaml): no .endpoints.env, so
# the defaults below apply — the same addresses the scripts always used.
#
# Two kinds of address appear below:
#   *_MGMT, RECEIVER_BASE, SIMULATOR_HOST, CONSUMER_PROXY — called by this
#   script (or the pull client) from the shell
#   PROVIDER_DSP, RECEIVER_PUSH_BASE, SIMULATOR_ASSET_BASE — handed to a
#   connector, which calls it
# ─────────────────────────────────────────────────────────────────────────────

_ENDPOINTS_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/.endpoints.env"
if [[ -f "$_ENDPOINTS_FILE" && "${IGNORE_ENDPOINTS_FILE:-0}" != "1" ]]; then
  # shellcheck disable=SC1090
  source "$_ENDPOINTS_FILE"
fi

if [[ -n "${PROVIDER_CP_HOST:-}" ]]; then
  PROVIDER_MGMT="http://${PROVIDER_CP_HOST}:8182/management/v3"
  PROVIDER_DSP="http://${PROVIDER_CP_HOST}:8183/protocol"
  CONSUMER_MGMT="http://${CONSUMER_CP_HOST}:9192/management/v3"
  RECEIVER_BASE="http://${CONSUMER_DP_HOST}:4000"
  RECEIVER_PUSH_BASE="$RECEIVER_BASE"
  CONSUMER_PROXY="http://${CONSUMER_DP_HOST}:9296/proxy"
  SIMULATOR_HOST="http://${SOURCE_HOST}:5050"
  # The data source is its own unit on its own machine; provider-dp reaches it
  # there wherever provider-dp runs (so in "cloud" the data crosses the WAN).
  SIMULATOR_ASSET_BASE="$SIMULATOR_HOST"
else
  PROVIDER_MGMT="http://localhost:8182/management/v3"
  PROVIDER_DSP="http://provider-cp:8183/protocol"
  CONSUMER_MGMT="http://localhost:9192/management/v3"
  RECEIVER_BASE="http://localhost:4000"
  RECEIVER_PUSH_BASE="http://receiver:4000"
  CONSUMER_PROXY="http://localhost:9296/proxy"
  # Host-mapped port 5050 (not 5000 — macOS AirPlay Receiver conflict)
  SIMULATOR_HOST="http://localhost:5050"
  # Single-machine stack: provider-dp shares a Docker network with the simulator
  SIMULATOR_ASSET_BASE="http://simulator:5000"
fi

# TC-4 source: "aas" = the provider's Data Plane reads the alert from the AAS
# (SensorData submodel, LastAlert collection) on the data-source machine;
# "simulator" = straight from the simulator. Distributed default: aas (the
# provider-source unit always runs BaSyx). Single-machine default: simulator
# (BaSyx there is an optional compose profile).
if [[ -n "${SOURCE_HOST:-}" ]]; then
  TC4_SOURCE="${TC4_SOURCE:-aas}"
  AAS_ASSET_BASE="http://${SOURCE_HOST}:8091"
else
  TC4_SOURCE="${TC4_SOURCE:-simulator}"
  AAS_ASSET_BASE="http://basyx-aas:8081"
fi
# URL-safe base64 of the submodel id urn:ilmatar:crane:sm:SensorData
SENSORDATA_SM_B64="dXJuOmlsbWF0YXI6Y3JhbmU6c206U2Vuc29yRGF0YQ"
if [[ "$TC4_SOURCE" == "aas" ]]; then
  TC4_ASSET_URL="$AAS_ASSET_BASE/submodels/$SENSORDATA_SM_B64/submodel-elements/LastAlert/\$value"
else
  TC4_ASSET_URL="$SIMULATOR_ASSET_BASE/tc4/alert-event"
fi

# Every HTTP call the test scripts make goes to another machine. Bound them, so
# a lost connection fails the step instead of hanging the whole run.
curl() { command curl --connect-timeout 10 --max-time 60 "$@"; }

export PROVIDER_MGMT PROVIDER_DSP CONSUMER_MGMT CONSUMER_PROXY RECEIVER_BASE RECEIVER_PUSH_BASE \
       SIMULATOR_HOST SIMULATOR_ASSET_BASE TC4_SOURCE TC4_ASSET_URL
