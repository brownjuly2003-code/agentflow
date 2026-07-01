"""Pin the vendored NL->SQL generation engine (AgentFlow ADR 0008).

Covers the four moving parts of the vendored generation subtree without a live
GraceKelly:

1. schema grounding from the DataCatalog (all demo tables, few-shots, the
   bounded-PII `exclude_fields` seam);
2. the generate -> validate -> repair_once graph routing (recover, fail,
   no-repair) via a scripted fake provider;
3. the static sqlglot guard (SELECT-only, no DML, DuckDB file-read denylist);
4. tolerant parsing of the model's JSON output contract.
"""

from __future__ import annotations

import json

import pytest

from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.nl_sql_engine import (
    GenerateRequest,
    GenerateResponse,
    GenerationErrorKind,
    build_context_from_catalog,
    generate_sql,
    generate_sql_text,
    validate_sql,
)
from src.serving.semantic_layer.nl_sql_engine._sql_envelope import strip_ansi, unwrap_sql_json
from src.serving.semantic_layer.nl_sql_engine.parsing import parse_generate_sql_output


class _SeqProvider:
    """Fake LLMProvider that returns a scripted SQL per call.

    The last entry is repeated if the graph calls more times than scripted, so a
    two-entry script drives exactly the generate -> repair sequence.
    """

    name = "seq"
    model = "seq-model"

    def __init__(self, *sqls: str) -> None:
        self._sqls = list(sqls)
        self.calls = 0

    def generate(self, req: GenerateRequest) -> GenerateResponse:
        sql = self._sqls[min(self.calls, len(self._sqls) - 1)]
        self.calls += 1
        return GenerateResponse(
            text=json.dumps({"sql": sql, "rationale": "r", "confidence": 0.6}),
            model=self.model,
        )


@pytest.fixture
def catalog() -> DataCatalog:
    return DataCatalog()


# --- schema grounding ----------------------------------------------------


def test_context_covers_all_demo_tables(catalog: DataCatalog) -> None:
    ctx = build_context_from_catalog(catalog, "total revenue")
    expected = {e.table for e in catalog.entities.values()}
    assert set(ctx.tables) == expected
    # every table name appears in the rendered schema block
    for table in expected:
        assert table in ctx.schema_block


def test_context_derives_metric_fewshots(catalog: DataCatalog) -> None:
    ctx = build_context_from_catalog(catalog, "q")
    assert len(ctx.fewshots) == len(catalog.metrics)
    # each few-shot SQL is a concrete SELECT with the window placeholder filled
    for ex in ctx.fewshots:
        assert ex.sql.strip().upper().startswith("SELECT")
        assert "{window}" not in ex.sql


def test_exclude_fields_hides_a_single_column(catalog: DataCatalog) -> None:
    ctx = build_context_from_catalog(
        catalog, "q", exclude_fields={"users_enriched": ["total_spent"]}
    )
    assert "users_enriched" in ctx.tables
    assert "total_spent" not in ctx.schema_block


def test_exclude_all_columns_drops_the_table(catalog: DataCatalog) -> None:
    entity = catalog.entities["product"]
    all_cols = [entity.primary_key, *entity.fields.keys()]
    ctx = build_context_from_catalog(catalog, "q", exclude_fields={entity.table: all_cols})
    assert entity.table not in ctx.tables
    assert entity.table not in ctx.schema_block
    assert any("fully excluded" in note for note in ctx.notes)


# --- graph routing -------------------------------------------------------


def test_happy_path_one_call(catalog: DataCatalog) -> None:
    provider = _SeqProvider("SELECT SUM(total_amount) FROM orders_v2 WHERE status != 'cancelled'")
    result = generate_sql("what is revenue", catalog, provider=provider)
    assert result.ok
    assert provider.calls == 1
    assert not result.repair_attempted
    assert [t["node"] for t in result.trace] == ["generate_sql", "validate"]


def test_repair_recovers_invalid_first_pass(catalog: DataCatalog) -> None:
    provider = _SeqProvider("DELETE FROM orders_v2", "SELECT COUNT(*) FROM orders_v2")
    result = generate_sql("q", catalog, provider=provider)
    assert result.ok
    assert provider.calls == 2
    assert result.repair_attempted
    assert result.error_kind is None
    assert [t["node"] for t in result.trace] == [
        "generate_sql",
        "validate",
        "repair_once",
        "validate",
    ]


def test_repair_failure_is_classified(catalog: DataCatalog) -> None:
    provider = _SeqProvider("DROP TABLE orders_v2", "UPDATE orders_v2 SET x = 1")
    result = generate_sql("q", catalog, provider=provider)
    assert not result.ok
    assert provider.calls == 2
    assert result.error_kind == GenerationErrorKind.REPAIR_FAILED


def test_disable_repair_keeps_invalid_sql_classification(catalog: DataCatalog) -> None:
    provider = _SeqProvider("DELETE FROM orders_v2")
    result = generate_sql("q", catalog, provider=provider, disable_repair=True)
    assert not result.ok
    assert provider.calls == 1
    assert result.error_kind == GenerationErrorKind.INVALID_SQL


def test_generate_sql_text_returns_none_on_guard_reject(catalog: DataCatalog) -> None:
    provider = _SeqProvider("DELETE FROM orders_v2", "TRUNCATE orders_v2")
    assert generate_sql_text("q", catalog, provider=provider) is None


def test_generate_sql_text_returns_sql_on_success(catalog: DataCatalog) -> None:
    provider = _SeqProvider("SELECT COUNT(*) FROM orders_v2")
    sql = generate_sql_text("q", catalog, provider=provider)
    assert sql == "SELECT COUNT(*) FROM orders_v2"


# --- static guard --------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "expect_ok"),
    [
        ("SELECT SUM(total_amount) FROM orders_v2", True),
        ("SELECT COUNT(*) FROM orders_v2 WHERE status != 'cancelled'", True),
        ("DELETE FROM orders_v2", False),
        ("UPDATE orders_v2 SET total_amount = 0", False),
        ("SELECT 1; SELECT 2", False),
        ("SELECT * FROM read_csv('/etc/passwd')", False),
        ("SELECT * FROM read_parquet('x')", False),
        ("SELECT read_json_auto('x')", False),
        ("SELECT pg_sleep(10)", False),
    ],
)
def test_guard_shapes(sql: str, expect_ok: bool) -> None:
    assert validate_sql(sql, dialect="duckdb").ok is expect_ok


# --- output parsing ------------------------------------------------------


def test_parse_plain_json_envelope() -> None:
    parsed = parse_generate_sql_output(
        '{"sql": "SELECT 1", "rationale": "r", "tables_used": ["t"], "confidence": 0.9}'
    )
    assert parsed.sql == "SELECT 1"
    assert parsed.tables_used == ("t",)
    assert parsed.confidence == pytest.approx(0.9)


def test_parse_fenced_json() -> None:
    parsed = parse_generate_sql_output('```json\n{"sql": "SELECT 2"}\n```')
    assert parsed.sql == "SELECT 2"


def test_parse_bare_select_fallback_zero_confidence() -> None:
    parsed = parse_generate_sql_output("here you go: SELECT 3 FROM t;")
    assert parsed.sql.startswith("SELECT 3")
    assert parsed.confidence == 0.0


def test_parse_strips_trailing_semicolon() -> None:
    parsed = parse_generate_sql_output('{"sql": "SELECT 4;"}')
    assert parsed.sql == "SELECT 4"


# --- envelope helpers (GraceKelly browser-path quirks) -------------------


def test_unwrap_sql_json_extracts_sql() -> None:
    assert unwrap_sql_json('{"sql": "SELECT 5", "rationale": "x"}') == "SELECT 5"


def test_unwrap_sql_json_passthrough_when_not_envelope() -> None:
    assert unwrap_sql_json("SELECT 6") == "SELECT 6"


def test_unwrap_sql_json_tolerates_literal_newlines() -> None:
    # literal newline inside the value breaks strict json.loads -> regex fallback
    raw = '{"sql": "SELECT 7\nFROM t", "rationale": "x"}'
    assert "SELECT 7" in unwrap_sql_json(raw)


def test_strip_ansi_removes_colour_codes() -> None:
    assert strip_ansi("\x1b[31mSELECT 8\x1b[0m") == "SELECT 8"
