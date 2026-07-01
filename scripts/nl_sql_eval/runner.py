"""Eval runner: translate each gold question, execute, score EA.

For every gold item the runner calls the injected `translate_fn` (defaults to
`src.serving.semantic_layer.nl_engine.translate_nl_to_sql`), executes the
predicted SQL and the gold SQL against the same seeded DuckDB, and compares the
result sets with `metrics.compare_results`. A `None` prediction (the rule-based
translator's "untranslatable" signal) or a pred that raises both count as a
miss.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import duckdb

from scripts.nl_sql_eval.dataset import GOLD_SET, GoldItem
from scripts.nl_sql_eval.metrics import compare_results, execution_accuracy
from scripts.nl_sql_eval.warehouse import build_demo_warehouse

TranslateFn = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class ItemResult:
    id: str
    question: str
    category: str
    pred_sql: str | None
    match: bool
    reason: str


@dataclass(slots=True)
class EvalReport:
    results: list[ItemResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def matched(self) -> int:
        return sum(1 for r in self.results if r.match)

    @property
    def ea(self) -> float:
        return execution_accuracy([r.match for r in self.results])

    def ea_for(self, category: str) -> float:
        subset = [r.match for r in self.results if r.category == category]
        return execution_accuracy(subset)

    def categories(self) -> list[str]:
        seen: list[str] = []
        for r in self.results:
            if r.category not in seen:
                seen.append(r.category)
        return seen


def _default_translate_fn() -> TranslateFn:
    """Build the default translator: AgentFlow's shipped NL->SQL entrypoint."""
    from src.serving.semantic_layer.catalog import DataCatalog
    from src.serving.semantic_layer.nl_engine import translate_nl_to_sql

    catalog = DataCatalog()
    return lambda question: translate_nl_to_sql(question, catalog)


def _execute(conn: duckdb.DuckDBPyConnection, sql: str) -> tuple[list[Sequence[Any]], str | None]:
    """Run `sql`, returning (rows, error). Any exception -> ([], message)."""
    try:
        return conn.execute(sql).fetchall(), None
    except Exception as exc:  # noqa: BLE001 - eval must survive any pred SQL error
        return [], f"{type(exc).__name__}: {exc}"


def score_item(
    conn: duckdb.DuckDBPyConnection,
    item: GoldItem,
    translate_fn: TranslateFn,
) -> ItemResult:
    pred_sql = translate_fn(item.question)
    if pred_sql is None:
        return ItemResult(
            id=item.id,
            question=item.question,
            category=item.category,
            pred_sql=None,
            match=False,
            reason="untranslatable (translator returned no SQL)",
        )

    gold_rows, gold_err = _execute(conn, item.gold_sql)
    if gold_err is not None:
        # A broken gold SQL is a harness bug, not a translator miss — surface it.
        raise ValueError(f"gold SQL failed for {item.id!r}: {gold_err}\n  {item.gold_sql}")

    pred_rows, pred_err = _execute(conn, pred_sql)
    if pred_err is not None:
        return ItemResult(
            id=item.id,
            question=item.question,
            category=item.category,
            pred_sql=pred_sql,
            match=False,
            reason=f"pred execution failed: {pred_err}",
        )

    comparison = compare_results(gold_rows, pred_rows, gold_sql=item.gold_sql)
    return ItemResult(
        id=item.id,
        question=item.question,
        category=item.category,
        pred_sql=pred_sql,
        match=comparison.match,
        reason="ok" if comparison.match else comparison.reason,
    )


def run_eval(
    gold_set: Sequence[GoldItem] | None = None,
    translate_fn: TranslateFn | None = None,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> EvalReport:
    """Score `gold_set` (default: the bundled set) and return an EvalReport."""
    items = list(gold_set) if gold_set is not None else GOLD_SET
    fn = translate_fn or _default_translate_fn()
    warehouse = conn or build_demo_warehouse()
    report = EvalReport()
    for item in items:
        report.results.append(score_item(warehouse, item, fn))
    return report
