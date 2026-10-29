# Manual EDC Transfer Demo — Step by Step

**Goal:** Walk through all 4 phases of an EDC data transfer manually using `curl`, so you can see exactly what happens at each step.

**Prerequisites:**

- All containers running: `docker compose -f docker/docker-compose.yaml up --build`
- Provider setup done: `bash scripts/1-setup-provider.sh`
- `jq` installed: `brew install jq`

---

## Before You Start — Verify All Services Are Up

EDC 0.14.x removed the `/api/health` endpoint. Use the management API instead — a 200 response means the connector is running.

```bash
# Provider EDC — returns number of registered assets (3 after setup, 0 before)
curl -s -X POST http://localhost:8182/management/v3/assets/request \
  -H "Content-Type: application/json" \
  -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"@type":"QuerySpec"}' | jq 'length'

# Consumer EDC — returns 0 (no negotiations yet)
curl -s -X POST http://localhost:9192/management/v3/contractnegotiations/request \
  -H "Content-Type: application/json" \
  -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"@type":"QuerySpec"}' | jq 'length'

# Data Simulator
curl http://localhost:5000/health | jq

# Data Receiver
curl http://localhost:4000/health | jq
```

---

## Phase 1 — Catalog Discovery

**What happens:** The Consumer connector asks the Provider "what data do you have available?" The Provider responds with its public catalog — a list of assets and the contract terms for each.

### Step 1.1 — Look at the Provider's assets directly (Provider side)

This is you looking at what the Provider has registered:

```bash
curl http://localhost:8182/management/v3/assets | jq
```

You should see 3 assets: `asset-tc1-control`, `asset-tc2-sensors`, `asset-tc3-video`.

### Step 1.2 — Request the catalog through the Consumer

This is the real EDC call. You ask the Consumer connector to fetch the catalog from the Provider. The Consumer makes a DSP protocol call to the Provider on your behalf.

```bash
curl -s -X POST http://localhost:9192/management/v3/catalog/request \
  -H "Content-Type: application/json" \
  -d '{
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "counterPartyAddress": "http://provider:8183/protocol",
    "protocol": "dataspace-protocol-http"
  }' | jq
```

**What you get back:** A DCAT catalog containing all 3 assets. Each asset has a `odrl:hasPolicy` field — that contains the **Offer ID** you need for negotiation.

### Step 1.3 — Extract the Offer ID for TC-1

Pick out just the relevant info for the TC-1 asset:

```bash
curl -s -X POST http://localhost:9192/management/v3/catalog/request \
  -H "Content-Type: application/json" \
  -d '{
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "counterPartyAddress": "http://provider:8183/protocol",
    "protocol": "dataspace-protocol-http"
  }' | jq '
    .["dcat:dataset"]
    | if type == "array" then .[] else . end
    | select(.["@id"] == "asset-tc1-control")
    | {
        asset_id: .["@id"],
        asset_name: .name,
        offer_id: .["odrl:hasPolicy"]["@id"]
      }
  '
```

**Save the `offer_id` value** — you need it in Phase 2.

```bash
# Save it to a variable for the next steps
OFFER_ID=$(curl -s -X POST http://localhost:9192/management/v3/catalog/request \
  -H "Content-Type: application/json" \
  -d '{
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "counterPartyAddress": "http://provider:8183/protocol",
    "protocol": "dataspace-protocol-http"
  }' | jq -r '
    .["dcat:dataset"]
    | if type == "array" then .[] else . end
    | select(.["@id"] == "asset-tc1-control")
    | .["odrl:hasPolicy"]["@id"]
  ')

echo "Offer ID: $OFFER_ID"
```

---

## Phase 2 — Contract Negotiation

**What happens:** The Consumer proposes a contract to the Provider: "I want to use `asset-tc1-control` under the terms of offer `$OFFER_ID`." Both connectors exchange DSP messages. The Provider accepts (because policy is open). Both sides record a signed `ContractAgreement`.

### Step 2.1 — Start the negotiation

```bash
NEG_ID=$(curl -s -X POST http://localhost:9192/management/v3/contractnegotiations \
  -H "Content-Type: application/json" \
  -d "{
    \"@context\": { \"@vocab\": \"https://w3id.org/edc/v0.0.1/ns/\" },
    \"@type\": \"ContractRequest\",
    \"counterPartyAddress\": \"http://provider:8183/protocol\",
    \"protocol\": \"dataspace-protocol-http\",
    \"policy\": {
      \"@context\": \"http://www.w3.org/ns/odrl.jsonld\",
      \"@id\": \"$OFFER_ID\",
      \"@type\": \"Offer\",
      \"assigner\": \"provider\",
      \"target\": \"asset-tc1-control\"
    }
  }" | jq -r '.["@id"]')

echo "Negotiation ID: $NEG_ID"
```

### Step 2.2 — Watch the negotiation state change

Run this a few times, a second apart. You will see the state transition through the EDC state machine:

```text
REQUESTING → OFFERED → ACCEPTED → AGREED → VERIFIED → FINALIZED
```

```bash
# Run this repeatedly to watch the state change
curl -s http://localhost:9192/management/v3/contractnegotiations/$NEG_ID \
  | jq '{state: .state, agreement: .contractAgreementId}'
```

### Step 2.3 — Confirm it is FINALIZED and extract the Agreement ID

```bash
curl -s http://localhost:9192/management/v3/contractnegotiations/$NEG_ID | jq '{
  state: .state,
  agreement_id: .contractAgreementId
}'
```

State must be `FINALIZED` before you can transfer.

```bash
# Save the Agreement ID
AGREEMENT_ID=$(curl -s http://localhost:9192/management/v3/contractnegotiations/$NEG_ID \
  | jq -r '.contractAgreementId')

echo "Agreement ID: $AGREEMENT_ID"
```

### Step 2.4 — Also verify the agreement was recorded on the Consumer side

```bash
curl -s http://localhost:9192/management/v3/contractagreements | jq '.[0] | {
  id: .["@id"],
  asset_id: .assetId,
  provider_id: .providerId,
  consumer_id: .consumerId
}'
```

---

## Phase 3 — Transfer Initiation

**What happens:** You tell the Consumer connector to start a transfer. The Consumer tells the Provider via DSP. The Provider's Data Plane fetches the data from the Simulator and pushes it to the Receiver.

### Step 3.1 — Reset the receiver metrics (clean slate)

```bash
curl -s -X POST http://localhost:4000/reset | jq
```

### Step 3.2 — Initiate the transfer

```bash
TRANSFER_ID=$(curl -s -X POST http://localhost:9192/management/v3/transferprocesses \
  -H "Content-Type: application/json" \
  -d "{
    \"@context\": { \"@vocab\": \"https://w3id.org/edc/v0.0.1/ns/\" },
    \"@type\": \"TransferRequestDto\",
    \"connectorId\": \"provider\",
    \"counterPartyAddress\": \"http://provider:8183/protocol\",
    \"contractId\": \"$AGREEMENT_ID\",
    \"protocol\": \"dataspace-protocol-http\",
    \"transferType\": \"HttpData-PUSH\",
    \"dataDestination\": {
      \"type\": \"HttpData\",
      \"baseUrl\": \"http://receiver:4000/receive/tc1\"
    }
  }" | jq -r '.["@id"]')

echo "Transfer ID: $TRANSFER_ID"
```

### Step 3.3 — Watch the transfer state

```bash
# Run this a few times to see the state change
curl -s http://localhost:9192/management/v3/transferprocesses/$TRANSFER_ID \
  | jq '{state: .state, type: .type}'
```

States you will see: `REQUESTING → STARTED → COMPLETED`

### Step 3.4 — Check all transfer processes on the Consumer

```bash
curl -s http://localhost:9192/management/v3/transferprocesses | jq '.[] | {
  id: .["@id"],
  state: .state,
  asset_id: .assetId
}'
```

---

## Phase 4 — Verify Data Was Received

**What happens:** The Receiver logged the incoming transfer with timing data. You query it to see the actual latency.

### Step 4.1 — Check the receiver got the data

```bash
curl -s http://localhost:4000/metrics/tc1 | jq
```

You should see:

```json
{
  "tc": "tc1",
  "summary": {
    "count": 1,
    "total_bytes": 312,
    "avg_size_bytes": 312.0,
    "latency_ms_min": 847.32,
    "latency_ms_max": 847.32,
    "latency_ms_avg": 847.32,
    "latency_ms_median": 847.32
  },
  "records": [...]
}
```

The `latency_ms_avg` is the end-to-end EDC overhead — from the moment the data was generated in the Simulator to when the Receiver got it.

### Step 4.2 — See the actual payload that was delivered

```bash
curl -s http://localhost:4000/metrics/tc1 | jq '.records[0].preview'
```

This shows the actual TC-1 control signal data that travelled through EDC.

### Step 4.3 — Compare with the raw Simulator data (bypassing EDC)

For comparison, fetch the same data directly from the Simulator — no EDC involved:

```bash
# Direct fetch — no negotiation, no governance
curl -s http://localhost:5000/tc1/control-signal | jq
```

The payload is the same structure. The difference is:

- **Direct fetch:** ~5 ms
- **Through EDC:** ~500–2000 ms

That gap is the EDC overhead — and it's the core finding of TC-1.

---

## Run the Same Flow for TC-2 (Sensor Batch)

Same steps, just change the asset ID and receiver endpoint:

```bash
# Step 1: Get TC-2 offer
OFFER_ID_TC2=$(curl -s -X POST http://localhost:9192/management/v3/catalog/request \
  -H "Content-Type: application/json" \
  -d '{
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "counterPartyAddress": "http://provider:8183/protocol",
    "protocol": "dataspace-protocol-http"
  }' | jq -r '
    .["dcat:dataset"]
    | if type == "array" then .[] else . end
    | select(.["@id"] == "asset-tc2-sensors")
    | .["odrl:hasPolicy"]["@id"]
  ')

echo "TC-2 Offer: $OFFER_ID_TC2"

# Step 2: Negotiate
NEG_ID_TC2=$(curl -s -X POST http://localhost:9192/management/v3/contractnegotiations \
  -H "Content-Type: application/json" \
  -d "{
    \"@context\": { \"@vocab\": \"https://w3id.org/edc/v0.0.1/ns/\" },
    \"@type\": \"ContractRequest\",
    \"counterPartyAddress\": \"http://provider:8183/protocol\",
    \"protocol\": \"dataspace-protocol-http\",
    \"policy\": {
      \"@context\": \"http://www.w3.org/ns/odrl.jsonld\",
      \"@id\": \"$OFFER_ID_TC2\",
      \"@type\": \"Offer\",
      \"assigner\": \"provider\",
      \"target\": \"asset-tc2-sensors\"
    }
  }" | jq -r '.["@id"]')

# Step 3: Wait for FINALIZED (run a few times)
sleep 3
curl -s http://localhost:9192/management/v3/contractnegotiations/$NEG_ID_TC2 | jq '.state'

AGREEMENT_ID_TC2=$(curl -s http://localhost:9192/management/v3/contractnegotiations/$NEG_ID_TC2 \
  | jq -r '.contractAgreementId')

# Step 4: Transfer
curl -s -X POST http://localhost:4000/reset | jq .

curl -s -X POST http://localhost:9192/management/v3/transferprocesses \
  -H "Content-Type: application/json" \
  -d "{
    \"@context\": { \"@vocab\": \"https://w3id.org/edc/v0.0.1/ns/\" },
    \"@type\": \"TransferRequestDto\",
    \"connectorId\": \"provider\",
    \"counterPartyAddress\": \"http://provider:8183/protocol\",
    \"contractId\": \"$AGREEMENT_ID_TC2\",
    \"protocol\": \"dataspace-protocol-http\",
    \"transferType\": \"HttpData-PUSH\",
    \"dataDestination\": {
      \"type\": \"HttpData\",
      \"baseUrl\": \"http://receiver:4000/receive/tc2\"
    }
  }" | jq -r '.["@id"]'

# Step 5: Check metrics (wait 5s first)
sleep 5
curl -s http://localhost:4000/metrics/tc2 | jq '.summary'
```

TC-2 will show higher `avg_size_bytes` (~50 KB vs ~300 bytes for TC-1) but similar latency — demonstrating that EDC overhead is mostly fixed negotiation cost, not data-size-dependent.

---

## Quick Reference — All Management API Endpoints

```bash
# ── Provider (port 8182) ──────────────────────────────────────────
# List all assets
curl http://localhost:8182/management/v3/assets | jq

# List all policies
curl http://localhost:8182/management/v3/policydefinitions | jq

# List all contract definitions
curl http://localhost:8182/management/v3/contractdefinitions | jq

# ── Consumer (port 9192) ──────────────────────────────────────────
# All negotiations
curl http://localhost:9192/management/v3/contractnegotiations | jq '.[].state'

# All agreements
curl http://localhost:9192/management/v3/contractagreements | jq

# All transfer processes
curl http://localhost:9192/management/v3/transferprocesses | jq '.[] | {id: .["@id"], state: .state}'

# ── Receiver (port 4000) ──────────────────────────────────────────
# All metrics
curl http://localhost:4000/metrics | jq '.tc1.summary, .tc2.summary, .tc3.summary'

# Reset between runs
curl -X POST http://localhost:4000/reset | jq
```

---

*The key takeaway from running this manually: even one transfer takes 500–2000 ms from start to finish. The negotiation phase alone is ~300–1000 ms. This is the evidence base for the research finding that EDC is unsuitable for real-time control but works well for governed batch transfers.*
