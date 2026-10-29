#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 1-setup-provider.sh
# Registers the test-case assets (TC-1 … TC-4) and the payload-sweep assets
# (one per size in SWEEP_SIZES), one open policy, and a contract definition
# per asset on the Provider connector.
# Run once after the connectors are healthy.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

source "$(dirname "$0")/lib-endpoints.sh"
SIMULATOR="$SIMULATOR_ASSET_BASE"   # the data source, as provider-dp reaches it (see lib-endpoints.sh)

echo "======================================================================"
echo " Provider Setup — Creating Assets, Policy, and Contract Definitions"
echo "======================================================================"
echo ""

wait_for_provider() {
  echo "Waiting for Provider Management API..."
  # curl without -f: any HTTP response (even 4xx) means the API is listening
  until curl -s -o /dev/null "$PROVIDER_MGMT/assets" 2>/dev/null; do
    sleep 2
  done
  sleep 2   # give the HTTP server one extra second to finish binding
  echo "Provider is up."
  echo ""
}
wait_for_provider

# Create a resource on the provider's Management API, or update it if it
# already exists (HTTP 409). The connector keeps its state in Postgres, so on a
# re-run the resource may be there already — possibly with an outdated data
# address (e.g. after the data source moved to another machine). Updating it
# keeps the catalogue in step with deploy/hosts.env and makes re-runs safe.
mgmt_create() {   # usage: mgmt_create <path> <json-body>
  local path="$1" body="$2" resp code id put_url
  resp="$(curl -s -w '\n%{http_code}' -X POST "$PROVIDER_MGMT/$path" \
    -H "Content-Type: application/json" -d "$body")"
  code="${resp##*$'\n'}"
  resp="${resp%$'\n'*}"
  case "$code" in
    2??) echo "$resp"; return ;;
    409) ;;
    *)   echo "  ✗ POST $path failed (HTTP $code): $resp" >&2; return 1 ;;
  esac
  id="$(jq -r '.["@id"]' <<<"$body")"
  # Policy definitions are updated by id in the path; assets and contract
  # definitions carry their id in the body.
  if [[ "$path" == "policydefinitions" ]]; then put_url="$PROVIDER_MGMT/$path/$id"; else put_url="$PROVIDER_MGMT/$path"; fi
  code="$(curl -s -o /dev/null -w '%{http_code}' -X PUT "$put_url" \
    -H "Content-Type: application/json" -d "$body")"
  [[ "$code" == 2?? ]] || { echo "  ✗ PUT $path/$id failed (HTTP $code)" >&2; return 1; }
  jq -c --arg id "$id (updated)" '{"@id": $id}' <<<"$body"
}

# ── 1. Create Assets ──────────────────────────────────────────────────────────

echo "--- Creating TC-1 Asset (real-time control signal) ---"
mgmt_create assets '{
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "@id": "asset-tc1-control",
    "properties": {
      "name": "TC-1 Real-time Control Signal",
      "description": "Near-real-time control signal from AGV-001 at ~50 Hz",
      "contenttype": "application/json",
      "testcase": "TC1"
    },
    "dataAddress": {
      "type": "HttpData",
      "baseUrl": "'"$SIMULATOR"'/tc1/control-signal",
      "proxyPath": "false"
    }
  }' | jq -r '"  → Asset ID: \(.["@id"])"'

echo ""
echo "--- Creating TC-2 Asset (high-frequency sensor batch) ---"
mgmt_create assets '{
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "@id": "asset-tc2-sensors",
    "properties": {
      "name": "TC-2 High-Frequency Sensor Batch",
      "description": "1 kHz vibration sensor batch (1000 samples per request)",
      "contenttype": "application/json",
      "testcase": "TC2"
    },
    "dataAddress": {
      "type": "HttpData",
      "baseUrl": "'"$SIMULATOR"'/tc2/sensor-batch",
      "proxyPath": "false"
    }
  }' | jq -r '"  → Asset ID: \(.["@id"])"'

echo ""
echo "--- Creating TC-3 Asset (video frame) ---"
mgmt_create assets '{
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "@id": "asset-tc3-video",
    "properties": {
      "name": "TC-3 Video Frame",
      "description": "Simulated 640x480 camera frame (~15 KB compressed)",
      "contenttype": "application/json",
      "testcase": "TC3"
    },
    "dataAddress": {
      "type": "HttpData",
      "baseUrl": "'"$SIMULATOR"'/tc3/video-frame",
      "proxyPath": "false"
    }
  }' | jq -r '"  → Asset ID: \(.["@id"])"'

echo ""
echo "--- Creating TC-4 Asset (triggered event alert) ---"
mgmt_create assets '{
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "@id": "asset-tc4-alert",
    "properties": {
      "name": "TC-4 Triggered Event Alert",
      "description": "Single-shot threshold-crossing alert derived from the SensorData rms field",
      "contenttype": "application/json",
      "testcase": "TC4"
    },
    "dataAddress": {
      "type": "HttpData",
      "baseUrl": "'"$TC4_ASSET_URL"'",
      "proxyPath": "false"
    }
  }' | jq -r '"  → Asset ID: \(.["@id"])"'

# Payload-size sweep (6-payload-sweep.sh): one asset per size, same data source
SWEEP_ASSETS=""
for SIZE in ${SWEEP_SIZES:-10240 1048576 10485760 52428800}; do
  echo ""
  echo "--- Creating sweep asset ($SIZE bytes) ---"
  mgmt_create assets '{
      "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
      "@id": "asset-sweep-'"$SIZE"'",
      "properties": {
        "name": "Payload sweep, '"$SIZE"' bytes",
        "contenttype": "application/json",
        "testcase": "sweep"
      },
      "dataAddress": {
        "type": "HttpData",
        "baseUrl": "'"$SIMULATOR"'/sweep/'"$SIZE"'",
        "proxyPath": "false"
      }
    }' | jq -r '"  → Asset ID: \(.["@id"])"'
  SWEEP_ASSETS="$SWEEP_ASSETS asset-sweep-$SIZE"
done

# Policy-enforcement test (7-pull-transfer.sh pull-timed): TC-1's data under a
# contract that is only valid for a limited time after it is agreed
echo ""
echo "--- Creating time-limited asset (TC-1 data, policy-timed) ---"
mgmt_create assets '{
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "@id": "asset-tc1-timed",
    "properties": {
      "name": "TC-1 control signal, time-limited contract",
      "contenttype": "application/json",
      "testcase": "policy"
    },
    "dataAddress": {
      "type": "HttpData",
      "baseUrl": "'"$SIMULATOR"'/tc1/control-signal",
      "proxyPath": "false"
    }
  }' | jq -r '"  → Asset ID: \(.["@id"])"'

# ── 2. Create Open Access Policy ──────────────────────────────────────────────
echo ""
echo "--- Creating open-access policy ---"
mgmt_create policydefinitions '{
    "@context": {
      "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
      "odrl": "http://www.w3.org/ns/odrl/2/"
    },
    "@id": "policy-open",
    "policy": {
      "@context": "http://www.w3.org/ns/odrl.jsonld",
      "@type": "Set",
      "permission": [],
      "prohibition": [],
      "obligation": []
    }
  }' | jq -r '"  → Policy ID: \(.["@id"])"'

# Usage allowed until POLICY_VALID_S seconds after the contract agreement
# (EDC's inForceDate constraint). Checked when a transfer starts, and again
# and again by the provider's policy monitor while it runs.
echo ""
echo "--- Creating time-limited policy (valid ${POLICY_VALID_S:-30} s after agreement) ---"
mgmt_create policydefinitions '{
    "@context": {
      "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
      "odrl": "http://www.w3.org/ns/odrl/2/"
    },
    "@id": "policy-timed",
    "policy": {
      "@context": "http://www.w3.org/ns/odrl.jsonld",
      "@type": "Set",
      "permission": [{
        "action": "use",
        "constraint": {
          "@type": "AtomicConstraint",
          "leftOperand": "https://w3id.org/edc/v0.0.1/ns/inForceDate",
          "operator": { "@id": "odrl:lteq" },
          "rightOperand": {
            "@value": "contractAgreement+'"${POLICY_VALID_S:-30}"'s",
            "@type": "https://w3id.org/edc/v0.0.1/ns/dateExpression"
          }
        }
      }],
      "prohibition": [],
      "obligation": []
    }
  }' | jq -r '"  → Policy ID: \(.["@id"])"'

# ── 3. Create Contract Definitions (one per asset) ────────────────────────────
echo ""
echo "--- Creating contract definitions ---"

for ASSET_ID in "asset-tc1-control" "asset-tc2-sensors" "asset-tc3-video" "asset-tc4-alert" "asset-tc1-timed" $SWEEP_ASSETS; do
  DEF_ID="def-${ASSET_ID}"
  CONTRACT_POLICY="policy-open"; [[ "$ASSET_ID" == "asset-tc1-timed" ]] && CONTRACT_POLICY="policy-timed"
  mgmt_create contractdefinitions "{
      \"@context\": { \"@vocab\": \"https://w3id.org/edc/v0.0.1/ns/\" },
      \"@id\": \"$DEF_ID\",
      \"accessPolicyId\": \"policy-open\",
      \"contractPolicyId\": \"$CONTRACT_POLICY\",
      \"assetsSelector\": [
        {
          \"@type\": \"Criterion\",
          \"operandLeft\": \"https://w3id.org/edc/v0.0.1/ns/id\",
          \"operator\": \"=\",
          \"operandRight\": \"$ASSET_ID\"
        }
      ]
    }" | jq -r '"  → Contract Def ID: \(.["@id"])"'
done

echo ""
echo "======================================================================"
echo " Setup complete: the four test-case assets, the payload-sweep assets,
 and a contract definition for each."
echo " Run test scripts: 2-tc1.sh, 3-tc2.sh, 4-tc3.sh, 5-tc4.sh"
echo "======================================================================"
