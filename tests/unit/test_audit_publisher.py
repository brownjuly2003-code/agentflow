import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from src.serving.api.auth.manager import AuthManager, TenantKey
from src.serving.api.auth.usage_table import ensure_usage_table, record_usage
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


class _BoomPublisher:
    """Audit publisher that always raises — to assert publish failure does
    not trigger a duplicate api_usage INSERT (H-C3 / audit_kimi_25_05_26)."""

    def __init__(self) -> None:
        self.calls = 0

    def publish(self, payload: Mapping[str, object]) -> None:
        self.calls += 1
        raise RuntimeError("audit pipe broken")


def _make_manager(tmp_path: Path) -> tuple[AuthManager, TenantKey]:
    api_keys_path = tmp_path / "api_keys.yaml"
    api_keys_path.write_text("keys: []\n", encoding="utf-8")
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
    return manager, tenant_key


def test_record_usage_no_duplicate_insert_when_publish_raises(tmp_path: Path) -> None:
    manager, tenant_key = _make_manager(tmp_path)
    manager.audit_publisher = _BoomPublisher()
    ensure_usage_table(manager)

    # Publish failure must be swallowed (logged) so the API hot path does
    # not 500 on audit-pipe outages, and crucially must NOT trigger another
    # INSERT into api_usage via the DB retry loop.
    record_usage(manager, tenant_key, "/v1/entity/order")

    from src.serving.duckdb_connection import connect_duckdb

    conn = connect_duckdb(manager.db_path)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()
    finally:
        conn.close()
    assert count == 1, "publish failure must not trigger a duplicate INSERT"
    assert manager.audit_publisher.calls == 1, "publish must be attempted exactly once"


def test_record_usage_skips_publish_when_all_inserts_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, tenant_key = _make_manager(tmp_path)
    publisher = _BoomPublisher()
    manager.audit_publisher = publisher
    ensure_usage_table(manager)

    import duckdb

    from src.serving.api.auth import usage_table as usage_table_module

    real_connect = usage_table_module.connect_duckdb
    call_count = {"n": 0}

    class _InsertFailingConn:
        def __init__(self, inner):  # type: ignore[no-untyped-def]
            self._inner = inner

        def execute(self, sql, *args, **kwargs):  # type: ignore[no-untyped-def]
            if "INSERT INTO api_usage" in sql:
                raise duckdb.Error("simulated transient lock")
            return self._inner.execute(sql, *args, **kwargs)

        def close(self) -> None:
            self._inner.close()

    def _always_fail_insert(db_path):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        return _InsertFailingConn(real_connect(db_path))

    monkeypatch.setattr(usage_table_module, "connect_duckdb", _always_fail_insert)
    # Also speed up the retry loop so the test does not spend ~0.55s sleeping.
    monkeypatch.setattr(usage_table_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(duckdb.Error):
        record_usage(manager, tenant_key, "/v1/entity/order")

    assert publisher.calls == 0, "publish must not run when insert never succeeded"
    assert call_count["n"] == 10, "expected the 10-attempt retry budget to be exhausted"
