from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


REGRESSION_THRESHOLD = 0.20
IMPROVEMENT_THRESHOLD = 0.10


@dataclass(frozen=True)
class EndpointMetrics:
    p50: float
    p95: float
    p99: float
    error_rate: float


@dataclass(frozen=True)
class EndpointComparison:
    endpoint: str
    baseline: EndpointMetrics
    current: EndpointMetrics | None
    delta: float | None
    status: str


@dataclass(frozen=True)
class ComparisonOutcome:
    regressions: list[str]
    improvements: list[str]
    extra_endpoints: list[str]
    comparisons: list[EndpointComparison]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--report-out", type=Path)
    parser.add_argument("--git-sha")
    return parser.parse_args()


def load_report(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Benchmark file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc


def _require_number(payload: dict[str, object], keys: tuple[str, ...], label: str) -> float:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError) as exc:
                raise SystemExit(f"Invalid numeric value for {label}.{key}") from exc
    raise SystemExit(f"Missing metric for {label}: expected one of {', '.join(keys)}")


def _load_endpoint_metrics(payload: object, label: str) -> EndpointMetrics:
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected object for {label}")
    return EndpointMetrics(
        p50=_require_number(payload, ("p50", "p50_ms", "p50_latency_ms"), label),
        p95=_require_number(payload, ("p95", "p95_ms", "p95_latency_ms"), label),
        p99=_require_number(payload, ("p99", "p99_ms", "p99_latency_ms"), label),
        error_rate=_load_error_rate(payload, label),
    )


def _load_error_rate(payload: dict[str, object], label: str) -> float:
    if "error_rate" in payload:
        return _require_number(payload, ("error_rate",), label)
    if "fail_ratio" in payload:
        return _require_number(payload, ("fail_ratio",), label)
    if "failure_rate_percent" in payload:
        return _require_number(payload, ("failure_rate_percent",), label) / 100.0
    raise SystemExit(
        f"Missing metric for {label}: expected one of error_rate, fail_ratio, failure_rate_percent"
    )


def load_endpoints(report: dict[str, object], label: str) -> dict[str, EndpointMetrics]:
    endpoints = report.get("endpoints")
    if not isinstance(endpoints, dict):
        raise SystemExit(f"Expected 'endpoints' object in {label}")

    normalized: dict[str, EndpointMetrics] = {}
    for endpoint, payload in endpoints.items():
        if not isinstance(endpoint, str):
            raise SystemExit(f"Endpoint name must be string in {label}")
        normalized[endpoint] = _load_endpoint_metrics(payload, f"{label} endpoint {endpoint!r}")
    return normalized


def _format_delta(delta: float) -> str:
    return f"{delta:+.1%}"


def _calculate_delta(baseline_p95: float, current_p95: float) -> float:
    if baseline_p95 == 0:
        return 0.0 if current_p95 == 0 else float("inf")
    return (current_p95 - baseline_p95) / baseline_p95


def compare_reports(current: dict[str, object], baseline: dict[str, object]) -> ComparisonOutcome:
    current_endpoints = load_endpoints(current, "current report")
    baseline_endpoints = load_endpoints(baseline, "baseline report")

    regressions: list[str] = []
    improvements: list[str] = []
    comparisons: list[EndpointComparison] = []

    for endpoint in sorted(baseline_endpoints):
        baseline_metrics = baseline_endpoints[endpoint]
        current_metrics = current_endpoints.get(endpoint)
        if current_metrics is None:
            regressions.append(f"{endpoint}: missing in current results")
            comparisons.append(
                EndpointComparison(
                    endpoint=endpoint,
                    baseline=baseline_metrics,
                    current=None,
                    delta=None,
                    status="missing",
                )
            )
            continue

        delta = _calculate_delta(baseline_metrics.p95, current_metrics.p95)
        status = "stable"
        if delta > REGRESSION_THRESHOLD:
            status = "regression"
            regressions.append(
                f"{endpoint}: p95 {baseline_metrics.p95:.1f}ms -> "
                f"{current_metrics.p95:.1f}ms ({_format_delta(delta)}) REGRESSION"
            )
        elif delta < -IMPROVEMENT_THRESHOLD:
            status = "improvement"
            improvements.append(
                f"{endpoint}: p95 {baseline_metrics.p95:.1f}ms -> "
                f"{current_metrics.p95:.1f}ms ({_format_delta(delta)}) IMPROVEMENT"
            )

        comparisons.append(
            EndpointComparison(
                endpoint=endpoint,
                baseline=baseline_metrics,
                current=current_metrics,
                delta=delta,
                status=status,
            )
        )

    extra_endpoints = sorted(set(current_endpoints) - set(baseline_endpoints))
    return ComparisonOutcome(
        regressions=regressions,
        improvements=improvements,
        extra_endpoints=extra_endpoints,
        comparisons=comparisons,
    )


def serialize_baseline(
    current: dict[str, object],
    *,
    git_sha: str | None = None,
    generated_at: str | None = None,
) -> dict[str, object]:
    current_endpoints = load_endpoints(current, "current report")
    short_sha = (git_sha or os.environ.get("GITHUB_SHA") or "unknown")[:7]
    baseline_payload = {
        "generated_at": generated_at
        or str(current.get("generated_at") or datetime.now(UTC).isoformat()),
        "git_sha": short_sha,
        "endpoints": {},
    }
    for endpoint in sorted(current_endpoints):
        metrics = current_endpoints[endpoint]
        baseline_payload["endpoints"][endpoint] = {
            "p50": metrics.p50,
            "p95": metrics.p95,
            "p99": metrics.p99,
            "error_rate": metrics.error_rate,
        }
    return baseline_payload


def write_updated_baseline(
    baseline_path: Path,
    current: dict[str, object],
    *,
    git_sha: str | None = None,
    generated_at: str | None = None,
) -> None:
    baseline_payload = serialize_baseline(
        current,
        git_sha=git_sha,
        generated_at=generated_at,
    )
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(baseline_payload, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def render_report(
    outcome: ComparisonOutcome,
    *,
    baseline_updated: bool = False,
) -> str:
    status = "FAIL" if outcome.regressions else "PASS"
    if baseline_updated:
        status = "PASS (baseline updated)"

    lines = [
        "## Performance Regression Check",
        "",
        f"- Status: `{status}`",
        f"- Regression threshold: `>{REGRESSION_THRESHOLD:.0%}` p95 growth",
        f"- Improvement threshold: `>{IMPROVEMENT_THRESHOLD:.0%}` p95 reduction",
        "",
        "| Endpoint | Baseline p95 | Current p95 | Delta | Status |",
        "| --- | ---: | ---: | ---: | --- |",
    ]

    for comparison in outcome.comparisons:
        current_p95 = "missing" if comparison.current is None else f"{comparison.current.p95:.1f} ms"
        delta = "-" if comparison.delta is None else _format_delta(comparison.delta)
        lines.append(
            f"| {comparison.endpoint} | {comparison.baseline.p95:.1f} ms | "
            f"{current_p95} | {delta} | {comparison.status.upper()} |"
        )

    if outcome.extra_endpoints:
        lines.extend(
            [
                "",
                "### Extra Endpoints",
                *[f"- {endpoint}" for endpoint in outcome.extra_endpoints],
            ]
        )

    if outcome.regressions:
        lines.extend(
            [
                "",
                "### Regressions",
                *[f"- {entry}" for entry in outcome.regressions],
            ]
        )
    if outcome.improvements:
        lines.extend(
            [
                "",
                "### Improvements",
                *[f"- {entry}" for entry in outcome.improvements],
            ]
        )
    if not outcome.regressions and not outcome.improvements:
        lines.extend(["", "### Summary", "- No p95 regressions or major improvements detected."])

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    current = load_report(args.current)
    baseline = load_report(args.baseline)
    outcome = compare_reports(current, baseline)
    baseline_updated = False

    if args.update_baseline and outcome.improvements and not outcome.regressions:
        write_updated_baseline(
            args.baseline,
            current,
            git_sha=args.git_sha,
            generated_at=current.get("generated_at")
            if isinstance(current.get("generated_at"), str)
            else None,
        )
        baseline_updated = True

    report = render_report(outcome, baseline_updated=baseline_updated)
    if args.report_out is not None:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(report, encoding="utf-8", newline="\n")
    sys.stdout.write(report)

    if outcome.regressions:
        return 1
    return 0


def test_compare_reports_regressions_improvements_and_missing_endpoints():
    baseline = {
        "generated_at": "2026-04-12T18:04:35+00:00",
        "git_sha": "abc1234",
        "endpoints": {
            "GET /v1/entity/order/{id}": {
                "p50": 20.0,
                "p95": 100.0,
                "p99": 140.0,
                "error_rate": 0.0,
            },
            "GET /v1/health": {
                "p50": 5.0,
                "p95": 10.0,
                "p99": 12.0,
                "error_rate": 0.0,
            },
            "POST /v1/query": {
                "p50": 250.0,
                "p95": 500.0,
                "p99": 700.0,
                "error_rate": 0.01,
            },
        },
    }
    current = {
        "generated_at": "2026-04-12T19:04:35+00:00",
        "endpoints": {
            "GET /v1/entity/order/{id}": {
                "p50_ms": 21.0,
                "p95_ms": 130.0,
                "p99_ms": 145.0,
                "fail_ratio": 0.0,
            },
            "GET /v1/entity/product/{id}": {
                "p50_ms": 18.0,
                "p95_ms": 30.0,
                "p99_ms": 35.0,
                "fail_ratio": 0.0,
            },
            "POST /v1/query": {
                "p50_ms": 180.0,
                "p95_ms": 400.0,
                "p99_ms": 600.0,
                "fail_ratio": 0.005,
            },
        },
    }

    outcome = compare_reports(current, baseline)

    assert outcome.regressions == [
        "GET /v1/entity/order/{id}: p95 100.0ms -> 130.0ms (+30.0%) REGRESSION",
        "GET /v1/health: missing in current results",
    ]
    assert outcome.improvements == [
        "POST /v1/query: p95 500.0ms -> 400.0ms (-20.0%) IMPROVEMENT",
    ]
    assert outcome.extra_endpoints == ["GET /v1/entity/product/{id}"]


def test_write_updated_baseline_normalizes_load_results(tmp_path):
    baseline_path = tmp_path / "baseline.json"
    current = {
        "generated_at": "2026-04-12T18:04:35+00:00",
        "endpoints": {
            "GET /v1/entity/order/{id}": {
                "p50_ms": 26000.0,
                "p95_ms": 26000.0,
                "p99_ms": 26000.0,
                "fail_ratio": 0.0,
            },
            "POST /v1/query": {
                "p50_ms": 40000.0,
                "p95_ms": 40000.0,
                "p99_ms": 40000.0,
                "fail_ratio": 0.0,
            },
        },
    }

    write_updated_baseline(
        baseline_path,
        current,
        git_sha="d7675fe",
        generated_at="2026-04-12T18:04:35+00:00",
    )

    assert json.loads(baseline_path.read_text(encoding="utf-8")) == {
        "generated_at": "2026-04-12T18:04:35+00:00",
        "git_sha": "d7675fe",
        "endpoints": {
            "GET /v1/entity/order/{id}": {
                "p50": 26000.0,
                "p95": 26000.0,
                "p99": 26000.0,
                "error_rate": 0.0,
            },
            "POST /v1/query": {
                "p50": 40000.0,
                "p95": 40000.0,
                "p99": 40000.0,
                "error_rate": 0.0,
            },
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
