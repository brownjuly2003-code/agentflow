from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_workflow(name: str) -> dict:
    return yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    )


def _workflow_triggers(workflow: dict) -> dict:
    # PyYAML follows YAML 1.1 and may deserialize the plain ``on`` key as True.
    return workflow.get("on", workflow[True])


def _step_commands(workflow: dict) -> str:
    return "\n".join(
        step.get("run", "")
        for step in workflow["jobs"]["publish"]["steps"]
        if isinstance(step, dict)
    )


RELEASE_CASES = (
    ("sdk-v2.1.0", "2.1.0", "2.1.0", {"runtime", "python-sdk", "typescript-sdk"}),
    ("v2.1.0", "2.1.0", "2.1.0", {"runtime", "python-sdk", "typescript-sdk"}),
    ("v2.1.0-rc1", "2.1.0rc1", "2.1.0-rc1", {"runtime", "python-sdk"}),
)


def _model_release(tag: str) -> tuple[str, str, set[str]]:
    match = re.fullmatch(r"(?:sdk-v|v)(\d+\.\d+\.\d+(?:-rc\d+)?)", tag)
    assert match is not None
    npm_version = match.group(1)
    python_version = npm_version.replace("-rc", "rc", 1)
    artifacts = {"runtime", "python-sdk"}
    if "-rc" not in npm_version:
        artifacts.add("typescript-sdk")
    return python_version, npm_version, artifacts


def test_npm_publish_workflow_uses_trusted_publishing_oidc():
    workflow = _load_workflow("publish-npm.yml")
    publish_job = workflow["jobs"]["publish"]
    step_commands = "\n".join(
        step.get("run", "") for step in publish_job["steps"] if isinstance(step, dict)
    )
    publish_steps = [
        step
        for step in publish_job["steps"]
        if isinstance(step, dict) and step.get("name") == "Publish to npm"
    ]

    assert workflow["permissions"]["id-token"] == "write"
    assert publish_job["environment"] == "npm"
    assert publish_steps
    assert "npm install -g npm@^11.5.1" in step_commands
    assert "GITHUB_REF_TYPE" in step_commands
    assert "MANUAL_RELEASE_VERSION" in step_commands
    assert "does not match tag" in step_commands
    assert publish_steps[0]["run"] == "npm publish --access public"
    assert "NODE_AUTH_TOKEN" not in publish_steps[0].get("env", {})
    assert "NPM_TOKEN" not in yaml.safe_dump(publish_steps[0])


def test_typescript_package_repository_matches_trusted_publisher_repo():
    package_json = json.loads(
        (PROJECT_ROOT / "sdk-ts" / "package.json").read_text(encoding="utf-8")
    )

    assert package_json["repository"]["type"] == "git"
    assert package_json["repository"]["url"] == (
        "git+https://github.com/brownjuly2003-code/agentflow.git"
    )


def test_publish_workflows_cover_the_same_allowed_release_tags():
    pypi = _load_workflow("publish-pypi.yml")
    npm = _load_workflow("publish-npm.yml")

    expected = ["sdk-v*", "v*-rc*", "v[0-9]+.[0-9]+.[0-9]+"]
    assert _workflow_triggers(pypi)["push"]["tags"] == expected
    assert _workflow_triggers(npm)["push"]["tags"] == expected


def test_allowed_release_tag_matrix_matches_publish_artifacts_and_versions():
    pypi = _load_workflow("publish-pypi.yml")
    npm = _load_workflow("publish-npm.yml")
    pypi_commands = _step_commands(pypi)
    npm_commands = _step_commands(npm)

    for tag, python_version, npm_version, artifacts in RELEASE_CASES:
        assert _model_release(tag) == (python_version, npm_version, artifacts)

    for version_surface in (
        "pyproject.toml",
        "sdk/pyproject.toml",
        "sdk/agentflow/__init__.py",
        "sdk-ts/package.json",
        "sdk-ts/package-lock.json",
    ):
        assert version_surface in pypi_commands
        assert version_surface in npm_commands

    assert "Publish agentflow-runtime to PyPI" in yaml.safe_dump(pypi)
    assert "Publish agentflow-client SDK to PyPI" in yaml.safe_dump(pypi)
    assert "Publish to npm" in yaml.safe_dump(npm)
    assert "env.IS_RC != 'true'" in yaml.safe_dump(npm)


def test_python_publish_checks_artifacts_with_pinned_tooling_before_upload():
    workflow = _load_workflow("publish-pypi.yml")
    steps = workflow["jobs"]["publish"]["steps"]
    names = [step.get("name") for step in steps if isinstance(step, dict)]
    commands = _step_commands(workflow)

    assert "python -m pip install --upgrade build==1.5.1 twine==6.2.0" in commands
    assert "python scripts/check_release_artifacts.py dist/* sdk/dist/*" in commands
    assert names.index("Reject unsafe release artifacts") < names.index(
        "Dry-run build and twine check"
    )
