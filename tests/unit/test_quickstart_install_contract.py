from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_setup_scripts_install_the_cloud_extra_used_by_local_pipeline() -> None:
    for relative in ("scripts/setup.sh", "scripts/setup.ps1"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert '".[dev,cloud]"' in text, relative


def test_ci_smokes_clean_wheel_on_all_declared_python_versions() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["python-compat"]

    assert job["strategy"]["matrix"]["python-version"] == ["3.11", "3.12", "3.13"]
    steps = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "--require-hashes -r requirements-docker.lock" in steps
    assert "pip install --quiet --no-deps dist/agentflow_runtime-*.whl" in steps
    assert "pip install --quiet --no-deps dist/agentflow_client-*.whl" in steps
    assert "uv pip install --no-deps --editable ./sdk" in steps
    assert "tests/unit/test_sdk_client.py" in steps
    assert "tests/unit/test_sdk_async_client.py" in steps
    assert "tests/unit/test_event_schemas.py" in steps
    assert "from agentflow.client import AgentFlowClient" in steps
    assert "agentflow_runtime.processing.local_pipeline" in steps
    assert "agentflow_runtime.processing.lake_consumer" in steps
    smoke_step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Smoke quickstart, materializer and deprecated-shim imports"
    )
    assert smoke_step["working-directory"] == "/tmp"  # noqa: S108
    # F-09: the deprecated src.* surface must be exercised through the wheel
    # shim (warning + module identity), and the wheel's top-level namespace
    # policy must gate the build.
    assert "import src.serving.api.main as shim_main" in smoke_step["run"]
    assert "DeprecationWarning" in smoke_step["run"]
    assert any("scripts/wheel_smoke.py" in step.get("run", "") for step in job["steps"]), (
        "python-compat must run the wheel top-level namespace policy"
    )

    required_job = workflow["jobs"]["test-unit"]
    assert "python-compat" in required_job["needs"]
