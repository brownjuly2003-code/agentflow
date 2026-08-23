"""The no-Docker pipeline path must not probe optional Iceberg services."""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path

import pytest

from agentflow_runtime.processing import local_pipeline


def test_local_pipeline_imports_without_pyiceberg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Core-only installs must load local_pipeline without the cloud extra.

    ``pyiceberg`` is optional ([cloud]); ``--no-iceberg`` and unconfigured
    local runs must not require it at import time.
    """
    real_import = builtins.__import__

    def block_pyiceberg(
        name: str,
        globals: dict | None = None,  # noqa: A002 — mirrors builtins.__import__
        locals: dict | None = None,  # noqa: A002
        fromlist: tuple = (),
        level: int = 0,
    ):
        if name == "pyiceberg" or name.startswith("pyiceberg."):
            raise ModuleNotFoundError(name)
        return real_import(name, globals, locals, fromlist, level)

    for key in list(sys.modules):
        if (
            key == "agentflow_runtime.processing.local_pipeline"
            or key == "agentflow_runtime.processing.iceberg_sink"
            or key == "pyiceberg"
            or key.startswith("pyiceberg.")
        ):
            monkeypatch.delitem(sys.modules, key, raising=False)

    monkeypatch.setattr(builtins, "__import__", block_pyiceberg)

    module = importlib.import_module("agentflow_runtime.processing.local_pipeline")
    assert module.run is not None


def test_main_forwards_cli_args_including_no_iceberg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installed-wheel smoke imports ``main``; CLI must stay callable as main(argv)."""
    captured: dict[str, object] = {}

    def fake_run(
        events_per_second: int = 10,
        burst: int = 0,
        *,
        iceberg_enabled: bool = True,
    ) -> None:
        captured["events_per_second"] = events_per_second
        captured["burst"] = burst
        captured["iceberg_enabled"] = iceberg_enabled

    monkeypatch.setattr(local_pipeline, "run", fake_run)

    rc = local_pipeline.main(["--eps", "7", "--burst", "3", "--no-iceberg"])

    assert rc == 0
    assert captured == {
        "events_per_second": 7,
        "burst": 3,
        "iceberg_enabled": False,
    }


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
