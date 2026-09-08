from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_workflow() -> dict:
    path = PROJECT_ROOT / ".github" / "workflows" / "terraform-apply.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_terraform_apply_workflow_keeps_apply_disabled_but_adds_preflight():
    workflow = _load_workflow()
    jobs = workflow["jobs"]
    preflight_steps = yaml.safe_dump(jobs["preflight"]["steps"])

    assert jobs["plan"]["if"] is False
    assert jobs["apply"]["if"] is False
    assert "terraform apply" not in preflight_steps
    assert "AWS_TERRAFORM_ROLE_ARN" in preflight_steps
    assert "terraform init -backend=false" in preflight_steps
    assert "terraform validate" in preflight_steps
    assert "AssumeRoleWithWebIdentity" in preflight_steps


TERRAFORM_ARTIFACT_DIR = ".artifacts/terraform"
TERRAFORM_PLAN_FILE = f"{TERRAFORM_ARTIFACT_DIR}/tfplan"
# Both Terraform steps run from infrastructure/terraform, so the plan file is
# addressed from the checkout root rather than written next to the configuration.
TERRAFORM_PLAN_WORKSPACE_PATH = f'"$GITHUB_WORKSPACE/{TERRAFORM_PLAN_FILE}"'
PLAN_ARTIFACT_NAME = "terraform-plan-${{ inputs.environment }}"
STATE_KEY_INIT = (
    'terraform init -backend-config="key=env/${{ inputs.environment }}/terraform.tfstate"'
)
UPLOAD_ARTIFACT_PIN = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
DOWNLOAD_ARTIFACT_PIN = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
LEGACY_PLAN_PATH = "infrastructure/terraform/tfplan"


def _job(name: str) -> dict:
    return _load_workflow()["jobs"][name]


def _step(job: dict, name: str) -> dict:
    step = next((item for item in job["steps"] if item.get("name") == name), None)
    assert step is not None, f"step not found: {name}"
    return step


def _uses_step(job: dict, action_prefix: str) -> dict:
    step = next(
        (item for item in job["steps"] if str(item.get("uses", "")).startswith(action_prefix)),
        None,
    )
    assert step is not None, f"uses step not found: {action_prefix}"
    return step


def _run_lines(step: dict) -> list[str]:
    return [
        line.strip()
        for line in step["run"].splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_plan_job_writes_plan_file_under_ignored_artifacts_and_uploads_it() -> None:
    plan = _job("plan")
    plan_step = _step(plan, "Terraform plan")
    upload = _uses_step(plan, "actions/upload-artifact@")

    assert plan_step["working-directory"] == "infrastructure/terraform"
    assert _run_lines(plan_step) == [
        STATE_KEY_INIT,
        f'mkdir -p "$GITHUB_WORKSPACE/{TERRAFORM_ARTIFACT_DIR}"',
        'terraform plan -var-file="${{ steps.tfvars.outputs.file }}" '
        f"-out={TERRAFORM_PLAN_WORKSPACE_PATH}",
    ]
    assert upload["uses"].startswith(UPLOAD_ARTIFACT_PIN)
    assert upload["with"] == {"name": PLAN_ARTIFACT_NAME, "path": TERRAFORM_PLAN_FILE}


def test_apply_job_downloads_the_same_plan_path_and_applies_it() -> None:
    apply = _job("apply")
    download = _uses_step(apply, "actions/download-artifact@")
    apply_step = _step(apply, "Terraform apply")

    assert apply["needs"] == "plan"
    assert download["uses"].startswith(DOWNLOAD_ARTIFACT_PIN)
    assert download["with"] == {"name": PLAN_ARTIFACT_NAME, "path": TERRAFORM_ARTIFACT_DIR}
    assert apply_step["working-directory"] == "infrastructure/terraform"
    assert _run_lines(apply_step) == [
        STATE_KEY_INIT,
        f"terraform apply -auto-approve {TERRAFORM_PLAN_WORKSPACE_PATH}",
    ]


def test_plan_file_never_lands_next_to_the_configuration() -> None:
    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "terraform-apply.yml").read_text(
        encoding="utf-8"
    )
    gitignore_lines = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert LEGACY_PLAN_PATH not in workflow_text
    assert "-out=tfplan" not in workflow_text
    assert "-auto-approve tfplan" not in workflow_text
    assert ".artifacts/" in gitignore_lines
