"""Runtime-artifact ownership for the repository-wide coverage XML."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
CLAIMS_PATH = ROOT / "scripts" / "validate_project_claims.py"
ARTIFACT_DIR = ".artifacts/coverage"
ARTIFACT_PATH = ".artifacts/coverage/coverage.xml"
CONTROL_PLANE_PATH = ".artifacts/coverage/coverage-control-plane.xml"
XML_REPORT = f"--cov-report=xml:{ARTIFACT_PATH}"
DIFF_COVER = f"diff-cover {ARTIFACT_PATH} --compare-branch=origin/main --fail-under=80"
OLD_XML_REPORT = "--cov-report=xml --cov-report=term-missing"
OLD_DIFF_COVER = "diff-cover coverage.xml --compare-branch=origin/main --fail-under=80"
OLD_CLAIMS_FRAGMENT = (
    "diff-cover coverage.xml --compare-branch=origin/main --fail-under={patch_floor}"
)


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_repository_coverage_xml_has_ignored_runtime_owner() -> None:
    steps = _load_workflow()["jobs"]["test-unit"]["steps"]
    produce = next(
        step for step in steps if step.get("name") == "Run unit and property tests with coverage"
    )
    consume = next(step for step in steps if step.get("name") == "Enforce changed-code coverage")
    run = produce["run"]
    mkdir_at = run.find(f"mkdir -p {ARTIFACT_DIR}")
    report_at = run.find(XML_REPORT)
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert mkdir_at != -1, f"unit coverage must create {ARTIFACT_DIR} before xml report"
    assert report_at != -1
    assert mkdir_at < report_at
    assert XML_REPORT in run
    assert OLD_XML_REPORT not in run
    assert "tests/unit/" in run
    assert "tests/property/" in run
    assert "--cov=src/agentflow_runtime" in run
    assert "--cov=sdk" in run
    assert "--cov-branch" in run
    assert "--cov-fail-under=60" in run
    assert consume["run"] == DIFF_COVER
    assert OLD_DIFF_COVER not in workflow_text
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_repository_coverage_xml_keeps_local_floors_and_omits_codecov() -> None:
    workflow = _load_workflow()
    job = workflow["jobs"]["test-unit"]
    all_step_actions = [
        str(step.get("uses", ""))
        for named_job in workflow["jobs"].values()
        for step in named_job.get("steps", [])
    ]

    assert job["timeout-minutes"] == 25
    assert job.get("permissions") == {"contents": "read"}
    assert "id-token" not in job.get("permissions", {})
    assert not any("codecov" in action.lower() for action in all_step_actions)


def test_control_plane_coverage_xml_contract_is_preserved() -> None:
    steps = _load_workflow()["jobs"]["test-integration"]["steps"]
    gate = next(
        step
        for step in steps
        if step.get("name") == "Control-plane critical-set coverage gate (audit F-12)"
    )
    publish = next(step for step in steps if step.get("name") == "Publish control-plane coverage")

    assert f"coverage xml -o {CONTROL_PLANE_PATH}" in gate["run"]
    assert "coverage xml -o coverage-control-plane.xml" not in gate["run"]
    assert publish["with"]["name"] == "coverage-control-plane"
    assert publish["with"]["path"] == CONTROL_PLANE_PATH
    assert publish["if"] == "always()"
    assert publish["with"]["if-no-files-found"] == "warn"


def test_claims_checker_requires_canonical_repository_coverage_xml() -> None:
    source = CLAIMS_PATH.read_text(encoding="utf-8")

    assert f"diff-cover {ARTIFACT_PATH}" in source
    assert "--compare-branch=origin/main --fail-under={patch_floor}" in source
    assert OLD_CLAIMS_FRAGMENT not in source
