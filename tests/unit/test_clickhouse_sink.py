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


def test_upsert_sessions_one_select_one_insert_for_the_batch() -> None:
    """Q1.4: the batch fold must cost two round-trips total, not two per event."""
    existing = {
        "session_id": "SES-A",
        "user_id": "USR-1",
        "started_at": "2026-07-09 09:00:00",
        "ended_at": None,
        "duration_seconds": None,
        "event_count": "4",
        "unique_pages": 3,
        "funnel_stage": "cart",
        "is_conversion": 0,
    }
    sink, backend = _sink(execute_results=[[existing]])
    sink.upsert_sessions(
        [
            {"session_id": "SES-A", "user_id": "USR-1", "_derived": {"page_category": "home"}},
            {"session_id": "SES-B", "user_id": "USR-2", "_derived": {"page_category": "search"}},
            {"session_id": "SES-A", "user_id": "USR-1", "_derived": {"page_category": "checkout"}},
            {"session_id": "SES-B", "user_id": "USR-2", "_derived": {"page_category": "home"}},
        ]
    )

    assert len(backend.executed) == 1, "one SELECT for the whole batch"
    assert "IN" in backend.executed[0]
    ((table, rows),) = backend.inserts
    assert table == "sessions_aggregated"
    assert len(rows) == 2, "one folded version per session, not one per event"

    by_id = {row["session_id"]: row for row in rows}
    folded_a = by_id["SES-A"]
    # 4 existing + 2 batch events; checkout(4) outranks cart(3); metadata kept.
    assert folded_a["event_count"] == 6
    assert folded_a["funnel_stage"] == "checkout"
    assert folded_a["is_conversion"] is True
    assert folded_a["started_at"] == "2026-07-09 09:00:00"
    assert folded_a["unique_pages"] == 3

    folded_b = by_id["SES-B"]
    # New session: first event *sets* search(1); home(0) must not regress it.
    assert folded_b["event_count"] == 2
    assert folded_b["funnel_stage"] == "search"
    assert folded_b["is_conversion"] is False
    assert folded_b["user_id"] == "USR-2"
    assert folded_b["duration_seconds"] == 0
    assert folded_b["unique_pages"] == 1


def test_upsert_sessions_first_event_sets_stage_even_at_zero_rank() -> None:
    """The first event of a new session assigns its stage with no comparison —
    a fold seeded from 'bounce' would wrongly keep 'bounce' for rank-0 pages."""
    sink, backend = _sink(execute_results=[[]])
    sink.upsert_sessions(
        [{"session_id": "SES-1", "user_id": "USR-1", "_derived": {"page_category": "home"}}]
    )
    ((_, rows),) = backend.inserts
    assert rows[0]["funnel_stage"] == "home"
    assert rows[0]["event_count"] == 1


def test_upsert_sessions_empty_batch_is_a_no_op() -> None:
    sink, backend = _sink()
    sink.upsert_sessions([])
    assert backend.executed == []
    assert backend.inserts == []


def test_refresh_user_aggregates_one_query_for_the_batch() -> None:
    """Q1.4: near-unique users per batch made the per-user recompute the
    dominant term of the apply ceiling — it must be one grouped SELECT now."""
    sink, backend = _sink(
        execute_results=[
            [
                {
                    "user_id": "USR-2",
                    "total_orders": "1",
                    "total_spent": "10.00",
                    "first_order_at": "2026-07-09 10:00:00",
                    "last_order_at": "2026-07-09 10:00:00",
                },
                {
                    "user_id": "USR-1",
                    "total_orders": "3",
                    "total_spent": "459.97",
                    "first_order_at": "2026-01-01 00:00:00",
                    "last_order_at": "2026-07-02 10:00:00",
                },
            ]
        ]
    )
    # USR-3 has only cancelled orders: the grouped SELECT returns no row for it.
    sink.refresh_user_aggregates({"USR-1", "USR-2", "USR-3"})

    assert len(backend.executed) == 1, "one grouped SELECT for the whole user set"
    assert "IN" in backend.executed[0]
    assert "status != 'cancelled'" in backend.executed[0]
    ((table, rows),) = backend.inserts
    assert table == "users_enriched"
    assert [row["user_id"] for row in rows] == ["USR-1", "USR-2"], "deterministic order"
    assert rows[0]["total_orders"] == 3
    assert rows[0]["total_spent"] == pytest.approx(459.97)


def test_refresh_user_aggregates_empty_ids_is_a_no_op() -> None:
    sink, backend = _sink()
    sink.refresh_user_aggregates(set())
    sink.refresh_user_aggregates([""])
    assert backend.executed == []
    assert backend.inserts == []


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
