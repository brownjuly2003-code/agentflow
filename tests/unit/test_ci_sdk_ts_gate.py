"""Shape test for the TypeScript SDK PR gate (audit P1-5).

Before this, `sdk-ts` typecheck/tests/build only ran in publish-npm.yml (tag
pushes) and mutation.yml (scheduled); every PR only got `npm audit`
(security.yml). ci.yml now carries an `sdk-ts` job that runs on the same
push/pull_request triggers as the rest of CI and mirrors the steps
publish-npm.yml already trusts, minus the actual publish.

Branch-protection required-context wiring is a repo-settings change gated
on the repo owner — this test only pins the job's own shape, not whether
GitHub is configured to require it.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _ci_workflow() -> dict:
    path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _sdk_ts_job() -> dict:
    job = _ci_workflow()["jobs"].get("sdk-ts")
    assert job is not None, "ci.yml must define an sdk-ts job"
    return job


def test_sdk_ts_job_runs_on_the_same_triggers_as_the_rest_of_ci() -> None:
    workflow = _ci_workflow()
    # PyYAML parses the bare key `on:` as the boolean True (YAML 1.1).
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["pull_request"]["branches"] == ["main"]


def test_sdk_ts_job_has_a_bounded_timeout() -> None:
    job = _sdk_ts_job()
    assert job["runs-on"] == "ubuntu-latest"
    assert 0 < job["timeout-minutes"] <= 30


def test_sdk_ts_job_runs_the_full_build_gate() -> None:
    steps = _sdk_ts_job()["steps"]
    run_steps = " ".join(str(step.get("run", "")) for step in steps)
    for required in (
        "npm ci",
        "npm run typecheck",
        "npm test",
        "npm run build",
        "npm pack --dry-run",
    ):
        assert required in run_steps, f"sdk-ts job must run {required!r}"


def test_sdk_ts_job_does_not_publish() -> None:
    steps = _sdk_ts_job()["steps"]
    run_steps = " ".join(str(step.get("run", "")) for step in steps)
    assert "npm publish" not in run_steps
