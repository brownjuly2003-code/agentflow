"""Branches of ``AuthManager`` key resolution and rate-limit bookkeeping that
no unit file reached.

Each one is a decision the module makes about *how* a key is resolved or how a
bucket is named, and each is only observable by driving the method directly:
the legacy rotation-grace scan (entries predating the M-C4 lookup digest), the
plaintext-cache guard for hash-only entries, the sweep that keeps a window
whose timestamps have not all expired, the batch debit in ``charge_rate_limit``,
and the ``_rate_limit_key`` fallbacks that keep a plaintext key out of a Redis
key name (audit S-6).

Pure calls only: no TestClient, no Redis, so the CI auth-manager coverage gate
can run this file.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from agentflow_runtime.serving.api.auth.manager import (
    DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    AuthManager,
    TenantKey,
)
from agentflow_runtime.serving.api.security import hash_api_key

BCRYPT_TEST_ROUNDS = 4


class _FrozenClock:
    def __init__(self, now: float = 10_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _CountingLimiter:
    """Records every ``check`` call and refuses once the budget is spent.

    No ``_redis`` attribute, so ``check_rate_limit`` skips its secondary
    in-memory window and each call is exactly one debit.
    """

    def __init__(self, budget: int) -> None:
        self.calls = 0
        self.budget = budget

    async def check(self, _key: str, _limit: int) -> tuple[bool, int, int]:
        self.calls += 1
        return self.calls <= self.budget, max(0, self.budget - self.calls), 0


def _key(**overrides: object) -> TenantKey:
    base: dict[str, object] = {
        "key": "plain-key",
        "name": "agent",
        "tenant": "acme",
        "created_at": date(2026, 1, 1),
    }
    base.update(overrides)
    return TenantKey(**base)  # type: ignore[arg-type]


def _manager(tmp_path: Path, **kwargs: object) -> AuthManager:
    manager = AuthManager(
        api_keys_path=None,
        db_path=tmp_path / "usage.duckdb",
        admin_key="admin-secret",
        **kwargs,  # type: ignore[arg-type]
    )
    manager.load()
    manager.security_policy.bcrypt_rounds = BCRYPT_TEST_ROUNDS
    return manager


def test_a_hash_only_entry_is_skipped_by_the_plaintext_fast_path(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    hashed = _key(key=None, key_hash=hash_api_key("stored", BCRYPT_TEST_ROUNDS, scheme="bcrypt"))
    # A hashed entry can sit in the plaintext map after a reload dropped its
    # cached plaintext. The fast path must step over it instead of comparing
    # against None.
    manager.keys_by_value = {"stale-plaintext": hashed}

    assert manager.authenticate("some-other-key") is None


def test_a_legacy_previous_key_still_resolves_through_the_rotation_grace_scan(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    old_key = "retired-key"
    item = _key(
        key=None,
        key_hash=hash_api_key("current", BCRYPT_TEST_ROUNDS, scheme="bcrypt"),
        previous_key_hash=hash_api_key(old_key, BCRYPT_TEST_ROUNDS, scheme="bcrypt"),
        previous_key_active_until=datetime.now(UTC) + timedelta(hours=1),
    )
    # No key_lookup / previous_key_lookup: a pre-M-C4 entry, which is exactly
    # what the O(n) scan exists for.
    manager._loaded_keys = [item]

    matched = manager.authenticate(old_key)

    assert matched is not None
    assert matched.matched_slot == "previous"
    assert matched.tenant == "acme"


def test_the_grace_scan_skips_entries_the_o1_lookup_already_owns(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    old_key = "retired-key"
    item = _key(
        key=None,
        key_hash=hash_api_key("current", BCRYPT_TEST_ROUNDS, scheme="bcrypt"),
        previous_key_hash=hash_api_key(old_key, BCRYPT_TEST_ROUNDS, scheme="bcrypt"),
        previous_key_lookup="a-digest-the-index-resolves",
        previous_key_active_until=datetime.now(UTC) + timedelta(hours=1),
    )
    # The entry carries a previous_key_lookup, so `_previous_keys_by_lookup`
    # is authoritative for it. Leaving it out of that index and out of the
    # scan is the point: the scan must not pay a second verify for a key the
    # O(1) path already declined.
    manager._loaded_keys = [item]

    assert manager.authenticate(old_key) is None


def test_a_legacy_previous_key_outside_its_grace_window_is_not_resolvable(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    old_key = "retired-key"
    manager._loaded_keys = [
        _key(
            key=None,
            key_hash=hash_api_key("current", BCRYPT_TEST_ROUNDS, scheme="bcrypt"),
            previous_key_hash=hash_api_key(old_key, BCRYPT_TEST_ROUNDS, scheme="bcrypt"),
            previous_key_active_until=datetime.now(UTC) - timedelta(seconds=1),
        )
    ]

    assert manager.authenticate(old_key) is None


def test_the_runtime_cache_ignores_a_match_with_no_stored_hash(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    plaintext_only = _key(key="plain-key", key_hash=None)

    manager._remember_runtime_key("plain-key", plaintext_only)

    # The cache is keyed by hash: an entry with none would land under a None
    # key and be handed to the next caller presenting anything.
    assert manager.keys_by_value == {}
    assert manager._runtime_plaintext_by_hash == {}


def test_the_sweep_keeps_a_window_that_has_not_fully_expired(tmp_path: Path) -> None:
    clock = _FrozenClock()
    manager = _manager(tmp_path, time_source=clock)
    recent = clock.now - 1.0
    expired = clock.now - DEFAULT_RATE_LIMIT_WINDOW_SECONDS - 1.0
    manager._rate_windows["kid:live"] = [expired, recent]
    manager._rate_windows["kid:idle"] = [expired]

    manager._sweep_expired_windows()

    # Trimmed, not dropped: dropping it would hand the caller a fresh budget.
    assert manager._rate_windows["kid:live"] == [recent]
    assert "kid:idle" not in manager._rate_windows


async def test_charging_a_batch_debits_every_unit_even_after_the_budget_is_gone(
    tmp_path: Path,
) -> None:
    limiter = _CountingLimiter(budget=2)
    manager = _manager(tmp_path, rate_limiter=limiter)

    allowed = await manager.charge_rate_limit(_key(key_id="kid-1"), units=3)

    assert allowed is False
    # All three are debited: a partially-charged batch would let the caller
    # retry the remainder for free.
    assert limiter.calls == 3


async def test_charging_a_batch_within_budget_is_allowed(tmp_path: Path) -> None:
    limiter = _CountingLimiter(budget=5)
    manager = _manager(tmp_path, rate_limiter=limiter)

    assert await manager.charge_rate_limit(_key(key_id="kid-1"), units=2) is True
    assert limiter.calls == 2


@pytest.mark.parametrize("units", [0, -3])
async def test_charging_no_units_touches_the_bucket_at_all(tmp_path: Path, units: int) -> None:
    limiter = _CountingLimiter(budget=0)
    manager = _manager(tmp_path, rate_limiter=limiter)

    assert await manager.charge_rate_limit(_key(key_id="kid-1"), units=units) is True
    assert limiter.calls == 0


def test_the_bucket_name_falls_back_to_the_stored_hash(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    stored = hash_api_key("plain-key", BCRYPT_TEST_ROUNDS, scheme="bcrypt")

    assert manager._rate_limit_key(_key(key=None, key_hash=stored)) == f"kh:{stored}"


def test_the_bucket_name_falls_back_to_the_non_secret_name(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    # Empty key material passes model validation (the validator rejects None,
    # not ""), and it is the one shape that reaches the final fallback.
    nameless_material = _key(key="", key_hash=None, name="ops-agent")

    assert manager._rate_limit_key(nameless_material) == "name:ops-agent"


def test_key_material_matches_a_key_inside_its_rotation_grace_window(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    old_key = "retired-key"
    item = _key(
        key=None,
        key_hash=hash_api_key("current", BCRYPT_TEST_ROUNDS, scheme="bcrypt"),
        previous_key_hash=hash_api_key(old_key, BCRYPT_TEST_ROUNDS, scheme="bcrypt"),
    )

    # The revoke path matches on any live material for the entry, so a caller
    # holding only the previous key can still revoke what it owns.
    assert manager._matches_key_material(item, old_key) is True
