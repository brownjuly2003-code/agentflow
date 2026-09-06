import re
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.unit.test_terraform_lock_retention import (
    _assert_linux_amd64_lock_guard,
    _is_lock_guard_step,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "terraform-apply.yml"
MAKEFILE_PATH = PROJECT_ROOT / "Makefile"
TERRAFORM_MAIN_PATH = PROJECT_ROOT / "infrastructure" / "terraform" / "main.tf"
OIDC_CALL_PATH = PROJECT_ROOT / "infrastructure" / "terraform" / "oidc.tf"
OIDC_MODULE_PATH = (
    PROJECT_ROOT / "infrastructure" / "terraform" / "modules" / "github-oidc" / "main.tf"
)
OIDC_VARIABLES_PATH = (
    PROJECT_ROOT / "infrastructure" / "terraform" / "modules" / "github-oidc" / "variables.tf"
)
OIDC_README_PATH = (
    PROJECT_ROOT / "infrastructure" / "terraform" / "modules" / "github-oidc" / "README.md"
)
OIDC_RUNBOOK_PATH = PROJECT_ROOT / "docs" / "operations" / "aws-oidc-setup.md"
LOCK_PATH = PROJECT_ROOT / "infrastructure" / "terraform" / ".terraform.lock.hcl"
WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
WORKFLOW_FILES = sorted([*WORKFLOWS_DIR.glob("*.yml"), *WORKFLOWS_DIR.glob("*.yaml")])

TERRAFORM_VERSION = "1.15.4"
AWS_PROVIDER_VERSION = "6.46.0"
WORKFLOW_ENVIRONMENT_EXPRESSION = "${{ inputs.environment }}"
STATE_KEY_INIT_LINE = re.compile(r'^terraform init -backend-config="key=(?P<key>[^"]+)"$')
STATE_KEY_SHAPE = re.compile(r"^env/[^/]+/terraform\.tfstate$")
PRODUCTION_INIT_COMMAND = (
    'terraform init -reconfigure -backend-config="key=env/production/terraform.tfstate"'
)
STATE_ENVIRONMENT_SHAPE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TRACKED_INIT_SITES = (*WORKFLOW_FILES, MAKEFILE_PATH)


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _workflow_dispatch_environment_options(workflow: dict) -> set[str]:
    triggers = workflow.get("on", workflow.get(True))
    options = triggers["workflow_dispatch"]["inputs"]["environment"]["options"]
    return set(options)


def _terraform_init_commands(text: str) -> list[str]:
    commands: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for fragment in stripped.split("&&"):
            command = fragment.strip()
            if command.startswith("terraform init"):
                commands.append(command)
    return commands


def _state_key_templates_from_text(text: str) -> list[str]:
    templates: list[str] = []
    for command in _terraform_init_commands(text):
        if command == "terraform init -backend=false":
            continue
        match = STATE_KEY_INIT_LINE.fullmatch(command)
        assert match is not None, f"Terraform init has no recognised state-key contract: {command}"
        templates.append(match.group("key"))
    return templates


def _workflow_state_key_templates(workflow: dict) -> set[str]:
    templates: set[str] = set()

    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            templates.update(_state_key_templates_from_text(str(step.get("run", ""))))

    assert templates, "the workflow must initialise at least one remote state key"
    return templates


def _string_list_assignment(source: str, name: str) -> set[str]:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*\[(?P<body>.*?)\]", source, re.DOTALL)
    assert match is not None, f"assignment not found: {name}"
    return set(re.findall(r'"([^"]+)"', match.group("body")))


def _collected_init_state_keys(*paths: Path) -> list[str]:
    keys: list[str] = []
    for path in paths:
        keys.extend(_state_key_templates_from_text(path.read_text(encoding="utf-8")))
    return keys


def _assert_workflow_init_keys_are_granted(
    *paths: Path,
    workflow_environments: set[str],
    granted_keys: set[str],
) -> None:
    for key in _collected_init_state_keys(*paths):
        resolved = {
            key.replace(WORKFLOW_ENVIRONMENT_EXPRESSION, environment)
            for environment in workflow_environments
        }
        assert resolved <= granted_keys, f"workflow init key is outside the granted prefix: {key}"


def _state_key_local_template(module_source: str, local_name: str) -> str:
    pattern = re.compile(
        rf"\b{re.escape(local_name)}\s*=\s*\[\s*for environment in "
        rf'var\.state_environments\s*:\s*"\$\{{local\.state_bucket_arn\}}/'
        r'(?P<key>[^"]+)"\s*\]'
    )
    match = pattern.search(module_source)
    assert match is not None, f"state-key local not found: {local_name}"
    return match.group("key")


def _iam_statement(module_source: str, sid: str) -> str:
    match = re.search(rf'sid\s*=\s*"{re.escape(sid)}"', module_source)
    assert match is not None, f"IAM statement not found: {sid}"
    start = module_source.rfind("statement {", 0, match.start())
    assert start != -1, f"statement block missing for {sid}"
    rest = module_source[match.end() :]
    next_stmt = re.search(r"\n  statement \{", rest)
    end = match.end() + next_stmt.start() if next_stmt else len(module_source)
    return module_source[start:end]


def _state_lock_id_templates(module_source: str) -> list[str]:
    match = re.search(
        r"state_lock_ids\s*=\s*flatten\(\[\s*"
        r"for environment in var\.state_environments\s*:\s*\[(?P<body>.*?)\]\s*\]\)",
        module_source,
        re.DOTALL,
    )
    assert match is not None, "state_lock_ids local not found"
    return re.findall(r'"([^"]+)"', match.group("body"))


def _quoted_local(module_source: str, name: str) -> str:
    match = re.search(rf'\b{re.escape(name)}\s*=\s*"([^"]+)"', module_source)
    assert match is not None, f"local not found: {name}"
    return match.group(1)


def _backend_s3_bucket(terraform_main: str) -> str:
    match = re.search(r'backend "s3" \{(?P<body>.*?)\n  \}', terraform_main, re.DOTALL)
    assert match is not None, "s3 backend block not found"
    bucket = re.search(r'bucket\s*=\s*"([^"]+)"', match.group("body"))
    assert bucket is not None, "backend bucket not found"
    return bucket.group(1)


def _markdown_section(source: str, heading: str) -> str:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(source)
    assert match is not None, f"section not found: {heading}"
    return match.group("body")


def test_oidc_policy_covers_exactly_the_workflow_state_keys() -> None:
    workflow = _load_workflow()
    workflow_environments = _workflow_dispatch_environment_options(workflow)
    workflow_templates = _workflow_state_key_templates(workflow)
    oidc_call = OIDC_CALL_PATH.read_text(encoding="utf-8")
    module_source = OIDC_MODULE_PATH.read_text(encoding="utf-8")
    terraform_main = TERRAFORM_MAIN_PATH.read_text(encoding="utf-8")

    state_environments = _string_list_assignment(oidc_call, "state_environments")
    allowed_environments = _string_list_assignment(oidc_call, "allowed_environments")
    assert state_environments == workflow_environments
    assert allowed_environments >= workflow_environments
    assert workflow_templates == {f"env/{WORKFLOW_ENVIRONMENT_EXPRESSION}/terraform.tfstate"}

    object_template = _state_key_local_template(module_source, "state_object_arns")
    prefix_template = _state_key_local_template(module_source, "state_prefix_arns")
    granted_objects = {
        object_template.replace("${environment}", environment) for environment in state_environments
    }
    granted_prefixes = {
        prefix_template.replace("${environment}", environment) for environment in state_environments
    }
    workflow_keys = {
        template.replace(WORKFLOW_ENVIRONMENT_EXPRESSION, environment)
        for template in workflow_templates
        for environment in workflow_environments
    }

    assert granted_objects == workflow_keys
    assert granted_prefixes == {f"env/{environment}/*" for environment in workflow_environments}
    assert re.search(
        r"resources\s*=\s*concat\(\s*local\.state_object_arns,\s*"
        r"local\.state_prefix_arns\s*\)",
        module_source,
    )
    assert "infrastructure/terraform.tfstate" not in module_source
    assert "infrastructure/*" not in module_source
    assert re.search(r'sid\s*=\s*"TerraformStateLockTable"', module_source) is None

    describe_statement = _iam_statement(module_source, "TerraformStateLockTableDescribe")
    assert "dynamodb:DescribeTable" in describe_statement
    assert "dynamodb:PutItem" not in describe_statement
    assert "dynamodb:GetItem" not in describe_statement
    assert "dynamodb:DeleteItem" not in describe_statement
    assert "dynamodb:UpdateItem" not in describe_statement
    assert "condition {" not in describe_statement
    assert re.search(r"resources\s*=\s*\[local\.state_table_arn\]", describe_statement)

    items_statement = _iam_statement(module_source, "TerraformStateLockItems")
    assert "dynamodb:DescribeTable" not in items_statement
    for action in ("DeleteItem", "GetItem", "PutItem", "UpdateItem"):
        assert f"dynamodb:{action}" in items_statement
    assert re.search(r"resources\s*=\s*\[local\.state_table_arn\]", items_statement)
    assert "ForAllValues:StringEquals" in items_statement
    assert "dynamodb:LeadingKeys" in items_statement
    assert re.search(r"values\s*=\s*local\.state_lock_ids", items_statement)

    bucket_statement = _iam_statement(module_source, "TerraformStateBucket")
    assert "s3:ListBucket" in bucket_statement
    assert "s3:prefix" not in bucket_statement
    assert "condition {" not in bucket_statement
    assert re.search(r"resources\s*=\s*\[local\.state_bucket_arn\]", bucket_statement)

    lock_id_templates = _state_lock_id_templates(module_source)
    assert lock_id_templates == [
        "${local.state_bucket_name}/env/${environment}/terraform.tfstate",
        "${local.state_bucket_name}/env/${environment}/terraform.tfstate-md5",
    ]
    module_bucket = _quoted_local(module_source, "state_bucket_name")
    backend_bucket = _backend_s3_bucket(terraform_main)
    assert module_bucket == backend_bucket
    granted_lock_ids = {
        template.replace("${local.state_bucket_name}", module_bucket).replace(
            "${environment}", environment
        )
        for template in lock_id_templates
        for environment in state_environments
    }
    assert granted_lock_ids == {
        f"{backend_bucket}/env/{environment}/terraform.tfstate{suffix}"
        for environment in state_environments
        for suffix in ("", "-md5")
    }


def test_tracked_terraform_init_keys_match_env_state_shape() -> None:
    assert WORKFLOW_FILES, "no GitHub workflow files discovered"
    assert {p.name for p in WORKFLOW_FILES} >= {"ci.yml", "terraform-apply.yml"}
    assert MAKEFILE_PATH in TRACKED_INIT_SITES

    # Makefile: shape only. `make deploy-dev` inits env/dev/terraform.tfstate
    # with the operator's own credentials, not the CI role — a documented
    # local exception, not an oversight.
    makefile_keys = _collected_init_state_keys(MAKEFILE_PATH)
    assert makefile_keys, "Makefile must name at least one remote state key"
    for key in makefile_keys:
        assert STATE_KEY_SHAPE.fullmatch(key), (
            f"state key is outside env/<name>/terraform.tfstate: {key}"
        )

    workflow = _load_workflow()
    workflow_environments = _workflow_dispatch_environment_options(workflow)
    workflow_templates = _workflow_state_key_templates(workflow)
    state_environments = _string_list_assignment(
        OIDC_CALL_PATH.read_text(encoding="utf-8"), "state_environments"
    )
    workflow_keys = {
        template.replace(WORKFLOW_ENVIRONMENT_EXPRESSION, environment)
        for template in workflow_templates
        for environment in workflow_environments
    }
    granted_keys = {f"env/{environment}/terraform.tfstate" for environment in state_environments}
    assert workflow_keys == granted_keys

    workflow_init_keys = _collected_init_state_keys(*WORKFLOW_FILES)
    assert workflow_init_keys, "terraform workflows must name at least one remote state key"
    for key in workflow_init_keys:
        assert STATE_KEY_SHAPE.fullmatch(key), (
            f"state key is outside env/<name>/terraform.tfstate: {key}"
        )
    _assert_workflow_init_keys_are_granted(
        *WORKFLOW_FILES,
        workflow_environments=workflow_environments,
        granted_keys=granted_keys,
    )


def test_nongranted_workflow_init_key_is_rejected(tmp_path: Path) -> None:
    rogue = tmp_path / "attacker.yml"
    rogue.write_text(
        'terraform init -backend-config="key=env/attacker/terraform.tfstate"\n',
        encoding="utf-8",
    )
    workflow = _load_workflow()
    workflow_environments = _workflow_dispatch_environment_options(workflow)
    granted_keys = {
        f"env/{environment}/terraform.tfstate"
        for environment in _string_list_assignment(
            OIDC_CALL_PATH.read_text(encoding="utf-8"), "state_environments"
        )
    }
    with pytest.raises(AssertionError, match="outside the granted prefix"):
        _assert_workflow_init_keys_are_granted(
            rogue,
            workflow_environments=workflow_environments,
            granted_keys=granted_keys,
        )


@pytest.mark.parametrize(
    "spelling",
    [
        "terraform init -backend-config=key=env/attacker/terraform.tfstate",
        'terraform init -backend-config "key=other/prod.tfstate"',
        "terraform init -backend-config=backend.hcl",
        "terraform init",
        "terraform init -backend-config='key=env/staging/terraform.tfstate'",
        "cd infrastructure/terraform && terraform init -backend-config=key=env/dev/terraform.tfstate",
    ],
)
def test_unrecognised_terraform_init_spellings_fail_loudly(spelling: str) -> None:
    with pytest.raises(AssertionError, match="no recognised state-key contract"):
        _state_key_templates_from_text(spelling)


def test_recognised_terraform_init_forms_collect_keys() -> None:
    assert _state_key_templates_from_text("terraform init -backend=false") == []
    assert _state_key_templates_from_text(
        'terraform init -backend-config="key=env/staging/terraform.tfstate"'
    ) == ["env/staging/terraform.tfstate"]
    assert _state_key_templates_from_text(
        'cd infrastructure/terraform && terraform init -backend-config="key=env/dev/terraform.tfstate"'
        " && terraform plan -var-file=dev.tfvars"
    ) == ["env/dev/terraform.tfstate"]


def test_workflow_cli_and_provider_versions_are_reproducibly_pinned() -> None:
    setup_steps = [
        step
        for workflow_path in WORKFLOW_FILES
        for job in yaml.safe_load(workflow_path.read_text(encoding="utf-8"))["jobs"].values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("hashicorp/setup-terraform@")
    ]
    assert setup_steps, "no setup-terraform steps found"
    assert {(step.get("with") or {}).get("terraform_version") for step in setup_steps} == {
        TERRAFORM_VERSION
    }

    terraform_main = TERRAFORM_MAIN_PATH.read_text(encoding="utf-8")
    required_version = re.search(r'required_version\s*=\s*"([^"]+)"', terraform_main)
    aws_provider = re.search(r"aws\s*=\s*\{(?P<body>.*?)\n\s*\}", terraform_main, re.DOTALL)
    assert required_version is not None
    assert required_version.group(1) == f"= {TERRAFORM_VERSION}"
    assert aws_provider is not None
    assert f'version = "= {AWS_PROVIDER_VERSION}"' in aws_provider.group("body")

    assert LOCK_PATH.is_file()
    lock_source = LOCK_PATH.read_text(encoding="utf-8")
    locked_provider = re.search(
        r'provider "registry\.terraform\.io/hashicorp/aws" \{(?P<body>.*?)\n\}',
        lock_source,
        re.DOTALL,
    )
    assert locked_provider is not None
    lock_body = locked_provider.group("body")
    assert f'version     = "{AWS_PROVIDER_VERSION}"' in lock_body
    assert f'constraints = "{AWS_PROVIDER_VERSION}"' in lock_body
    h1_hashes = set(re.findall(r'"h1:([^"]+)"', lock_body))
    zh_hashes = set(re.findall(r'"zh:[0-9a-f]+"', lock_body))
    assert len(h1_hashes) >= 3, (
        ">=3 h1: hashes is a shape smoke check only; h1: hashes carry no "
        f"platform label (found {len(h1_hashes)} h1 hashes). Coverage of "
        "linux_amd64, darwin_arm64 and windows_amd64 is guarded by the "
        "terraform-validate provider-lock step in .github/workflows/ci.yml, "
        "which regenerates the lock and fails on a non-empty git diff."
    )
    assert zh_hashes, "provider lock must carry registry zh: hashes"

    ci_workflow = yaml.safe_load((WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8"))
    terraform_validate = ci_workflow["jobs"]["terraform-validate"]
    _assert_linux_amd64_lock_guard(ci_workflow)
    lock_guard_steps = [
        step for step in terraform_validate.get("steps", []) if _is_lock_guard_step(step)
    ]
    assert lock_guard_steps, (
        "linux_amd64 coverage is guarded by wiring terraform providers lock and "
        "git diff --exit-code .terraform.lock.hcl into ci.yml terraform-validate, "
        "not by this hash count"
    )

    ignore_check = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "--quiet",
            LOCK_PATH.relative_to(PROJECT_ROOT).as_posix(),
        ],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert ignore_check.returncode == 1, ".terraform.lock.hcl must not be ignored"
    tracked_check = subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            LOCK_PATH.relative_to(PROJECT_ROOT).as_posix(),
        ],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert tracked_check.returncode == 0, ".terraform.lock.hcl must be tracked"


def test_state_environments_variable_rejects_path_shaped_names() -> None:
    variables = OIDC_VARIABLES_PATH.read_text(encoding="utf-8")
    assert 'can(regex("^[a-z0-9][a-z0-9-]*$", environment))' in variables
    assert STATE_ENVIRONMENT_SHAPE.fullmatch("staging")
    assert STATE_ENVIRONMENT_SHAPE.fullmatch("production")
    assert not STATE_ENVIRONMENT_SHAPE.fullmatch("staging/old")
    assert not STATE_ENVIRONMENT_SHAPE.fullmatch("../")
    assert not STATE_ENVIRONMENT_SHAPE.fullmatch("")


def test_oidc_docs_record_shared_role_and_account_global_provider() -> None:
    runbook = OIDC_RUNBOOK_PATH.read_text(encoding="utf-8")
    readme = OIDC_README_PATH.read_text(encoding="utf-8")

    for source in (runbook, readme):
        assert "AWS_TERRAFORM_ROLE_ARN" in source
        assert "state_environments" in source
        assert "EntityAlreadyExists" in source
        assert "terraform import" in source
        assert "module.github_oidc.aws_iam_openid_connect_provider.github_actions" in source
        # F-T-12-25: both pages must carry a runnable recipe, not a bare
        # one-liner. `terraform import` loads the configuration, so it needs
        # the production backend key and the root variables that have no
        # defaults (`environment`, `vpc_id`, `private_subnet_ids`).
        assert PRODUCTION_INIT_COMMAND in source
        assert "terraform import -var-file=environments/prod.tfvars" in source
        assert "`terraform import module.github_oidc" not in source
        assert "token.actions.githubusercontent.com" in source
        assert "s3:ListBucket` is bucket-wide" in source
        assert "s3:prefix" in source
        assert "not readable or writable" in source
        # The page must not claim a role exists: no bootstrap apply has been
        # performed (see the runbook's Current readiness handoff).
        assert "No bootstrap apply has been performed" in source
        assert "only the staging state has been applied" not in source
        assert "exactly one role exists" not in source
        assert "agentflow-terraform-production" in source
        assert "`-boundary` policy" in source
        assert "the operator decides which of the two ARNs" in source

    assert "aws-actions/configure-aws-credentials@v4" not in runbook
    assert "v6.2.3" in runbook
    assert "aws-actions/configure-aws-credentials" in runbook
    assert "confirm the run includes" not in runbook
    verify = _markdown_section(runbook, "Verify OIDC is active")
    assert "In `terraform-apply.yml`" in verify
    assert "e6de054" in verify
    assert "`if: false`" in verify
    # Steps 1, 2 and 4 read the tracked workflow file and hold today; only the
    # CloudTrail step needs a real federated run.
    assert "Steps 1, 2 and 4 are static inspections" in verify
    assert "Step 3 needs a real federated run" in verify
    assert "env/staging/terraform.tfstate" in runbook
    assert "terraform providers lock -platform=linux_amd64" in readme

    assert "`hashicorp/terraform:1.13.5`" in runbook
    assert "superseded" in runbook
    assert 'required_version = "= 1.15.4"' in runbook
    assert "2026-09-05" in runbook
    assert "`hashicorp/terraform:1.15.4`" in runbook
    assert "has not been performed" in runbook
    assert "not evidence of a real apply" in runbook

    assert "terraform destroy" in runbook
    assert "trust anchor" in runbook
    assert "Rotate the thumbprint from the staging state only." in runbook
    thumbprint_section = _markdown_section(runbook, "Thumbprint rotation")
    assert "env/staging/terraform.tfstate" in thumbprint_section
    assert "thumbprint_list" in thumbprint_section
    assert "terraform destroy" in thumbprint_section

    prerequisites = _markdown_section(runbook, "Prerequisites").strip()
    assert prerequisites.startswith("- ")
    assert "### " not in prerequisites
    bullets = [line for line in prerequisites.splitlines() if line.startswith("- ")]
    assert len(bullets) == 4
    prereq_at = runbook.index("## Prerequisites")
    scope_at = runbook.index("## State-key and role scope")
    bootstrap_at = runbook.index("## Bootstrap the role")
    assert prereq_at < scope_at < bootstrap_at
    scope = runbook[scope_at:bootstrap_at]
    assert "### Shared CI role and account-global OIDC provider" in scope
    assert "#shared-ci-role-and-account-global-oidc-provider" in runbook


def test_github_oidc_readme_ends_with_single_newline() -> None:
    raw = OIDC_README_PATH.read_bytes()
    assert raw.endswith(b"```\n")
    assert not raw.endswith(b"```\n\n")
