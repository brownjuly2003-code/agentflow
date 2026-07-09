"""Serving bridge: ``events.validated`` (Kafka) → the serving store (S6).

This is the missing link in the product's headline claim. Flink validates,
enriches and dedupes events and sinks them to ``events.validated``
(``src/processing/flink_jobs/stream_processor.py``) — and, until this module,
nothing carried that topic into the store the API serves from. Freshness on the
real path was therefore measurable only as far as the Kafka hop
(``docs/perf/freshness-realpath-2026-06-30.md``).

**Guarantee.** At-least-once delivery plus an idempotent, ``event_id``-keyed
apply. Offsets are committed *after* the batch is applied, so a crash replays
the batch and the journal guard collapses what already landed. We do not claim
Kafka-transactional exactly-once, and could not: Flink builds the
``events.validated`` sink without a ``DeliveryGuarantee`` and its dedup state
expires after ten minutes, so duplicates reach us by design.

**Where it runs.**

* ``SERVING_BACKEND=clickhouse`` (production): a standalone process,
  ``python -m src.processing.bridge_consumer``. ClickHouse is out-of-process and
  multi-writer safe. Keeping the bridge out of the API process is deliberate —
  a sustained writer sharing the API's serialized DuckDB writer is exactly the
  shape that capped throughput at ``1 / commit_latency``
  (``docs/perf/usage-write-bifurcation-2026-07-09.md``).
* ``SERVING_BACKEND=duckdb`` (local demo/tests): a thread inside the API
  process, because the demo store is usually ``:memory:`` and a DuckDB file has
  a single writer — no other process can reach it. Off by default; see
  :func:`start_in_process_bridge`.

**Cache invalidation (S7).** After a successful apply the bridge publishes on
``agentflow:cache:metrics_invalidate`` (and, on the in-process arm, calls
``on_batch_applied``). The API's ``MetricCacheController`` listens for that
push and also keeps an independent journal scan so writers that do not push
(node-ingest, seed) still drop stale metric keys — even when the webhook
dispatcher is not running.
"""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

import duckdb
import structlog

from src.processing.bridge_metrics import (
    APPLY_FAILURES,
    CONSUMER_LAG,
    EVENTS_APPLIED,
    EVENTS_CONSUMED,
    EVENTS_DEADLETTER,
    EVENTS_DUPLICATE,
    SECONDS_SINCE_LAST_APPLY,
    start_metrics_server,
)
from src.processing.clickhouse_sink import ClickHouseSink
from src.processing.local_pipeline import _ensure_tables, _process_event

logger = structlog.get_logger()

VALIDATED_TOPIC = "events.validated"
DEFAULT_GROUP_ID = "agentflow-serving-bridge"

# The event families `_process_event` actually routes to a serving table
# (`src/processing/local_pipeline.py`). Its if/elif chain has no `else`, so an
# event outside this set would get a journal row and *no* upsert — silently
# fresh-looking, actually absent. CDC events can reach `events.validated`
# (Flink sources `cdc.postgres.*`, `cdc.mysql.*`), so the bridge rejects
# anything it cannot actually serve rather than half-applying it. CDC → serving
# is a separate path and an explicit non-goal of S6.
_CANONICAL_PREFIXES = ("order.", "payment.", "product.")
_CANONICAL_TYPES = frozenset({"click", "page_view", "add_to_cart"})


def is_canonical_event_type(event_type: str) -> bool:
    return event_type in _CANONICAL_TYPES or event_type.startswith(_CANONICAL_PREFIXES)


class BatchResult(NamedTuple):
    consumed: int
    applied: int
    duplicates: int
    dead_lettered: int
    applied_event_ids: list[str]


class ServingBridge:
    """Applies validated Kafka events to the serving store, idempotently.

    ``consumer`` is duck-typed on the confluent-kafka ``Consumer`` surface this
    class uses (``consume``, ``commit``, ``assignment``, ``committed``,
    ``get_watermark_offsets``, ``seek``, ``close``) so the unit suite can drive
    it without a broker.

    ``sink`` is the ClickHouse serving sink, or ``None`` on the DuckDB path —
    the same switch ``local_pipeline`` uses. ``lake_conn`` is the DuckDB
    connection ``_process_event`` writes: the serving store itself on the DuckDB
    path, a scratch ``:memory:`` lake on the ClickHouse path.
    """

    def __init__(
        self,
        consumer: Any,
        *,
        sink: ClickHouseSink | None,
        lake_conn: duckdb.DuckDBPyConnection,
        write_lock: threading.Lock | None = None,
        on_batch_applied: Callable[[list[str]], None] | None = None,
        batch_max: int = 256,
        poll_timeout: float = 1.0,
        retry_backoff_seconds: float = 1.0,
        lag_refresh_seconds: float = 10.0,
    ) -> None:
        self._consumer = consumer
        self._sink = sink
        self._lake_conn = lake_conn
        self._write_lock = write_lock
        self._on_batch_applied = on_batch_applied
        self._batch_max = batch_max
        self._poll_timeout = poll_timeout
        self._retry_backoff_seconds = retry_backoff_seconds
        self._lag_refresh_seconds = lag_refresh_seconds
        self._last_apply_monotonic = time.monotonic()
        self._last_lag_refresh = 0.0

    # -- idempotency guard ------------------------------------------------

    def _existing_serving_event_ids(self, event_ids: list[str]) -> set[str]:
        """Ids already carried by the journal of the store the API serves from."""
        if not event_ids:
            return set()
        if self._sink is not None:
            return self._sink.existing_event_ids(event_ids)
        # Static SQL: the batch's ids arrive as one bound LIST parameter rather
        # than a generated run of placeholders, so nothing is interpolated and
        # this query stays out of the reviewed interpolated-SQL surface (A-4).
        rows = self._lake_conn.execute(
            "SELECT DISTINCT event_id FROM pipeline_events "
            "WHERE event_id IN (SELECT unnest(?)) "
            "AND topic IN ('events.validated', 'events.deadletter')",
            [list(event_ids)],
        ).fetchall()
        return {str(row[0]) for row in rows}

    # -- apply ------------------------------------------------------------

    def _apply_batch(self, messages: Sequence[Any]) -> BatchResult:
        events: list[dict] = []
        dead_lettered = 0

        for message in messages:
            EVENTS_CONSUMED.labels(topic=message.topic() or VALIDATED_TOPIC).inc()
            try:
                event = json.loads(message.value().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                EVENTS_DEADLETTER.labels(reason="undecodable").inc()
                dead_lettered += 1
                logger.warning("bridge_event_undecodable", offset=message.offset())
                continue
            if not isinstance(event, dict) or not event.get("event_id"):
                EVENTS_DEADLETTER.labels(reason="missing_event_id").inc()
                dead_lettered += 1
                continue
            if not is_canonical_event_type(str(event.get("event_type", ""))):
                # Reject rather than half-apply: see _CANONICAL_PREFIXES.
                EVENTS_DEADLETTER.labels(reason="non_canonical_event_type").inc()
                dead_lettered += 1
                logger.warning(
                    "bridge_event_type_not_servable",
                    event_id=event.get("event_id"),
                    event_type=event.get("event_type"),
                )
                continue
            events.append(event)

        applied = 0
        duplicates = 0
        applied_event_ids: list[str] = []

        if events:
            batch_ids = [str(event["event_id"]) for event in events]
            seen = self._existing_serving_event_ids(batch_ids)
            for event in events:
                event_id = str(event["event_id"])
                if event_id in seen:
                    # Replay of an already-applied event, or a Flink duplicate
                    # that outlived its 10-minute dedup TTL. Count, do not
                    # re-apply; re-applying would also rewrite the derived
                    # `-status` journal row.
                    EVENTS_DUPLICATE.inc()
                    duplicates += 1
                    continue
                success, reason = self._process(event)
                if success:
                    EVENTS_APPLIED.inc()
                    applied += 1
                    applied_event_ids.append(event_id)
                    seen.add(event_id)
                else:
                    # Flink already validated this; a failure here means the
                    # bridge's schema has drifted from Flink's.
                    EVENTS_DEADLETTER.labels(reason=reason.split(":", 1)[0]).inc()
                    dead_lettered += 1
                    logger.warning("bridge_event_dead_lettered", event_id=event_id, reason=reason)

        if applied:
            self._last_apply_monotonic = time.monotonic()

        return BatchResult(
            consumed=len(messages),
            applied=applied,
            duplicates=duplicates,
            dead_lettered=dead_lettered,
            applied_event_ids=applied_event_ids,
        )

    def _process(self, event: dict) -> tuple[bool, str]:
        # ClickHouse path: skip the throwaway DuckDB scratch (Q1.2 / S10).
        # Dual-write was correctness-preserving but paid BEGIN/COMMIT + local
        # upserts the API never reads. DuckDB demo path keeps the lock + lake.
        skip_local = self._sink is not None
        if self._write_lock is None:
            return _process_event(
                self._lake_conn,
                event,
                clickhouse_sink=self._sink,
                skip_local_store=skip_local,
            )
        with self._write_lock:
            return _process_event(
                self._lake_conn,
                event,
                clickhouse_sink=self._sink,
                skip_local_store=skip_local,
            )

    # -- consume loop -----------------------------------------------------

    def run_once(self) -> BatchResult | None:
        """Poll, apply, commit. Returns ``None`` when the poll came back empty.

        On failure the offsets are left uncommitted *and* the consumer is
        rewound to the batch's first offsets, so the very next poll replays it.
        Without the rewind the in-memory position would have moved past the
        batch and the uncommitted offsets would only matter across a restart.
        """
        messages = self._consumer.consume(num_messages=self._batch_max, timeout=self._poll_timeout)
        messages = [message for message in (messages or []) if not _is_error(message)]
        if not messages:
            self._refresh_gauges()
            return None

        try:
            result = self._apply_batch(messages)
        except Exception:
            APPLY_FAILURES.inc()
            logger.error("bridge_batch_apply_failed", exc_info=True)
            self._rewind(messages)
            time.sleep(self._retry_backoff_seconds)
            return None

        self._consumer.commit(asynchronous=False)
        if result.applied_event_ids:
            # S7 push: always publish so multi-replica API pods drop metric keys.
            # Local ``on_batch_applied`` is optional extra (in-process arm).
            try:
                from src.serving.cache_invalidation import publish_metrics_invalidate

                publish_metrics_invalidate(
                    os.getenv("REDIS_URL", "redis://localhost:6379"),
                    result.applied_event_ids,
                )
            except Exception:  # pragma: no cover - publish is best-effort
                logger.warning("bridge_cache_invalidate_publish_failed", exc_info=True)
            if self._on_batch_applied is not None:
                self._on_batch_applied(result.applied_event_ids)
        logger.info(
            "bridge_batch_applied",
            consumed=result.consumed,
            applied=result.applied,
            duplicates=result.duplicates,
            dead_lettered=result.dead_lettered,
        )
        self._refresh_gauges()
        return result

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        while stop_event is None or not stop_event.is_set():
            try:
                self.run_once()
            except Exception:  # pragma: no cover - loop must outlive one bad poll
                logger.error("bridge_poll_failed", exc_info=True)
                time.sleep(self._retry_backoff_seconds)

    def _rewind(self, messages: Sequence[Any]) -> None:
        first: dict[tuple[str, int], Any] = {}
        for message in messages:
            key = (message.topic(), message.partition())
            if key not in first or message.offset() < first[key].offset():
                first[key] = message
        for message in first.values():
            try:
                from confluent_kafka import TopicPartition

                self._consumer.seek(
                    TopicPartition(message.topic(), message.partition(), message.offset())
                )
            except Exception:  # pragma: no cover - a rebalance can revoke the partition
                logger.warning(
                    "bridge_rewind_failed",
                    topic=message.topic(),
                    partition=message.partition(),
                    exc_info=True,
                )

    def _refresh_gauges(self) -> None:
        SECONDS_SINCE_LAST_APPLY.set(time.monotonic() - self._last_apply_monotonic)
        now = time.monotonic()
        if now - self._last_lag_refresh < self._lag_refresh_seconds:
            return
        self._last_lag_refresh = now
        try:
            assignment = self._consumer.assignment()
            if not assignment:
                return
            committed = self._consumer.committed(assignment, timeout=5.0)
            lag = 0
            for partition in committed:
                _low, high = self._consumer.get_watermark_offsets(
                    partition, timeout=5.0, cached=False
                )
                # offset < 0 means "no committed offset yet" in confluent-kafka.
                position = partition.offset if partition.offset >= 0 else 0
                lag += max(high - position, 0)
            CONSUMER_LAG.set(lag)
        except Exception:  # pragma: no cover - lag is observability, never fatal
            logger.debug("bridge_lag_refresh_failed", exc_info=True)


def _is_error(message: Any) -> bool:
    if message is None:
        return True
    error = message.error()
    if error is None:
        return False
    logger.warning("bridge_consumer_message_error", error=str(error))
    return True


# -- in-process bridge (DuckDB serving backend) ---------------------------


def start_in_process_bridge(
    *,
    lake_conn: duckdb.DuckDBPyConnection,
    bootstrap_servers: str,
    group_id: str = DEFAULT_GROUP_ID,
    topics: Sequence[str] = (VALIDATED_TOPIC,),
    offset_reset: str = "latest",
    on_batch_applied: Callable[[list[str]], None] | None = None,
) -> tuple[ServingBridge, threading.Event, threading.Thread]:
    """Run the bridge as a daemon thread against the API's DuckDB connection.

    Only for the DuckDB serving backend, where a separate process physically
    cannot reach the store. Writes take :data:`SERVING_WRITE_LOCK`, shared with
    the node-ingest endpoint. Default ``offset_reset='latest'``: an in-memory
    demo store is re-seeded on boot, so replaying the topic's backlog into it
    would be noise, not recovery.

    ``on_batch_applied`` is the S7 in-process push seam: the API schedules
    metric-cache invalidation on the event loop without waiting for the journal
    poll. The Redis publish still happens inside ``run_once`` for multi-replica.
    """
    from confluent_kafka import Consumer

    from src.serving.write_lock import SERVING_WRITE_LOCK

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": offset_reset,
        }
    )
    consumer.subscribe(list(topics))
    bridge = ServingBridge(
        consumer,
        sink=None,
        lake_conn=lake_conn,
        write_lock=SERVING_WRITE_LOCK,
        on_batch_applied=on_batch_applied,
    )
    stop_event = threading.Event()
    thread = threading.Thread(
        target=bridge.run_forever,
        args=(stop_event,),
        name="serving-bridge",
        daemon=True,
    )
    thread.start()
    logger.info("in_process_bridge_started", topics=list(topics), group_id=group_id)
    return bridge, stop_event, thread


# -- standalone process (ClickHouse serving backend) ----------------------


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def main() -> int:
    from src.logger import configure_logging
    from src.serving.backends import load_serving_backend_config

    configure_logging()

    backend = load_serving_backend_config()["backend"]
    if backend != "clickhouse":
        # A standalone process cannot open the API's DuckDB store: `:memory:`
        # is unreachable across processes and a DuckDB file admits one writer.
        # Failing loudly beats writing to a store nobody reads.
        logger.error(
            "bridge_requires_clickhouse_backend",
            backend=backend,
            hint=(
                "The standalone bridge serves the ClickHouse backend. On the DuckDB demo, "
                "run it inside the API process with AGENTFLOW_SERVING_BRIDGE_ENABLED=true."
            ),
        )
        return 2

    sink = ClickHouseSink.from_serving_config()
    if sink is None:  # pragma: no cover - guarded by the backend check above
        logger.error("bridge_sink_unavailable")
        return 2

    from confluent_kafka import Consumer

    from src.serving.duckdb_connection import connect_duckdb

    lake_conn = connect_duckdb(":memory:")
    _ensure_tables(lake_conn)

    consumer = Consumer(
        {
            "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            "group.id": os.getenv("AGENTFLOW_BRIDGE_GROUP_ID", DEFAULT_GROUP_ID),
            "enable.auto.commit": False,
            "auto.offset.reset": os.getenv("AGENTFLOW_BRIDGE_OFFSET_RESET", "earliest"),
        }
    )
    consumer.subscribe([VALIDATED_TOPIC])

    start_metrics_server(_env_int("AGENTFLOW_BRIDGE_METRICS_PORT", 9108))

    stop_event = threading.Event()

    def _stop(signum: int, _frame: object) -> None:
        logger.info("bridge_stopping", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    bridge = ServingBridge(
        consumer,
        sink=sink,
        lake_conn=lake_conn,
        batch_max=_env_int("AGENTFLOW_BRIDGE_BATCH_MAX", 256),
    )
    logger.info("bridge_started", topic=VALIDATED_TOPIC, backend=backend)
    try:
        bridge.run_forever(stop_event)
    finally:
        consumer.close()
        lake_conn.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
