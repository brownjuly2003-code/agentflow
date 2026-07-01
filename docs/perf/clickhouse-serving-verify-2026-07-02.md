# ClickHouse serving path — live verification (2026-07-02)

**What was verified:** ADR 0006 Phase 1 (+ Phase 1a coherence work) against a
**real ClickHouse server** — not mocks: the config-default engine flip, the
pipeline's ClickHouse sink, ReplacingMergeTree upsert semantics under
`final=1`, and the freshness-critical event scan through the serving backend.

**Stand:** single-binary ClickHouse `26.7.1.368` (official build) running
standalone in WSL Ubuntu 22.04 (no Docker — Windows host), HTTP interface on
`localhost:8123`. API: uvicorn on the working tree,
`AGENTFLOW_AUTH_DISABLED=true`, serving config = the shipped
`config/serving.yaml` (`backend: clickhouse`). Writer:
`python -m src.processing.local_pipeline --burst N` as a **separate process**.

## Results

| Check | Result |
|---|---|
| Sink bootstrap (schema + canonical demo seed) | ✅ database/tables created, `ORD-20260404-1001` present |
| Pipeline burst 60 with `serving_sink=clickhouse` | ✅ 60/60 valid; `orders_v2`=13 rows (8 seed + 5 burst orders), `pipeline_events`=73 |
| `GET /v1/entity/order/ORD-20260404-1001` | ✅ correct row from ClickHouse |
| `GET /v1/metrics/revenue?window=24h` | ✅ 2799.65 computed over ClickHouse data |
| `POST /v1/query` (rule-based NL) | ✅ top-3 products; response showed the **latest row version** for a product updated by the burst (ReplacingMergeTree + `final=1` working through the API) |
| `GET /v1/stream/events?event_type=order` (SSE) | ✅ streamed burst events that exist **only in ClickHouse** — the backend-routed journal scan end-to-end |
| **Cross-process freshness** | ✅ revenue 2799.65 → separate-process burst 40 → **3279.57** on the next read: events written by another process move the served metric |
| ReplacingMergeTree upsert dedup | ✅ same `order_id` written twice (`confirmed`→`shipped`) reads back as exactly 1 row, status `shipped` |
| Webhook/alert dispatcher against ClickHouse | ✅ `api_ready`, 0 dispatcher/scan errors in the API log |
| Tenant-scope transpile assert | ✅ no false positives across all served queries |

## Defect found and fixed by this verification

`ClickHouseBackend._request` set the session database (`?database=agentflow`)
on **every** statement, including the `CREATE DATABASE IF NOT EXISTS`
bootstrap — which fails with `UNKNOWN_DATABASE` on a bare server. Docker
images mask this by pre-creating the database via `CLICKHOUSE_DB`. Fixed
(`use_database=False` on the bootstrap statement) with a regression test
(`test_create_database_bootstrap_does_not_set_session_database`).

## Honest scope notes

- The stand is a single-node, single-writer demo profile; no claim is made
  about multi-writer version ordering (documented single-writer assumption in
  `clickhouse_sink.py`).
- `/v1/health` component checks for Kafka/Flink stay placeholder-unhealthy in
  a single-process bring-up (same as the HF Space demo); the serving backend
  itself answered healthily.
- The freshness numbers in the README (1.06 s p50) are the DuckDB in-process
  benchmark; no equivalent p50/p95 was measured on this stand — this document
  verifies *behavior* (the loop works cross-process on ClickHouse), not a
  latency figure.
