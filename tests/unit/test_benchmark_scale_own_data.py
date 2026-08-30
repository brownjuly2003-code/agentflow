from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import benchmark_scale_own_data

ROOT = Path(__file__).resolve().parents[2]
S13_SCALE_RECORD = ROOT / "docs" / "perf" / "scale-own-data-2026-07-11.md"


def test_parse_args_defaults_to_ignored_runtime_artifacts(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["benchmark_scale_own_data.py"])

    args = benchmark_scale_own_data.parse_args()

    assert args.report_json == str(
        benchmark_scale_own_data.PROJECT_ROOT / ".artifacts" / "scale" / "own-data-current.json"
    )
    assert args.report_md == str(
        benchmark_scale_own_data.PROJECT_ROOT / ".artifacts" / "scale" / "own-data-current.md"
    )
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "report_path",
    [
        "docs/perf/scale-own-data-2026-07-11.md",
        str(S13_SCALE_RECORD),
    ],
)
def test_s13_scale_record_cannot_be_overwritten(report_path: str) -> None:
    with pytest.raises(ValueError, match=r"\.artifacts/scale"):
        benchmark_scale_own_data.resolve_report_path(report_path)


@pytest.mark.parametrize("output_flag", ["--report-json", "--report-md"])
def test_main_rejects_s13_record_before_clickhouse_access(
    monkeypatch, capsys, output_flag: str
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_scale_own_data.py",
            output_flag,
            "docs/perf/scale-own-data-2026-07-11.md",
        ],
    )

    def fail_if_runtime_is_touched(*_args, **_kwargs):
        pytest.fail("tracked-output validation must run before ClickHouse access")

    monkeypatch.setattr(benchmark_scale_own_data, "ClickHouseHTTP", fail_if_runtime_is_touched)

    assert benchmark_scale_own_data.main() == 2
    assert ".artifacts/scale" in capsys.readouterr().err


def test_runtime_markdown_names_artifacts_and_promotion_boundary() -> None:
    report: dict[str, object] = {
        "days": 1,
        "generated_at": "2026-07-11T00:00:00+00:00",
        "database": "rv_scale",
        "anchor": "2026-07-11 00:00:00.000",
        "clickhouse_version": "24.8",
        "orders": 1_965,
        "units": 7_300,
        "total_rows": 10_000,
        "total_compressed_bytes": 1_000_000,
        "total_uncompressed_bytes": 2_000_000,
        "load": [],
        "load_total_rows": 0,
        "load_total_seconds": 0.0,
        "load_total_rows_per_s": 0,
        "queries": {},
        "checks": [],
        "disk": [],
    }

    markdown = benchmark_scale_own_data.render_markdown(report)

    assert "runtime artifact" in markdown.lower()
    assert ".artifacts/scale/own-data-current.md" in markdown
    assert ".artifacts/scale/own-data-current.json" in markdown
    assert "date-stamped" in markdown
    assert "not a production" in markdown.lower()


def test_s13_scale_docs_name_owner_outputs_and_promotion_boundary() -> None:
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    perf_hub = " ".join((ROOT / "docs" / "perf" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "| Own-data scale benchmark |" in docs_hub
    assert "scripts/benchmark_scale_own_data.py" in perf_hub
    assert ".artifacts/scale/own-data-current.json" in perf_hub
    assert ".artifacts/scale/own-data-current.md" in perf_hub
    assert "python scripts/benchmark_scale_own_data.py" in contributing
    assert "docs/perf/scale-own-data-2026-07-11.md" in contributing
    assert "S13 own-data scale runtime-output sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan
