from __future__ import annotations

import sys

from scripts import run_benchmark


def test_read_readme_claims_returns_none_when_claim_table_missing(tmp_path, monkeypatch):
    readme_path = tmp_path / "README.md"
    readme_path.write_text("# AgentFlow\n\nNo benchmark claim table here.\n", encoding="utf-8")
    monkeypatch.setattr(run_benchmark, "README_PATH", readme_path)

    assert run_benchmark.read_readme_claims() is None


def test_parse_args_accepts_host_and_results_json(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_benchmark.py",
            "--host",
            "http://127.0.0.1:8000",
            "--results-json",
            "out.json",
        ],
    )

    args = run_benchmark.parse_args()

    assert args.host == "http://127.0.0.1:8000"
    assert args.results_json == "out.json"


def test_parse_args_accepts_output_alias(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_benchmark.py",
            "--output",
            "alias.json",
        ],
    )

    args = run_benchmark.parse_args()

    assert args.results_json == "alias.json"


def test_resolve_host_seed_db_path_defaults_to_demo_db(monkeypatch):
    monkeypatch.delenv("DUCKDB_PATH", raising=False)

    db_path = run_benchmark.resolve_host_seed_db_path("http://127.0.0.1:8000")

    assert db_path == run_benchmark.PROJECT_ROOT / "agentflow_demo.duckdb"


def test_maybe_seed_host_fixtures_ignores_locked_local_db(monkeypatch, capsys):
    monkeypatch.setattr(
        run_benchmark,
        "resolve_host_seed_db_path",
        lambda host: run_benchmark.PROJECT_ROOT / "agentflow_demo.duckdb",
    )

    def _raise_locked(_: object) -> None:
        raise run_benchmark.duckdb.IOException("locked")

    monkeypatch.setattr(run_benchmark, "seed_benchmark_fixtures", _raise_locked)

    run_benchmark.maybe_seed_host_fixtures("http://127.0.0.1:8000")
    captured = capsys.readouterr()

    assert "Skipping benchmark fixture seed for host run" in captured.out


def test_build_report_warns_when_profile_is_below_canonical_baseline():
    report = run_benchmark.build_report(
        generated_at="2026-04-17T13:00:00+03:00",
        base_url="http://127.0.0.1:8001",
        burst=500,
        users=20,
        spawn_rate=10,
        run_time="30s",
        system_info={
            "os": "Windows",
            "cpu": "cpu",
            "cpu_count": "8",
            "ram": "16 GB",
            "python": "3.13.0",
        },
        claims=None,
        aggregate={
            "request_count": 1,
            "failure_count": 0,
            "failure_rate": 0.0,
            "rps": 1.0,
            "p50": 20.0,
            "p95": 40.0,
            "p99": 50.0,
        },
        endpoint_rows=[],
    )

    assert "below canonical baseline" in report
    assert "50 users" in report
    assert "60s" in report


def test_build_report_documents_warmup_step():
    report = run_benchmark.build_report(
        generated_at="2026-04-17T13:00:00+03:00",
        base_url="http://127.0.0.1:8001",
        burst=500,
        users=50,
        spawn_rate=10,
        run_time="60s",
        system_info={
            "os": "Windows",
            "cpu": "cpu",
            "cpu_count": "8",
            "ram": "16 GB",
            "python": "3.13.0",
        },
        claims=None,
        aggregate={
            "request_count": 1,
            "failure_count": 0,
            "failure_rate": 0.0,
            "rps": 1.0,
            "p50": 20.0,
            "p95": 40.0,
            "p99": 50.0,
        },
        endpoint_rows=[],
    )

    assert "Warmup" in report
    assert "10s" in report


def test_start_api_routes_server_output_to_log_file(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class DummyProcess:
        pass

    def fake_popen(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return DummyProcess()

    monkeypatch.setattr(run_benchmark.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(run_benchmark, "PROJECT_ROOT", tmp_path)

    process = run_benchmark.start_api(env={"DUCKDB_PATH": "bench.duckdb"}, port=8001)

    assert isinstance(process, DummyProcess)
    # stdout goes to a real file handle (not a pipe — pipe backpressure can stall
    # the server). stderr is merged into stdout via STDOUT.
    assert hasattr(captured["kwargs"]["stdout"], "write")
    assert captured["kwargs"]["stderr"] is run_benchmark.subprocess.STDOUT
    assert run_benchmark._API_LOG_PATH == tmp_path / ".tmp" / "api-bench-8001.log"
