"""Narrow, duckdb-free mutation test for the API-key auth manager
(src/serving/api/auth/manager.py).

This is the test the mutation gate runs against
``serving/api/auth/manager.py`` (see scripts/mutation_report.py MODULE_TARGETS).
manager.py is the request-authentication boundary: ``authenticate()`` resolves a
presented key to a ``TenantKey`` (or ``None``), ``tenant_key_allowed_tables`` /
``is_entity_allowed`` are the tenant-isolation gates, and the failed-auth window
trio is the per-IP brute-force throttle (audit_28_06_26.md auth surface). A
surviving mutant in any of these is an auth-bypass, a cross-tenant read or a
disabled throttle -- exactly what a mutation gate should pin.

Design rules, shared with test_rate_limiter_mutation.py /
test_sql_builder_mutation.py / test_nl_queries_mutation.py (see fable_handoff.md
cont.16-21):

1. **duckdb-free.** Importing ``serving.api.auth.manager`` runs the auth package
   ``__init__`` (``import duckdb`` + ``.key_rotation`` + ``.usage_table`` import
   chain), and real duckdb's lazy ``_duckdb._sqltypes`` import crashes mutmut's
   coverage-instrumented stats pass (the same break ci.yml works around with
   ``coverage run``; see .github/workflows/ci.yml). manager.py *itself* never
   calls duckdb -- every usage-table read/write lives in usage_table.py -- so a
   fake top-level ``duckdb`` module that satisfies the import keeps the mutation
   target genuinely duckdb-free. All other deps (rate_limiter, security,
   audit_publisher) are duckdb-free already.

2. **No fixtures for the subject -- inline construction + direct method calls.**
   With ``mutate_only_covered_lines = true`` a fixture-built manager left method
   lines uncovered (only ``__init__`` mutated, score 0%). ``_build_manager`` is a
   plain helper called inside each test, and the methods under test are called
   directly so coverage attributes every line.

3. **Workspace discrimination by top-level ``serving``.** mutmut's mutants/
   workspace copies src/serving to a TOP-LEVEL ``serving`` package; ordinary
   pytest has no top-level ``serving`` (only src.serving). Gate the harness stubs
   on ``find_spec("serving")`` -- NOT ``import src``, which stays importable via
   the editable install even inside the workspace (cont.21 duckdb-crash root
   cause). Under ordinary pytest no stub is installed and the real modules load.
"""

from __future__ import annotations

import sys
import types
from datetime import date


def _in_mutation_workspace() -> bool:
    # mutmut's mutants/ workspace copies src/serving to a TOP-LEVEL `serving`
    # package (scripts/mutation_report.py prepare_workspace); ordinary pytest has
    # no top-level `serving` (only src.serving), so its presence cleanly marks the
    # harness. `import src` does NOT discriminate: the editable install keeps the
    # real `src` importable even inside the workspace.
    import importlib.util

    try:
        return importlib.util.find_spec("serving") is not None
    except (ImportError, ValueError):
        return False


def _ensure_module(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    return module


def _install_harness_stubs() -> None:
    # The auth package import chain pulls duckdb at import time
    # (auth/__init__.py `import duckdb`; key_rotation / usage_table /
    # duckdb_connection). Replace the whole `duckdb` module with a fake that
    # supplies the names those modules reference at import / type-check time.
    # manager.py never executes a duckdb call, so the fake changes no logic in
    # the mutation target; it only keeps the import chain off real duckdb's
    # coverage-breaking native extension. Force-overwrite (not _ensure_module) so
    # a duckdb already pulled in by the coverage harness can't shadow the fake.
    duckdb_stub = types.ModuleType("duckdb")

    class _DuckDBError(Exception):
        pass

    duckdb_stub.Error = _DuckDBError
    duckdb_stub.IOException = type("IOException", (_DuckDBError,), {})
    duckdb_stub.DuckDBPyConnection = object

    def _connect(*_args: object, **_kwargs: object) -> object:
        raise _DuckDBError("duckdb is stubbed out in the mutation harness")

    duckdb_stub.connect = _connect
    sys.modules["duckdb"] = duckdb_stub


if _in_mutation_workspace():
    _install_harness_stubs()

try:  # mutation-harness workspace exposes it as a top-level package
    from serving.api.auth import manager as manager_module
except ImportError:  # ordinary pytest sees it under the src package
    from src.serving.api.auth import manager as manager_module

import pytest

AuthManager = manager_module.AuthManager
TenantKey = manager_module.TenantKey
tenant_key_allowed_tables = manager_module.tenant_key_allowed_tables
get_current_tenant_id = manager_module.get_current_tenant_id
_CURRENT_TENANT_ID = manager_module._CURRENT_TENANT_ID
DEFAULT_RATE_LIMIT_RPM = manager_module.DEFAULT_RATE_LIMIT_RPM
FAILED_AUTH_WINDOW_SECONDS = manager_module.FAILED_AUTH_WINDOW_SECONDS
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = manager_module.DEFAULT_RATE_LIMIT_WINDOW_SECONDS
DEFAULT_ROTATION_GRACE_PERIOD_SECONDS = manager_module.DEFAULT_ROTATION_GRACE_PERIOD_SECONDS


# --------------------------------------------------------------------------- #
# Inline construction helpers (no fixtures for the subject).
# --------------------------------------------------------------------------- #


class FrozenClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _key(**overrides: object) -> TenantKey:
    base: dict[str, object] = {
        "key": "plain-key",
        "name": "n",
        "tenant": "acme",
        "created_at": date(2026, 1, 1),
    }
    base.update(overrides)
    return TenantKey(**base)  # type: ignore[arg-type]


def _build_manager(**overrides: object) -> AuthManager:
    # api_keys_path=None -> env-only config, no file I/O. A neutral db_path
    # (not the magic "agentflow_api.duckdb") skips the pipeline-path derivation
    # branch, and the path is never connected because no usage is recorded here.
    params: dict[str, object] = {
        "api_keys_path": None,
        "db_path": "usage.duckdb",
        "time_source": FrozenClock(1_000.0),
    }
    params.update(overrides)
    return AuthManager(**params)  # type: ignore[arg-type]


class _FullRemainingLimiter:
    """Redis-backed limiter that fails open (full quota remaining) while keeping
    a live `_redis` handle -- the condition that triggers `check_rate_limit`'s
    in-memory secondary window."""

    def __init__(self) -> None:
        self._redis = object()

    async def check(self, key: str, rpm: int) -> tuple[bool, int, int]:
        return True, rpm, 0


# --------------------------------------------------------------------------- #
# Tenant isolation: tenant_key_allowed_tables.
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# TenantKey key-material validation.
# --------------------------------------------------------------------------- #


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
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Either key or key_hash must be provided"):
            _key(key=None, key_hash=None)


# --------------------------------------------------------------------------- #
# authenticate(): the request-auth boundary.
# --------------------------------------------------------------------------- #


class TestAuthenticate:
    def test_plaintext_match_returns_current_slot_copy_with_presented_key(self) -> None:
        m = _build_manager()
        m.keys_by_value = {"plain-secret": _key(key="plain-secret", tenant="acme")}
        out = m.authenticate("plain-secret")
        assert out is not None
        assert out.key == "plain-secret"
        assert out.tenant == "acme"
        assert out.matched_slot == "current"

    def test_plaintext_mismatch_returns_none(self) -> None:
        m = _build_manager()
        m.keys_by_value = {"plain-secret": _key(key="plain-secret")}
        assert m.authenticate("not-the-secret") is None

    def test_entry_without_runtime_key_is_skipped_not_matched(self) -> None:
        # item.key is None -> the `continue` guard; a None runtime key must never
        # be compared/matched. No hashed/indexed entries -> overall None.
        m = _build_manager()
        m.keys_by_value = {"slot": _key(key=None, key_hash="h")}
        assert m.authenticate("anything") is None

    def test_indexed_lookup_verifies_and_remembers_runtime_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        m = _build_manager()
        entry = _key(key=None, key_hash="stored-hash", key_lookup="digest-x", tenant="t1")
        m._keys_by_lookup = {"digest-x": entry}
        monkeypatch.setattr(manager_module, "compute_key_lookup", lambda value: "digest-x")
        monkeypatch.setattr(manager_module, "verify_api_key", lambda value, h: h == "stored-hash")
        out = m.authenticate("real-key")
        assert out is not None
        assert out.matched_slot == "current"
        assert out.key == "real-key"
        assert out.tenant == "t1"
        # _remember_runtime_key cached the plaintext->hash binding.
        assert m._runtime_plaintext_by_hash["stored-hash"] == "real-key"
        assert m.keys_by_value["real-key"].key_hash == "stored-hash"

    def test_indexed_lookup_wrong_hash_does_not_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        m = _build_manager()
        entry = _key(key=None, key_hash="stored-hash", key_lookup="digest-x")
        m._keys_by_lookup = {"digest-x": entry}
        monkeypatch.setattr(manager_module, "compute_key_lookup", lambda value: "digest-x")
        monkeypatch.setattr(manager_module, "verify_api_key", lambda value, h: False)
        assert m.authenticate("real-key") is None

    def test_legacy_scan_matches_only_unindexed_hashed_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        m = _build_manager()
        indexed = _key(key=None, key_hash="indexed-hash", key_lookup="has-digest")
        unindexed = _key(key=None, key_hash="legacy-hash", key_lookup=None, tenant="legacy")
        m._hashed_keys = [indexed, unindexed]
        # compute_key_lookup misses the index so the O(n) fallback runs; verify
        # only accepts the legacy hash. The indexed entry must be skipped by the
        # `key_lookup is not None -> continue` guard, not verified.
        monkeypatch.setattr(manager_module, "compute_key_lookup", lambda value: "no-index-hit")
        seen: list[str] = []

        def _verify(value: str, h: str) -> bool:
            seen.append(h)
            return h == "legacy-hash"

        monkeypatch.setattr(manager_module, "verify_api_key", _verify)
        out = m.authenticate("real-key")
        assert out is not None
        assert out.tenant == "legacy"
        assert out.matched_slot == "current"
        assert "indexed-hash" not in seen  # indexed entry skipped, not verified

    def test_no_configured_keys_returns_none(self) -> None:
        m = _build_manager()
        assert m.authenticate("whatever") is None


# --------------------------------------------------------------------------- #
# _remember_runtime_key: plaintext cache binding.
# --------------------------------------------------------------------------- #


class TestRememberRuntimeKey:
    def test_no_hash_is_not_cached(self) -> None:
        m = _build_manager()
        matched = _key(key="plain", key_hash=None)
        m._remember_runtime_key("plain", matched)
        assert m._runtime_plaintext_by_hash == {}

    def test_hashed_match_is_cached_under_its_hash(self) -> None:
        m = _build_manager()
        matched = _key(key="real-key", key_hash="the-hash")
        m._remember_runtime_key("real-key", matched)
        assert m._runtime_plaintext_by_hash["the-hash"] == "real-key"
        assert m.keys_by_value["real-key"] is matched


# --------------------------------------------------------------------------- #
# _matches_key_material: revoke-path matcher.
# --------------------------------------------------------------------------- #


class TestMatchesKeyMaterial:
    def test_plaintext_key_match(self) -> None:
        m = _build_manager()
        assert m._matches_key_material(_key(key="secret", key_hash=None), "secret") is True

    def test_plaintext_key_mismatch_without_hash_returns_false(self) -> None:
        m = _build_manager()
        assert m._matches_key_material(_key(key="secret", key_hash=None), "wrong") is False

    def test_literal_key_hash_match(self) -> None:
        m = _build_manager()
        item = _key(key=None, key_hash="stored-hash-literal")
        assert m._matches_key_material(item, "stored-hash-literal") is True

    def test_cached_plaintext_match(self) -> None:
        m = _build_manager()
        item = _key(key=None, key_hash="bcrypt-ish-hash")
        m._runtime_plaintext_by_hash["bcrypt-ish-hash"] = "cached-plain"
        assert m._matches_key_material(item, "cached-plain") is True

    def test_unrelated_value_against_non_bcrypt_hash_returns_false(self) -> None:
        m = _build_manager()
        item = _key(key=None, key_hash="not-a-valid-bcrypt-hash")
        assert m._matches_key_material(item, "anything") is False


# --------------------------------------------------------------------------- #
# Per-IP failed-auth brute-force throttle.
# --------------------------------------------------------------------------- #


def _policy(limit: int) -> types.SimpleNamespace:
    return types.SimpleNamespace(max_failed_auth_per_ip_per_hour=limit)


class TestFailedAuthThrottle:
    def test_record_failed_auth_trips_strictly_above_limit(self) -> None:
        m = _build_manager(time_source=FrozenClock(1_000.0))
        m.security_policy = _policy(2)
        assert m.record_failed_auth("1.2.3.4") is False  # 1 > 2 -> no
        assert m.record_failed_auth("1.2.3.4") is False  # 2 > 2 -> no
        assert m.record_failed_auth("1.2.3.4") is True  # 3 > 2 -> tripped

    def test_is_failed_auth_limited_reads_window_without_appending(self) -> None:
        m = _build_manager(time_source=FrozenClock(1_000.0))
        m.security_policy = _policy(1)
        m.record_failed_auth("ip")  # window size 1
        # is_failed_auth_limited must NOT append; 1 > 1 is False.
        assert m.is_failed_auth_limited("ip") is False
        assert m.is_failed_auth_limited("ip") is False
        m.record_failed_auth("ip")  # window size 2
        assert m.is_failed_auth_limited("ip") is True  # 2 > 1

    def test_record_failed_auth_evicts_stamps_outside_window(self) -> None:
        clock = FrozenClock(1_000.0)
        m = _build_manager(time_source=clock)
        m.security_policy = _policy(5)
        m.record_failed_auth("ip")
        clock.now = 1_000.0 + FAILED_AUTH_WINDOW_SECONDS + 1.0
        m.record_failed_auth("ip")
        # The stale stamp fell strictly outside the cutoff; only the new one left.
        assert len(m._failed_auth_windows["ip"]) == 1

    def test_stamp_exactly_at_cutoff_is_excluded(self) -> None:
        clock = FrozenClock(1_000.0)
        m = _build_manager(time_source=clock)
        m.security_policy = _policy(5)
        m.record_failed_auth("ip")  # stamp at 1000.0
        clock.now = 1_000.0 + FAILED_AUTH_WINDOW_SECONDS  # cutoff == old stamp
        # window keeps stamp only if stamp > cutoff; 1000.0 > 1000.0 is False.
        m.record_failed_auth("ip")
        assert len(m._failed_auth_windows["ip"]) == 1

    def test_clear_failed_auth_removes_ip(self) -> None:
        m = _build_manager(time_source=FrozenClock(1_000.0))
        m.security_policy = _policy(5)
        m.record_failed_auth("ip")
        m.clear_failed_auth("ip")
        assert "ip" not in m._failed_auth_windows

    def test_clear_failed_auth_unknown_ip_is_noop(self) -> None:
        m = _build_manager(time_source=FrozenClock(1_000.0))
        m.security_policy = _policy(5)
        m.clear_failed_auth("never-seen")  # pop(..., None) must not raise
        assert "never-seen" not in m._failed_auth_windows


# --------------------------------------------------------------------------- #
# _sweep_expired_windows: opportunistic GC of rate / failed-auth dicts.
# --------------------------------------------------------------------------- #


class TestSweepExpiredWindows:
    def test_drops_fully_expired_rate_window(self) -> None:
        clock = FrozenClock(1_000.0)
        m = _build_manager(time_source=clock)
        m._rate_windows["k"] = [1_000.0 - DEFAULT_RATE_LIMIT_WINDOW_SECONDS - 5.0]
        m._sweep_expired_windows()
        assert "k" not in m._rate_windows

    def test_keeps_live_rate_window_stamps(self) -> None:
        clock = FrozenClock(1_000.0)
        m = _build_manager(time_source=clock)
        live = 1_000.0 - 1.0
        m._rate_windows["k"] = [1_000.0 - DEFAULT_RATE_LIMIT_WINDOW_SECONDS - 5.0, live]
        m._sweep_expired_windows()
        assert m._rate_windows["k"] == [live]

    def test_drops_fully_expired_failed_auth_window(self) -> None:
        clock = FrozenClock(1_000.0)
        m = _build_manager(time_source=clock)
        m._failed_auth_windows["ip"] = [1_000.0 - FAILED_AUTH_WINDOW_SECONDS - 5.0]
        m._sweep_expired_windows()
        assert "ip" not in m._failed_auth_windows


# --------------------------------------------------------------------------- #
# In-memory rate limiting (is_rate_limited / check_rate_limit).
# --------------------------------------------------------------------------- #


class TestInMemoryRateLimiting:
    def test_is_rate_limited_blocks_after_rpm_in_window(self) -> None:
        m = _build_manager(time_source=FrozenClock(1_000.0))
        tenant_key = _key(rate_limit_rpm=2)
        assert m.is_rate_limited(tenant_key) is False
        assert m.is_rate_limited(tenant_key) is False
        assert m.is_rate_limited(tenant_key) is True

    def test_is_rate_limited_evicts_stale_stamps(self) -> None:
        clock = FrozenClock(1_000.0)
        m = _build_manager(time_source=clock)
        tenant_key = _key(rate_limit_rpm=1)
        assert m.is_rate_limited(tenant_key) is False
        assert m.is_rate_limited(tenant_key) is True
        clock.now = 1_000.0 + DEFAULT_RATE_LIMIT_WINDOW_SECONDS + 1.0
        # Old stamp expired -> allowed again.
        assert m.is_rate_limited(tenant_key) is False

    @pytest.mark.asyncio
    async def test_check_rate_limit_applies_local_window_when_redis_reports_full(self) -> None:
        m = _build_manager(
            time_source=FrozenClock(1_000.0),
            rate_limiter=_FullRemainingLimiter(),
        )
        tenant_key = _key(rate_limit_rpm=2)
        first = await m.check_rate_limit(tenant_key)
        second = await m.check_rate_limit(tenant_key)
        third = await m.check_rate_limit(tenant_key)
        assert first == (True, 1, 1_060)
        assert second == (True, 0, 1_060)
        assert third == (False, 0, 1_060)


# --------------------------------------------------------------------------- #
# _rate_limit_key, is_entity_allowed, configured-key accessors.
# --------------------------------------------------------------------------- #


class TestKeyingAndAuthorization:
    def test_rate_limit_key_prefers_plaintext_key(self) -> None:
        m = _build_manager()
        assert m._rate_limit_key(_key(key="k", key_hash="h")) == "k"

    def test_rate_limit_key_falls_back_to_hash_when_no_plaintext(self) -> None:
        m = _build_manager()
        assert m._rate_limit_key(_key(key=None, key_hash="h")) == "h"

    def test_is_entity_allowed_true_when_unrestricted(self) -> None:
        m = _build_manager()
        assert m.is_entity_allowed(_key(allowed_entity_types=None), "user") is True

    def test_is_entity_allowed_true_when_in_allowlist(self) -> None:
        m = _build_manager()
        assert m.is_entity_allowed(_key(allowed_entity_types=["user"]), "user") is True

    def test_is_entity_allowed_false_when_not_in_allowlist(self) -> None:
        m = _build_manager()
        assert m.is_entity_allowed(_key(allowed_entity_types=["order"]), "user") is False

    def test_has_configured_keys_false_when_empty(self) -> None:
        m = _build_manager()
        assert m.has_configured_keys() is False

    def test_has_configured_keys_true_with_plaintext_key(self) -> None:
        m = _build_manager()
        m.keys_by_value = {"k": _key(key="k")}
        assert m.has_configured_keys() is True

    def test_has_configured_keys_true_with_hashed_key(self) -> None:
        m = _build_manager()
        m._hashed_keys = [_key(key=None, key_hash="h")]
        assert m.has_configured_keys() is True


# --------------------------------------------------------------------------- #
# get_current_tenant_id contextvar.
# --------------------------------------------------------------------------- #


class TestCurrentTenantId:
    def test_returns_default_when_context_unset(self) -> None:
        assert get_current_tenant_id(default="fallback-tenant") == "fallback-tenant"

    def test_returns_context_value_when_set(self) -> None:
        token = _CURRENT_TENANT_ID.set("tenant-x")
        try:
            assert get_current_tenant_id() == "tenant-x"
        finally:
            _CURRENT_TENANT_ID.reset(token)


# --------------------------------------------------------------------------- #
# Legacy AGENTFLOW_API_KEYS env parsing.
# --------------------------------------------------------------------------- #


class TestLegacyEnvKeys:
    def test_empty_env_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = _build_manager()
        monkeypatch.delenv("AGENTFLOW_API_KEYS", raising=False)
        assert m._legacy_env_keys() == []

    def test_whitespace_env_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = _build_manager()
        monkeypatch.setenv("AGENTFLOW_API_KEYS", "   ")
        assert m._legacy_env_keys() == []

    def test_key_with_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = _build_manager()
        monkeypatch.setenv("AGENTFLOW_API_KEYS", "abc123:Alice")
        keys = m._legacy_env_keys()
        assert len(keys) == 1
        assert keys[0].key == "abc123"
        assert keys[0].name == "Alice"
        assert keys[0].tenant == "default"
        assert keys[0].rate_limit_rpm == DEFAULT_RATE_LIMIT_RPM

    def test_key_without_colon_gets_unnamed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = _build_manager()
        monkeypatch.setenv("AGENTFLOW_API_KEYS", "loosekey")
        keys = m._legacy_env_keys()
        assert len(keys) == 1
        assert keys[0].key == "loosekey"
        assert keys[0].name == "unnamed"

    def test_multiple_keys_skip_empty_segments(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = _build_manager()
        monkeypatch.setenv("AGENTFLOW_API_KEYS", "k1:n1, k2:n2 ,,")
        keys = m._legacy_env_keys()
        assert [(k.key, k.name) for k in keys] == [("k1", "n1"), ("k2", "n2")]


# --------------------------------------------------------------------------- #
# __init__ config branches + lifecycle.
# --------------------------------------------------------------------------- #


class TestInitConfigBranches:
    def test_derives_api_db_path_from_pipeline_duckdb_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENTFLOW_USAGE_DB_PATH", raising=False)
        monkeypatch.setenv("DUCKDB_PATH", "/data/pipeline.duckdb")
        m = _build_manager(db_path="agentflow_api.duckdb")
        assert m.db_path.name == "pipeline_api.duckdb"

    def test_falls_back_on_invalid_rotation_grace_period(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTFLOW_ROTATION_GRACE_PERIOD_SECONDS", "not-an-int")
        m = _build_manager()
        assert m.rotation_grace_period_seconds == DEFAULT_ROTATION_GRACE_PERIOD_SECONDS

    def test_valid_rotation_grace_period_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTFLOW_ROTATION_GRACE_PERIOD_SECONDS", "7")
        m = _build_manager()
        assert m.rotation_grace_period_seconds == 7

    def test_load_with_env_only_config_has_no_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENTFLOW_API_KEYS", raising=False)
        m = _build_manager()
        m.load()
        assert m.configured_key_count == 0

    def test_shutdown_is_idempotent(self) -> None:
        m = _build_manager()
        m.shutdown()
        m.shutdown()
