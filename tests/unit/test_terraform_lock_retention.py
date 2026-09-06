"""T-36: DynamoDB lock retention is deliberate, and linux_amd64 lock drift is guarded in CI.

`h1:` hashes in `.terraform.lock.hcl` carry no platform label, so a local
count of hashes cannot prove platform coverage. The honest local assertion is
that `.github/workflows/ci.yml` `terraform-validate` runs
`terraform providers lock` with `-platform=linux_amd64` and fails on a
non-empty `git diff --exit-code .terraform.lock.hcl`. Additional `-platform=`
values are accepted by this assertion, but any platform named must also be
present in the tracked lock or the git diff guard will fail. The documented
three-platform command satisfies the claim and is what CI actually runs.

The S3 backend keeps `dynamodb_table` on purpose under Terraform 1.15.4.
This file does not claim a real-backend init/plan/apply, and it does not
claim that the CI guard has been observed on a GitHub runner.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
TERRAFORM_MAIN_PATH = PROJECT_ROOT / "infrastructure" / "terraform" / "main.tf"
OIDC_MODULE_PATH = (
    PROJECT_ROOT / "infrastructure" / "terraform" / "modules" / "github-oidc" / "main.tf"
)
OIDC_README_PATH = (
    PROJECT_ROOT / "infrastructure" / "terraform" / "modules" / "github-oidc" / "README.md"
)
OIDC_RUNBOOK_PATH = PROJECT_ROOT / "docs" / "operations" / "aws-oidc-setup.md"
LOCK_PATH = PROJECT_ROOT / "infrastructure" / "terraform" / ".terraform.lock.hcl"

LOCK_COMMAND = "terraform providers lock"
LOCK_DIFF_COMMAND = "git diff --exit-code .terraform.lock.hcl"
BACKEND_TABLE = 'dynamodb_table = "agentflow-terraform-locks"'
LOCK_PATH_NAME = ".terraform.lock.hcl"

REQUIRED_RETENTION_PHRASES = (
    "Warning: Deprecated Parameter",
    "use_lockfile = true",
    "locking mechanism of a live backend",
    "next Terraform major bump",
    "recreated from scratch",
)


def _load_ci_workflow() -> dict:
    return yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))


def _backend_body(terraform_main: str) -> str:
    match = re.search(r'backend "s3" \{(?P<body>.*?)\n  \}', terraform_main, re.DOTALL)
    assert match is not None, "s3 backend block not found"
    return match.group("body")


def _effective_run_lines(run: str) -> list[str]:
    """Non-blank, non-comment lines of a step `run` block, stripped."""
    lines: list[str] = []
    for raw in str(run).splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def _is_lock_guard_step(step: dict) -> bool:
    """Recognise the provider-lock drift guard by line, not substring.

    After dropping blank and `#` comment lines, the body must contain one
    remaining line that starts with `terraform providers lock` and one whose
    stripped form is exactly `git diff --exit-code .terraform.lock.hcl`, and
    the step must run in `infrastructure/terraform`.
    """
    run = str(step.get("run", ""))
    working = str(step.get("working-directory", "")).replace("\\", "/")
    lines = _effective_run_lines(run)
    in_terraform_dir = working == "infrastructure/terraform" or any(
        line == "cd infrastructure/terraform" or line.startswith("cd infrastructure/terraform ")
        for line in lines
    )
    has_lock = any(line.startswith(LOCK_COMMAND) for line in lines)
    has_diff = any(line == LOCK_DIFF_COMMAND for line in lines)
    return has_lock and has_diff and in_terraform_dir


def _assert_lock_guard_run_not_neutered(run: str) -> None:
    lines = _effective_run_lines(run)
    lock_lines = [line for line in lines if line.startswith(LOCK_COMMAND)]
    diff_lines = [line for line in lines if line == LOCK_DIFF_COMMAND]
    assert lock_lines, "lock guard must contain a terraform providers lock line"
    assert diff_lines, f"lock guard must contain exactly `{LOCK_DIFF_COMMAND}`"
    for line in (*lock_lines, *diff_lines):
        assert "||" not in line, "lock-guard command must not be chained with ||"
        assert "&&" not in line, "lock-guard command must not be chained with &&"
        assert ";" not in line, "lock-guard command must not be chained with ;"
        assert not line.endswith(" true"), "lock-guard command must not end with trailing true"
    joined = "\n".join(lines)
    assert "set +e" not in joined, "lock guard must not disable errexit"
    assert "exit 0" not in joined, "lock guard must not force a successful exit"
    for line in lines:
        if re.search(r"\bgit\s+(checkout|restore|stash)\b", line):
            assert LOCK_PATH_NAME not in line, (
                "lock guard must not git checkout/restore/stash the lock path"
            )


def _assert_linux_amd64_lock_guard(workflow: dict) -> None:
    job = workflow["jobs"]["terraform-validate"]
    assert "if" not in job
    assert job["runs-on"] == "ubuntu-latest"
    timeout = job.get("timeout-minutes")
    assert isinstance(timeout, int)
    assert not isinstance(timeout, bool)
    assert timeout >= 20, (
        "terraform-validate must budget >= 20 minutes for three-platform "
        f"provider-lock fetches; got {timeout!r}"
    )
    setup_versions = {
        (step.get("with") or {}).get("terraform_version")
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("hashicorp/setup-terraform@")
    }
    assert setup_versions == {"1.15.4"}

    matching = [step for step in job.get("steps", []) if _is_lock_guard_step(step)]
    assert matching, (
        "ci.yml terraform-validate must run "
        f"`{LOCK_COMMAND}` with `-platform=linux_amd64` in "
        "infrastructure/terraform/ and fail on "
        f"`{LOCK_DIFF_COMMAND}`"
    )
    for step in matching:
        assert step.get("continue-on-error") in (None, False)
        assert "if" not in step
        run = str(step.get("run", ""))
        _assert_lock_guard_run_not_neutered(run)
        assert re.search(r"-platform=linux_amd64\b", run), (
            "lock guard must cover linux_amd64 (ubuntu-latest); "
            "additional -platform= values are accepted by this assertion, "
            "but any platform named must also be present in the tracked lock "
            "or the git diff guard will fail"
        )


def _assert_lock_retention_docs(readme: str, runbook: str) -> None:
    for source in (readme, runbook):
        for phrase in REQUIRED_RETENTION_PHRASES:
            assert phrase in source, f"missing retention phrase: {phrase}"
        assert "deprecated as of Terraform 1.15.4" in source
        assert "needs AWS access" in source
        assert "lock-migration" in source
    assert LOCK_DIFF_COMMAND in readme, "README must document the ci.yml git diff --exit-code guard"
    assert "terraform-validate" in readme, (
        "README must name the ci.yml terraform-validate provider-lock step"
    )
    assert "ASSUMPTION-T-36-BACKEND" in runbook
    assert "ASSUMPTION-T-36-CI-LOCK" in runbook


def _mutate_lock_guard_run(workflow: dict, run: str) -> dict:
    for step in workflow["jobs"]["terraform-validate"]["steps"]:
        if _is_lock_guard_step(step):
            step["run"] = run
            return step
    raise AssertionError("no lock-guard step to mutate")


def test_control_tracked_backend_and_lock_remain_accepted() -> None:
    """FALSE-REJECT CONTROL: T-12's valid backend, IAM lock statements, and lock file stay accepted."""
    terraform_main = TERRAFORM_MAIN_PATH.read_text(encoding="utf-8")
    backend = _backend_body(terraform_main)
    assert BACKEND_TABLE in backend
    assert "use_lockfile" not in backend

    module_source = OIDC_MODULE_PATH.read_text(encoding="utf-8")
    assert re.search(r'sid\s*=\s*"TerraformStateLockTableDescribe"', module_source)
    assert re.search(r'sid\s*=\s*"TerraformStateLockItems"', module_source)
    assert "dynamodb:LeadingKeys" in module_source

    lock_source = LOCK_PATH.read_text(encoding="utf-8")
    assert 'provider "registry.terraform.io/hashicorp/aws"' in lock_source


def test_backend_retains_dynamodb_table_on_purpose() -> None:
    terraform_main = TERRAFORM_MAIN_PATH.read_text(encoding="utf-8")
    backend = _backend_body(terraform_main)
    assert BACKEND_TABLE in backend, "dynamodb_table must remain; retention is deliberate"
    assert "use_lockfile" not in backend
    # The parameter is present on purpose, not because the file merely parses.
    assert 'required_version = "= 1.15.4"' in terraform_main


def test_ci_terraform_validate_guards_linux_amd64_provider_lock() -> None:
    _assert_linux_amd64_lock_guard(_load_ci_workflow())


def test_linux_amd64_lock_guard_allows_additional_platforms() -> None:
    """Reorder of the documented three is a genuinely valid extra-platform mutant.

    Additional -platform= values are accepted by this assertion, but any
    platform named must also be present in the tracked lock or the git diff
    guard will fail. linux_arm64 is not such a mutant: the tracked lock has
    no hash for it, so CI would go red on every PR.
    """
    workflow = copy.deepcopy(_load_ci_workflow())
    _mutate_lock_guard_run(
        workflow,
        "cd infrastructure/terraform\n"
        "terraform providers lock -platform=darwin_arm64 "
        "-platform=windows_amd64 -platform=linux_amd64\n"
        f"{LOCK_DIFF_COMMAND}\n",
    )
    _assert_linux_amd64_lock_guard(workflow)


def test_linux_amd64_lock_guard_accepts_working_directory() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    for step in workflow["jobs"]["terraform-validate"]["steps"]:
        if _is_lock_guard_step(step):
            step.pop("working-directory", None)
            step["working-directory"] = "infrastructure/terraform"
            step["run"] = (
                "terraform providers lock -platform=linux_amd64 "
                "-platform=linux_amd64\n"
                f"{LOCK_DIFF_COMMAND}\n"
            )
            break
    else:
        raise AssertionError("no lock-guard step to mutate")
    _assert_linux_amd64_lock_guard(workflow)


def test_oidc_docs_record_dynamodb_retention_and_migration_trigger() -> None:
    _assert_lock_retention_docs(
        OIDC_README_PATH.read_text(encoding="utf-8"),
        OIDC_RUNBOOK_PATH.read_text(encoding="utf-8"),
    )


def test_workflow_without_linux_amd64_lock_guard_is_rejected() -> None:
    workflow = _load_ci_workflow()
    stripped = copy.deepcopy(workflow)
    stripped["jobs"]["terraform-validate"]["steps"] = [
        step
        for step in stripped["jobs"]["terraform-validate"]["steps"]
        if not _is_lock_guard_step(step)
    ]
    with pytest.raises(AssertionError, match="terraform-validate must run"):
        _assert_linux_amd64_lock_guard(stripped)


def test_lock_guard_without_linux_amd64_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    _mutate_lock_guard_run(
        workflow,
        "cd infrastructure/terraform\n"
        "terraform providers lock -platform=darwin_arm64 "
        "-platform=windows_amd64\n"
        f"{LOCK_DIFF_COMMAND}\n",
    )
    with pytest.raises(AssertionError, match="must cover linux_amd64"):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_continue_on_error_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    for step in workflow["jobs"]["terraform-validate"]["steps"]:
        if _is_lock_guard_step(step):
            step["continue-on-error"] = True
            break
    else:
        raise AssertionError("no lock-guard step to mutate")
    with pytest.raises(AssertionError):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_if_false_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    for step in workflow["jobs"]["terraform-validate"]["steps"]:
        if _is_lock_guard_step(step):
            step["if"] = "false"
            break
    else:
        raise AssertionError("no lock-guard step to mutate")
    with pytest.raises(AssertionError):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_job_if_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    workflow["jobs"]["terraform-validate"]["if"] = "false"
    with pytest.raises(AssertionError):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_timeout_below_20_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    workflow["jobs"]["terraform-validate"]["timeout-minutes"] = 10
    with pytest.raises(AssertionError, match="must budget >= 20 minutes"):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_or_true_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    _mutate_lock_guard_run(
        workflow,
        "cd infrastructure/terraform\n"
        "terraform providers lock -platform=linux_amd64 "
        "-platform=darwin_arm64 -platform=windows_amd64 || true\n"
        f"{LOCK_DIFF_COMMAND} || true\n",
    )
    with pytest.raises(AssertionError):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_commented_out_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    _mutate_lock_guard_run(
        workflow,
        "cd infrastructure/terraform\n"
        "# terraform providers lock -platform=linux_amd64 "
        "-platform=darwin_arm64 -platform=windows_amd64\n"
        f"# {LOCK_DIFF_COMMAND}\n"
        "echo skipped\n",
    )
    with pytest.raises(AssertionError):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_set_plus_e_exit_0_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    _mutate_lock_guard_run(
        workflow,
        "cd infrastructure/terraform\n"
        "set +e\n"
        "terraform providers lock -platform=linux_amd64 "
        "-platform=darwin_arm64 -platform=windows_amd64\n"
        f"{LOCK_DIFF_COMMAND}\n"
        "exit 0\n",
    )
    with pytest.raises(AssertionError):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_git_restore_lock_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    _mutate_lock_guard_run(
        workflow,
        "cd infrastructure/terraform\n"
        "terraform providers lock -platform=linux_amd64 "
        "-platform=darwin_arm64 -platform=windows_amd64\n"
        f"{LOCK_DIFF_COMMAND}\n"
        "git restore .terraform.lock.hcl\n",
    )
    with pytest.raises(AssertionError):
        _assert_linux_amd64_lock_guard(workflow)


def test_docs_without_retention_phrases_are_rejected() -> None:
    with pytest.raises(AssertionError, match="missing retention phrase"):
        _assert_lock_retention_docs("no lock notes", "no lock notes")


def test_readme_without_lock_diff_guard_prose_is_rejected() -> None:
    readme = OIDC_README_PATH.read_text(encoding="utf-8").replace(LOCK_DIFF_COMMAND, "")
    with pytest.raises(AssertionError, match="git diff --exit-code guard"):
        _assert_lock_retention_docs(
            readme,
            OIDC_RUNBOOK_PATH.read_text(encoding="utf-8"),
        )
