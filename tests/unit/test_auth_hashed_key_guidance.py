"""M-C4 guidance enforcement: warn when an AuthManager loads more hashed keys
than the documented soft limit.

Each hashed key adds one bcrypt verification to the cold-cache worst-case
``authenticate()`` path. ``docs/perf/auth-bench-2026-05-26.md`` measured the p95
at ``bcrypt_rounds=12`` crossing the 1100 ms POST load gate around N=20, and
``docs/runbooks/auth-401-spike.md`` records a "<= 10 hashed keys per
AuthManager" guidance. Until now that guidance lived only in docs; these tests
pin a runtime warning so the latency cliff is observable before it bites.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from src.constants import HASHED_KEY_SOFT_LIMIT
from src.serving.api.auth import AuthManager

_WARNING_EVENT = "hashed_key_count_exceeds_guidance"


def _write_hashed_keys(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["keys:"]
    for index in range(count):
        lines.extend(
            [
                f"  - key_id: hashed-{index}",
                f"    key_hash: hash-{index}",
                f"    name: Hashed Agent {index}",
                "    tenant: acme",
                "    rate_limit_rpm: 120",
                "    created_at: '2026-04-10'",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_manager(tmp_path: Path, count: int) -> AuthManager:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_hashed_keys(api_keys_path, count)
    return AuthManager(api_keys_path=api_keys_path, db_path=tmp_path / "usage.duckdb")


def _warnings(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("event") == _WARNING_EVENT]


def test_load_warns_when_hashed_keys_exceed_soft_limit(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path, HASHED_KEY_SOFT_LIMIT + 1)
    with structlog.testing.capture_logs() as events:
        manager.load()

    warnings = _warnings(events)
    assert warnings, (
        f"expected a {_WARNING_EVENT!r} warning when loading "
        f"{HASHED_KEY_SOFT_LIMIT + 1} hashed keys"
    )
    warning = warnings[0]
    assert warning["hashed_keys"] == HASHED_KEY_SOFT_LIMIT + 1
    assert warning["soft_limit"] == HASHED_KEY_SOFT_LIMIT
    assert warning["log_level"] == "warning"


def test_load_does_not_warn_at_soft_limit(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path, HASHED_KEY_SOFT_LIMIT)
    with structlog.testing.capture_logs() as events:
        manager.load()

    assert not _warnings(events), (
        "must not warn when hashed-key count is at or below the soft limit"
    )


def test_load_does_not_warn_without_hashed_keys(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text("keys: []\n", encoding="utf-8")
    manager = AuthManager(api_keys_path=api_keys_path, db_path=tmp_path / "usage.duckdb")
    with structlog.testing.capture_logs() as events:
        manager.load()

    assert not _warnings(events)
