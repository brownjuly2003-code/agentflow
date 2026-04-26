import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHART_PATH = PROJECT_ROOT / "helm" / "kafka-connect"


def _run_helm(*args: str) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is not installed")
    return subprocess.run(
        [helm, *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def test_kafka_connect_helm_lint_accepts_defaults():
    result = _run_helm("lint", str(CHART_PATH))

    assert result.returncode == 0, _combined_output(result)


def test_kafka_connect_helm_template_renders_connector_hooks_when_enabled():
    result = _run_helm(
        "template",
        "agentflow-cdc",
        str(CHART_PATH),
        "--set",
        "connectors.postgres.enabled=true",
        "--set",
        "connectors.mysql.enabled=true",
    )

    output = _combined_output(result)
    assert result.returncode == 0, output
    assert "agentflow-postgres-cdc-register" in output
    assert "agentflow-mysql-cdc-register" in output
    assert "cdc.postgres" in output
    assert "cdc.mysql" in output
