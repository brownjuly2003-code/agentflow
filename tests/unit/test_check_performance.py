from __future__ import annotations

import json
import sys

from scripts import check_performance


def _write_report(path, endpoints, *, gate=None):
    payload = {
        "generated_at": "2026-04-17T12:00:00+00:00",
        "endpoints": endpoints,
    }
    if gate is not None:
        payload["gate"] = gate
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


def test_parse_args_uses_repo_defaults(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_performance.py"])

    args = check_performance.parse_args()

    assert args.baseline == check_performance.DEFAULT_BASELINE_PATH
    assert args.current == check_performance.DEFAULT_CURRENT_PATH


def test_parse_args_accepts_named_flags(tmp_path, monkeypatch):
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_performance.py",
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
            "--max-regress",
            "35",
        ],
    )

    args = check_performance.parse_args()

    assert args.baseline == baseline_path
    assert args.current == current_path
    assert args.max_regress == 35.0


def test_main_fails_when_entity_gate_or_regression_is_exceeded(tmp_path, monkeypatch, capsys):
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    gate = {
        "entity": {
            "p50_ms": 100.0,
            "p99_ms": 500.0,
        }
    }
    _write_report(
        baseline_path,
        {
            "GET /v1/entity/order/{id}": {
                "p50_ms": 90.0,
                "p99_ms": 400.0,
            }
        },
        gate=gate,
    )
    _write_report(
        current_path,
        {
            "GET /v1/entity/order/{id}": {
                "p50_ms": 140.0,
                "p99_ms": 650.0,
            }
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_performance.py", str(baseline_path), str(current_path)],
    )

    exit_code = check_performance.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "p50 140.0 ms exceeds gate 100.0 ms" in captured.out
    assert "p99 650.0 ms exceeds gate 500.0 ms" in captured.out
    assert "regressed by 55.6%" in captured.out


def test_main_passes_when_current_results_stay_within_gate(tmp_path, monkeypatch, capsys):
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    gate = {
        "entity": {
            "p50_ms": 100.0,
            "p99_ms": 500.0,
        }
    }
    _write_report(
        baseline_path,
        {
            "GET /v1/entity/order/{id}": {
                "p50_ms": 90.0,
                "p99_ms": 400.0,
            }
        },
        gate=gate,
    )
    _write_report(
        current_path,
        {
            "GET /v1/entity/order/{id}": {
                "p50_ms": 95.0,
                "p99_ms": 420.0,
            }
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_performance.py", str(baseline_path), str(current_path)],
    )

    exit_code = check_performance.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Status: `PASS`" in captured.out


def test_main_allows_custom_regression_threshold(tmp_path, monkeypatch, capsys):
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    _write_report(
        baseline_path,
        {
            "POST /v1/query": {
                "p50_ms": 100.0,
                "p99_ms": 200.0,
            }
        },
    )
    _write_report(
        current_path,
        {
            "POST /v1/query": {
                "p50_ms": 125.0,
                "p99_ms": 220.0,
            }
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_performance.py",
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
            "--max-regress",
            "30",
        ],
    )

    exit_code = check_performance.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Status: `PASS`" in captured.out
