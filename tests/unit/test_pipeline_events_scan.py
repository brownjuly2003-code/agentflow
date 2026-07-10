"""Unit coverage for ``QueryEngine.fetch_pipeline_events`` on a non-DuckDB
serving backend.

The DuckDB path (schema variants, filters, ordering, guards) is pinned by
``test_stream_router_unit.py`` and ``test_webhook_dispatcher_unit.py`` through
their callers. These tests pin the *external-backend* convention: no ``?``
placeholders (the ClickHouse backend documents ``params`` as a no-op), values
inlined as escaped literals — the same convention the entity/metric mixins use.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.serving.semantic_layer.query import QueryEngine

_ALL_COLUMNS = {
    "event_id",
    "topic",
    "tenant_id",
    "entity_id",
    "event_type",
    "latency_ms",
    "processed_at",
}


class FakeExternalBackend:
    name = "clickhouse"

    def __init__(self, columns: set[str] | None = None) -> None:
        self.columns = _ALL_COLUMNS if columns is None else columns
        self.calls: list[tuple[str, list | None]] = []

    def table_columns(self, table_name: str) -> set[str]:
        del table_name
        return self.columns

    def execute(self, sql: str, params: list | None = None) -> list[dict]:
        self.calls.append((sql, params))
        return []


def _engine(backend: FakeExternalBackend) -> QueryEngine:
    engine = QueryEngine.__new__(QueryEngine)
    engine._backend = backend
    engine._backend_name = backend.name
    # Only `.name` is consulted (to decide the parameter convention).
    engine._duckdb_backend = type("D", (), {"name": "duckdb"})()
    return engine


def test_external_backend_gets_inlined_literals_not_placeholders() -> None:
    backend = FakeExternalBackend()
    engine = _engine(backend)

    engine.fetch_pipeline_events(tenant_id="acme", event_type="custom.thing", entity_id="ORD-1")

    ((sql, params),) = backend.calls
    assert params is None, "ClickHouse documents params as a no-op — never rely on binding"
    assert "?" not in sql
    assert "COALESCE(tenant_id, 'default') = 'acme'" in sql
    assert "event_type = 'custom.thing'" in sql
    assert "entity_id = 'ORD-1'" in sql
    assert sql.endswith("ORDER BY processed_at ASC, event_id ASC")


def test_external_backend_escapes_quotes_in_literals() -> None:
    backend = FakeExternalBackend()
    engine = _engine(backend)

    engine.fetch_pipeline_events(tenant_id="ac'me")

    ((sql, _),) = backend.calls
    assert "'ac''me'" in sql, "a quote in the tenant id must not break out of the literal"


def test_family_filters_and_limit_are_static_sql() -> None:
    backend = FakeExternalBackend()
    engine = _engine(backend)

    engine.fetch_pipeline_events(
        event_type="clickstream", validated_only=True, newest_first=True, limit=10
    )

    ((sql, _),) = backend.calls
    assert "topic = 'events.validated'" in sql
    assert "event_type IN ('click', 'page_view', 'add_to_cart')" in sql
    assert sql.endswith("ORDER BY processed_at DESC, event_id DESC LIMIT 10")


def test_missing_journal_returns_empty_without_query() -> None:
    backend = FakeExternalBackend(columns=set())
    engine = _engine(backend)

    assert engine.fetch_pipeline_events() == []
    assert backend.calls == []


# --- min_processed_at incremental-scan cursor (issue #183) ---------------------


def test_min_processed_at_renders_inclusive_typed_bound() -> None:
    backend = FakeExternalBackend()
    engine = _engine(backend)

    engine.fetch_pipeline_events(min_processed_at="2026-07-10T12:34:56.789", limit=500)

    ((sql, _),) = backend.calls
    # Inclusive, second-floored, typed — the poller's seen-set dedups the
    # re-fetched cursor second.
    assert "processed_at >= CAST('2026-07-10 12:34:56' AS TIMESTAMP)" in sql
    assert sql.endswith("LIMIT 500")


def test_min_processed_at_accepts_datetime_and_floors_microseconds() -> None:
    backend = FakeExternalBackend()
    engine = _engine(backend)

    engine.fetch_pipeline_events(min_processed_at=datetime(2026, 7, 10, 12, 0, 0, 999999))

    ((sql, _),) = backend.calls
    assert "processed_at >= CAST('2026-07-10 12:00:00' AS TIMESTAMP)" in sql


def test_min_processed_at_rejects_free_text_before_any_query() -> None:
    backend = FakeExternalBackend()
    engine = _engine(backend)

    with pytest.raises(ValueError):
        engine.fetch_pipeline_events(min_processed_at="1970-01-01' OR 1=1 --")
    assert backend.calls == [], "an unparseable cursor must never reach the backend"


def test_min_processed_at_rejects_timezone_aware_datetime() -> None:
    backend = FakeExternalBackend()
    engine = _engine(backend)

    with pytest.raises(ValueError):
        engine.fetch_pipeline_events(min_processed_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC))
    assert backend.calls == []


def test_min_processed_at_ignored_when_journal_has_no_time_column() -> None:
    backend = FakeExternalBackend(columns={"event_id", "topic"})
    engine = _engine(backend)

    engine.fetch_pipeline_events(min_processed_at="2026-07-10 12:00:00", limit=50)

    ((sql, _),) = backend.calls
    assert "CAST" not in sql, "no time column to bound on — the scan stays limit-bounded"
    assert sql.endswith("LIMIT 50")
