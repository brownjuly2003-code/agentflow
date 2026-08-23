"""MySQL CDC connector configuration for Debezium."""

import os
from dataclasses import dataclass

# Identifier of the password field inside the Kafka Connect external
# secret file (`${file:/path:<key>}` syntax). Not a credential — it's
# the property key name expected by Connect's FileConfigProvider.
_CONNECT_SECRET_KEY = "password"  # noqa: S105 - property key name, not a value
_MYSQL_SECRET_REF = f"${{file:/opt/connect/secrets/mysql.properties:{_CONNECT_SECRET_KEY}}}"

# Default Debezium MySQL replication server.id. Each running connector
# instance MUST advertise a unique value to MySQL — without an override
# two parallel instances pointing at the same source would collide on
# the replication stream. Override via AGENTFLOW_MYSQL_SERVER_ID.
DEFAULT_MYSQL_SERVER_ID = 223345


def _resolve_mysql_server_id() -> int:
    raw = os.getenv("AGENTFLOW_MYSQL_SERVER_ID")
    if raw is None or not raw.strip():
        return DEFAULT_MYSQL_SERVER_ID
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MYSQL_SERVER_ID


@dataclass(frozen=True)
class MySqlDebeziumConnectorConfig:
    """Generates Kafka Connect configuration for Debezium MySQL source."""

    name: str
    database_hostname: str
    database_port: int
    database_user: str
    database_secret_ref: str
    database_server_id: int
    database_include_list: str
    table_include_list: str
    topic_prefix: str
    schema_history_topic: str
    tasks_max: int = 1

    def to_connect_config(self) -> dict:
        return {
            "name": self.name,
            "config": {
                "connector.class": "io.debezium.connector.mysql.MySqlConnector",
                "tasks.max": str(self.tasks_max),
                "database.hostname": self.database_hostname,
                "database.port": str(self.database_port),
                "database.user": self.database_user,
                "database.password": self.database_secret_ref,
                "database.server.id": str(self.database_server_id),
                "topic.prefix": self.topic_prefix,
                "database.include.list": self.database_include_list,
                "table.include.list": self.table_include_list,
                "snapshot.mode": "initial",
                "heartbeat.interval.ms": "30000",
                "schema.history.internal.kafka.bootstrap.servers": "${KAFKA_BOOTSTRAP_SERVERS}",
                "schema.history.internal.kafka.topic": self.schema_history_topic,
                "key.converter": "org.apache.kafka.connect.json.JsonConverter",
                "value.converter": "org.apache.kafka.connect.json.JsonConverter",
                "key.converter.schemas.enable": "false",
                "value.converter.schemas.enable": "false",
                "custom.metric.tags": "service=agentflow,source=mysql",
            },
        }


AGENTFLOW_MYSQL_CDC = MySqlDebeziumConnectorConfig(
    name="agentflow-mysql-cdc",
    database_hostname="${file:/opt/connect/secrets/mysql.properties:hostname}",
    database_port=3306,
    database_user="${file:/opt/connect/secrets/mysql.properties:user}",
    database_secret_ref=_MYSQL_SECRET_REF,
    database_server_id=_resolve_mysql_server_id(),
    database_include_list="agentflow_demo",
    table_include_list="agentflow_demo.products_current,agentflow_demo.sessions_aggregated",
    topic_prefix="cdc.mysql",
    schema_history_topic="schemahistory.cdc.mysql.agentflow_demo",
)
