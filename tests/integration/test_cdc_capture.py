import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from src.ingestion.connectors.mysql_cdc import AGENTFLOW_MYSQL_CDC
from src.ingestion.connectors.postgres_cdc import AGENTFLOW_POSTGRES_CDC

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ("-f", "docker-compose.yml", "-f", "docker-compose.cdc.yml")


def test_postgres_connector_config_matches_t25_topic_contract():
    payload = AGENTFLOW_POSTGRES_CDC.to_connect_config()

    assert payload["name"] == "agentflow-postgres-cdc"
    config = payload["config"]
    assert config["connector.class"] == "io.debezium.connector.postgresql.PostgresConnector"
    assert config["tasks.max"] == "1"
    assert config["database.dbname"] == "agentflow_demo"
    assert config["topic.prefix"] == "cdc.postgres"
    assert config["slot.name"] == "agentflow_postgres_slot"
    assert config["publication.name"] == "agentflow_cdc_publication"
    assert config["table.include.list"] == "public.orders_v2,public.users_enriched"
    assert config["signal.data.collection"] == "agentflow_demo.public.debezium_signal"
    assert config["key.converter.schemas.enable"] == "false"
    assert config["value.converter.schemas.enable"] == "false"
    assert "transforms" not in config


def test_mysql_connector_config_matches_t25_topic_contract():
    payload = AGENTFLOW_MYSQL_CDC.to_connect_config()

    assert payload["name"] == "agentflow-mysql-cdc"
    config = payload["config"]
    assert config["connector.class"] == "io.debezium.connector.mysql.MySqlConnector"
    assert config["tasks.max"] == "1"
    assert config["database.server.id"] == "223345"
    assert config["topic.prefix"] == "cdc.mysql"
    assert config["database.include.list"] == "agentflow_demo"
    assert (
        config["table.include.list"]
        == "agentflow_demo.products_current,agentflow_demo.sessions_aggregated"
    )
    assert config["schema.history.internal.kafka.topic"] == "schemahistory.cdc.mysql.agentflow_demo"
    assert config["key.converter.schemas.enable"] == "false"
    assert config["value.converter.schemas.enable"] == "false"


def _connect_ready() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8083/connectors", timeout=5) as response:
            return response.status == 200
    except OSError:
        return False


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *COMPOSE_FILES, *args],
        cwd=PROJECT_ROOT,
        check=check,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _consume_topic(topic: str) -> list[dict]:
    result = _compose(
        "exec",
        "-T",
        "kafka",
        "kafka-console-consumer",
        "--bootstrap-server",
        "kafka:9092",
        "--topic",
        topic,
        "--from-beginning",
        "--timeout-ms",
        "30000",
        "--max-messages",
        "20",
        check=False,
    )
    records = []
    for line in result.stdout.splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


@pytest.mark.integration
@pytest.mark.requires_docker
@pytest.mark.skipif(
    os.getenv("AGENTFLOW_RUN_CDC_DOCKER") != "1",
    reason="set AGENTFLOW_RUN_CDC_DOCKER=1 and start docker-compose.cdc.yml to run",
)
def test_cdc_compose_stack_captures_postgres_and_mysql_rows():
    if not _connect_ready():
        pytest.skip("Kafka Connect is not running on http://127.0.0.1:8083")

    suffix = str(int(time.time()))
    order_id = f"ORD-CDC-{suffix}"
    product_id = f"PROD-CDC-{suffix}"

    _compose(
        "exec",
        "-T",
        "postgres-source",
        "psql",
        "-U",
        "cdc_reader",
        "-d",
        "agentflow_demo",
        "-c",
        (
            "insert into orders_v2(order_id,user_id,status,total_amount,currency) "
            f"values ('{order_id}','USR-CDC-{suffix}','confirmed',42.50,'USD');"
        ),
    )
    _compose(
        "exec",
        "-T",
        "mysql-source",
        "mysql",
        "-ucdc_reader",
        "-pagentflow",
        "-D",
        "agentflow_demo",
        "-e",
        (
            "insert into products_current(product_id,name,category,price,in_stock,stock_quantity) "
            f"values ('{product_id}','CDC Widget','test',9.99,true,10);"
        ),
    )

    postgres_records = _consume_topic("cdc.postgres.public.orders_v2")
    mysql_records = _consume_topic("cdc.mysql.agentflow_demo.products_current")

    assert any(
        record.get("payload", {}).get("after", {}).get("order_id") == order_id
        and record.get("payload", {}).get("op") == "c"
        and record.get("payload", {}).get("source", {}).get("db") == "agentflow_demo"
        and record.get("payload", {}).get("source", {}).get("table") == "orders_v2"
        for record in postgres_records
    )
    assert any(
        record.get("payload", {}).get("after", {}).get("product_id") == product_id
        and record.get("payload", {}).get("op") == "c"
        and record.get("payload", {}).get("source", {}).get("db") == "agentflow_demo"
        and record.get("payload", {}).get("source", {}).get("table") == "products_current"
        for record in mysql_records
    )
