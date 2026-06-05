from __future__ import annotations

import sys
from decimal import Decimal

import pytest

from scripts import benchmark_freshness


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


def test_parse_args_defaults(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["benchmark_freshness.py"])

    args = benchmark_freshness.parse_args()

    assert args.iterations == 30
    assert args.metric == "revenue"
    assert args.window == "24h"
    assert args.ttl_only_ttl_seconds == 5


def test_build_order_event_passes_the_pipeline_validators():
    from src.quality.validators.schema_validator import validate_event
    from src.quality.validators.semantic_validator import validate_semantics

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
    # The zero-webhooks staleness caveat is part of the public methodology.
    assert "active webhook" in report
    assert "sentinel webhook" in report


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
