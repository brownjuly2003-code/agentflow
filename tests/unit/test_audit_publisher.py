import json
from pathlib import Path

from src.serving.api.auth.manager import AuthManager, TenantKey
from src.serving.api.auth.middleware import ensure_usage_table, record_usage
from src.serving.audit_publisher import HashChainedFileAuditPublisher, verify_hash_chain


def test_hash_chained_file_audit_publisher_appends_tamper_evident_records(tmp_path: Path):
    log_path = tmp_path / "audit.jsonl"
    publisher = HashChainedFileAuditPublisher(log_path)

    publisher.publish({"event_type": "api_usage", "tenant": "acme", "endpoint": "/v1/health"})
    publisher.publish({"event_type": "api_usage", "tenant": "demo", "endpoint": "/v1/catalog"})

    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["sequence"] == 1
    assert lines[0]["previous_hash"] is None
    assert lines[1]["sequence"] == 2
    assert lines[1]["previous_hash"] == lines[0]["hash"]
    assert verify_hash_chain(log_path) is True


def test_auth_usage_writes_configured_append_only_audit_path(monkeypatch, tmp_path: Path):
    audit_path = tmp_path / "auth-audit.jsonl"
    api_keys_path = tmp_path / "api_keys.yaml"
    api_keys_path.write_text("keys: []\n", encoding="utf-8")
    monkeypatch.setenv("AGENTFLOW_AUDIT_LOG_PATH", str(audit_path))

    manager = AuthManager(api_keys_path=api_keys_path, db_path=tmp_path / "usage.duckdb")
    tenant_key = TenantKey(
        key_id="support-agent",
        key_hash="hash",
        name="Support Agent",
        tenant="acme",
        rate_limit_rpm=60,
        allowed_entity_types=None,
        created_at="2026-04-10",
    )

    ensure_usage_table(manager)
    record_usage(manager, tenant_key, "/v1/entity/order")

    lines = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["payload"]["event_type"] == "api_usage"
    assert lines[0]["payload"]["tenant"] == "acme"
    assert lines[0]["payload"]["key_id"] == "support-agent"
    assert lines[0]["payload"]["endpoint"] == "/v1/entity/order"
    assert verify_hash_chain(audit_path) is True
