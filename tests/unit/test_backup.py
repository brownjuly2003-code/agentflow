"""scripts/backup.py must never let secret-bearing config into an archive.

`config/api_keys.yaml` (bcrypt key hashes), `config/webhooks.yaml` (signing
secrets) and `config/tenants.yaml` (routing/quota data) are excluded from the
Python sdist (`pyproject.toml` `[tool.hatch.build.targets.sdist] exclude`)
and from release artifacts (`scripts/check_release_artifacts.py`
`FORBIDDEN_MEMBER_PATTERNS`). A nightly backup archive that sweeps all of
`config/` is a third, independent way for the same credential material to
leave the host (audit P1-2) unless it honors the same policy.
"""

from __future__ import annotations

import tarfile

import duckdb
import pytest

from scripts.backup import backup
from scripts.check_release_artifacts import find_forbidden_members
from scripts.restore import restore
from scripts.verify_backup import verify_backup
from src.serving.backends.duckdb_backend import DuckDBBackend

SECRET_CONFIG_FILES = ("api_keys.yaml", "webhooks.yaml", "tenants.yaml")
NON_SECRET_CONFIG_FILES = ("alerts.yaml", "serving.yaml")


def _make_project(root):
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    for name in (*SECRET_CONFIG_FILES, *NON_SECRET_CONFIG_FILES):
        (config_dir / name).write_text(f"# {name} fixture\nkey: value\n", encoding="utf-8")
    # A real pipeline store, laid down by the product's own DDL: the restore
    # smoke test asserts that a restored store still carries its tenant boundary
    # (the `tenant_id` column in each serving table's key, ADR-004), and an empty
    # DuckDB file has no boundary to carry. It refuses that rather than passing
    # quietly — which is the whole point of the check.
    backend = DuckDBBackend(db_path=str(root / "agentflow_demo.duckdb"))
    backend.ensure_schema()
    backend.connection.close()
    return root


def test_backup_archive_excludes_secret_bearing_config_files(tmp_path):
    project_root = _make_project(tmp_path / "project")

    manifest, archive_path = backup(output_dir=str(tmp_path / "out"), project_root=project_root)

    with tarfile.open(archive_path, "r:gz") as archive:
        members = {name.replace("\\", "/") for name in archive.getnames()}

    for name in SECRET_CONFIG_FILES:
        assert f"config/{name}" not in members, f"{name} must never enter the backup archive"
        assert f"config/{name}" not in manifest.config_files
    for name in NON_SECRET_CONFIG_FILES:
        assert f"config/{name}" in members, f"{name} should still be backed up"
        assert f"config/{name}" in manifest.config_files


def test_backup_excludes_any_config_path_matching_the_shared_secret_patterns(tmp_path):
    # Defense in depth, not just the three known filenames: backup.py reuses
    # check_release_artifacts.FORBIDDEN_MEMBER_PATTERNS, which also matches
    # anything with "secret" in the name or under a `secrets/` directory.
    project_root = _make_project(tmp_path / "project")
    nested = project_root / "config" / "nested"
    nested.mkdir()
    (nested / "my_secret_thing.yaml").write_text("x: 1\n", encoding="utf-8")

    manifest, _ = backup(output_dir=str(tmp_path / "out"), project_root=project_root)

    assert not any("secret" in path for path in manifest.config_files)


def test_backup_archive_has_no_forbidden_release_artifact_members(tmp_path):
    project_root = _make_project(tmp_path / "project")

    _, archive_path = backup(output_dir=str(tmp_path / "out"), project_root=project_root)

    # The same checker that guards Python release artifacts, run directly
    # against a backup archive: a regression test that fails "if it ever
    # comes back," per the audit's acceptance criterion, without a second
    # hand-maintained pattern list to drift out of sync.
    assert find_forbidden_members(archive_path) == []


def test_backup_verify_and_restore_round_trip_without_secret_config(tmp_path):
    project_root = _make_project(tmp_path / "project")
    restore_root = tmp_path / "restored"

    _, archive_path = backup(output_dir=str(tmp_path / "out"), project_root=project_root)

    verify_result = verify_backup(archive_path)
    assert verify_result["file_count"] > 0

    restore_result = restore(archive_path, target_root=restore_root)
    assert restore_result["checked_databases"] >= 1

    for name in SECRET_CONFIG_FILES:
        assert not (restore_root / "config" / name).exists()
    for name in NON_SECRET_CONFIG_FILES:
        assert (restore_root / "config" / name).exists()


def test_restore_refuses_a_pipeline_store_with_no_tenant_boundary(tmp_path):
    """The restore invariant has to be able to fail.

    Its predecessor looked for a schema per tenant, named by the `duckdb_schema`
    field of `config/tenants.yaml`. When ADR-004 removed that field the regex
    matched nothing, the expected set went empty, and the check passed on
    anything at all — including a store with no serving tables. A check that
    cannot fail is not a check, so this pins the failing case directly.
    """
    project_root = _make_project(tmp_path / "project")
    # An empty DuckDB file where the pipeline store should be: no serving tables,
    # therefore no tenant boundary to restore.
    (project_root / "agentflow_demo.duckdb").unlink()
    duckdb.connect(str(project_root / "agentflow_demo.duckdb")).close()

    _, archive_path = backup(output_dir=str(tmp_path / "out"), project_root=project_root)

    with pytest.raises(ValueError, match="none of the tenant-scoped serving tables"):
        restore(archive_path, target_root=tmp_path / "restored")
