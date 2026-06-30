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


def test_scope_sql_qualifies_physical_table_shadowed_by_cte_name(engine: QueryEngine) -> None:
    # A CTE whose name collides with a real table must not hide the *physical*
    # inner reference from tenant rescoping. Pre-fix the inner `orders_v2` was
    # skipped (its name matched the CTE) and stayed bound to the shared `main`
    # schema, leaking every tenant's rows. (audit_30_06_26.md D1)
    scoped = engine._scope_sql(
        "WITH orders_v2 AS (SELECT * FROM orders_v2) SELECT * FROM orders_v2",
        tenant_id="tenant_a",
    )

    tables = _tables(scoped)
    # The physical inner reference is now pinned to the caller's tenant schema.
    assert ("orders_v2", "tenant_a") in tables
    # The only unqualified `orders_v2` left is the outer CTE reference (1, not 2).
    assert tables.count(("orders_v2", "")) == 1
    # And nothing fell back to the shared `main` schema.
    assert all(db != "main" for _, db in tables)


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


def test_scope_sql_rescopes_foreign_schema_qualified_table(engine: QueryEngine) -> None:
    # Defense-in-depth (audit_28_06_26.md #5): even if a schema-qualified known
    # table reaches _scope_sql (validate_nl_sql rejects it on the NL path), it
    # must be forced into the caller's tenant schema, never executed against the
    # named foreign schema — otherwise tenant_a reads victim's data.
    scoped = engine._scope_sql("SELECT * FROM victim.orders_v2", tenant_id="tenant_a")

    assert ("orders_v2", "tenant_a") in _tables(scoped)
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
        lambda question, tenant_id=None: "SELECT * FROM orders_v2",
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
