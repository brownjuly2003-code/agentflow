"""C-4: AuthManager cache writes in ``authenticate()`` must be atomic with
respect to the ``load()`` / ``reload()`` rebuild.

``authenticate()`` caches the plaintext->key binding it just verified so repeat
lookups skip the slow argon2/bcrypt verify. ``load()`` (driven by SIGHUP via
``reload()``) rebuilds ``keys_by_value`` and ``_runtime_plaintext_by_hash``
wholesale under ``_config_lock``. If the cache write is not also under the
lock, a concurrent reload can interleave between the two map writes and leave
the maps inconsistent (a key present in ``keys_by_value`` but missing from
``_runtime_plaintext_by_hash``, so the next reload silently drops it).

The slow verify itself stays OUTSIDE the lock, so a reload is never serialized
behind a bcrypt/argon2 verification — only the two fast dict writes are guarded.
"""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

import yaml

from src.serving.api.auth import AuthManager
from src.serving.api.auth.manager import TenantKey
from src.serving.api.security import compute_key_lookup, hash_api_key

BCRYPT_TEST_ROUNDS = 4


def _write_keys(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"keys": entries}, sort_keys=False), encoding="utf-8")


def _manager(tmp_path: Path) -> AuthManager:
    return AuthManager(
        api_keys_path=tmp_path / "config" / "api_keys.yaml",
        db_path=tmp_path / "usage.duckdb",
    )


def test_remember_runtime_key_is_serialized_against_config_lock(tmp_path: Path) -> None:
    """The cache write must block while a reload holds ``_config_lock``.

    Regression guard for C-4: without ``with self._config_lock`` in
    ``_remember_runtime_key`` the writer thread completes while the lock is
    held here, so ``done`` would be set during the held window and the
    ``not done.wait(...)`` assertion fails.
    """
    mgr = _manager(tmp_path)
    plaintext = "plain-test-key"
    matched = TenantKey(
        key_id="k1",
        key=plaintext,
        key_hash=hash_api_key(plaintext, rounds=BCRYPT_TEST_ROUNDS, scheme="bcrypt"),
        name="Agent A",
        tenant="t",
        created_at=date(2026, 1, 1),
    )
    started = threading.Event()
    done = threading.Event()

    def writer() -> None:
        started.set()
        mgr._remember_runtime_key(plaintext, matched)
        done.set()

    mgr._config_lock.acquire()
    worker = threading.Thread(target=writer)
    try:
        worker.start()
        assert started.wait(1.0), "writer thread never started"
        # Writer must be parked on _config_lock; it must NOT finish the write.
        assert not done.wait(0.3), (
            "authenticate cache write completed without holding _config_lock (C-4 race)"
        )
    finally:
        mgr._config_lock.release()

    assert done.wait(1.0), "writer never completed after lock release"
    worker.join(1.0)
    assert mgr.keys_by_value.get(plaintext) is matched
    assert mgr._runtime_plaintext_by_hash.get(matched.key_hash) == plaintext


def test_authenticate_under_concurrent_reload_stays_consistent(tmp_path: Path) -> None:
    """Hammer authenticate() while reload() rebuilds the maps in parallel.

    Asserts no exception escapes (e.g. dict-mutation errors), every successful
    authentication returns the right tenant, and the plaintext cache never
    references a hash that is not live — the invariant load()'s GC relies on.
    """
    api_keys = tmp_path / "config" / "api_keys.yaml"
    plaintext = "key-abc123def456"
    _write_keys(
        api_keys,
        [
            {
                "key_id": "k1",
                "key_hash": hash_api_key(plaintext, rounds=BCRYPT_TEST_ROUNDS, scheme="bcrypt"),
                "key_lookup": compute_key_lookup(plaintext),
                "name": "Agent A",
                "tenant": "t",
                "created_at": "2026-01-01",
            }
        ],
    )
    mgr = _manager(tmp_path)
    mgr.load()

    errors: list[Exception] = []
    results: list[TenantKey | None] = []

    def auth_worker() -> None:
        try:
            for _ in range(25):
                results.append(mgr.authenticate(plaintext))
        except Exception as exc:  # noqa: BLE001 - surface any thread error to the assertion
            errors.append(exc)

    def reload_worker() -> None:
        try:
            for _ in range(25):
                mgr.load()
        except Exception as exc:  # noqa: BLE001 - surface any thread error to the assertion
            errors.append(exc)

    threads = [threading.Thread(target=auth_worker) for _ in range(6)]
    threads += [threading.Thread(target=reload_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    assert not errors, f"concurrent auth/reload raised: {errors!r}"
    assert results, "no authentication attempts recorded"
    assert all(r is not None and r.tenant == "t" for r in results)
    live_hashes = {item.key_hash for item in mgr._hashed_keys if item.key_hash}
    assert set(mgr._runtime_plaintext_by_hash) <= live_hashes
