"""Execution Accuracy (EA) — result-set equality between gold and pred SQL.

Ported from the D:\\NL_SQL engine's
`src/nl_sql/eval/metrics/execution_accuracy.py` (see ADR 0008). That in turn
follows the official BIRD Mini-Dev `evaluation_ex.py`: run gold + pred against
the same database and compare row sets, with three guards:

1. Floats (and Decimals) compared with absolute tolerance (1e-6) so trivial
   CAST/precision differences don't flip a correct query to a fail.
2. Rows are normalised to tuples; column names are NOT compared (any aliasing
   is accepted as long as the values match).
3. ORDER BY in gold => order-sensitive comparison; otherwise set equality.

`compare_results` is the single source of truth; `execution_accuracy`
aggregates a list of match bits into a fraction.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

_FLOAT_TOLERANCE = 1e-6
_ORDER_BY_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ResultComparison:
    """Outcome of comparing a (gold, pred) result set.

    `match` is the EA bit. `reason` describes why a comparison failed, for
    slicing the report (row-count vs value vs execution failure).
    """

    match: bool
    reason: str = ""
    gold_rows: int = 0
    pred_rows: int = 0


def compare_results(
    gold_rows: Sequence[Sequence[Any]],
    pred_rows: Sequence[Sequence[Any]],
    *,
    gold_sql: str | None = None,
) -> ResultComparison:
    """Compare two result sets BIRD-style.

    Default is set-equality on normalised row tuples. When `gold_sql` contains
    ``ORDER BY`` the comparison becomes order-sensitive (a "top N" answer in the
    wrong order is wrong). Pass ``gold_sql=None`` to force set-equality.
    """
    gold_norm = [_normalise_row(r) for r in gold_rows]
    pred_norm = [_normalise_row(r) for r in pred_rows]

    order_sensitive = gold_sql is not None and bool(_ORDER_BY_RE.search(gold_sql))

    if order_sensitive:
        if len(gold_norm) != len(pred_norm):
            return ResultComparison(
                match=False,
                reason=f"ordered row count mismatch: gold={len(gold_norm)}, pred={len(pred_norm)}",
                gold_rows=len(gold_norm),
                pred_rows=len(pred_norm),
            )
        for i, (g, p) in enumerate(zip(gold_norm, pred_norm, strict=True)):
            if not _row_equal(g, p):
                return ResultComparison(
                    match=False,
                    reason=f"ordered row {i} mismatch: gold={g!r}, pred={p!r}",
                    gold_rows=len(gold_norm),
                    pred_rows=len(pred_norm),
                )
        return ResultComparison(match=True, gold_rows=len(gold_norm), pred_rows=len(pred_norm))

    gold_set = {_hashable(g) for g in gold_norm}
    pred_set = {_hashable(p) for p in pred_norm}
    if gold_set != pred_set:
        reason = (
            f"set mismatch (unique rows differ): |gold|={len(gold_set)}, |pred|={len(pred_set)}"
        )
        return ResultComparison(
            match=False,
            reason=reason,
            gold_rows=len(gold_norm),
            pred_rows=len(pred_norm),
        )
    return ResultComparison(match=True, gold_rows=len(gold_norm), pred_rows=len(pred_norm))


def execution_accuracy(matches: Sequence[bool]) -> float:
    """Return EA as a fraction in [0, 1]. Empty => 0.0."""
    if not matches:
        return 0.0
    return sum(1 for m in matches if m) / len(matches)


def _normalise_row(row: Sequence[Any]) -> tuple[Any, ...]:
    return tuple(_normalise_cell(v) for v in row)


def _normalise_cell(value: Any) -> Any:
    """Strip type quirks before comparison.

    - bool preserved (bool is an int subclass — do not promote to 1/0).
    - Decimal -> float (DuckDB SUM over DECIMAL returns Decimal; AVG returns
      DOUBLE — normalise both to float so a sum and its float echo compare).
    - bytes -> str; NaN -> a sentinel so two NaNs compare equal.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float):
        if value != value:  # NaN
            return "__NaN__"
        return float(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    return value


def _row_equal(a: tuple[Any, ...], b: tuple[Any, ...]) -> bool:
    if len(a) != len(b):
        return False
    return all(_cell_equal(x, y) for x, y in zip(a, b, strict=True))


def _cell_equal(a: Any, b: Any) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) <= _FLOAT_TOLERANCE
        except (TypeError, ValueError):
            return False
    return bool(a == b)


def _hashable(row: tuple[Any, ...]) -> tuple[Any, ...]:
    """Project a row into a hashable form for set comparison.

    Floats are quantised to the tolerance grid so 1.0000001 and 1.0 bucket
    together; everything else passes through.
    """
    out: list[Any] = []
    for v in row:
        if isinstance(v, float):
            out.append(round(v / _FLOAT_TOLERANCE) if v == v else "__NaN__")
        else:
            out.append(v)
    return tuple(out)
