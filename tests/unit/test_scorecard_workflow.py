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

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
    assert analysis["uses"] == "ossf/scorecard-action@v2.4.3"
    assert analysis["with"]["results_file"] == "results.sarif"
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
    assert upload["with"]["sarif_file"] == "results.sarif"


def test_scorecard_checkout_does_not_persist_credentials():
    job = _job(_load_workflow())

    checkout = next(
        step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] is False
