#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 4-tc3-video-stream.sh
# Test Case 3: Video stream (frame-by-frame transfer)
# Each transfer delivers one simulated 640x480 camera frame (~15 KB).
# Measures achievable frame rate through the EDC dataspace.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

source "$(dirname "$0")/lib-endpoints.sh"
source "$(dirname "$0")/lib-edc.sh"
RECEIVER_URL="$RECEIVER_PUSH_BASE/receive/tc3"
ASSET_ID="asset-tc3-video"
REPEAT="${TC3_REPEAT:-5}"

echo "======================================================================"
echo " TC-3: Video Stream (frame-by-frame)"
echo " Payload: ~15 KB per frame (640x480 simulated compressed)"
echo " Target:  24 fps (41 ms per frame)"
echo " Frames:  $REPEAT"
echo "======================================================================"
echo ""

# ── Steps 1–3: catalogue and contract negotiation, retried (lib-edc.sh) ──────
negotiate_contract tc3 "$ASSET_ID"

# ── Frame transfers ───────────────────────────────────────────────────────────
echo "[4/4] Transferring $REPEAT frames..."
echo ""
echo "  Frame# | ms elapsed | Status"
echo "  -------+------------+----------"

TOTAL_START=$(date +%s%N)
for i in $(seq 1 "$REPEAT"); do
  # Matches this transfer to its arrival at the receiver (X-Run-Id header) and
  # to its creation time on consumer-cp — see scripts/run-all-tests.sh
  RUN_ID="tc3-$i-$(date +%s%N)"
  edc_transfer tc3
  printf "  %-6s | %-10s | %s\n" "$i" "${ELAPSED_MS} ms" "$T_STATE"
done
TOTAL_END=$(date +%s%N)

TOTAL_MS=$(( (TOTAL_END - TOTAL_START) / 1000000 ))
ACHIEVED_FPS=$(echo "scale=2; $REPEAT * 1000 / $TOTAL_MS" | bc 2>/dev/null || echo "N/A")

echo ""
echo "======================================================================"
echo " TC-3 done."
printf " Total time:     %d ms for %d frames\n" "$TOTAL_MS" "$REPEAT"
printf " Achieved rate:  %s fps (target: 24 fps)\n" "$ACHIEVED_FPS"
echo "======================================================================"
echo ""
echo " Receiver metrics:"
curl -sf "$RECEIVER_BASE/metrics/tc3" | jq --argjson neg_ms "$NEG_MS" '{
  summary: .summary,
  negotiation_ms: $neg_ms,
  note: "avg_size_bytes verifies payload integrity through EDC"
}'
