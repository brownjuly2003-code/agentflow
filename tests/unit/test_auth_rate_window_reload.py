"""Reloading the key store keeps the in-memory rate-limit windows
(docs/specs/api-key-rate-limiting.md, T-46).

``AuthManager.load()`` runs on SIGHUP and at the end of every key create,
rotate and revoke. It used to rebuild ``_rate_windows`` from ``keys_by_value``
-- the PLAINTEXT key index -- while every window is named by
``_rate_limit_key()`` (``kid:<key_id>``), so each reload emptied every window
and handed every tenant a fresh budget. One test per spec scenario, against
both readers of the window: ``is_rate_limited()`` and the secondary check in
``check_rate_limit()``.

Keys live in a tmp key file with an explicit ``key_id``: environment keys get
a random key_id on every load (until T-47), so they cannot pin a bucket here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentflow_runtime.serving.api.auth.manager import AuthManager

ALPHA_PLAIN = "plain-secret-alpha"
BETA_PLAIN = "plain-secret-beta"
ALPHA_ID = "acme-support-1a2b3c4d"
BETA_ID = "acme-billing-5e6f7a8b"


class _FrozenClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _FullRemainingLimiter:
    """Redis limiter that answers "allowed, full quota" while its `_redis`
    handle is live -- the condition for `check_rate_limit`'s in-memory
    secondary window."""

    def __init__(self) -> None:
        self._redis = object()

    async def check(self, key: str, rpm: int) -> tuple[bool, int, int]:
        return True, rpm, 0


def _entry(key_id: str, plain: str, name: str) -> str:
    return (
        f"  - key_id: {key_id}\n"
        f"    key: {plain}\n"
        f"    name: {name}\n"
        "    tenant: acme\n"
        "    rate_limit_rpm: 1\n"
        "    created_at: '2026-04-10'\n"
    )


def _write_keys(path: Path, *entries: str) -> None:
    path.write_text("keys:\n" + "".join(entries), encoding="utf-8")


def _manager(tmp_path: Path, *entries: str, **overrides: object) -> AuthManager:
    api_keys_path = tmp_path / "api_keys.yaml"
    _write_keys(api_keys_path, *entries)
    params: dict[str, object] = {
        "api_keys_path": api_keys_path,
        "db_path": tmp_path / "usage.duckdb",
        "time_source": _FrozenClock(),
    }
    params.update(overrides)
    manager = AuthManager(**params)  # type: ignore[arg-type]
    manager.load()
    return manager


def test_a_key_with_an_id_is_rate_limited_in_its_kid_bucket(tmp_path: Path) -> None:
    manager = _manager(tmp_path, _entry(ALPHA_ID, ALPHA_PLAIN, "Support"))

    assert manager.is_rate_limited(manager.keys_by_value[ALPHA_PLAIN]) is False

    assert set(manager._rate_windows) == {f"kid:{ALPHA_ID}"}


def test_a_full_window_survives_a_reload(tmp_path: Path) -> None:
    manager = _manager(tmp_path, _entry(ALPHA_ID, ALPHA_PLAIN, "Support"))
    assert manager.is_rate_limited(manager.keys_by_value[ALPHA_PLAIN]) is False
    assert manager.is_rate_limited(manager.keys_by_value[ALPHA_PLAIN]) is True

    manager.load()

    # Same frozen instant: still inside the window the first request opened.
    assert manager.is_rate_limited(manager.keys_by_value[ALPHA_PLAIN]) is True


@pytest.mark.asyncio
async def test_the_secondary_window_survives_a_reload(tmp_path: Path) -> None:
    manager = _manager(
        tmp_path,
        _entry(ALPHA_ID, ALPHA_PLAIN, "Support"),
        rate_limiter=_FullRemainingLimiter(),
    )
    allowed, remaining, _ = await manager.check_rate_limit(manager.keys_by_value[ALPHA_PLAIN])
    assert (allowed, remaining) == (True, 0)

    manager.load()

    allowed, remaining, _ = await manager.check_rate_limit(manager.keys_by_value[ALPHA_PLAIN])
    assert (allowed, remaining) == (False, 0)


def test_a_removed_keys_window_is_dropped(tmp_path: Path) -> None:
    alpha = _entry(ALPHA_ID, ALPHA_PLAIN, "Support")
    beta = _entry(BETA_ID, BETA_PLAIN, "Billing")
    manager = _manager(tmp_path, alpha, beta)
    assert manager.is_rate_limited(manager.keys_by_value[ALPHA_PLAIN]) is False
    assert manager.is_rate_limited(manager.keys_by_value[BETA_PLAIN]) is False

    _write_keys(tmp_path / "api_keys.yaml", alpha)
    manager.load()

    assert f"kid:{ALPHA_ID}" in manager._rate_windows
    assert f"kid:{BETA_ID}" not in manager._rate_windows


def test_no_plaintext_key_becomes_a_window_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path, _entry(ALPHA_ID, ALPHA_PLAIN, "Support"))
    assert manager.is_rate_limited(manager.keys_by_value[ALPHA_PLAIN]) is False

    # load() rebuilds the windows and then sweeps them; the sweep is the one
    # point inside the reload where the rebuilt dict is observable before it
    # is trimmed, so snapshot the names there as well as after the reload.
    names_seen: list[set[str]] = []
    sweep = manager._sweep_expired_windows

    def recording_sweep() -> None:
        names_seen.append(set(manager._rate_windows))
        sweep()

    monkeypatch.setattr(manager, "_sweep_expired_windows", recording_sweep)
    manager.load()
    names_seen.append(set(manager._rate_windows))

    assert len(names_seen) == 2
    for names in names_seen:
        assert not any(ALPHA_PLAIN in name for name in names), names
