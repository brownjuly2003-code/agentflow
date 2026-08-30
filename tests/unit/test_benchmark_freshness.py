from __future__ import annotations

import hashlib
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import benchmark_freshness

ROOT = Path(__file__).resolve().parents[2]
ARCHIVED_DEMO_FRESHNESS_BLOB = "7b77d238d9a8e452adbf7e571323de4873513ff4"


def test_percentile_nearest_rank_basics():
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]

    assert benchmark_freshness.percentile(values, 50) == 50.0
    assert benchmark_freshness.percentile(values, 95) == 100.0
    assert benchmark_freshness.percentile([42.0], 99) == 42.0


def test_percentile_rejects_empty_input():
    with pytest.raises(ValueError, match="empty"):
        benchmark_freshness.percentile([], 50)


def test_summarize_reports_all_stats():
    summary = benchmark_freshness.summarize([100.0, 200.0, 300.0, 400.0])

    assert summary["p50_ms"] == 200.0
    assert summary["max_ms"] == 400.0
    assert summary["mean_ms"] == 250.0
    assert summary["p95_ms"] == 400.0


def test_parse_args_defaults_to_ignored_runtime_artifacts(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["benchmark_freshness.py"])

    args = benchmark_freshness.parse_args()
    expected_report_path = (
        benchmark_freshness.PROJECT_ROOT / ".artifacts" / "freshness" / "freshness-benchmark.md"
    )

    assert args.iterations == 30
    assert args.metric == "revenue"
    assert args.window == "24h"
    assert args.ttl_only_ttl_seconds == 5
    assert benchmark_freshness.REPORT_PATH == expected_report_path
    assert args.report_path == str(expected_report_path)
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "relative_path",
    [
        "docs/perf/freshness-benchmark.md",
        "docs/archive/performance/freshness-benchmark-2026-06-06.md",
    ],
)
def test_tracked_freshness_docs_cannot_be_overwritten(relative_path):
    with pytest.raises(ValueError, match=r"\.artifacts/freshness"):
        benchmark_freshness.resolve_report_path(relative_path)


def test_build_order_event_passes_the_pipeline_validators():
    from agentflow_runtime.quality.validators.schema_validator import validate_event
    from agentflow_runtime.quality.validators.semantic_validator import validate_semantics

    event = benchmark_freshness.build_order_event(Decimal("701.37"), 7)

    assert validate_event(event).is_valid
    error_issues = [
        issue for issue in validate_semantics(event).issues if issue.severity == "error"
    ]
    assert error_issues == []
    assert float(event["total_amount"]) == pytest.approx(701.37)
    assert event["event_type"] == "order.created"


def test_build_report_lists_arms_and_the_webhook_caveat():
    arms = [
        {
            "arm": "event_driven",
            "iterations": 30,
            "timeouts": 0,
            "samples_ms": [900.0, 1100.0],
            "p50_ms": 1000.0,
            "p95_ms": 2000.0,
            "max_ms": 2100.0,
            "mean_ms": 1050.0,
        },
        {
            "arm": "ttl_only",
            "iterations": 12,
            "timeouts": 0,
            "samples_ms": [2400.0, 2600.0],
            "p50_ms": 2500.0,
            "p95_ms": 4800.0,
            "max_ms": 4900.0,
            "mean_ms": 2500.0,
        },
    ]

    report = benchmark_freshness.build_report(
        generated_at="2026-06-06T00:00:00+03:00",
        system_info={"os": "TestOS", "cpu": "TestCPU", "cpu_count": "8", "python": "3.13.7"},
        metric="revenue",
        window="24h",
        poll_interval_ms=25,
        ttl_only_ttl_seconds=5,
        arms=arms,
    )

    assert "# Event-to-Metric Freshness Benchmark" in report
    assert "| event_driven |" in report
    assert "| ttl_only |" in report
    # The TTL extrapolation must anchor on the measured ttl_only arm.
    assert "Event-driven invalidation measured" in report
    # The invalidation scan is decoupled from webhook registration
    # (BACKLOG #25): the report must state the numbers hold with zero
    # webhooks and keep the resolved-coupling history.
    assert "regardless of webhook registration" in report
    assert "zero webhooks registered" in report
    assert "BACKLOG #25" in report
    assert "runtime artifact" in report.lower()
    assert ".artifacts/freshness/freshness-benchmark.md" in report
    assert "date-stamped" in report
    assert "pre-S7 demo" in report
    assert "does not represent current production invalidation wiring" in report
    assert "production configuration" not in report.lower()
    assert "production default" not in report.lower()


def test_demo_freshness_docs_name_owner_and_snapshot_lifecycle():
    current = " ".join(
        (ROOT / "docs" / "perf" / "freshness-benchmark.md").read_text(encoding="utf-8").split()
    )
    archived = " ".join(
        (ROOT / "docs" / "archive" / "performance" / "freshness-benchmark-2026-06-06.md")
        .read_text(encoding="utf-8")
        .split()
    )
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "Demo freshness benchmark artifact lifecycle" in current
    assert "`python scripts/benchmark_freshness.py`" in current
    assert "`.artifacts/freshness/freshness-benchmark.md`" in current
    assert "`.artifacts/freshness/current.json`" in current
    assert "archive/performance/freshness-benchmark-2026-06-06.md" in current
    assert "Original path: *docs/perf/freshness-benchmark.md*" in archived
    assert "Content type: historical generated demo freshness benchmark snapshot" in archived
    assert "Generated: `2026-06-06T10:10:41+03:00`" in archived
    assert "| Demo freshness benchmark |" in docs_hub
    assert ".artifacts/freshness/freshness-benchmark.md" in docs_hub
    assert "python scripts/benchmark_freshness.py" in contributing
    assert ".artifacts/freshness/freshness-benchmark.md" in contributing
    assert "Demo freshness benchmark snapshot/lifecycle sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan


def test_archived_demo_freshness_body_preserves_the_original_git_blob():
    archived = (
        ROOT / "docs" / "archive" / "performance" / "freshness-benchmark-2026-06-06.md"
    ).read_bytes()
    marker = b"<!-- ARCHIVE BODY START -->"
    _metadata, original_tail = archived.split(marker, maxsplit=1)
    original = b"# Event-to-Metric Freshness Benchmark" + original_tail
    git_blob = b"blob " + str(len(original)).encode("ascii") + b"\0" + original

    assert hashlib.sha1(git_blob, usedforsecurity=False).hexdigest() == ARCHIVED_DEMO_FRESHNESS_BLOB


def test_build_report_skips_extrapolation_without_samples():
    arms = [
        {"arm": "event_driven", "iterations": 0, "timeouts": 0, "samples_ms": []},
        {"arm": "no_cache", "iterations": 0, "timeouts": 0, "samples_ms": []},
    ]

    report = benchmark_freshness.build_report(
        generated_at="2026-06-06T00:00:00+03:00",
        system_info={"os": "TestOS", "cpu": "TestCPU", "cpu_count": "8", "python": "3.13.7"},
        metric="revenue",
        window="24h",
        poll_interval_ms=25,
        ttl_only_ttl_seconds=5,
        arms=arms,
    )

    assert "Event-driven invalidation measured" not in report
    assert "| event_driven |" in report
    assert "n/a" in report


def test_format_ms_switches_to_seconds_at_one_thousand():
    assert benchmark_freshness.format_ms(180.0) == "180 ms"
    assert benchmark_freshness.format_ms(2150.0) == "2.15 s"
