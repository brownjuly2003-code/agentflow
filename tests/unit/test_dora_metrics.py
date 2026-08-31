"""Runtime-artifact ownership for DORA JSON and workflow working files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from scripts import dora_metrics

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "dora.yml"


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _on_section(workflow: dict) -> dict:
    # An unquoted `on:` key parses as the YAML boolean True; accept both.
    return workflow.get("on", workflow.get(True))


def test_parse_args_defaults_to_ignored_runtime_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["dora_metrics.py"])

    args = dora_metrics.parse_args()

    assert args.output == dora_metrics.DEFAULT_OUTPUT_PATH
    assert args.output == ROOT / ".artifacts" / "dora" / "dora-report.json"
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_relative_output_resolves_from_project_root() -> None:
    assert dora_metrics.resolve_output_path(".artifacts/dora/custom.json") == (
        ROOT / ".artifacts" / "dora" / "custom.json"
    )


def test_write_report_creates_parent_and_writes_utf8_lf_json(tmp_path: Path) -> None:
    output_path = tmp_path / "nested" / "dora-report.json"
    report = {
        "generated_at": "2026-08-31T00:00:00+00:00",
        "window_days": 30,
        "branch": "main",
        "metrics": {},
    }

    dora_metrics.write_report(output_path, report)

    raw = output_path.read_bytes()
    assert raw.decode("utf-8") == json.dumps(report, indent=2) + "\n"
    assert b"\r" not in raw
    assert json.loads(output_path.read_text(encoding="utf-8")) == report


def test_main_writes_explicit_output_without_network_or_live_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "nested" / "custom-report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["dora_metrics.py", "--output", str(output_path)],
    )
    monkeypatch.setattr(dora_metrics, "_load_commits", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(dora_metrics, "_load_deployment_log", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        dora_metrics,
        "_load_github_runs",
        lambda *_args, **_kwargs: ([], None),
    )
    monkeypatch.setattr(dora_metrics, "_parse_repo_slug", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        dora_metrics,
        "_fetch_json",
        lambda *_args, **_kwargs: pytest.fail("GitHub API must not be contacted"),
    )
    monkeypatch.setattr(
        dora_metrics,
        "_run_git",
        lambda *_args, **_kwargs: pytest.fail("live git history must not be read"),
    )

    assert dora_metrics.main() == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["window_days"] == 30
    assert payload["branch"] == "main"
    assert payload["metrics"]["deployment_frequency"]["deployments"] == 0
    assert payload["metrics"]["lead_time_for_changes"]["changes"] == 0
    assert b"\r" not in output_path.read_bytes()
    stdout = capsys.readouterr().out
    assert "DORA metrics for main over the last 30 day(s)" in stdout
    assert f"Wrote report to {output_path}" in stdout


def test_workflow_uses_ignored_dora_working_files_and_upload() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    job = _load_workflow()["jobs"]["dora-report"]
    run_steps = [step.get("run", "") for step in job["steps"] if "run" in step]
    joined = "\n".join(run_steps)

    assert "--output .artifacts/dora/dora-report.json" in joined
    assert ".artifacts/dora/dora-report.json" in joined
    assert ".artifacts/dora/dora-summary.md" in joined
    assert ".artifacts/dora/dora-comment.md" in joined
    assert 'Path("dora-report.json")' not in workflow_text
    assert 'Path("dora-summary.md")' not in workflow_text
    assert 'Path("dora-comment.md")' not in workflow_text
    assert 'readFileSync("dora-comment.md"' not in workflow_text
    assert "--output dora-report.json" not in workflow_text

    upload_steps = [
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(upload_steps) == 1
    assert upload_steps[0]["with"]["name"] == "dora-report"
    upload_paths = upload_steps[0]["with"]["path"]
    assert ".artifacts/dora/dora-report.json" in upload_paths
    assert ".artifacts/dora/dora-summary.md" in upload_paths


def test_workflow_retains_schedule_dispatch_pr_and_comment_behavior() -> None:
    workflow = _load_workflow()
    on = _on_section(workflow)
    job = workflow["jobs"]["dora-report"]

    assert on["schedule"] == [{"cron": "0 6 * * 1"}]
    assert "workflow_dispatch" in on
    assert on["pull_request"]["branches"] == ["main"]

    comment_steps = [step for step in job["steps"] if step.get("name") == "Comment on pull request"]
    assert len(comment_steps) == 1
    comment = comment_steps[0]
    assert comment["if"] == "github.event_name == 'pull_request'"
    assert str(comment["uses"]).startswith("actions/github-script@")
    script = comment["with"]["script"]
    assert 'readFileSync(".artifacts/dora/dora-comment.md"' in script
    assert "<!-- dora-report -->" in script
    assert "github.rest.issues.updateComment" in script
    assert "github.rest.issues.createComment" in script
    assert "github.paginate(github.rest.issues.listComments" in script
