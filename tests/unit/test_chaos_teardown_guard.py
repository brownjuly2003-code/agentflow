"""The chaos teardown guard must tolerate ONLY green-session signal deaths.

The chaos lanes intermittently SIGABRT at interpreter exit after every test
passed (native-library teardown). The guard re-checks the pytest JSON report;
these tests pin the decision table so the tolerance can never widen silently
into masking real failures.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.chaos_teardown_guard import evaluate, main

SIGABRT = 134


def _write_report(path: Path, *, exitcode: int, total: int, failed: int = 0, error: int = 0):
    summary: dict[str, int] = {"total": total, "collected": total}
    passed = total - failed - error
    if passed:
        summary["passed"] = passed
    if failed:
        summary["failed"] = failed
    if error:
        summary["error"] = error
    path.write_text(json.dumps({"exitcode": exitcode, "summary": summary}), encoding="utf-8")


def test_clean_pytest_exit_passes_through(tmp_path: Path):
    code, _ = evaluate(0, tmp_path / "missing.json")

    assert code == 0


def test_green_session_signal_death_is_tolerated(tmp_path: Path):
    report = tmp_path / "report.json"
    _write_report(report, exitcode=0, total=5)

    code, reason = evaluate(SIGABRT, report)

    assert code == 0
    assert "teardown" in reason


def test_real_test_failure_is_not_masked_even_with_signal_exit(tmp_path: Path):
    report = tmp_path / "report.json"
    _write_report(report, exitcode=1, total=5, failed=1)

    code, _ = evaluate(SIGABRT, report)

    assert code == SIGABRT


def test_pytest_verdict_exit_codes_propagate_unchanged(tmp_path: Path):
    report = tmp_path / "report.json"
    _write_report(report, exitcode=1, total=5, failed=1)

    for pytest_code in (1, 2, 3, 4, 5):
        code, _ = evaluate(pytest_code, report)

        assert code == pytest_code


def test_signal_death_without_report_is_a_real_failure(tmp_path: Path):
    code, reason = evaluate(SIGABRT, tmp_path / "never-written.json")

    assert code == SIGABRT
    assert "did not finish" in reason


def test_signal_death_with_empty_collection_is_a_real_failure(tmp_path: Path):
    report = tmp_path / "report.json"
    _write_report(report, exitcode=0, total=0)

    code, _ = evaluate(SIGABRT, report)

    assert code == SIGABRT


def test_signal_death_with_corrupt_report_is_a_real_failure(tmp_path: Path):
    report = tmp_path / "report.json"
    report.write_text("{not json", encoding="utf-8")

    code, _ = evaluate(SIGABRT, report)

    assert code == SIGABRT


def test_errored_session_is_not_masked(tmp_path: Path):
    report = tmp_path / "report.json"
    _write_report(report, exitcode=3, total=5, error=2)

    code, _ = evaluate(SIGABRT, report)

    assert code == SIGABRT


def test_main_cli_green_teardown_abort(tmp_path: Path, capsys):
    report = tmp_path / "report.json"
    _write_report(report, exitcode=0, total=3)

    code = main(["--report", str(report), "--pytest-exit-code", str(SIGABRT)])

    assert code == 0
    assert "::warning" in capsys.readouterr().out


def test_main_cli_real_failure(tmp_path: Path, capsys):
    report = tmp_path / "report.json"
    _write_report(report, exitcode=1, total=3, failed=1)

    code = main(["--report", str(report), "--pytest-exit-code", str(SIGABRT)])

    assert code == SIGABRT
    assert "not green" in capsys.readouterr().err
