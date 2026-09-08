"""Fail-closed branches of the key-store writability probe (auth.manager).

The probe decides whether key-lifecycle mutations can persist: a read-only
Secret mount must answer 409 instead of raising a filesystem error (audit
F-02 B). ``tests/unit/test_key_store_readonly.py`` drives the happy paths
through a real ``chmod``-ed file; the branches here are the ones a filesystem
will not produce on demand -- a non-permission ``OSError`` that has to
propagate rather than be read as "read-only", the errno/winerror shapes only
one platform raises, and a store path whose file does not exist yet.

Pure module-level calls: no TestClient, no event loop, so the CI auth-manager
coverage gate can run this file without the teardown crashes that keep
middleware cases out of the per-module gates.
"""

from __future__ import annotations

import errno
from pathlib import Path
from typing import IO, Any

import pytest
import structlog

from agentflow_runtime.serving.api.auth import AuthManager
from agentflow_runtime.serving.api.auth.manager import (
    is_permission_denied,
    probe_key_store_writable,
)

SEED_WITHOUT_KEY_IDS = (
    "keys:\n"
    '  - key: "probe-acme-key"\n'
    '    name: "Probe Agent"\n'
    '    tenant: "acme"\n'
    "    rate_limit_rpm: 100\n"
    "    allowed_entity_types: null\n"
    '    created_at: "2026-04-10"\n'
)


class _WinErrorOSError(OSError):
    """An OSError carrying a Windows error code on any platform.

    ``winerror`` is a read-only member of ``OSError`` on Windows and absent on
    POSIX, so neither host can populate it on a plain instance. The subclass
    attribute shadows both, which is what lets one test assert the same branch
    on both platforms.
    """

    winerror = 5


@pytest.fixture(autouse=True)
def _uncached_auth_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentflow_runtime.serving.api import auth as auth_package

    monkeypatch.setattr(auth_package, "logger", structlog.get_logger())


def test_a_non_oserror_is_never_read_as_permission_denied() -> None:
    assert is_permission_denied(ValueError("not a filesystem failure")) is False


def test_read_only_filesystem_errno_is_permission_denied() -> None:
    exc = OSError(errno.EROFS, "Read-only file system")

    # EROFS is the one permission errno CPython does not map onto
    # PermissionError, so it reaches the errno check instead of the isinstance
    # short-circuit above it.
    assert not isinstance(exc, PermissionError)
    assert is_permission_denied(exc) is True


def test_windows_access_denied_winerror_is_permission_denied() -> None:
    exc = _WinErrorOSError(errno.EIO, "Access is denied")

    assert not isinstance(exc, PermissionError)
    assert exc.errno not in {errno.EACCES, errno.EPERM}
    assert is_permission_denied(exc) is True


def test_an_unrelated_oserror_is_not_permission_denied() -> None:
    assert is_permission_denied(OSError(errno.EIO, "I/O error")) is False


def test_a_missing_store_file_probes_its_parent_directory(tmp_path: Path) -> None:
    store = tmp_path / "api_keys.yaml"

    assert probe_key_store_writable(store) is True
    # The probe file is temporary: a writable verdict must not leave a stray
    # dotfile next to the operator's key store.
    assert list(tmp_path.iterdir()) == []


def test_a_missing_store_path_probes_the_nearest_existing_ancestor(tmp_path: Path) -> None:
    store = tmp_path / "not-created-yet" / "deeper" / "api_keys.yaml"

    assert probe_key_store_writable(store) is True
    assert list(tmp_path.iterdir()) == []


def test_a_store_path_with_no_existing_ancestor_is_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A mount that vanished under the process: nothing on the path exists, so
    # there is nowhere to write and no exception to classify.
    monkeypatch.setattr(Path, "exists", lambda self: False)

    assert probe_key_store_writable(tmp_path / "api_keys.yaml") is False


def test_a_parent_that_refuses_the_probe_file_is_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = Path.open

    def _deny_create(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> IO[Any]:
        if "x" in mode:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _deny_create)

    assert probe_key_store_writable(tmp_path / "api_keys.yaml") is False


def test_an_unwritable_existing_store_file_is_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "api_keys.yaml"
    store.write_text("keys: []\n", encoding="utf-8")

    def _deny_append(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> IO[Any]:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(Path, "open", _deny_append)

    assert probe_key_store_writable(store) is False


def test_a_non_permission_failure_on_an_existing_store_file_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "api_keys.yaml"
    store.write_text("keys: []\n", encoding="utf-8")

    def _io_error(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> IO[Any]:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(Path, "open", _io_error)

    # A failing disk is not a read-only mount. Reading it as one would answer
    # 409 "the key store is read-only" to an operator whose store is broken.
    with pytest.raises(OSError) as excinfo:
        probe_key_store_writable(store)
    assert excinfo.value.errno == errno.EIO


def test_a_permission_denied_stat_reports_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _denied(self: Path) -> bool:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(Path, "exists", _denied)

    assert probe_key_store_writable(tmp_path / "api_keys.yaml") is False


def test_a_non_permission_stat_failure_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _io_error(self: Path) -> bool:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(Path, "exists", _io_error)

    with pytest.raises(OSError) as excinfo:
        probe_key_store_writable(tmp_path / "api_keys.yaml")
    assert excinfo.value.errno == errno.EIO


def test_key_store_writable_probes_on_first_read(tmp_path: Path) -> None:
    store = tmp_path / "api_keys.yaml"
    store.write_text(SEED_WITHOUT_KEY_IDS, encoding="utf-8", newline="\n")
    manager = AuthManager(
        api_keys_path=store,
        db_path=tmp_path / "usage.duckdb",
        admin_key="admin-secret",
    )

    # load() has not run, so nothing has probed yet: this property is what
    # every admin mutation asks before it decides 409 vs. write.
    assert manager._key_store_writable is None
    assert manager.key_store_writable is True
    assert manager._key_store_writable is True


def test_a_write_denied_during_load_marks_the_store_read_only(tmp_path: Path) -> None:
    store = tmp_path / "api_keys.yaml"
    store.write_text(SEED_WITHOUT_KEY_IDS, encoding="utf-8", newline="\n")
    manager = AuthManager(
        api_keys_path=store,
        db_path=tmp_path / "usage.duckdb",
        admin_key="admin-secret",
    )
    manager.security_policy.bcrypt_rounds = 4

    def _denied(_config: object) -> None:
        raise PermissionError(errno.EACCES, "Permission denied")

    # The seed carries no key_id, so ensure_key_ids() mutates the config and
    # load() tries to persist it. A store that turns read-only between the
    # probe and the write must downgrade in place, not crash at startup.
    manager._key_rotator.write_config = _denied  # type: ignore[method-assign]

    manager.load()

    assert manager.key_store_writable is False
    assert manager.configured_key_count == 1


def test_a_non_permission_failure_creating_the_probe_file_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _io_error(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> IO[Any]:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(Path, "open", _io_error)

    # Same rule as the existing-file case: only a permission failure means
    # "read-only mount". Anything else is a broken store and must surface.
    with pytest.raises(OSError) as excinfo:
        probe_key_store_writable(tmp_path / "api_keys.yaml")
    assert excinfo.value.errno == errno.EIO


def test_a_probe_file_that_cannot_be_removed_still_reports_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _unlink_fails(self: Path, missing_ok: bool = False) -> None:
        raise OSError(errno.EBUSY, "Device or resource busy")

    monkeypatch.setattr(Path, "unlink", _unlink_fails)

    # The probe answered its question before the cleanup ran. A failed unlink
    # leaves a stray dotfile, which is not a reason to declare the operator's
    # writable key store read-only.
    assert probe_key_store_writable(tmp_path / "api_keys.yaml") is True
