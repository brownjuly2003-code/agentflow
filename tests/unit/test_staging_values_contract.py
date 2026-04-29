from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STAGING_VALUES_PATH = PROJECT_ROOT / "k8s" / "staging" / "values-staging.yaml"


def test_staging_support_key_can_read_active_session_metric():
    values = yaml.safe_load(STAGING_VALUES_PATH.read_text(encoding="utf-8"))
    support_key = values["secrets"]["apiKeys"]["keys"][0]

    assert support_key["name"] == "Support Agent"
    assert "session" in support_key["allowed_entity_types"]


def test_staging_webhooks_file_uses_writable_data_volume():
    values = yaml.safe_load(STAGING_VALUES_PATH.read_text(encoding="utf-8"))
    extra_env = {
        item["name"]: item["value"]
        for item in values.get("extraEnv", [])
        if "name" in item and "value" in item
    }

    assert extra_env["AGENTFLOW_WEBHOOKS_FILE"].startswith("/data/")
