from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from scripts import run_benchmark

ROOT = Path(__file__).resolve().parents[2]
ARCHIVED_LOAD_BENCHMARK_BLOB = "8488572c9abb10b2aedf9aae35e0467de672cf9e"


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


def test_parse_args_defaults_report_to_ignored_runtime_artifact(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py"])

    args = run_benchmark.parse_args()

    assert args.report_path == str(
        run_benchmark.PROJECT_ROOT / ".artifacts" / "benchmark" / "benchmark.md"
    )
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "relative_path",
    [
        "docs/perf/load-benchmark-latest.md",
        "docs/archive/performance/load-benchmark-2026-04-17.md",
    ],
)
def test_tracked_benchmark_docs_cannot_be_overwritten(relative_path):
    with pytest.raises(ValueError, match=r"\.artifacts/benchmark"):
        run_benchmark.resolve_report_path(relative_path)


@pytest.mark.parametrize(
    "results_path",
    [
        "docs/benchmark-baseline.json",
        str(ROOT / "docs" / "benchmark-baseline.json"),
    ],
)
def test_main_rejects_canonical_baseline_before_runtime(results_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_benchmark.py", "--results-json", results_path],
    )

    def fail_if_runtime_starts() -> None:
        raise AssertionError("benchmark runtime started before output validation")

    monkeypatch.setattr(
        run_benchmark,
        "ensure_locust_available",
        fail_if_runtime_starts,
    )

    assert run_benchmark.main() == 2
    assert "canonical benchmark baseline" in capsys.readouterr().err.lower()


@pytest.mark.parametrize(
    "report_path",
    [
        "docs/perf/arm-server-benchmark-2026-06-05.md",
        "docs/perf/arm-benchmark-2026-06-05/arm-benchmark.md",
        "docs/perf/arm-benchmark-2026-06-05/arm-host-metadata.md",
        str(ROOT / "docs" / "perf" / "arm-server-benchmark-2026-06-05.md"),
        str(ROOT / "docs" / "perf" / "arm-benchmark-2026-06-05" / "arm-benchmark.md"),
        str(ROOT / "docs" / "perf" / "arm-benchmark-2026-06-05" / "arm-host-metadata.md"),
    ],
)
def test_arm_reviewed_reports_cannot_be_runtime_output(report_path):
    with pytest.raises(ValueError, match=r"(?i)reviewed tracked evidence"):
        run_benchmark.resolve_report_path(report_path)


@pytest.mark.parametrize(
    "results_path",
    [
        "docs/perf/arm-benchmark-2026-06-05/arm-current.json",
        str(ROOT / "docs" / "perf" / "arm-benchmark-2026-06-05" / "arm-current.json"),
    ],
)
def test_arm_reviewed_results_cannot_be_runtime_output(results_path):
    with pytest.raises(ValueError, match=r"(?i)reviewed tracked evidence"):
        run_benchmark.resolve_results_path(results_path)


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--report-path", "docs/perf/arm-benchmark-2026-06-05/arm-benchmark.md"),
        (
            "--results-json",
            "docs/perf/arm-benchmark-2026-06-05/arm-current.json",
        ),
    ],
)
def test_main_rejects_arm_reviewed_evidence_before_runtime(flag, value, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py", flag, value])

    def fail_if_runtime_starts() -> None:
        raise AssertionError("benchmark runtime started before output validation")

    monkeypatch.setattr(
        run_benchmark,
        "ensure_locust_available",
        fail_if_runtime_starts,
    )

    assert run_benchmark.main() == 2
    assert "reviewed tracked evidence" in capsys.readouterr().err.lower()


def test_ignored_benchmark_runtime_artifacts_remain_writable():
    report_paths = (
        ".artifacts/benchmark/benchmark.md",
        ".artifacts/benchmark/arm-benchmark.md",
        ".artifacts/benchmark/arm-host-metadata.md",
    )
    results_paths = (
        ".artifacts/benchmark/current.json",
        ".artifacts/benchmark/arm-current.json",
    )

    for relative in report_paths:
        assert run_benchmark.resolve_report_path(relative) == ROOT / relative
    for relative in results_paths:
        assert run_benchmark.resolve_results_path(relative) == ROOT / relative


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


def test_build_report_documents_runtime_artifact_scope():
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

    assert "runtime artifact" in report
    assert ".artifacts/benchmark/benchmark.md" in report
    assert "date-stamped" in report
    assert "docs/perf/entity-benchmark-contract.md" in report


def test_full_load_benchmark_docs_name_owner_and_snapshot_lifecycle():
    current = " ".join(
        (ROOT / "docs" / "perf" / "load-benchmark-latest.md").read_text(encoding="utf-8").split()
    )
    archived = " ".join(
        (ROOT / "docs" / "archive" / "performance" / "load-benchmark-2026-04-17.md")
        .read_text(encoding="utf-8")
        .split()
    )
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "Full-load benchmark artifact lifecycle" in current
    assert "`python scripts/run_benchmark.py`" in current
    assert "`.artifacts/benchmark/benchmark.md`" in current
    assert "`.artifacts/benchmark/current.json`" in current
    assert "read-only gate input" in current
    assert "`docs/benchmark-baseline.json`" in current
    assert "archive/performance/load-benchmark-2026-04-17.md" in current
    assert "Original path: *docs/perf/load-benchmark-latest.md*" in archived
    assert "Content type: historical generated full-load benchmark snapshot" in archived
    assert "Generated: `2026-04-17T12:55:58+03:00`" in archived
    assert "| Full-load benchmark |" in docs_hub
    assert "Read-only gate input `docs/benchmark-baseline.json`" in docs_hub
    assert ".artifacts/benchmark/benchmark.md" in docs_hub
    assert "python scripts/run_benchmark.py" in contributing
    assert ".artifacts/benchmark/benchmark.md" in contributing
    assert "must not replace `docs/benchmark-baseline.json`" in contributing
    assert "Full-load benchmark snapshot/lifecycle sub-slice" in plan
    assert "Canonical full-load gate baseline protection sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan


def test_archived_load_benchmark_body_preserves_the_original_git_blob():
    archived = (
        ROOT / "docs" / "archive" / "performance" / "load-benchmark-2026-04-17.md"
    ).read_bytes()
    marker = b"> The report body below is unchanged; only this provenance block was added."
    _metadata, original_tail = archived.split(marker, maxsplit=1)
    original = b"# AgentFlow Benchmark Report" + original_tail
    git_blob = b"blob " + str(len(original)).encode("ascii") + b"\0" + original

    assert hashlib.sha1(git_blob, usedforsecurity=False).hexdigest() == ARCHIVED_LOAD_BENCHMARK_BLOB


def test_ci_consumes_the_ignored_runtime_report() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'report_path = Path(".artifacts/benchmark/benchmark.md")' in workflow
    assert 'report_path = Path("docs/perf/load-benchmark-latest.md")' not in workflow


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
