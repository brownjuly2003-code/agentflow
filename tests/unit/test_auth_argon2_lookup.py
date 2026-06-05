"""M-C4 full closure: argon2id hash format + O(1) peppered lookup index.

`docs/perf/auth-bench-2026-05-26.md` measured the cold-cache worst case of
``authenticate()`` at N x ~400 ms (one bcrypt verify per hashed key) and
deferred the real fix — "argon2id with a deterministic peppered prefix so we
can index the lookup" (`docs/runbooks/auth-401-spike.md`) — behind a product
decision. That decision landed 2026-06-05: new key material is hashed with
argon2id and stored alongside a deterministic HMAC-SHA256 lookup digest, so
``authenticate()`` resolves the candidate in O(1) and runs exactly ONE slow
verify. Legacy bcrypt entries (no ``key_lookup``) keep working through the
old O(n) fallback scan.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import structlog
import yaml

from src.serving.api import security as security_module
from src.serving.api.auth import AuthManager
from src.serving.api.auth import manager as manager_module
from src.serving.api.security import (
    compute_key_lookup,
    hash_api_key,
    verify_api_key,
)

BCRYPT_TEST_ROUNDS = 4


@pytest.fixture(autouse=True)
def _uncached_auth_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same order-independence guard as test_auth_hashed_key_guidance.py:
    # earlier suites may freeze production processors onto the package logger.
    from src.serving.api import auth as auth_package

    monkeypatch.setattr(auth_package, "logger", structlog.get_logger())


def _write_keys(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"keys": entries}, sort_keys=False), encoding="utf-8")


def _manager(tmp_path: Path) -> AuthManager:
    return AuthManager(
        api_keys_path=tmp_path / "config" / "api_keys.yaml",
        db_path=tmp_path / "usage.duckdb",
    )


def _entry(index: int, plaintext: str, *, indexed: bool = True, scheme: str = "argon2id") -> dict:
    entry = {
        "key_id": f"key-{index}",
        "key_hash": hash_api_key(plaintext, rounds=BCRYPT_TEST_ROUNDS, scheme=scheme),
        "name": f"Agent {index}",
        "tenant": "acme",
        "rate_limit_rpm": 120,
        "created_at": "2026-06-05",
    }
    if indexed:
        entry["key_lookup"] = compute_key_lookup(plaintext)
    return entry


# --- hash format -----------------------------------------------------------


def test_hash_api_key_defaults_to_argon2id():
    digest = hash_api_key("af-prod-acme-agent-secret", rounds=BCRYPT_TEST_ROUNDS)
    assert digest.startswith("$argon2id$")


def test_hash_api_key_bcrypt_scheme_still_available():
    digest = hash_api_key("af-prod-acme-agent-secret", rounds=BCRYPT_TEST_ROUNDS, scheme="bcrypt")
    assert digest.startswith("$2")


def test_verify_api_key_accepts_argon2id():
    digest = hash_api_key("the-key", rounds=BCRYPT_TEST_ROUNDS)
    assert verify_api_key("the-key", digest)
    assert not verify_api_key("not-the-key", digest)


def test_verify_api_key_still_accepts_legacy_bcrypt():
    digest = hash_api_key("the-key", rounds=BCRYPT_TEST_ROUNDS, scheme="bcrypt")
    assert verify_api_key("the-key", digest)
    assert not verify_api_key("not-the-key", digest)


def test_hash_api_key_rejects_unknown_scheme():
    with pytest.raises(ValueError, match="scheme"):
        hash_api_key("the-key", rounds=BCRYPT_TEST_ROUNDS, scheme="md5")


# --- lookup digest ---------------------------------------------------------


def test_compute_key_lookup_is_deterministic():
    assert compute_key_lookup("same-key") == compute_key_lookup("same-key")
    assert compute_key_lookup("same-key") != compute_key_lookup("other-key")


def test_compute_key_lookup_depends_on_pepper(monkeypatch: pytest.MonkeyPatch):
    baseline = compute_key_lookup("same-key")
    monkeypatch.setenv("AGENTFLOW_KEY_LOOKUP_PEPPER", "another-pepper")
    assert compute_key_lookup("same-key") != baseline


# --- O(1) authenticate -----------------------------------------------------


def test_authenticate_indexed_key_runs_single_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Hit-last with 8 indexed keys must cost exactly one slow verify."""
    plaintexts = [f"af-prod-acme-agent-{i}-0123456789abcdef" for i in range(8)]
    _write_keys(
        tmp_path / "config" / "api_keys.yaml", [_entry(i, pt) for i, pt in enumerate(plaintexts)]
    )
    manager = _manager(tmp_path)
    manager.load()

    calls: list[str] = []
    real_verify = manager_module.verify_api_key

    def counting_verify(value: str, key_hash: str) -> bool:
        calls.append(key_hash)
        return real_verify(value, key_hash)

    monkeypatch.setattr(manager_module, "verify_api_key", counting_verify)

    matched = manager.authenticate(plaintexts[-1])

    assert matched is not None
    assert matched.key_id == "key-7"
    assert len(calls) == 1, f"indexed lookup must verify once, saw {len(calls)}"


def test_authenticate_rejects_wrong_key_without_legacy_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A miss against an all-indexed config must not fall into O(n) verifies."""
    _write_keys(
        tmp_path / "config" / "api_keys.yaml",
        [_entry(i, f"af-prod-acme-agent-{i}-0123456789abcdef") for i in range(8)],
    )
    manager = _manager(tmp_path)
    manager.load()

    calls: list[str] = []
    real_verify = manager_module.verify_api_key

    def counting_verify(value: str, key_hash: str) -> bool:
        calls.append(key_hash)
        return real_verify(value, key_hash)

    monkeypatch.setattr(manager_module, "verify_api_key", counting_verify)

    assert manager.authenticate("af-prod-acme-bogus-ffffffffffffffff") is None
    assert calls == [], "an unindexed miss must not pay any slow verifies"


def test_authenticate_legacy_bcrypt_unindexed_still_works(tmp_path: Path):
    plaintext = "af-prod-acme-legacy-0123456789abcdef"
    _write_keys(
        tmp_path / "config" / "api_keys.yaml",
        [_entry(0, plaintext, indexed=False, scheme="bcrypt")],
    )
    manager = _manager(tmp_path)
    manager.load()

    matched = manager.authenticate(plaintext)

    assert matched is not None
    assert matched.tenant == "acme"


def test_authenticate_mixed_config_prefers_index_and_keeps_legacy(tmp_path: Path):
    indexed_plain = "af-prod-acme-indexed-0123456789abcdef"
    legacy_plain = "af-prod-acme-legacy-0123456789abcdef"
    _write_keys(
        tmp_path / "config" / "api_keys.yaml",
        [
            _entry(0, indexed_plain),
            _entry(1, legacy_plain, indexed=False, scheme="bcrypt"),
        ],
    )
    manager = _manager(tmp_path)
    manager.load()

    assert manager.authenticate(indexed_plain) is not None
    assert manager.authenticate(legacy_plain) is not None
    assert manager.authenticate("af-prod-acme-bogus-ffffffffffffffff") is None


def test_authenticate_previous_slot_uses_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    old_plain = "af-prod-acme-old-0123456789abcdef"
    new_plain = "af-prod-acme-new-0123456789abcdef"
    active_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    entry = _entry(0, new_plain)
    entry["previous_key_hash"] = hash_api_key(old_plain, rounds=BCRYPT_TEST_ROUNDS)
    entry["previous_key_lookup"] = compute_key_lookup(old_plain)
    entry["previous_key_active_until"] = active_until
    _write_keys(tmp_path / "config" / "api_keys.yaml", [entry])
    manager = _manager(tmp_path)
    manager.load()

    calls: list[str] = []
    real_verify = manager_module.verify_api_key

    def counting_verify(value: str, key_hash: str) -> bool:
        calls.append(key_hash)
        return real_verify(value, key_hash)

    monkeypatch.setattr(manager_module, "verify_api_key", counting_verify)

    matched = manager.authenticate(old_plain)

    assert matched is not None
    assert matched.matched_slot == "previous"
    assert len(calls) == 1, f"previous-slot lookup must verify once, saw {len(calls)}"


# --- rotation writes lookups ------------------------------------------------


def test_create_key_persists_lookup(tmp_path: Path):
    from src.serving.api.auth.manager import KeyCreateRequest

    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, [])
    manager = _manager(tmp_path)
    manager.load()

    created = manager.create_key(
        KeyCreateRequest(name="Fresh Agent", tenant="acme", rate_limit_rpm=120)
    )

    stored = yaml.safe_load(api_keys_path.read_text(encoding="utf-8"))["keys"][0]
    assert stored["key_hash"].startswith("$argon2id$")
    assert stored["key_lookup"] == compute_key_lookup(created.key)
    assert "key" not in stored


def test_rotate_key_moves_lookup_to_previous_slot(tmp_path: Path):
    plaintext = "af-prod-acme-agent-0-0123456789abcdef"
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, [_entry(0, plaintext)])
    manager = _manager(tmp_path)
    manager.load()

    rotated, _expires = manager.rotate_key("key-0")

    stored = yaml.safe_load(api_keys_path.read_text(encoding="utf-8"))["keys"][0]
    assert stored["key_lookup"] == compute_key_lookup(rotated.key)
    assert stored["previous_key_lookup"] == compute_key_lookup(plaintext)
    assert stored["previous_key_hash"].startswith("$argon2id$")

    # the old plaintext still authenticates during grace, via its lookup
    assert manager.authenticate(plaintext) is not None
    # revoking the old slot clears the previous lookup as well
    assert manager.revoke_old_key("key-0") is True
    cleared = yaml.safe_load(api_keys_path.read_text(encoding="utf-8"))["keys"][0]
    assert "previous_key_lookup" not in cleared


# --- soft-limit warning scopes to unindexed keys ----------------------------


def test_soft_limit_warning_counts_only_unindexed_keys(tmp_path: Path):
    from src.constants import HASHED_KEY_SOFT_LIMIT

    over = HASHED_KEY_SOFT_LIMIT + 1
    entries = [_entry(i, f"af-prod-acme-agent-{i}-0123456789abcdef") for i in range(over)]
    _write_keys(tmp_path / "config" / "api_keys.yaml", entries)
    manager = _manager(tmp_path)

    with structlog.testing.capture_logs() as events:
        manager.load()

    warnings = [
        event for event in events if event.get("event") == "hashed_key_count_exceeds_guidance"
    ]
    assert not warnings, (
        "indexed argon2id keys resolve in O(1) and must not trip the "
        "cold-cache O(n) soft-limit warning"
    )


def test_soft_limit_warning_still_fires_for_unindexed_keys(tmp_path: Path):
    from src.constants import HASHED_KEY_SOFT_LIMIT

    over = HASHED_KEY_SOFT_LIMIT + 1
    entries = [
        _entry(i, f"af-prod-acme-agent-{i}-0123456789abcdef", indexed=False) for i in range(over)
    ]
    _write_keys(tmp_path / "config" / "api_keys.yaml", entries)
    manager = _manager(tmp_path)

    with structlog.testing.capture_logs() as events:
        manager.load()

    warnings = [
        event for event in events if event.get("event") == "hashed_key_count_exceeds_guidance"
    ]
    assert warnings
    assert warnings[0]["hashed_keys"] == over


def test_security_policy_defaults_to_argon2id():
    assert security_module.SecurityPolicy().key_hashing == "argon2id"
