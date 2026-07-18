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
| `clickhouse` (production) | standalone process — `python -m src.processing.bridge_consumer` | **Serving store = ClickHouse only.** No DuckDB. Q1.2 dropped scratch lake; **Q1.3** `apply_serving_batch` (multi-row order/journal, user aggregate once per user); **Q1.4** batches the remaining read-modify-writes (session fold + grouped user recompute) so a batch costs a *constant* number of ClickHouse round-trips, independent of batch size. Live drain: ~11.4 → 22.9 → **87.4 eps** (400-burst, Q1.4) → **107.3 eps** (2000-event drain) — see [`perf/throughput-realpath-q14-2026-07-10.md`](perf/throughput-realpath-q14-2026-07-10.md), [`perf/throughput-realpath-100eps-try-2026-07-17.md`](perf/throughput-realpath-100eps-try-2026-07-17.md). Multi-hour *sustained* ≥100 eps is **not** claimed. |
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
| `agentflow_bridge_apply_batch_size` | Events applied per non-empty batch (histogram). p50 > 1 under sustained load is the constant-round-trips apply path (Q1.3/Q1.4) actually amortizing; p50 = 1 means the bridge outruns the producers (healthy idle). |
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
  a read-modify-write (existing count + the batch's events, folded in one
  version since Q1.4) across non-transactional writes. A crash between the
  session-versions insert and the journal insert lets a replay re-add that
  batch's per-session increments. Orders, products and `users_enriched` are
  unaffected (the last is a full recompute). The clean fix is to derive the
  count from the deduplicated journal rather than increment it; that is a
  serving-schema change, not a bridge change. On DuckDB the marker and the
  increment share one transaction, so the problem does not arise.
- **Global ordering.** Order holds per partition; serving upserts are
  last-write-wins per key, which is what `ReplacingMergeTree` already does.
- **High throughput.** The apply path has been amortized in steps — Q1.2
  dropped the per-event DuckDB scratch commit, Q1.3 made orders/journal
  multi-row, Q1.4 batched the session fold and the user recompute — so a batch
  now costs a constant number of ClickHouse round-trips. Delivery semantics
  never depended on the write mechanism, which is what made those swaps safe.
  **Drain ceiling (Mac/Colima, realpath):** post-Q1.4 **~87.4 eps** on a
  400-event burst (peak lag 0); later **107.3 eps** on a 2000-event drain
  (Flink hop = apply, 0 failures) — numeric ≥100 on a *single catch-up window*
  is observed, not a multi-hour produce rate held above 100.
  History: ~8 → 11.4 (Q1.2) → 22.9 ([`perf/throughput-realpath-q13-2026-07-09.md`](perf/throughput-realpath-q13-2026-07-09.md))
  → 87.4 ([`perf/throughput-realpath-q14-2026-07-10.md`](perf/throughput-realpath-q14-2026-07-10.md))
  → 107.3 drain ([`perf/throughput-realpath-100eps-try-2026-07-17.md`](perf/throughput-realpath-100eps-try-2026-07-17.md))
  → paced 10 min @ 100 produce ≈ **96.5 apply / 97.1 flink**
  ([`perf/throughput-realpath-paced100-2026-07-17.md`](perf/throughput-realpath-paced100-2026-07-17.md))
  → paced **1 h** @ 100 produce ≈ **99.5 apply / 99.5 flink** (0 dups)
  ([`perf/throughput-realpath-paced100-1h-2026-07-17.md`](perf/throughput-realpath-paced100-1h-2026-07-17.md)).
  Multi-hour (4 h+) at ≥100 still open. Endurance: a 4 h soak at ~47 eps
  *delivered* held bounded lag with flat
  RSS/FDs, survived a live broker/Redis fault with an exactly-once batch
  replay, and ended with zero cache drift —
  [`perf/soak-s11-2026-07-10.md`](perf/soak-s11-2026-07-10.md).

## Cache invalidation (S7)

Metric-cache drops are **push-driven**, not hostage to the webhook loop.

| Feed | Path | When |
|---|---|---|
| **Push** | After a successful apply the bridge publishes on Redis channel `agentflow:cache:metrics_invalidate` (payload `{"event_ids":[…]}`). Every API pod's `MetricCacheController` is subscribed and runs `QueryCache.invalidate_metrics()`. | Primary path for the bridge (standalone and in-process). |
| **In-process callback** | `ServingBridge(..., on_batch_applied=callback)` — the API schedules a local invalidate on the event loop so the DuckDB arm does not wait for the pub/sub round-trip. | Same-process only. |
| **Journal scan fallback** | `MetricCacheController` polls `QueryEngine.fetch_pipeline_events` independently of `WebhookDispatcher` — a `newest_first` window of 2000 rows (`journal_scan_fetch`), sized to hold the tail a non-pushing writer can produce between two passes at the ≥100 eps target (~2 physical rows/event pre-merge), so detection stays O(window) and correct however large the journal grows. | Writers that do not push (node-ingest, seed); also covers `webhook_dispatcher_autostart=False`. |

The historical monkey-patch that wrapped `WebhookDispatcher.dispatch_new_events`
in `main.py` is gone. Webhooks keep their own scan for delivery; cache
invalidation is a first-class controller in `src/serving/cache_invalidation.py`.

### Journal scans are bounded (issue #183)

The S11 soak caught the API process at 1.67 GB RSS after 4 h: the webhook
dispatcher's poll re-materialized the **entire** `pipeline_events` journal
every 2 s (unlimited `fetch_pipeline_events`), and the seen-sets that dedup
scans and pushes kept one entry per event forever. All journal consumers are
now bounded:

- **Webhook dispatcher** — incremental cursor scan: each pass fetches at most
  `scan_batch_size` (1000) rows **strictly after** a composite
  `(processed_at, event_id)` keyset cursor, in `processed_at, event_id ASC`
  order. The cursor advances over the contiguous prefix of rows that end the
  pass seen and **freezes at the first row whose durable enqueue failed**, so
  that row is re-fetched and retried next pass — the retry-forever semantics the
  full scan provided. The keyset (not a bare second-granular high-water mark) is
  what lets the frontier advance **within** a single second: an inclusive
  `processed_at >=` cursor floored to the second was re-pinned forever by any
  second holding ≥ `scan_batch_size` rows, silently dropping every later webhook
  for every tenant (audit 2026-07-17 #1). The predicate is the portable
  OR-decomposition `t > ts OR (t = ts AND event_id > id)` — a row-value tuple
  does not transpile to ClickHouse. A strict keyset is only lossless over
  seconds no writer will stamp again — event ids are UUIDs (not monotonic), so
  a frontier inside the still-open second would permanently exclude any
  same-second row that becomes visible later with a lower id. Every dispatcher
  fetch is therefore bounded by a DB-clock **settle watermark**
  (`processed_at <= now() - INTERVAL N SECOND`,
  `AGENTFLOW_WEBHOOK_SETTLE_SECONDS`, default 3 s; `0` disables the bound
  entirely — tests only; must exceed writer stamp-to-visibility lag +
  writer↔DB clock skew — treat the invariant as an operating requirement, not
  a tunable, because a violation still drops the late-visible row behind the
  frontier (it is simply never delivered). That drop is no longer *silent*: a
  cheap sampled runtime detector probes the band immediately behind the frontier
  (`max_processed_at = frontier`, bounded `newest_first` window, once per
  interval — no per-pass cost, no journal-wide scan) for rows the scan never
  marked seen, and raises `agentflow_webhook_settle_violations_total` with a
  `webhook_settle_invariant_violation` warning naming the frontier and a sample
  row. It reads only `fetch_pipeline_events` and the in-memory seen-set, so it
  runs on both the DuckDB and ClickHouse serving stores; it is silent under the
  `0` opt-out. (Residual, documented: membership is tested against the bounded
  seen-set, so an id evicted under an extreme burst within the lookback band, or
  an arrival stamped older than that band, can be missed — the probe is
  read-only and never changes what is delivered.) On a non-UTC DuckDB host the
  session-local frame is non-monotonic across the autumn DST fold: delivery
  of rows stamped inside the fold window is delayed (never dropped) by up to
  the fold width. Worst-case added delivery latency = settle. Startup (`mark_existing_events_seen`) seeds the cursor
  from the newest **settled** batch instead of enumerating the journal —
  unsettled rows deliver once settled (a restart race is not lost; the durable
  enqueue's idempotent key suppresses re-POSTs); the seen-set is now a
  secondary safety net, with the keyset as the primary dedup. Delivery
  *outcomes* are idempotent per round too: `record_webhook_delivery_outcome`
  carries that round's `delivery_id` and records it on the queue row
  (`last_outcome_id`), so a repeat of the outcome write no-ops instead of
  bumping `attempts` a second time. This closes attempts+2 → premature
  dead-letter, where the PostgreSQL adapter's transient-error retry re-applied a
  failure whose UPDATE had committed but whose commit-ack was lost.
- **Seen-sets** — `BoundedSeenSet` (`src/serving/seen_events.py`): capped,
  FIFO-with-refresh eviction. Eviction is safe because webhook enqueue is
  idempotent on its primary key (inline delivery fires only for freshly
  inserted rows) and a redundant metric-cache invalidate just repopulates on
  the next read.
- **Cache scan fallback** — the lifespan used to wire an *ascending* limited
  scan: the oldest rows, a window that stops changing once the journal
  outgrows it, which silently disabled scan-driven invalidation on grown
  journals (push kept the soak honest). `journal_scan_fetch` reads the tail
  window instead, and it is sized (`DEFAULT_SCAN_WINDOW_ROWS = 2000`) to hold a
  full ≥100 eps burst between two passes rather than clip it.
- **SSE stream** (`/v1/stream/events`) — the per-connection dedup cache is a
  `BoundedSeenSet` too (was a bare set growing one entry per distinct event
  for the connection's lifetime). Eviction cannot re-emit: the scan window is
  the newest `limit` (10) rows, so an id leaves the window thousands of
  distinct events before it leaves the cache.

Unit-scale measurement (DuckDB backend, same mechanism): one dispatcher scan
allocated 35.5 → 283.6 MB as the journal grew 50 k → 400 k rows before the
fix, flat ≤ 0.8 MB after; live stand re-verification is scheduled for the next
stand window.
