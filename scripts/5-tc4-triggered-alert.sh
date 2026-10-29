#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 5-tc4-triggered-alert.sh
# Test Case 4: Triggered event alert
# Negotiates a contract for asset-tc4-alert once, then for each of N runs:
# deterministically fires a threshold-crossing alert on the simulator
# (POST /tc4/trigger) and initiates a single EDC transfer to fetch and push it.
#
# TC4_SOURCE=aas (distributed default): the simulator hands the alert to the
# crane adapter, which writes it into the AAS (SensorData/LastAlert) before the
# trigger call returns; the Data Plane then reads it from the AAS. The receiver
# reports source→AAS and AAS→receiver in addition to the end-to-end latency.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

source "$(dirname "$0")/lib-endpoints.sh"
source "$(dirname "$0")/lib-edc.sh"
RECEIVER_URL="$RECEIVER_PUSH_BASE/receive/tc4"
ASSET_ID="asset-tc4-alert"
REPEAT="${TC4_REPEAT:-5}"   # number of triggered transfers to run

echo "======================================================================"
echo " TC-4: Triggered Event Alert"
echo " Target: seconds-scale latency tolerance (single-shot, triggered)"
echo " Transfers: $REPEAT"
echo " Alert read from: $TC4_SOURCE ($TC4_ASSET_URL)"
echo "======================================================================"
echo ""

# ── Steps 1–3: catalogue and contract negotiation, retried (lib-edc.sh) ──────
negotiate_contract tc4 "$ASSET_ID"

# ── Step 4: Run N triggered transfers and collect timing ──────────────────────
echo "[4/4] Running $REPEAT triggered transfers..."
echo ""
echo "  Run# | Alert-ID              | Transfer-ID                          | Status"
echo "  -----+-----------------------+---------------------------------------+--------"

for i in $(seq 1 "$REPEAT"); do
  # Matches this transfer to its arrival at the receiver (X-Run-Id header) and
  # to its creation time on consumer-cp — see scripts/run-all-tests.sh
  RUN_ID="tc4-$i-$(date +%s%N)"
  # Fire a deterministic threshold crossing on the simulator before transferring,
  # so each run has a fresh alert waiting at /tc4/alert-event.
  TRIGGER_RESP=$(curl -sf -X POST "$SIMULATOR_HOST/tc4/trigger")
  ALERT_ID=$(echo "$TRIGGER_RESP" | jq -r '.alert_id')
  if [[ "$TC4_SOURCE" == "aas" ]] && [[ "$(echo "$TRIGGER_RESP" | jq -r '.aas')" != "written" ]]; then
    echo "  ✗ alert $ALERT_ID did not reach the AAS: $(echo "$TRIGGER_RESP" | jq -r '.aas')" >&2
    exit 1
  fi

  edc_transfer tc4
  printf "  %-4s | %-21s | %-37s | %s (%d ms)\n" "$i" "$ALERT_ID" "$TRANSFER_ID" "$T_STATE" "$ELAPSED_MS"

  # Small gap between runs so alerts don't overlap with a still-pending fetch
  sleep 1
done

echo ""
echo "======================================================================"
echo " TC-4 done. Checking receiver metrics..."
echo "======================================================================"
curl -sf "$RECEIVER_BASE/metrics/tc4" | jq --argjson neg_ms "$NEG_MS" '{
  summary: .summary,
  negotiation_ms: $neg_ms,
  note: (if .summary.source_to_aas_ms_avg then "latency_ms = alert fired → received; split into source_to_aas_ms (on the source machine, one clock) + aas_to_receiver_ms (includes transfer start-up, crosses machines)" else "latency_ms is end-to-end from simulator trigger timestamp to receiver arrival" end)
}'
echo ""
echo " Success criterion: seconds-scale latency tolerance (exception/status alert, not a live control signal)."
