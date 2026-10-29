# EDC Test Plan — Installation & Testing Guide

**Project:** Minimal Viable Dataspace — TUNI EDC Edge Feasibility Test  
**Covers:** EDC Test Plan (2026-04-23) — TC-1, TC-2, TC-3  
**Architecture:** Provider EDC + Consumer EDC (Docker) + Data Simulator + Receiver

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Cloud (simulated — Docker network)                     │
│                                                         │
│  ┌──────────────────┐    DSP     ┌──────────────────┐  │
│  │  Provider EDC    │◄──────────►│  Consumer EDC    │  │
│  │  Control Plane   │  negotiate │  Control Plane   │  │
│  │  :8182 (mgmt)    │            │  :9192 (mgmt)    │  │
│  │  :8183 (DSP)     │            │  :9193 (DSP)     │  │
│  └────────┬─────────┘            └─────────┬────────┘  │
│           │ control                         │ control   │
│  ─ ─ ─ ─ ─│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│─ ─ ─ ─ ─  │
│  Edge (resource-constrained Docker containers)          │
│           │                                 │           │
│  ┌────────▼─────────┐  push data  ┌─────────▼────────┐ │
│  │  Provider        │────────────►│  Consumer        │ │
│  │  Data Plane      │             │  Data Plane      │ │
│  │  :8184 (public)  │             │  :9194 (public)  │ │
│  └────────▲─────────┘             └──────────────────┘ │
│           │ fetch                          ▲ push       │
│  ┌────────┴─────────┐             ┌────────┴─────────┐  │
│  │  Data Simulator  │             │  Data Receiver   │  │
│  │  :5000           │             │  :4000           │  │
│  │  TC-1/TC-2/TC-3  │             │  metrics + logs  │  │
│  └──────────────────┘             └──────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Flow:**  
1. Consumer requests catalog → Provider DSP lists available assets  
2. Contract negotiated (Control Plane ↔ Control Plane over DSP)  
3. Transfer started → Provider Data Plane fetches from Simulator, pushes to Receiver  
4. Receiver logs timing and size → metrics collected

---

## Prerequisites

| Tool | Minimum version | Check |
|------|----------------|-------|
| Docker | 20+ | `docker --version` |
| Docker Compose | v2 | `docker compose version` |
| curl | any | `curl --version` |
| jq | any | `jq --version` |

No Java or Gradle installation required — the build runs entirely inside Docker.

Install `jq` on macOS: `brew install jq`

---

## Step 1 — Start All Services

```bash
# From the project root
docker compose -f docker/docker-compose.yaml up --build
```

Docker will compile the EDC connector JAR inside a builder container (Gradle 9 + JDK 17) and produce a lean runtime image (~100 MB). This happens automatically during `--build`.

**First-run build time:** ~5–10 minutes (Gradle downloads ~150 MB of EDC dependencies). Subsequent runs use Docker layer cache and are much faster.

This starts 4 containers:
- `provider-connector` — Provider EDC (ports 8181–8185)
- `consumer-connector` — Consumer EDC (ports 9191–9195)
- `data-simulator`     — Test data service (port 5000)
- `data-receiver`      — Metrics receiver (port 4000)

Wait until you see both connectors print `EDC system [booted]` in the logs (~30–60 seconds).

### Verify all services are up

```bash
# Provider — lists registered assets (empty array [] if setup not yet run)
curl -s -X POST http://localhost:8182/management/v3/assets/request \
  -H "Content-Type: application/json" \
  -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"@type":"QuerySpec"}' | jq 'length'

# Consumer — lists contract negotiations (returns 0 before any test runs)
curl -s -X POST http://localhost:9192/management/v3/contractnegotiations/request \
  -H "Content-Type: application/json" \
  -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"@type":"QuerySpec"}' | jq 'length'

# Simulator
curl http://localhost:5000/health | jq

# Receiver
curl http://localhost:4000/health | jq
```

The connectors are up when the management API responds (any HTTP 200). EDC 0.14.x removed the `/api/health` endpoint — use the management API calls above instead.

Note: after `1-setup-provider.sh` runs, the assets query will return `3` instead of `0`.

---

## Step 2 — Run with Edge Resource Constraints (Optional)

To simulate edge devices (as per the EDC Test Plan), limit Docker resources:

```bash
# Edge-constrained: 0.5 CPU / 512 MB per connector
EDGE_CPU=0.5 EDGE_MEM=512m \
  docker compose -f docker/docker-compose.yaml up --build

# Highly constrained: 0.25 CPU / 256 MB per connector
EDGE_CPU=0.25 EDGE_MEM=256m \
  docker compose -f docker/docker-compose.yaml up --build
```

Run the same test scripts under each resource profile and compare metrics.

---

## Step 3 — Setup Provider Resources

In a new terminal (connectors must be running):

```bash
cd edc-connector-placement-testbed
bash scripts/1-setup-provider.sh
```

This creates:
- 3 assets: `asset-tc1-control`, `asset-tc2-sensors`, `asset-tc3-video`
- 1 open-access policy: `policy-open`
- 3 contract definitions (one per asset)

---

## Step 4 — Run the Test Cases

### TC-1: Real-time Control Signal

```bash
bash scripts/2-tc1-realtime-control.sh
```

**What it tests:** Whether EDC can deliver near-real-time control data (50 Hz target = 20 ms per transfer).  
**Expected finding:** EDC negotiation + transfer overhead is typically 200–2000 ms, far exceeding the 20 ms budget. This quantifies the latency gap.

```bash
# Control the number of transfers
TC1_REPEAT=10 bash scripts/2-tc1-realtime-control.sh
```

### TC-2: High-Frequency Sensor Batch

```bash
bash scripts/3-tc2-high-freq-sensors.sh
```

**What it tests:** Throughput for bulk sensor data (1 kHz → 1000 samples per batch, ~50 KB).  
**Expected finding:** Batch transfers are more EDC-friendly. Measures how batch size affects throughput.

```bash
TC2_REPEAT=10 bash scripts/3-tc2-high-freq-sensors.sh
```

### TC-3: Video Stream (Frame-by-Frame)

```bash
bash scripts/4-tc3-video-stream.sh
```

**What it tests:** Achievable frame rate through EDC (target: 24 fps = 41 ms/frame).  
**Expected finding:** Achievable rate will be well below 24 fps due to EDC per-transfer overhead.

```bash
TC3_REPEAT=20 bash scripts/4-tc3-video-stream.sh
```

### Run All Tests at Once

```bash
bash scripts/run-all-tests.sh
```

---

## Step 5 — View Metrics

The receiver logs all incoming transfers with timing data:

```bash
# All test cases summary
curl http://localhost:4000/metrics | jq

# Individual test case
curl http://localhost:4000/metrics/tc1 | jq
curl http://localhost:4000/metrics/tc2 | jq
curl http://localhost:4000/metrics/tc3 | jq
```

Metrics include:
- `count` — number of successful transfers
- `total_bytes` — total data received
- `avg_size_bytes` — average payload size
- `latency_ms_avg/min/max/median/stdev` — end-to-end latency (data timestamp → arrival)

Reset between runs:
```bash
curl -X POST http://localhost:4000/reset
```

---

## Step 6 — Inspect Connector State (Advanced)

In EDC 0.14.x all query operations use `POST .../request` instead of `GET`.

```bash
# List all assets on provider
curl -s -X POST http://localhost:8182/management/v3/assets/request \
  -H "Content-Type: application/json" \
  -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"@type":"QuerySpec"}' \
  | jq '[.[] | {id: .["@id"], name: .properties.name}]'

# List contract negotiations on consumer
curl -s -X POST http://localhost:9192/management/v3/contractnegotiations/request \
  -H "Content-Type: application/json" \
  -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"@type":"QuerySpec"}' \
  | jq '.[].state'

# List transfer processes on consumer
curl -s -X POST http://localhost:9192/management/v3/transferprocesses/request \
  -H "Content-Type: application/json" \
  -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"@type":"QuerySpec"}' \
  | jq '.[] | {id: .["@id"], state: .state}'

# Provider catalog (as seen by consumer)
curl -s -X POST http://localhost:9192/management/v3/catalog/request \
  -H "Content-Type: application/json" \
  -d '{
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "counterPartyAddress": "http://provider:8183/protocol",
    "protocol": "dataspace-protocol-http"
  }' | jq '[.["dcat:dataset"][] | {id: .["@id"], name: .name}]'
```

---

## Port Reference

| Service | Port | Purpose |
|---------|------|---------|
| Provider | 8181 | Default API (no health endpoint in v0.14.x) |
| Provider | 8182 | Management API (create assets, policies; use POST .../request to query) |
| Provider | 8183 | DSP Protocol (contract negotiation) |
| Provider | 8184 | Data Plane public (data transfer) |
| Provider | 8185 | Control signaling (internal) |
| Consumer | 9191 | Default API |
| Consumer | 9192 | Management API (initiate transfers; use POST .../request to query) |
| Consumer | 9193 | DSP Protocol |
| Consumer | 9194 | Data Plane public |
| Consumer | 9195 | Control signaling |
| Simulator | 5000 | Test data endpoints |
| Receiver | 4000 | Receive + metrics |

---

## Simulator Endpoints (Manual Testing)

```bash
# TC-1: Real-time control signal
curl http://localhost:5000/tc1/control-signal | jq

# TC-2: Sensor batch (1000 samples)
curl http://localhost:5000/tc2/sensor-batch | jq '{
  sensor_id, sample_rate_hz, sample_count, rms,
  first_reading: .readings[0]
}'

# TC-3: Video frame
curl http://localhost:5000/tc3/video-frame | jq '{
  frame_id, width, height, compressed_size_bytes
}'
```

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| Build fails in Docker | Gradle download timeout | Re-run `docker compose up --build` (network retry) |
| Provider/Consumer not starting | Port conflict | Check `lsof -i :8181` |
| Negotiation fails | Connectors can't reach each other | Ensure both on `dataspace-net`; check Docker logs |
| Transfer stays `STARTED` | Data Plane not registered | Wait 30s after startup for self-registration |
| `jq: command not found` | jq not installed | `brew install jq` |

---

## Questions Addressed

| Test Case | Question (from EDC Test Plan) |
|-----------|---------------------------------------|
| TC-1 | Can EDC support near-real-time control (≤20 ms)? |
| TC-2 | What throughput does EDC achieve for large sensor batches? |
| TC-3 | What frame rate is achievable for video through EDC? |
| All TCs | How do edge resource constraints affect connector performance? |
| Repeat with limits | What is the minimum resource threshold for a functioning connector? |

---

## Stopping

```bash
docker compose -f docker/docker-compose.yaml down
```

To also remove built images:
```bash
docker compose -f docker/docker-compose.yaml down --rmi local
```

---

*Last updated: 2026-05-05*
