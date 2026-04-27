import json
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest
import yaml

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


def test_kafka_connect_topic_bootstrap_defaults_are_declared():
    values = yaml.safe_load((CHART_PATH / "values.yaml").read_text())

    assert values["topicBootstrap"]["enabled"] is True
    assert values["topicBootstrap"]["image"]["repository"] == "confluentinc/cp-kafka"
    assert values["topicBootstrap"]["image"]["tag"] == "7.7.0"


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


def test_kafka_connect_helm_template_renders_topic_bootstrap_hook_when_enabled():
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
    assert "agentflow-cdc-kafka-connect-topic-bootstrap" in output
    assert "connect-agentflow-configs" in output
    assert "cdc.postgres.public.orders_v2" in output
    assert "__debezium-heartbeat.cdc.postgres" in output
    assert "cdc.mysql.agentflow_demo.products_current" in output
    assert "__debezium-heartbeat.cdc.mysql" in output
    assert "schemahistory.cdc.mysql.agentflow_demo" in output
    assert "cleanup.policy=delete,retention.ms=-1" in output


def test_kafka_connect_helm_rejects_disabled_secret_without_existing_secret():
    result = _run_helm(
        "template",
        "agentflow-cdc",
        str(CHART_PATH),
        "--set",
        "secrets.create=false",
        "--set",
        "secrets.existingSecret=",
    )

    output = _combined_output(result)
    assert result.returncode != 0, output
    assert "existingSecret" in output


def test_kafka_connect_values_schema_rejects_disabled_secret_without_existing_secret():
    values = yaml.safe_load((CHART_PATH / "values.yaml").read_text())
    schema = json.loads((CHART_PATH / "values.schema.json").read_text())
    values["secrets"]["create"] = False
    values["secrets"]["existingSecret"] = ""

    with pytest.raises(jsonschema.ValidationError, match="existingSecret"):
        jsonschema.Draft7Validator(schema).validate(values)


def test_kafka_connect_values_schema_rejects_created_secret_with_existing_secret():
    values = yaml.safe_load((CHART_PATH / "values.yaml").read_text())
    schema = json.loads((CHART_PATH / "values.schema.json").read_text())
    values["secrets"]["create"] = True
    values["secrets"]["existingSecret"] = "agentflow-cdc-source-credentials"

    with pytest.raises(jsonschema.ValidationError, match="existingSecret"):
        jsonschema.Draft7Validator(schema).validate(values)
