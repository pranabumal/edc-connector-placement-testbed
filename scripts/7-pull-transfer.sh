#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 7-pull-transfer.sh <test-case>
# PULL transfer of a test case's asset: the consumer negotiates a contract,
# starts one transfer of type HttpData-PULL, receives the provider Data Plane's
# address and an access token (the EDR), and then fetches the data N times
# from that Data Plane with the token.
#
# <test-case> is pull-tc1 … pull-tc4, pull-s<bytes> (payload sweep) or
# pull-timed; run by run-all-tests.sh, e.g. TCS="pull-tc1 pull-s1048576".
#
# pull-timed is the policy-enforcement test: TC-1's data under a contract valid
# for POLICY_VALID_S seconds after agreement (1-setup-provider.sh). The client
# keeps fetching past that point, to see how soon access is actually cut off.
#
# Enforcement (measurement set D), all on TC-1's data:
#   pull-timed-linkcut  as pull-timed; run-all-tests.sh cuts the link between
#                the provider's Control Plane and Data Plane meanwhile (LINK_CUT)
#   pull-terminate  fetches every 0.1 s for ENF_DURATION s (default 40); after
#                TERMINATE_AFTER_S (default 10) the provider terminates the
#                transfer through its Management API
#   pull-tokens  10 fetches with no token and 10 with a wrong one, then 20
#                with the real token
# TIMED_AFTER_S (default 30): how long pull-timed keeps fetching after expiry;
# TIMED_INTERVAL_S (default 0.25) the pause between its fetches.
#
# PULL_VIA chooses who fetches from the provider's Data Plane:
#   direct       (default, stock EDC) the client itself, with the token. Data
#                path: source → provider DP → client.
#   consumer-dp  the consumer's Data Plane, through its pull proxy (an extension
#                of this testbed, off unless configured in
#                consumer-dp-config.properties). Data path: source → provider
#                DP → consumer DP → client; the client never holds the token.
#
#   source       baseline without EDC: no negotiation, no transfer; the client
#                fetches straight from the data source, same schedule.
#
# PULL_RATE=<Hz>|target puts the fetches on a fixed schedule for PULL_DURATION
# seconds (default 300) instead of PULL_REPEAT fetches with a pause; "target"
# is the test case's rate in the protocol (TC-1 50 Hz, TC-2 1/s, TC-3 24 Hz).
# PULL_PARALLEL workers (default 1) share the schedule; PULL_DEADLINE_MS is the
# per-fetch deadline (default one period). See pull-client.py.
#
# The timed part (scripts/pull-client.py) runs on the consumer's machine, so
# setup time and fetch times are taken on one clock. For TC-4 the alert is
# fired just before each fetch, so its source→received time is alert → consumer.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

source "$(dirname "$0")/lib-endpoints.sh"
source "$(dirname "$0")/lib-edc.sh"
source "$(dirname "$0")/lib-remote.sh"
TC="${1:?usage: 7-pull-transfer.sh pull-tc1|…|pull-s<bytes>}"
REPEAT="${PULL_REPEAT:-20}"
TRIGGER=""
MODE="--count $REPEAT"
POLICY_VALID_S="${POLICY_VALID_S:-30}"
PULL_VIA="${PULL_VIA:-direct}"
case "$PULL_VIA" in
  consumer-dp) VIA="--proxy $CONSUMER_PROXY" ;;
  direct|source) VIA="" ;;
  *) echo "PULL_VIA must be direct, consumer-dp or source, not '$PULL_VIA'" >&2; exit 1 ;;
esac
case "${TC#pull-}" in
  timed|timed-linkcut) ASSET_ID="asset-tc1-timed"
         MODE="--duration $((POLICY_VALID_S + ${TIMED_AFTER_S:-30})) --interval ${TIMED_INTERVAL_S:-0.25} --policy-valid-s $POLICY_VALID_S" ;;
  terminate) ASSET_ID="asset-tc1-control"
         MODE="--duration ${ENF_DURATION:-40} --interval 0.1 --terminate-after ${TERMINATE_AFTER_S:-10} --provider-mgmt $PROVIDER_MGMT" ;;
  tokens) ASSET_ID="asset-tc1-control"; MODE="--count 20 --token-tests 10" ;;
  tc1) ASSET_ID="asset-tc1-control"; TARGET_HZ=50; SOURCE_PATH=/tc1/control-signal ;;
  tc2) ASSET_ID="asset-tc2-sensors"; TARGET_HZ=1;  SOURCE_PATH=/tc2/sensor-batch ;;
  tc3) ASSET_ID="asset-tc3-video";   TARGET_HZ=24; SOURCE_PATH=/tc3/video-frame ;;
  tc4) ASSET_ID="asset-tc4-alert"; TRIGGER="--trigger-url $SIMULATOR_HOST/tc4/trigger" ;;
  s[0-9]*) ASSET_ID="asset-sweep-${TC#pull-s}" ;;
  *) echo "unknown pull test case '$TC'" >&2; exit 1 ;;
esac
OUT="${RUN_LOG:+$(dirname "$RUN_LOG")/}pull-$TC.json"

if [[ -n "${PULL_RATE:-}" ]]; then
  [[ "$PULL_RATE" == target ]] && PULL_RATE="${TARGET_HZ:?no target rate for $TC}"
  MODE="--rate $PULL_RATE --duration ${PULL_DURATION:-300} --parallel ${PULL_PARALLEL:-1}"
  [[ -n "${PULL_DEADLINE_MS:-}" ]] && MODE="$MODE --deadline-ms $PULL_DEADLINE_MS"
  if [[ "${PULL_NEW_CONN:-0}" == 1 ]]; then MODE="$MODE --new-connection"; fi
  # a 5-minute schedule must not hit on_role's default 900 s limit
  export ON_ROLE_TIMEOUT=$(( ${PULL_DURATION:-300} + 600 ))
fi
DESCRIBE="${PULL_RATE:+$PULL_RATE Hz for ${PULL_DURATION:-300} s, ${PULL_PARALLEL:-1} worker(s)}"
DESCRIBE="${DESCRIBE:-$REPEAT fetches}"

echo "======================================================================"
echo " PULL transfer: $TC ($ASSET_ID)"
echo " Fetches: $DESCRIBE, via $PULL_VIA"
echo "======================================================================"
echo ""

if [[ "$PULL_VIA" == source ]]; then
  # ── Baseline: the same fetches straight from the data source, no EDC ───────
  echo "[1/1] Fetching from the data source directly ($DESCRIBE, on the consumer's machine)..."
  on_role consumer "python3 scripts/pull-client.py --source-url '$SIMULATOR_HOST${SOURCE_PATH:?no data-source path for $TC}' $MODE" > "$OUT"
else
  # ── Steps 1–3: catalogue and contract negotiation, retried (lib-edc.sh) ────
  negotiate_contract "$TC" "$ASSET_ID"

  # ── Step 4: one PULL transfer, then the fetches (PULL_VIA) ─────────────────
  echo "[4/4] Starting the transfer and fetching ($DESCRIBE, on the consumer's machine)..."
  on_role consumer "python3 scripts/pull-client.py --mgmt '$CONSUMER_MGMT' --provider-dsp '$PROVIDER_DSP' \
    --agreement '$AGREEMENT_ID' $MODE $TRIGGER $VIA" > "$OUT"
fi

jq -r '
  if .error then "  ✗ " + .error
  else (if .transfer_id then "  transfer " + .transfer_id + "\n  endpoint " + .endpoint
          + "\n  setup    " + (.setup_ms | tostring) + " ms (request → address and token)\n" else "" end)
     + "  fetched  " + .fetch_url
     + (if .schedule then "\n  schedule " + (.schedule | "\(.rate_hz) Hz × \(.duration_s) s: \(.ok) of \(.slots) slots OK, \(.skipped_slots) skipped, \(.missed_pct) % missed the \(.deadline_ms) ms deadline, achieved \(.achieved_hz) Hz") else "" end)
     + "\n  fetches  " + ([.fetches[] | select(.status == 200)] | length | tostring) + " of " + (.fetches | length | tostring) + " OK"
     + "\n  statuses " + ([.fetches[] | (.status // "error") | tostring] | group_by(.) | map(.[0] + " ×" + (length | tostring)) | join(", "))
     + "\n  fetch ms " + ([.fetches[] | .elapsed_ms // empty] | .[:25] | map(tostring) | join(" "))
  end' "$OUT"
[[ -n "${RUN_LOG:-}" ]] && printf 'pull\t%s\t%s\n' "$TC" "$(jq -r '.transfer_id // ""' "$OUT")" >> "$RUN_LOG"
jq -e '.error | not' "$OUT" > /dev/null
