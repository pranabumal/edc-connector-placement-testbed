#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 3-tc2-high-freq-sensors.sh
# Test Case 2: High-frequency sensor batch transfer
# Each transfer delivers 1 second of 1 kHz vibration data (~50 KB).
# Measures batch throughput and latency through the dataspace.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

source "$(dirname "$0")/lib-endpoints.sh"
source "$(dirname "$0")/lib-edc.sh"
RECEIVER_URL="$RECEIVER_PUSH_BASE/receive/tc2"
ASSET_ID="asset-tc2-sensors"
REPEAT="${TC2_REPEAT:-5}"
# PUSH_INTERVAL_S (whole seconds; review re-run B, 27 Oct 2026): transfer i is
# due at t0 + (i-1)·interval instead of right after the previous one, the push
# counterpart of the fixed pull schedule. A slot reached a full interval late
# is skipped, as in pull. Due times and skips go to the run log (push_due,
# push_skip); a slot meets its deadline if its data arrive within one interval
# of its due time.
INTERVAL="${PUSH_INTERVAL_S:-}"

echo "======================================================================"
echo " TC-2: High-Frequency Sensor Batch"
echo " Payload: ~50 KB per batch (1000 samples at 1 kHz)"
echo " Transfers: $REPEAT"
echo "======================================================================"
echo ""

# ── Steps 1–3: catalogue and contract negotiation, retried (lib-edc.sh) ──────
negotiate_contract tc2 "$ASSET_ID"

# ── Transfers ─────────────────────────────────────────────────────────────────
echo "[4/4] Running $REPEAT transfers..."
echo ""
echo "  Transfer# | ms elapsed | Status"
echo "  ----------+------------+----------"

T0_NS=$(date +%s%N)
for i in $(seq 1 "$REPEAT"); do
  if [[ -n "$INTERVAL" ]]; then
    due_ns=$(( T0_NS + (i - 1) * INTERVAL * 1000000000 ))
    now_ns=$(date +%s%N)
    if (( now_ns > due_ns + INTERVAL * 1000000000 )); then
      [[ -n "${RUN_LOG:-}" ]] && printf 'push_skip\ttc2\t%s\t%s\n' "$i" "$due_ns" >> "$RUN_LOG"
      continue
    fi
    if (( now_ns < due_ns )); then sleep "$(awk -v d=$(( due_ns - now_ns )) 'BEGIN{printf "%.3f", d/1e9}')"; fi
    [[ -n "${RUN_LOG:-}" ]] && printf 'push_due\ttc2\t%s\t%s\n' "$i" "$due_ns" >> "$RUN_LOG"
  fi
  # Matches this transfer to its arrival at the receiver (X-Run-Id header) and
  # to its creation time on consumer-cp — see scripts/run-all-tests.sh
  RUN_ID="tc2-$i-$(date +%s%N)"
  edc_transfer tc2
  printf "  %-9s | %-10s | %s\n" "$i" "${ELAPSED_MS} ms" "$T_STATE"
done

echo ""
echo "======================================================================"
echo " TC-2 done. Receiver metrics:"
echo "======================================================================"
curl -sf "$RECEIVER_BASE/metrics/tc2" | jq --argjson neg_ms "$NEG_MS" '{
  summary: .summary,
  negotiation_ms: $neg_ms,
  note: "avg_size_bytes shows actual payload received through EDC"
}'
