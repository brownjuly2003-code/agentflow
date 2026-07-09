"""Unit coverage for the serving bridge (S6).

These tests pin the three properties the design leans on and one it refuses:

* a **Flink-shaped** event (already validated, already enriched, carrying the
  job's private ``_enriched``/``_partition_key`` keys) survives the bridge's
  second pass — this is what makes reusing ``_process_event`` legal;
* the apply is **idempotent by ``event_id``**, which is what turns at-least-once
  delivery into an effectively-once serving state;
* offsets are committed **only after** a batch applies, and a failed batch is
  rewound so the very next poll replays it;
* an event the serving path cannot actually route (CDC) is **rejected**, not
  half-applied — ``_process_event``'s if/elif chain has no ``else``, so it would
  otherwise write a journal row and no serving row.
"""

from __future__ import annotations

import copy
import json
import threading
import uuid
from datetime import UTC, datetime

import duckdb
import pytest

from src.processing.bridge_consumer import ServingBridge, is_canonical_event_type
from src.processing.local_pipeline import _ensure_tables
from src.processing.transformations.enrichment import enrich_order

VALIDATED_TOPIC = "events.validated"


# -- fixtures / doubles ---------------------------------------------------


class _Message:
    def __init__(self, event: dict, *, offset: int = 0, partition: int = 0) -> None:
        self._value = json.dumps(event).encode("utf-8")
        self._offset = offset
        self._partition = partition

    def value(self) -> bytes:
        return self._value

    def error(self) -> None:
        return None

    def topic(self) -> str:
        return VALIDATED_TOPIC

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset


class _FakeConsumer:
    """The slice of confluent-kafka's Consumer the bridge actually calls."""

    def __init__(self, batches: list[list[_Message]]) -> None:
        self._batches = list(batches)
        self.commits = 0
        self.seeks: list = []

    def consume(self, num_messages: int, timeout: float) -> list[_Message]:
        return self._batches.pop(0) if self._batches else []

    def commit(self, asynchronous: bool = False) -> None:
        self.commits += 1

    def seek(self, partition) -> None:
        self.seeks.append((partition.topic, partition.partition, partition.offset))

    def assignment(self) -> list:
        return []


class _RecordingSink:
    """Stands in for ClickHouseSink: records the serving writes it is asked for."""

    def __init__(self, *, journal: set[str] | None = None, raise_on_order: bool = False) -> None:
        self.journal = set(journal or ())
        self.orders: list[dict] = []
        self.pipeline_events: list[dict] = []
        self.insert_orders_calls = 0
        self.journal_batch_calls = 0
        self.session_batches: list[list[dict]] = []
        self.user_refresh_ids: set[str] = set()
        self._raise_on_order = raise_on_order

    def existing_event_ids(self, event_ids: list[str]) -> set[str]:
        return {event_id for event_id in event_ids if event_id in self.journal}

    def upsert_order(self, event: dict, *, refresh_user: bool = True) -> None:
        if self._raise_on_order:
            raise RuntimeError("clickhouse unreachable")
        self.orders.append(event)
        if refresh_user:
            self.user_refresh_ids.add(str(event["user_id"]))

    def insert_orders(self, events: list[dict]) -> None:
        if self._raise_on_order:
            raise RuntimeError("clickhouse unreachable")
        self.insert_orders_calls += 1
        self.orders.extend(events)

    def insert_products(self, events: list[dict]) -> None:  # pragma: no cover
        pass

    def upsert_product(self, event: dict) -> None:  # pragma: no cover - not exercised here
        pass

    def upsert_session(self, event: dict) -> None:  # pragma: no cover - not exercised here
        pass

    def upsert_sessions(self, events: list[dict]) -> None:
        if events:
            self.session_batches.append(events)

    def refresh_user_aggregates(self, user_ids) -> None:
        self.user_refresh_ids.update(str(uid) for uid in user_ids)

    def record_pipeline_event(self, **kwargs) -> None:
        self.pipeline_events.append(kwargs)
        self.journal.add(str(kwargs["event_id"]))

    def record_pipeline_events(self, rows: list[dict]) -> None:
        self.journal_batch_calls += 1
        for row in rows:
            self.pipeline_events.append(row)
            self.journal.add(str(row["event_id"]))


def _flink_shaped_order(event_id: str | None = None, order_id: str | None = None) -> dict:
    """An order exactly as it lands on `events.validated`.

    Flink validates, enriches (so `_derived` is present), then adds `_enriched`
    and `_partition_key` before the Kafka sink — `stream_processor.py`.
    """
    event = {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": "order.created",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "unit-test",
        "order_id": order_id or f"ORD-{datetime.now(UTC).strftime('%Y%m%d')}-9101",
        "user_id": "USR-90101",
        "status": "confirmed",
        "items": [
            {"product_id": "PROD-001", "quantity": 2, "unit_price": "79.99"},
            {"product_id": "PROD-003", "quantity": 1, "unit_price": "49.99"},
        ],
        "total_amount": "209.97",
        "currency": "USD",
    }
    event = enrich_order(event)
    event["_enriched"] = {
        "processing_time": datetime.now(UTC).isoformat(),
        "pipeline_latency_ms": 12,
        "processor_version": "1.0.0",
    }
    event["_partition_key"] = event["user_id"]
    event["tenant"] = "default"
    return event


def _flink_shaped_page_view(session_id: str, page_url: str) -> dict:
    """A clickstream event as Flink sinks it to `events.validated`."""
    from src.processing.transformations.enrichment import enrich_clickstream

    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "page_view",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "unit-test",
        "session_id": session_id,
        "user_id": "USR-90102",
        "page_url": page_url,
        "user_agent": "pytest/1.0",
        "viewport_width": 1280,
    }
    event = enrich_clickstream(event)
    event["_partition_key"] = session_id
    return event


@pytest.fixture
def lake() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    _ensure_tables(conn)
    yield conn
    conn.close()


def _bridge(consumer, *, sink=None, lake_conn=None, **kwargs) -> ServingBridge:
    return ServingBridge(
        consumer,
        sink=sink,
        lake_conn=lake_conn,
        retry_backoff_seconds=0.0,
        **kwargs,
    )


# -- 1. the reuse of _process_event is legal ------------------------------


def test_revalidation_passes_on_flink_enriched_event(lake):
    """Regression pin: this reddens if the event schemas ever adopt
    `extra="forbid"`, which would make Flink's `_enriched`/`_partition_key`
    keys fatal on the bridge's second validation pass."""
    event = _flink_shaped_order()
    consumer = _FakeConsumer([[_Message(event)]])

    result = _bridge(consumer, lake_conn=lake).run_once()

    assert result is not None
    assert (result.applied, result.dead_lettered, result.duplicates) == (1, 0, 0)
    assert consumer.commits == 1

    topic = lake.execute(
        "SELECT topic FROM pipeline_events WHERE event_id = ?", [event["event_id"]]
    ).fetchone()
    assert topic == (VALIDATED_TOPIC,)


def test_reenrichment_is_stable():
    event = _flink_shaped_order()
    once = enrich_order(copy.deepcopy(event))["_derived"]
    twice = enrich_order(enrich_order(copy.deepcopy(event)))["_derived"]
    assert once == twice


# -- 2. at-least-once becomes effectively-once ----------------------------


def test_idempotent_on_duplicate_event_id(lake):
    """The same event delivered twice — a Flink duplicate past its dedup TTL,
    or an offset replay — must apply once."""
    event = _flink_shaped_order(order_id="ORD-20260709-9102")
    consumer = _FakeConsumer([[_Message(event, offset=0)], [_Message(event, offset=1)]])
    bridge = _bridge(consumer, lake_conn=lake)

    first = bridge.run_once()
    second = bridge.run_once()

    assert (first.applied, first.duplicates) == (1, 0)
    assert (second.applied, second.duplicates) == (0, 1)

    journal_rows = lake.execute(
        "SELECT COUNT(*) FROM pipeline_events WHERE event_id = ? AND topic = ?",
        [event["event_id"], VALIDATED_TOPIC],
    ).fetchone()[0]
    order_rows = lake.execute(
        "SELECT COUNT(*) FROM orders_v2 WHERE order_id = ?", [event["order_id"]]
    ).fetchone()[0]
    assert journal_rows == 1
    assert order_rows == 1


def test_guard_reads_the_serving_journal_not_the_scratch_lake(lake):
    """On the ClickHouse path the guard must ask ClickHouse. If it asked the
    bridge's scratch lake, a crash between the local commit and the mirror
    would strand the event: the lake would claim it was applied and the
    serving store would never receive it."""
    event = _flink_shaped_order()
    sink = _RecordingSink(journal={event["event_id"]})
    consumer = _FakeConsumer([[_Message(event)]])

    result = _bridge(consumer, sink=sink, lake_conn=lake).run_once()

    assert (result.applied, result.duplicates) == (0, 1)
    assert sink.orders == []
    # The scratch lake never saw it either — _process_event was not called.
    assert lake.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0] == 0


def test_clickhouse_path_skips_scratch_duckdb_on_apply(lake):
    """Q1.2/Q1.3: CH bridge is ClickHouse-only — lake stays empty."""
    event = _flink_shaped_order()
    sink = _RecordingSink()
    consumer = _FakeConsumer([[_Message(event)]])

    result = _bridge(consumer, sink=sink, lake_conn=lake).run_once()

    assert result.applied == 1
    assert len(sink.orders) == 1
    assert sink.orders[0]["order_id"] == event["order_id"]
    # Journal + status rows land on the sink, never DuckDB.
    assert event["event_id"] in sink.journal
    assert f"{event['event_id']}-status" in sink.journal
    assert lake.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0] == 0
    assert lake.execute("SELECT COUNT(*) FROM orders_v2").fetchone()[0] == 0


def test_clickhouse_batch_one_multi_row_order_insert(lake):
    """Q1.3: many orders → one insert_orders call, aggregates once per user."""
    events = [_flink_shaped_order(order_id=f"ORD-20260709-91{i:02d}") for i in range(5)]
    # Force two distinct users so aggregate refresh is counted.
    events[0]["user_id"] = "USR-A"
    events[1]["user_id"] = "USR-A"
    events[2]["user_id"] = "USR-B"
    events[3]["user_id"] = "USR-B"
    events[4]["user_id"] = "USR-C"
    sink = _RecordingSink()
    consumer = _FakeConsumer([[_Message(e, offset=i) for i, e in enumerate(events)]])

    result = _bridge(consumer, sink=sink, lake_conn=lake).run_once()

    assert result.applied == 5
    assert sink.insert_orders_calls == 1
    assert len(sink.orders) == 5
    assert sink.journal_batch_calls == 1
    # Unique users A,B,C — not 5 per-order aggregate refreshes.
    assert sink.user_refresh_ids == {"USR-A", "USR-B", "USR-C"}
    assert lake.execute("SELECT COUNT(*) FROM orders_v2").fetchone()[0] == 0


def test_clickhouse_batch_folds_sessions_in_one_call(lake):
    """Q1.4: a mixed batch hands *all* its clickstream events to the sink as one
    ``upsert_sessions`` call — the per-event RMW loop is gone."""
    events = [
        _flink_shaped_order(order_id="ORD-20260709-9201"),
        _flink_shaped_page_view("SES-Q14-A", "/products/1"),
        _flink_shaped_page_view("SES-Q14-B", "/checkout"),
        _flink_shaped_page_view("SES-Q14-A", "/cart"),
    ]
    sink = _RecordingSink()
    consumer = _FakeConsumer([[_Message(e, offset=i) for i, e in enumerate(events)]])

    result = _bridge(consumer, sink=sink, lake_conn=lake).run_once()

    assert result.applied == 4
    assert len(sink.session_batches) == 1, "one batched fold, not one RMW per event"
    batch = sink.session_batches[0]
    assert [event["session_id"] for event in batch] == ["SES-Q14-A", "SES-Q14-B", "SES-Q14-A"]
    assert sink.insert_orders_calls == 1
    assert sink.journal_batch_calls == 1


def test_applied_event_ids_feed_the_s7_seam(lake):
    event = _flink_shaped_order()
    consumer = _FakeConsumer([[_Message(event)]])
    seen: list[list[str]] = []

    _bridge(consumer, lake_conn=lake, on_batch_applied=seen.append).run_once()

    assert seen == [[event["event_id"]]]


# -- 3. offsets follow the write, never lead it ---------------------------


def test_offset_committed_only_after_apply(lake):
    event = _flink_shaped_order()
    sink = _RecordingSink(raise_on_order=True)
    consumer = _FakeConsumer([[_Message(event, offset=7)]])

    result = _bridge(consumer, sink=sink, lake_conn=lake).run_once()

    assert result is None
    assert consumer.commits == 0, "a failed batch must not advance the committed offset"
    assert consumer.seeks == [(VALIDATED_TOPIC, 0, 7)], "the batch must be rewound for replay"


def test_write_lock_is_taken_on_the_duckdb_path(lake):
    event = _flink_shaped_order()
    consumer = _FakeConsumer([[_Message(event)]])
    lock = threading.Lock()

    class _TrackingLock:
        def __init__(self) -> None:
            self.entered = 0

        def __enter__(self):
            self.entered += 1
            return lock.__enter__()

        def __exit__(self, *args):
            return lock.__exit__(*args)

    tracking = _TrackingLock()
    _bridge(consumer, lake_conn=lake, write_lock=tracking).run_once()

    assert tracking.entered == 1


# -- 4. what the bridge refuses -------------------------------------------


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("order.created", True),
        ("payment.completed", True),
        ("product.updated", True),
        ("click", True),
        ("page_view", True),
        ("add_to_cart", True),
        ("cdc.postgres.public.orders_v2", False),
        ("", False),
    ],
)
def test_canonical_event_types(event_type: str, expected: bool):
    assert is_canonical_event_type(event_type) is expected


def test_non_canonical_event_type_dead_letters(lake):
    """A CDC event would fall through `_process_event`'s if/elif with no `else`:
    journal row written, serving row absent. Refuse it instead."""
    event = _flink_shaped_order()
    event["event_type"] = "cdc.postgres.public.orders_v2"
    consumer = _FakeConsumer([[_Message(event)]])

    result = _bridge(consumer, lake_conn=lake).run_once()

    assert (result.applied, result.dead_lettered) == (0, 1)
    assert lake.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0] == 0
    assert lake.execute("SELECT COUNT(*) FROM orders_v2").fetchone()[0] == 0
    # The batch is still committed: replaying it would only re-reject it.
    assert consumer.commits == 1


@pytest.mark.parametrize(
    "hostile_event_id",
    [
        "x' OR 1=1 --",
        "x\\' OR 1=1 --",
        "x\\'; DROP TABLE orders_v2; --",
        "x') OR (1=1",
        "x' UNION ALL SELECT 1 --",
        "x\\",
        "x\n OR 1=1",
    ],
)
def test_hostile_event_id_cannot_escape_the_guard_literal(hostile_event_id: str):
    """`ClickHouseSink.existing_event_ids` interpolates event_ids that came off
    Kafka. ClickHouse's `execute(params=...)` is a documented no-op, so the id is
    escaped by `_quote_literal` and re-escaped structurally by the backend
    transpile. Assert that structurally: one statement, one literal in the IN
    list, and the literal round-trips to the payload — a breakout would show up
    as a second statement or an extra predicate."""
    import sqlglot
    from sqlglot import exp

    from src.processing.clickhouse_sink import _quote_literal
    from src.serving.backends.clickhouse_backend import ClickHouseBackend

    backend = ClickHouseBackend.__new__(ClickHouseBackend)
    backend._database = "agentflow"

    sql = (
        "SELECT DISTINCT event_id FROM pipeline_events "
        f"WHERE event_id IN ({_quote_literal(hostile_event_id)}) "
        "AND topic IN ('events.validated', 'events.deadletter')"
    )
    translated = backend._translate_sql(sql)

    statements = sqlglot.parse(translated, dialect="clickhouse")
    assert len(statements) == 1, "payload smuggled in a second statement"

    where = statements[0].find(exp.Where)
    in_clauses = list(where.find_all(exp.In))
    assert len(in_clauses) == 2, "payload smuggled an extra predicate"

    event_id_in = in_clauses[0]
    assert len(event_id_in.expressions) == 1
    literal = event_id_in.expressions[0]
    assert isinstance(literal, exp.Literal)
    assert literal.this == hostile_event_id, "the id did not survive as a single literal"


def test_undecodable_payload_is_dead_lettered_not_fatal(lake):
    class _Corrupt(_Message):
        def value(self) -> bytes:
            return b"{not json"

    consumer = _FakeConsumer([[_Corrupt(_flink_shaped_order())]])

    result = _bridge(consumer, lake_conn=lake).run_once()

    assert (result.applied, result.dead_lettered) == (0, 1)
    assert consumer.commits == 1


def test_schema_invalid_event_is_dead_lettered(lake):
    event = _flink_shaped_order()
    event["total_amount"] = "1.00"  # violates total_matches_items
    consumer = _FakeConsumer([[_Message(event)]])

    result = _bridge(consumer, lake_conn=lake).run_once()

    assert (result.applied, result.dead_lettered) == (0, 1)
    topic = lake.execute(
        "SELECT topic FROM pipeline_events WHERE event_id = ?", [event["event_id"]]
    ).fetchone()
    assert topic == ("events.deadletter",)
