import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ChartCase:
    chart_id: str
    chart_path: Path
    base_values: Path | None
    invalid_values: Path
    expected_error_tokens: tuple[tuple[str, ...], ...]


AGENTFLOW_CHART = ChartCase(
    chart_id="agentflow",
    chart_path=PROJECT_ROOT / "helm" / "agentflow",
    base_values=PROJECT_ROOT / "k8s" / "staging" / "values-staging.yaml",
    invalid_values=(
        PROJECT_ROOT / "tests" / "integration" / "fixtures" / "helm-values-invalid.yaml"
    ),
    expected_error_tokens=(
        ("unexpectedTopLevel", "additional propert", "not allowed"),
        ("replicaCount", "integer", "string"),
        ("service.port", "minimum", "1"),
    ),
)

KAFKA_CONNECT_CHART = ChartCase(
    chart_id="kafka-connect",
    chart_path=PROJECT_ROOT / "helm" / "kafka-connect",
    # The default values.yaml is already a valid baseline (kind-friendly,
    # connectors disabled, demo secret placeholders). No staging-overlay
    # exists yet because no production source has been onboarded.
    base_values=None,
    invalid_values=(
        PROJECT_ROOT
        / "tests"
        / "integration"
        / "fixtures"
        / "helm-values-kafka-connect-invalid.yaml"
    ),
    expected_error_tokens=(
        ("unexpectedTopLevel", "additional propert", "not allowed"),
        ("replicaCount", "integer", "string"),
        ("service.port", "minimum", "1"),
    ),
)

CHART_CASES = (AGENTFLOW_CHART, KAFKA_CONNECT_CHART)


pytestmark = [pytest.mark.integration, pytest.mark.kind]


def _run_helm(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["helm", *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def _values_args(case: ChartCase, *extra: Path) -> list[str]:
    args: list[str] = []
    for path in (case.base_values, *extra):
        if path is None:
            continue
        args.extend(["-f", str(path)])
    return args


def _assert_schema_validation_failed(
    result: subprocess.CompletedProcess[str], expected: tuple[tuple[str, ...], ...]
) -> None:
    output = _combined_output(result)
    normalized_lines = [
        line.lower().replace("/", ".").replace("must be greater than or equal to", "minimum")
        for line in output.splitlines()
    ]

    assert result.returncode != 0, output
    assert "values don't meet the specifications of the schema" in output.lower()
    for tokens in expected:
        normalized_tokens = tuple(token.lower() for token in tokens)
        assert any(
            all(token in line for token in normalized_tokens) for line in normalized_lines
        ), f"missing schema error tokens {tokens!r} in:\n{output}"


@pytest.mark.parametrize(
    "schema_output",
    [
        """values don't meet the specifications of the schema(s):
- (root): Additional property unexpectedTopLevel is not allowed
- replicaCount: Invalid type. Expected: integer, given: string
- service.port: Must be greater than or equal to 1
""",
        """values don't meet the specifications of the schema(s):
- additional properties 'unexpectedTopLevel' not allowed
- /replicaCount': got string, want integer
- /service/port': minimum: got 0, want 1
""",
    ],
    ids=("helm-3", "helm-4"),
)
def test_schema_failure_assertion_accepts_supported_helm_wording(schema_output: str):
    result = subprocess.CompletedProcess(
        args=["helm", "lint"],
        returncode=1,
        stdout="",
        stderr=schema_output,
    )

    _assert_schema_validation_failed(result, AGENTFLOW_CHART.expected_error_tokens)


@pytest.mark.parametrize("case", CHART_CASES, ids=lambda c: c.chart_id)
def test_helm_lint_accepts_baseline_values(case: ChartCase, kind_cluster):
    result = _run_helm("lint", str(case.chart_path), *_values_args(case))

    assert result.returncode == 0, _combined_output(result)


@pytest.mark.parametrize("case", CHART_CASES, ids=lambda c: c.chart_id)
def test_helm_lint_rejects_invalid_values(case: ChartCase, kind_cluster):
    result = _run_helm(
        "lint",
        str(case.chart_path),
        *_values_args(case, case.invalid_values),
    )

    _assert_schema_validation_failed(result, case.expected_error_tokens)


@pytest.mark.parametrize("case", CHART_CASES, ids=lambda c: c.chart_id)
def test_helm_install_dry_run_rejects_invalid_values(case: ChartCase, kind_cluster):
    release = f"{case.chart_id}-schema-invalid"
    result = _run_helm(
        "install",
        release,
        str(case.chart_path),
        *_values_args(case, case.invalid_values),
        "--dry-run",
    )

    _assert_schema_validation_failed(result, case.expected_error_tokens)


def test_remote_cluster_mode_documented():
    """The kind_cluster fixture also honours AGENTFLOW_KIND_CLUSTER. For
    external clusters (real staging), set KUBECONFIG / kubectl current
    context, then pass --no-create via AGENTFLOW_LIVE_REUSE_CLUSTER=1 so
    the fixture skips kind create/delete and validates against the active
    context. See conftest._reuse_external_cluster."""
    reuse_flag = os.getenv("AGENTFLOW_LIVE_REUSE_CLUSTER", "")
    # This guard just documents the contract; the actual behaviour is in
    # tests/integration/conftest.py::kind_cluster.
    assert reuse_flag in {"", "0", "1", "true", "false"}, (
        "AGENTFLOW_LIVE_REUSE_CLUSTER must be unset, 0/1, or true/false"
    )
