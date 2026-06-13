"""Injection safety for the rule-based NL->SQL fallback (audit A-4).

`_rule_based_translate` is the one dynamic-SQL site that interpolates tokens
lifted from free-text *without* routing through the query package's
SQLBuilderMixin. Two independent layers keep it inert:

1. Extraction regexes (`ORD-[\\w-]+`, `USR-\\d+`, `\\d+` windows, int limits)
   exclude SQL metacharacters from the captured token in the first place.
2. `_sql_str_literal` doubles single quotes at the splice point, so a token
   would stay contained even if a future edit loosened a pattern.

These tests pin both: the exact SQL for valid inputs, and that adversarial
input collapses to a single harmless SELECT.
"""

import pytest

from src.serving.semantic_layer.nl_engine import _rule_based_translate, _sql_str_literal


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "show me order ORD-2024-X1",
            "SELECT * FROM orders_v2 WHERE order_id = 'ORD-2024-X1'",
        ),
        (
            "details for user USR-42",
            "SELECT * FROM users_enriched WHERE user_id = 'USR-42'",
        ),
        (
            "total revenue last 3 hours",
            "SELECT SUM(total_amount) as revenue FROM orders_v2 "
            "WHERE status != 'cancelled' AND created_at >= NOW() - INTERVAL '3 hours'",
        ),
        (
            "top 7 products",
            "SELECT name, category, price, stock_quantity FROM products_current "
            "ORDER BY price DESC LIMIT 7",
        ),
    ],
)
def test_valid_inputs_render_expected_sql(question: str, expected: str) -> None:
    # Quoting the value-interpolation sites must not change the SQL for inputs
    # that never contained a quote (i.e. every legitimate input).
    assert _rule_based_translate(question) == expected


@pytest.mark.parametrize(
    "payload",
    [
        "order ORD-1' OR '1'='1",
        "order ORD-1'); DROP TABLE orders_v2;--",
        "show order ORD-9 UNION SELECT password FROM users",
    ],
)
def test_order_injection_collapses_to_inert_select(payload: str) -> None:
    sql = _rule_based_translate(payload)
    assert sql is not None
    # The regex stops at the first non-[\w-] char, so the tail never reaches SQL.
    assert sql == "SELECT * FROM orders_v2 WHERE order_id = 'ORD-1'" or sql.startswith(
        "SELECT * FROM orders_v2 WHERE order_id = 'ORD-9'"
    )
    assert "DROP" not in sql.upper()
    assert "UNION" not in sql.upper()
    assert "OR '1'='1" not in sql
    assert ";" not in sql


@pytest.mark.parametrize(
    "payload",
    [
        "user USR-1; DROP TABLE users_enriched--",
        "user USR-7' OR 1=1 --",
    ],
)
def test_user_injection_collapses_to_inert_select(payload: str) -> None:
    sql = _rule_based_translate(payload)
    assert sql is not None
    assert sql.startswith("SELECT * FROM users_enriched WHERE user_id = 'USR-")
    assert "DROP" not in sql.upper()
    assert ";" not in sql
    assert " OR " not in sql.upper()


def test_window_only_accepts_numeric_units() -> None:
    # A bogus window phrase falls back to the safe default, never interpolating
    # attacker text into the INTERVAL literal.
    sql = _rule_based_translate("revenue last 5'; DROP TABLE orders_v2 -- minutes")
    assert sql is not None
    assert "DROP" not in sql.upper()
    assert ";" not in sql
    # No numeric window matched -> default 1 hour.
    assert sql.endswith("INTERVAL '1 hour'")


def test_sql_str_literal_doubles_single_quotes() -> None:
    # The defense-in-depth layer, independent of the extraction regexes.
    assert _sql_str_literal("ORD-1") == "'ORD-1'"
    assert _sql_str_literal("a'b") == "'a''b'"
    assert _sql_str_literal("'; DROP TABLE t;--") == "'''; DROP TABLE t;--'"
