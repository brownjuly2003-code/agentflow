"""Revoke-by-id and the failure paths of the key-rotation lifecycle.

``tests/unit/test_key_rotation.py`` pins the happy lifecycle. This file covers
what it does not reach: ``revoke_key_by_id`` -- the whole reason F-02 A stopped
taking the plaintext key in a URL, and the only revoke path the admin router
now calls -- plus the three failures the rotator has to distinguish rather than
crash on: a read-only key store, a store that is broken rather than read-only,
and a background grace-period cleanup that fails after the caller is gone.

Direct rotator calls: no TestClient, so the CI key-rotation coverage gate can
run this file.
"""

from __future__ import annotations

import errno
from datetime import date
from pathlib import Path

import pytest
import structlog

from agentflow_runtime.serving.api.auth.key_rotation import KeyStoreReadOnlyError
from agentflow_runtime.serving.api.auth.manager import (
    ApiKeysConfig,
    AuthManager,
    KeyCreateRequest,
    TenantKey,
)

SEED_KEY_YAML = (
    "keys:\n"
    '  - key: "rotation-acme-key"\n'
    '    name: "Rotation Agent"\n'
    '    tenant: "acme"\n'
    "    rate_limit_rpm: 100\n"
    "    allowed_entity_types: null\n"
    '    created_at: "2026-04-10"\n'
)


@pytest.fixture(autouse=True)
def _uncached_auth_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentflow_runtime.serving.api import auth as auth_package

    monkeypatch.setattr(auth_package, "logger", structlog.get_logger())


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AuthManager:
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "usage.duckdb"))
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(SEED_KEY_YAML, encoding="utf-8", newline="\n")
    mgr = AuthManager(
        api_keys_path=api_keys_path,
        db_path=tmp_path / "usage.duckdb",
        admin_key="admin-secret",
    )
    # bcrypt-12 is slow and every create/rotate hashes several times; the hash
    # format is unchanged, only the cost factor.
    mgr.security_policy.bcrypt_rounds = 4
    mgr.load()
    mgr.ensure_usage_table()
    try:
        yield mgr
    finally:
        mgr.shutdown()


def _only_key_id(manager: AuthManager) -> str:
    keys = manager.list_keys_with_usage()
    assert keys, "expected at least one configured key"
    key_id = keys[0]["key_id"]
    assert key_id is not None
    return str(key_id)


def test_revoking_by_key_id_removes_the_entry(manager: AuthManager) -> None:
    key_id = _only_key_id(manager)

    assert manager.revoke_key_by_id(key_id) is True

    assert manager.list_keys_with_usage() == []


def test_revoking_an_unknown_key_id_changes_nothing(manager: AuthManager) -> None:
    before = manager.list_keys_with_usage()

    assert manager.revoke_key_by_id("no-such-key-id") is False

    # No write, no reload: an admin typo must not disturb the live store.
    assert manager.list_keys_with_usage() == before


def test_revoking_by_key_id_stops_a_cached_plaintext_from_authenticating(
    manager: AuthManager,
) -> None:
    created = manager.create_key(
        KeyCreateRequest(name="Support Agent", tenant="globex", rate_limit_rpm=7)
    )
    assert created.key is not None
    plaintext = created.key
    assert manager.authenticate(plaintext) is not None
    assert created.key_hash in manager._runtime_plaintext_by_hash
    assert created.key_id is not None

    assert manager.revoke_key_by_id(created.key_id) is True

    # The plaintext->key cache exists to skip the slow verify. If revoke left an
    # entry behind, the revoked key would keep authenticating from memory for
    # the life of the process.
    assert created.key_hash not in manager._runtime_plaintext_by_hash
    assert manager.authenticate(plaintext) is None


def test_rotating_an_entry_with_no_key_material_is_refused(manager: AuthManager) -> None:
    key_id = _only_key_id(manager)
    stored = manager._load_config().keys[0]
    hollow = stored.model_copy(update={"key": None, "key_hash": None})

    # A store on disk cannot produce this: ApiKeysConfig validation rejects an
    # entry with neither key nor key_hash, which is why the config has to be
    # built unvalidated to get here at all. The branch is defensive -- it is the
    # difference between a named refusal and a TypeError inside hash_api_key.
    def _hollow_config() -> ApiKeysConfig:
        return ApiKeysConfig.model_construct(keys=[hollow])

    manager._load_config = _hollow_config  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="Current key material is unavailable"):
        manager.rotate_key(key_id)


def test_a_read_only_store_is_reported_as_read_only(
    manager: AuthManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = manager._load_config()

    def _denied(self: Path, *args: object, **kwargs: object) -> int:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(Path, "write_text", _denied)

    with pytest.raises(KeyStoreReadOnlyError):
        manager._key_rotator.write_config(config)
    # The manager downgrades in place, so the next admin mutation answers 409
    # instead of probing the mount again.
    assert manager._key_store_writable is False


def test_a_broken_store_is_not_reported_as_read_only(
    manager: AuthManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = manager._load_config()

    def _io_error(self: Path, *args: object, **kwargs: object) -> int:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(Path, "write_text", _io_error)

    with pytest.raises(OSError) as excinfo:
        manager._key_rotator.write_config(config)

    assert not isinstance(excinfo.value, KeyStoreReadOnlyError)
    assert excinfo.value.errno == errno.EIO
    # A failing disk is not a read-only mount: leaving the flag alone keeps the
    # 409 for the case that really means it.
    assert manager._key_store_writable is not False


def test_a_failed_grace_period_cleanup_is_logged_and_swallowed(manager: AuthManager) -> None:
    def _boom(_key_id: str) -> bool:
        raise RuntimeError("store went away")

    manager._key_rotator.revoke_old_key = _boom  # type: ignore[method-assign]

    with structlog.testing.capture_logs() as events:
        manager._key_rotator.expire_previous_key("acme-ops-abcd")

    # This runs on a timer thread with no caller left to catch it: an exception
    # here would be swallowed by threading with no record at all.
    assert any(event.get("event") == "api_key_rotation_cleanup_failed" for event in events)
    assert any("store went away" in str(event.get("error", "")) for event in events)


def test_a_cleanup_for_an_unknown_key_is_silent(manager: AuthManager) -> None:
    def _missing(_key_id: str) -> bool:
        raise KeyError("gone")

    manager._key_rotator.revoke_old_key = _missing  # type: ignore[method-assign]

    with structlog.testing.capture_logs() as events:
        manager._key_rotator.expire_previous_key("acme-ops-abcd")

    # A key revoked before its grace timer fired is the expected race, not a
    # fault worth waking anyone for.
    assert not [
        event for event in events if event.get("event") == "api_key_rotation_cleanup_failed"
    ]


def test_a_created_key_can_be_revoked_by_its_id_only(manager: AuthManager) -> None:
    created = manager.create_key(
        KeyCreateRequest(name="Second Agent", tenant="globex", rate_limit_rpm=5)
    )
    assert created.key_id is not None

    # F-02 A: the plaintext is not an identifier the admin surface accepts. It
    # is still valid key material, so revoke must not resolve it as an id.
    assert manager.revoke_key_by_id(str(created.key)) is False
    assert manager.revoke_key_by_id(created.key_id) is True

    remaining = {key["key_id"] for key in manager.list_keys_with_usage()}
    assert created.key_id not in remaining


def test_the_seeded_entry_survives_an_unrelated_revoke(manager: AuthManager) -> None:
    seeded = _only_key_id(manager)
    created = manager.create_key(
        KeyCreateRequest(name="Third Agent", tenant="globex", rate_limit_rpm=5)
    )
    assert created.key_id is not None

    assert manager.revoke_key_by_id(created.key_id) is True

    remaining = {key["key_id"] for key in manager.list_keys_with_usage()}
    assert remaining == {seeded}


def test_a_revoked_entry_leaves_no_previous_slot_behind(manager: AuthManager) -> None:
    key_id = _only_key_id(manager)
    rotated, _expires_at = manager.rotate_key(key_id)
    assert rotated.previous_key_hash is not None

    assert manager.revoke_key_by_id(key_id) is True

    stored: list[TenantKey] = manager._load_config().keys
    assert [item for item in stored if item.key_id == key_id] == []
    assert manager.list_keys_with_usage() == []


def test_revoking_the_last_key_leaves_a_loadable_store(manager: AuthManager) -> None:
    key_id = _only_key_id(manager)

    assert manager.revoke_key_by_id(key_id) is True

    reloaded = AuthManager(
        api_keys_path=manager.api_keys_path,
        db_path=manager.db_path,
        admin_key="admin-secret",
    )
    reloaded.load()
    try:
        # An empty store is a valid store: writing something a later load()
        # cannot parse would take the API down on the next restart.
        assert reloaded.configured_key_count == 0
        assert reloaded.authenticate("rotation-acme-key") is None
    finally:
        reloaded.shutdown()


def test_a_revoked_key_id_is_gone_from_rotation_status(manager: AuthManager) -> None:
    created = manager.create_key(
        KeyCreateRequest(name="Fourth Agent", tenant="globex", rate_limit_rpm=5)
    )
    assert created.key_id is not None
    assert manager.get_rotation_status(created.key_id)["phase"] in {"idle", "grace_period"}

    assert manager.revoke_key_by_id(created.key_id) is True

    with pytest.raises(KeyError):
        manager.get_rotation_status(created.key_id)


def test_the_seed_entry_is_created_with_a_date(manager: AuthManager) -> None:
    stored = manager._load_config().keys[0]

    # ensure_key_ids() rewrites the store on first load; the created_at it
    # writes back has to survive that round trip as a date, not a string.
    assert isinstance(stored.created_at, date)
