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


# --- composite keyset cursor (audit 2026-07-17 #1) -----------------------------


def test_min_event_id_renders_composite_keyset_not_inclusive_bound() -> None:
    backend = FakeExternalBackend()
    engine = _engine(backend)

    engine.fetch_pipeline_events(
        min_processed_at="2026-07-10 10:00:00", min_event_id="e0004", limit=1000
    )

    ((sql, params),) = backend.calls
    # Strict keyset PAST (processed_at, event_id), written as the portable
    # OR-decomposition (row-value tuples do not transpile to ClickHouse). This is
    # what lets the scan advance WITHIN a second holding more than one batch of
    # rows; the inclusive `>=` bound alone pins there forever (the cohort-wedge).
    assert params is None
    assert (
        "(processed_at > CAST('2026-07-10 10:00:00' AS TIMESTAMP) "
        "OR (processed_at = CAST('2026-07-10 10:00:00' AS TIMESTAMP) "
        "AND event_id > 'e0004'))"
    ) in sql
    assert ">=" not in sql, "keyset must not fall back to the wedge-prone inclusive bound"
    assert sql.endswith("ORDER BY processed_at ASC, event_id ASC LIMIT 1000")


def test_min_event_id_preserves_sub_second_precision_in_the_keyset() -> None:
    # A DuckDB journal timestamp can carry microseconds; the keyset must compare
    # at full precision, otherwise a saturated second's sub-second rows collapse
    # to one key and re-wedge. (On ClickHouse processed_at is second-granular, so
    # this branch simply never produces a fractional literal there.)
    backend = FakeExternalBackend()
    engine = _engine(backend)

    engine.fetch_pipeline_events(min_processed_at="2026-07-10T10:00:00.123456", min_event_id="e1")

    ((sql, _),) = backend.calls
    assert "CAST('2026-07-10 10:00:00.123456' AS TIMESTAMP)" in sql


def test_min_event_id_without_min_processed_at_is_ignored() -> None:
    # A keyset needs both halves; an event id alone is not a cursor.
    backend = FakeExternalBackend()
    engine = _engine(backend)

    engine.fetch_pipeline_events(min_event_id="e1", limit=10)

    ((sql, _),) = backend.calls
    assert "event_id >" not in sql
    assert "CAST" not in sql


def test_keyset_predicate_transpiles_to_clickhouse() -> None:
    # Two-backend portability guard (audit 2026-07-17 #1): the keyset predicate
    # the external path emits must survive the exact ClickHouseBackend transpile
    # (parse duckdb -> generate clickhouse -> re-parse clickhouse) with table
    # references preserved — the backend's own fail-closed invariant
    # (`_assert_scope_preserved`). A row-value tuple `(a, b) > (x, y)` would not
    # round-trip; this OR-decomposition does. Pins the property in CI so a
    # sqlglot regression can never silently reintroduce the ClickHouse-only wedge.
    import sqlglot
    from sqlglot import exp

    backend = FakeExternalBackend()
    engine = _engine(backend)
    engine.fetch_pipeline_events(min_processed_at="2026-07-10 10:00:00", min_event_id="e0004")
    ((sql, _),) = backend.calls

    statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    assert len(statements) == 1
    translated = statements[0].sql(dialect="clickhouse")
    reparsed = sqlglot.parse_one(translated, read="clickhouse")  # must not raise

    def _refs(node: exp.Expr) -> list[tuple[str, str, str]]:
        return sorted(
            ((t.catalog or "").lower(), (t.db or "").lower(), (t.name or "").lower())
            for t in node.find_all(exp.Table)
        )

    assert _refs(statements[0]) == _refs(reparsed), "transpile changed table references"
    # the keyset survived as an OR of two typed comparisons over event_id
    assert "event_id" in translated
    assert " OR " in translated.upper()
