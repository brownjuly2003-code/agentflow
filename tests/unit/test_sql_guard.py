from unittest.mock import Mock

import pytest

from src.serving.semantic_layer.query_engine import QueryEngine
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.sql_guard import UnsafeSQLError, validate_nl_sql

ALLOWED_TABLES = {
    "orders_v2",
    "products_current",
    "sessions_aggregated",
    "users_enriched",
    "pipeline_events",
}

SAFE_SQL = [
    "SELECT * FROM orders_v2",
    "SELECT COUNT(*) FROM orders_v2 WHERE status = 'delivered'",
    "WITH recent AS (SELECT * FROM orders_v2) SELECT * FROM recent",
]

UNSAFE_SQL = [
    ("DROP TABLE orders_v2", "Statement type"),
    ("INSERT INTO orders_v2 VALUES (1)", "Statement type"),
    ("SELECT * FROM orders_v2; DROP TABLE orders_v2", "single statement"),
    ("SELECT * FROM pg_users", "Unknown tables"),
    ("UPDATE orders_v2 SET status = 'cancelled'", "Statement type"),
    ("SELECT * FROM api_keys", "Unknown tables"),
    ("ATTACH 'evil.db' AS evil", "Statement type"),
]


@pytest.mark.parametrize("sql", SAFE_SQL)
def test_validate_nl_sql_allows_single_statement_selects(sql: str) -> None:
    validate_nl_sql(sql, ALLOWED_TABLES)


@pytest.mark.parametrize(("sql", "message"), UNSAFE_SQL)
def test_validate_nl_sql_rejects_unsafe_statements(sql: str, message: str) -> None:
    with pytest.raises(UnsafeSQLError, match=message):
        validate_nl_sql(sql, ALLOWED_TABLES)


def test_execute_nl_query_rejects_unsafe_translated_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = QueryEngine(catalog=DataCatalog(), db_path=":memory:")
    engine._tenant_router = Mock()
    engine._tenant_router.has_config.return_value = False
    engine._tenant_router.get_duckdb_schema.return_value = None
    backend = Mock()
    backend.name = "duckdb"
    engine._backend = backend
    engine._backend_name = backend.name
    monkeypatch.setattr(
        engine,
        "_translate_question_to_sql",
        lambda question, tenant_id=None: "DROP TABLE orders_v2",
    )

    with pytest.raises(ValueError, match="unsafe query"):
        engine.execute_nl_query("drop everything")

    backend.execute.assert_not_called()


def test_execute_nl_query_executes_safe_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = QueryEngine(catalog=DataCatalog(), db_path=":memory:")
    engine._tenant_router = Mock()
    engine._tenant_router.has_config.return_value = False
    engine._tenant_router.get_duckdb_schema.return_value = None
    backend = Mock()
    backend.name = "duckdb"
    backend.execute.return_value = [{"order_id": "ORD-1"}]
    engine._backend = backend
    engine._backend_name = backend.name
    monkeypatch.setattr(
        engine,
        "_translate_question_to_sql",
        lambda question, tenant_id=None: "SELECT * FROM orders_v2",
    )

    result = engine.execute_nl_query("show me orders")

    assert result["data"] == [{"order_id": "ORD-1"}]
    assert result["row_count"] == 1
    backend.execute.assert_called_once_with("SELECT * FROM orders_v2")
