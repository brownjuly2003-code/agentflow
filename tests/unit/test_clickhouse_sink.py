"""Unit coverage for ``src.processing.clickhouse_sink`` — the serving-store
mirror the local pipeline writes when the configured serving backend is
ClickHouse (ADR 0006).

A fake backend records ``insert_rows``/``execute`` calls, so these tests pin
the upsert *semantics* (append-a-new-version, aggregate recompute, funnel
monotonicity) without a live server; the live path is exercised by the
ClickHouse demo verification (docs/perf) and the compose stack.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.processing.clickhouse_sink import ClickHouseSink


class FakeBackend:
    def __init__(self, execute_results: list[list[dict]] | None = None) -> None:
        self.inserts: list[tuple[str, list[dict]]] = []
        self.executed: list[str] = []
        self._execute_results = list(execute_results or [])
        self.initialized = False

    def initialize_demo_data(self) -> None:
        self.initialized = True

    def insert_rows(self, table_name: str, rows: list[dict]) -> None:
        self.inserts.append((table_name, rows))

    def execute(self, sql: str, params: list | None = None) -> list[dict]:
        del params
        self.executed.append(sql)
        if self._execute_results:
            return self._execute_results.pop(0)
        return []


def _sink(execute_results: list[list[dict]] | None = None) -> tuple[ClickHouseSink, FakeBackend]:
    backend = FakeBackend(execute_results)
    return ClickHouseSink(backend), backend  # type: ignore[arg-type]


def test_sink_bootstraps_demo_data_on_construction() -> None:
    sink, backend = _sink()
    del sink
    assert backend.initialized, (
        "the sink must seed the canonical demo rows so the documented demo "
        "entities exist regardless of bring-up order"
    )


def test_from_serving_config_returns_none_on_duckdb(tmp_path) -> None:
    config = tmp_path / "serving.yaml"
    config.write_text("backend: duckdb\n", encoding="utf-8")
    assert ClickHouseSink.from_serving_config(str(config)) is None


def test_record_pipeline_event_appends_journal_row() -> None:
    sink, backend = _sink()
    processed_at = datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC)
    sink.record_pipeline_event(
        event_id="evt-1",
        topic="events.validated",
        tenant_id="acme",
        event_type="order.created",
        latency_ms=42,
        processed_at=processed_at,
    )
    assert backend.inserts == [
        (
            "pipeline_events",
            [
                {
                    "event_id": "evt-1",
                    "topic": "events.validated",
                    "tenant_id": "acme",
                    "entity_id": None,
                    "event_type": "order.created",
                    "latency_ms": 42,
                    "processed_at": processed_at,
                }
            ],
        )
    ]


def test_upsert_order_appends_version_and_recomputes_user_aggregate() -> None:
    sink, backend = _sink(
        execute_results=[
            [
                {
                    "user_id": "USR-1",
                    "total_orders": "3",  # ClickHouse JSON quotes UInt64
                    "total_spent": "459.97",  # and Decimal aggregates
                    "first_order_at": "2026-01-01 00:00:00",
                    "last_order_at": "2026-07-02 10:00:00",
                }
            ]
        ]
    )
    sink.upsert_order(
        {
            "order_id": "ORD-1",
            "user_id": "USR-1",
            "status": "confirmed",
            "total_amount": "159.99",
            "currency": "USD",
            "timestamp": "2026-07-02T10:00:00+00:00",
        }
    )

    tables = [table for table, _ in backend.inserts]
    assert tables == ["orders_v2", "users_enriched"]
    order_row = backend.inserts[0][1][0]
    assert order_row["order_id"] == "ORD-1"
    assert order_row["total_amount"] == pytest.approx(159.99)
    aggregate_row = backend.inserts[1][1][0]
    assert aggregate_row == {
        "user_id": "USR-1",
        "total_orders": 3,
        "total_spent": pytest.approx(459.97),
        "first_order_at": "2026-01-01 00:00:00",
        "last_order_at": "2026-07-02 10:00:00",
        "preferred_category": None,
    }
    # The recompute must exclude cancelled orders, like the DuckDB path.
    assert "status != 'cancelled'" in backend.executed[0]


def test_upsert_order_with_only_cancelled_orders_skips_aggregate() -> None:
    sink, backend = _sink(execute_results=[[]])
    sink.upsert_order(
        {
            "order_id": "ORD-1",
            "user_id": "USR-1",
            "status": "cancelled",
            "total_amount": 10,
            "timestamp": "2026-07-02T10:00:00+00:00",
        }
    )
    assert [table for table, _ in backend.inserts] == ["orders_v2"]


def test_upsert_session_new_session_inserts_fresh_row() -> None:
    sink, backend = _sink(execute_results=[[]])
    sink.upsert_session(
        {
            "session_id": "SES-1",
            "user_id": "USR-1",
            "_derived": {"page_category": "checkout"},
        }
    )
    ((table, rows),) = backend.inserts
    assert table == "sessions_aggregated"
    row = rows[0]
    assert row["session_id"] == "SES-1"
    assert row["event_count"] == 1
    assert row["funnel_stage"] == "checkout"
    assert row["is_conversion"] is True


def test_upsert_session_existing_bumps_count_and_keeps_furthest_stage() -> None:
    existing = {
        "session_id": "SES-1",
        "user_id": "USR-1",
        "started_at": "2026-07-02 09:00:00",
        "ended_at": None,
        "duration_seconds": None,
        "event_count": "4",  # quoted ints survive the round-trip
        "unique_pages": 3,
        "funnel_stage": "cart",
        "is_conversion": 0,
    }
    sink, backend = _sink(execute_results=[[existing]])
    # A later page view further *down* the funnel must not regress the stage.
    sink.upsert_session(
        {
            "session_id": "SES-1",
            "user_id": "USR-1",
            "_derived": {"page_category": "home"},
        }
    )
    row = backend.inserts[0][1][0]
    assert row["event_count"] == 5
    assert row["funnel_stage"] == "cart"
    assert row["is_conversion"] is False
    assert row["started_at"] == "2026-07-02 09:00:00"


def test_upsert_product_inserts_row() -> None:
    sink, backend = _sink()
    sink.upsert_product(
        {
            "product_id": "PROD-1",
            "name": "Lamp",
            "category": "home",
            "price": "44.99",
            "in_stock": False,
            "stock_quantity": 0,
        }
    )
    ((table, rows),) = backend.inserts
    assert table == "products_current"
    assert rows[0]["price"] == pytest.approx(44.99)
    assert rows[0]["in_stock"] is False
