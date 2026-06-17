"""Shape tests for .github/workflows/benchmark-arm.yml.

Evidence channel: a dispatch-only benchmark on the
GitHub-hosted arm64 runner for public repositories (ubuntu-24.04-arm), the
available ARM server class for this project. The workflow must stay
dispatch-only (it is real load work, not a PR
gate), must run on the arm64 runner label, and must upload the three evidence
artifacts (host metadata, report, results JSON) so docs/perf/ records can be
verified against a real run.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_workflow() -> dict:
    path = PROJECT_ROOT / ".github" / "workflows" / "benchmark-arm.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on_section(workflow: dict) -> dict:
    # An unquoted `on:` key parses as the YAML boolean True; accept both.
    return workflow.get("on", workflow.get(True))


def _job(workflow: dict) -> dict:
    return workflow["jobs"]["benchmark-arm"]


def test_benchmark_arm_is_dispatch_only():
    on = _on_section(_load_workflow())

    assert "workflow_dispatch" in on
    assert "pull_request" not in on
    assert "push" not in on
    assert "schedule" not in on


def test_benchmark_arm_runs_on_free_arm64_runner():
    job = _job(_load_workflow())

    assert job["runs-on"] == "ubuntu-24.04-arm"


def test_benchmark_arm_runs_canonical_benchmark_script():
    job = _job(_load_workflow())

    run_steps = [step.get("run", "") for step in job["steps"] if "run" in step]
    assert any("scripts/run_benchmark.py" in run for run in run_steps)


def test_benchmark_arm_uploads_evidence_artifacts():
    job = _job(_load_workflow())

    upload_steps = [
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert upload_steps
    paths = upload_steps[0]["with"]["path"]
    for artifact in (
        "arm-host-metadata.md",
        "arm-benchmark.md",
        "arm-current.json",
    ):
        assert artifact in paths
    assert upload_steps[0]["with"]["if-no-files-found"] == "error"
