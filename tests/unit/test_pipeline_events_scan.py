"""Unit coverage for ``QueryEngine.fetch_pipeline_events`` on a non-DuckDB
serving backend.

The DuckDB path (schema variants, filters, ordering, guards) is pinned by
``test_stream_router_unit.py`` and ``test_webhook_dispatcher_unit.py`` through
their callers. These tests pin the *external-backend* convention: no ``?``
placeholders (the ClickHouse backend documents ``params`` as a no-op), values
inlined as escaped literals — the same convention the entity/metric mixins use.
"""

from __future__ import annotations

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
    assert sql.endswith("ORDER BY processed_at DESC LIMIT 10")


def test_missing_journal_returns_empty_without_query() -> None:
    backend = FakeExternalBackend(columns=set())
    engine = _engine(backend)

    assert engine.fetch_pipeline_events() == []
    assert backend.calls == []
