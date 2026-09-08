"""Contract: the deferred `use_lockfile` migration has a plan (audit FB-12).

`tests/unit/test_terraform_lock_retention.py` holds the *decision* to keep
`dynamodb_table`: the deprecation warning, the replacement, and the trigger for
revisiting. What it could not hold is that the trigger is actionable. The
rationale said "revisit on the next Terraform major bump" and left whoever hits
that day to design a live-backend lock migration from scratch.

These tests hold the plan itself, and hold it to the state of the backend: the
day `main.tf` gains `use_lockfile`, the pages that call DynamoDB retention
deliberate must change in the same commit.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND = PROJECT_ROOT / "infrastructure" / "terraform" / "main.tf"
RUNBOOK = PROJECT_ROOT / "docs" / "operations" / "aws-oidc-setup.md"
MODULE_README = (
    PROJECT_ROOT / "infrastructure" / "terraform" / "modules" / "github-oidc" / "README.md"
)

PLAN_HEADING = "### Migration to S3 native locking (planned, not executed)"

# One anchor per step that a reader must be able to execute. Each names a thing
# that exists -- a command, a backend argument, an IAM statement, a resource --
# rather than an intention.
REQUIRED_PLAN_ANCHORS = (
    "terraform init -reconfigure",
    "use_lockfile = true",
    "env/<environment>/terraform.tfstate.tflock",
    "TerraformStateLockTableDescribe",
    "state_lock_ids",
    "agentflow-terraform-locks",
    "aws s3 rm",
    "1.10 or",
)


def _backend_block() -> str:
    text = BACKEND.read_text(encoding="utf-8")
    start = text.index('backend "s3"')
    return text[start : text.index("}", text.index("{", start))]


def test_backend_has_not_migrated_yet() -> None:
    # The premise the plan is written against. When this fails, the migration
    # happened and every assertion below changes meaning.
    assert "use_lockfile" not in _backend_block()
    assert "dynamodb_table" in _backend_block()


def test_the_runbook_carries_an_executable_migration_plan() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert PLAN_HEADING in runbook, (
        "the deferral trigger needs a plan next to it, or the person who hits the "
        "trigger has nothing to run"
    )
    plan = runbook[runbook.index(PLAN_HEADING) :]
    for anchor in REQUIRED_PLAN_ANCHORS:
        assert anchor in plan, f"the migration plan must name {anchor!r}"


def test_the_plan_names_the_iam_grant_that_already_covers_the_lock_object() -> None:
    plan = RUNBOOK.read_text(encoding="utf-8")
    plan = plan[plan.index(PLAN_HEADING) :]

    # The single fact that decides whether step 1 is a one-line change or an IAM
    # change: the S3 object grant is prefix-scoped, and the .tflock object lives
    # under that prefix.
    assert "state_prefix_arns" in plan
    assert "env/<environment>/*" in plan
    assert "No IAM change is needed to begin" in plan


def test_the_module_readme_points_at_the_plan_instead_of_copying_it() -> None:
    readme = MODULE_README.read_text(encoding="utf-8")

    assert "docs/operations/aws-oidc-setup.md" in readme
    assert PLAN_HEADING not in readme, (
        "two copies of a migration plan drift; the module README must link the runbook"
    )


def test_deliberate_retention_language_is_tied_to_the_backend_state() -> None:
    deliberate = "on purpose"
    for page in (RUNBOOK, MODULE_README):
        text = page.read_text(encoding="utf-8")
        if "use_lockfile" in _backend_block():
            assert deliberate not in text, (
                f"{page.name} still calls DynamoDB retention deliberate after the backend "
                "gained use_lockfile"
            )
        else:
            assert deliberate in text, (
                f"{page.name} must keep saying the retention is deliberate while the "
                "backend still uses DynamoDB locking"
            )
