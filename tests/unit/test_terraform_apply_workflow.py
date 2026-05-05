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
