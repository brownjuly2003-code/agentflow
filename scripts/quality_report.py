from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import mutation_report as mutation_report_module  # noqa: E402
from scripts.security_check import (  # noqa: E402
    load_project_dependencies,
    load_requirements,
    resolve_command,
    write_requirements,
)
from tests.load.thresholds import LOAD_PROFILE  # noqa: E402


OUTPUT_PATH = PROJECT_ROOT / "docs" / "quality.md"
NODEIDS_CACHE_PATH = PROJECT_ROOT / ".pytest_cache" / "v" / "cache" / "nodeids"
SECURITY_TIMEOUT_SECONDS = 300
COLLECTION_TIMEOUT_SECONDS = 120

TEST_SUITES = {
    "Unit": ("tests/unit",),
    "Integration": ("tests/integration",),
    "E2E": ("tests/e2e",),
    "Property-based": ("tests/property",),
    "Contract": ("tests/contract",),
    "Chaos": ("tests/chaos",),
}

PERFORMANCE_ROWS = (
    ("Entity lookup", ("GET /v1/entity/order/{id}", "GET /v1/entity/user/{id}", "GET /v1/entity/product/{id}"), 50.0),
    ("NL query", ("POST /v1/query",), 500.0),
    ("Batch", ("POST /v1/batch",), 200.0),
)


@dataclass
class SuiteMetric:
    name: str
    count: int
    source: str
    detail: str | None = None


@dataclass
class SecurityMetric:
    name: str
    status: str
    detail: str


@dataclass
class PerformanceMetric:
    name: str
    status: str
    detail: str


@dataclass
class MutationMetric:
    module_name: str
    status: str
    detail: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    return parser.parse_args()


def run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def load_cached_nodeids() -> list[str]:
    if not NODEIDS_CACHE_PATH.exists():
        return []
    try:
        payload = json.loads(NODEIDS_CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [nodeid for nodeid in payload if isinstance(nodeid, str)]


def collect_suite_metric(name: str, paths: tuple[str, ...]) -> SuiteMetric:
    result = run_command(
        [sys.executable, "-m", "pytest", *paths, "-q", "--collect-only"],
        timeout=COLLECTION_TIMEOUT_SECONDS,
    )
    nodeids = [
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and line.strip() and " tests collected" not in line
    ]
    if nodeids:
        return SuiteMetric(name=name, count=len(nodeids), source="pytest --collect-only")

    summary_match = re.search(r"(\d+)\s+tests?\s+collected", result.stdout)
    if summary_match:
        return SuiteMetric(
            name=name,
            count=int(summary_match.group(1)),
            source="pytest --collect-only summary",
        )

    cached_nodeids = load_cached_nodeids()
    cached_count = sum(
        1
        for nodeid in cached_nodeids
        if any(nodeid.startswith(f"{path}/") for path in paths)
    )
    if cached_count:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return SuiteMetric(
            name=name,
            count=cached_count,
            source=".pytest_cache/v/cache/nodeids",
            detail=detail[-1] if detail else None,
        )

    detail = (result.stderr or result.stdout).strip().splitlines()
    return SuiteMetric(
        name=name,
        count=0,
        source="no collection data",
        detail=detail[-1] if detail else None,
    )


def load_coverage_detail() -> str:
    coverage_path = PROJECT_ROOT / "coverage.xml"
    if not coverage_path.exists():
        return "coverage.xml not found"
    root = ET.parse(coverage_path).getroot()
    line_rate = root.attrib.get("line-rate")
    lines_valid = root.attrib.get("lines-valid")
    lines_covered = root.attrib.get("lines-covered")
    if line_rate is None:
        return "coverage.xml missing line-rate"
    percentage = float(line_rate) * 100
    if lines_valid and lines_covered:
        return (
            f"{percentage:.2f}% line coverage "
            f"({lines_covered}/{lines_valid} lines, source `coverage.xml`)"
        )
    return f"{percentage:.2f}% line coverage (source `coverage.xml`)"


def build_requirement_files(temp_path: Path) -> tuple[Path, Path]:
    main_requirements = temp_path / "requirements-main.txt"
    sdk_requirements = temp_path / "requirements-sdk.txt"
    write_requirements(
        main_requirements,
        load_project_dependencies(PROJECT_ROOT / "pyproject.toml")
        + load_requirements(PROJECT_ROOT / "requirements.txt"),
    )
    write_requirements(
        sdk_requirements,
        load_project_dependencies(PROJECT_ROOT / "sdk" / "pyproject.toml"),
    )
    return main_requirements, sdk_requirements


def parse_json_output(text: str) -> dict | list | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        for token in ("{", "["):
            index = stripped.find(token)
            if index == -1:
                continue
            try:
                return json.loads(stripped[index:])
            except json.JSONDecodeError:
                continue
    return None


def collect_bandit_metric() -> SecurityMetric:
    result = run_command(
        [
            sys.executable,
            "-m",
            "bandit",
            "-r",
            "src",
            "sdk",
            "--ini",
            ".bandit",
            "--severity-level",
            "medium",
            "-q",
            "-f",
            "json",
        ],
        timeout=SECURITY_TIMEOUT_SECONDS,
    )
    payload = parse_json_output(result.stdout)
    if payload is None:
        detail = (result.stderr or result.stdout).strip() or "bandit output was empty"
        return SecurityMetric("Bandit", "WARN", detail)

    assert isinstance(payload, dict)
    findings = payload.get("results") or []
    count = len(findings)
    status = "PASS" if count == 0 and result.returncode == 0 else "FAIL"
    return SecurityMetric(
        "Bandit",
        status,
        f"{count} medium/high finding(s) (`python -m bandit ...`)",
    )


def collect_safety_metric(main_requirements: Path, sdk_requirements: Path) -> SecurityMetric:
    try:
        command = resolve_command("safety")
    except FileNotFoundError as error:
        return SecurityMetric("Safety", "WARN", str(error))

    result = run_command(
        [
            command,
            "check",
            "--json",
            "-r",
            str(main_requirements),
            "-r",
            str(sdk_requirements),
        ],
        timeout=SECURITY_TIMEOUT_SECONDS,
    )
    payload = parse_json_output(result.stdout)
    if payload is None:
        detail = (result.stderr or result.stdout).strip() or "safety output was empty"
        return SecurityMetric("Safety", "WARN", detail)

    vulnerabilities = 0
    if isinstance(payload, list):
        vulnerabilities = len(payload)
    elif isinstance(payload, dict):
        vulnerabilities = len(payload.get("vulnerabilities") or payload.get("affected_packages") or [])

    status = "PASS" if vulnerabilities == 0 and result.returncode == 0 else "FAIL"
    return SecurityMetric(
        "Safety",
        status,
        f"{vulnerabilities} known vulnerability entries (`safety check`)",
    )


def collect_pip_audit_metric(main_requirements: Path, sdk_requirements: Path) -> SecurityMetric:
    try:
        command = resolve_command("pip-audit")
    except FileNotFoundError as error:
        return SecurityMetric("pip-audit", "WARN", str(error))

    result = run_command(
        [
            command,
            "-r",
            str(main_requirements),
            "-r",
            str(sdk_requirements),
            "--progress-spinner",
            "off",
            "--format",
            "json",
        ],
        timeout=SECURITY_TIMEOUT_SECONDS,
    )
    payload = parse_json_output(result.stdout)
    if payload is None:
        detail = (result.stderr or result.stdout).strip() or "pip-audit output was empty"
        return SecurityMetric("pip-audit", "WARN", detail)

    assert isinstance(payload, dict)
    dependencies = payload.get("dependencies") or []
    vulnerabilities = sum(len(dependency.get("vulns") or []) for dependency in dependencies)
    status = "PASS" if vulnerabilities == 0 and result.returncode == 0 else "FAIL"
    return SecurityMetric(
        "pip-audit",
        status,
        f"{vulnerabilities} known vulnerability entries (`pip-audit`)",
    )


def collect_trivy_metric() -> SecurityMetric:
    dockerfile_path = PROJECT_ROOT / "Dockerfile.api"
    if not dockerfile_path.exists():
        return SecurityMetric("Trivy", "WARN", "`Dockerfile.api` not found")

    try:
        command = resolve_command("trivy")
    except FileNotFoundError:
        return SecurityMetric("Trivy", "WARN", "`trivy` CLI not found")

    image_name = "agentflow-api:quality-scan"
    build_result = run_command(
        ["docker", "build", "-t", image_name, "-f", str(dockerfile_path), "."],
        timeout=SECURITY_TIMEOUT_SECONDS,
    )
    if build_result.returncode != 0:
        detail = (build_result.stderr or build_result.stdout).strip() or "docker build failed"
        return SecurityMetric("Trivy", "WARN", detail)

    result = run_command(
        [command, "image", "--format", "json", "--severity", "HIGH,CRITICAL", image_name],
        timeout=SECURITY_TIMEOUT_SECONDS,
    )
    payload = parse_json_output(result.stdout)
    if payload is None:
        detail = (result.stderr or result.stdout).strip() or "trivy output was empty"
        return SecurityMetric("Trivy", "WARN", detail)

    assert isinstance(payload, dict)
    findings = 0
    for item in payload.get("Results") or []:
        findings += sum(
            1
            for vulnerability in item.get("Vulnerabilities") or []
            if vulnerability.get("Severity") in {"HIGH", "CRITICAL"}
        )
    status = "PASS" if findings == 0 and result.returncode == 0 else "FAIL"
    return SecurityMetric(
        "Trivy",
        status,
        f"{findings} HIGH/CRITICAL image vulnerabilities (`trivy image`)",
    )


def collect_security_metrics() -> list[SecurityMetric]:
    with tempfile.TemporaryDirectory(prefix="agentflow-quality-security-") as temp_dir:
        main_requirements, sdk_requirements = build_requirement_files(Path(temp_dir))
        return [
            collect_bandit_metric(),
            collect_safety_metric(main_requirements, sdk_requirements),
            collect_pip_audit_metric(main_requirements, sdk_requirements),
            collect_trivy_metric(),
        ]


def load_latest_load_report() -> tuple[Path | None, dict]:
    candidates = [
        PROJECT_ROOT / ".artifacts" / "load" / "results.json",
        PROJECT_ROOT / "tests" / "load" / "results.json",
        PROJECT_ROOT / "docs" / "benchmark-baseline.json",
    ]
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return None, {}
    latest = max(existing, key=lambda path: path.stat().st_mtime)
    return latest, json.loads(latest.read_text(encoding="utf-8"))


def render_performance_metric(
    name: str,
    endpoints: tuple[str, ...],
    threshold_ms: float,
    report: dict,
) -> PerformanceMetric:
    endpoint_rows = report.get("endpoints") or {}
    values = [
        float(endpoint_rows[endpoint]["p95_ms"])
        for endpoint in endpoints
        if endpoint in endpoint_rows and "p95_ms" in endpoint_rows[endpoint]
    ]
    if not values:
        return PerformanceMetric(
            name,
            "WARN",
            f"no load-test sample collected (threshold {threshold_ms:.1f} ms)",
        )

    p95_ms = max(values)
    status = "PASS" if p95_ms <= threshold_ms else "FAIL"
    return PerformanceMetric(
        name,
        status,
        f"p95 {p95_ms:.1f} ms vs threshold {threshold_ms:.1f} ms",
    )


def load_performance_metrics() -> tuple[str, list[PerformanceMetric], str]:
    report_path, report = load_latest_load_report()
    if report_path is None:
        return "unknown", [], "no load report found"

    profile = report.get("load_profile") or LOAD_PROFILE
    profile_label = (
        f"{profile.get('users', LOAD_PROFILE['users'])} users, "
        f"spawn rate {profile.get('spawn_rate', LOAD_PROFILE['spawn_rate'])}/s, "
        f"duration {profile.get('run_time', LOAD_PROFILE['run_time'])}"
    )
    metrics = [
        render_performance_metric(name, endpoints, threshold_ms, report)
        for name, endpoints, threshold_ms in PERFORMANCE_ROWS
    ]
    return profile_label, metrics, f"source `{report_path.relative_to(PROJECT_ROOT).as_posix()}`"


def load_hypothesis_profile_detail() -> str:
    conftest_path = PROJECT_ROOT / "tests" / "property" / "conftest.py"
    if not conftest_path.exists():
        return "Hypothesis profile file not found"
    content = conftest_path.read_text(encoding="utf-8")
    ci_match = re.search(r'"ci".*?max_examples=(\d+)', content, re.DOTALL)
    dev_match = re.search(r'"dev".*?max_examples=(\d+)', content, re.DOTALL)
    ci_examples = ci_match.group(1) if ci_match else "?"
    dev_examples = dev_match.group(1) if dev_match else "?"
    return f"Hypothesis profiles: ci={ci_examples}, dev={dev_examples}"


def load_chaos_detail() -> str:
    candidates = [
        PROJECT_ROOT / ".artifacts" / "chaos" / "ci-chaos-summary.json",
        PROJECT_ROOT / ".artifacts" / "chaos" / "chaos-summary.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary = payload.get("summary") or {}
        return (
            f"{summary.get('passed', 0)} passed, "
            f"{summary.get('failed', 0)} failed, "
            f"{summary.get('errors', 0)} errors "
            f"(source `{path.relative_to(PROJECT_ROOT).as_posix()}`)"
        )
    return "no chaos summary artifact found"


def load_mutation_metrics() -> tuple[list[MutationMetric], str]:
    results_dir = PROJECT_ROOT / "mutants"
    overall_path = results_dir / "mutmut-cicd-stats.json"
    overall = (
        json.loads(overall_path.read_text(encoding="utf-8-sig"))
        if overall_path.exists()
        else None
    )
    module_targets = getattr(mutation_report_module, "MODULE_TARGETS", {})
    if not module_targets:
        legacy_thresholds = getattr(mutation_report_module, "THRESHOLDS", {})
        module_targets = {
            module_path: type("LegacyTarget", (), {"threshold": threshold})()
            for module_path, threshold in legacy_thresholds.items()
        }
    metrics: list[MutationMetric] = []
    for module_path, target in module_targets.items():
        result = mutation_report_module.load_module_result(results_dir, module_path, target)
        threshold = result.threshold
        if result.total_scored == 0:
            status = "WARN"
            detail = f"no scored mutants yet (threshold {threshold:.0%})"
        else:
            status = "PASS" if result.score >= threshold else "FAIL"
            detail = (
                f"{result.score:.1%} score "
                f"({result.killed} killed / {result.total_scored} scored, threshold {threshold:.0%})"
            )
        if result.problematic_mutants:
            detail += f"; {len(result.problematic_mutants)} problematic mutant(s)"
        if result.errors:
            detail += f"; {'; '.join(result.errors)}"
        metrics.append(
            MutationMetric(
                module_name=module_path.name,
                status=status,
                detail=detail,
            )
        )

    if overall is None:
        overall_detail = "overall mutmut summary not found"
    else:
        overall_detail = (
            f"killed={overall.get('killed', 0)}, "
            f"survived={overall.get('survived', 0)}, "
            f"total={overall.get('total', 0)} "
            f"(source `mutants/mutmut-cicd-stats.json`)"
        )
    return metrics, overall_detail


def render_markdown(
    generated_at: str,
    suite_metrics: list[SuiteMetric],
    coverage_detail: str,
    security_metrics: list[SecurityMetric],
    performance_profile: str,
    performance_metrics: list[PerformanceMetric],
    performance_source: str,
    mutation_metrics: list[MutationMetric],
    mutation_overall: str,
) -> str:
    lines = [
        "# AgentFlow Quality Report",
        "",
        f"- Generated: `{generated_at}`",
        "- Generator: `python scripts/quality_report.py`",
        "",
        "## Test Suites",
    ]

    for metric in suite_metrics:
        detail = f" ({metric.detail})" if metric.detail else ""
        lines.append(f"- {metric.name}: {metric.count} collected ({metric.source}){detail}")
    lines.append(f"- Coverage: {coverage_detail}")
    lines.append(f"- Property detail: {load_hypothesis_profile_detail()}")
    lines.append(f"- Chaos latest run: {load_chaos_detail()}")
    lines.extend(
        [
            "",
            "## Security",
        ]
    )
    for metric in security_metrics:
        lines.append(f"- {metric.name}: {metric.status} - {metric.detail}")
    lines.extend(
        [
            "",
            f"## Performance (p95, {performance_profile})",
        ]
    )
    if performance_metrics:
        for metric in performance_metrics:
            lines.append(f"- {metric.name}: {metric.status} - {metric.detail}")
    else:
        lines.append(f"- No performance metrics available ({performance_source})")
    lines.append(f"- Evidence: {performance_source}")
    lines.extend(
        [
            "",
            "## Mutation Score",
        ]
    )
    for metric in mutation_metrics:
        lines.append(f"- {metric.module_name}: {metric.status} - {metric.detail}")
    lines.append(f"- Overall: {mutation_overall}")
    lines.extend(
        [
            "",
            "## Notes",
            "- Missing tools or fresh artifacts are reported explicitly instead of placeholders.",
            "- This report uses local repo state plus the newest local quality artifacts it can find.",
            "",
            f"_Last updated automatically by `scripts/quality_report.py` at `{generated_at}`._",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    suite_metrics = [
        collect_suite_metric(name, paths)
        for name, paths in TEST_SUITES.items()
    ]
    coverage_detail = load_coverage_detail()
    security_metrics = collect_security_metrics()
    performance_profile, performance_metrics, performance_source = load_performance_metrics()
    mutation_metrics, mutation_overall = load_mutation_metrics()
    report = render_markdown(
        generated_at=generated_at,
        suite_metrics=suite_metrics,
        coverage_detail=coverage_detail,
        security_metrics=security_metrics,
        performance_profile=performance_profile,
        performance_metrics=performance_metrics,
        performance_source=performance_source,
        mutation_metrics=mutation_metrics,
        mutation_overall=mutation_overall,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8", newline="\n")
    print(f"Wrote {output_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
