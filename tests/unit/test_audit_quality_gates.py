from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_required_ci_quality_gates_are_local_and_fail_closed() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(workflow)
    checkout = next(
        step
        for step in parsed["jobs"]["test-unit"]["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )

    assert checkout["with"]["fetch-depth"] == 0
    assert "--cov-fail-under=60" in workflow
    assert (
        "diff-cover .artifacts/coverage/coverage.xml --compare-branch=origin/main --fail-under=80"
    ) in workflow
    assert "--fail-under=90" in workflow
    assert "mkdocs build --strict" in workflow
    assert "python scripts/validate_project_claims.py" in workflow
    # Audit F-06: the non-functional Codecov upload was removed outright, so
    # no external reporting step can mask the local blocking floors, and the
    # test job must not carry the OIDC capability that existed only for it.
    all_step_actions = [
        str(step.get("uses", ""))
        for job in parsed["jobs"].values()
        for step in job.get("steps", [])
    ]
    assert not any("codecov" in action.lower() for action in all_step_actions)
    assert "id-token" not in parsed["jobs"]["test-unit"].get("permissions", {})


def test_dev_profile_pins_quality_gate_tool_families() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["optional-dependencies"]["dev"]

    for package in ("diff-cover", "mkdocs", "mkdocs-material"):
        assert any(
            dependency == package
            or dependency.startswith(f"{package}<")
            or dependency.startswith(f"{package}>")
            for dependency in dependencies
        )


def test_wait_target_uses_bounded_http_helper() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "scripts/wait_for_http.py" in makefile
    assert 'python -c "import time, urllib.request' not in makefile


def test_quality_and_security_docs_do_not_publish_stale_claims() -> None:
    quality = (ROOT / "docs" / "quality.md").read_text(encoding="utf-8")
    security = (ROOT / "docs" / "security-audit.md").read_text(encoding="utf-8")

    assert "67.09% line coverage" not in quality
    assert "- Coverage:" in quality
    assert "source `coverage.xml`" in quality
    assert "Argon2id" in security
    assert "default security policy sets bcrypt" not in security


def test_pull_request_template_does_not_claim_workflows_are_generated() -> None:
    template = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")

    assert "workflow YAML is generated from this" not in template
