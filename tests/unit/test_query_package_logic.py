"""Unit coverage for the query package mixins behind the per-package CI gate.

The query package (engine, entity_queries, metric_queries, nl_queries,
sql_builder) is the NL->SQL orchestration surface and a mutmut target, so its
branches — error mapping, literal-vs-parameter SQL building, cursor handling,
tenant qualification — need direct unit coverage. Uses the same minimal-host
pattern as test_query_engine_mixin_contracts.py: a Mock backend, no Docker.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from src.serving.backends import BackendExecutionError, BackendMissingTableError
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query.entity_queries import EntityQueryMixin
from src.serving.semantic_layer.query.metric_queries import MetricQueryMixin
from src.serving.semantic_layer.query.nl_queries import NLQueryMixin, UnsafeNLQueryError
from src.serving.semantic_layer.query.sql_builder import SQLBuilderMixin

AWARE_TS = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)


class _Host(
    SQLBuilderMixin,
    NLQueryMixin,
    EntityQueryMixin,
    MetricQueryMixin,
):
    def __init__(self, backend_name: str = "duckdb") -> None:
        self.catalog = DataCatalog()
        self._tenant_router = Mock()
        self._tenant_router.has_config.return_value = False
        self._tenant_router.get_duckdb_schema.return_value = None
        self._backend = Mock()
        self._backend.name = backend_name
        self._backend_name = backend_name
        self._duckdb_backend = Mock()
        self._duckdb_backend.name = "duckdb"
        self._qualified_table_cache: dict[tuple[str, str | None], str] = {}
        self._columns_by_table: dict[str, set[str]] = {}

    def _table_columns(self, table_name: str) -> set[str]:
        return self._columns_by_table.get(table_name, set())

    def _translate_question_to_sql(
        self,
        question: str,
        tenant_id: str | None = None,
    ) -> str:
        del question, tenant_id
        return "SELECT order_id FROM orders_v2"


@pytest.fixture
def host() -> _Host:
    return _Host()


@pytest.fixture
def literal_host() -> _Host:
    # A backend whose name differs from the DuckDB backend forces the
    # quoted-literal SQL building branches instead of `?` query params.
    return _Host(backend_name="clickhouse")


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------


def test_engine_health_read_connection_and_idempotent_close() -> None:
    from src.serving.semantic_layer.query.engine import QueryEngine

    engine = QueryEngine(catalog=DataCatalog(), db_path=":memory:")
    try:
        assert isinstance(engine.health(), dict)
        with engine._read_connection() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
    finally:
        engine.close()
    # Second close must hit the early-return guard, not re-close the
    # connection.
    engine.close()
    assert engine._closed is True


def test_engine_initializes_demo_data_on_non_duckdb_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.serving.semantic_layer.query.engine as engine_module

    promoted = Mock()
    promoted.name = "clickhouse"
    monkeypatch.setattr(engine_module, "create_backend", lambda duckdb_backend: promoted)

    engine = engine_module.QueryEngine(catalog=DataCatalog(), db_path=":memory:")
    try:
        # A backend other than the DuckDB one must get its own demo-data
        # initialization call.
        promoted.initialize_demo_data.assert_called_once_with()
        assert engine._backend_name == "clickhouse"
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# sql_builder
# ---------------------------------------------------------------------------


def test_quote_literal_covers_every_type_branch(host: _Host) -> None:
    assert host._quote_literal(None) == "NULL"
    assert host._quote_literal(True) == "TRUE"
    assert host._quote_literal(False) == "FALSE"
    assert host._quote_literal(7) == "7"
    assert host._quote_literal(2.5) == "2.5"
    assert host._quote_literal(datetime(2026, 4, 1, 12, 30, 15)) == "'2026-04-01 12:30:15'"
    assert host._quote_literal("O'Brien") == "'O''Brien'"


def test_get_tenant_schema_rejects_non_identifier_schema(host: _Host) -> None:
    host._tenant_router.get_duckdb_schema.return_value = "bad-schema;"

    with pytest.raises(ValueError, match="Invalid DuckDB schema"):
        host._get_tenant_schema("tenant_a")


def test_qualify_table_returns_cached_qualified_name(host: _Host) -> None:
    host._qualified_table_cache[("orders_v2", "tenant_a")] = '"cached"."orders_v2"'

    assert host._qualify_table("orders_v2", "tenant_a") == '"cached"."orders_v2"'
    host._tenant_router.get_duckdb_schema.assert_not_called()


def test_qualify_table_requires_tenant_for_tenant_scoped_table(host: _Host) -> None:
    host._tenant_router.has_config.return_value = True
    host._tenant_router.get_duckdb_schema.return_value = None
    tenant = Mock()
    tenant.duckdb_schema = "tenant_a"
    host._tenant_router.load.return_value = Mock(tenants=[tenant])
    host._columns_by_table['"tenant_a"."orders_v2"'] = {"order_id"}

    with pytest.raises(ValueError, match="Tenant context is required"):
        host._qualify_table("orders_v2", None)


def test_qualify_table_rejects_non_identifier_schema(host: _Host) -> None:
    host._tenant_router.get_duckdb_schema.return_value = "drop table;"

    with pytest.raises(ValueError, match="Invalid DuckDB schema"):
        host._qualify_table("orders_v2", "tenant_a")


def test_qualify_table_qualifies_and_caches_tenant_schema(host: _Host) -> None:
    host._tenant_router.get_duckdb_schema.return_value = "tenant_a"

    qualified = host._qualify_table("orders_v2", "tenant_a")

    assert qualified == '"tenant_a"."orders_v2"'
    assert host._qualified_table_cache[("orders_v2", "tenant_a")] == qualified


def test_scope_sql_without_schema_still_validates_known_tables(host: _Host) -> None:
    # The schema-None branch must still call _qualify_table for each known
    # unqualified table (tenant-context enforcement), then return sql as-is.
    # Without tenant config the resolved tenant falls back to "demo".
    # unknown_table is not in the catalog, so the loop must skip it.
    sql = "SELECT * FROM orders_v2, unknown_table"

    assert host._scope_sql(sql, None) == sql
    assert ("orders_v2", "demo") in host._qualified_table_cache
    assert ("unknown_table", "demo") not in host._qualified_table_cache


# ---------------------------------------------------------------------------
# metric_queries
# ---------------------------------------------------------------------------


def test_get_metric_unknown_metric_returns_zero(host: _Host) -> None:
    assert host.get_metric("nonexistent") == {"value": 0, "unit": "unknown"}
    host._backend.scalar.assert_not_called()


def test_get_metric_literal_backend_inlines_as_of_anchor(literal_host: _Host) -> None:
    literal_host._backend.scalar.return_value = 42.0

    result = literal_host.get_metric("revenue", as_of=AWARE_TS)

    assert result == {"value": 42.0, "unit": "RUB"}
    sql = literal_host._backend.scalar.call_args.args[0]
    assert "NOW()" not in sql
    assert sql.count("AS TIMESTAMP") == 2  # anchor substitution + upper bound
    assert "created_at <= CAST(" in sql


def test_get_metric_missing_table_maps_to_value_error(host: _Host) -> None:
    host._backend.scalar.side_effect = BackendMissingTableError(
        "Table orders_v2 not found", table_name="orders_v2"
    )

    with pytest.raises(ValueError, match="not materialized yet"):
        host.get_metric("revenue")


def test_get_metric_execution_error_maps_to_value_error(host: _Host) -> None:
    host._backend.scalar.side_effect = BackendExecutionError("boom")

    with pytest.raises(ValueError, match="Metric query failed"):
        host.get_metric("revenue")


# ---------------------------------------------------------------------------
# entity_queries — get_entity
# ---------------------------------------------------------------------------


def test_get_entity_unknown_type_returns_none(host: _Host) -> None:
    assert host.get_entity("nonexistent", "X-1") is None
    host._backend.execute.assert_not_called()


def test_get_entity_literal_backend_quotes_entity_id(literal_host: _Host) -> None:
    literal_host._backend.execute.return_value = []

    assert literal_host.get_entity("order", "ORD'1") is None
    sql = literal_host._backend.execute.call_args.args[0]
    assert "'ORD''1'" in sql
    assert len(literal_host._backend.execute.call_args.args) == 1


def test_get_entity_missing_table_maps_to_value_error(host: _Host) -> None:
    host._backend.execute.side_effect = BackendMissingTableError("no table")

    with pytest.raises(ValueError, match="not materialized yet"):
        host.get_entity("order", "ORD-1")


def test_get_entity_execution_error_maps_to_value_error(host: _Host) -> None:
    host._backend.execute.side_effect = BackendExecutionError("boom")

    with pytest.raises(ValueError, match="Entity lookup failed"):
        host.get_entity("order", "ORD-1")


def test_get_entity_normalizes_datetime_last_updated(host: _Host) -> None:
    host._backend.execute.return_value = [{"order_id": "ORD-1", "updated_at": AWARE_TS}]

    result = host.get_entity("order", "ORD-1")

    assert result is not None
    assert result["_last_updated"] == AWARE_TS.isoformat()


def test_get_entity_parses_string_timestamp_and_skips_bad_candidates(host: _Host) -> None:
    # updated_at is an unparseable string -> the loop must `continue` to the
    # next candidate instead of failing the lookup.
    host._backend.execute.return_value = [
        {
            "order_id": "ORD-1",
            "updated_at": "not-a-timestamp",
            "created_at": "2026-04-01T12:00:00+00:00",
        }
    ]

    result = host.get_entity("order", "ORD-1")

    assert result is not None
    assert result["_last_updated"] == AWARE_TS.isoformat()


# ---------------------------------------------------------------------------
# entity_queries — get_entity_at
# ---------------------------------------------------------------------------


def _enable_pipeline_history(host: _Host, *, with_entity_type: bool = True) -> None:
    columns = {"entity_id", "entity_data", "processed_at"}
    if with_entity_type:
        columns.add("entity_type")
    host._columns_by_table["pipeline_events"] = columns


def test_get_entity_at_unknown_type_returns_none(host: _Host) -> None:
    assert host.get_entity_at("nonexistent", "X-1", as_of=AWARE_TS) is None


def test_get_entity_at_literal_backend_inlines_history_filters(literal_host: _Host) -> None:
    _enable_pipeline_history(literal_host)
    literal_host._backend.execute.return_value = [
        {"entity_data": '{"order_id": "ORD-1"}', "event_time": "2026-04-01 10:00:00"}
    ]

    result = literal_host.get_entity_at("order", "ORD-1", as_of=AWARE_TS)

    assert result is not None
    # event_time is not a datetime -> normalized time falls back to as_of.
    assert result["_last_updated"] == AWARE_TS.isoformat()
    sql = literal_host._backend.execute.call_args.args[0]
    assert "entity_type = 'order'" in sql
    assert "entity_id = 'ORD-1'" in sql
    assert len(literal_host._backend.execute.call_args.args) == 1


def test_get_entity_at_decodes_bytes_payload(host: _Host) -> None:
    _enable_pipeline_history(host)
    host._backend.execute.return_value = [
        {"entity_data": b'{"order_id": "ORD-1"}', "event_time": AWARE_TS}
    ]

    result = host.get_entity_at("order", "ORD-1", as_of=AWARE_TS)

    assert result is not None
    assert result["order_id"] == "ORD-1"
    assert result["_last_updated"] == AWARE_TS.isoformat()


def test_get_entity_at_invalid_json_payload_maps_to_value_error(host: _Host) -> None:
    _enable_pipeline_history(host)
    host._backend.execute.return_value = [{"entity_data": "{not json", "event_time": AWARE_TS}]

    with pytest.raises(ValueError, match="invalid JSON"):
        host.get_entity_at("order", "ORD-1", as_of=AWARE_TS)


def test_get_entity_at_history_execution_error_maps_to_value_error(host: _Host) -> None:
    _enable_pipeline_history(host)
    host._backend.execute.side_effect = BackendExecutionError("boom")

    with pytest.raises(ValueError, match="Historical entity lookup failed"):
        host.get_entity_at("order", "ORD-1", as_of=AWARE_TS)


def test_get_entity_at_returns_none_without_time_column(host: _Host) -> None:
    # No usable pipeline_events columns and no timestamp column on the entity
    # table -> the fallback lookup cannot anchor history and returns None.
    host._columns_by_table["orders_v2"] = {"order_id", "status"}

    assert host.get_entity_at("order", "ORD-1", as_of=AWARE_TS) is None
    host._backend.execute.assert_not_called()


def test_get_entity_at_table_fallback_param_branch(host: _Host) -> None:
    host._columns_by_table["orders_v2"] = {"order_id", "updated_at"}
    host._backend.execute.return_value = [{"order_id": "ORD-1", "updated_at": AWARE_TS}]

    result = host.get_entity_at("order", "ORD-1", as_of=AWARE_TS)

    assert result is not None
    assert result["_last_updated"] == AWARE_TS.isoformat()
    sql, params = host._backend.execute.call_args.args
    assert "updated_at <= CAST(? AS TIMESTAMP)" in sql
    assert params[0] == "ORD-1"


def test_get_entity_at_table_fallback_literal_branch(literal_host: _Host) -> None:
    literal_host._columns_by_table["orders_v2"] = {"order_id", "updated_at"}
    literal_host._backend.execute.return_value = []

    assert literal_host.get_entity_at("order", "ORD-1", as_of=AWARE_TS) is None
    sql = literal_host._backend.execute.call_args.args[0]
    assert "'ORD-1'" in sql
    assert "updated_at <= CAST(" in sql


def test_get_entity_at_table_fallback_missing_table_maps_to_value_error(host: _Host) -> None:
    host._columns_by_table["orders_v2"] = {"order_id", "updated_at"}
    host._backend.execute.side_effect = BackendMissingTableError("no table")

    with pytest.raises(ValueError, match="not materialized yet"):
        host.get_entity_at("order", "ORD-1", as_of=AWARE_TS)


def test_get_entity_at_table_fallback_execution_error_maps_to_value_error(host: _Host) -> None:
    host._columns_by_table["orders_v2"] = {"order_id", "updated_at"}
    host._backend.execute.side_effect = BackendExecutionError("boom")

    with pytest.raises(ValueError, match="Historical entity lookup failed"):
        host.get_entity_at("order", "ORD-1", as_of=AWARE_TS)


# ---------------------------------------------------------------------------
# nl_queries — translation
# ---------------------------------------------------------------------------


class _TranslatingHost(_Host):
    # Use the real NLQueryMixin._translate_question_to_sql instead of the stub.
    _translate_question_to_sql = NLQueryMixin._translate_question_to_sql


def test_translate_question_returns_rule_based_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.serving.semantic_layer.nl_engine as nl_engine

    host = _TranslatingHost()
    monkeypatch.setattr(
        nl_engine, "translate_nl_to_sql", lambda question, catalog: "SELECT * FROM orders_v2"
    )

    assert host._translate_question_to_sql("show orders") == "SELECT * FROM orders_v2"


def test_translate_question_untranslatable_raises_with_catalog_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.serving.semantic_layer.nl_engine as nl_engine

    host = _TranslatingHost()
    monkeypatch.setattr(nl_engine, "translate_nl_to_sql", lambda question, catalog: "")

    with pytest.raises(ValueError, match="Could not translate question"):
        host._translate_question_to_sql("gibberish")


# ---------------------------------------------------------------------------
# nl_queries — cursors and pagination
# ---------------------------------------------------------------------------


def test_decode_cursor_roundtrip(host: _Host) -> None:
    cursor = host._encode_cursor(100, "abc123")

    assert host._decode_cursor(cursor) == (100, "abc123")


@pytest.mark.parametrize(
    "cursor",
    [
        "%%%not-base64%%%",
        "bm8tY29sb24",  # decodes to "no-colon"
        "LTU6aGFzaA==",  # decodes to "-5:hash" (negative offset)
        "NTo=",  # decodes to "5:" (empty query hash)
    ],
)
def test_decode_cursor_rejects_malformed_values(host: _Host, cursor: str) -> None:
    with pytest.raises(ValueError, match="Invalid cursor value"):
        host._decode_cursor(cursor)


def test_paginated_query_rejects_out_of_range_limit(host: _Host) -> None:
    with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
        host.paginated_query("show orders", limit=0)


def test_paginated_query_first_page_and_cursor_continuation(host: _Host) -> None:
    rows = [{"order_id": f"ORD-{i}"} for i in range(3)]
    host._backend.execute.return_value = rows
    host._backend.scalar.return_value = 5

    page = host.paginated_query("show orders", limit=2)

    assert page["row_count"] == 2
    assert page["has_more"] is True
    assert page["total_count"] == 5
    assert page["next_cursor"] is not None
    page_sql = host._backend.execute.call_args.args[0]
    assert "LIMIT 3 OFFSET 0" in page_sql

    host._backend.execute.return_value = rows[2:]
    second = host.paginated_query("show orders", limit=2, cursor=page["next_cursor"])

    assert second["has_more"] is False
    assert second["next_cursor"] is None
    assert "OFFSET 2" in host._backend.execute.call_args.args[0]


def test_paginated_query_rejects_cursor_for_different_query(host: _Host) -> None:
    stale_cursor = host._encode_cursor(2, "different-query-hash")

    with pytest.raises(ValueError, match="Cursor does not match"):
        host.paginated_query("show orders", limit=2, cursor=stale_cursor)


def test_paginated_query_caps_total_count_above_bound(host: _Host) -> None:
    host._backend.execute.return_value = [{"order_id": "ORD-1"}]
    host._backend.scalar.return_value = 10_001

    page = host.paginated_query("show orders", limit=2)

    assert page["total_count"] is None
    assert page["has_more"] is False


def test_paginated_query_execution_error_maps_to_value_error(host: _Host) -> None:
    host._backend.execute.side_effect = BackendExecutionError("boom")

    with pytest.raises(ValueError, match="Query execution failed"):
        host.paginated_query("show orders", limit=2)


def test_execute_nl_query_execution_error_maps_to_value_error(host: _Host) -> None:
    host._backend.execute.side_effect = BackendExecutionError("boom")

    with pytest.raises(ValueError, match="Query execution failed"):
        host.execute_nl_query("show orders")


def test_execute_nl_query_rejects_unsafe_translation(host: _Host) -> None:
    host._translate_question_to_sql = lambda question, tenant_id=None: "DROP TABLE orders_v2"  # type: ignore[method-assign]

    with pytest.raises(UnsafeNLQueryError, match="unsafe query"):
        host.execute_nl_query("drop everything")


# ---------------------------------------------------------------------------
# nl_queries — explain
# ---------------------------------------------------------------------------


def test_explain_reports_llm_engine_when_gracekelly_configured(
    host: _Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.serving.semantic_layer.nl_engine as nl_engine

    monkeypatch.setattr(nl_engine, "_GRACEKELLY_URL", "http://gracekelly.test")
    monkeypatch.setitem(sys.modules, "httpx", types.ModuleType("httpx"))
    host._backend.explain.return_value = [("physical_plan", "SEQ_SCAN ~10 rows")]

    result = host.explain("show orders")

    assert result["engine"] == "llm"
    assert result["tables_accessed"] == ["orders_v2"]
    assert result["estimated_rows"] == 10
    assert result["warning"] == "Full table scan on orders_v2 (no index)"


def test_explain_execution_error_maps_to_value_error(host: _Host) -> None:
    host._backend.explain.side_effect = BackendExecutionError("boom")

    with pytest.raises(ValueError, match="Query explanation failed"):
        host.explain("show orders")


def test_explain_stays_rule_based_when_httpx_import_fails(
    host: _Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.serving.semantic_layer.nl_engine as nl_engine

    monkeypatch.setattr(nl_engine, "_GRACEKELLY_URL", "http://gracekelly.test")
    # A None entry in sys.modules makes `import httpx` raise ImportError.
    monkeypatch.setitem(sys.modules, "httpx", None)  # type: ignore[arg-type]
    host._backend.explain.return_value = [("physical_plan", "PROJECTION")]

    result = host.explain("show orders")

    assert result["engine"] == "rule_based"


def test_explain_falls_back_to_regex_when_sqlglot_parse_fails(
    host: _Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlglot

    host._backend.explain.return_value = [("physical_plan", "PROJECTION")]
    # _scope_sql parses the SQL before explain does; stub it so only explain's
    # own sqlglot.parse_one call sees the failure and takes the regex fallback.
    monkeypatch.setattr(host, "_scope_sql", lambda sql, tenant_id: sql)

    def _boom(sql: str, read: str | None = None) -> None:
        raise sqlglot.errors.ParseError("unparseable")

    monkeypatch.setattr(sqlglot, "parse_one", _boom)

    # This test exercises explain's OWN parse_one regex fallback (validate_nl_sql
    # uses sqlglot.parse, not parse_one, so it is unaffected by the monkeypatch).
    result = host.explain("show orders", tenant_id="internal-analytics")

    assert result["tables_accessed"] == ["orders_v2"]
    assert result["warning"] is None
