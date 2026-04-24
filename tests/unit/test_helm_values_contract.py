import json
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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


def test_chart_defaults_use_structured_api_keys_and_tenants():
    values = _load_yaml(PROJECT_ROOT / "helm" / "agentflow" / "values.yaml")

    api_keys = values["secrets"]["apiKeys"]
    tenants = values["config"]["tenants"]

    assert isinstance(api_keys, dict)
    assert isinstance(tenants, dict)
    assert api_keys["keys"]
    assert tenants["tenants"]

    for item in api_keys["keys"]:
        assert item["key_id"]
        assert item["name"]
        assert item["tenant"]
        assert item["created_at"]
        assert item["rate_limit_rpm"] >= 1
        assert item.get("key") or item.get("key_hash")

    for tenant in tenants["tenants"]:
        assert tenant["id"]
        assert tenant["display_name"]
        assert tenant["kafka_topic_prefix"]
        assert tenant["duckdb_schema"]
        assert tenant["max_events_per_day"] >= 1
        assert tenant["max_api_keys"] >= 1


def test_staging_overrides_use_structured_api_keys_with_explicit_ids():
    values = _load_yaml(PROJECT_ROOT / "k8s" / "staging" / "values-staging.yaml")

    api_keys = values["secrets"]["apiKeys"]

    assert isinstance(api_keys, dict)
    assert api_keys["keys"]

    for item in api_keys["keys"]:
        assert item["key_id"]
        assert item["name"]
        assert item["tenant"]
        assert item["created_at"]
        assert item["rate_limit_rpm"] >= 1
        assert item["key"]
