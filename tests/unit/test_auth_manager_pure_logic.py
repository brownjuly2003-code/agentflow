"""Unit coverage for the pure, infra-free security logic in
``src.serving.api.auth.manager`` that the integration / e2e auth suites
exercise only indirectly: tenant table-allowlist resolution (tenant
isolation), ``TenantKey`` key-material validation, legacy ``AGENTFLOW_API_KEYS``
env parsing, and the ``_matches_key_material`` revoke-path matcher. These
functions carried no direct unit test before (verified 2026-06-03); a
surviving bug in any of them is a tenant-isolation or key-matching defect."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.constants import DEFAULT_ROTATION_GRACE_PERIOD_SECONDS
from src.serving.api.auth.manager import (
    _CURRENT_TENANT_ID,
    DEFAULT_RATE_LIMIT_RPM,
    AuthManager,
    TenantKey,
    get_current_tenant_id,
    tenant_key_allowed_tables,
)


def _key(**overrides: object) -> TenantKey:
    base: dict[str, object] = {
        "key": "plain-key",
        "name": "n",
        "tenant": "acme",
        "created_at": date(2026, 1, 1),
    }
    base.update(overrides)
    return TenantKey(**base)  # type: ignore[arg-type]


class FrozenClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _FullRemainingLimiter:
    """Stub limiter standing in for a Redis-backed limiter that fails open
    (reports the full quota as remaining) while still having a live `_redis`
    handle — the condition that triggers `AuthManager.check_rate_limit`'s
    in-memory secondary window."""

    def __init__(self) -> None:
        self._redis = object()

    async def check(self, key: str, rpm: int) -> tuple[bool, int, int]:
        return True, rpm, 0


@pytest.fixture
def manager(tmp_path: Path) -> AuthManager:
    api_keys_path = tmp_path / "api_keys.yaml"
    api_keys_path.write_text("keys: []\n", encoding="utf-8")
    return AuthManager(api_keys_path=api_keys_path, db_path=tmp_path / "usage.duckdb")


class TestTenantKeyAllowedTables:
    def test_none_tenant_key_returns_all_tables_from_list(self) -> None:
        assert tenant_key_allowed_tables(None, ["a", "b", "c"]) == ["a", "b", "c"]

    def test_none_tenant_key_returns_all_table_values_from_mapping(self) -> None:
        catalog = {"customer": "dim_customer", "order": "fct_order"}
        assert tenant_key_allowed_tables(None, catalog) == ["dim_customer", "fct_order"]

    def test_none_allowed_entity_types_returns_all_tables(self) -> None:
        tk = _key(allowed_entity_types=None)
        assert tenant_key_allowed_tables(tk, ["a", "b"]) == ["a", "b"]

    def test_filters_mapping_by_entity_type(self) -> None:
        tk = _key(allowed_entity_types=["customer"])
        catalog = {"customer": "dim_customer", "order": "fct_order"}
        assert tenant_key_allowed_tables(tk, catalog) == ["dim_customer"]

    def test_filters_mapping_by_table_name_when_entity_type_differs(self) -> None:
        # The allowlist matches either the entity type OR the resolved table
        # name, so naming the physical table also grants it.
        tk = _key(allowed_entity_types=["fct_order"])
        catalog = {"customer": "dim_customer", "order": "fct_order"}
        assert tenant_key_allowed_tables(tk, catalog) == ["fct_order"]

    def test_filters_list_input_by_allowed(self) -> None:
        tk = _key(allowed_entity_types=["a"])
        assert tenant_key_allowed_tables(tk, ["a", "b"]) == ["a"]

    def test_empty_allowlist_excludes_everything(self) -> None:
        tk = _key(allowed_entity_types=[])
        assert tenant_key_allowed_tables(tk, ["a", "b"]) == []


class TestValidateKeyMaterial:
    def test_key_only_is_valid(self) -> None:
        assert _key(key="k", key_hash=None).key == "k"

    def test_key_hash_only_is_valid(self) -> None:
        assert _key(key=None, key_hash="h").key_hash == "h"

    def test_both_key_and_hash_is_valid(self) -> None:
        tk = _key(key="k", key_hash="h")
        assert tk.key == "k"
        assert tk.key_hash == "h"

    def test_neither_key_nor_hash_raises(self) -> None:
        with pytest.raises(ValidationError, match="Either key or key_hash must be provided"):
            _key(key=None, key_hash=None)


class TestLegacyEnvKeys:
    def test_empty_env_returns_empty(
        self, manager: AuthManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENTFLOW_API_KEYS", raising=False)
        assert manager._legacy_env_keys() == []

    def test_whitespace_env_returns_empty(
        self, manager: AuthManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTFLOW_API_KEYS", "   ")
        assert manager._legacy_env_keys() == []

    def test_key_with_name(self, manager: AuthManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTFLOW_API_KEYS", "abc123:Alice")
        keys = manager._legacy_env_keys()
        assert len(keys) == 1
        assert keys[0].key == "abc123"
        assert keys[0].name == "Alice"
        assert keys[0].tenant == "default"
        assert keys[0].rate_limit_rpm == DEFAULT_RATE_LIMIT_RPM

    def test_key_without_colon_gets_unnamed(
        self, manager: AuthManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTFLOW_API_KEYS", "loosekey")
        keys = manager._legacy_env_keys()
        assert len(keys) == 1
        assert keys[0].key == "loosekey"
        assert keys[0].name == "unnamed"

    def test_multiple_keys_skip_empty_segments(
        self, manager: AuthManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTFLOW_API_KEYS", "k1:n1, k2:n2 ,,")
        keys = manager._legacy_env_keys()
        assert [(k.key, k.name) for k in keys] == [("k1", "n1"), ("k2", "n2")]


class TestMatchesKeyMaterial:
    def test_plaintext_key_match(self, manager: AuthManager) -> None:
        item = _key(key="secret", key_hash=None)
        assert manager._matches_key_material(item, "secret") is True

    def test_plaintext_key_mismatch_without_hash_returns_false(self, manager: AuthManager) -> None:
        item = _key(key="secret", key_hash=None)
        assert manager._matches_key_material(item, "wrong") is False

    def test_literal_key_hash_match(self, manager: AuthManager) -> None:
        # A caller can present the stored hash string itself (constant-time
        # compared) without going through bcrypt verification.
        item = _key(key=None, key_hash="stored-hash-literal")
        assert manager._matches_key_material(item, "stored-hash-literal") is True

    def test_cached_plaintext_match(self, manager: AuthManager) -> None:
        item = _key(key=None, key_hash="bcrypt-ish-hash")
        manager._runtime_plaintext_by_hash["bcrypt-ish-hash"] = "cached-plain"
        assert manager._matches_key_material(item, "cached-plain") is True

    def test_unrelated_value_against_non_bcrypt_hash_returns_false(
        self, manager: AuthManager
    ) -> None:
        # verify_api_key swallows malformed-hash ValueError and returns False,
        # so an unrelated value must not match.
        item = _key(key=None, key_hash="not-a-valid-bcrypt-hash")
        assert manager._matches_key_material(item, "anything") is False


class TestCurrentTenantId:
    def test_returns_default_when_context_unset(self) -> None:
        assert get_current_tenant_id(default="fallback-tenant") == "fallback-tenant"

    def test_returns_context_value_when_set(self) -> None:
        token = _CURRENT_TENANT_ID.set("tenant-x")
        try:
            assert get_current_tenant_id() == "tenant-x"
        finally:
            _CURRENT_TENANT_ID.reset(token)


class TestInitConfigBranches:
    def test_derives_api_db_path_from_pipeline_duckdb_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENTFLOW_USAGE_DB_PATH", raising=False)
        monkeypatch.setenv("DUCKDB_PATH", "/data/pipeline.duckdb")
        manager = AuthManager(api_keys_path=None, db_path="agentflow_api.duckdb")
        assert manager.db_path.name == "pipeline_api.duckdb"

    def test_falls_back_on_invalid_rotation_grace_period(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AGENTFLOW_ROTATION_GRACE_PERIOD_SECONDS", "not-an-int")
        manager = AuthManager(api_keys_path=None, db_path=tmp_path / "usage.duckdb")
        assert manager.rotation_grace_period_seconds == DEFAULT_ROTATION_GRACE_PERIOD_SECONDS

    def test_load_with_env_only_config_has_no_keys(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("AGENTFLOW_API_KEYS", raising=False)
        manager = AuthManager(api_keys_path=None, db_path=tmp_path / "usage.duckdb")
        manager.load()
        assert manager.configured_key_count == 0


class TestInMemoryRateLimiting:
    def test_is_rate_limited_blocks_after_rpm_in_window(self, tmp_path: Path) -> None:
        manager = AuthManager(
            api_keys_path=None,
            db_path=tmp_path / "usage.duckdb",
            time_source=FrozenClock(1_000.0),
        )
        tenant_key = _key(rate_limit_rpm=2)

        assert manager.is_rate_limited(tenant_key) is False
        assert manager.is_rate_limited(tenant_key) is False
        assert manager.is_rate_limited(tenant_key) is True

    @pytest.mark.asyncio
    async def test_check_rate_limit_applies_local_window_when_redis_reports_full(
        self, tmp_path: Path
    ) -> None:
        manager = AuthManager(
            api_keys_path=None,
            db_path=tmp_path / "usage.duckdb",
            time_source=FrozenClock(1_000.0),
            rate_limiter=_FullRemainingLimiter(),
        )
        tenant_key = _key(rate_limit_rpm=2)

        first = await manager.check_rate_limit(tenant_key)
        second = await manager.check_rate_limit(tenant_key)
        third = await manager.check_rate_limit(tenant_key)

        assert first == (True, 1, 1_060)
        assert second == (True, 0, 1_060)
        assert third == (False, 0, 1_060)


class TestEntityAllowAndLifecycle:
    def test_is_entity_allowed_true_when_unrestricted(self, manager: AuthManager) -> None:
        assert manager.is_entity_allowed(_key(allowed_entity_types=None), "user") is True

    def test_shutdown_is_idempotent(self, manager: AuthManager) -> None:
        manager.shutdown()
        manager.shutdown()
