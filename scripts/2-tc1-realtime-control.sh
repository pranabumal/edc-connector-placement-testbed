#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 2-tc1-realtime-control.sh
# Test Case 1: Real-time control signal transfer
# Negotiates a contract for asset-tc1-control and initiates N sequential
# transfers, measuring EDC end-to-end latency vs the 50 Hz target.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

source "$(dirname "$0")/lib-endpoints.sh"
source "$(dirname "$0")/lib-edc.sh"
RECEIVER_URL="$RECEIVER_PUSH_BASE/receive/tc1"
ASSET_ID="asset-tc1-control"
REPEAT="${TC1_REPEAT:-5}"   # number of transfers to run

echo "======================================================================"
echo " TC-1: Real-time Control Signal"
echo " Target: ~50 Hz (20 ms per cycle)"
echo " Transfers: $REPEAT"
echo "======================================================================"
echo ""

# ── Steps 1–3: catalogue and contract negotiation, retried (lib-edc.sh) ──────
negotiate_contract tc1 "$ASSET_ID"

# ── Baseline: direct, ungoverned fetch (isolates EDC's governance overhead) ───
echo "[baseline] Direct fetch of simulator:5000/tc1/control-signal (no EDC)..."
BASELINE_START=$(date +%s%N)
curl -sf "$SIMULATOR_HOST/tc1/control-signal" > /dev/null
BASELINE_END=$(date +%s%N)
BASELINE_MS=$(( (BASELINE_END - BASELINE_START) / 1000000 ))
echo "  Baseline (ungoverned) fetch time: ${BASELINE_MS} ms"
echo ""

# ── Step 4: Run N transfers and collect timing ────────────────────────────────
echo "[4/4] Running $REPEAT transfers..."
echo ""
echo "  Transfer# | Transfer-ID                         | Status"
echo "  ----------+-----------------------------------------+--------"

for i in $(seq 1 "$REPEAT"); do
  # Matches this transfer to its arrival at the receiver (X-Run-Id header) and
  # to its creation time on consumer-cp — see scripts/run-all-tests.sh
  RUN_ID="tc1-$i-$(date +%s%N)"
  edc_transfer tc1
  printf "  %-9s | %-39s | %s (%d ms)\n" "$i" "$TRANSFER_ID" "$T_STATE" "$ELAPSED_MS"
done

echo ""
echo "======================================================================"
echo " TC-1 done. Checking receiver metrics..."
echo "======================================================================"
curl -sf "$RECEIVER_BASE/metrics/tc1" | jq \
  --argjson neg_ms "$NEG_MS" --argjson baseline_ms "$BASELINE_MS" '{
  summary: .summary,
  negotiation_ms: $neg_ms,
  baseline_ungoverned_fetch_ms: $baseline_ms,
  note: "latency_ms is end-to-end from data_source timestamp to receiver arrival"
}'
echo ""
echo " Target: 20 ms (50 Hz). EDC overhead is typically >> 20 ms."
echo " This quantifies the latency gap for the research findings."
