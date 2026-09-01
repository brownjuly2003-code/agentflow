"""Runtime-artifact ownership for E2E failure logs."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "e2e.yml"
ARTIFACT_DIR = ".artifacts/e2e"
ARTIFACT_PATH = ".artifacts/e2e/e2e-logs.txt"
ROOT_LOG = "e2e-logs.txt"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _job() -> dict:
    return _load()["jobs"]["e2e"]


def _step(name: str) -> dict:
    step = next((s for s in _job()["steps"] if s.get("name") == name), None)
    assert step is not None, f"step not found: {name}"
    return step


def _bare_root_log_lines(text: str) -> list[str]:
    mentions = []
    for line in text.splitlines():
        if ARTIFACT_PATH in line:
            continue
        if ROOT_LOG in line:
            mentions.append(line.strip())
    return mentions


def test_e2e_failure_log_has_ignored_canonical_owner() -> None:
    collect = _step("Collect logs on failure")
    upload = _step("Upload logs")
    run = collect["run"]
    mkdir_at = run.find(f"mkdir -p {ARTIFACT_DIR}")
    redirect_at = run.find(f"> {ARTIFACT_PATH}")
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert mkdir_at != -1, f"collection must create {ARTIFACT_DIR} before Compose logs"
    assert redirect_at != -1
    assert mkdir_at < redirect_at
    assert f"docker compose -f docker-compose.e2e.yml logs --tail=500 > {ARTIFACT_PATH}" in run
    assert upload["with"]["path"] == ARTIFACT_PATH
    assert not _bare_root_log_lines(run)
    assert not _bare_root_log_lines(workflow_text)
    assert upload["with"]["path"] != ROOT_LOG
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_e2e_log_collection_and_upload_remain_failure_only() -> None:
    collect = _step("Collect logs on failure")
    upload = _step("Upload logs")

    assert collect["if"] == "failure()"
    assert upload["if"] == "failure()"


def test_e2e_log_keeps_name_tail_fail_behavior_and_teardown() -> None:
    collect = _step("Collect logs on failure")
    upload = _step("Upload logs")
    teardown = _step("Stop API")

    assert upload["with"]["name"] == "e2e-logs"
    assert "if-no-files-found" not in upload.get("with", {})
    assert "--tail=500" in collect["run"]
    assert "|| true" not in collect["run"]
    assert teardown["if"] == "always()"
    assert "down -v" in teardown["run"]
