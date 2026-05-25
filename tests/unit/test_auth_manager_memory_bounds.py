"""Regression tests for H-C4 (audit_kimi_25_05_26): AuthManager's
``_rate_windows`` / ``_failed_auth_windows`` / ``_runtime_plaintext_by_hash``
dicts must not grow unbounded across the lifetime of the process. Stale
entries (windows fully aged out, hashes for revoked keys) should be
swept by ``_sweep_expired_windows`` on ``load()`` and on every successful
``clear_failed_auth`` call."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.constants import DEFAULT_RATE_LIMIT_WINDOW_SECONDS, FAILED_AUTH_WINDOW_SECONDS
from src.serving.api.auth.manager import AuthManager


def _write_keys(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def manager(tmp_path: Path) -> AuthManager:
    api_keys_path = tmp_path / "api_keys.yaml"
    _write_keys(api_keys_path, "keys: []\n")
    return AuthManager(api_keys_path=api_keys_path, db_path=tmp_path / "usage.duckdb")


class TestFailedAuthWindowSweep:
    def test_clear_failed_auth_evicts_expired_windows_for_unrelated_ips(
        self, manager: AuthManager
    ) -> None:
        now = manager.time_source()
        manager._failed_auth_windows["1.2.3.4"] = [now - FAILED_AUTH_WINDOW_SECONDS - 1]
        manager._failed_auth_windows["5.6.7.8"] = [now - FAILED_AUTH_WINDOW_SECONDS - 5]
        manager._failed_auth_windows["9.9.9.9"] = [now - 10]  # still inside cutoff

        # clear_failed_auth pops its own IP, plus the opportunistic sweep
        # must reap every IP whose entire window has aged out.
        manager.clear_failed_auth("9.9.9.9")
        assert manager._failed_auth_windows == {}

    def test_clear_failed_auth_preserves_active_windows_for_other_ips(
        self, manager: AuthManager
    ) -> None:
        now = manager.time_source()
        manager._failed_auth_windows["1.2.3.4"] = [now - 5, now - 1]
        manager.clear_failed_auth("not-tracked")
        assert "1.2.3.4" in manager._failed_auth_windows


class TestRateWindowSweepOnLoad:
    def test_load_sweeps_expired_rate_windows(self, manager: AuthManager) -> None:
        now = manager.time_source()
        manager._rate_windows["stale-key"] = [now - DEFAULT_RATE_LIMIT_WINDOW_SECONDS - 1]
        manager._rate_windows["fresh-key"] = [now - 5]
        manager.load()  # triggers _sweep_expired_windows under config lock
        assert "stale-key" not in manager._rate_windows
        # 'fresh-key' is also removed because load() rebuilds _rate_windows
        # from keys_by_value (none configured in this fixture) — that
        # rebuild is documented behaviour from session 17 and is independent
        # of the H-C4 sweep, but the assertion below pins it so a future
        # refactor that reuses the old `defaultdict` cannot reintroduce
        # the unbounded-growth path silently.
        assert "fresh-key" not in manager._rate_windows


class TestRuntimePlaintextCacheCleanup:
    def test_load_drops_plaintext_entries_for_unknown_hashes(self, tmp_path: Path) -> None:
        api_keys_path = tmp_path / "api_keys.yaml"
        _write_keys(api_keys_path, "keys: []\n")
        mgr = AuthManager(api_keys_path=api_keys_path, db_path=tmp_path / "usage.duckdb")

        # Simulate that two hashed keys were validated at some point; only
        # one is still present in the on-disk config. After reload the
        # cache must drop the orphaned hash.
        mgr._runtime_plaintext_by_hash["hash-still-live"] = "plaintext-still-live"
        mgr._runtime_plaintext_by_hash["hash-revoked"] = "plaintext-revoked"
        _write_keys(
            api_keys_path,
            "keys:\n"
            "  - key_id: live-key\n"
            "    key_hash: hash-still-live\n"
            "    name: Live Key\n"
            "    tenant: acme\n"
            "    rate_limit_rpm: 60\n"
            "    created_at: '2026-04-10'\n",
        )
        mgr.load()
        assert mgr._runtime_plaintext_by_hash == {"hash-still-live": "plaintext-still-live"}


class TestSweepIdempotent:
    def test_sweep_is_safe_on_empty_state(self, manager: AuthManager) -> None:
        # Calling on a fresh manager must not raise and must leave the
        # dicts in the same empty shape.
        manager._sweep_expired_windows()
        assert manager._rate_windows == {}
        assert manager._failed_auth_windows == {}
