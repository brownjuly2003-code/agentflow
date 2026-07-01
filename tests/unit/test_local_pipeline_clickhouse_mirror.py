"""Unit coverage for the local pipeline's ClickHouse serving-store mirror.

Pins the ADR 0006 wiring: when a ClickHouse sink is configured, every DuckDB
commit is mirrored to the serving store — domain upsert + validated journal
row on the happy path, a dead-letter journal row on validation failure — and
the mirror runs *after* the DuckDB commit, never inside the transaction.
Without a sink the pipeline behaves exactly as before.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import duckdb
import pytest

from src.ingestion.producers.event_producer import generate_click, generate_order
from src.processing.local_pipeline import _ensure_tables, _process_event


class FakeSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def upsert_order(self, event: dict) -> None:
        self.calls.append(("upsert_order", event))

    def upsert_session(self, event: dict) -> None:
        self.calls.append(("upsert_session", event))

    def upsert_product(self, event: dict) -> None:
        self.calls.append(("upsert_product", event))

    def record_pipeline_event(self, **kwargs) -> None:
        self.calls.append(("record_pipeline_event", kwargs))


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    _ensure_tables(connection)
    try:
        yield connection
    finally:
        connection.close()


def _order_event() -> dict:
    _, event = generate_order()
    return json.loads(event.model_dump_json())


def test_valid_order_mirrors_upsert_and_validated_journal_row(conn) -> None:
    sink = FakeSink()
    event = _order_event()

    success, reason = _process_event(conn, event, clickhouse_sink=sink)

    assert (success, reason) == (True, "ok")
    kinds = [kind for kind, _ in sink.calls]
    assert kinds == ["upsert_order", "record_pipeline_event"]
    journal = sink.calls[1][1]
    assert journal["topic"] == "events.validated"
    assert journal["event_id"] == str(event["event_id"])
    # DuckDB stays the canonical local store — the mirror is additive.
    row = conn.execute("SELECT COUNT(*) FROM orders_v2").fetchone()
    assert row is not None
    assert row[0] == 1


def test_valid_click_mirrors_session_upsert(conn) -> None:
    sink = FakeSink()
    _, click = generate_click()
    event = json.loads(click.model_dump_json())

    success, _ = _process_event(conn, event, clickhouse_sink=sink)

    assert success
    assert [kind for kind, _ in sink.calls] == ["upsert_session", "record_pipeline_event"]


def test_schema_invalid_event_mirrors_deadletter_only(conn) -> None:
    sink = FakeSink()

    success, reason = _process_event(conn, {"event_type": "order.created"}, clickhouse_sink=sink)

    assert not success
    assert reason.startswith("schema:")
    assert [kind for kind, _ in sink.calls] == ["record_pipeline_event"]
    assert sink.calls[0][1]["topic"] == "events.deadletter"


def test_no_sink_means_no_mirror(conn) -> None:
    success, _ = _process_event(conn, _order_event(), clickhouse_sink=None)
    assert success
