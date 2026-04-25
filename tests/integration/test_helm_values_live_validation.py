import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHART_PATH = PROJECT_ROOT / "helm" / "agentflow"
STAGING_VALUES_PATH = PROJECT_ROOT / "k8s" / "staging" / "values-staging.yaml"
INVALID_VALUES_PATH = (
    PROJECT_ROOT / "tests" / "integration" / "fixtures" / "helm-values-invalid.yaml"
)
EXPECTED_SCHEMA_ERRORS = [
    "(root): Additional property unexpectedTopLevel is not allowed",
    "replicaCount: Invalid type. Expected: integer, given: string",
    "service.port: Must be greater than or equal to 1",
]

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


def _assert_schema_validation_failed(result: subprocess.CompletedProcess[str]) -> None:
    output = _combined_output(result)

    assert result.returncode != 0, output
    assert "values don't meet the specifications of the schema" in output
    for expected in EXPECTED_SCHEMA_ERRORS:
        assert expected in output


def test_helm_lint_accepts_staging_values(kind_cluster):
    result = _run_helm("lint", str(CHART_PATH), "-f", str(STAGING_VALUES_PATH))

    assert result.returncode == 0, _combined_output(result)


def test_helm_lint_rejects_invalid_values(kind_cluster):
    result = _run_helm(
        "lint",
        str(CHART_PATH),
        "-f",
        str(STAGING_VALUES_PATH),
        "-f",
        str(INVALID_VALUES_PATH),
    )

    _assert_schema_validation_failed(result)


def test_helm_install_dry_run_rejects_invalid_values(kind_cluster):
    result = _run_helm(
        "install",
        "agentflow-schema-invalid",
        str(CHART_PATH),
        "-f",
        str(STAGING_VALUES_PATH),
        "-f",
        str(INVALID_VALUES_PATH),
        "--dry-run",
    )

    _assert_schema_validation_failed(result)
