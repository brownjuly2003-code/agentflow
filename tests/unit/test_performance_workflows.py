from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_workflow(name: str) -> dict:
    return yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    )


def test_perf_regression_workflow_defines_entity_smoke_gate():
    workflow = _load_workflow("perf-regression.yml")
    job = workflow["jobs"]["perf-smoke"]
    step_commands = "\n".join(
        step.get("run", "") for step in job["steps"] if isinstance(step, dict)
    )

    assert "scripts/profile_entity.py" in step_commands
    assert "--iterations 2000" in step_commands
    assert "--concurrency 16" in step_commands
    assert "docs/perf/ci-smoke-latest.json" in step_commands
    assert "p99_ms" in step_commands
    assert "500" in step_commands


def test_nightly_performance_workflow_archives_baseline_json():
    workflow = _load_workflow("performance.yml")
    job = workflow["jobs"]["perf-baseline"]
    step_commands = "\n".join(
        step.get("run", "") for step in job["steps"] if isinstance(step, dict)
    )
    artifact_steps = [
        step
        for step in job["steps"]
        if isinstance(step, dict) and step.get("uses") == "actions/upload-artifact@v4"
    ]

    assert "scripts/run_benchmark.py" in step_commands
    assert ".artifacts/benchmark/current.json" in step_commands
    assert artifact_steps
    assert artifact_steps[0]["with"]["path"] == ".artifacts/benchmark/"
