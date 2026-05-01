from __future__ import annotations

import json
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_workflow(name: str) -> dict:
    return yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    )


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
    assert publish_steps
    assert "npm install -g npm@^11.5.1" in step_commands
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
