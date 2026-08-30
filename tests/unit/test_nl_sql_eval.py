"""Keep the NL->SQL eval harness alive and honest in CI.

Three jobs:
1. Pin the metric math (`compare_results` / `execution_accuracy`) exactly.
2. Prove the harness runs end-to-end on the seeded warehouse — this also
   validates every gold SQL, since `score_item` raises if a gold query fails —
   and pin the documented rule-based baseline shape so the number in
   docs/perf/nl-sql-eval-*.md can't drift silently.
3. Keep runtime output out of tracked performance evidence and document its
   promotion boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import run_nl_sql_eval as run_nl_sql_eval_cli
from scripts.nl_sql_eval import (
    GOLD_SET,
    build_demo_warehouse,
    compare_results,
    execution_accuracy,
    run_eval,
)
from scripts.nl_sql_eval.dataset import GoldItem

ROOT = Path(__file__).resolve().parents[2]
RULE_BASED_RECORD = ROOT / "docs" / "perf" / "nl-sql-eval-2026-07-01.md"
SONNET_RECORD = ROOT / "docs" / "perf" / "nl-sql-eval-sonnet5-2026-07-01.md"


def test_cli_defaults_to_ignored_project_root_runtime_report(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_nl_sql_eval.py"])

    args = run_nl_sql_eval_cli.parse_args()

    assert args.md == ROOT / ".artifacts" / "nl-sql-eval" / "current.md"
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_relative_report_path_resolves_from_project_root() -> None:
    assert (
        run_nl_sql_eval_cli.resolve_report_path(Path(".artifacts/nl-sql-eval/custom.md"))
        == ROOT / ".artifacts" / "nl-sql-eval" / "custom.md"
    )


@pytest.mark.parametrize(
    "report_path",
    [
        Path("docs/perf/nl-sql-eval-2026-07-01.md"),
        RULE_BASED_RECORD,
        Path("docs/perf/nl-sql-eval-sonnet5-2026-07-01.md"),
        SONNET_RECORD,
        Path("docs/perf/nl-sql-eval-next.md"),
    ],
)
def test_tracked_performance_evidence_cannot_be_overwritten(report_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.artifacts/nl-sql-eval"):
        run_nl_sql_eval_cli.resolve_report_path(report_path)


def test_cli_rejects_tracked_output_before_running_eval(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_nl_sql_eval.py", "--md", "docs/perf/nl-sql-eval-2026-07-01.md"],
    )

    def fail_if_eval_runs():
        pytest.fail("tracked-output validation must run before the evaluation")

    monkeypatch.setattr(run_nl_sql_eval_cli, "run_eval", fail_if_eval_runs)

    assert run_nl_sql_eval_cli.main() == 2
    assert ".artifacts/nl-sql-eval" in capsys.readouterr().err


def test_runtime_markdown_names_artifact_and_promotion_boundary() -> None:
    markdown = run_nl_sql_eval_cli._render_markdown(run_eval(), "rule-based")

    assert ".artifacts/nl-sql-eval/current.md" in markdown
    assert "runtime artifact" in markdown.lower()
    assert "date-stamped" in markdown
    assert "not a production benchmark" in markdown.lower()
    assert "served `/query`" in markdown


def test_current_docs_name_nl_sql_eval_owner_and_evidence_boundary() -> None:
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    perf_hub = " ".join((ROOT / "docs" / "perf" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "| NL-to-SQL evaluation |" in docs_hub
    assert "scripts/run_nl_sql_eval.py" in perf_hub
    assert ".artifacts/nl-sql-eval/current.md" in perf_hub
    assert "docs/perf/nl-sql-eval-2026-07-01.md" in contributing
    assert "docs/perf/nl-sql-eval-sonnet5-2026-07-01.md" in contributing
    assert "NL-to-SQL evaluation runtime-artifact ownership sub-slice" in plan


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
