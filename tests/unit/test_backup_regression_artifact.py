"""Runtime-artifact ownership for backup/restore regression archives."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "backup.yml"
ARTIFACT_DIR = ".artifacts/backup-regression"
RESOLVER_GLOB = ".artifacts/backup-regression/*.tar.gz"
ARCHIVE_OUTPUT = "${{ steps.backup.outputs.archive_path }}"
LEGACY_DIR = "backup-artifacts"

CHECKOUT_PIN = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON_PIN = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
UPLOAD_PIN = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _on_section(workflow: dict) -> dict:
    # An unquoted `on:` key parses as the YAML boolean True; accept both.
    return workflow.get("on", workflow.get(True))


def _job() -> dict:
    return _load()["jobs"]["backup"]


def _step(name: str) -> dict:
    step = next((item for item in _job()["steps"] if item.get("name") == name), None)
    assert step is not None, f"step not found: {name}"
    return step


def _bare_legacy_working_path_lines(text: str) -> list[str]:
    mentions = []
    for line in text.splitlines():
        if ARTIFACT_DIR in line:
            continue
        if LEGACY_DIR in line:
            mentions.append(line.strip())
    return mentions


def test_backup_regression_archive_has_ignored_canonical_owner() -> None:
    produce = _step("Create backup archive (synthetic fixture)")
    resolve = _step("Resolve backup path")
    verify = _step("Verify backup manifest")
    restore = _step("Restore smoke test")
    upload = _step("Upload regression-test archive")
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert produce["run"] == f"python scripts/backup.py --output {ARTIFACT_DIR}"
    assert RESOLVER_GLOB in resolve["run"]
    assert f'archive_path="$(ls -1t {RESOLVER_GLOB} | head -n 1)"' in resolve["run"]
    assert 'echo "archive_path=$archive_path" >> "$GITHUB_OUTPUT"' in resolve["run"]
    assert resolve["id"] == "backup"
    assert resolve.get("shell") == "bash"
    assert ARCHIVE_OUTPUT in verify["run"]
    assert f'--backup "{ARCHIVE_OUTPUT}"' in restore["run"]
    assert upload["with"]["path"] == ARCHIVE_OUTPUT
    assert not _bare_legacy_working_path_lines(produce["run"])
    assert not _bare_legacy_working_path_lines(resolve["run"])
    assert not _bare_legacy_working_path_lines(workflow_text)
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_backup_regression_keeps_triggers_permissions_job_and_action_pins() -> None:
    workflow = _load()
    on = _on_section(workflow)
    job = workflow["jobs"]["backup"]
    steps = job["steps"]
    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    setup_python = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/setup-python@")
    )
    upload = _step("Upload regression-test archive")
    install = _step("Install dependencies")
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow["name"] == "Backup/Restore Regression Test"
    assert on["schedule"] == [{"cron": "0 2 * * *"}]
    assert "workflow_dispatch" in on
    assert workflow["permissions"] == {"contents": "read"}
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == 20
    assert checkout["uses"] == CHECKOUT_PIN
    assert setup_python["uses"] == SETUP_PYTHON_PIN
    assert setup_python["with"]["python-version"] == "3.11"
    assert upload["uses"] == UPLOAD_PIN
    assert f"{CHECKOUT_PIN} # v7.0.1" in workflow_text
    assert f"{SETUP_PYTHON_PIN} # v7.0.0" in workflow_text
    assert f"{UPLOAD_PIN} # v7.0.1" in workflow_text
    assert install["run"] == "bash scripts/ci_sync.sh dev-tools"


def test_backup_regression_keeps_fixture_verify_restore_upload_and_synthetic_scope() -> None:
    fixture = _step("Prepare backup fixture")
    verify = _step("Verify backup manifest")
    restore = _step("Restore smoke test")
    upload = _step("Upload regression-test archive")
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "This does not back up a deployed environment" in workflow_text
    assert "disaster-recovery control (audit P1-2)" in workflow_text
    assert "docs/operations/disaster-recovery.md" in workflow_text
    assert "DuckDBBackend" in fixture["run"]
    assert "agentflow_demo.duckdb" in fixture["run"]
    assert "agentflow_api.duckdb" in fixture["run"]
    assert "orders_v2" in fixture["run"]
    assert "api_usage" in fixture["run"]
    assert verify["run"] == f'python scripts/verify_backup.py "{ARCHIVE_OUTPUT}"'
    assert "--target-root /tmp/agentflow-restore" in restore["run"]
    assert upload["with"]["name"] == "agentflow-backup-restore-regression-fixture"
    assert upload["with"]["retention-days"] == 7
    assert "if-no-files-found" not in upload.get("with", {})
