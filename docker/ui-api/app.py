"""
EDC Dataspace Dashboard — Backend API (BFF)
Proxies to Provider/Consumer EDC management APIs and orchestrates test runs.
Streams live test progress via SSE.
Persists catalog cache, negotiations, and agreements to SQLite.
"""

import asyncio
import base64
import json
import os
import sqlite3
import statistics
import time
import uuid
from contextlib import contextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="EDC Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Endpoints — defaults match the single-machine compose (Docker service names).
# Distributed deployments (deploy/units/dashboard) override them with host
# addresses, since each connector unit may run on a different machine.
PROVIDER_MGMT      = os.getenv("PROVIDER_MGMT", "http://provider-cp:8182/management/v3")
CONSUMER_MGMT      = os.getenv("CONSUMER_MGMT", "http://consumer-cp:9192/management/v3")
PROVIDER_DSP       = os.getenv("PROVIDER_DSP", "http://provider-cp:8183/protocol")
RECEIVER_BASE      = os.getenv("RECEIVER_BASE", "http://receiver:4000")
# Written into asset data addresses, so it is resolved by provider-dp (which
# shares a network with the simulator) — not by this service.
SIMULATOR_INTERNAL = os.getenv("SIMULATOR_INTERNAL", "http://simulator:5000")
# Called directly by this service (TC-4 trigger).
SIMULATOR_URL      = os.getenv("SIMULATOR_URL", SIMULATOR_INTERNAL)
# BaSyx AAS environment. Single-machine: internal address, active only with
# --profile basyx. Distributed: runs in the provider-source unit on the data
# source machine.
BASYX_AAS_BASE     = os.getenv("BASYX_AAS_BASE", "http://basyx-aas:8081")
# Where the TC-4 asset reads the alert: "aas" (SensorData/LastAlert in the
# AAS) or "simulator" (/tc4/alert-event) — same switch as the test scripts.
TC4_SOURCE         = os.getenv("TC4_SOURCE", "simulator")

# BaSyx submodel IDs (AAS Part 2 API uses URL-safe base64 without padding)
SM_IDS = {
    "tc1": "urn:ilmatar:crane:sm:ControlSignal",
    "tc2": "urn:ilmatar:crane:sm:SensorData",
    "tc3": "urn:ilmatar:crane:sm:VideoStream",
}


def _sm_b64(sm_id: str) -> str:
    return base64.urlsafe_b64encode(sm_id.encode()).decode().rstrip("=")

DB_PATH = os.getenv("DB_PATH", "/data/consumer.db")

TC_CONFIG = {
    "tc1": {
        "asset_id":     "asset-tc1-control",
        "receiver_url": f"{RECEIVER_BASE}/receive/tc1",
        "label":        "TC-1 Real-time Control",
        "target_hz":    50,
    },
    "tc2": {
        "asset_id":     "asset-tc2-sensors",
        "receiver_url": f"{RECEIVER_BASE}/receive/tc2",
        "label":        "TC-2 High-Frequency Sensors",
        "target_hz":    1000,
    },
    "tc3": {
        "asset_id":     "asset-tc3-video",
        "receiver_url": f"{RECEIVER_BASE}/receive/tc3",
        "label":        "TC-3 Video Stream",
        "target_hz":    24,
    },
    "tc4": {
        "asset_id":     "asset-tc4-alert",
        "receiver_url": f"{RECEIVER_BASE}/receive/tc4",
        "label":        "TC-4 Triggered Event Alert",
        "triggered":    True,  # simulator alert must be POSTed before each transfer
    },
}

# In-memory run history — keyed by run_id
_runs: dict[str, dict] = {}

QUERY_SPEC = {
    "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
    "@type": "QuerySpec",
}


# ── SQLite ────────────────────────────────────────────────────────────────────

@contextmanager
def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_db() -> None:
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS catalog_cache (
                id         INTEGER PRIMARY KEY,
                fetched_at INTEGER NOT NULL,
                data       TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS negotiations (
                neg_id       TEXT PRIMARY KEY,
                asset_id     TEXT,
                offer_id     TEXT,
                asset_name   TEXT,
                state        TEXT    DEFAULT 'REQUESTING',
                agreement_id TEXT,
                started_at   INTEGER,
                updated_at   INTEGER
            );

            CREATE TABLE IF NOT EXISTS agreements (
                agreement_id TEXT PRIMARY KEY,
                neg_id       TEXT,
                asset_id     TEXT,
                asset_name   TEXT,
                provider_id  TEXT,
                finalized_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS test_runs (
                run_id       TEXT    PRIMARY KEY,
                tc           TEXT    NOT NULL,
                label        TEXT,
                repeats      INTEGER,
                status       TEXT    DEFAULT 'pending',
                started_at   INTEGER,
                completed_at INTEGER,
                result_json  TEXT,
                error        TEXT
            );

            CREATE TABLE IF NOT EXISTS access_requests (
                request_id   TEXT    PRIMARY KEY,
                asset_id     TEXT    NOT NULL,
                asset_name   TEXT,
                status       TEXT    DEFAULT 'pending',
                requested_at INTEGER NOT NULL,
                decided_at   INTEGER
            );
        """)


def _save_run_to_db(run_id: str) -> None:
    run = _runs[run_id]
    with _db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO test_runs
               (run_id, tc, label, repeats, status, started_at, completed_at, result_json, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, run["tc"], run["label"], run["repeats"], run["status"],
                run["started_at"], _now_ms(),
                json.dumps(run["result"]) if run.get("result") else None,
                run.get("error"),
            ),
        )


def _load_runs_from_db() -> None:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM test_runs ORDER BY started_at DESC"
        ).fetchall()
    for row in rows:
        if row["run_id"] in _runs:
            continue
        result = json.loads(row["result_json"]) if row["result_json"] else None
        _runs[row["run_id"]] = {
            "id":         row["run_id"],
            "tc":         row["tc"],
            "label":      row["label"],
            "repeats":    row["repeats"],
            "status":     row["status"],
            "events":     [],
            "started_at": row["started_at"],
            "result":     result,
            "error":      row["error"],
        }


@app.on_event("startup")
async def startup() -> None:
    _init_db()
    _load_runs_from_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_ms() -> int:
    return round(time.time() * 1000)


def _emit(run_id: str, event_type: str, **kwargs) -> None:
    event = {"type": event_type, "ts": _now_ms(), **kwargs}
    _runs[run_id]["events"].append(event)


async def _post_json(client: httpx.AsyncClient, url: str, body: dict) -> dict:
    r = await client.post(url, json=body, headers={"Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


async def _get_json(client: httpx.AsyncClient, url: str) -> dict:
    r = await client.get(url)
    r.raise_for_status()
    return r.json()


# ── Provider proxy ────────────────────────────────────────────────────────────

@app.get("/api/provider/assets")
async def provider_assets():
    async with httpx.AsyncClient(timeout=15) as c:
        data = await _post_json(c, f"{PROVIDER_MGMT}/assets/request", QUERY_SPEC)
    return data if isinstance(data, list) else []


@app.get("/api/provider/policies")
async def provider_policies():
    async with httpx.AsyncClient(timeout=15) as c:
        data = await _post_json(c, f"{PROVIDER_MGMT}/policydefinitions/request", QUERY_SPEC)
    return data if isinstance(data, list) else []


@app.get("/api/provider/contractdefinitions")
async def provider_contractdefs():
    async with httpx.AsyncClient(timeout=15) as c:
        data = await _post_json(c, f"{PROVIDER_MGMT}/contractdefinitions/request", QUERY_SPEC)
    return data if isinstance(data, list) else []


@app.get("/api/provider/transfers")
async def provider_transfers():
    async with httpx.AsyncClient(timeout=15) as c:
        data = await _post_json(c, f"{PROVIDER_MGMT}/transferprocesses/request", QUERY_SPEC)
    return data if isinstance(data, list) else []


# ── Consumer proxy — Catalog ──────────────────────────────────────────────────

@app.get("/api/consumer/catalog")
async def consumer_catalog():
    """Fetch a fresh catalog from the provider and cache it in SQLite."""
    async with httpx.AsyncClient(timeout=30) as c:
        data = await _post_json(c, f"{CONSUMER_MGMT}/catalog/request", {
            "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
            "counterPartyAddress": PROVIDER_DSP,
            "protocol": "dataspace-protocol-http",
        })
    with _db() as conn:
        conn.execute("DELETE FROM catalog_cache")
        conn.execute(
            "INSERT INTO catalog_cache (fetched_at, data) VALUES (?, ?)",
            (_now_ms(), json.dumps(data)),
        )
    return data


@app.get("/api/consumer/catalog/cached")
async def consumer_catalog_cached():
    """Return the last cached catalog without hitting the provider. Returns null if empty."""
    with _db() as conn:
        row = conn.execute(
            "SELECT fetched_at, data FROM catalog_cache ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {"fetched_at": row["fetched_at"], "data": json.loads(row["data"])}


# ── Consumer proxy — Negotiations ─────────────────────────────────────────────

@app.get("/api/consumer/negotiations")
async def consumer_negotiations():
    async with httpx.AsyncClient(timeout=15) as c:
        data = await _post_json(c, f"{CONSUMER_MGMT}/contractnegotiations/request", QUERY_SPEC)
    return data if isinstance(data, list) else []


@app.get("/api/consumer/negotiations/{neg_id}")
async def consumer_get_negotiation(neg_id: str):
    """Fetch negotiation state from EDC and update it in the local DB."""
    async with httpx.AsyncClient(timeout=15) as c:
        data = await _get_json(c, f"{CONSUMER_MGMT}/contractnegotiations/{neg_id}")

    state        = data.get("state", "")
    agreement_id = data.get("contractAgreementId")

    with _db() as conn:
        conn.execute(
            "UPDATE negotiations SET state = ?, agreement_id = ?, updated_at = ? WHERE neg_id = ?",
            (state, agreement_id, _now_ms(), neg_id),
        )
        if state == "FINALIZED" and agreement_id:
            row = conn.execute(
                "SELECT asset_id, asset_name FROM negotiations WHERE neg_id = ?", (neg_id,)
            ).fetchone()
            asset_id   = row["asset_id"]   if row else ""
            asset_name = row["asset_name"] if row else ""
            conn.execute(
                """INSERT OR IGNORE INTO agreements
                   (agreement_id, neg_id, asset_id, asset_name, provider_id, finalized_at)
                   VALUES (?, ?, ?, ?, 'provider', ?)""",
                (agreement_id, neg_id, asset_id, asset_name, _now_ms()),
            )

    return data


@app.get("/api/consumer/db/negotiations")
async def db_negotiations():
    """Return all negotiation records stored locally in SQLite."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM negotiations ORDER BY started_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Consumer proxy — Agreements ───────────────────────────────────────────────

@app.get("/api/consumer/agreements")
async def consumer_agreements():
    async with httpx.AsyncClient(timeout=15) as c:
        data = await _post_json(c, f"{CONSUMER_MGMT}/contractagreements/request", QUERY_SPEC)
    return data if isinstance(data, list) else []


@app.get("/api/consumer/db/agreements")
async def db_agreements():
    """Return all agreement records stored locally in SQLite."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM agreements ORDER BY finalized_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Consumer proxy — Transfers & Negotiate ────────────────────────────────────

@app.get("/api/consumer/transfers")
async def consumer_transfers():
    async with httpx.AsyncClient(timeout=15) as c:
        data = await _post_json(c, f"{CONSUMER_MGMT}/transferprocesses/request", QUERY_SPEC)
    return data if isinstance(data, list) else []


@app.post("/api/consumer/negotiate")
async def consumer_start_negotiation(body: dict):
    """Start a contract negotiation and record it in the local DB."""
    async with httpx.AsyncClient(timeout=30) as c:
        data = await _post_json(c, f"{CONSUMER_MGMT}/contractnegotiations", body)

    policy     = body.get("policy", {})
    asset_id   = policy.get("target", "")
    offer_id   = policy.get("@id", "")
    neg_id     = data.get("@id", "")

    # Resolve asset name from the cached catalog
    asset_name = asset_id
    with _db() as conn:
        cached = conn.execute(
            "SELECT data FROM catalog_cache ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        if cached:
            catalog    = json.loads(cached["data"])
            datasets   = catalog.get("dcat:dataset", [])
            if not isinstance(datasets, list):
                datasets = [datasets]
            for ds in datasets:
                if ds.get("@id") == asset_id:
                    asset_name = ds.get("name", asset_id)
                    break

        conn.execute(
            """INSERT OR REPLACE INTO negotiations
               (neg_id, asset_id, offer_id, asset_name, state, started_at, updated_at)
               VALUES (?, ?, ?, ?, 'REQUESTING', ?, ?)""",
            (neg_id, asset_id, offer_id, asset_name, _now_ms(), _now_ms()),
        )

    return data


@app.post("/api/consumer/transfer")
async def consumer_start_transfer(body: dict):
    """Initiate a transfer process from the consumer side."""
    async with httpx.AsyncClient(timeout=30) as c:
        data = await _post_json(c, f"{CONSUMER_MGMT}/transferprocesses", body)
    return data


# ── Receiver proxy ────────────────────────────────────────────────────────────

@app.get("/api/receiver/metrics")
async def receiver_metrics():
    async with httpx.AsyncClient(timeout=10) as c:
        return (await _get_json(c, f"{RECEIVER_BASE}/metrics"))


@app.get("/api/receiver/metrics/{tc}")
async def receiver_metrics_tc(tc: str):
    async with httpx.AsyncClient(timeout=10) as c:
        return (await _get_json(c, f"{RECEIVER_BASE}/metrics/{tc}"))


@app.post("/api/receiver/reset")
async def receiver_reset():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{RECEIVER_BASE}/reset")
        return r.json()


# ── Test orchestration ────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    repeats: int = 5


@app.post("/api/tests/{tc}/run")
async def start_test_run(tc: str, req: RunRequest):
    if tc not in TC_CONFIG:
        raise HTTPException(400, f"Unknown test case '{tc}'. Use: {', '.join(TC_CONFIG)}.")
    run_id = str(uuid.uuid4())
    _runs[run_id] = {
        "id": run_id,
        "tc": tc,
        "label": TC_CONFIG[tc]["label"],
        "repeats": req.repeats,
        "status": "pending",
        "events": [],
        "started_at": _now_ms(),
        "result": None,
        "error": None,
    }
    # Persist pending row immediately so a browser refresh can see the run
    with _db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO test_runs (run_id, tc, label, repeats, status, started_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (run_id, tc, TC_CONFIG[tc]["label"], req.repeats, _now_ms()),
        )
    asyncio.create_task(_orchestrate_test(run_id, tc, req.repeats))
    return {"run_id": run_id, "tc": tc, "repeats": req.repeats}


@app.get("/api/tests/runs")
async def list_runs():
    return sorted(_runs.values(), key=lambda r: r["started_at"], reverse=True)


@app.get("/api/tests/runs/{run_id}")
async def get_run(run_id: str):
    if run_id not in _runs:
        raise HTTPException(404, "Run not found")
    return _runs[run_id]


@app.get("/api/tests/stream/{run_id}")
async def stream_run(run_id: str):
    """SSE stream for live test run progress."""
    async def generate() -> AsyncGenerator[str, None]:
        last_idx = 0
        yield ": heartbeat\n\n"
        while True:
            if run_id not in _runs:
                yield f"data: {json.dumps({'type': 'error', 'message': 'run not found'})}\n\n"
                return
            run    = _runs[run_id]
            events = run["events"]
            while last_idx < len(events):
                yield f"data: {json.dumps(events[last_idx])}\n\n"
                last_idx += 1
            if run["status"] in ("completed", "failed"):
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _orchestrate_test(run_id: str, tc: str, repeats: int) -> None:
    cfg          = TC_CONFIG[tc]
    asset_id     = cfg["asset_id"]
    receiver_url = cfg["receiver_url"]
    run          = _runs[run_id]
    run["status"] = "running"

    try:
        # ── Access gate: check for existing agreement or approved access request ─
        agreement_id = None
        with _db() as conn:
            # 1. Reuse existing finalized agreement if present
            row = conn.execute(
                "SELECT agreement_id FROM negotiations WHERE asset_id = ? AND state = 'FINALIZED' "
                "ORDER BY updated_at DESC LIMIT 1",
                (asset_id,),
            ).fetchone()
            if row:
                agreement_id = row["agreement_id"]
            else:
                # 2. No agreement — require an approved access request
                access_row = conn.execute(
                    "SELECT request_id FROM access_requests WHERE asset_id = ? AND status = 'approved' "
                    "ORDER BY decided_at DESC LIMIT 1",
                    (asset_id,),
                ).fetchone()
                if not access_row:
                    raise ValueError(
                        f"No active agreement and no approved access for '{asset_id}'. "
                        "Request access in the Catalog and wait for Provider approval before running tests."
                    )

        async with httpx.AsyncClient(timeout=60) as c:

            if agreement_id:
                # ── Reuse existing agreement — skip catalog + negotiate ────────
                _emit(run_id, "phase", phase="catalog",   status="done", skipped=True)
                _emit(run_id, "phase", phase="negotiate", status="done", skipped=True,
                      agreement_id=agreement_id)
            else:
                # ── Phase 1: Catalog discovery ────────────────────────────────
                _emit(run_id, "phase", phase="catalog", status="running")
                catalog = await _post_json(c, f"{CONSUMER_MGMT}/catalog/request", {
                    "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                    "counterPartyAddress": PROVIDER_DSP,
                    "protocol": "dataspace-protocol-http",
                })
                datasets = catalog.get("dcat:dataset", [])
                if not isinstance(datasets, list):
                    datasets = [datasets]

                offer_id = None
                for ds in datasets:
                    if ds.get("@id") == asset_id:
                        policy = ds.get("odrl:hasPolicy", {})
                        if isinstance(policy, list):
                            offer_id = policy[0].get("@id")
                        else:
                            offer_id = policy.get("@id")
                        break

                if not offer_id:
                    raise ValueError(f"No offer found for asset '{asset_id}' in catalog.")
                _emit(run_id, "phase", phase="catalog", status="done", offer_id=offer_id)

                # ── Phase 2: Contract negotiation ─────────────────────────────
                _emit(run_id, "phase", phase="negotiate", status="running")
                neg = await _post_json(c, f"{CONSUMER_MGMT}/contractnegotiations", {
                    "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                    "@type": "ContractRequest",
                    "counterPartyAddress": PROVIDER_DSP,
                    "protocol": "dataspace-protocol-http",
                    "policy": {
                        "@context": "http://www.w3.org/ns/odrl.jsonld",
                        "@id": offer_id,
                        "@type": "Offer",
                        "assigner": "provider",
                        "target": asset_id,
                    },
                })
                neg_id = neg.get("@id")
                _emit(run_id, "phase", phase="negotiate", status="running", neg_id=neg_id)

                for attempt in range(30):
                    await asyncio.sleep(1)
                    status_data = await _get_json(c, f"{CONSUMER_MGMT}/contractnegotiations/{neg_id}")
                    state = status_data.get("state", "UNKNOWN")
                    _emit(run_id, "negotiate_state", state=state, attempt=attempt + 1)
                    if state == "FINALIZED":
                        agreement_id = status_data.get("contractAgreementId")
                        break
                    if state == "TERMINATED":
                        raise ValueError("Contract negotiation was TERMINATED by provider.")

                if not agreement_id:
                    raise ValueError("Negotiation did not reach FINALIZED within 30 s.")
                _emit(run_id, "phase", phase="negotiate", status="done", agreement_id=agreement_id)

            # Reset receiver metrics for a clean run
            await c.post(f"{RECEIVER_BASE}/reset")

            # ── Phase 3: Transfer loop ────────────────────────────────────────
            _emit(run_id, "phase", phase="transfers", status="running", total=repeats)
            transfer_results = []

            for i in range(1, repeats + 1):
                if cfg.get("triggered"):
                    # Fire a deterministic threshold crossing before each
                    # transfer — /tc4/alert-event is single-shot/consumed on
                    # read, so without this the fetch would just see the
                    # "no active alert" placeholder.
                    await c.post(f"{SIMULATOR_URL}/tc4/trigger")

                t_start = time.perf_counter()
                tr = await _post_json(c, f"{CONSUMER_MGMT}/transferprocesses", {
                    "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                    "@type": "TransferRequestDto",
                    "connectorId": "provider",
                    "counterPartyAddress": PROVIDER_DSP,
                    "contractId": agreement_id,
                    "protocol": "dataspace-protocol-http",
                    "transferType": "HttpData-PUSH",
                    "dataDestination": {"type": "HttpData", "baseUrl": receiver_url},
                })
                tr_id = tr.get("@id")
                _emit(run_id, "transfer_start", index=i, transfer_id=tr_id)

                tr_state = "UNKNOWN"
                for _ in range(40):
                    await asyncio.sleep(0.5)
                    ts = await _get_json(c, f"{CONSUMER_MGMT}/transferprocesses/{tr_id}")
                    tr_state = ts.get("state", "UNKNOWN")
                    if tr_state in ("COMPLETED", "TERMINATED"):
                        break

                elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)
                row = {"index": i, "transfer_id": tr_id, "state": tr_state, "elapsed_ms": elapsed_ms}
                transfer_results.append(row)
                _emit(run_id, "transfer_done", **row)

            # ── Phase 4: Collect metrics ──────────────────────────────────────
            _emit(run_id, "phase", phase="metrics", status="running")
            metrics = await _get_json(c, f"{RECEIVER_BASE}/metrics/{tc}")
            _emit(run_id, "phase", phase="metrics", status="done")

            latencies = [r["elapsed_ms"] for r in transfer_results if r["state"] == "COMPLETED"]
            summary = {
                "total_transfers": repeats,
                "completed": len(latencies),
                "failed": repeats - len(latencies),
                "latency_ms_avg":    round(statistics.mean(latencies), 1)   if latencies else None,
                "latency_ms_min":    round(min(latencies), 1)               if latencies else None,
                "latency_ms_max":    round(max(latencies), 1)               if latencies else None,
                "latency_ms_median": round(statistics.median(latencies), 1) if latencies else None,
                "latency_ms_stdev":  round(statistics.stdev(latencies), 1)  if len(latencies) > 1 else 0,
            }

            run["result"] = {
                "agreement_id": agreement_id,
                "transfers": transfer_results,
                "summary": summary,
                "receiver_metrics": metrics,
                "completed_at": _now_ms(),
            }
            run["status"] = "completed"
            _emit(run_id, "completed", summary=summary)
            _save_run_to_db(run_id)

    except Exception as exc:
        run["status"] = "failed"
        run["error"]  = str(exc)
        _emit(run_id, "failed", error=str(exc))
        _save_run_to_db(run_id)


# ── Provider one-shot setup ───────────────────────────────────────────────────

@app.post("/api/provider/setup")
async def provider_setup():
    """Register 3 assets, 1 open policy, and 3 contract definitions on the Provider."""
    results = {}
    async with httpx.AsyncClient(timeout=30) as c:

        assets_to_create = [
            {
                "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                "@id": "asset-tc1-control",
                "properties": {
                    "name": "TC-1 Real-time Control Signal",
                    "description": "Near-real-time control signal from AGV-001 at ~50 Hz",
                    "contenttype": "application/json",
                    "testcase": "TC1",
                },
                "dataAddress": {
                    "type": "HttpData",
                    "baseUrl": f"{SIMULATOR_INTERNAL}/tc1/control-signal",
                    "proxyPath": "false",
                },
            },
            {
                "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                "@id": "asset-tc2-sensors",
                "properties": {
                    "name": "TC-2 High-Frequency Sensor Batch",
                    "description": "1 kHz vibration sensor batch (1000 samples per request)",
                    "contenttype": "application/json",
                    "testcase": "TC2",
                },
                "dataAddress": {
                    "type": "HttpData",
                    "baseUrl": f"{SIMULATOR_INTERNAL}/tc2/sensor-batch",
                    "proxyPath": "false",
                },
            },
            {
                "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                "@id": "asset-tc3-video",
                "properties": {
                    "name": "TC-3 Video Frame",
                    "description": "Simulated 640x480 camera frame (~15 KB compressed)",
                    "contenttype": "application/json",
                    "testcase": "TC3",
                },
                "dataAddress": {
                    "type": "HttpData",
                    "baseUrl": f"{SIMULATOR_INTERNAL}/tc3/video-frame",
                    "proxyPath": "false",
                },
            },
            {
                "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                "@id": "asset-tc4-alert",
                "properties": {
                    "name": "TC-4 Triggered Event Alert",
                    "description": "Single-shot threshold-crossing alert derived from the SensorData rms field",
                    "contenttype": "application/json",
                    "testcase": "TC4",
                },
                "dataAddress": {
                    "type": "HttpData",
                    "baseUrl": (f"{BASYX_AAS_BASE}/submodels/{_sm_b64('urn:ilmatar:crane:sm:SensorData')}"
                                "/submodel-elements/LastAlert/$value")
                               if TC4_SOURCE == "aas" else f"{SIMULATOR_INTERNAL}/tc4/alert-event",
                    "proxyPath": "false",
                },
            },
        ]

        asset_ids = []
        for asset in assets_to_create:
            try:
                resp = await _post_json(c, f"{PROVIDER_MGMT}/assets", asset)
                asset_ids.append(resp.get("@id", asset["@id"]))
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 409:
                    asset_ids.append(asset["@id"])
                else:
                    raise HTTPException(502, f"Failed to create asset {asset['@id']}: {e}")
        results["assets"] = asset_ids

        policy_body = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
                "odrl": "http://www.w3.org/ns/odrl/2/",
            },
            "@id": "policy-open",
            "policy": {
                "@context": "http://www.w3.org/ns/odrl.jsonld",
                "@type": "Set",
                "permission": [],
                "prohibition": [],
                "obligation": [],
            },
        }
        try:
            await _post_json(c, f"{PROVIDER_MGMT}/policydefinitions", policy_body)
            results["policy"] = "policy-open"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                results["policy"] = "policy-open (already existed)"
            else:
                raise HTTPException(502, f"Failed to create policy: {e}")

        def_ids = []
        for asset_id in ["asset-tc1-control", "asset-tc2-sensors", "asset-tc3-video", "asset-tc4-alert"]:
            def_id   = f"def-{asset_id}"
            def_body = {
                "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                "@id": def_id,
                "accessPolicyId":  "policy-open",
                "contractPolicyId": "policy-open",
                "assetsSelector": [
                    {
                        "@type": "Criterion",
                        "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
                        "operator": "=",
                        "operandRight": asset_id,
                    }
                ],
            }
            try:
                await _post_json(c, f"{PROVIDER_MGMT}/contractdefinitions", def_body)
                def_ids.append(def_id)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 409:
                    def_ids.append(f"{def_id} (already existed)")
                else:
                    raise HTTPException(502, f"Failed to create contract def {def_id}: {e}")
        results["contract_definitions"] = def_ids

    return {"status": "ok", **results}


# ── Access-request workflow ───────────────────────────────────────────────────

class AccessRequestBody(BaseModel):
    asset_id:   str
    asset_name: str = ""


@app.post("/api/access/request")
async def create_access_request(body: AccessRequestBody):
    """Consumer requests pre-authorization for an asset."""
    request_id = str(uuid.uuid4())
    with _db() as conn:
        # Upsert: if a pending request already exists for this asset, replace it
        conn.execute(
            """INSERT OR REPLACE INTO access_requests
               (request_id, asset_id, asset_name, status, requested_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (request_id, body.asset_id, body.asset_name, _now_ms()),
        )
    return {"request_id": request_id, "status": "pending", "asset_id": body.asset_id}


@app.get("/api/access/requests")
async def list_access_requests():
    """Return all access requests (used by Provider UI)."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM access_requests ORDER BY requested_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/access/status/{tc}")
async def access_status(tc: str):
    """Return current access + agreement status for a TC (used by TestRunner)."""
    if tc not in TC_CONFIG:
        raise HTTPException(400, f"Unknown tc '{tc}'.")
    asset_id = TC_CONFIG[tc]["asset_id"]
    with _db() as conn:
        access_row = conn.execute(
            "SELECT request_id, status, decided_at FROM access_requests "
            "WHERE asset_id = ? ORDER BY requested_at DESC LIMIT 1",
            (asset_id,),
        ).fetchone()
        agreement_row = conn.execute(
            "SELECT agreement_id, updated_at FROM negotiations "
            "WHERE asset_id = ? AND state = 'FINALIZED' ORDER BY updated_at DESC LIMIT 1",
            (asset_id,),
        ).fetchone()
    return {
        "tc":              tc,
        "asset_id":        asset_id,
        "access_request":  dict(access_row) if access_row else None,
        "access_approved": access_row["status"] == "approved" if access_row else False,
        "agreement_id":    agreement_row["agreement_id"] if agreement_row else None,
        "agreement_at":    agreement_row["updated_at"]   if agreement_row else None,
    }


@app.post("/api/access/{request_id}/approve")
async def approve_access_request(request_id: str):
    with _db() as conn:
        row = conn.execute(
            "SELECT request_id FROM access_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Request not found")
        conn.execute(
            "UPDATE access_requests SET status = 'approved', decided_at = ? WHERE request_id = ?",
            (_now_ms(), request_id),
        )
    return {"request_id": request_id, "status": "approved"}


@app.post("/api/access/{request_id}/reject")
async def reject_access_request(request_id: str):
    with _db() as conn:
        row = conn.execute(
            "SELECT request_id FROM access_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Request not found")
        conn.execute(
            "UPDATE access_requests SET status = 'rejected', decided_at = ? WHERE request_id = ?",
            (_now_ms(), request_id),
        )
    return {"request_id": request_id, "status": "rejected"}


# ── BaSyx AAS proxy ───────────────────────────────────────────────────────────

@app.get("/api/aas/health")
async def aas_health():
    """Check whether the BaSyx AAS Environment is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{BASYX_AAS_BASE}/actuator/health")
            if r.status_code == 200:
                return {"status": "ok", "basyx": r.json()}
            return {"status": "unavailable", "error": f"HTTP {r.status_code}"}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


@app.get("/api/aas/submodels/{tc}/values")
async def aas_submodel_values(tc: str):
    """Return a flat {idShort: value} dict for one of the crane submodels (tc1/tc2/tc3)."""
    if tc not in SM_IDS:
        raise HTTPException(400, f"Unknown tc '{tc}'. Use tc1, tc2, or tc3.")
    sm_b64 = _sm_b64(SM_IDS[tc])
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{BASYX_AAS_BASE}/submodels/{sm_b64}/submodel-elements")
            r.raise_for_status()
            data     = r.json()
            elements = data.get("result", data) if isinstance(data, dict) else data
            if not isinstance(elements, list):
                elements = []
            return {el["idShort"]: el.get("value", "") for el in elements if "idShort" in el}
    except Exception as exc:
        raise HTTPException(503, f"BaSyx unavailable: {exc}")


# ── Provider AAS asset setup ──────────────────────────────────────────────────

@app.post("/api/provider/setup-aas")
async def provider_setup_aas():
    """Register asset-tc4-aas (BaSyx ControlSignal submodel) and its contract definition."""
    sm_ctrl_b64 = _sm_b64(SM_IDS["tc1"])   # ControlSignal — same data domain as TC-1
    results     = {}
    async with httpx.AsyncClient(timeout=30) as c:

        asset = {
            "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
            "@id": "asset-tc4-aas",
            "properties": {
                "name":        "TC-4 AAS Control Signal",
                "description": "Live crane ControlSignal submodel from BaSyx AAS digital twin",
                "contenttype": "application/json",
                "testcase":    "TC4",
            },
            "dataAddress": {
                "type":      "HttpData",
                "baseUrl":   f"{BASYX_AAS_BASE}/submodels/{sm_ctrl_b64}",
                "proxyPath": "false",
            },
        }
        try:
            resp = await _post_json(c, f"{PROVIDER_MGMT}/assets", asset)
            results["asset"] = resp.get("@id", "asset-tc4-aas")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                results["asset"] = "asset-tc4-aas (already existed)"
            else:
                raise HTTPException(502, f"Failed to create AAS asset: {e}")

        def_body = {
            "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
            "@id": "def-asset-tc4-aas",
            "accessPolicyId":   "policy-open",
            "contractPolicyId": "policy-open",
            "assetsSelector": [{
                "@type":       "Criterion",
                "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
                "operator":    "=",
                "operandRight": "asset-tc4-aas",
            }],
        }
        try:
            await _post_json(c, f"{PROVIDER_MGMT}/contractdefinitions", def_body)
            results["contract_def"] = "def-asset-tc4-aas"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                results["contract_def"] = "def-asset-tc4-aas (already existed)"
            else:
                raise HTTPException(502, f"Failed to create contract def: {e}")

    return {"status": "ok", **results}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    with _db() as conn:
        neg_count = conn.execute("SELECT COUNT(*) FROM negotiations").fetchone()[0]
        agr_count = conn.execute("SELECT COUNT(*) FROM agreements").fetchone()[0]
    return {
        "status": "ok",
        "runs_stored": len(_runs),
        "negotiations_stored": neg_count,
        "agreements_stored": agr_count,
    }
