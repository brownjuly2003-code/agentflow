"""Runtime-artifact ownership for the chaos report CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from scripts import chaos_report

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "chaos.yml"
RUNBOOK_PATH = ROOT / "docs" / "operations" / "chaos-runbook.md"

SAMPLE_PYTEST_REPORT = {
    "status": "failed",
    "exitcode": 1,
    "summary": {
        "collected": 2,
        "total": 2,
        "passed": 1,
        "failed": 1,
        "error": 0,
        "skipped": 0,
    },
    "tests": [
        {
            "nodeid": "tests/chaos/test_b.py::test_b",
            "outcome": "failed",
            "metadata": {
                "scenario": "zulu",
                "expectation": "degrade",
                "ci_mode": True,
            },
            "setup": {"duration": 0.1},
            "call": {"duration": 0.2},
            "teardown": {"duration": 0.05},
        },
        {
            "nodeid": "tests/chaos/test_a.py::test_a",
            "outcome": "passed",
            "metadata": {"scenario": "alpha", "expectation": "survive"},
            "call": {"duration": 1.5},
        },
    ],
}


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_parse_args_defaults_to_ignored_runtime_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["chaos_report.py"])

    args = chaos_report.parse_args()

    assert args.input == chaos_report.DEFAULT_INPUT_PATH
    assert args.input == ROOT / ".artifacts" / "chaos" / "chaos-report.json"
    assert args.output is None
    assert args.markdown is None
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_relative_and_absolute_paths_resolve_from_project_root(tmp_path: Path) -> None:
    relative = chaos_report.resolve_path(".artifacts/chaos/custom-report.json")
    absolute = tmp_path / "nested" / "chaos-report.json"

    assert relative == ROOT / ".artifacts" / "chaos" / "custom-report.json"
    assert chaos_report.resolve_path(absolute) == absolute
    assert chaos_report.resolve_path(str(absolute)) == absolute


def test_build_report_preserves_schema_and_scenario_order() -> None:
    source = ROOT / ".artifacts" / "chaos" / "chaos-report.json"

    report = chaos_report.build_report(SAMPLE_PYTEST_REPORT, source)

    assert set(report) == {
        "generated_at",
        "source",
        "status",
        "exitcode",
        "ci_mode",
        "summary",
        "scenario_summary",
        "scenarios",
    }
    assert report["source"] == str(source)
    assert report["status"] == "ok"
    assert report["exitcode"] == 1
    assert report["ci_mode"] is True
    assert report["summary"] == {
        "collected": 2,
        "total": 2,
        "passed": 1,
        "failed": 1,
        "errors": 0,
        "skipped": 0,
    }
    assert [item["scenario"] for item in report["scenarios"]] == ["alpha", "zulu"]
    assert report["scenarios"][0]["outcome"] == "passed"
    assert report["scenarios"][1]["outcome"] == "failed"
    assert report["scenario_summary"] == {
        "total": 2,
        "passed": 1,
        "failed": 1,
        "skipped": 0,
    }
    assert report["generated_at"].endswith("+00:00")


def test_main_writes_parent_utf8_lf_outputs_and_keeps_stdout_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "pytest-report.json"
    output_path = tmp_path / "nested" / "summary" / "chaos-summary.json"
    markdown_path = tmp_path / "nested" / "summary" / "chaos-summary.md"
    input_path.write_text(json.dumps(SAMPLE_PYTEST_REPORT), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chaos_report.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--markdown",
            str(markdown_path),
        ],
    )

    assert chaos_report.main() == 0

    json_raw = output_path.read_bytes()
    markdown_raw = markdown_path.read_bytes()
    payload = json.loads(json_raw.decode("utf-8"))
    markdown = markdown_raw.decode("utf-8")
    assert json_raw.endswith(b"\n")
    assert b"\r" not in json_raw
    assert markdown_raw.endswith(b"\n")
    assert b"\r" not in markdown_raw
    assert payload["scenarios"][0]["scenario"] == "alpha"
    assert payload["scenarios"][1]["scenario"] == "zulu"
    assert "# Chaos Report" in markdown
    assert "[passed] alpha" in markdown
    assert "[failed] zulu" in markdown
    assert capsys.readouterr().out == ""


def test_main_stdout_fallback_and_missing_input_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_path = tmp_path / "missing" / "chaos-report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["chaos_report.py", "--input", str(missing_path)],
    )

    assert chaos_report.main() == 1

    stdout = capsys.readouterr().out
    assert stdout.endswith("\n")
    assert "\r" not in stdout
    assert "# Chaos Report" in stdout
    assert f"source: `{missing_path}`" in stdout
    assert "exitcode: 1" in stdout


def test_workflow_and_runbook_keep_ignored_chaos_working_files() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")
    workflow = _load_workflow()

    assert "--input .artifacts/chaos/chaos-report.json" in workflow_text
    assert "--output .artifacts/chaos/chaos-summary.json" in workflow_text
    assert "--markdown .artifacts/chaos/chaos-summary.md" in workflow_text
    assert "--json-report-file=.artifacts/chaos/chaos-report.json" in workflow_text
    assert "--input chaos-report.json" not in workflow_text
    assert "--output chaos-summary.json" not in workflow_text
    assert "--markdown chaos-summary.md" not in workflow_text
    assert "--json-report-file=chaos-report.json" not in workflow_text

    upload_names = [
        step["with"]["name"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    upload_paths = [
        step["with"]["path"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert upload_names == ["chaos-smoke-report", "chaos-report"]
    assert upload_paths == [".artifacts/chaos/", ".artifacts/chaos/"]

    assert ".artifacts/chaos/chaos-report.json" in runbook
    assert ".artifacts/chaos/chaos-summary.json" in runbook
    assert ".artifacts/chaos/chaos-summary.md" in runbook
    assert "python scripts/chaos_report.py" in runbook
    assert "default" in runbook.lower()
    assert "project root" in runbook.lower()
    assert "parent" in runbook.lower()
    assert "date-stamped" in runbook


def test_docs_contributing_and_plan_name_chaos_runtime_owner() -> None:
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    plan = (ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8")

    assert "| Chaos report |" in docs_hub
    assert "python scripts/chaos_report.py" in docs_hub
    assert ".artifacts/chaos/chaos-report.json" in docs_hub
    assert "date-stamped" in docs_hub
    assert "python scripts/chaos_report.py" in contributing
    assert ".artifacts/chaos/chaos-report.json" in contributing
    assert "project root" in contributing
    assert "date-stamped" in contributing
    assert "Chaos report runtime-artifact ownership sub-slice" in plan
    assert "- [ ] **6. Отделить generated reference.**" in plan
    assert "Пункт 6 остаётся открыт" in plan
