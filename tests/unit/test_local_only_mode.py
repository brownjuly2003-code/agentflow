"""Local-only API mode must not construct or probe external infrastructure."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts import demo_local
from src.quality.monitors.metrics_collector import HealthCollector
from src.serving import cache as cache_module
from src.serving import provision
from src.serving.api.main import app
from src.serving.cache import QueryCache

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_local_health_collector_keeps_only_embedded_checks() -> None:
    collector = HealthCollector(include_external=False)

    assert [check.__name__ for check in collector._checks] == [
        "_check_serving",
        "_check_freshness",
        "_check_quality_score",
    ]


def test_metrics_collector_imports_without_pyiceberg() -> None:
    """Core/local mode must import HealthCollector when pyiceberg is absent."""
    script = """
import os
import sys

# Force pyiceberg absent even if the host env has the cloud extra installed.
sys.modules["pyiceberg"] = None
sys.modules["pyiceberg.exceptions"] = None

from src.quality.monitors.metrics_collector import (
    CheckSource,
    HealthCollector,
    HealthStatus,
)

collector = HealthCollector(include_external=False)
assert [check.__name__ for check in collector._checks] == [
    "_check_serving",
    "_check_freshness",
    "_check_quality_score",
]

# Existing config + blocked pyiceberg must yield degraded placeholder, not
# the missing-config path (config check runs before the lazy import).
health = collector._check_iceberg()
assert health.name == "iceberg"
assert health.status == HealthStatus.DEGRADED
assert health.source == CheckSource.PLACEHOLDER
assert health.message.startswith("Iceberg unavailable")
assert "Iceberg config not found" not in health.message
print("ok")
"""
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yaml",
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write("catalog:\n  name: test\n")
        config_path = handle.name

    env = os.environ.copy()
    env["AGENTFLOW_ICEBERG_CONFIG"] = config_path
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    finally:
        Path(config_path).unlink(missing_ok=True)

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_disabled_query_cache_does_not_construct_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RedisMustNotBeUsed:
        @staticmethod
        def from_url(url: str) -> object:
            raise AssertionError(f"Redis must stay disabled, got {url}")

    monkeypatch.setattr(cache_module, "redis", RedisMustNotBeUsed())

    query_cache = QueryCache(enabled=False)

    assert query_cache._redis is None


def test_local_only_lifespan_wires_embedded_components(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environment = demo_local.build_environment(
        tmp_path / "demo.duckdb",
        base_environment={},
    )
    environment["AGENTFLOW_USAGE_DB_PATH"] = str(tmp_path / "usage.duckdb")
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert provision.main(["--schema", "--seed"]) == 0

    previous_webhook_autostart = getattr(app.state, "webhook_dispatcher_autostart", True)
    previous_alert_autostart = getattr(app.state, "alert_dispatcher_autostart", True)
    app.state.webhook_dispatcher_autostart = False
    app.state.alert_dispatcher_autostart = False
    try:
        with TestClient(app) as client:
            assert client.app.state.local_only is True
            assert client.app.state.query_cache._disabled is True
            assert [check.__name__ for check in client.app.state.health_collector._checks] == [
                "_check_serving",
                "_check_freshness",
                "_check_quality_score",
            ]
            assert client.app.state.metric_cache_controller._push_task is None
            assert client.app.state.metric_cache_controller._scan_task is None
    finally:
        app.state.webhook_dispatcher_autostart = previous_webhook_autostart
        app.state.alert_dispatcher_autostart = previous_alert_autostart
