from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import duckdb
import pytest
import yaml

from src.processing.iceberg_sink import IcebergSink
from src.processing.local_pipeline import _ensure_tables, _process_event
from src.processing.transformations.enrichment import enrich_order
from src.quality.monitors.metrics_collector import HealthCollector

pytestmark = pytest.mark.integration


def _write_iceberg_config(
    path: Path,
    *,
    catalog_type: str = "sql",
    catalog_uri: str | None = None,
    warehouse: str | None = None,
    namespace: str = "agentflow",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path = path.parent.parent / "catalog.db"
    resolved_catalog_uri = catalog_uri or f"sqlite:///{catalog_path.as_posix()}"
    resolved_warehouse = warehouse or "../warehouse"
    path.write_text(
        yaml.safe_dump(
            {
                "iceberg": {
                    "catalog_type": catalog_type,
                    "catalog_uri": resolved_catalog_uri,
                    "warehouse": resolved_warehouse,
                    "namespace": namespace,
                    "tables": [
                        {"name": "orders", "partition_by": ["days(created_at)"]},
                        {"name": "payments", "partition_by": ["days(created_at)"]},
                        {"name": "clickstream", "partition_by": ["hours(created_at)"]},
                        {"name": "inventory", "partition_by": ["days(created_at)"]},
                        {"name": "dead_letter", "partition_by": ["days(received_at)"]},
                    ],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _write_repo_default_iceberg_config(path: Path, *, namespace: str) -> Path:
    repo_config = (
        Path(__file__).resolve().parents[2] / "config" / "iceberg.yaml"
    )
    payload = yaml.safe_load(repo_config.read_text(encoding="utf-8"))
    payload["iceberg"]["namespace"] = namespace
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _table_names(sink: IcebergSink) -> list[str]:
    return sorted(identifier[1] for identifier in sink.catalog.list_tables(sink.namespace))


def _wait_for_catalog(config_path: Path, timeout_seconds: int = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            IcebergSink(config_path=config_path).row_counts()
            return
        except Exception as exc:  # pragma: no cover - retry path
            last_error = exc
            time.sleep(1)
    pytest.fail(f"Iceberg catalog did not become ready: {last_error}")


@pytest.fixture
def iceberg_rest_catalog():
    compose_file = Path(__file__).resolve().parents[2] / "docker-compose.iceberg.yml"
    project_name = f"agentflow-iceberg-{uuid4().hex[:8]}"
    down_command = [
        "docker",
        "compose",
        "-p",
        project_name,
        "-f",
        str(compose_file),
        "down",
        "-v",
    ]
    subprocess.run(  # noqa: S603
        down_command,
        check=False,
        capture_output=True,
        text=True,
    )
    up_command = [
        "docker",
        "compose",
        "-p",
        project_name,
        "-f",
        str(compose_file),
        "up",
        "-d",
    ]
    completed = subprocess.run(  # noqa: S603
        up_command,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    try:
        yield project_name
    finally:
        subprocess.run(  # noqa: S603
            down_command,
            check=False,
            capture_output=True,
            text=True,
        )


def test_init_iceberg_script_creates_five_tables(tmp_path: Path) -> None:
    config_path = _write_iceberg_config(tmp_path / "config" / "iceberg.yaml")
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "init_iceberg.py"

    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(script_path), "--config", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    sink = IcebergSink(config_path=config_path)
    assert _table_names(sink) == [
        "clickstream",
        "dead_letter",
        "inventory",
        "orders",
        "payments",
    ]


def test_write_batch_appends_rows_and_reports_counts(
    tmp_path: Path,
    sample_order_event: dict,
) -> None:
    config_path = _write_iceberg_config(tmp_path / "config" / "iceberg.yaml")
    sink = IcebergSink(config_path=config_path)
    sink.create_tables_if_not_exist()

    written = sink.write_batch("orders", [enrich_order(dict(sample_order_event))])

    assert written == 1
    assert sink.row_counts()["orders"] == 1


def test_local_pipeline_writes_valid_orders_to_duckdb_and_iceberg(
    tmp_path: Path,
    sample_order_event: dict,
) -> None:
    config_path = _write_iceberg_config(tmp_path / "config" / "iceberg.yaml")
    db_path = tmp_path / "pipeline.duckdb"
    sink = IcebergSink(config_path=config_path)
    sink.create_tables_if_not_exist()

    conn = duckdb.connect(str(db_path))
    try:
        _ensure_tables(conn)
        success, reason = _process_event(conn, sample_order_event, iceberg_sink=sink)
    finally:
        conn.close()

    assert success is True, reason
    row = duckdb.connect(str(db_path)).execute("SELECT COUNT(*) FROM orders_v2").fetchone()
    assert row == (1,)
    assert sink.row_counts()["orders"] == 1


def test_invalid_events_land_in_dead_letter_iceberg_table(
    tmp_path: Path,
    sample_invalid_event: dict,
) -> None:
    config_path = _write_iceberg_config(tmp_path / "config" / "iceberg.yaml")
    db_path = tmp_path / "pipeline.duckdb"
    sink = IcebergSink(config_path=config_path)
    sink.create_tables_if_not_exist()

    conn = duckdb.connect(str(db_path))
    try:
        _ensure_tables(conn)
        success, reason = _process_event(conn, sample_invalid_event, iceberg_sink=sink)
    finally:
        conn.close()

    assert success is False
    assert reason.startswith("schema:")
    assert sink.row_counts()["dead_letter"] == 1


def test_health_collector_reports_iceberg_row_counts(
    tmp_path: Path,
    sample_order_event: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_iceberg_config(tmp_path / "config" / "iceberg.yaml")
    sink = IcebergSink(config_path=config_path)
    sink.create_tables_if_not_exist()
    sink.write_batch("orders", [enrich_order(dict(sample_order_event))])
    monkeypatch.setenv("AGENTFLOW_ICEBERG_CONFIG", str(config_path))

    health = HealthCollector().collect().to_dict()
    iceberg = next(
        component
        for component in health["components"]
        if component["name"] == "iceberg"
    )

    assert iceberg["source"] == "live"
    assert iceberg["metrics"]["row_counts"]["orders"] == 1


@pytest.mark.requires_docker
def test_repo_default_config_writes_to_rest_catalog(
    tmp_path: Path,
    sample_order_event: dict,
    iceberg_rest_catalog: str,
) -> None:
    namespace = f"agentflow_rest_{uuid4().hex[:8]}"
    repo_config = _write_repo_default_iceberg_config(
        tmp_path / "config" / "iceberg.yaml",
        namespace=namespace,
    )
    rest_config = _write_iceberg_config(
        tmp_path / "config" / "rest.yaml",
        catalog_type="rest",
        catalog_uri="http://localhost:8181",
        warehouse="/warehouse",
        namespace=namespace,
    )

    _wait_for_catalog(rest_config)

    sink = IcebergSink(config_path=repo_config)
    sink.create_tables_if_not_exist()
    sink.write_batch("orders", [enrich_order(dict(sample_order_event))])

    rest_sink = IcebergSink(config_path=rest_config)

    assert iceberg_rest_catalog
    assert rest_sink.row_counts()["orders"] == 1
