from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_report(input_path: Path) -> dict[str, Any]:
    if not input_path.exists():
        return {
            "status": "missing",
            "path": str(input_path),
            "tests": [],
            "summary": {},
            "exitcode": 1,
        }
    return json.loads(input_path.read_text(encoding="utf-8"))


def _test_duration_seconds(test_case: dict[str, Any]) -> float:
    total = 0.0
    for stage_name in ("setup", "call", "teardown"):
        stage = test_case.get(stage_name)
        if isinstance(stage, dict):
            total += float(stage.get("duration", 0.0) or 0.0)
    return round(total, 3)


def _scenario_outcome(test_cases: list[dict[str, Any]]) -> str:
    outcomes = [case["outcome"] for case in test_cases]
    if any(outcome in {"failed", "error"} for outcome in outcomes):
        return "failed"
    if outcomes and all(outcome == "skipped" for outcome in outcomes):
        return "skipped"
    return "passed"


def build_report(pytest_json: dict[str, Any], source: Path) -> dict[str, Any]:
    raw_tests = pytest_json.get("tests", [])
    scenario_map: dict[str, dict[str, Any]] = {}

    for test_case in raw_tests:
        metadata = test_case.get("metadata") or {}
        scenario_name = metadata.get("scenario") or test_case.get("nodeid", "unknown")
        scenario = scenario_map.setdefault(
            scenario_name,
            {
                "scenario": scenario_name,
                "expectation": metadata.get("expectation", "unspecified"),
                "tests": [],
            },
        )
        scenario["tests"].append(
            {
                "nodeid": test_case.get("nodeid", "unknown"),
                "outcome": test_case.get("outcome", "unknown"),
                "duration_seconds": _test_duration_seconds(test_case),
            }
        )

    scenarios = []
    for scenario in scenario_map.values():
        scenario["outcome"] = _scenario_outcome(scenario["tests"])
        scenario["test_count"] = len(scenario["tests"])
        scenarios.append(scenario)

    scenarios.sort(key=lambda item: item["scenario"])

    summary = pytest_json.get("summary", {})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "status": "ok" if pytest_json.get("status") != "missing" else "missing",
        "exitcode": int(pytest_json.get("exitcode", 1)),
        "ci_mode": any(
            bool((test_case.get("metadata") or {}).get("ci_mode"))
            for test_case in raw_tests
        ),
        "summary": {
            "collected": int(summary.get("collected", 0)),
            "total": int(summary.get("total", 0)),
            "passed": int(summary.get("passed", 0)),
            "failed": int(summary.get("failed", 0)),
            "errors": int(summary.get("error", 0) or summary.get("errors", 0)),
            "skipped": int(summary.get("skipped", 0)),
        },
        "scenario_summary": {
            "total": len(scenarios),
            "passed": sum(1 for scenario in scenarios if scenario["outcome"] == "passed"),
            "failed": sum(1 for scenario in scenarios if scenario["outcome"] == "failed"),
            "skipped": sum(1 for scenario in scenarios if scenario["outcome"] == "skipped"),
        },
        "scenarios": scenarios,
    }


def build_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    scenario_summary = report["scenario_summary"]
    lines = [
        "# Chaos Report",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- source: `{report['source']}`",
        f"- exitcode: {report['exitcode']}",
        f"- ci_mode: {report['ci_mode']}",
        "",
        "## Totals",
        "",
        f"- collected: {summary['collected']}",
        f"- total: {summary['total']}",
        f"- passed: {summary['passed']}",
        f"- failed: {summary['failed']}",
        f"- errors: {summary['errors']}",
        f"- skipped: {summary['skipped']}",
        "",
        "## Scenario SLO",
        "",
        f"- scenarios_total: {scenario_summary['total']}",
        f"- scenarios_passed: {scenario_summary['passed']}",
        f"- scenarios_failed: {scenario_summary['failed']}",
        f"- scenarios_skipped: {scenario_summary['skipped']}",
        "",
    ]

    for scenario in report["scenarios"]:
        lines.append(
            f"- [{scenario['outcome']}] {scenario['scenario']} -> "
            f"{scenario['expectation']} ({scenario['test_count']} test(s))"
        )
        for test_case in scenario["tests"]:
            lines.append(
                f"  - [{test_case['outcome']}] {test_case['nodeid']} "
                f"({test_case['duration_seconds']}s)"
            )

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a compact chaos test report from pytest JSON.")
    parser.add_argument(
        "--input",
        default="chaos-report.json",
        help="Path to the pytest JSON report produced by pytest-json-report.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to write the JSON summary report.",
    )
    parser.add_argument(
        "--markdown",
        default=None,
        help="Optional path to write the markdown summary report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    report = build_report(_load_report(input_path), input_path)
    markdown = build_markdown(report)
    if args.output:
        Path(args.output).write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if args.markdown:
        Path(args.markdown).write_text(markdown, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(markdown)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
