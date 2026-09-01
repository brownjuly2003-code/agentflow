"""Shape tests for .github/workflows/scorecard.yml.

The OpenSSF Scorecard workflow is the project's $0 supply-chain security
posture channel: an automated, third-party-defined (OpenSSF/Google heuristics)
assessment of this repository that produces a citable score + SARIF. It is a
posture signal, explicitly NOT a third-party penetration-test attestation
(backlog item 22 remains N/A / unclaimed). The workflow must run on the default
branch + a weekly schedule + branch_protection_rule, hold least-privilege
top-level permissions with the two writes the analysis job needs
(security-events for the SARIF upload, id-token for publish_results), and both
publish the public result and upload the SARIF to code scanning.
"""

import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCORECARD_ARTIFACT_DIR = ".artifacts/scorecard"
SCORECARD_SARIF = ".artifacts/scorecard/results.sarif"


def _load_workflow() -> dict:
    path = PROJECT_ROOT / ".github" / "workflows" / "scorecard.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on_section(workflow: dict) -> dict:
    # An unquoted `on:` key parses as the YAML boolean True; accept both.
    return workflow.get("on", workflow.get(True))


def _job(workflow: dict) -> dict:
    return workflow["jobs"]["analysis"]


def test_scorecard_runs_on_default_branch_schedule_and_protection_rule():
    on = _on_section(_load_workflow())

    assert "schedule" in on
    assert "branch_protection_rule" in on
    # Posture of the default branch is what gets published; gate on push to main.
    assert on["push"]["branches"] == ["main"]
    # Not a PR gate — it is an assessment, never a required check.
    assert "pull_request" not in on


def test_scorecard_top_level_permissions_are_least_privilege():
    workflow = _load_workflow()

    assert workflow["permissions"] == "read-all"


def test_scorecard_analysis_job_holds_only_the_two_required_writes():
    job = _job(_load_workflow())

    assert job["permissions"] == {
        "security-events": "write",
        "id-token": "write",
    }


def test_scorecard_runs_the_pinned_ossf_action_and_publishes_results():
    job = _job(_load_workflow())

    analysis = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("ossf/scorecard-action@")
    )
    # Commit-SHA pinned (the human-readable version rides in the inline
    # comment, which YAML parsing drops); the repo-wide pin convention is
    # enforced by test_workflow_action_pinning.py.
    assert re.fullmatch(r"ossf/scorecard-action@[0-9a-f]{40}", analysis["uses"])
    assert analysis["with"]["results_file"] == SCORECARD_SARIF
    assert analysis["with"]["results_format"] == "sarif"
    # The public, citable artifact is the whole point for a portfolio repo.
    assert analysis["with"]["publish_results"] is True


def test_scorecard_uploads_sarif_to_code_scanning():
    job = _job(_load_workflow())

    upload = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("github/codeql-action/upload-sarif@")
    )
    assert upload["with"]["sarif_file"] == SCORECARD_SARIF


def test_scorecard_checkout_does_not_persist_credentials():
    job = _job(_load_workflow())

    checkout = next(
        step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] is False


def test_scorecard_uses_one_canonical_sarif_path_at_all_boundaries():
    job = _job(_load_workflow())
    analysis = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("ossf/scorecard-action@")
    )
    artifact = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    code_scanning = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("github/codeql-action/upload-sarif@")
    )

    assert analysis["with"]["results_file"] == SCORECARD_SARIF
    assert artifact["with"]["path"] == SCORECARD_SARIF
    assert code_scanning["with"]["sarif_file"] == SCORECARD_SARIF
    assert artifact["with"]["name"] == "SARIF file"
    assert artifact["with"]["retention-days"] == 5
    assert artifact["with"]["if-no-files-found"] == "error"


def test_scorecard_prepares_canonical_directory_before_analysis():
    steps = _job(_load_workflow())["steps"]
    prepare = [
        index
        for index, step in enumerate(steps)
        if isinstance(step.get("run"), str) and f"mkdir -p {SCORECARD_ARTIFACT_DIR}" in step["run"]
    ]
    analysis = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("ossf/scorecard-action@")
    )

    assert prepare, f"analysis job must create {SCORECARD_ARTIFACT_DIR} before Scorecard"
    assert prepare[0] < analysis


def test_scorecard_sarif_is_covered_by_gitignore():
    gitignore_lines = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".artifacts/" in gitignore_lines
    assert SCORECARD_SARIF == ".artifacts/scorecard/results.sarif"
    assert SCORECARD_SARIF.startswith(".artifacts/")


def test_docs_contributing_and_plan_name_scorecard_runtime_owner():
    docs_hub = " ".join((PROJECT_ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    posture = (PROJECT_ROOT / "docs" / "operations" / "openssf-security-posture.md").read_text(
        encoding="utf-8"
    )
    plan = (PROJECT_ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8")

    assert "| Scorecard SARIF |" in docs_hub
    assert SCORECARD_SARIF in docs_hub
    assert "date-stamped" in docs_hub
    assert SCORECARD_SARIF in contributing
    assert "date-stamped" in contributing
    assert SCORECARD_SARIF in posture
    assert "replaceable" in posture
    assert "Scorecard SARIF runtime-artifact ownership sub-slice" in plan
    assert "- [ ] **6. Отделить generated reference.**" in plan
    assert "Пункт 6 остаётся открыт" in plan
