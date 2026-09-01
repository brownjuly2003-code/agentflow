"""Runtime-artifact ownership for Flink smoke failure logs."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "flink-smoke.yml"
ARTIFACT_DIR = ".artifacts/flink-smoke"
ARTIFACT_PATH = ".artifacts/flink-smoke/flink-smoke-logs.txt"
ROOT_LOG = "flink-smoke-logs.txt"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _job() -> dict:
    return _load()["jobs"]["flink-smoke"]


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


def test_flink_smoke_failure_log_has_ignored_canonical_owner() -> None:
    collect = _step("Collect Flink logs on failure")
    upload = _step("Upload Flink logs")
    run = collect["run"]
    mkdir_at = run.find(f"mkdir -p {ARTIFACT_DIR}")
    redirect_at = run.find(f"> {ARTIFACT_PATH}")
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert mkdir_at != -1, f"collection must create {ARTIFACT_DIR} before Compose logs"
    assert redirect_at != -1
    assert mkdir_at < redirect_at
    assert f"docker compose $COMPOSE_FILES logs --tail=800 > {ARTIFACT_PATH}" in run
    assert upload["with"]["path"] == ARTIFACT_PATH
    assert not _bare_root_log_lines(run)
    assert not _bare_root_log_lines(workflow_text)
    assert upload["with"]["path"] != ROOT_LOG
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_flink_smoke_log_collection_and_upload_remain_failure_only() -> None:
    collect = _step("Collect Flink logs on failure")
    upload = _step("Upload Flink logs")

    assert collect["if"] == "failure()"
    assert upload["if"] == "failure()"


def test_flink_smoke_log_keeps_name_warn_tail_best_effort_and_teardown() -> None:
    collect = _step("Collect Flink logs on failure")
    upload = _step("Upload Flink logs")
    teardown = _step("Tear down stack")

    assert upload["with"]["name"] == "flink-smoke-logs"
    assert upload["with"]["if-no-files-found"] == "warn"
    assert "--tail=800" in collect["run"]
    assert "|| true" in collect["run"]
    assert teardown["if"] == "always()"
    assert "down -v" in teardown["run"]
