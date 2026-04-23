import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from src.quality.monitors.metrics_collector import (
    CheckSource,
    ComponentHealth,
    HealthStatus,
    PipelineHealth,
)
from src.serving.api.main import app
from src.serving.db_pool import DuckDBPool
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine


def _build_pool(db_path: Path, pool_size: int = 2) -> DuckDBPool:
    pool = DuckDBPool(str(db_path), pool_size=pool_size)
    pool.initialize()
    return pool


def test_initialize_creates_expected_connections(tmp_path):
    pool = _build_pool(tmp_path / "pool.duckdb", pool_size=3)

    try:
        stats = pool.stats()
        assert stats["pool_size"] == 3
        assert stats["read_available"] == 3
        assert stats["read_in_use"] == 0
        assert stats["write_in_use"] == 0
        assert pool.write_connection is not None
    finally:
        pool.close()


def test_read_connection_returns_to_pool_after_use(tmp_path):
    pool = _build_pool(tmp_path / "pool.duckdb", pool_size=2)

    try:
        with pool.read_conn() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
            stats = pool.stats()
            assert stats["read_in_use"] == 1
            assert stats["read_available"] == 1

        stats = pool.stats()
        assert stats["read_in_use"] == 0
        assert stats["read_available"] == 2
    finally:
        pool.close()


def test_concurrent_reads_use_multiple_connections(tmp_path):
    pool = _build_pool(tmp_path / "pool.duckdb", pool_size=2)
    entered: list[str] = []
    release_reads = threading.Event()

    try:
        with pool.write_conn() as conn:
            conn.execute("CREATE TABLE numbers AS SELECT * FROM range(5)")

        def worker(name: str) -> None:
            with pool.read_conn() as conn:
                conn.execute("SELECT COUNT(*) FROM numbers").fetchone()
                entered.append(name)
                release_reads.wait(timeout=1)

        first = threading.Thread(target=worker, args=("first",))
        second = threading.Thread(target=worker, args=("second",))

        first.start()
        second.start()

        deadline = time.monotonic() + 1
        while len(entered) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)

        assert sorted(entered) == ["first", "second"]
        release_reads.set()
        first.join(timeout=1)
        second.join(timeout=1)
    finally:
        pool.close()


def test_read_connection_waits_when_pool_is_exhausted(tmp_path):
    pool = _build_pool(tmp_path / "pool.duckdb", pool_size=1)
    first_acquired = threading.Event()
    release_first = threading.Event()
    second_acquired = threading.Event()

    try:

        def first_reader() -> None:
            with pool.read_conn():
                first_acquired.set()
                release_first.wait(timeout=1)

        def second_reader() -> None:
            with pool.read_conn():
                second_acquired.set()

        first = threading.Thread(target=first_reader)
        second = threading.Thread(target=second_reader)

        first.start()
        assert first_acquired.wait(timeout=1)

        second.start()
        time.sleep(0.1)
        assert not second_acquired.is_set()

        release_first.set()
        first.join(timeout=1)
        second.join(timeout=1)
        assert second_acquired.is_set()
    finally:
        pool.close()


def test_write_connection_is_serialized_with_lock(tmp_path):
    pool = _build_pool(tmp_path / "pool.duckdb", pool_size=1)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    try:
        with pool.write_conn() as conn:
            conn.execute("CREATE TABLE writes(id INTEGER)")

        def first_writer() -> None:
            with pool.write_conn() as conn:
                conn.execute("INSERT INTO writes VALUES (1)")
                first_entered.set()
                release_first.wait(timeout=1)

        def second_writer() -> None:
            with pool.write_conn() as conn:
                conn.execute("INSERT INTO writes VALUES (2)")
                second_entered.set()

        first = threading.Thread(target=first_writer)
        second = threading.Thread(target=second_writer)

        first.start()
        assert first_entered.wait(timeout=1)

        second.start()
        time.sleep(0.1)
        assert not second_entered.is_set()

        release_first.set()
        first.join(timeout=1)
        second.join(timeout=1)
        assert second_entered.is_set()
    finally:
        pool.close()


def test_query_engine_uses_pool_for_reads(tmp_path):
    pool = _build_pool(tmp_path / "engine.duckdb", pool_size=2)

    try:
        engine = QueryEngine(
            catalog=DataCatalog(),
            db_path=str(tmp_path / "engine.duckdb"),
            db_pool=pool,
        )

        entity = engine.get_entity("product", "PROD-001")

        assert entity is not None
        assert entity["name"] == "Wireless Headphones"
        assert engine._conn is pool.write_connection
        assert pool.stats()["read_in_use"] == 0
    finally:
        pool.close()


def test_health_endpoint_reports_pool_utilization(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "health.duckdb"))
    monkeypatch.setenv("DUCKDB_POOL_SIZE", "4")
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "usage.duckdb"))
    previous_autostart = getattr(app.state, "webhook_dispatcher_autostart", True)
    app.state.webhook_dispatcher_autostart = False

    try:
        with TestClient(app) as client:
            assert hasattr(client.app.state, "health_collector")
            response = client.get("/v1/health")
            assert response.status_code == 200
            component = next(
                item for item in response.json()["components"] if item["name"] == "duckdb_pool"
            )
            assert component["metrics"]["pool_size"] == 4
            assert "read_utilization" in component["metrics"]
    finally:
        app.state.webhook_dispatcher_autostart = previous_autostart


def test_default_duckdb_pool_size_scales_with_cpu_count(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "auto-pool.duckdb"))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "usage.duckdb"))
    monkeypatch.delenv("DUCKDB_POOL_SIZE", raising=False)
    monkeypatch.setattr("src.serving.api.main.os.cpu_count", lambda: 8)
    previous_webhook_autostart = getattr(app.state, "webhook_dispatcher_autostart", True)
    previous_alert_autostart = getattr(app.state, "alert_dispatcher_autostart", True)
    app.state.webhook_dispatcher_autostart = False
    app.state.alert_dispatcher_autostart = False

    try:
        with TestClient(app) as client:
            assert client.app.state.duckdb_pool_size == 16
            assert client.app.state.db_pool.stats()["pool_size"] == 16
    finally:
        app.state.webhook_dispatcher_autostart = previous_webhook_autostart
        app.state.alert_dispatcher_autostart = previous_alert_autostart


def test_health_endpoint_does_not_block_parallel_entity_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "health_parallel.duckdb"))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "usage.duckdb"))
    previous_webhook_autostart = getattr(app.state, "webhook_dispatcher_autostart", True)
    previous_alert_autostart = getattr(app.state, "alert_dispatcher_autostart", True)
    app.state.webhook_dispatcher_autostart = False
    app.state.alert_dispatcher_autostart = False

    collect_started = threading.Event()
    release_collect = threading.Event()

    def slow_collect():
        collect_started.set()
        release_collect.wait(timeout=1)
        return PipelineHealth(
            overall=HealthStatus.HEALTHY,
            components=[
                ComponentHealth(
                    name="stub",
                    status=HealthStatus.HEALTHY,
                    message="ok",
                    last_check=datetime.now(UTC),
                    metrics={},
                    source=CheckSource.LIVE,
                )
            ],
            checked_at=datetime.now(UTC),
        )

    try:
        with TestClient(app) as client:
            client.app.state.health_collector.collect = slow_collect

            def call_health():
                client.get("/v1/health")

            health_thread = threading.Thread(target=call_health)
            health_thread.start()
            assert collect_started.wait(timeout=1)

            started_at = time.monotonic()
            entity_response = client.get("/v1/entity/product/PROD-001")
            elapsed = time.monotonic() - started_at

            release_collect.set()
            health_thread.join(timeout=1)

            assert entity_response.status_code == 200
            assert elapsed < 0.5
    finally:
        app.state.webhook_dispatcher_autostart = previous_webhook_autostart
        app.state.alert_dispatcher_autostart = previous_alert_autostart


def test_health_endpoint_reuses_recent_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "health_cache.duckdb"))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "usage.duckdb"))
    previous_webhook_autostart = getattr(app.state, "webhook_dispatcher_autostart", True)
    previous_alert_autostart = getattr(app.state, "alert_dispatcher_autostart", True)
    app.state.webhook_dispatcher_autostart = False
    app.state.alert_dispatcher_autostart = False

    calls = 0

    def collect_once():
        nonlocal calls
        calls += 1
        return PipelineHealth(
            overall=HealthStatus.HEALTHY,
            components=[
                ComponentHealth(
                    name="stub",
                    status=HealthStatus.HEALTHY,
                    message=f"call-{calls}",
                    last_check=datetime.now(UTC),
                    metrics={"calls": calls},
                    source=CheckSource.LIVE,
                )
            ],
            checked_at=datetime.now(UTC),
        )

    try:
        with TestClient(app) as client:
            client.app.state.health_collector.collect = collect_once
            client.app.state.health_cache_ttl_seconds = 60.0
            client.app.state.health_cache_payload = None
            client.app.state.health_cache_expires_at = 0.0

            first = client.get("/v1/health")
            second = client.get("/v1/health")

            assert first.status_code == 200
            assert second.status_code == 200
            assert calls == 1
            assert first.json() == second.json()
    finally:
        app.state.webhook_dispatcher_autostart = previous_webhook_autostart
        app.state.alert_dispatcher_autostart = previous_alert_autostart


def test_health_endpoint_coalesces_concurrent_cache_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "health_coalesce.duckdb"))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "usage.duckdb"))
    previous_webhook_autostart = getattr(app.state, "webhook_dispatcher_autostart", True)
    previous_alert_autostart = getattr(app.state, "alert_dispatcher_autostart", True)
    app.state.webhook_dispatcher_autostart = False
    app.state.alert_dispatcher_autostart = False

    calls = 0
    collect_started = threading.Event()
    release_collect = threading.Event()

    def slow_collect():
        nonlocal calls
        calls += 1
        collect_started.set()
        release_collect.wait(timeout=1)
        return PipelineHealth(
            overall=HealthStatus.HEALTHY,
            components=[
                ComponentHealth(
                    name="stub",
                    status=HealthStatus.HEALTHY,
                    message="ok",
                    last_check=datetime.now(UTC),
                    metrics={"calls": calls},
                    source=CheckSource.LIVE,
                )
            ],
            checked_at=datetime.now(UTC),
        )

    try:
        with TestClient(app) as client:
            client.app.state.health_collector.collect = slow_collect
            client.app.state.health_cache_ttl_seconds = 60.0
            client.app.state.health_cache_payload = None
            client.app.state.health_cache_expires_at = 0.0

            responses: list[int] = []

            def call_health() -> None:
                responses.append(client.get("/v1/health").status_code)

            threads = [threading.Thread(target=call_health) for _ in range(4)]
            for thread in threads:
                thread.start()

            assert collect_started.wait(timeout=1)
            time.sleep(0.1)
            assert calls == 1

            release_collect.set()
            for thread in threads:
                thread.join(timeout=1)

            assert responses == [200, 200, 200, 200]
    finally:
        app.state.webhook_dispatcher_autostart = previous_webhook_autostart
        app.state.alert_dispatcher_autostart = previous_alert_autostart
