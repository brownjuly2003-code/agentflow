"""The no-Docker pipeline path must not probe optional Iceberg services."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.processing import local_pipeline


def test_run_can_disable_iceberg_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(local_pipeline, "DB_PATH", str(tmp_path / "demo.duckdb"))
    monkeypatch.setenv(
        "AGENTFLOW_ICEBERG_CONFIG",
        str(tmp_path / "must-still-be-ignored.yaml"),
    )
    monkeypatch.setattr(
        local_pipeline.ClickHouseSink,
        "from_serving_config",
        lambda: None,
    )

    def fail_if_constructed(*args: object, **kwargs: object) -> None:
        raise AssertionError("Iceberg must stay disabled in the offline demo")

    monkeypatch.setattr(local_pipeline, "IcebergSink", fail_if_constructed)
    monkeypatch.setattr(
        local_pipeline,
        "_generate_random_event",
        lambda: ("events.test", {}),
    )
    monkeypatch.setattr(
        local_pipeline,
        "_process_event",
        lambda *args, **kwargs: (True, "ok"),
    )

    local_pipeline.run(burst=1, iceberg_enabled=False)
