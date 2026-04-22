from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine

ATTACK_VECTORS = [
    "'; DROP TABLE orders_v2; --",
    "' OR '1'='1",
    "'; DELETE FROM users WHERE '1'='1",
    "\\'; DROP TABLE orders_v2; --",
    "ORD' UNION SELECT * FROM api_keys --",
    "'); ATTACH 'evil.db' AS evil; --",
    "ORD\x00'; DROP TABLE --",
    "ORD' AND (SELECT COUNT(*) FROM api_keys) > 0 --",
]


@pytest.mark.parametrize("payload", ATTACK_VECTORS)
def test_get_entity_passes_entity_id_as_query_param(payload: str) -> None:
    engine = QueryEngine(catalog=DataCatalog(), db_path=":memory:")
    engine._tenant_router = Mock()
    engine._tenant_router.has_config.return_value = False
    engine._tenant_router.get_duckdb_schema.return_value = None
    backend = Mock()
    backend.name = "duckdb"
    backend.execute.return_value = []
    engine._backend = backend
    engine._backend_name = backend.name

    result = engine.get_entity("order", payload)

    assert result is None
    assert backend.execute.call_count == 1
    args = backend.execute.call_args.args
    assert len(args) == 2
    sql, params = args
    assert 'WHERE "order_id" = ?' in sql
    assert payload not in sql
    assert params == [payload]


@pytest.mark.parametrize("payload", ATTACK_VECTORS)
def test_get_entity_at_passes_history_filters_as_query_params(payload: str) -> None:
    engine = QueryEngine(catalog=DataCatalog(), db_path=":memory:")
    engine._tenant_router = Mock()
    engine._tenant_router.has_config.return_value = False
    engine._tenant_router.get_duckdb_schema.return_value = None
    backend = Mock()
    backend.name = "duckdb"
    backend.table_columns.return_value = {"entity_id", "entity_data", "entity_type", "processed_at"}
    backend.execute.return_value = [
        {"entity_data": "{}", "event_time": datetime(2026, 4, 1, 12, 0, tzinfo=UTC)}
    ]
    engine._backend = backend
    engine._backend_name = backend.name
    as_of = datetime(2026, 4, 1, 15, 30, tzinfo=UTC)
    expected_anchor = as_of.astimezone(datetime.now().astimezone().tzinfo or UTC).replace(
        tzinfo=None
    )

    result = engine.get_entity_at("order", payload, as_of=as_of)

    assert result is not None
    assert backend.execute.call_count == 1
    args = backend.execute.call_args.args
    assert len(args) == 2
    sql, params = args
    assert "entity_type = ?" in sql
    assert "entity_id = ?" in sql
    assert "CAST(? AS TIMESTAMP)" in sql
    assert payload not in sql
    assert params == ["order", payload, expected_anchor]


def test_get_metric_passes_as_of_anchor_as_query_params() -> None:
    engine = QueryEngine(catalog=DataCatalog(), db_path=":memory:")
    engine._tenant_router = Mock()
    engine._tenant_router.has_config.return_value = False
    engine._tenant_router.get_duckdb_schema.return_value = None
    backend = Mock()
    backend.name = "duckdb"
    backend.scalar.return_value = 12.5
    engine._backend = backend
    engine._backend_name = backend.name
    as_of = datetime(2026, 4, 1, 15, 30, tzinfo=UTC)
    expected_anchor = as_of.astimezone(datetime.now().astimezone().tzinfo or UTC).replace(
        tzinfo=None
    )

    result = engine.get_metric("revenue", window="24h", as_of=as_of)

    assert result == {"value": 12.5, "unit": "USD"}
    assert backend.scalar.call_count == 1
    args = backend.scalar.call_args.args
    assert len(args) == 2
    sql, params = args
    assert sql.count("CAST(? AS TIMESTAMP)") == 2
    assert "NOW()" not in sql
    assert params == [expected_anchor, expected_anchor]
