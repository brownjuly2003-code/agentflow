"""Requirement tests for docs/specs/api-key-identity.md, one per scenario.

A key configured without a `key_id` -- every key from `AGENTFLOW_API_KEYS`, and
a key-file entry without one -- gets an id derived from its peppered key-lookup
digest, so the same key keeps the same id (and so the same rate-limit bucket
and usage rows) on every load, restart and replica, even when the key file is
mounted read-only and the id can never be written back.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path

import pytest
import yaml

from agentflow_runtime.serving.api.auth import manager as manager_module
from agentflow_runtime.serving.api.auth.manager import AuthManager
from agentflow_runtime.serving.api.security import compute_key_lookup

PEPPER = "api-key-identity-test-pepper"
REPO_ROOT = Path(__file__).resolve().parents[2]
STORED_LOOKUP = "5e1f0c3a9b7d24866d3f2e1c0b9a8f7e6d5c4b3a29180716f5e4d3c2b1a09f8e"
HASHED_ENTRY_YAML = (
    "keys:\n"
    '  - key_hash: "$2b$04$storedhashstoredhashstoredhashstoredhashstoredhashst"\n'
    f'    key_lookup: "{STORED_LOOKUP}"\n'
    '    name: "Support Agent"\n'
    '    tenant: "acme"\n'
    "    rate_limit_rpm: 60\n"
    '    created_at: "2026-04-10"\n'
)


@pytest.fixture(autouse=True)
def _pinned_pepper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_KEY_LOOKUP_PEPPER", PEPPER)
    monkeypatch.delenv("AGENTFLOW_PROFILE", raising=False)
    monkeypatch.delenv("AGENTFLOW_API_KEYS", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)


def _env_manager(tmp_path: Path, db_name: str = "usage.duckdb") -> AuthManager:
    manager = AuthManager(api_keys_path=None, db_path=tmp_path / db_name)
    manager.load()
    return manager


def _file_manager(path: Path, tmp_path: Path, db_name: str = "usage.duckdb") -> AuthManager:
    manager = AuthManager(api_keys_path=path, db_path=tmp_path / db_name)
    manager.load()
    return manager


def _key_file(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config" / "api_keys.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def test_same_environment_key_two_managers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_API_KEYS", "k1:Support Agent")

    first = _env_manager(tmp_path, "first.duckdb")
    second = _env_manager(tmp_path, "second.duckdb")

    key_id = first.keys_by_value["k1"].key_id
    assert key_id is not None
    assert re.fullmatch(r"default-support-agent-[0-9a-f]{8}", key_id)
    assert second.keys_by_value["k1"].key_id == key_id


def test_a_reload_keeps_the_id_and_the_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Environment keys carry the default rpm; one request fills a 1-rpm window.
    monkeypatch.setattr(manager_module, "DEFAULT_RATE_LIMIT_RPM", 1)
    monkeypatch.setenv("AGENTFLOW_API_KEYS", "k1:bot")
    manager = _env_manager(tmp_path)
    key = manager.keys_by_value["k1"]
    bucket = manager._rate_limit_key(key)
    assert manager.is_rate_limited(key) is False
    assert manager.is_rate_limited(key) is True

    manager.load()

    reloaded = manager.keys_by_value["k1"]
    assert reloaded.key_id == key.key_id
    assert manager._rate_limit_key(reloaded) == bucket
    # The practical effect: the full window survived the reload.
    assert manager.is_rate_limited(reloaded) is True


def test_different_keys_under_one_name_get_different_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTFLOW_API_KEYS", "k1:bot,k2:bot")

    manager = _env_manager(tmp_path)

    first = manager.keys_by_value["k1"].key_id
    second = manager.keys_by_value["k2"].key_id
    assert first is not None
    assert second is not None
    assert first != second


def test_an_idless_entry_in_a_read_only_key_file(tmp_path: Path) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root writes a read-only file regardless of its mode")
    path = _key_file(tmp_path, HASHED_ENTRY_YAML)
    on_disk = path.read_bytes()
    os.chmod(path, stat.S_IREAD)
    try:
        first = _file_manager(path, tmp_path, "first.duckdb")
        second = _file_manager(path, tmp_path, "second.duckdb")
        [first_key] = first._loaded_keys
        [second_key] = second._loaded_keys
        assert first_key.key_id is not None
        assert second_key.key_id == first_key.key_id

        first.load()

        [reloaded] = first._loaded_keys
        assert reloaded.key_id == first_key.key_id
        # The id was never written back: it is the derivation, not the file,
        # that keeps it stable.
        assert path.read_bytes() == on_disk
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def test_a_writable_key_file_persists_the_derived_id(tmp_path: Path) -> None:
    path = _key_file(
        tmp_path,
        "keys:\n"
        '  - key: "plain-file-key"\n'
        '    name: "Report Bot"\n'
        '    tenant: "Acme"\n'
        '    created_at: "2026-04-10"\n',
    )

    manager = _file_manager(path, tmp_path)

    [key] = manager._loaded_keys
    expected = f"acme-report-bot-{compute_key_lookup('plain-file-key', PEPPER)[:8]}"
    assert key.key_id == expected
    [stored] = yaml.safe_load(path.read_text(encoding="utf-8"))["keys"]
    assert stored["key_id"] == expected


def test_the_suffix_is_the_lookup_digests_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTFLOW_API_KEYS", "k1:bot")

    manager = _env_manager(tmp_path)

    key_id = manager.keys_by_value["k1"].key_id
    assert key_id == f"default-bot-{compute_key_lookup('k1', PEPPER)[:8]}"


def test_a_stored_key_lookup_is_used_as_it_is(tmp_path: Path) -> None:
    path = _key_file(tmp_path, HASHED_ENTRY_YAML)

    manager = _file_manager(path, tmp_path)

    [key] = manager._loaded_keys
    assert key.key_id == f"acme-support-agent-{STORED_LOOKUP[:8]}"


def test_a_different_pepper_gives_a_different_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTFLOW_API_KEYS", "k1:bot")
    first = _env_manager(tmp_path, "first.duckdb")
    monkeypatch.setenv("AGENTFLOW_KEY_LOOKUP_PEPPER", PEPPER + "-rotated")
    second = _env_manager(tmp_path, "second.duckdb")

    assert first.keys_by_value["k1"].key_id != second.keys_by_value["k1"].key_id


def test_a_stored_key_lookup_keeps_its_id_under_another_pepper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two copies of one file: a writable file gets the id written back, and the
    # second load must derive it again rather than read it.
    first_path = _key_file(tmp_path, HASHED_ENTRY_YAML)
    second_path = tmp_path / "copy" / "api_keys.yaml"
    second_path.parent.mkdir()
    second_path.write_text(HASHED_ENTRY_YAML, encoding="utf-8", newline="\n")

    first = _file_manager(first_path, tmp_path, "first.duckdb")
    monkeypatch.setenv("AGENTFLOW_KEY_LOOKUP_PEPPER", PEPPER + "-rotated")
    second = _file_manager(second_path, tmp_path, "second.duckdb")

    [first_key] = first._loaded_keys
    [second_key] = second._loaded_keys
    assert first_key.key_id == f"acme-support-agent-{STORED_LOOKUP[:8]}"
    assert second_key.key_id == first_key.key_id


def test_a_writable_key_file_keeps_its_written_id_under_another_pepper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pepper changes only an id that was never written back: the first load
    # persists the derived id, and a later load reads it from the file.
    path = _key_file(
        tmp_path,
        "keys:\n"
        '  - key: "plain-file-key"\n'
        '    name: "Report Bot"\n'
        '    tenant: "Acme"\n'
        '    created_at: "2026-04-10"\n',
    )
    first = _file_manager(path, tmp_path, "first.duckdb")
    [written] = yaml.safe_load(path.read_text(encoding="utf-8"))["keys"]
    monkeypatch.setenv("AGENTFLOW_KEY_LOOKUP_PEPPER", PEPPER + "-rotated")
    second = _file_manager(path, tmp_path, "second.duckdb")

    [first_key] = first._loaded_keys
    [second_key] = second._loaded_keys
    expected = f"acme-report-bot-{compute_key_lookup('plain-file-key', PEPPER)[:8]}"
    assert first_key.key_id == expected
    assert written["key_id"] == expected
    assert second_key.key_id == expected


# --------------------------------------------------------------------------- #
# False-reject control: the change derives ids, it rejects nothing that loaded.
# --------------------------------------------------------------------------- #


def test_the_shipped_key_file_still_loads_with_ids_from_its_stored_lookups(
    tmp_path: Path,
) -> None:
    # config/api_keys.yaml is the file docker-compose.prod.yml mounts
    # read-only: two hashed entries with a key_lookup and no key_id.
    path = tmp_path / "config" / "api_keys.yaml"
    path.parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "config" / "api_keys.yaml", path)

    manager = _file_manager(path, tmp_path)

    by_name = {item.name: item for item in manager._loaded_keys}
    assert set(by_name) == {"Support Agent", "Ops Agent"}
    for name, slug in (("Support Agent", "support-agent"), ("Ops Agent", "ops-agent")):
        item = by_name[name]
        assert item.key_lookup is not None
        assert item.key_id == f"default-{slug}-{item.key_lookup[:8]}"
        assert manager._keys_by_lookup[item.key_lookup] is item


def test_a_persisted_id_and_a_hash_only_entry_still_load(tmp_path: Path) -> None:
    path = _key_file(
        tmp_path,
        "keys:\n"
        '  - key_id: "acme-kept-id"\n'
        '    key: "kept-plain-key"\n'
        '    name: "Kept"\n'
        '    tenant: "acme"\n'
        '    created_at: "2026-04-10"\n'
        '  - key_hash: "$2b$04$legacyhashlegacyhashlegacyhashlegacyhashlegacyhash"\n'
        '    name: "Legacy"\n'
        '    tenant: "acme"\n'
        '    created_at: "2026-04-10"\n',
    )

    manager = _file_manager(path, tmp_path)

    kept, legacy = manager._loaded_keys
    assert kept.key_id == "acme-kept-id"
    # Nothing to derive from: the legacy entry keeps generate_key_id's shape.
    assert legacy.key_id is not None
    assert re.fullmatch(r"acme-legacy-[0-9a-f]{8}", legacy.key_id)
