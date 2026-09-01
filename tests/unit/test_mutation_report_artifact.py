"""Runtime-artifact ownership for mutation JSON and workflow uploads."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from scripts import mutation_report, quality_report

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "mutation.yml"


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _on_section(workflow: dict) -> dict:
    # An unquoted `on:` key parses as the YAML boolean True; accept both.
    return workflow.get("on", workflow.get(True))


def test_parse_args_defaults_to_ignored_runtime_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["mutation_report.py"])

    args = mutation_report.parse_args()

    assert Path(args.results_dir) == mutation_report.DEFAULT_RESULTS_DIR
    assert mutation_report.DEFAULT_RESULTS_DIR == ROOT / ".artifacts" / "mutation"
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_relative_results_dir_resolves_from_project_root_not_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    relative = mutation_report.resolve_results_dir(".artifacts/mutation/custom")
    absolute = tmp_path / "outside" / "mutation"

    assert relative == ROOT / ".artifacts" / "mutation" / "custom"
    assert mutation_report.resolve_results_dir(absolute) == absolute
    assert mutation_report.resolve_results_dir(str(absolute)) == absolute
    assert mutation_report.resolve_results_dir(mutation_report.DEFAULT_RESULTS_DIR) == (
        mutation_report.DEFAULT_RESULTS_DIR
    )


@pytest.mark.parametrize(
    "results_dir",
    [
        "docs",
        "docs/mutation",
        "docs/archive/quality-report-2026-07-23.md",
        str(ROOT / "docs"),
        str(ROOT / "docs" / "perf"),
        str(ROOT / "docs" / "archive" / "quality-report-2026-07-23.md"),
    ],
)
def test_docs_destinations_are_rejected_before_run_mutmut(
    results_dir: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["mutation_report.py", "--results-dir", results_dir],
    )

    def fail_if_mutmut_runs(*_args: object, **_kwargs: object) -> dict:
        pytest.fail("docs destination validation must run before run_mutmut")

    monkeypatch.setattr(mutation_report, "run_mutmut", fail_if_mutmut_runs)

    assert mutation_report.main() == 2
    assert ".artifacts/mutation" in capsys.readouterr().err


def test_skip_run_creates_nested_parent_and_writes_utf8_lf_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results_dir = tmp_path / "nested" / "mutation-run"
    monkeypatch.setattr(
        sys,
        "argv",
        ["mutation_report.py", "--skip-run", "--results-dir", str(results_dir)],
    )

    def fail_if_mutmut_runs(*_args: object, **_kwargs: object) -> dict:
        pytest.fail("skip-run must not invoke mutmut")

    monkeypatch.setattr(mutation_report, "run_mutmut", fail_if_mutmut_runs)

    mutation_report.main()

    summary_path = results_dir / mutation_report.SUMMARY_FILENAME
    raw = summary_path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    assert summary_path.name == "mutmut-cicd-stats.json"
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    assert payload["killed"] == 0
    assert payload["survived"] == 0
    assert payload["total"] == 0
    assert 'workspace / "mutants"' in (ROOT / "scripts" / "mutation_report.py").read_text(
        encoding="utf-8"
    )


def test_workflow_uploads_ignored_mutation_artifacts_and_keeps_name() -> None:
    workflow = _load_workflow()
    on = _on_section(workflow)
    job = workflow["jobs"]["mutation"]
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert on["schedule"] == [{"cron": "0 4 * * 0"}]
    assert "workflow_dispatch" in on
    assert job["timeout-minutes"] == 60
    assert "python scripts/mutation_report.py" in workflow_text

    upload_steps = [
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(upload_steps) == 1
    assert upload_steps[0]["with"]["name"] == "mutmut-results"
    assert upload_steps[0]["with"]["path"] == ".artifacts/mutation/"
    assert "path: mutants/" not in workflow_text


def test_quality_report_reads_canonical_mutation_directory() -> None:
    results_dir = quality_report.mutation_report_module.DEFAULT_RESULTS_DIR

    assert results_dir == mutation_report.DEFAULT_RESULTS_DIR
    assert results_dir == ROOT / ".artifacts" / "mutation"

    _metrics, overall = quality_report.load_mutation_metrics()

    assert ".artifacts/mutation/mutmut-cicd-stats.json" in overall


def test_docs_contributing_and_plan_name_mutation_runtime_owner() -> None:
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    plan = (ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8")

    assert "| Mutation report |" in docs_hub
    assert "python scripts/mutation_report.py" in docs_hub
    assert ".artifacts/mutation/" in docs_hub
    assert "date-stamped" in docs_hub
    assert "python scripts/mutation_report.py" in contributing
    assert ".artifacts/mutation/" in contributing
    assert "project root" in contributing
    assert "date-stamped" in contributing
    assert "Mutation report runtime-artifact ownership sub-slice" in plan
    assert "- [x] **6. Отделить generated reference.**" in plan
    assert "Пункт 6 остаётся открыт" in plan
