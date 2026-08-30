from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.load import run_load_test
from tests.load.thresholds import LOAD_PROFILE

ROOT = Path(__file__).resolve().parents[2]


def test_parse_args_defaults_to_ignored_runtime_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_load_test.py"])

    args = run_load_test.parse_args()

    assert args.stats_prefix == str(run_load_test.PROJECT_ROOT / ".artifacts" / "load" / "results")
    assert args.results_json == str(
        run_load_test.PROJECT_ROOT / ".artifacts" / "load" / "results.json"
    )
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_relative_output_paths_resolve_from_project_root() -> None:
    assert run_load_test.resolve_output_path(".artifacts/load/custom") == (
        run_load_test.PROJECT_ROOT / ".artifacts" / "load" / "custom"
    )
    assert run_load_test.resolve_output_path(".artifacts/load/custom.json") == (
        run_load_test.PROJECT_ROOT / ".artifacts" / "load" / "custom.json"
    )


@pytest.mark.parametrize(
    "output_path",
    [
        "docs/perf/results",
        "docs/perf/results.json",
        str(ROOT / "docs" / "perf" / "results"),
        str(ROOT / "docs" / "perf" / "results.json"),
        "tests/load/results",
        "tests/load/results.json",
        str(ROOT / "tests" / "load" / "results"),
        str(ROOT / "tests" / "load" / "results.json"),
    ],
)
def test_docs_perf_and_load_source_outputs_are_rejected(output_path: str) -> None:
    with pytest.raises(ValueError, match=r"\.artifacts/load"):
        run_load_test.resolve_output_path(output_path)


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--stats-prefix", "docs/perf/results"),
        ("--results-json", "docs/perf/results.json"),
        ("--stats-prefix", str(ROOT / "docs" / "perf" / "results")),
        ("--results-json", str(ROOT / "docs" / "perf" / "results.json")),
        ("--stats-prefix", "tests/load/results"),
        ("--results-json", "tests/load/results.json"),
        ("--stats-prefix", str(ROOT / "tests" / "load" / "results")),
        ("--results-json", str(ROOT / "tests" / "load" / "results.json")),
    ],
)
def test_main_rejects_forbidden_outputs_before_seed_and_locust(
    flag: str,
    value: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_load_test.py",
            "--seed-only",
            "--duckdb-path",
            "agentflow_demo.duckdb",
            flag,
            value,
        ],
    )

    def fail_if_seed_runs(*_args: object, **_kwargs: object) -> None:
        pytest.fail("output validation must run before seed_benchmark_data")

    def fail_if_locust_runs(*_args: object, **_kwargs: object) -> None:
        pytest.fail("output validation must run before run_locust")

    monkeypatch.setattr(run_load_test, "seed_benchmark_data", fail_if_seed_runs)
    monkeypatch.setattr(run_load_test, "run_locust", fail_if_locust_runs)

    assert run_load_test.main() == 2
    assert ".artifacts/load" in capsys.readouterr().err


def test_main_seed_only_accepts_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    duckdb_path = tmp_path / "load-seed.duckdb"
    seeded: list[Path] = []
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_load_test.py", "--seed-only", "--duckdb-path", str(duckdb_path)],
    )
    monkeypatch.setattr(
        run_load_test,
        "seed_benchmark_data",
        lambda path: seeded.append(path),
    )

    def fail_if_locust_runs(*_args: object, **_kwargs: object) -> None:
        pytest.fail("seed-only must not start Locust")

    monkeypatch.setattr(run_load_test, "run_locust", fail_if_locust_runs)

    assert run_load_test.main() == 0
    assert seeded == [duckdb_path]


def test_makefile_usage_docs_and_plan_name_load_smoke_owner() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    locustfile = (ROOT / "tests" / "load" / "locustfile.py").read_text(encoding="utf-8")
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    perf_hub = " ".join((ROOT / "docs" / "perf" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "python tests/load/run_load_test.py" in makefile
    assert "--host http://localhost:8000" in makefile
    assert "locust -f tests/load/locustfile.py" not in makefile
    assert LOAD_PROFILE == {"users": 50, "spawn_rate": 10, "run_time": "60s"}
    assert "python tests/load/run_load_test.py" in locustfile
    assert "| Locust p99 CI-smoke |" in docs_hub
    assert "python tests/load/run_load_test.py" in docs_hub
    assert ".artifacts/load/results.json" in docs_hub
    assert ".artifacts/load/results" in docs_hub
    assert "docs/benchmark-baseline.json" in docs_hub
    assert "date-stamped" in docs_hub
    assert "tests/load/run_load_test.py" in perf_hub
    assert ".artifacts/load/results.json" in perf_hub
    assert ".artifacts/load/results" in perf_hub
    assert "python tests/load/run_load_test.py" in contributing
    assert ".artifacts/load/results.json" in contributing
    assert ".artifacts/load/results" in contributing
    assert "docs/benchmark-baseline.json" in contributing
    assert "CI-smoke" in contributing
    assert "production SLA" in contributing
    assert "full-load benchmark" in contributing
    assert "date-stamped" in contributing
    assert "Locust p99 CI-smoke runtime-artifact ownership sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan
