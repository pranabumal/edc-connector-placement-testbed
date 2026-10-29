#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 6-payload-sweep.sh <bytes>
# Payload-size sweep: negotiates a contract for the sweep asset of that size
# (asset-sweep-<bytes>, see 1-setup-provider.sh) and runs N transfers of it.
# Shows how transfer time grows with the amount of data, separately from
# EDC's fixed per-transfer processing; run by run-all-tests.sh as test case
# "s<bytes>" (e.g. TCS="s10240 s1048576").
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

TRANSFER_WAIT_S="${TRANSFER_WAIT_S:-120}"   # large payloads take longer
source "$(dirname "$0")/lib-endpoints.sh"
source "$(dirname "$0")/lib-edc.sh"
BYTES="${1:?usage: 6-payload-sweep.sh <bytes>}"
TC="s$BYTES"
RECEIVER_URL="$RECEIVER_PUSH_BASE/receive/$TC"
ASSET_ID="asset-sweep-$BYTES"
REPEAT="${SWEEP_REPEAT:-10}"

echo "======================================================================"
echo " Payload sweep: $BYTES bytes"
echo " Transfers: $REPEAT"
echo "======================================================================"
echo ""

# ── Steps 1–3: catalogue and contract negotiation, retried (lib-edc.sh) ──────
negotiate_contract "$TC" "$ASSET_ID"

# ── Step 4: Run N transfers ───────────────────────────────────────────────────
echo "[4/4] Running $REPEAT transfers..."
for i in $(seq 1 "$REPEAT"); do
  RUN_ID="$TC-$i-$(date +%s%N)"
  edc_transfer "$TC"
  printf "  %-4s | %-37s | %s (%d ms)\n" "$i" "$TRANSFER_ID" "$T_STATE" "$ELAPSED_MS"
  sleep 0.5
done
