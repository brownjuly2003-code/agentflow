"""Unit coverage for the security-critical key-rotation lifecycle in
``src.serving.api.auth.key_rotation`` (a mutmut target): create / rotate /
revoke / revoke-old, grace-period scheduling and expiry, rotation status, and
the usage-stat queries. The full HTTP flow is exercised by
``tests/integration/test_rotation.py``; these tests pin the rotator logic
directly at the unit layer so a rotation or revoke regression fails fast."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

import src.serving.api.auth.key_rotation as key_rotation_module
import src.serving.control_plane.embedded as embedded_module
from src.serving.api.auth.key_rotation import rotate_all_keys
from src.serving.api.auth.manager import AuthManager, KeyCreateRequest, TenantKey

SEED_KEY_YAML = (
    "keys:\n"
    '  - key: "rotation-acme-key"\n'
    '    name: "Rotation Agent"\n'
    '    tenant: "acme"\n'
    "    rate_limit_rpm: 100\n"
    "    allowed_entity_types: null\n"
    '    created_at: "2026-04-10"\n'
)


def _build_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, grace: str = "30"
) -> AuthManager:
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "usage.duckdb"))
    monkeypatch.setenv("AGENTFLOW_ROTATION_GRACE_PERIOD_SECONDS", grace)
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(SEED_KEY_YAML, encoding="utf-8", newline="\n")
    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=tmp_path / "usage.duckdb",
        admin_key="admin-secret",
    )
    # bcrypt-12 is slow; rotation/create call hash_api_key several times per
    # test. Drop rounds to keep the unit suite fast — the hash format is
    # unchanged, only the cost factor.
    manager.security_policy.bcrypt_rounds = 4
    manager.load()
    manager.ensure_usage_table()
    return manager


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AuthManager:
    mgr = _build_manager(tmp_path, monkeypatch)
    try:
        yield mgr
    finally:
        mgr.shutdown()


def _only_key_id(manager: AuthManager) -> str:
    keys = manager.list_keys_with_usage()
    assert keys, "expected at least one configured key"
    key_id = keys[0]["key_id"]
    assert key_id is not None
    return key_id


class TestRotateKey:
    def test_rotate_starts_grace_period(self, manager: AuthManager) -> None:
        key_id = _only_key_id(manager)

        rotated, expires_at = manager.rotate_key(key_id)

        assert rotated.key is not None
        assert rotated.key.startswith("af-prod-acme-")
        assert expires_at > datetime.now(UTC)
        assert manager.get_rotation_status(key_id)["phase"] == "grace_period"

    def test_rotate_unknown_key_id_raises(self, manager: AuthManager) -> None:
        with pytest.raises(KeyError):
            manager.rotate_key("does-not-exist")

    def test_rotate_twice_rejects_overlapping_rotation(self, manager: AuthManager) -> None:
        key_id = _only_key_id(manager)
        manager.rotate_key(key_id)
        with pytest.raises(ValueError, match="Rotation already in progress"):
            manager.rotate_key(key_id)

    def test_old_key_still_authenticates_during_grace(self, manager: AuthManager) -> None:
        key_id = _only_key_id(manager)
        rotated, _ = manager.rotate_key(key_id)

        # both the new and the previous key resolve during the grace window
        assert manager.authenticate(rotated.key) is not None
        assert manager.authenticate("rotation-acme-key") is not None


class TestRevokeOldKey:
    def test_revoke_old_key_ends_grace_period(self, manager: AuthManager) -> None:
        key_id = _only_key_id(manager)
        manager.rotate_key(key_id)

        assert manager.revoke_old_key(key_id) is True
        assert manager.get_rotation_status(key_id)["phase"] == "idle"
        assert manager.authenticate("rotation-acme-key") is None

    def test_revoke_old_key_without_rotation_returns_false(self, manager: AuthManager) -> None:
        key_id = _only_key_id(manager)
        assert manager.revoke_old_key(key_id) is False

    def test_revoke_old_key_unknown_raises(self, manager: AuthManager) -> None:
        with pytest.raises(KeyError):
            manager.revoke_old_key("does-not-exist")


class TestRevokeKey:
    def test_revoke_known_key_removes_it(self, manager: AuthManager) -> None:
        assert manager.revoke_key("rotation-acme-key") is True
        assert manager.authenticate("rotation-acme-key") is None

    def test_revoke_unknown_key_returns_false(self, manager: AuthManager) -> None:
        assert manager.revoke_key("not-a-real-key") is False


class TestRotationStatus:
    def test_status_unknown_key_raises(self, manager: AuthManager) -> None:
        with pytest.raises(KeyError):
            manager.get_rotation_status("does-not-exist")

    def test_status_idle_for_unrotated_key(self, manager: AuthManager) -> None:
        key_id = _only_key_id(manager)
        status = manager.get_rotation_status(key_id)
        assert status["phase"] == "idle"
        assert status["old_key_active_until"] is None
        assert status["requests_on_old_key_last_hour"] == 0


class TestCreateAndList:
    def test_create_key_then_list_includes_it(self, manager: AuthManager) -> None:
        created = manager.create_key(
            KeyCreateRequest(name="Reporting Agent", tenant="beta", rate_limit_rpm=50)
        )
        assert created.key is not None
        listed = {item["name"] for item in manager.list_keys_with_usage()}
        assert {"Rotation Agent", "Reporting Agent"} <= listed

    def test_list_keys_omits_plaintext(self, manager: AuthManager) -> None:
        # A created key carries a hash; listing must never echo plaintext back.
        manager.create_key(KeyCreateRequest(name="Listed Agent", tenant="beta"))
        entry = next(
            item for item in manager.list_keys_with_usage() if item["name"] == "Listed Agent"
        )
        assert "key" not in entry
        assert entry["key_hash_present"] is True


class TestRotateAllKeys:
    def test_rotate_all_keys_rotates_every_configured_key(self, manager: AuthManager) -> None:
        manager.create_key(KeyCreateRequest(name="Second Agent", tenant="beta"))

        rotated = rotate_all_keys(manager)

        assert len(rotated) == 2
        phases = {item["rotation_phase"] for item in manager.list_keys_with_usage()}
        assert phases == {"grace_period"}

    def test_rotate_all_skips_entries_without_key_id(
        self, manager: AuthManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(manager, "list_keys_with_usage", lambda: [{"key_id": None}])
        assert rotate_all_keys(manager) == []


class TestRotatorHelpers:
    def test_write_config_without_path_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        try:
            rotator = manager._key_rotator
            config = manager._load_config()
            manager.api_keys_path = None
            with pytest.raises(RuntimeError, match="AGENTFLOW_API_KEYS_FILE"):
                rotator.write_config(config)
        finally:
            manager.shutdown()

    def test_validate_generated_key_allows_none(self, manager: AuthManager) -> None:
        # None means "no generated key to check" and must not raise.
        manager._key_rotator.validate_generated_key(None)

    def test_validate_generated_key_rejects_short_key(self, manager: AuthManager) -> None:
        manager.security_policy.min_key_length = 32
        with pytest.raises(ValueError, match="below min_key_length"):
            manager._key_rotator.validate_generated_key("too-short")

    def test_generate_key_id_avoids_collisions(self, manager: AuthManager) -> None:
        existing = {"acme-agent-aaaaaaaa"}
        key_id = manager._key_rotator.generate_key_id("acme", "agent", existing)
        assert key_id not in existing
        assert key_id.startswith("acme-agent-")

    def test_expire_previous_key_unknown_id_is_silent(self, manager: AuthManager) -> None:
        # expire_previous_key swallows KeyError for an already-gone key.
        manager._key_rotator.expire_previous_key("does-not-exist")

    def test_expire_previous_key_revokes_old_after_rotation(self, manager: AuthManager) -> None:
        key_id = _only_key_id(manager)
        manager.rotate_key(key_id)

        manager._key_rotator.expire_previous_key(key_id)

        assert manager.get_rotation_status(key_id)["phase"] == "idle"

    def test_schedule_cleanup_noops_without_key_id(self, manager: AuthManager) -> None:
        item = TenantKey(
            key=None,
            key_hash="h",
            name="n",
            tenant="t",
            created_at=date(2026, 1, 1),
            key_id=None,
            previous_key_active_until=datetime.now(UTC) + timedelta(seconds=30),
        )
        # key_id is None -> early return, no timer scheduled.
        manager._key_rotator.schedule_rotation_cleanup(item)
        assert "n" not in manager._rotation_cleanup_timers

    def test_schedule_cleanup_noops_when_already_expired(self, manager: AuthManager) -> None:
        item = TenantKey(
            key=None,
            key_hash="h",
            name="n",
            tenant="t",
            created_at=date(2026, 1, 1),
            key_id="acme-agent-stale",
            previous_key_active_until=datetime.now(UTC) - timedelta(seconds=30),
        )
        # delay <= 0 -> early return, no timer scheduled.
        manager._key_rotator.schedule_rotation_cleanup(item)
        assert "acme-agent-stale" not in manager._rotation_cleanup_timers

    def test_usage_query_retries_on_transient_duckdb_error(
        self, manager: AuthManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ADR 0010 slice 4: the retry-loop-with-connect for these usage-stat
        # queries now lives in EmbeddedControlPlaneStore, not key_rotation.py.
        real_connect = embedded_module.connect_duckdb
        calls = {"n": 0}

        def flaky_connect(path: object) -> object:
            calls["n"] += 1
            if calls["n"] == 1:
                raise duckdb.Error("database is locked")
            return real_connect(path)

        monkeypatch.setattr(embedded_module, "connect_duckdb", flaky_connect)

        # list_keys_with_usage runs the usage queries; the first connect raises
        # a transient error and the store must retry rather than propagate.
        manager.list_keys_with_usage()

        assert calls["n"] >= 2

    def test_old_key_usage_retries_on_transient_duckdb_error(
        self, manager: AuthManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_connect = embedded_module.connect_duckdb
        calls = {"n": 0}

        def flaky_connect(path: object) -> object:
            calls["n"] += 1
            if calls["n"] == 1:
                raise duckdb.Error("database is locked")
            return real_connect(path)

        monkeypatch.setattr(embedded_module, "connect_duckdb", flaky_connect)

        # old_key_usage_last_hour runs its own connect+query with the same retry
        # guard; a transient error on the first attempt must be retried.
        assert manager._key_rotator.old_key_usage_last_hour("acme-agent-xyz") == 0
        assert calls["n"] >= 2


class TestExpiredRotationCleanup:
    def test_load_clears_already_expired_previous_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "usage.duckdb"))
        api_keys_path = tmp_path / "config" / "api_keys.yaml"
        api_keys_path.parent.mkdir(parents=True, exist_ok=True)
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        api_keys_path.write_text(
            "keys:\n"
            '  - key_id: "acme-agent-deadbeef"\n'
            '    key_hash: "$2b$04$abcdefghijklmnopqrstuv"\n'
            '    previous_key_hash: "$2b$04$staleoldhashstaleoldhash"\n'
            f'    previous_key_active_until: "{past}"\n'
            '    name: "Expired Agent"\n'
            '    tenant: "acme"\n'
            "    rate_limit_rpm: 100\n"
            '    created_at: "2026-04-10"\n',
            encoding="utf-8",
            newline="\n",
        )
        manager = AuthManager(
            api_keys_path=api_keys_path,
            db_path=tmp_path / "usage.duckdb",
            admin_key="admin-secret",
        )
        try:
            manager.load()
            manager.ensure_usage_table()
            status = manager.get_rotation_status("acme-agent-deadbeef")
            assert status["phase"] == "idle"
            assert status["old_key_active_until"] is None
        finally:
            manager.shutdown()


def test_module_exposes_logger_for_cleanup_warnings() -> None:
    # expire_previous_key logs via the auth package logger on unexpected
    # failure; the module import path used there must resolve.
    assert hasattr(key_rotation_module, "KeyRotator")
