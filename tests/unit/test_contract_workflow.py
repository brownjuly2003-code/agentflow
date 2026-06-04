"""Shape tests for .github/workflows/contract.yml.

The `contract` job is a required branch-protection check, so its workflow must
COMPLETE on every pull request. A `paths:` filter on the pull_request trigger
leaves PRs that touch none of the listed paths stuck forever on
"Expected - waiting for status" (the historical contract Lessons 1/4 trap,
closed for build-smoke in PR #37). Path-gating must live INSIDE the job via a
`changes` step instead, so irrelevant PRs complete as an instant skip-success.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_workflow() -> dict:
    path = PROJECT_ROOT / ".github" / "workflows" / "contract.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on_section(workflow: dict) -> dict:
    # An unquoted `on:` key parses as the YAML boolean True; accept both.
    return workflow.get("on", workflow.get(True))


def test_contract_workflow_triggers_on_every_pull_request():
    on = _on_section(_load_workflow())

    assert "pull_request" in on
    pr_trigger = on["pull_request"]
    assert not (isinstance(pr_trigger, dict) and "paths" in pr_trigger), (
        "pull_request must not be paths-filtered; `contract` is a required "
        "branch-protection check and has to complete on every PR - gate the "
        "suite inside the job instead (see build-smoke / PR #37)"
    )


def test_contract_workflow_keeps_push_paths_filter():
    # Pushes to main are not gated by the required-check expectation, so the
    # cheap trigger-level paths filter stays there (docs-only pushes skip).
    on = _on_section(_load_workflow())

    push_trigger = on["push"]
    assert isinstance(push_trigger, dict)
    assert "paths" in push_trigger
    assert "src/**" in push_trigger["paths"]


def test_contract_workflow_gates_suite_inside_job():
    workflow = _load_workflow()
    job = workflow["jobs"]["contract"]

    assert job.get("name") == "contract", (
        "required-check branch protection depends on a stable PR job context"
    )

    steps = job["steps"]

    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout.get("with", {}).get("fetch-depth") == 0, (
        "the changes step diffs against the PR base, which needs full history"
    )

    changes_step = next(step for step in steps if step.get("id") == "changes")
    run_text = changes_step["run"]
    for tracked in ("src/", "tests/contract", "pyproject", "sdk", "workflows"):
        assert tracked in run_text, f"the change-detection step must inspect {tracked!r} paths"
    assert "GITHUB_OUTPUT" in run_text, (
        "change detection must publish a step output the suite steps key off"
    )
    assert "pull_request" in run_text, (
        "non-PR events (push / workflow_dispatch) must force relevant=true so "
        "the full suite still runs there"
    )

    skip_note = next(
        step for step in steps if step.get("if") == "steps.changes.outputs.relevant == 'false'"
    )
    assert "skip" in skip_note["run"].lower()

    gated_text = yaml.safe_dump(
        [step for step in steps if step.get("if") == "steps.changes.outputs.relevant == 'true'"]
    )
    assert "pip install" in gated_text, "dependency install is wasted work on irrelevant PRs"
    assert "generate_contracts.py --check" in gated_text
    assert "export_openapi.py --check" in gated_text
    assert "pytest tests/contract" in gated_text, "the contract suite itself must be gated"
