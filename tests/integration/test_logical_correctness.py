from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import duckdb
import pytest
import structlog
from fastapi.testclient import TestClient
from pyiceberg.exceptions import ServiceUnavailableError

from src.processing import local_pipeline as local_pipeline_module
from src.processing.event_replayer import EventReplayer
from src.serving.api.main import app
from src.serving.control_plane import ensure_dead_letter_table

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "logical.duckdb"))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "logical_api.duckdb"))
    with TestClient(app) as test_client:
        manager = test_client.app.state.auth_manager
        manager.keys_by_value = {}
        manager._hashed_keys = []
        manager._loaded_keys = []
        manager._rate_windows.clear()
        yield test_client


def test_entity_endpoint_returns_503_when_backing_table_is_not_materialized(
    client: TestClient,
) -> None:
    client.app.state.query_engine._conn.execute("DROP TABLE users_enriched")

    response = client.get("/v1/entity/user/USR-10001")

    assert response.status_code == 503
    assert "is not materialized yet" in response.json()["detail"]


def test_metric_endpoint_returns_503_when_backing_table_is_not_materialized(
    client: TestClient,
) -> None:
    client.app.state.query_engine._conn.execute("DROP TABLE pipeline_events")

    response = client.get("/v1/metrics/error_rate?window=1h")

    assert response.status_code == 503
    assert "is not materialized yet" in response.json()["detail"]


def test_local_pipeline_falls_back_to_duckdb_when_iceberg_init_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sample_order_event: dict,
) -> None:
    db_path = tmp_path / "pipeline.duckdb"
    monkeypatch.setattr(local_pipeline_module, "DB_PATH", str(db_path))
    monkeypatch.setenv("AGENTFLOW_ICEBERG_CONFIG", str(tmp_path / "config" / "iceberg.yaml"))
    monkeypatch.setattr(
        local_pipeline_module,
        "_generate_random_event",
        lambda: ("events.raw", dict(sample_order_event)),
    )

    class FailingIcebergSink:
        def __init__(self, config_path=None) -> None:
            raise ServiceUnavailableError("catalog unavailable")

    monkeypatch.setattr(local_pipeline_module, "IcebergSink", FailingIcebergSink)

    local_pipeline_module.run(events_per_second=1, burst=1)

    connection = duckdb.connect(str(db_path))
    try:
        row = connection.execute("SELECT COUNT(*) FROM orders_v2").fetchone()
    finally:
        connection.close()
    assert row == (1,)


def test_local_pipeline_fallback_logging_handles_non_utf8_stdout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sample_order_event: dict,
) -> None:
    db_path = tmp_path / "pipeline_cp1252.duckdb"
    monkeypatch.setattr(local_pipeline_module, "DB_PATH", str(db_path))
    monkeypatch.setenv("AGENTFLOW_ICEBERG_CONFIG", str(tmp_path / "config" / "iceberg.yaml"))
    monkeypatch.setattr(
        local_pipeline_module,
        "_generate_random_event",
        lambda: ("events.raw", dict(sample_order_event)),
    )
    structlog.reset_defaults()

    class FailingIcebergSink:
        def __init__(self, config_path=None) -> None:
            raise ServiceUnavailableError("каталог недоступен → fallback")

    monkeypatch.setattr(local_pipeline_module, "IcebergSink", FailingIcebergSink)
    cp1252_stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", cp1252_stdout)

    local_pipeline_module.run(events_per_second=1, burst=1)

    connection = duckdb.connect(str(db_path))
    try:
        row = connection.execute("SELECT COUNT(*) FROM orders_v2").fetchone()
    finally:
        connection.close()
    assert row == (1,)


def test_local_pipeline_propagates_unexpected_iceberg_init_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sample_order_event: dict,
) -> None:
    db_path = tmp_path / "pipeline_unexpected.duckdb"
    monkeypatch.setattr(local_pipeline_module, "DB_PATH", str(db_path))
    monkeypatch.setenv("AGENTFLOW_ICEBERG_CONFIG", str(tmp_path / "config" / "iceberg.yaml"))
    monkeypatch.setattr(
        local_pipeline_module,
        "_generate_random_event",
        lambda: ("events.raw", dict(sample_order_event)),
    )

    class FailingIcebergSink:
        def __init__(self, config_path=None) -> None:
            raise RuntimeError("unexpected init bug")

    monkeypatch.setattr(local_pipeline_module, "IcebergSink", FailingIcebergSink)

    with pytest.raises(RuntimeError, match="unexpected init bug"):
        local_pipeline_module.run(events_per_second=1, burst=1)


def test_local_pipeline_rolls_back_duckdb_when_iceberg_write_fails(
    tmp_path: Path,
    sample_order_event: dict,
) -> None:
    connection = duckdb.connect(str(tmp_path / "rollback.duckdb"))
    try:
        local_pipeline_module._ensure_tables(connection)

        class FailingIcebergSink:
            def write_batch(self, table_name: str, records: list[dict]) -> int:
                raise RuntimeError("iceberg write failed")

        with pytest.raises(RuntimeError, match="iceberg write failed"):
            local_pipeline_module._process_event(
                connection,
                dict(sample_order_event),
                iceberg_sink=FailingIcebergSink(),
            )

        order_rows = connection.execute("SELECT COUNT(*) FROM orders_v2").fetchone()
        pipeline_rows = connection.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()
    finally:
        connection.close()

    assert order_rows == (0,)
    assert pipeline_rows == (0,)


def test_event_replay_marks_pending_before_publish_finalize(
    tmp_path: Path,
    sample_order_event: dict,
) -> None:
    db_path = tmp_path / "replay.duckdb"
    connection = duckdb.connect(str(db_path))
    event_id = "11111111-1111-1111-1111-111111111111"
    payload = dict(sample_order_event)
    payload["event_id"] = event_id
    payload["order_id"] = "ORD-20260411-9001"
    produced_messages: list[tuple[str, dict]] = []

    ensure_dead_letter_table(connection)
    connection.execute(
        """
        INSERT INTO dead_letter_events (
            event_id,
            event_type,
            payload,
            failure_reason,
            failure_detail,
            received_at,
            retry_count,
            last_retried_at,
            status
        )
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0, NULL, 'failed')
        """,
        [
            event_id,
            payload["event_type"],
            json.dumps(payload),
            "semantic_validation",
            "stated total did not match computed total",
        ],
    )

    class FailingFinalizeConnection:
        def __init__(self, wrapped) -> None:
            self._wrapped = wrapped

        def execute(self, sql: str, params=None):
            if "status = 'replayed'" in sql:
                raise RuntimeError("final replay update failed")
            if params is None:
                return self._wrapped.execute(sql)
            return self._wrapped.execute(sql, params)

    replayer = EventReplayer(
        FailingFinalizeConnection(connection),
        producer=lambda topic, message: produced_messages.append((topic, message)),
    )

    with pytest.raises(RuntimeError, match="final replay update failed"):
        replayer.replay(event_id)

    row = connection.execute(
        "SELECT status, retry_count FROM dead_letter_events WHERE event_id = ?",
        [event_id],
    ).fetchone()
    connection.close()

    assert produced_messages == [("events.raw", payload)]
    assert row == ("replay_pending", 1)
