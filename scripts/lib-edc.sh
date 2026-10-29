#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# lib-edc.sh — contract negotiation and transfers for the test-case scripts,
# with retries. Sourced after lib-endpoints.sh; defines functions only.
#
# EDC ends a negotiation or transfer for good when the partner rejects one of
# its messages — e.g. with 409 when the message arrives while the partner holds
# the lease on that record ("Entity is currently leased!"). It does not resend.
# A real consumer would simply start over, so these helpers do the same, up to
# NEG_MAX_ATTEMPTS / TRANSFER_MAX_ATTEMPTS times, and log every failed attempt
# to RUN_LOG (neg_retry / transfer_retry) so retries are counted, not hidden.
# ─────────────────────────────────────────────────────────────────────────────

NEG_MAX_ATTEMPTS="${NEG_MAX_ATTEMPTS:-3}"
TRANSFER_MAX_ATTEMPTS="${TRANSFER_MAX_ATTEMPTS:-3}"
TRANSFER_WAIT_S="${TRANSFER_WAIT_S:-10}"   # how long to wait for COMPLETED

_edc_log() { [[ -n "${RUN_LOG:-}" ]] && printf '%s\n' "$1" >> "$RUN_LOG"; return 0; }

# negotiate_contract <tc> <asset-id>
# Fetches the provider's catalogue and negotiates a contract for the asset.
# Sets AGREEMENT_ID, and NEG_MS: catalogue request to agreement, all attempts
# included. Exits the script if no attempt succeeds.
negotiate_contract() {
  local tc="$1" asset="$2" offer policy neg_id status state="" reason attempt
  local start; start=$(date +%s%N)
  echo "[1/4] Fetching catalog from provider..."
  # The offer's policy exactly as the provider's catalogue states it (the
  # provider rejects a request whose policy differs), plus who offers what.
  policy=$(curl -sf -X POST "$CONSUMER_MGMT/catalog/request" -H "Content-Type: application/json" -d "{
      \"@context\": { \"@vocab\": \"https://w3id.org/edc/v0.0.1/ns/\" },
      \"counterPartyAddress\": \"$PROVIDER_DSP\", \"protocol\": \"dataspace-protocol-http\" }" \
    | jq -c --arg asset "$asset" '[.["dcat:dataset"] | if type == "array" then .[] else . end
             | select(.["@id"] == $asset) | .["odrl:hasPolicy"] | if type == "array" then .[0] else . end][0]
             | select(. != null)
             | . + {"odrl:assigner": {"@id": "provider"}, "odrl:target": {"@id": $asset}}')
  offer=$(jq -r '.["@id"] // empty' <<<"${policy:-null}")
  if [[ -z "$offer" ]]; then
    echo "ERROR: Could not find offer for asset '$asset'."; exit 1
  fi
  # Catalogue request alone (NEG_MS below also contains it)
  _edc_log "$(printf 'catalog\t%s\t%s' "$tc" "$(( ($(date +%s%N) - start) / 1000000 ))")"
  echo "  Offer ID: $offer"
  echo ""

  echo "[2/4] Negotiating contract..."
  for attempt in $(seq 1 "$NEG_MAX_ATTEMPTS"); do
    neg_id=$(curl -sf -X POST "$CONSUMER_MGMT/contractnegotiations" -H "Content-Type: application/json" -d "{
        \"@context\": { \"@vocab\": \"https://w3id.org/edc/v0.0.1/ns/\", \"edc\": \"https://w3id.org/edc/v0.0.1/ns/\",
                        \"odrl\": \"http://www.w3.org/ns/odrl/2/\" },
        \"@type\": \"ContractRequest\",
        \"counterPartyAddress\": \"$PROVIDER_DSP\", \"protocol\": \"dataspace-protocol-http\",
        \"policy\": $policy }" | jq -r '.["@id"]')
    echo "  Negotiation ID: $neg_id (attempt $attempt/$NEG_MAX_ATTEMPTS)"
    echo "[3/4] Waiting for contract agreement..."
    state=""
    for _ in $(seq 1 300); do   # up to 30 s, checked every 0.1 s
      sleep 0.1
      status=$(curl -sf "$CONSUMER_MGMT/contractnegotiations/$neg_id")
      state=$(echo "$status" | jq -r '.state')
      [[ "$state" == FINALIZED || "$state" == TERMINATED ]] && break
    done
    if [[ "$state" == FINALIZED ]]; then
      AGREEMENT_ID=$(echo "$status" | jq -r '.contractAgreementId')
      NEG_MS=$(( ($(date +%s%N) - start) / 1000000 ))
      _edc_log "$(printf 'neg\t%s\t%s' "$tc" "$NEG_MS")"
      echo "  Agreement ID: $AGREEMENT_ID"
      echo "  Negotiation time: ${NEG_MS} ms"
      echo ""
      return 0
    fi
    reason=$(echo "$status" | jq -r '.errorDetail // "no error detail"' | tr '\t\n' '  ' | cut -c1-200)
    echo "  ✗ Negotiation $neg_id ended in state ${state:-unknown}: $reason" >&2
    _edc_log "$(printf 'neg_retry\t%s\t%s\t%s\t%s' "$tc" "$attempt" "$neg_id" "${state:-timeout}")"
  done
  echo "ERROR: no agreement after $NEG_MAX_ATTEMPTS attempts."
  exit 1
}

# edc_transfer <tc>
# Starts an HttpData-PUSH transfer of AGREEMENT_ID's asset to RECEIVER_URL,
# tagged with RUN_ID, and waits for it to complete. Retried (with a new run id)
# only if EDC terminates it: a transfer that is still running may yet deliver,
# and starting another would deliver the data twice.
# Sets TRANSFER_ID, T_STATE and ELAPSED_MS (last attempt).
edc_transfer() {
  local tc="$1" attempt run_id="$RUN_ID" t_start
  for attempt in $(seq 1 "$TRANSFER_MAX_ATTEMPTS"); do
    [[ $attempt -gt 1 ]] && run_id="$RUN_ID-r$attempt"
    t_start=$(date +%s%N)
    TRANSFER_ID=$(curl -sf -X POST "$CONSUMER_MGMT/transferprocesses" -H "Content-Type: application/json" -d "{
        \"@context\": { \"@vocab\": \"https://w3id.org/edc/v0.0.1/ns/\" },
        \"@type\": \"TransferRequestDto\", \"connectorId\": \"provider\",
        \"counterPartyAddress\": \"$PROVIDER_DSP\", \"contractId\": \"$AGREEMENT_ID\",
        \"protocol\": \"dataspace-protocol-http\", \"transferType\": \"HttpData-PUSH\",
        \"dataDestination\": { \"type\": \"HttpData\", \"baseUrl\": \"$RECEIVER_URL\",
                               \"header:X-Run-Id\": \"$run_id\" } }" | jq -r '.["@id"]')
    T_STATE=""
    for _ in $(seq 1 $((TRANSFER_WAIT_S * 2))); do
      sleep 0.5
      T_STATE=$(curl -sf "$CONSUMER_MGMT/transferprocesses/$TRANSFER_ID" | jq -r '.state')
      [[ "$T_STATE" == COMPLETED || "$T_STATE" == TERMINATED ]] && break
      # Delivered but not (yet) marked COMPLETED — EDC sometimes never does.
      curl -sf "$RECEIVER_BASE/metrics/$tc" 2>/dev/null \
        | jq -e --arg r "$run_id" 'any(.records[]?; .run_id == $r)' > /dev/null 2>&1 && break
    done
    ELAPSED_MS=$(( ($(date +%s%N) - t_start) / 1000000 ))
    if [[ "$T_STATE" != TERMINATED ]]; then
      _edc_log "$(printf 'transfer\t%s\t%s\t%s' "$tc" "$run_id" "$TRANSFER_ID")"
      return 0
    fi
    echo "  ✗ Transfer $TRANSFER_ID terminated (attempt $attempt/$TRANSFER_MAX_ATTEMPTS)" >&2
    _edc_log "$(printf 'transfer_retry\t%s\t%s\t%s\t%s' "$tc" "$attempt" "$run_id" "$TRANSFER_ID")"
  done
  return 0   # the script reports T_STATE; the summary counts the missing delivery
}
