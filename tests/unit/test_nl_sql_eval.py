"""Keep the NL->SQL eval harness alive and honest in CI.

Two jobs:
1. Pin the metric math (`compare_results` / `execution_accuracy`) exactly.
2. Prove the harness runs end-to-end on the seeded warehouse — this also
   validates every gold SQL, since `score_item` raises if a gold query fails —
   and pin the documented rule-based baseline shape so the number in
   docs/perf/nl-sql-eval-*.md can't drift silently.
"""

from __future__ import annotations

from scripts.nl_sql_eval import (
    GOLD_SET,
    build_demo_warehouse,
    compare_results,
    execution_accuracy,
    run_eval,
)
from scripts.nl_sql_eval.dataset import GoldItem


def test_compare_results_set_equality_ignores_order_and_names() -> None:
    # Same unique rows, different order, no ORDER BY in gold -> match.
    assert compare_results([(1,), (2,)], [(2,), (1,)]).match


def test_compare_results_order_sensitive_when_gold_has_order_by() -> None:
    gold_sql = "SELECT x FROM t ORDER BY x DESC"
    assert not compare_results([(2,), (1,)], [(1,), (2,)], gold_sql=gold_sql).match
    assert compare_results([(2,), (1,)], [(2,), (1,)], gold_sql=gold_sql).match


def test_compare_results_float_tolerance() -> None:
    assert compare_results([(1.0,)], [(1.0000001,)]).match
    assert not compare_results([(1.0,)], [(1.5,)]).match


def test_compare_results_decimal_and_float_compare_equal() -> None:
    from decimal import Decimal

    assert compare_results([(Decimal("895.50"),)], [(895.5,)]).match


def test_execution_accuracy_fraction() -> None:
    assert execution_accuracy([True, True, False, True]) == 0.75
    assert execution_accuracy([]) == 0.0


def test_gold_ids_are_unique() -> None:
    ids = [item.id for item in GOLD_SET]
    assert len(ids) == len(set(ids))


def test_harness_scores_a_perfect_translator() -> None:
    # A translator that echoes gold SQL must score 100% — exercises the
    # execute+compare path independently of the shipped engine.
    conn = build_demo_warehouse()
    by_q = {item.question: item.gold_sql for item in GOLD_SET}
    report = run_eval(translate_fn=lambda q: by_q[q], conn=conn)
    assert report.total == len(GOLD_SET)
    assert report.ea == 1.0


def test_harness_scores_untranslatable_and_broken_preds_as_misses() -> None:
    conn = build_demo_warehouse()
    gold = [
        GoldItem("a", "q1", "SELECT COUNT(*) FROM orders_v2", "x"),
        GoldItem("b", "q2", "SELECT COUNT(*) FROM orders_v2", "x"),
    ]
    none_report = run_eval(gold_set=gold, translate_fn=lambda _q: None, conn=conn)
    assert none_report.ea == 0.0
    broken = run_eval(gold_set=gold, translate_fn=lambda _q: "SELECT nope FROM missing", conn=conn)
    assert broken.ea == 0.0
    assert "pred execution failed" in broken.results[0].reason


def test_rule_based_baseline_shape() -> None:
    # The shipped default (rule-based; GRACEKELLY_URL unset in tests) covers its
    # seven designed shapes and nothing else. If this changes, update the report.
    report = run_eval()
    assert report.total == 18
    assert 0.0 < report.ea < 1.0
    assert report.ea_for("out-of-pattern") == 0.0
    assert report.ea_for("in-pattern") >= 0.5
