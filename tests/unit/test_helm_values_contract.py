"""Static Helm values contract checks.

Live Helm CLI schema validation is covered by
tests/integration/test_helm_values_live_validation.py.
"""

import json
import shutil
import subprocess
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHART_PATH = PROJECT_ROOT / "helm" / "agentflow"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _run_helm_template(*args: str) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        raise AssertionError("helm is required for Helm render policy tests")
    return subprocess.run(
        [helm, "template", "agentflow", str(CHART_PATH), *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def test_chart_declares_values_schema_for_runtime_contracts():
    schema_path = PROJECT_ROOT / "helm" / "agentflow" / "values.schema.json"

    assert schema_path.exists()

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    api_key_item = schema["properties"]["secrets"]["properties"]["apiKeys"]["properties"]["keys"][
        "items"
    ]
    tenant_item = schema["properties"]["config"]["properties"]["tenants"]["properties"]["tenants"][
        "items"
    ]

    assert "key_id" in api_key_item["required"]
    assert "name" in api_key_item["required"]
    assert "tenant" in api_key_item["required"]
    assert "created_at" in api_key_item["required"]
    assert "id" in tenant_item["required"]
    assert "display_name" in tenant_item["required"]
    assert "duckdb_schema" in tenant_item["required"]
    assert "create" in schema["properties"]["secrets"]["required"]
    assert "existingSecret" in schema["properties"]["secrets"]["required"]


def test_chart_defaults_use_structured_api_keys_and_tenants():
    values = _load_yaml(PROJECT_ROOT / "helm" / "agentflow" / "values.yaml")

    api_keys = values["secrets"]["apiKeys"]
    tenants = values["config"]["tenants"]

    assert isinstance(api_keys, dict)
    assert isinstance(tenants, dict)
    assert tenants["tenants"]
    assert api_keys["keys"] == []

    for tenant in tenants["tenants"]:
        assert tenant["id"]
        assert tenant["display_name"]
        assert tenant["kafka_topic_prefix"]
        assert tenant["duckdb_schema"]
        assert tenant["max_events_per_day"] >= 1
        assert tenant["max_api_keys"] >= 1


def test_chart_defaults_do_not_embed_production_shaped_api_key_hashes():
    values_text = (PROJECT_ROOT / "helm" / "agentflow" / "values.yaml").read_text(encoding="utf-8")
    values = yaml.safe_load(values_text)

    assert values["secrets"]["apiKeys"]["keys"] == []
    assert "$2b$" not in values_text
    assert "$2a$" not in values_text


def test_helm_template_rejects_persistent_duckdb_multi_replica_render():
    result = _run_helm_template(
        "--set",
        "persistence.enabled=true",
        "--set",
        "autoscaling.enabled=false",
        "--set",
        "replicaCount=2",
    )

    output = _combined_output(result)
    assert result.returncode != 0, output
    assert "DuckDB persistence requires a single writer replica" in output


def test_helm_template_uses_existing_secret_without_rendering_api_key_material():
    result = _run_helm_template(
        "--set",
        "secrets.create=false",
        "--set",
        "secrets.existingSecret=agentflow-api-runtime-secret",
    )

    output = _combined_output(result)
    assert result.returncode == 0, output
    assert "kind: Secret" not in output
    assert "secretName: agentflow-api-runtime-secret" in output


def test_staging_overrides_use_structured_api_keys_with_explicit_ids():
    # The tracked values-staging.yaml carries placeholders (no plaintext keys —
    # see Codex audit p2_2 #5 / p9 #4). The structured contract is enforced by
    # values-staging.yaml.example, which represents the schema operators must
    # populate from a secrets manager before deploying.
    values = _load_yaml(PROJECT_ROOT / "k8s" / "staging" / "values-staging.yaml.example")

    api_keys = values["secrets"]["apiKeys"]

    assert isinstance(api_keys, dict)
    assert api_keys["keys"]

    for item in api_keys["keys"]:
        assert item["key_id"]
        assert item["name"]
        assert item["tenant"]
        assert item["created_at"]
        assert item["rate_limit_rpm"] >= 1
        assert item.get("key") or item.get("key_hash")
