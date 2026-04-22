from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import bandit_diff


def _write_report(path, results):
    path.write_text(
        json.dumps({"results": results}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_bandit_diff_passes_when_reports_match(tmp_path, monkeypatch, capsys):
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    report = [
        {
            "test_id": "B310",
            "filename": "src/example.py",
            "line_number": 10,
            "issue_text": "example",
        }
    ]
    _write_report(baseline_path, report)
    _write_report(current_path, report)
    monkeypatch.setattr(
        sys,
        "argv",
        ["bandit_diff.py", str(baseline_path), str(current_path)],
    )

    exit_code = bandit_diff.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "No new findings" in captured.out


def test_bandit_diff_fails_when_new_finding_appears(tmp_path, monkeypatch, capsys):
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    _write_report(
        baseline_path,
        [
            {
                "test_id": "B310",
                "filename": "src/example.py",
                "line_number": 10,
                "issue_text": "example",
            }
        ],
    )
    _write_report(
        current_path,
        [
            {
                "test_id": "B310",
                "filename": "src/example.py",
                "line_number": 10,
                "issue_text": "example",
            },
            {
                "test_id": "B602",
                "filename": "src/new.py",
                "line_number": 42,
                "issue_text": "shell injection",
            },
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["bandit_diff.py", str(baseline_path), str(current_path)],
    )

    exit_code = bandit_diff.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "New bandit findings: 1" in captured.out
    assert "B602 src/new.py:42" in captured.out


def test_bandit_diff_normalizes_mixed_path_separators(tmp_path, monkeypatch, capsys):
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    _write_report(
        baseline_path,
        [
            {
                "test_id": "B310",
                "filename": "src\\serving\\backends\\clickhouse_backend.py",
                "line_number": 49,
                "issue_text": "example",
            }
        ],
    )
    _write_report(
        current_path,
        [
            {
                "test_id": "B310",
                "filename": "src/serving\\backends\\clickhouse_backend.py",
                "line_number": 49,
                "issue_text": "example",
            }
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["bandit_diff.py", str(baseline_path), str(current_path)],
    )

    exit_code = bandit_diff.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "No new findings" in captured.out


def test_checked_in_bandit_baseline_has_no_new_findings(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    report_path = tmp_path / "bandit-current.json"
    scan = subprocess.run(
        [
            sys.executable,
            "-m",
            "bandit",
            "-r",
            "src/",
            "sdk/",
            "-f",
            "json",
            "-o",
            str(report_path),
            "--severity-level",
            "medium",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )

    assert report_path.exists(), scan.stdout + scan.stderr

    diff = subprocess.run(
        [
            sys.executable,
            "scripts/bandit_diff.py",
            ".bandit-baseline.json",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )

    assert diff.returncode == 0, diff.stdout + diff.stderr


def test_inline_nosec_comments_include_reason():
    repo_root = Path(__file__).resolve().parents[2]
    offenders = []

    for path in repo_root.joinpath("src").rglob("*.py"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            if "# nosec" not in line:
                continue
            _, _, suffix = line.partition("# nosec")
            if " - " not in suffix:
                offenders.append(f"{path.relative_to(repo_root)}:{line_number}")

    assert offenders == []
