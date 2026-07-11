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


def _scoped(sql: str, table: str, tenant: str) -> bool:
    """Is ``table`` read through its tenant-scoped relation (ADR-004)?

    Tenant isolation is a predicate on a `tenant_id` column, not a schema
    qualification, so what a scoped read looks like is
    ``(SELECT * EXCLUDE (tenant_id) FROM <table> WHERE tenant_id = '<tenant>')``.
    """
    return f"EXCLUDE (tenant_id) FROM {table} WHERE tenant_id = '{tenant}'" in sql


def test_scope_sql_does_not_scope_cte_aliases(engine: QueryEngine) -> None:
    scoped = engine._scope_sql(
        "WITH orders_v2 AS (SELECT * FROM users_enriched) SELECT * FROM orders_v2",
        tenant_id="tenant_a",
    )

    # The physical table inside the CTE body is scoped...
    assert _scoped(scoped, "users_enriched", "tenant_a")
    # ...while the CTE reference itself — a local alias, not a table — is not.
    assert not _scoped(scoped, "orders_v2", "tenant_a")


def test_scope_sql_scopes_physical_table_shadowed_by_cte_name(engine: QueryEngine) -> None:
    # A CTE whose name collides with a real table must not hide the *physical*
    # inner reference from tenant scoping. Pre-fix the inner `orders_v2` was
    # skipped (its name matched the CTE) and stayed bound to the shared `main`
    # schema, leaking every tenant's rows. (audit_30_06_26.md D1)
    scoped = engine._scope_sql(
        "WITH orders_v2 AS (SELECT * FROM orders_v2) SELECT * FROM orders_v2",
        tenant_id="tenant_a",
    )

    # Exactly one of the two `orders_v2` references is physical, and it is scoped;
    # the other is the CTE reference and is left alone.
    assert scoped.count("tenant_id = 'tenant_a'") == 1
    assert _scoped(scoped, "orders_v2", "tenant_a")
    # And nothing fell back to a shared schema.
    assert all(db != "main" for _, db in _tables(scoped))


def test_scope_sql_rejects_recursive_cte_shadowing_physical_table(engine: QueryEngine) -> None:
    # A recursive CTE *can* self-reference, so sqlglot keeps its name in its own
    # body scope and the cte_sources skip mis-classifies the physical *anchor*
    # reference (the first UNION branch, which cannot self-reference) as a CTE
    # reference — it is never re-scoped, stays bound to the shared `main` schema,
    # and leaks every tenant's rows (the WITH RECURSIVE bypass of the D1 fix).
    # There is no safe re-scoping of a recursive anchor and no legitimate query
    # names a recursive CTE after a physical table, so fail closed.
    # (audit_30 D1 follow-up)
    with pytest.raises(ValueError, match="[Rr]ecursive CTE shadows"):
        engine._scope_sql(
            "WITH RECURSIVE orders_v2 AS "
            "(SELECT * FROM orders_v2 UNION SELECT * FROM orders_v2) "
            "SELECT * FROM orders_v2",
            tenant_id="tenant_a",
        )


def test_scope_sql_scopes_tables_after_subquery(engine: QueryEngine) -> None:
    scoped = engine._scope_sql(
        "SELECT * FROM (SELECT * FROM orders_v2) AS recent, users_enriched",
        tenant_id="tenant_a",
    )

    assert _scoped(scoped, "orders_v2", "tenant_a")
    assert _scoped(scoped, "users_enriched", "tenant_a")


def test_scope_sql_leaves_comments_untouched(engine: QueryEngine) -> None:
    scoped = engine._scope_sql(
        "-- FROM orders_v2\nSELECT * FROM users_enriched",
        tenant_id="tenant_a",
    )

    assert scoped.startswith("/* FROM orders_v2 */")
    assert _scoped(scoped, "users_enriched", "tenant_a")


def test_scope_sql_rescopes_foreign_schema_qualified_table(engine: QueryEngine) -> None:
    # Defense-in-depth (audit_28_06_26.md #5): even if a schema-qualified known
    # table reaches _scope_sql (validate_nl_sql rejects it on the NL path), the
    # reference is replaced wholesale by the caller's tenant-scoped relation —
    # the foreign schema never survives into the executed SQL.
    scoped = engine._scope_sql("SELECT * FROM victim.orders_v2", tenant_id="tenant_a")

    assert _scoped(scoped, "orders_v2", "tenant_a")
    assert "victim" not in scoped
    assert ("orders_v2", "victim") not in _tables(scoped)


def test_query_package_exports_query_engine() -> None:
    from src.serving.semantic_layer.query import QueryEngine as PackageQueryEngine

    assert PackageQueryEngine is QueryEngine


def test_nl_query_plan_normalizer_source_has_no_mojibake() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "serving"
        / "semantic_layer"
        / "query"
        / "nl_queries.py"
    ).read_bytes()

    assert b"\xc3\xa2\xe2\x80\x9d" not in source


def test_query_package_sources_have_no_control_bytes() -> None:
    # A literal 0x08 (backspace) byte sat inside the explain() fallback regex
    # in nl_queries.py where the author meant the two-character escape \b:
    # the pattern then required a backspace character before FROM/JOIN, never
    # matched, and the regex fallback silently returned no tables_accessed.
    # Same corruption family as the mojibake box-drawing regex (c61a28c), so
    # guard the whole package: no ASCII control bytes other than newline.
    package_dir = (
        Path(__file__).resolve().parents[2] / "src" / "serving" / "semantic_layer" / "query"
    )
    allowed = {0x0A}
    offenders = {}
    for source in package_dir.glob("*.py"):
        # Tolerate CRLF line endings (a Windows checkout artifact, not file
        # content) but still flag a stray CR inside a line.
        data = source.read_bytes().replace(b"\r\n", b"\n")
        bad = sorted({byte for byte in data if byte < 0x20} - allowed)
        if bad:
            offenders[source.name] = bad

    assert offenders == {}


def test_explain_extracts_row_estimate_from_box_drawing_plan(
    engine: QueryEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        engine,
        "_translate_question_to_sql",
        lambda question, tenant_id=None: "SELECT order_id FROM orders_v2",
    )
    monkeypatch.setattr(
        engine._backend,
        "explain",
        lambda sql: [
            (
                "physical_plan",
                "\u250c\u2500\u2500\u2500\u2510\n"
                "\u2502 SEQ_SCAN \u2502\n"
                "\u2502 ~1,234 rows \u2502\n"
                "\u2514\u2500\u2500\u2500\u2518",
            )
        ],
    )

    result = engine.explain("show orders")

    assert result["estimated_rows"] == 1234
