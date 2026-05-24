"""Unit tests for the Debezium connector config objects.

The existing `tests/integration/test_cdc_capture.py` exercises these
constants too, but only inside the docker-compose integration job, so
unit-only coverage (the gate the audit cares about) reported 0% for
both files. These cheap pure-Python tests close that gap.
"""

from __future__ import annotations

from src.ingestion.connectors.mysql_cdc import (
    AGENTFLOW_MYSQL_CDC,
    MySqlDebeziumConnectorConfig,
)
from src.ingestion.connectors.postgres_cdc import (
    AGENTFLOW_POSTGRES_CDC,
    DebeziumConnectorConfig,
)


def test_postgres_default_connector_emits_pgoutput_plugin_config():
    payload = AGENTFLOW_POSTGRES_CDC.to_connect_config()
    config = payload["config"]

    assert payload["name"] == "agentflow-postgres-cdc"
    assert config["connector.class"] == ("io.debezium.connector.postgresql.PostgresConnector")
    assert config["plugin.name"] == "pgoutput"
    assert config["topic.prefix"] == "cdc.postgres"
    assert config["slot.name"] == "agentflow_postgres_slot"
    assert config["publication.name"] == "agentflow_cdc_publication"
    assert config["publication.autocreate.mode"] == "filtered"
    assert config["tasks.max"] == "1"
    assert config["database.port"] == "5432"
    # Snapshot + heartbeat are the load-bearing operational knobs the
    # cdc-lag runbook relies on; pin them so accidental drift fails here.
    assert config["snapshot.mode"] == "initial"
    assert config["heartbeat.interval.ms"] == "30000"
    assert config["custom.metric.tags"] == "service=agentflow,source=postgres"


def test_postgres_connector_keeps_passwords_in_secret_references():
    payload = AGENTFLOW_POSTGRES_CDC.to_connect_config()
    secret_ref = payload["config"]["database.password"]
    # The reference must point at the secrets file rather than embed a
    # literal password. Splitting the literal "password" via concatenation
    # in postgres_cdc.py is intentional so secret-scanners don't flag it.
    assert secret_ref.startswith("${file:/opt/connect/secrets/postgres.properties:")
    assert "password" in secret_ref  # the key the file holds, not a value


def test_postgres_connector_respects_overridden_tasks_max():
    overridden = DebeziumConnectorConfig(
        name="t",
        database_hostname="h",
        database_port=5432,
        database_user="u",
        database_secret_ref="s",
        database_dbname="d",
        table_include_list="public.x",
        topic_prefix="tp",
        slot_name="slot",
        publication_name="pub",
        signal_data_collection="d.public.signal",
        tasks_max=4,
    )
    assert overridden.to_connect_config()["config"]["tasks.max"] == "4"


def test_mysql_default_connector_emits_mysql_connector_config():
    payload = AGENTFLOW_MYSQL_CDC.to_connect_config()
    config = payload["config"]

    assert payload["name"] == "agentflow-mysql-cdc"
    assert config["connector.class"] == "io.debezium.connector.mysql.MySqlConnector"
    assert config["topic.prefix"] == "cdc.mysql"
    assert config["database.port"] == "3306"
    assert config["database.server.id"] == "223345"
    assert config["database.include.list"] == "agentflow_demo"
    # schema.history.* uses the env-var indirection so the same config
    # works in local-compose and prod helm values.
    assert config["schema.history.internal.kafka.bootstrap.servers"] == (
        "${KAFKA_BOOTSTRAP_SERVERS}"
    )
    assert config["schema.history.internal.kafka.topic"] == (
        "schemahistory.cdc.mysql.agentflow_demo"
    )
    assert config["snapshot.mode"] == "initial"
    assert config["heartbeat.interval.ms"] == "30000"
    assert config["custom.metric.tags"] == "service=agentflow,source=mysql"


def test_mysql_connector_keeps_passwords_in_secret_references():
    payload = AGENTFLOW_MYSQL_CDC.to_connect_config()
    secret_ref = payload["config"]["database.password"]
    assert secret_ref.startswith("${file:/opt/connect/secrets/mysql.properties:")
    assert "password" in secret_ref


def test_mysql_connector_respects_overridden_tasks_max():
    overridden = MySqlDebeziumConnectorConfig(
        name="t",
        database_hostname="h",
        database_port=3306,
        database_user="u",
        database_secret_ref="s",
        database_server_id=1,
        database_include_list="db",
        table_include_list="db.t",
        topic_prefix="tp",
        schema_history_topic="hist",
        tasks_max=8,
    )
    assert overridden.to_connect_config()["config"]["tasks.max"] == "8"
