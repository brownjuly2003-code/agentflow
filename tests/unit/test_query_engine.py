from __future__ import annotations

from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine


@pytest.fixture
def engine(tmp_path: Path) -> QueryEngine:
    tenants_path = tmp_path / "tenants.yaml"
    tenants_path.write_text(
        (
            "tenants:\n"
            "  - id: tenant_a\n"
            "    display_name: Tenant A\n"
            "    kafka_topic_prefix: tenant-a\n"
            "    duckdb_schema: tenant_a\n"
            "    max_events_per_day: 1000\n"
            "    max_api_keys: 10\n"
            "    allowed_entity_types: null\n"
        ),
        encoding="utf-8",
        newline="\n",
    )
    return QueryEngine(
        catalog=DataCatalog(),
        db_path=":memory:",
        tenants_config_path=tenants_path,
    )


def _tables(sql: str) -> list[tuple[str, str]]:
    parsed = sqlglot.parse_one(sql, dialect="duckdb")
    return [(table.name, table.db) for table in parsed.find_all(exp.Table)]


def test_scope_sql_does_not_qualify_cte_aliases(engine: QueryEngine) -> None:
    scoped = engine._scope_sql(
        "WITH orders_v2 AS (SELECT * FROM users_enriched) SELECT * FROM orders_v2",
        tenant_id="tenant_a",
    )

    assert ("users_enriched", "tenant_a") in _tables(scoped)
    assert ("orders_v2", "") in _tables(scoped)


def test_scope_sql_qualifies_tables_after_subquery(engine: QueryEngine) -> None:
    scoped = engine._scope_sql(
        "SELECT * FROM (SELECT * FROM orders_v2) AS recent, users_enriched",
        tenant_id="tenant_a",
    )

    assert ("orders_v2", "tenant_a") in _tables(scoped)
    assert ("users_enriched", "tenant_a") in _tables(scoped)


def test_scope_sql_leaves_comments_untouched(engine: QueryEngine) -> None:
    scoped = engine._scope_sql(
        "-- FROM orders_v2\nSELECT * FROM users_enriched",
        tenant_id="tenant_a",
    )

    assert scoped.startswith("/* FROM orders_v2 */")
    assert ("users_enriched", "tenant_a") in _tables(scoped)


def test_query_package_exports_query_engine() -> None:
    from src.serving.semantic_layer.query import QueryEngine as PackageQueryEngine

    assert PackageQueryEngine is QueryEngine
