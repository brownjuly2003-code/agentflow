"""T-36: DynamoDB lock retention is deliberate, and linux_amd64 lock drift is guarded in CI.

`h1:` hashes in `.terraform.lock.hcl` carry no platform label, so a local
count of hashes cannot prove platform coverage. The honest local assertion is
that `.github/workflows/ci.yml` `terraform-validate` runs
`terraform providers lock` with `-platform=linux_amd64` and fails on a
non-empty `git diff --exit-code .terraform.lock.hcl`. The guard step `run`
body is validated against a closed allowlist of effective lines. Additional
`-platform=` values are accepted by this assertion, but any platform named
must also be present in the tracked lock or the git diff guard will fail. The
documented three-platform command satisfies the claim and is what CI actually
runs.

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
LOCK_CD_LINE = "cd infrastructure/terraform"
LOCK_LS_FILES_COMMAND = "git ls-files --error-unmatch .terraform.lock.hcl"
LOCK_LINE_PATTERN = re.compile(r"^terraform providers lock(?:\s+-platform=[a-z0-9_]+)+$")
LOCK_LS_FILES_PATTERN = re.compile(
    r"git ls-files --error-unmatch(?:\s+--)?\s+\.terraform\.lock\.hcl"
)
LOCK_DIFF_PATTERN = re.compile(r"git diff --exit-code(?:\s+--)?\s+\.terraform\.lock\.hcl")
BACKEND_TABLE = 'dynamodb_table = "agentflow-terraform-locks"'

REQUIRED_RETENTION_PHRASES = (
    "Warning: Deprecated Parameter",
    "use_lockfile = true",
    "locking mechanism of a live backend",
    "next Terraform major bump",
    "recreated from scratch",
)


def _load_ci_workflow() -> dict:
    return yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))


def _effective_run_setting(workflow: dict, job: dict, step: dict, key: str):
    """Resolve a GitHub Actions run setting: step, then job defaults, then workflow defaults."""
    return (
        step.get(key)
        or ((job.get("defaults") or {}).get("run") or {}).get(key)
        or ((workflow.get("defaults") or {}).get("run") or {}).get(key)
    )


def _is_lock_ls_files_line(line: str) -> bool:
    return LOCK_LS_FILES_PATTERN.fullmatch(line) is not None


def _is_lock_diff_line(line: str) -> bool:
    return LOCK_DIFF_PATTERN.fullmatch(line) is not None


def _backend_body(terraform_main: str) -> str:
    match = re.search(r'backend "s3" \{(?P<body>.*?)\n  \}', terraform_main, re.DOTALL)
    assert match is not None, "s3 backend block not found"
    return match.group("body")


def _effective_run_lines(run: str) -> list[str]:
    """Non-blank, non-comment lines of a step `run` block, stripped.

    Shell backslash continuations are folded into one effective line (trailing
    ``\\`` stripped, pieces joined with a single space) so a wrapped
    ``terraform providers lock`` still has to match the closed allowlist whole.
    """
    unfolded: list[str] = []
    for raw in str(run).splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        unfolded.append(stripped)

    lines: list[str] = []
    pending = ""
    for stripped in unfolded:
        piece = stripped[:-1].rstrip() if stripped.endswith("\\") else stripped
        if pending:
            pending = f"{pending} {piece}"
        else:
            pending = piece
        if not stripped.endswith("\\"):
            lines.append(pending)
            pending = ""
    if pending:
        lines.append(pending)
    return lines


def _is_lock_guard_step(step: dict, *, working_directory: str | None = None) -> bool:
    """Recognise the provider-lock drift guard by line, not substring.

    After dropping blank and `#` comment lines, the body must contain one
    remaining line that starts with `terraform providers lock` and one git-diff
    lock line (optional ``--`` pathspec separator and extra whitespace allowed),
    and the step must run in `infrastructure/terraform`. `working_directory` is
    the already-resolved GitHub value (step, then job defaults, then workflow
    defaults); when omitted, only the step key is read.
    """
    run = str(step.get("run", ""))
    if working_directory is None:
        working = str(step.get("working-directory", "")).replace("\\", "/")
    else:
        working = str(working_directory).replace("\\", "/")
    lines = _effective_run_lines(run)
    in_terraform_dir = working == "infrastructure/terraform" or any(
        line == "cd infrastructure/terraform" or line.startswith("cd infrastructure/terraform ")
        for line in lines
    )
    has_lock = any(line.startswith(LOCK_COMMAND) for line in lines)
    has_diff = any(_is_lock_diff_line(line) for line in lines)
    return has_lock and has_diff and in_terraform_dir


def _assert_lock_guard_run_not_neutered(run: str, *, working_directory: str = "") -> None:
    """Closed allowlist of effective `run` lines for the provider-lock guard.

    After `_effective_run_lines` (blank/`#` dropped, backslash continuations
    folded), every remaining line must be one of, in this order:

    1. ``cd infrastructure/terraform`` — optional, first line only; required
       unless the step sets ``working-directory: infrastructure/terraform``
    2. ``terraform providers lock`` with one or more ``-platform=`` values —
       required, exactly one; extra whitespace before each flag is allowed
    3. ``git ls-files --error-unmatch .terraform.lock.hcl`` — optional, at most
       one; optional ``--`` pathspec separator and extra whitespace are allowed
    4. ``git diff --exit-code .terraform.lock.hcl`` — required, exactly one,
       last effective line; optional ``--`` and extra whitespace are allowed

    ``_is_lock_guard_step`` stays a loose recogniser on purpose so a neutered
    body is still found and this helper can raise the specific allowlist
    message instead of the generic missing-step assert.
    """
    lines = _effective_run_lines(run)
    lock_lines = [line for line in lines if line.startswith(LOCK_COMMAND)]
    diff_lines = [line for line in lines if _is_lock_diff_line(line)]
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

    kinds: list[int] = []
    for line in lines:
        if line == LOCK_CD_LINE:
            kinds.append(1)
        elif LOCK_LINE_PATTERN.fullmatch(line):
            kinds.append(2)
        elif _is_lock_ls_files_line(line):
            kinds.append(3)
        elif _is_lock_diff_line(line):
            kinds.append(4)
        else:
            raise AssertionError(
                f"lock guard effective line is outside the closed allowlist: {line!r}"
            )

    uses_working_dir = working_directory.replace("\\", "/") == "infrastructure/terraform"
    cd_count = kinds.count(1)
    assert cd_count <= 1, f"lock guard may contain at most one `{LOCK_CD_LINE}`"
    if not uses_working_dir:
        assert cd_count == 1, (
            f"lock guard must start with `{LOCK_CD_LINE}` unless "
            "working-directory: infrastructure/terraform is set"
        )
    if cd_count:
        assert kinds[0] == 1, f"`{LOCK_CD_LINE}` must be the first effective line"
    assert kinds.count(2) == 1, (
        "lock guard must contain exactly one `terraform providers lock -platform=...` line"
    )
    assert kinds.count(3) <= 1, f"lock guard may contain at most one `{LOCK_LS_FILES_COMMAND}`"
    assert kinds.count(4) == 1, f"lock guard must contain exactly one `{LOCK_DIFF_COMMAND}`"
    assert kinds[-1] == 4, f"`{LOCK_DIFF_COMMAND}` must be the last effective line"
    assert kinds == sorted(kinds), (
        "lock guard lines must appear in order: "
        f"`{LOCK_CD_LINE}`, terraform providers lock, "
        f"optional `{LOCK_LS_FILES_COMMAND}`, `{LOCK_DIFF_COMMAND}`"
    )


def _assert_linux_amd64_lock_guard(workflow: dict) -> None:
    triggers = workflow.get("on") or workflow.get(True)
    assert "pull_request" in triggers, (
        "ci.yml must still run on pull_request or the lock guard never gates a PR"
    )
    job = workflow["jobs"]["terraform-validate"]
    assert "if" not in job
    assert job.get("continue-on-error") in (None, False), (
        "terraform-validate must not be continue-on-error"
    )
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

    matching = [
        step
        for step in job.get("steps", [])
        if _is_lock_guard_step(
            step,
            working_directory=str(
                _effective_run_setting(workflow, job, step, "working-directory") or ""
            ),
        )
    ]
    assert matching, (
        "ci.yml terraform-validate must run "
        f"`{LOCK_COMMAND}` with `-platform=linux_amd64` in "
        "infrastructure/terraform/ and fail on "
        f"`{LOCK_DIFF_COMMAND}`"
    )
    for step in matching:
        assert step.get("continue-on-error") in (None, False)
        assert "if" not in step
        effective_shell = _effective_run_setting(workflow, job, step, "shell")
        assert effective_shell in (None, "bash"), (
            "lock guard must not override the default errexit shell"
        )
        run = str(step.get("run", ""))
        _assert_lock_guard_run_not_neutered(
            run,
            working_directory=str(
                _effective_run_setting(workflow, job, step, "working-directory") or ""
            ),
        )
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


def test_linux_amd64_lock_guard_accepts_backslash_continuation() -> None:
    """FALSE-REJECT CONTROL: wrapping the lock command with ``\\`` is still valid."""
    workflow = copy.deepcopy(_load_ci_workflow())
    _mutate_lock_guard_run(
        workflow,
        "cd infrastructure/terraform\n"
        "terraform providers lock -platform=linux_amd64 \\\n"
        "  -platform=darwin_arm64 -platform=windows_amd64\n"
        f"{LOCK_LS_FILES_COMMAND}\n"
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


def test_linux_amd64_lock_guard_accepts_job_defaults_working_directory() -> None:
    """FALSE-REJECT CONTROL: job defaults.run.working-directory is a valid hoist of `cd`."""
    workflow = copy.deepcopy(_load_ci_workflow())
    job = workflow["jobs"]["terraform-validate"]
    job["defaults"] = {"run": {"working-directory": "infrastructure/terraform"}}
    for step in job["steps"]:
        if _is_lock_guard_step(step):
            step.pop("working-directory", None)
            step["run"] = (
                "terraform providers lock -platform=linux_amd64 "
                "-platform=linux_amd64\n"
                f"{LOCK_DIFF_COMMAND}\n"
            )
            break
    else:
        raise AssertionError("no lock-guard step to mutate")
    _assert_linux_amd64_lock_guard(workflow)


def test_linux_amd64_lock_guard_accepts_git_pathspec_separator() -> None:
    """FALSE-REJECT CONTROL: optional `--` before the lock path is still valid."""
    workflow = copy.deepcopy(_load_ci_workflow())
    _mutate_lock_guard_run(
        workflow,
        "cd infrastructure/terraform\n"
        "terraform providers lock  -platform=linux_amd64 "
        "-platform=darwin_arm64 -platform=windows_amd64\n"
        "git ls-files --error-unmatch -- .terraform.lock.hcl\n"
        "git diff --exit-code -- .terraform.lock.hcl\n",
    )
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


def test_lock_guard_job_continue_on_error_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    workflow["jobs"]["terraform-validate"]["continue-on-error"] = True
    with pytest.raises(AssertionError, match="must not be continue-on-error"):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_without_pull_request_trigger_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    workflow["on"] = {"workflow_dispatch": None}
    with pytest.raises(AssertionError, match="must still run on pull_request"):
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


def test_lock_guard_diff_before_lock_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    _mutate_lock_guard_run(
        workflow,
        "cd infrastructure/terraform\n"
        f"{LOCK_DIFF_COMMAND}\n"
        "terraform providers lock -platform=linux_amd64 "
        "-platform=darwin_arm64 -platform=windows_amd64\n",
    )
    with pytest.raises(AssertionError, match="must be the last effective line"):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_cd_workspace_between_lock_and_diff_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    _mutate_lock_guard_run(
        workflow,
        "cd infrastructure/terraform\n"
        "terraform providers lock -platform=linux_amd64 "
        "-platform=darwin_arm64 -platform=windows_amd64\n"
        "cd $GITHUB_WORKSPACE\n"
        f"{LOCK_DIFF_COMMAND}\n",
    )
    with pytest.raises(AssertionError, match="outside the closed allowlist"):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_pathless_git_checkout_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    _mutate_lock_guard_run(
        workflow,
        "cd infrastructure/terraform\n"
        "terraform providers lock -platform=linux_amd64 "
        "-platform=darwin_arm64 -platform=windows_amd64\n"
        "git checkout .\n"
        f"{LOCK_DIFF_COMMAND}\n",
    )
    with pytest.raises(AssertionError, match="outside the closed allowlist"):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_shell_bash_file_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    for step in workflow["jobs"]["terraform-validate"]["steps"]:
        if _is_lock_guard_step(step):
            step["shell"] = "bash {0}"
            break
    else:
        raise AssertionError("no lock-guard step to mutate")
    with pytest.raises(AssertionError, match="must not override the default errexit shell"):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_job_defaults_shell_bash_file_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    workflow["jobs"]["terraform-validate"]["defaults"] = {"run": {"shell": "bash {0}"}}
    with pytest.raises(AssertionError, match="must not override the default errexit shell"):
        _assert_linux_amd64_lock_guard(workflow)


def test_lock_guard_workflow_defaults_shell_bash_file_is_rejected() -> None:
    workflow = copy.deepcopy(_load_ci_workflow())
    workflow["defaults"] = {"run": {"shell": "bash {0}"}}
    with pytest.raises(AssertionError, match="must not override the default errexit shell"):
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
