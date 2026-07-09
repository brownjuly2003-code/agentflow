# Serving Bridge — `events.validated` → the serving store

The bridge is the link that makes *event-driven freshness* true on the real
streaming path rather than only on the in-process demo shortcut.

Flink validates, enriches and dedupes events and sinks them to the Kafka topic
`events.validated` (`src/processing/flink_jobs/stream_processor.py`). Until the
bridge existed, nothing carried that topic into the store the API reads: the
serving store only moved when the in-process `local_pipeline` wrote it directly.
Freshness on the real path was therefore measurable no further than the
streaming hop — see [`perf/freshness-realpath-2026-06-30.md`](perf/freshness-realpath-2026-06-30.md).

```
orders.raw ──► Flink (validate → enrich → dedup) ──► events.validated
                                                          │
                                                    serving bridge
                                                          │
                                           ClickHouse / DuckDB serving store
                                                          │
                                                    Agent API (GET /v1/…)
```

## Verified

On the Mac stand (Colima, 6 GiB, single TaskManager, Flink **2.3.0** — the
runtime the repo pins), 2026-07-09:

- An `order.created` produced to `orders.raw` traversed the real Flink job, the
  bridge and ClickHouse, and was served by `GET /v1/entity/order/{id}` **3.26 s
  later** — the first time this path has been closed end to end (S6 live probe).
- **S8 (same day, full distribution):** the same path through to
  `GET /v1/metrics/revenue` measured **3.02 s p50 / 5.70 s p95** (n=20, 1
  warmup miss) with Redis push invalidation active. Report:
  [`perf/freshness-e2e-realpath.md`](perf/freshness-e2e-realpath.md);
  driver: `scripts/benchmark_freshness_e2e.py`.
- The in-process (DuckDB) arm served the same shape of event **1.1 s** after it
  was produced to `events.validated` (not the full produce→metric claim).
- Replaying an already-applied `event_id` against live Kafka + ClickHouse
  produced exactly one order row and one journal row
  (`tests/integration/test_serving_bridge.py`, 2 passed).
- Bridge counters after the S6 probe: `consumed 5 · applied 3 · duplicate 2 ·
  apply_failures 0 · lag 0`. The two duplicates are the guard collapsing
  re-delivered messages, which is what it is for.

> Both arms default to the same consumer group (`agentflow-serving-bridge`).
> Running the standalone process and the in-process thread against one broker
> makes them steal partitions from each other — pick one per cluster, or give
> the second a distinct `AGENTFLOW_BRIDGE_GROUP_ID`.

## Guarantee

**At-least-once delivery plus an idempotent, `event_id`-keyed apply** — which
makes the *state* of the serving store effectively-once.

Offsets are committed only after a batch has been applied. A batch that raises
is rewound to its first offsets, so the next poll replays it rather than
skipping it.

We do **not** claim Kafka-transactional exactly-once, and could not: Flink
builds the `events.validated` sink without a `DeliveryGuarantee`, and its
dedup keyed-state expires after ten minutes. Duplicates reach the bridge by
design — a Flink restart from an earlier offset, or a duplicate separated by
more than the TTL. The bridge is built to collapse them, not to be surprised by
them.

**What makes the apply idempotent** is the journal row. `_process_event` writes
the `pipeline_events` row with `topic='events.validated'` *last*: inside the
same transaction on DuckDB, and as the final mirror write on ClickHouse. Before
applying a batch the bridge asks the serving journal which of the batch's
`event_id`s it has already seen, and skips those.

The guard asks the **serving** store, never the bridge's scratch lake. On the
ClickHouse path the mirror happens after the local commit; a crash in between
must leave the event replayable, and a guard reading the local lake would
instead mark it done forever.

## Where it runs

| Serving backend | Bridge form | Why |
|---|---|---|
| `clickhouse` (production) | standalone process — `python -m src.processing.bridge_consumer` | **Serving store = ClickHouse only.** No DuckDB. Q1.2 dropped scratch lake; **Q1.3** `apply_serving_batch` (multi-row order/journal, user aggregate once per user). Live: ~11.4 eps post-Q1.2, **~22.9 eps post-Q1.3** — see [`perf/throughput-realpath-q13-2026-07-09.md`](perf/throughput-realpath-q13-2026-07-09.md). |
| `duckdb` (local demo / unit tests only) | in-process thread, `AGENTFLOW_SERVING_BRIDGE_ENABLED=true` | **Not production.** Demo and unit tests. Never the S8/S10 real-path store the API reads. |

The HuggingFace three-node demo runs no Kafka at all ([ADR 0012](decisions/0012-three-node-demo-topology.md)); its edges push events to the center over HTTPS. The bridge is absent there by design.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Broker list. |
| `AGENTFLOW_BRIDGE_GROUP_ID` | `agentflow-serving-bridge` | Consumer group. Stable: offsets are the bridge's restart state. |
| `AGENTFLOW_BRIDGE_OFFSET_RESET` | `earliest` | Standalone process. Replaying the topic's backlog is safe — the guard collapses what already landed. |
| `AGENTFLOW_BRIDGE_BATCH_MAX` | `256` | Messages per poll. |
| `AGENTFLOW_BRIDGE_METRICS_PORT` | `9108` | Scrape endpoint; `0` disables it. |
| `AGENTFLOW_SERVING_BRIDGE_ENABLED` | `false` | In-process arm only (DuckDB backend). |

The standalone process refuses to start on a non-ClickHouse backend rather than
writing to a store nobody reads.

## Observability

| Metric | Read it as |
|---|---|
| `agentflow_bridge_consumer_lag` | The health signal. Freshness ≈ lag / throughput. |
| `agentflow_bridge_events_applied_total` | Forward progress. |
| `agentflow_bridge_events_duplicate_total` | Replays and Flink duplicates collapsing. Non-zero is normal. |
| `agentflow_bridge_events_deadletter_total{reason}` | Should be flat at ~0 — Flink already validated these. Sustained growth means schema drift between Flink and the bridge, or a non-canonical event type being routed here. |
| `agentflow_bridge_apply_failures_total` | The sink is refusing writes. Offsets are *not* advancing, so nothing is lost; the batch replays. |
| `agentflow_bridge_seconds_since_last_apply` | Liveness. |

A healthy bridge has partitions assigned, bounded or falling lag, flat
`apply_failures_total`, and flat `deadletter_total`. Rising lag with a flat
`applied_total` means it is stuck writing the sink.

## What the bridge does not do

- **CDC → serving.** `_process_event`'s routing chain covers `order.*`,
  `payment.*`, `product.*` and the clickstream types, with no `else` branch. A
  CDC event would receive a journal row and no serving row — fresh-looking,
  actually absent. The bridge refuses such events into
  `agentflow_bridge_events_deadletter_total{reason="non_canonical_event_type"}`
  instead of half-applying them. Routing CDC into serving is a separate change.
- **Idempotent `sessions_aggregated.event_count` on ClickHouse.** That column is
  a read-modify-write (`old_count + 1`) across non-transactional mirror writes.
  A crash between the session write and the journal marker lets a replay add one
  extra. Orders, products and `users_enriched` are unaffected (the last is a
  full recompute). The clean fix is to derive the count from the deduplicated
  journal rather than increment it; that is a serving-schema change, not a
  bridge change. On DuckDB the marker and the increment share one transaction,
  so the problem does not arise.
- **Global ordering.** Order holds per partition; serving upserts are
  last-write-wins per key, which is what `ReplacingMergeTree` already does.
- **High throughput.** Applying through `_process_event` costs one DuckDB commit
  per event even on the ClickHouse path (the scratch lake). Delivery semantics
  do not depend on it, so the write mechanism can be swapped without re-deciding
  anything here. **Measured (S10, Mac/Colima, 2026-07-09):** bridge apply
  **≈ 8 events/s** sustained after a 400–500 event burst (produce ~500–700
  events/s); peak bridge lag hundreds of messages. Report:
  [`perf/throughput-realpath.md`](perf/throughput-realpath.md).

## Cache invalidation (S7)

Metric-cache drops are **push-driven**, not hostage to the webhook loop.

| Feed | Path | When |
|---|---|---|
| **Push** | After a successful apply the bridge publishes on Redis channel `agentflow:cache:metrics_invalidate` (payload `{"event_ids":[…]}`). Every API pod's `MetricCacheController` is subscribed and runs `QueryCache.invalidate_metrics()`. | Primary path for the bridge (standalone and in-process). |
| **In-process callback** | `ServingBridge(..., on_batch_applied=callback)` — the API schedules a local invalidate on the event loop so the DuckDB arm does not wait for the pub/sub round-trip. | Same-process only. |
| **Journal scan fallback** | `MetricCacheController` polls `QueryEngine.fetch_pipeline_events` independently of `WebhookDispatcher`. | Writers that do not push (node-ingest, seed); also covers `webhook_dispatcher_autostart=False`. |

The historical monkey-patch that wrapped `WebhookDispatcher.dispatch_new_events`
in `main.py` is gone. Webhooks keep their own scan for delivery; cache
invalidation is a first-class controller in `src/serving/cache_invalidation.py`.
