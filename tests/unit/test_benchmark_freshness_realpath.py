from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import benchmark_freshness_realpath

ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_STREAMING_HOP_RECORD = ROOT / "docs" / "perf" / "freshness-realpath-2026-06-30.md"


def test_parse_args_defaults_to_ignored_runtime_artifact(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["benchmark_freshness_realpath.py"])

    args = benchmark_freshness_realpath.parse_args()

    assert args.report_json == str(
        benchmark_freshness_realpath.PROJECT_ROOT
        / ".artifacts"
        / "freshness"
        / "realpath-current.json"
    )
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "report_path",
    [
        "docs/perf/freshness-realpath-2026-06-30.md",
        str(HISTORICAL_STREAMING_HOP_RECORD),
    ],
)
def test_historical_streaming_hop_record_cannot_be_overwritten(report_path: str) -> None:
    with pytest.raises(ValueError, match=r"\.artifacts/freshness"):
        benchmark_freshness_realpath.resolve_report_path(report_path)


def test_main_rejects_historical_record_before_runtime_access(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_freshness_realpath.py",
            "--report-json",
            "docs/perf/freshness-realpath-2026-06-30.md",
        ],
    )

    def fail_if_runtime_is_touched(*_args, **_kwargs):
        pytest.fail("tracked-output validation must run before Kafka access")

    monkeypatch.setattr(benchmark_freshness_realpath, "Producer", fail_if_runtime_is_touched)

    assert benchmark_freshness_realpath.main() == 2
    assert ".artifacts/freshness" in capsys.readouterr().err


def test_streaming_hop_docs_name_owner_output_and_promotion_boundary() -> None:
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    perf_hub = " ".join((ROOT / "docs" / "perf" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "| Streaming-hop freshness benchmark |" in docs_hub
    assert "scripts/benchmark_freshness_realpath.py" in perf_hub
    assert ".artifacts/freshness/realpath-current.json" in perf_hub
    assert "python scripts/benchmark_freshness_realpath.py" in contributing
    assert "docs/perf/freshness-realpath-2026-06-30.md" in contributing
    assert "Streaming-hop freshness immutable-output sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan
