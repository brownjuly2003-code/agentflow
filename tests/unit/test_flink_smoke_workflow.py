"""Shape guards for the Flink smoke workflow.

The job is the only CI lane that exercises PyFlink job *submission* (the
watermark/Duration regression class, T-2, is invisible to the no-Docker unit
suite). These tests pin the contract the no-Docker side can verify: triggers,
least-privilege permissions, the compose overlay, the submission smoke
criterion, and guaranteed teardown. Action SHA-pinning is enforced globally by
test_workflow_action_pinning.py.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "flink-smoke.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML parses the bare key `on:` as the boolean True (YAML 1.1).
    return workflow.get("on", workflow.get(True))


def test_triggers_cover_push_pr_and_manual_dispatch() -> None:
    triggers = _triggers(_load())
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["pull_request"]["branches"] == ["main"]
    assert "workflow_dispatch" in triggers


def test_permissions_are_least_privilege() -> None:
    assert _load()["permissions"] == {"contents": "read"}


def test_job_runs_on_ubuntu_with_a_bounded_timeout() -> None:
    job = _load()["jobs"]["flink-smoke"]
    assert job["runs-on"] == "ubuntu-latest"
    # A heavy stack that must never hang a runner indefinitely.
    assert 0 < job["timeout-minutes"] <= 30


def _submit_step(job: dict) -> dict:
    step = next(
        (s for s in job["steps"] if str(s.get("name", "")).startswith("Submit stream_processor")),
        None,
    )
    assert step is not None, "submission step not found"
    return step


def test_smoke_uses_the_flink_compose_overlay() -> None:
    job = _load()["jobs"]["flink-smoke"]
    # The overlay is what swaps the upstream flink image for the locally built
    # PyFlink job image; without it the regression is not exercised.
    assert job["env"]["COMPOSE_FILES"] == "-f docker-compose.yml -f docker-compose.flink.yml"
    run = _submit_step(job)["run"]
    # The build is bounded + retried separately (silent registry stalls ate the
    # whole 30-min job on #213/#218), and `up` must then run the locally built
    # image rather than pulling upstream.
    assert "timeout 600 docker compose $COMPOSE_FILES build flink-job-runner" in run
    assert "up -d flink-job-runner" in run
    assert "up -d --build" not in run


def test_smoke_criterion_is_job_submission() -> None:
    run = _submit_step(_load()["jobs"]["flink-smoke"])["run"]
    # The exact string flink run -d emits on a successful submit; proven on the
    # live cluster when T-2 was fixed (#59).
    assert "Job has been submitted with JobID" in run
    assert "exit 1" in run, "must fail when the job is never submitted"


def test_stack_is_always_torn_down() -> None:
    steps = _load()["jobs"]["flink-smoke"]["steps"]
    teardown = next((s for s in steps if s.get("name") == "Tear down stack"), None)
    assert teardown is not None
    assert teardown["if"] == "always()"
    assert "down -v" in teardown["run"]
